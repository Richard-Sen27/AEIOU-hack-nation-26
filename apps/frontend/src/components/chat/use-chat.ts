"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { useGate } from "@/components/providers/gate-provider";
import { announce } from "@/lib/a11y";
import { ApiError, reportApiError } from "@/lib/api/errors";
import { apiFetch } from "@/lib/api/fetch";
import { streamSSE } from "@/lib/api/sse";

import {
  emptyReply,
  toTurnChips,
  type AssistantTurn,
  type ChatEvent,
  type ChatSession,
  type PatientProfile,
  type Schemas,
  type Turn,
  type TurnChip,
  type TurnError,
} from "./types";

/** No event for this long means the turn is stuck (the server caps a turn at 30 s). */
export const STREAM_IDLE_TIMEOUT_MS = 60_000;

let seq = 0;
const nextId = (p: string) => `${p}-${Date.now().toString(36)}-${(seq++).toString(36)}`;

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

function turnsFromHistory(messages: Schemas.ChatMessage[]): Turn[] {
  return messages.map((m): Turn => {
    if (m.role === "user") return { id: m.id, kind: "user", text: m.content };
    const reply = m.reply;
    return {
      id: m.id,
      kind: "assistant",
      phase: "done",
      statuses: [],
      final: true,
      followUpDone: true,
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
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionsState>({ status: "loading", items: [] });
  const [loadingSession, setLoadingSession] = useState(false);
  const ctrlRef = useRef<AbortController | null>(null);
  const timedOut = useRef(false);
  const sessionRef = useRef<string | null>(null);
  const profileRef = useRef<PatientProfile | null>(null);

  useEffect(() => {
    sessionRef.current = sessionId;
  }, [sessionId]);

  const streaming = turns.some((t) => t.kind === "assistant" && t.phase === "streaming");

  const updateTurn = useCallback((id: string, fn: (t: AssistantTurn) => AssistantTurn) => {
    setTurns((all) => all.map((t) => (t.id === id && t.kind === "assistant" ? fn(t) : t)));
  }, []);

  const refreshSessions = useCallback(async () => {
    try {
      const items = await apiFetch<ChatSession[]>("/chat/sessions", { quiet: true, cache: "no-store" });
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

  // Abort a running answer when the chat really unmounts. Deferred, because
  // Strict Mode's simulated unmount/remount must not cancel the first turn.
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      setTimeout(() => {
        if (!mounted.current) ctrlRef.current?.abort();
      }, 0);
    };
  }, []);

  const handleEvent = useCallback(
    (turnId: string, e: ChatEvent) => {
      switch (e.type) {
        case "status":
          updateTurn(turnId, (t) => ({ ...t, statuses: [...t.statuses, { tool: e.tool, message: e.message }] }));
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
          updateTurn(turnId, (t) => ({ ...t, phase: "error", error: { code: e.code, message: e.message } }));
          if (e.code === "reauth_required" || e.code === "sign_in_required") {
            openSignIn("Your ChatGPT sign-in has expired. Sign in again to continue the conversation.");
          }
          announce(`Dr. Wu could not finish: ${e.message}`, "assertive");
          return;
      }
    },
    [updateTurn, refreshSessions, openSignIn],
  );

  const run = useCallback(
    async (turnId: string, text: string) => {
      ctrlRef.current?.abort();
      const ctrl = new AbortController();
      ctrlRef.current = ctrl;
      timedOut.current = false;
      let watchdog: ReturnType<typeof setTimeout> | undefined;
      const arm = () => {
        clearTimeout(watchdog);
        watchdog = setTimeout(() => {
          timedOut.current = true;
          ctrl.abort();
        }, STREAM_IDLE_TIMEOUT_MS);
      };
      arm();
      announce("Dr. Wu is working on your question.");
      try {
        await streamSSE<ChatEvent>("/chat", {
          json: { message: text, session_id: sessionRef.current, expert_mode: expertMode },
          signal: ctrl.signal,
          quiet: true,
          onEvent: (e) => {
            arm();
            handleEvent(turnId, e);
          },
        });
        // Stream ended. Without `final` or `error` the turn was cut short.
        updateTurn(turnId, (t) => {
          if (t.phase !== "streaming") return t;
          if (ctrl.signal.aborted) {
            return timedOut.current
              ? { ...t, phase: "error", error: { code: "timeout", message: "No answer arrived in time." } }
              : { ...t, phase: "stopped" };
          }
          return { ...t, phase: "error", error: { code: "network_error", message: "The answer stopped before it was complete." } };
        });
      } catch (e) {
        const err = errorFrom(e);
        updateTurn(turnId, (t) => ({ ...t, phase: "error", error: err }));
        if (err.code === "sign_in_required" || err.code === "reauth_required") {
          openSignIn("Sign in again to continue the conversation with Dr. Wu.");
        } else if (err.code === "age_confirmation_required" && e instanceof ApiError) {
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
        { id: assistantId, kind: "assistant", phase: "streaming", statuses: [], reply: emptyReply(), final: false, request: text },
      ]);
      void run(assistantId, text);
    },
    [run],
  );

  const retry = useCallback(
    (turnId: string) => {
      const turn = turns.find((t) => t.id === turnId);
      if (!turn || turn.kind !== "assistant" || !turn.request) return;
      updateTurn(turnId, (t) => ({ ...t, phase: "streaming", statuses: [], reply: emptyReply(), final: false, error: undefined }));
      void run(turnId, turn.request);
    },
    [turns, run, updateTurn],
  );

  const stop = useCallback(() => {
    ctrlRef.current?.abort();
  }, []);

  const newConversation = useCallback(() => {
    ctrlRef.current?.abort();
    setTurns([]);
    setSessionId(null);
    sessionRef.current = null;
  }, []);

  const openSession = useCallback(async (id: string) => {
    ctrlRef.current?.abort();
    setLoadingSession(true);
    try {
      const detail = await apiFetch<Schemas.ChatSessionDetail>(`/chat/sessions/${encodeURIComponent(id)}`, {
        quiet: true,
        cache: "no-store",
      });
      setTurns(turnsFromHistory(detail.messages ?? []));
      setSessionId(id);
      sessionRef.current = id;
      announce("Conversation opened.");
    } catch {
      toast("That conversation could not be opened", { description: "Please try again in a moment." });
    } finally {
      setLoadingSession(false);
    }
  }, []);

  const deleteSession = useCallback(
    async (id: string) => {
      try {
        await apiFetch(`/chat/sessions/${encodeURIComponent(id)}`, { method: "DELETE", quiet: true });
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
      profileRef.current = (await apiFetch<PatientProfile>("/profile", { quiet: true, cache: "no-store" })) ?? {};
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
   * Save `chip` into (add) or out of (remove) the profile. `PUT /profile` is
   * optimistically locked on `updated_at`: read fresh, merge, write, and on a
   * 409 conflict read again and retry once.
   */
  const persistChip = useCallback(
    async (chip: TurnChip, add: boolean) => {
      for (let attempt = 0; ; attempt++) {
        const current = await loadProfile();
        const next = applyChipToProfile(current, chip, add);
        try {
          const saved = await apiFetch<PatientProfile>("/profile", { method: "PUT", json: next, quiet: true });
          profileRef.current = saved && typeof saved === "object" ? saved : next;
          return;
        } catch (e) {
          if (attempt === 0 && e instanceof ApiError && (e.code === "conflict" || e.status === 409)) continue;
          throw e;
        }
      }
    },
    [loadProfile],
  );

  const chipFailed = useCallback(
    (e: unknown) => {
      const err = errorFrom(e);
      if (err.code === "sign_in_required" || err.code === "reauth_required") openSignIn();
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

  return {
    turns,
    sessionId,
    sessions,
    streaming,
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
