"use client";

import {
  ArrowRight,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  Hourglass,
  Lock,
  Radar,
  Send,
  Square,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { NodeChip } from "@/components/graph-ui";
import { useGate } from "@/components/providers/gate-provider";
import { useLens } from "@/components/providers/lens-provider";
import { useSession } from "@/components/providers/session-provider";
import { AiDisclosure } from "@/components/shell/ai-disclosure";
import { Button } from "@/components/ui/button";
import { LimitContact, LimitText } from "@/components/ui/limit-notice";
import { Spinner } from "@/components/ui/spinner";
import { announce } from "@/lib/a11y";
import { trackEvent } from "@/lib/analytics";
import { createContribution, streamSSE } from "@/lib/api";
import type { ApiError } from "@/lib/api/errors";
import { limitInfo, type LimitInfo } from "@/lib/api/limits";
import { relationLabel } from "@/lib/graph/meta";
import { cn } from "@/lib/utils";

import type {
  CandidateEdge,
  CandidateEdgeContributionCreate,
  Endpoint,
  Family,
  GapSearchEvent,
  GapStopReason,
} from "./types";

type Progress = { step: number; tool?: string | null; message: string; elapsed?: number };

type Ending =
  | { kind: "final"; reason: GapStopReason; count: number }
  | { kind: "error"; code: string; message: string; limit?: LimitInfo }
  | { kind: "stopped" };

type Phase = "idle" | "running" | "ended";

const TOOL_LABEL: Record<string, string> = {
  pubmed_search: "PubMed",
  clinicaltrials_search: "ClinicalTrials.gov",
  web_search: "Web",
  fetch_page: "Reading page",
};

const ENDING_COPY: Record<GapStopReason, string> = {
  completed: "Search finished.",
  max_steps: "Stopped at the step budget: the agent may have missed sources.",
  max_tokens: "Stopped at the reading budget: the agent may have missed sources.",
  timeout: "Stopped after 90 seconds: the agent may have missed sources.",
};

function errorEnding(code: string): string {
  switch (code) {
    case "rate_limited":
      return "You've reached the gap-search usage limit for now. Please try again later.";
    case "busy":
      return "Amber is busy. Try again in a moment.";
    case "reauth_required":
      return "Your ChatGPT sign-in has expired. Please sign in again to search.";
    case "assistant_unavailable":
      return "Gap search is not available for this sign-in.";
    case "upstream_error":
      return "A search service did not respond. Please try again in a moment.";
    case "not_implemented":
      return "Gap search isn't available on this server yet.";
    case "network_error":
      return "Amber's server can't be reached. Please try again in a moment.";
    case "not_found":
      return "One of these is no longer in the atlas, so the gap can't be searched.";
    case "validation_error":
      return "The gap can't be searched: both ends point to the same node.";
    case "age_confirmation_required":
      return "Please confirm you are 16 or older in your account before using gap search.";
    default:
      return "The search stopped unexpectedly. Please try again.";
  }
}

type Submit = { state: "idle" | "sending" | "sent" | "error"; message?: string };

function CandidateCard({
  c,
  labels,
  submit,
  onSubmit,
}: {
  c: CandidateEdge;
  labels: Map<string, Endpoint>;
  submit: Submit;
  onSubmit: () => void;
}) {
  const { labelStyle } = useLens();
  const src = labels.get(c.source_id);
  const tgt = labels.get(c.target_id);
  return (
    <li className="rounded-lg border-2 border-dashed border-status-flag/60 bg-card p-3.5" data-testid="gap-candidate">
      <p
        className="mb-2 inline-flex items-center gap-1.5 rounded-md bg-status-flag/15 px-2 py-0.5 text-[11.5px] font-semibold"
        data-testid="pending-review-label"
      >
        <Hourglass className="size-3.5 text-status-flag" aria-hidden />
        Pending review, not part of the trusted graph
      </p>
      <div className="flex flex-wrap items-center gap-1.5 text-sm">
        <NodeChip id={c.source_id} type={src?.type ?? "disease"} label={src?.label ?? c.source_id} size="sm" />
        <span className="inline-flex items-center gap-1 text-muted-foreground">
          <span className={cn(labelStyle === "technical" && "font-mono text-xs")}>{relationLabel(c.relation, labelStyle)}</span>
          <ArrowRight className="size-3" aria-hidden />
        </span>
        <NodeChip id={c.target_id} type={tgt?.type ?? "disease"} label={tgt?.label ?? c.target_id} size="sm" />
      </div>
      <blockquote className="mt-2 border-l-2 border-border pl-2.5 text-[13px] leading-relaxed text-muted-foreground">“{c.quote}”</blockquote>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <a
          href={c.source_url}
          target="_blank"
          rel="noopener noreferrer"
          referrerPolicy="no-referrer"
          className="inline-flex items-center gap-1 font-mono text-xs font-medium underline-offset-2 hover:underline"
        >
          {c.source_id_ref ?? c.source_type}
          <ArrowUpRight className="size-3" aria-hidden />
          <span className="sr-only">(opens in a new tab)</span>
        </a>
        {submit.state === "sent" ? (
          <span className="inline-flex items-center gap-1 text-xs font-medium" data-testid="candidate-submitted" role="status">
            <CheckCircle2 className="size-3.5 text-confidence-high" aria-hidden />
            Submitted for review
          </span>
        ) : (
          <Button size="sm" variant="outline" onClick={onSubmit} disabled={submit.state === "sending"} data-testid="submit-candidate">
            {submit.state === "sending" ? <Spinner /> : <Send aria-hidden />}
            Submit to the shared graph
          </Button>
        )}
      </div>
      {submit.state === "error" && (
        <p role="alert" className="mt-1.5 text-xs text-confidence-low">
          {submit.message}
        </p>
      )}
    </li>
  );
}

/**
 * Gap search (agent spec W5): signed in only. Streams what the agent is
 * searching, then candidate edges that stay `pending_review`. A candidate is
 * shared only if the user submits it (contribute consent); otherwise it
 * lives in this tab's memory and disappears on reload.
 */
export function GapSearchPanel({
  fromId,
  toId,
  family,
  labels,
}: {
  fromId: string;
  toId: string;
  family: Family;
  labels: Map<string, Endpoint>;
}) {
  const { user } = useSession();
  const { requireSignIn, requireConsent } = useGate();
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState<Progress[]>([]);
  const [candidates, setCandidates] = useState<CandidateEdge[]>([]);
  const [ending, setEnding] = useState<Ending | null>(null);
  const [submits, setSubmits] = useState<Record<number, Submit>>({});
  const ctrl = useRef<AbortController | null>(null);

  useEffect(() => () => ctrl.current?.abort(), []);
  // A different missing link starts over.
  useEffect(() => {
    ctrl.current?.abort();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset on new route
    setPhase("idle");
    setProgress([]);
    setCandidates([]);
    setEnding(null);
    setSubmits({});
  }, [fromId, toId, family]);

  const start = async () => {
    const here = `${window.location.pathname}${window.location.search}`;
    if (!(await requireSignIn("Gap search uses an AI agent that searches the literature for you.", here))) return;
    ctrl.current?.abort();
    const c = new AbortController();
    ctrl.current = c;
    setPhase("running");
    setProgress([]);
    setCandidates([]);
    setEnding(null);
    setSubmits({});
    announce("Gap search started.");
    trackEvent("gap_search");
    let ended = false;
    try {
      await streamSSE<GapSearchEvent>("/gap-search", {
        json: { from_id: fromId, to_id: toId, family },
        signal: c.signal,
        quiet: true,
        onEvent: (e) => {
          if (e.type === "progress") {
            setProgress((p) => [...p, { step: e.step, tool: e.tool, message: e.message, elapsed: e.elapsed_s }]);
          } else if (e.type === "candidate") {
            setCandidates((cs) => [...cs, e.candidate]);
            announce("Found a candidate link.");
          } else if (e.type === "final") {
            ended = true;
            setEnding({ kind: "final", reason: e.stop_reason, count: e.candidate_count });
            announce(`${ENDING_COPY[e.stop_reason]} ${e.candidate_count} candidate${e.candidate_count === 1 ? "" : "s"}.`);
          } else if (e.type === "error") {
            ended = true;
            setEnding({ kind: "error", code: e.code, message: errorEnding(e.code) });
            announce(errorEnding(e.code), "assertive");
          }
        },
      });
      if (c.signal.aborted) {
        setEnding((x) => x ?? { kind: "stopped" });
      } else if (!ended) {
        setEnding({ kind: "error", code: "network_error", message: "The search ended without a result. Please try again." });
      }
    } catch (err) {
      const e = err as ApiError;
      if (e.code === "sign_in_required") {
        setEnding({
          kind: "error",
          code: "reauth_required",
          message: "Gap search needs a working ChatGPT connection. Please sign in with ChatGPT again.",
        });
      } else {
        const limit = e.code === "rate_limited" ? limitInfo(e) : undefined;
        setEnding({ kind: "error", code: e.code, message: errorEnding(e.code), limit });
      }
    } finally {
      if (ctrl.current === c) setPhase("ended");
    }
  };

  const stop = () => {
    ctrl.current?.abort();
    setEnding({ kind: "stopped" });
    setPhase("ended");
    announce("Gap search stopped.");
  };

  const submit = async (i: number, c: CandidateEdge) => {
    if (!(await requireConsent("contribute", "Sharing a candidate link with the shared graph needs your consent."))) return;
    setSubmits((s) => ({ ...s, [i]: { state: "sending" } }));
    const body: CandidateEdgeContributionCreate = {
      kind: "candidate_edge",
      payload: {
        source_id: c.source_id,
        target_id: c.target_id,
        relation: c.relation,
        source_url: c.source_url,
        source_id_ref: c.source_id_ref ?? null,
        quote: c.quote.slice(0, 500),
      },
    };
    const { error } = await createContribution({ body, meta: { quiet: true } });
    if (!error) {
      setSubmits((s) => ({ ...s, [i]: { state: "sent" } }));
      announce("Candidate submitted for review.");
      return;
    }
    const e = error as unknown as ApiError;
    if (e.code === "consent_required") {
      setSubmits((s) => ({ ...s, [i]: { state: "idle" } }));
      void requireConsent("contribute");
      return;
    }
    const message =
      e.code === "validation_error"
        ? `The server did not accept this candidate. ${e.message}`
        : e.code === "rate_limited"
          ? "You've reached the limit for contributions this hour. The candidate stays private; try again later."
          : e.code === "age_confirmation_required"
            ? "Please confirm you are 16 or older in your account first. The candidate stays private."
            : e.code === "not_implemented"
              ? "Contributions aren't available on this server yet. The candidate stays private."
              : e.code === "sign_in_required"
                ? "Your session has ended. Please sign in again; the candidate stays private."
                : "It could not be submitted. It stays private to you; try again.";
    setSubmits((s) => ({ ...s, [i]: { state: "error", message } }));
  };

  const running = phase === "running";
  const latest = progress[progress.length - 1];

  return (
    <section aria-labelledby="gap-heading" className="space-y-4 rounded-xl border bg-card p-5" data-testid="gap-search">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <h3 id="gap-heading" className="flex items-center gap-2 text-base font-semibold">
            <Radar className="size-4 text-primary" aria-hidden />
            Search for the missing evidence
          </h3>
          <p className="max-w-prose text-sm text-muted-foreground">
            An AI agent searches PubMed, ClinicalTrials.gov and the web for up to 90 seconds, using public graph names
            only, never anything about you. Results are candidates to check, not facts.
          </p>
        </div>
        {running ? (
          <Button variant="outline" onClick={stop} data-testid="gap-stop">
            <Square aria-hidden /> Stop
          </Button>
        ) : (
          <Button onClick={start} data-testid="gap-start" className="shrink-0">
            {user ? <Radar aria-hidden /> : <Lock aria-hidden />}
            {phase === "ended" ? "Search again" : "Run gap search"}
          </Button>
        )}
      </div>
      {!user && phase === "idle" && <p className="text-xs text-muted-foreground">Gap search needs sign-in.</p>}

      {phase !== "idle" && <AiDisclosure />}

      {phase !== "idle" && (
        <div className="space-y-2" data-testid="gap-progress">
          <div className="flex items-center gap-2 text-sm" role="status" aria-live="polite">
            {running ? <Spinner className="size-4 text-primary" /> : <Clock className="size-4 text-muted-foreground" aria-hidden />}
            <span className="font-medium">
              {running ? (latest ? latest.message : "Starting the agent…") : `Searched in ${progress.length} step${progress.length === 1 ? "" : "s"}`}
            </span>
          </div>
          {progress.length > 0 && (
            <ol className="max-h-48 space-y-1 overflow-y-auto rounded-md bg-muted/40 p-2 font-mono text-[11.5px]" aria-label="Agent steps">
              {progress.map((p, i) => (
                <li key={i} className="flex gap-2">
                  <span className="w-6 shrink-0 text-right text-muted-foreground tabular">{p.step}</span>
                  {p.tool && <span className="shrink-0 rounded bg-background px-1 text-[10.5px]">{TOOL_LABEL[p.tool] ?? p.tool}</span>}
                  <span className="min-w-0 flex-1 font-sans text-[12.5px]">{p.message}</span>
                  {typeof p.elapsed === "number" && <span className="shrink-0 text-muted-foreground tabular">{p.elapsed.toFixed(0)}s</span>}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      {ending && (
        <div
          className={cn(
            "flex items-start gap-2 rounded-md border px-3 py-2 text-sm",
            ending.kind === "error" && "border-status-flag/60 bg-status-flag/10",
            ending.kind === "final" && ending.reason !== "completed" && "border-status-flag/60 bg-status-flag/10",
          )}
          role={ending.kind === "error" ? "alert" : "status"}
          data-testid="gap-ending"
          data-ending={ending.kind === "final" ? ending.reason : ending.kind === "error" ? ending.code : "stopped"}
        >
          {ending.kind === "final" && ending.reason === "completed" ? (
            <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-confidence-high" aria-hidden />
          ) : (
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-status-flag" aria-hidden />
          )}
          <span>
            {ending.kind === "final"
              ? `${ENDING_COPY[ending.reason]} ${ending.count === 0 ? "Nothing found in the sources searched." : `${ending.count} candidate link${ending.count === 1 ? "" : "s"} found.`}`
              : ending.kind === "error"
                ? ending.limit
                  ? <><LimitText info={ending.limit} subject="gap search" /><LimitContact info={ending.limit} /></>
                  : ending.message
                : `Stopped. ${candidates.length} candidate${candidates.length === 1 ? "" : "s"} found so far.`}
          </span>
          {ending.kind === "error" && ending.code === "reauth_required" && (
            <Button size="sm" variant="ghost" className="ml-auto" onClick={() => requireSignIn(undefined, `${window.location.pathname}${window.location.search}`)}>
              Sign in
            </Button>
          )}
        </div>
      )}

      {candidates.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-semibold">Candidate links · {candidates.length}</h4>
          <p className="text-xs text-muted-foreground">
            These stay private to you in this tab unless you submit one. A submitted candidate is reviewed by a person
            before it can become part of the graph.
          </p>
          <ul className="space-y-2.5">
            {candidates.map((c, i) => (
              <CandidateCard key={i} c={c} labels={labels} submit={submits[i] ?? { state: "idle" }} onSubmit={() => submit(i, c)} />
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
