"use client";

import { Archive, Bot, RefreshCw, Sparkles, TriangleAlert } from "lucide-react";
import { Fragment, useEffect, useState } from "react";

import { useGate } from "@/components/providers/gate-provider";
import { ROLE_LABELS, useLens } from "@/components/providers/lens-provider";
import { useSession } from "@/components/providers/session-provider";
import { AiDisclosure } from "@/components/shell/ai-disclosure";
import { Button } from "@/components/ui/button";
import { LimitContact, LimitText } from "@/components/ui/limit-notice";
import { Skeleton } from "@/components/ui/skeleton";
import { announce } from "@/lib/a11y";
import { streamSSE } from "@/lib/api";
import type { ApiError } from "@/lib/api/errors";
import { limitInfo, type LimitInfo } from "@/lib/api/limits";
import { relationLabel } from "@/lib/graph/meta";

import type { ExplainEvent, ExplainFinal, PathT } from "./types";

type State =
  | { kind: "loading" }
  | { kind: "streaming"; text: string }
  | { kind: "done"; final: ExplainFinal }
  | { kind: "sign_in" }
  | { kind: "unavailable" }
  | { kind: "error"; message: string; limit?: LimitInfo };

const CITATION = /\[(e_[0-9a-zA-Z]+(?:\s*[,;]\s*e_[0-9a-zA-Z]+)*)\]/g;

function errorMessage(code: string) {
  switch (code) {
    case "network_error":
      return "Amber's server can't be reached, so the explanation can't be loaded right now.";
    case "rate_limited":
      return "You've reached the usage limit for explanations for now. Please try again later.";
    case "busy":
      return "Dr. Wu is busy. Try again in a moment.";
    case "upstream_error":
      return "The AI service did not respond. Please try again in a moment.";
    case "not_found":
      return "This route is no longer in the atlas, so it can't be explained.";
    default:
      return "The explanation could not be loaded. Please try again.";
  }
}

/** Renders explanation text with `[e_…]` citations as links to the cited step. */
function CitedText({
  text,
  path,
  streaming,
  onCite,
}: {
  text: string;
  path: PathT;
  streaming: boolean;
  onCite: (edgeId: string) => void;
}) {
  const { labelStyle } = useLens();
  // While streaming, hide a citation that has only half arrived.
  const shown = streaming ? text.replace(/\[[^\]]{0,40}$/, "") : text;
  const index = new Map(path.steps.map((s, i) => [s.edge.id, i]));
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const m of shown.matchAll(CITATION)) {
    parts.push(shown.slice(last, m.index));
    const ids = m[1].split(/\s*[,;]\s*/).filter((id) => index.has(id));
    parts.push(
      <Fragment key={`${m.index}`}>
        {ids.map((id) => {
          const i = index.get(id)!;
          const step = path.steps[i];
          return (
            <a
              key={id}
              href={`#step-${id}`}
              onClick={(e) => {
                e.preventDefault();
                onCite(id);
              }}
              data-testid="citation"
              data-edge-id={id}
              className="mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-full border border-primary/60 bg-primary/15 px-1 align-middle font-mono text-[10px] font-semibold text-foreground no-underline outline-none transition hover:bg-primary hover:text-primary-foreground focus-visible:ring-2 focus-visible:ring-ring"
              aria-label={`Source: step ${i + 1}, ${relationLabel(step.edge.relation, labelStyle)}`}
            >
              {i + 1}
            </a>
          );
        })}
      </Fragment>,
    );
    last = (m.index ?? 0) + m[0].length;
  }
  parts.push(shown.slice(last));
  return <>{parts}</>;
}

/**
 * `POST /explain` (SSE) for the selected path in the current lens and
 * language. Guests get cached explanations; when none is cached the API says
 * `sign_in_required` and a quiet affordance is shown instead of a dialog.
 */
export function ExplanationPanel({ path, onCite }: { path: PathT; onCite: (edgeId: string) => void }) {
  const { role } = useLens();
  const { user } = useSession();
  const { requireSignIn } = useGate();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const language = user?.language || "en";
  const edgeKey = path.edge_ids.join(",");

  useEffect(() => {
    const ctrl = new AbortController();
    let text = "";
    // eslint-disable-next-line react-hooks/set-state-in-effect -- new request
    setState({ kind: "loading" });
    streamSSE<ExplainEvent>("/explain", {
      json: { edge_ids: edgeKey.split(","), role, language },
      signal: ctrl.signal,
      quiet: true,
      onEvent: (e) => {
        if (e.type === "delta") {
          text += e.text;
          setState({ kind: "streaming", text });
        } else if (e.type === "final") {
          setState({ kind: "done", final: e });
          announce(e.cached ? "Explanation loaded." : "Explanation finished.");
        } else if (e.type === "error") {
          if (e.code === "sign_in_required" || e.code === "reauth_required") setState({ kind: "sign_in" });
          else if (e.code === "not_implemented") setState({ kind: "unavailable" });
          else setState({ kind: "error", message: errorMessage(e.code) });
        }
      },
    }).catch((err: ApiError) => {
      if (ctrl.signal.aborted || err.code === "aborted") return;
      if (err.code === "sign_in_required" || err.code === "reauth_required") setState({ kind: "sign_in" });
      else if (err.code === "not_implemented") setState({ kind: "unavailable" });
      else setState({ kind: "error", message: errorMessage(err.code), limit: err.code === "rate_limited" ? limitInfo(err) : undefined });
    });
    return () => ctrl.abort();
  }, [edgeKey, role, language, user?.id, attempt]);

  const signIn = () => {
    const here = typeof window !== "undefined" ? `${window.location.pathname}${window.location.search}` : "/path";
    void requireSignIn("Explaining a new route uses Dr. Wu.", here);
  };

  return (
    <section aria-labelledby="explain-heading" className="rounded-xl border bg-card p-5" data-testid="explanation">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 id="explain-heading" className="flex items-center gap-2 text-base font-semibold">
          <Bot className="size-4 text-primary" aria-hidden />
          What this route means
          <span className="text-xs font-normal text-muted-foreground">· {ROLE_LABELS[role].label} lens</span>
        </h2>
        {(state.kind === "streaming" || state.kind === "done") && <AiDisclosure variant="inline" />}
      </div>

      {state.kind === "loading" && (
        <div className="space-y-2" role="status" aria-label="Loading explanation">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-11/12" />
          <Skeleton className="h-4 w-3/5" />
        </div>
      )}

      {(state.kind === "streaming" || state.kind === "done") && (
        <>
          <p className="text-[15px] leading-relaxed text-pretty" aria-live="off" data-testid="explanation-text">
            <CitedText
              text={state.kind === "done" ? state.final.text : state.text}
              path={path}
              streaming={state.kind === "streaming"}
              onCite={onCite}
            />
            {state.kind === "streaming" && (
              <span aria-hidden className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-primary align-middle" />
            )}
          </p>
          {state.kind === "done" && (
            <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted-foreground" data-testid="explanation-meta">
              {state.final.cached ? (
                <span className="inline-flex items-center gap-1" data-testid="explanation-cached">
                  <Archive className="size-3.5" aria-hidden /> Prepared in advance (cached)
                </span>
              ) : (
                <span className="inline-flex items-center gap-1" data-testid="explanation-fresh">
                  <Sparkles className="size-3.5" aria-hidden /> Written just now
                </span>
              )}
              <span>Numbers link to their step.</span>
              <span>Not medical advice.</span>
            </p>
          )}
        </>
      )}

      {state.kind === "sign_in" && (
        <div className="flex flex-col gap-3 rounded-lg border border-dashed bg-muted/30 p-4 sm:flex-row sm:items-center sm:justify-between" data-testid="explain-sign-in">
          <p className="text-sm text-muted-foreground">
            There is no prepared explanation for this route yet. Dr. Wu can write one for you, using only the cited
            steps shown here.
          </p>
          <Button variant="outline" size="sm" onClick={signIn} className="shrink-0">
            <Bot className="text-primary" aria-hidden />
            Sign in to have Dr. Wu explain this route
          </Button>
        </div>
      )}

      {state.kind === "unavailable" && (
        <p className="text-sm text-muted-foreground" data-testid="explain-unavailable">
          Explanations aren&apos;t available on this server yet. The steps and their sources below are complete without
          one.
        </p>
      )}

      {state.kind === "error" && (
        <div className="flex items-start gap-3 text-sm" role="alert" data-testid="explain-error">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-status-flag" aria-hidden />
          <div className="space-y-2">
            <p>
              {state.limit ? <LimitText info={state.limit} subject="explanations" /> : state.message}
              <LimitContact info={state.limit} />
            </p>
            <Button variant="ghost" size="sm" onClick={() => setAttempt((a) => a + 1)}>
              <RefreshCw aria-hidden /> Try again
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
