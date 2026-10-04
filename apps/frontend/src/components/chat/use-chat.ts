"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { useGate } from "@/components/providers/gate-provider";
import { useSession } from "@/components/providers/session-provider";
import { hasRevealProgress } from "@/components/ui/smooth-reveal";
import { announce } from "@/lib/a11y";
import { ApiError, reportApiError } from "@/lib/api/errors";
import {
  cancelChatRun,
  deleteChatSession,
  getChatSession,
  getProfile,
  listChatRuns,
  listChatSessions,
  listConsents,
  putProfile,
  unwrap,
} from "@/lib/api";
import { streamSSE } from "@/lib/api/sse";

import {
  emptyReply,
  toTurnChips,
  type AssistantTurn,
  type ChatEvent,
  type ChatSession,
  type HintKey,
  type PatientProfile,
  type Schemas,
  type Turn,
  type TurnChip,
  type TurnError,
} from "./types";

/**
 * No event for this long means the turn is stuck. The server answers within its 90 s turn
 * deadline (a normal turn takes about 30 s) and the longest silent stretch is one model call,
 * so this waits past that deadline: the server's own answer or error always arrives first.
 */
export const STREAM_IDLE_TIMEOUT_MS = 100_000;

let seq = 0;
const nextId = (p: string) => `${p}-${Date.now().toString(36)}-${(seq++).toString(36)}`;

/**
 * The conversation this tab used last, so the dock and the full page (and a remount) pick up
 * the same one, including a turn still running on the server. In memory only, never in a URL
 * or browser storage (docs/compliance.md); a reload finds a running turn via `listChatRuns`.
 */
let lastConversation: { userId: string; sessionId: string } | null = null;

/** Why a follow stream was aborted: the user stopped the turn, the view let go, or no event came. */
type AbortReason = "stop" | "detach" | "timeout";
/** A follow stream may end early (network, server restart) this often per turn before giving up. */
const MAX_RECOVERIES = 2;

type Source =
  | { kind: "send"; text: string; retryOf?: string }
  | { kind: "attach"; runId: string; after: number };

type SessionsState = { status: "loading" | "ready" | "unavailable"; items: ChatSession[] };

function profileKey(chip: Pick<TurnChip, "type" | "id" | "label" | "negated">) {
  return `${chip.type}:${chip.id ?? chip.label}`;
}

/** Add or remove one confirmed chip in a PatientProfile (only the fields it allows). */
export function applyChipToProfile(
  profile: PatientProfile,
  chip: TurnChip,
  add: boolean,
): PatientProfile {
  const now = new Date().toISOString();
  const next: PatientProfile = {
    ...profile,
    diseases: [...(profile.diseases ?? [])],
    genes: [...(profile.genes ?? [])],
    variants: [...(profile.variants ?? [])],
    phenotypes: [...(profile.phenotypes ?? [])],
  };
  const id = chip.id ?? "";
  switch (chip.type) {
    case "disease":
      next.diseases = next.diseases!.filter((d) => d.id !== id);
      if (add) next.diseases.push({ id, label: chip.label, source: "chat", confirmed_at: now });
      break;
    case "gene":
      next.genes = next.genes!.filter((g) => g.id !== id);
      if (add) next.genes.push({ id, label: chip.label, source: "chat", confirmed_at: now });
      break;
    case "variant": {
      const hgvs = /[cgmnpr]\.\S/.test(chip.label) ? chip.label : null;
      next.variants = next.variants!.filter((v) => (id ? v.clinvar_id !== id : v.hgvs !== hgvs));
      if (add) next.variants.push({ clinvar_id: id || null, hgvs, source: "chat", confirmed_at: now });
      break;
    }
    case "symptom":
      next.phenotypes = next.phenotypes!.filter((p) => p.id !== id);
      if (add) next.phenotypes.push({ id, label: chip.label, excluded: chip.negated, source: "chat", confirmed_at: now });
      break;
  }
  return next;
}

/** Write one profile hint (age, onset or country) into a PatientProfile. */
export function applyHintToProfile(profile: PatientProfile, hints: Schemas.ProfileHints, key: HintKey): PatientProfile {
  switch (key) {
    case "age":
      return hints.age_years != null
        ? { ...profile, age_years: hints.age_years, age_range: null }
        : { ...profile, age_range: hints.age_range ?? null, age_years: null };
    case "onset":
      return { ...profile, onset: hints.onset ?? null };
    case "country":
      return { ...profile, country: hints.country ?? null };
  }
}

/** A profile with nothing in it yet has no "whose data is this" decision either. */
function isEmptyProfile(p: PatientProfile) {
  return (
    !p.diseases?.length &&
    !p.genes?.length &&
    !p.variants?.length &&
    !p.phenotypes?.length &&
    p.age_years == null &&
    !p.age_range &&
    !p.onset &&
    !p.country &&
    !p.about_child
  );
}

function turnsFromHistory(messages: Schemas.ChatMessage[]): Turn[] {
  return messages.map((m, i): Turn => {
    if (m.role === "user") return { id: m.id, kind: "user", text: m.content };
    if (m.error) {
      // A stored failed turn: shown as the live view showed it (steps, error, "Try again").
      const asked = messages[i - 1]?.role === "user" ? messages[i - 1] : undefined;
      return {
        id: m.id,
        kind: "assistant",
        phase: "error",
        statuses: m.error.steps.map((s) => ({ tool: s.tool, message: s.message })),
        final: false,
        followUpDone: true,
        reply: emptyReply(),
        error: { code: m.error.code, message: m.error.message },
        request: asked?.content,
        userMessageId: asked?.id,
      };
    }
    const reply = m.reply;
    // A reply this tab was still revealing (the dock, then the full page) continues; any other stored reply shows at once.
    const askedId = messages[i - 1]?.role === "user" ? messages[i - 1].id : undefined;
    return {
      id: m.id,
      kind: "assistant",
      phase: "done",
      statuses: [],
      final: true,
      followUpDone: true,
      userMessageId: askedId,
      live: hasRevealProgress(askedId),
      reply: reply
        ? { ...reply, chips: toTurnChips(reply.chips) }
        : { ...emptyReply(), summary: m.content },
    };
  });
}

function errorFrom(e: unknown): TurnError {
  if (e instanceof ApiError) return { code: e.code, message: e.message };
  return { code: "network_error", message: "The connection was interrupted." };
}

export function useChat({ expertMode }: { expertMode: boolean }) {
  const { openSignIn } = useGate();
  const userId = useSession().user?.id ?? null;
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionsState>({ status: "loading", items: [] });
  const [loadingSession, setLoadingSession] = useState(false);
  const ctrlRef = useRef<AbortController | null>(null);
  const sessionRef = useRef<string | null>(null);
  const profileRef = useRef<PatientProfile | null>(null);
  /** The server run of the turn on screen; stopping cancels it there. */
  const runRef = useRef<{ runId: string | null; turnId: string; stopRequested?: boolean } | null>(null);
  const cancelling = useRef<Promise<unknown> | null>(null);
  const recoveries = useRef(0);
  /** The user acted (sent, opened, started anew) before the automatic resume finished. */
  const touched = useRef(false);
  /** Counts resumes of a turn still running, so a view can reveal it (the dock opens). */
  const [resumed, setResumed] = useState(0);

  useEffect(() => {
    sessionRef.current = sessionId;
    if (sessionId && userId) lastConversation = { userId, sessionId };
  }, [sessionId, userId]);

  const streaming = turns.some((t) => t.kind === "assistant" && t.phase === "streaming");

  const updateTurn = useCallback((id: string, fn: (t: AssistantTurn) => AssistantTurn) => {
    setTurns((all) => all.map((t) => (t.id === id && t.kind === "assistant" ? fn(t) : t)));
  }, []);

  const refreshSessions = useCallback(async () => {
    try {
      const items = await unwrap(listChatSessions({ meta: { quiet: true }, cache: "no-store" }));
      setSessions({ status: "ready", items: Array.isArray(items) ? items : [] });
    } catch {
      setSessions((s) => ({ status: s.items.length ? "ready" : "unavailable", items: s.items }));
    }
  }, []);

  useEffect(() => {
    // Initial load; state is set after the awaited fetch.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshSessions();
  }, [refreshSessions]);

  // Stop following when the chat really unmounts. Deferred, because Strict Mode's simulated
  // unmount/remount must not drop the first turn. The turn itself keeps running on the server.
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      setTimeout(() => {
        if (!mounted.current) ctrlRef.current?.abort("detach");
      }, 0);
    };
  }, []);

  const cancelRun = useCallback((runId: string) => {
    cancelling.current = unwrap(cancelChatRun({ path: { run_id: runId }, meta: { quiet: true } }))
      .catch(() => undefined)
      .finally(() => {
        cancelling.current = null;
      });
  }, []);

  const handleEvent = useCallback(
    (turnId: string, e: ChatEvent) => {
      switch (e.type) {
        case "status":
          updateTurn(turnId, (t) => ({ ...t, statuses: [...t.statuses, { tool: e.tool, message: e.message }] }));
          return;
        case "turn":
          // The message is stored: a retry from now on reruns it instead of storing it again.
          updateTurn(turnId, (t) => ({ ...t, userMessageId: e.message_id }));
          if (e.session_id !== sessionRef.current) {
            sessionRef.current = e.session_id;
            setSessionId(e.session_id);
          }
          if (runRef.current?.turnId === turnId && e.run_id) {
            runRef.current.runId = e.run_id;
            if (runRef.current.stopRequested) {
              // Stop was pressed before the run was known: cancel it now, stop following.
              cancelRun(e.run_id);
              ctrlRef.current?.abort("stop");
            }
          }
          return;
        case "uncertainty":
          // Sent before the summary so the uncertainty line leads the reply.
          updateTurn(turnId, (t) => ({ ...t, reply: { ...t.reply, uncertainty: e.text } }));
          return;
        case "summary_delta":
          updateTurn(turnId, (t) => ({ ...t, reply: { ...t.reply, summary: t.reply.summary + e.text } }));
          return;
        case "chips":
          updateTurn(turnId, (t) => ({ ...t, reply: { ...t.reply, chips: toTurnChips(e.chips, t.reply.chips) } }));
          return;
        case "claims":
          updateTurn(turnId, (t) => ({
            ...t,
            reply: { ...t.reply, claims: e.claims, contradictions: e.contradictions ?? t.reply.contradictions },
          }));
          return;
        case "cards":
          updateTurn(turnId, (t) => ({ ...t, reply: { ...t.reply, cards: e.cards } }));
          return;
        case "actions":
          updateTurn(turnId, (t) => ({ ...t, reply: { ...t.reply, actions: e.actions } }));
          return;
        case "follow_up":
          updateTurn(turnId, (t) => ({ ...t, reply: { ...t.reply, follow_up: e.follow_up } }));
          return;
        case "final": {
          const r = e.reply;
          recoveries.current = 0;
          updateTurn(turnId, (t) => ({
            ...t,
            phase: "done",
            final: true,
            reply: { ...r, chips: toTurnChips(r.chips, t.reply.chips) },
          }));
          if (e.session_id && e.session_id !== sessionRef.current) {
            sessionRef.current = e.session_id;
            setSessionId(e.session_id);
          }
          announce(`Dr. Wu replied. ${r.uncertainty ? `${r.uncertainty} ` : ""}${r.summary}`);
          void refreshSessions();
          return;
        }
        case "error":
          recoveries.current = 0;
          updateTurn(turnId, (t) => ({ ...t, phase: "error", error: { code: e.code, message: e.message } }));
          if (e.code === "reauth_required" || e.code === "sign_in_required") {
            openSignIn("Your sign-in has expired. Sign in again to continue the conversation.");
          }
          announce(`Dr. Wu could not finish: ${e.message}`, "assertive");
          void refreshSessions();
          return;
      }
    },
    [updateTurn, refreshSessions, openSignIn, cancelRun],
  );

  /** Set by `openSession` below; a cut stream calls it to show the turn as far as it got. */
  const recoverRef = useRef<(turnId: string) => void>(() => {});

  /**
   * Follow a turn: send a message (POST /chat starts a run and streams it) or attach to a run
   * (replays its events after `after`, then live). Attaching never sends the message again.
   */
  const follow = useCallback(
    async (turnId: string, source: Source) => {
      ctrlRef.current?.abort("detach");
      const ctrl = new AbortController();
      ctrlRef.current = ctrl;
      let watchdog: ReturnType<typeof setTimeout> | undefined;
      const arm = () => {
        clearTimeout(watchdog);
        watchdog = setTimeout(() => ctrl.abort("timeout"), STREAM_IDLE_TIMEOUT_MS);
      };
      arm();
      let ended = false;
      try {
        if (source.kind === "send") {
          announce("Dr. Wu is working on your question.");
          if (cancelling.current) await cancelling.current;
          runRef.current = { runId: null, turnId };
          await streamSSE<ChatEvent>("/chat", {
            json: {
              message: source.text,
              session_id: sessionRef.current,
              expert_mode: expertMode,
              ...(source.retryOf && sessionRef.current ? { retry_message_id: source.retryOf } : {}),
            },
            signal: ctrl.signal,
            quiet: true,
            onEvent: (e) => {
              arm();
              // Stopped before the run was known: only the `turn` event (to cancel it) counts.
              if (runRef.current?.turnId === turnId && runRef.current.stopRequested && e.type !== "turn") return;
              if (e.type === "final" || e.type === "error") ended = true;
              handleEvent(turnId, e);
            },
          });
        } else {
          runRef.current = { runId: source.runId, turnId };
          await streamSSE<ChatEvent>(`/chat/runs/${source.runId}/events`, {
            method: "GET",
            query: { after: source.after },
            signal: ctrl.signal,
            quiet: true,
            onEvent: (e) => {
              arm();
              if (e.type === "final" || e.type === "error") ended = true;
              handleEvent(turnId, e);
            },
          });
        }
        if (ended) return;
        const reason = ctrl.signal.aborted ? (ctrl.signal.reason as AbortReason) : null;
        if (reason === "detach") return; // another view or conversation took over
        if (reason === "stop") {
          updateTurn(turnId, (t) => (t.phase === "streaming" ? { ...t, phase: "stopped" } : t));
          return;
        }
        if (reason === "timeout") {
          updateTurn(turnId, (t) =>
            t.phase === "streaming" ? { ...t, phase: "error", error: { code: "timeout", message: "No answer arrived in time." } } : t,
          );
          return;
        }
        // The stream was cut while the turn runs on: pick it up again from the server.
        if (sessionRef.current && recoveries.current < MAX_RECOVERIES) {
          recoveries.current += 1;
          recoverRef.current(turnId);
          return;
        }
        updateTurn(turnId, (t) =>
          t.phase === "streaming"
            ? { ...t, phase: "error", error: { code: "network_error", message: "The answer stopped before it was complete." } }
            : t,
        );
      } catch (e) {
        const err = errorFrom(e);
        if (source.kind === "attach" && err.code === "not_found" && sessionRef.current) {
          // The run is over: the session holds its reply or failed turn.
          recoverRef.current(turnId);
          return;
        }
        updateTurn(turnId, (t) => ({ ...t, phase: "error", error: err }));
        if (err.code === "sign_in_required" || err.code === "reauth_required") {
          openSignIn("Sign in again to continue the conversation with Dr. Wu.");
        } else if ((err.code === "age_confirmation_required" || err.code === "consent_required") && e instanceof ApiError) {
          // Opens the welcome step or the consent dialog; "Try again" resends the kept text.
          reportApiError(e);
        }
        announce(`Dr. Wu could not answer. ${err.message}`, "assertive");
      } finally {
        clearTimeout(watchdog);
        if (ctrlRef.current === ctrl) ctrlRef.current = null;
      }
    },
    [expertMode, handleEvent, updateTurn, openSignIn],
  );

  const send = useCallback(
    (raw: string) => {
      const text = raw.trim();
      if (!text) return;
      const assistantId = nextId("a");
      setTurns((all) => [
        ...all.map((t) => (t.kind === "assistant" ? { ...t, followUpDone: true } : t)),
        { id: nextId("u"), kind: "user", text },
        { id: assistantId, kind: "assistant", phase: "streaming", statuses: [], reply: emptyReply(), final: false, request: text, live: true },
      ]);
      touched.current = true;
      recoveries.current = 0;
      void follow(assistantId, { kind: "send", text });
    },
    [follow],
  );

  const retry = useCallback(
    (turnId: string) => {
      const turn = turns.find((t) => t.id === turnId);
      if (!turn || turn.kind !== "assistant" || !turn.request) return;
      updateTurn(turnId, (t) => ({ ...t, phase: "streaming", statuses: [], reply: emptyReply(), final: false, error: undefined, live: true }));
      recoveries.current = 0;
      void follow(turnId, { kind: "send", text: turn.request, retryOf: turn.userMessageId });
    },
    [turns, follow, updateTurn],
  );

  /** Stop the answer: the run is cancelled on the server (stored as an interrupted turn). */
  const stop = useCallback(() => {
    const run = runRef.current;
    if (run?.runId) {
      cancelRun(run.runId);
      ctrlRef.current?.abort("stop");
    } else if (run) {
      // The run id arrives with the `turn` event; cancel it then.
      run.stopRequested = true;
      updateTurn(run.turnId, (t) => (t.phase === "streaming" ? { ...t, phase: "stopped" } : t));
    }
  }, [cancelRun, updateTurn]);

  const newConversation = useCallback(() => {
    // A running turn goes on in its own conversation on the server.
    ctrlRef.current?.abort("detach");
    touched.current = true;
    runRef.current = null;
    lastConversation = null;
    setTurns([]);
    setSessionId(null);
    sessionRef.current = null;
  }, []);

  /**
   * Show a stored conversation and, if a turn is still running in it, attach to that run: its
   * events replay from the start into a fresh turn, so it shows as far as it got.
   */
  const loadSession = useCallback(
    async (id: string, opts: { auto?: boolean; recoverTurn?: string } = {}) => {
      ctrlRef.current?.abort("detach");
      if (!opts.auto && !opts.recoverTurn) touched.current = true;
      setLoadingSession(true);
      try {
        const detail = await unwrap(getChatSession({ path: { session_id: id }, meta: { quiet: true }, cache: "no-store" }));
        if (opts.auto && touched.current) return; // the user moved on meanwhile
        const history = turnsFromHistory(detail.messages ?? []);
        const run = detail.run;
        let attach: { turnId: string; runId: string } | null = null;
        if (run) {
          const asked = [...(detail.messages ?? [])].reverse().find((m) => m.id === run.message_id);
          const turnId = nextId("a");
          history.forEach((t) => {
            if (t.kind === "assistant") t.followUpDone = true;
          });
          history.push({
            id: turnId,
            kind: "assistant",
            phase: "streaming",
            statuses: [],
            reply: emptyReply(),
            final: false,
            request: asked?.content,
            userMessageId: run.message_id,
            live: true,
          });
          attach = { turnId, runId: run.id };
        }
        setTurns(history);
        setSessionId(id);
        sessionRef.current = id;
        if (attach) {
          void follow(attach.turnId, { kind: "attach", runId: attach.runId, after: 0 });
          if (opts.auto) setResumed((n) => n + 1);
        }
        if (!opts.auto && !opts.recoverTurn) announce("Conversation opened.");
      } catch {
        if (opts.recoverTurn) {
          updateTurn(opts.recoverTurn, (t) =>
            t.phase === "streaming"
              ? { ...t, phase: "error", error: { code: "network_error", message: "The answer stopped before it was complete." } }
              : t,
          );
        } else if (opts.auto) {
          if (lastConversation?.sessionId === id) lastConversation = null;
        } else {
          toast("That conversation could not be opened", { description: "Please try again in a moment." });
        }
      } finally {
        setLoadingSession(false);
      }
    },
    [follow, updateTurn],
  );

  useEffect(() => {
    recoverRef.current = (turnId: string) => {
      if (sessionRef.current) void loadSession(sessionRef.current, { recoverTurn: turnId });
    };
  }, [loadSession]);

  const openSession = useCallback((id: string) => loadSession(id), [loadSession]);

  // On mount: pick up this tab's conversation (a view switch), else a turn still running on
  // the server (a reload). Nothing is sent again.
  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    void (async () => {
      let id = lastConversation?.userId === userId ? lastConversation.sessionId : null;
      if (!id) {
        try {
          const running = await unwrap(listChatRuns({ meta: { quiet: true }, cache: "no-store" }));
          id = Array.isArray(running) && running.length ? running[0].session_id : null;
        } catch {
          id = null;
        }
      }
      if (!id || cancelled || touched.current) return;
      await loadSession(id, { auto: true });
    })();
    return () => {
      cancelled = true;
    };
  }, [userId, loadSession]);

  const deleteSession = useCallback(
    async (id: string) => {
      try {
        await unwrap(deleteChatSession({ path: { session_id: id }, meta: { quiet: true } }));
        setSessions((s) => ({ ...s, items: s.items.filter((x) => x.id !== id) }));
        if (sessionRef.current === id) newConversation();
        announce("Conversation deleted.");
        toast("Conversation deleted");
      } catch {
        toast("The conversation could not be deleted", { description: "Please try again in a moment." });
      }
    },
    [newConversation],
  );

  const dismissFollowUp = useCallback(
    (turnId: string) => updateTurn(turnId, (t) => ({ ...t, followUpDone: true })),
    [updateTurn],
  );

  // ---- chips → PatientProfile -------------------------------------------

  const loadProfile = useCallback(async (): Promise<PatientProfile> => {
    try {
      profileRef.current = (await unwrap(getProfile({ meta: { quiet: true }, cache: "no-store" }))) ?? {};
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) profileRef.current = {};
      else throw e;
    }
    return profileRef.current!;
  }, []);

  const setChip = useCallback(
    (turnId: string, index: number, patch: Partial<TurnChip>) =>
      updateTurn(turnId, (t) => ({
        ...t,
        reply: { ...t.reply, chips: t.reply.chips.map((c, i) => (i === index ? { ...c, ...patch } : c)) },
      })),
    [updateTurn],
  );

  /**
   * Whose data the health-data consent was given for (own, or a child with
   * parental responsibility confirmed). compliance.md, Children: the first
   * save into an empty profile carries that answer, so it is asked only once.
   */
  const consentSubject = useCallback(async (): Promise<Pick<PatientProfile, "about_child" | "parental_responsibility_confirmed">> => {
    try {
      const list = await unwrap(listConsents({ meta: { quiet: true }, cache: "no-store" }));
      const c = (list ?? []).find((x) => x.consent_type === "health_data" && x.active);
      if (c?.about_child && c.parental_responsibility_confirmed) {
        return { about_child: true, parental_responsibility_confirmed: true };
      }
    } catch {
      /* fall back to "own data" */
    }
    return { about_child: false, parental_responsibility_confirmed: false };
  }, []);

  /**
   * Read the profile, apply `change`, write it. `PUT /profile` is
   * optimistically locked on `updated_at`: on a 409 conflict read again and
   * retry once.
   */
  const saveProfile = useCallback(
    async (change: (p: PatientProfile) => PatientProfile) => {
      for (let attempt = 0; ; attempt++) {
        const current = await loadProfile();
        let next = change(current);
        if (isEmptyProfile(current) && !next.about_child) next = { ...next, ...(await consentSubject()) };
        try {
          const saved = await unwrap(putProfile({ body: next, meta: { quiet: true } }));
          profileRef.current = saved && typeof saved === "object" ? saved : next;
          return profileRef.current;
        } catch (e) {
          if (attempt === 0 && e instanceof ApiError && (e.code === "conflict" || e.status === 409)) continue;
          throw e;
        }
      }
    },
    [loadProfile, consentSubject],
  );

  /** Save `chip` into (add) or out of (remove) the profile. */
  const persistChip = useCallback(
    async (chip: TurnChip, add: boolean) => {
      await saveProfile((p) => applyChipToProfile(p, chip, add));
    },
    [saveProfile],
  );

  const chipFailed = useCallback(
    (e: unknown) => {
      const err = errorFrom(e);
      if (err.code === "sign_in_required" || err.code === "reauth_required") openSignIn();
      if (err.code === "consent_required" && e instanceof ApiError) reportApiError(e);
      toast("Your profile was not updated", {
        description:
          err.code === "not_implemented"
            ? "Saving to the profile is not available yet."
            : err.code === "validation_error"
              ? "This item cannot be saved as it is. Try correcting it."
              : "Please try again in a moment.",
      });
    },
    [openSignIn],
  );

  const findChip = (turnId: string, index: number) => {
    const t = turns.find((x) => x.id === turnId);
    return t && t.kind === "assistant" ? t.reply.chips[index] : undefined;
  };

  const confirmChip = useCallback(
    async (turnId: string, index: number) => {
      const chip = findChip(turnId, index);
      if (!chip || !chip.id) return;
      setChip(turnId, index, { saving: true });
      try {
        await persistChip(chip, true);
        setChip(turnId, index, { state: "confirmed", confirmed: true, saving: false });
        announce(`${chip.label} added to your profile.`);
      } catch (e) {
        setChip(turnId, index, { saving: false });
        chipFailed(e);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [turns, persistChip, setChip, chipFailed],
  );

  const removeChip = useCallback(
    async (turnId: string, index: number) => {
      const chip = findChip(turnId, index);
      if (!chip) return;
      if (chip.state !== "confirmed") {
        setChip(turnId, index, { state: "removed" });
        announce(`${chip.label} removed.`);
        return;
      }
      setChip(turnId, index, { saving: true });
      try {
        await persistChip(chip, false);
        setChip(turnId, index, { state: "removed", confirmed: false, saving: false });
        announce(`${chip.label} removed from your profile.`);
      } catch (e) {
        setChip(turnId, index, { saving: false });
        chipFailed(e);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [turns, persistChip, setChip, chipFailed],
  );

  const undoRemove = useCallback(
    (turnId: string, index: number) => setChip(turnId, index, { state: "pending" }),
    [setChip],
  );

  /** Replace a chip with an entity the user picked from search, and confirm it. */
  const correctChip = useCallback(
    async (turnId: string, index: number, pick: { id: string; label: string }) => {
      const chip = findChip(turnId, index);
      if (!chip) return;
      const corrected: TurnChip = { ...chip, id: pick.id, label: pick.label, state: "pending" };
      setChip(turnId, index, { ...corrected, saving: true });
      try {
        // Drop the wrong item if it had been confirmed, then add the right one.
        if (chip.state === "confirmed" && chip.id && profileKey(chip) !== profileKey(corrected)) {
          await persistChip(chip, false);
        }
        await persistChip(corrected, true);
        setChip(turnId, index, { state: "confirmed", confirmed: true, saving: false });
        announce(`Corrected to ${pick.label} and added to your profile.`);
      } catch (e) {
        setChip(turnId, index, { saving: false });
        chipFailed(e);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [turns, persistChip, setChip, chipFailed],
  );

  const setHint = useCallback(
    (turnId: string, key: HintKey, decision: "saving" | "confirmed" | "dismissed" | undefined) =>
      updateTurn(turnId, (t) => ({ ...t, hintState: { ...t.hintState, [key]: decision } })),
    [updateTurn],
  );

  /** Confirm one profile hint (age, onset, country) into the profile. */
  const confirmHint = useCallback(
    async (turnId: string, key: HintKey) => {
      const t = turns.find((x) => x.id === turnId);
      const hints = t && t.kind === "assistant" ? t.reply.profile_hints : null;
      if (!hints) return;
      setHint(turnId, key, "saving");
      try {
        await saveProfile((p) => applyHintToProfile(p, hints, key));
        setHint(turnId, key, "confirmed");
        announce("Added to your profile.");
      } catch (e) {
        setHint(turnId, key, undefined);
        chipFailed(e);
      }
    },
    [turns, saveProfile, setHint, chipFailed],
  );

  const dismissHint = useCallback(
    (turnId: string, key: HintKey) => setHint(turnId, key, "dismissed"),
    [setHint],
  );

  /** Whether the stored profile already says it describes a child (null: unknown yet). */
  const [profileAboutChild, setProfileAboutChild] = useState<boolean | null>(null);
  const suspectsChild = turns.some(
    (t) => t.kind === "assistant" && t.final && t.reply.profile_hints?.about_child_suspected && !t.childOfferDone,
  );
  useEffect(() => {
    if (!suspectsChild || profileAboutChild !== null) return;
    // An empty profile takes its answer from the consent (asked there already).
    loadProfile()
      .then(async (p) => setProfileAboutChild(isEmptyProfile(p) ? !!(await consentSubject()).about_child : !!p.about_child))
      .catch(() => setProfileAboutChild(null));
  }, [suspectsChild, profileAboutChild, loadProfile, consentSubject]);

  /** The user says the profile is about a child they hold parental responsibility for. */
  const markAboutChild = useCallback(
    async (turnId: string) => {
      try {
        await saveProfile((p) => ({ ...p, about_child: true, parental_responsibility_confirmed: true }));
        setProfileAboutChild(true);
        updateTurn(turnId, (t) => ({ ...t, childOfferDone: true }));
        announce("Your profile now says it is about a child you care for.");
      } catch (e) {
        chipFailed(e);
      }
    },
    [saveProfile, updateTurn, chipFailed],
  );

  const dismissChildOffer = useCallback(
    (turnId: string) => updateTurn(turnId, (t) => ({ ...t, childOfferDone: true })),
    [updateTurn],
  );

  return {
    profileAboutChild,
    confirmHint,
    dismissHint,
    markAboutChild,
    dismissChildOffer,
    turns,
    sessionId,
    sessions,
    streaming,
    resumed,
    loadingSession,
    send,
    stop,
    retry,
    newConversation,
    openSession,
    deleteSession,
    dismissFollowUp,
    confirmChip,
    removeChip,
    undoRemove,
    correctChip,
  };
}

export type ChatController = ReturnType<typeof useChat>;
