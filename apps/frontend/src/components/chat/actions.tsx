"use client";

import { ChevronDown, CircleAlert, CircleCheckBig, FileDown, FlaskConical, HandCoins, Recycle, Users } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { useGate } from "@/components/providers/gate-provider";
import { useLens } from "@/components/providers/lens-provider";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { ApiError } from "@/lib/api/errors";
import { apiFetch } from "@/lib/api/fetch";
import { cn } from "@/lib/utils";

import { EdgeItem } from "./edge-item";
import { useEdges } from "./graph-data";
import type { Action } from "./types";

const TYPE_META: Record<Action["type"], { icon: typeof Recycle; label: string }> = {
  reuse_asset: { icon: Recycle, label: "Reuse what exists" },
  contact: { icon: Users, label: "Get in touch" },
  join_trial: { icon: FlaskConical, label: "Join a study" },
  fund: { icon: HandCoins, label: "Fund research" },
};

/** The proposal is our own server's HTML; still, no scripts may run in it. */
const PROPOSAL_CSP =
  "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:\">";

function ActionCard({ action }: { action: Action }) {
  const [open, setOpen] = useState(false);
  const edges = useEdges(open ? action.edge_ids : []);
  const meta = TYPE_META[action.type] ?? TYPE_META.reuse_asset;
  const Icon = meta.icon;
  return (
    <li
      className={cn(
        "rounded-xl border bg-card p-3.5",
        action.viable ? "border-confidence-high/40" : "border-dashed",
      )}
      data-testid="action"
      data-viable={action.viable}
    >
      <p className="flex items-center gap-1.5 font-mono text-[10.5px] uppercase tracking-[0.12em] text-muted-foreground">
        <Icon className="size-3.5" aria-hidden /> {meta.label}
      </p>
      <h4 className="mt-1 text-[15px] font-semibold tracking-tight" dir="auto">
        {action.title}
      </h4>
      {(action.timeline_today || action.timeline_proposed) && (
        <dl className="mt-2.5 grid gap-2 sm:grid-cols-2">
          <div className="rounded-lg bg-muted/60 px-3 py-2">
            <dt className="text-[11px] font-medium text-muted-foreground">Today</dt>
            <dd className="text-sm" dir="auto">{action.timeline_today ?? "Not stated"}</dd>
          </div>
          <div className="rounded-lg bg-primary/10 px-3 py-2">
            <dt className="text-[11px] font-medium text-muted-foreground">Proposed route</dt>
            <dd className="text-sm font-medium" dir="auto">{action.timeline_proposed ?? "Not stated"}</dd>
          </div>
        </dl>
      )}
      {action.assumptions.length > 0 && (
        <div className="mt-2.5">
          <p className="text-[11px] font-medium text-muted-foreground">Assumes</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-sm">
            {action.assumptions.map((a, i) => (
              <li key={i} dir="auto">{a}</li>
            ))}
          </ul>
        </div>
      )}
      {action.edge_ids.length > 0 && (
        <>
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
            className="mt-2.5 inline-flex items-center gap-1 rounded text-xs font-medium text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ChevronDown className={cn("size-3.5 transition-transform motion-reduce:transition-none", open && "rotate-180")} aria-hidden />
            {open ? "Hide the links behind this" : `Based on ${action.edge_ids.length} link${action.edge_ids.length === 1 ? "" : "s"}`}
          </button>
          {open && (
            <div className="mt-2 space-y-2">
              {action.edge_ids.map((id) => (
                <EdgeItem key={id} id={id} data={edges[id]} />
              ))}
            </div>
          )}
        </>
      )}
    </li>
  );
}

/**
 * The action plan: viable leads (every supporting link observed and active)
 * apart from unsupported ones, each with today's timeline vs the proposed
 * route and its assumptions, and a sourced proposal export.
 */
export function Actions({ actions, edgeIds, language }: { actions: Action[]; edgeIds: string[]; language?: string }) {
  const { role } = useLens();
  const { openSignIn } = useGate();
  const [exporting, setExporting] = useState(false);
  if (actions.length === 0) return null;
  const viable = actions.filter((a) => a.viable);
  const unsupported = actions.filter((a) => !a.viable);
  const allEdges = [...new Set([...actions.flatMap((a) => a.edge_ids), ...edgeIds])].slice(0, 50);

  async function exportProposal() {
    // Open the tab inside the click so popup blockers allow it.
    const tab = window.open("", "_blank");
    setExporting(true);
    try {
      const html = await apiFetch<string>("/proposal", {
        method: "POST",
        quiet: true,
        headers: { Accept: "text/html" },
        json: {
          edge_ids: allEdges,
          actions,
          title: viable[0]?.title ?? actions[0]?.title ?? null,
          role: role === "guest" ? null : role,
          language: language ?? null,
        },
      });
      const text = typeof html === "string" ? html : String(html);
      const safe = /<head[^>]*>/i.test(text) ? text.replace(/<head[^>]*>/i, (m) => `${m}${PROPOSAL_CSP}`) : `${PROPOSAL_CSP}${text}`;
      const url = URL.createObjectURL(new Blob([safe], { type: "text/html" }));
      if (tab) {
        tab.opener = null;
        tab.location.href = url;
      } else {
        window.open(url, "_blank", "noopener");
      }
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      tab?.close();
      const code = e instanceof ApiError ? e.code : "network_error";
      if (code === "sign_in_required" || code === "reauth_required") openSignIn();
      toast("The proposal could not be created", {
        description: code === "not_implemented" ? "Proposal export is not available yet." : "Please try again in a moment.",
      });
    } finally {
      setExporting(false);
    }
  }

  return (
    <section aria-labelledby="actions-heading" className="space-y-3" data-testid="actions">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="actions-heading" className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-muted-foreground">
          What you could do next
        </h3>
        <Button variant="outline" size="sm" onClick={exportProposal} disabled={exporting || allEdges.length === 0}>
          {exporting ? <Spinner className="size-3.5" /> : <FileDown aria-hidden />}
          Export proposal
        </Button>
      </div>
      {viable.length > 0 && (
        <div>
          <p className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
            <CircleCheckBig className="size-4 text-confidence-high" aria-hidden /> Viable leads
            <span className="font-normal text-muted-foreground">· every link is cited data and active</span>
          </p>
          <ul className="space-y-2">
            {viable.map((a, i) => (
              <ActionCard key={i} action={a} />
            ))}
          </ul>
        </div>
      )}
      {unsupported.length > 0 && (
        <div>
          <p className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
            <CircleAlert className="size-4 text-status-flag" aria-hidden /> Unsupported leads
            <span className="font-normal text-muted-foreground">· relies on a hypothesis, an unreviewed or a contradicted link</span>
          </p>
          <ul className="space-y-2">
            {unsupported.map((a, i) => (
              <ActionCard key={i} action={a} />
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
