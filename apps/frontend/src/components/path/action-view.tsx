"use client";

import { CircleCheck, CircleSlash, ExternalLink, FileDown, Printer } from "lucide-react";
import { useEffect, useState } from "react";

import { NodeChip } from "@/components/graph-ui";
import { useGate } from "@/components/providers/gate-provider";
import { useLens } from "@/components/providers/lens-provider";
import { useSession } from "@/components/providers/session-provider";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { announce } from "@/lib/a11y";
import { createProposal, type Schemas } from "@/lib/api";
import type { ApiError } from "@/lib/api/errors";
import { nodeTypeMeta, relationLabel } from "@/lib/graph/meta";
import { cn } from "@/lib/utils";

import type { ApiNode, PathT } from "./types";

type LeadGroup = "assets" | "partners" | "trials";

const GROUP_OF: Partial<Record<string, LeadGroup>> = {
  registry: "assets",
  researcher: "partners",
  doctor: "partners",
  grant: "partners",
  patient_org: "partners",
  trial: "trials",
};

const GROUP_COPY: Record<LeadGroup, { title: string; hint: string }> = {
  assets: { title: "Reusable assets", hint: "Registries and natural-history studies you may not need to build again." },
  partners: { title: "Shared researchers, funders and groups", hint: "People and organisations already working on this link." },
  trials: { title: "Trials", hint: "Clinical studies along this route." },
};

const ACTION_TYPE: Record<LeadGroup, Schemas.ActionType> = {
  assets: "reuse_asset",
  partners: "contact",
  trials: "join_trial",
};

export type Lead = {
  node: ApiNode;
  group: LeadGroup;
  /** Path edges from the start to this lead, in order. */
  edgeIds: string[];
  viable: boolean;
  reasons: string[];
};

/**
 * Leads along a path. A lead is viable only when every edge from the start
 * to it is observed, active and uncontradicted (agent spec W4); otherwise it
 * is unsupported and the reasons are listed.
 */
export function leadsFromPath(path: PathT, style: "plain" | "clinical" | "technical"): Lead[] {
  const leads: Lead[] = [];
  const seen = new Set<string>();
  path.steps.forEach((step, i) => {
    for (const node of [step.from_node, step.to_node]) {
      const group = GROUP_OF[node.type];
      if (!group || seen.has(node.id) || node.id === path.steps[0].from_node.id) continue;
      seen.add(node.id);
      const chain = path.steps.slice(0, i + 1);
      const reasons: string[] = [];
      for (const s of chain) {
        const rel = `“${relationLabel(s.edge.relation, style)}”`;
        if (s.edge.origin !== "observed") reasons.push(`relies on a ${s.edge.origin === "inferred" ? "hypothesis" : s.edge.origin.replace("_", "-")} link (${rel})`);
        if (s.edge.status !== "active") reasons.push(`a link is ${s.edge.status.replace("_", " ")} (${rel})`);
        if ((s.edge.contradiction_count ?? 0) > 0) reasons.push(`a link has contradicting evidence (${rel})`);
      }
      leads.push({ node, group, edgeIds: chain.map((s) => s.edge.id), viable: reasons.length === 0, reasons });
    }
  });
  return leads;
}

function LeadCard({ lead }: { lead: Lead }) {
  const { labelStyle } = useLens();
  const meta = nodeTypeMeta(lead.node.type);
  return (
    <li
      className={cn("rounded-lg border bg-card p-3", !lead.viable && "border-dashed")}
      data-testid="lead"
      data-viable={lead.viable}
    >
      <div className="flex flex-wrap items-center gap-2">
        <NodeChip id={lead.node.id} type={lead.node.type} label={lead.node.label} size="sm" />
        <span className="text-[11px] text-muted-foreground">{meta.label[labelStyle]}</span>
      </div>
      {lead.node.description && <p className="mt-1.5 text-[13px] text-muted-foreground">{lead.node.description}</p>}
      {lead.viable ? (
        <p className="mt-2 text-[12px] text-muted-foreground">
          {lead.edgeIds.length} cited step{lead.edgeIds.length === 1 ? "" : "s"}, all observed data.
        </p>
      ) : (
        <ul className="mt-2 space-y-0.5 text-[12px] text-muted-foreground">
          {[...new Set(lead.reasons)].map((r) => (
            <li key={r}>Unsupported: {r}.</li>
          ))}
        </ul>
      )}
    </li>
  );
}

/**
 * The action view of a supported path: viable leads apart from unsupported
 * ones, grouped by what they offer, and "Export proposal" (signed in).
 */
export function ActionView({ path, fromLabel, toLabel }: { path: PathT; fromLabel: string; toLabel: string }) {
  const { labelStyle, role } = useLens();
  const { user } = useSession();
  const { requireSignIn } = useGate();
  const [busy, setBusy] = useState(false);
  const [fallbackUrl, setFallbackUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const leads = leadsFromPath(path, labelStyle);
  const viable = leads.filter((l) => l.viable);
  const unsupported = leads.filter((l) => !l.viable);

  useEffect(() => () => {
    if (fallbackUrl) URL.revokeObjectURL(fallbackUrl);
  }, [fallbackUrl]);

  const exportProposal = async () => {
    setError(null);
    const here = `${window.location.pathname}${window.location.search}`;
    if (!(await requireSignIn("Exporting a proposal needs an account.", here))) return;
    // Open the tab inside the click so pop-up blockers allow it.
    const win = window.open("", "_blank");
    if (win) {
      win.document.title = "Preparing proposal…";
      win.document.body.textContent = "Preparing your proposal…";
    }
    setBusy(true);
    const actions: Schemas.Action[] = leads.map((l) => ({
      title: `${GROUP_COPY[l.group].title}: ${l.node.label}`,
      type: l.node.type === "grant" ? "fund" : ACTION_TYPE[l.group],
      viable: l.viable,
      edge_ids: l.edgeIds,
      timeline_today: null,
      timeline_proposed: null,
      assumptions: l.viable ? [] : [...new Set(l.reasons)],
    }));
    const { data, error: err } = await createProposal({
      body: {
        edge_ids: path.edge_ids,
        actions,
        title: `${fromLabel} → ${toLabel}`,
        role,
        language: user?.language || "en",
      },
      parseAs: "text",
      meta: { quiet: true },
    });
    setBusy(false);
    if (err || typeof data !== "string") {
      win?.close();
      const code = (err as unknown as ApiError | undefined)?.code;
      setError(
        code === "not_implemented"
          ? "Proposal export isn't available on this server yet."
          : code === "network_error"
            ? "Amber's server can't be reached. Please try again in a moment."
            : code === "sign_in_required"
              ? "Your session has ended. Please sign in again to export."
              : "The proposal could not be created. Please try again.",
      );
      return;
    }
    const url = URL.createObjectURL(new Blob([data], { type: "text/html" }));
    if (win && !win.closed) {
      win.location.href = url;
      announce("Proposal opened in a new tab. Use your browser's print dialog to save it as PDF.");
    } else {
      setFallbackUrl(url);
      announce("Proposal ready. Use the link to open it.");
    }
  };

  const groups = (["assets", "partners", "trials"] as LeadGroup[]).filter((g) => leads.some((l) => l.group === g));

  return (
    <section aria-labelledby="action-heading" className="space-y-4" data-testid="action-view">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-muted-foreground">What to do together</p>
          <h2 id="action-heading" className="text-lg font-semibold tracking-tight">
            Leads on this route
          </h2>
          <p className="text-sm text-muted-foreground">
            Viable only if every step is observed, active and uncontradicted.
          </p>
        </div>
        <div className="flex flex-col items-start gap-1 sm:items-end">
          <Button onClick={exportProposal} disabled={busy} data-testid="export-proposal">
            {busy ? <Spinner /> : <FileDown aria-hidden />}
            Export proposal
          </Button>
          <span className="text-[11px] text-muted-foreground">
            {user ? "One sourced page, ready to print or save as PDF." : "Needs sign-in."}
          </span>
        </div>
      </div>

      {error && (
        <p role="alert" className="rounded-md border border-dashed px-3 py-2 text-sm" data-testid="proposal-error">
          {error}
        </p>
      )}
      {fallbackUrl && (
        <p className="flex flex-wrap items-center gap-3 rounded-md border bg-muted/40 px-3 py-2 text-sm" data-testid="proposal-ready">
          <Printer className="size-4" aria-hidden /> Your proposal is ready.
          <a href={fallbackUrl} target="_blank" rel="noopener" className="inline-flex items-center gap-1 font-medium underline underline-offset-4">
            Open it to print or save as PDF <ExternalLink className="size-3.5" aria-hidden />
          </a>
        </p>
      )}

      {leads.length === 0 ? (
        <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground" data-testid="no-leads">
          This route does not pass through a registry, trial, researcher, funder or patient group. The proposal can
          still document the cited connection.
        </p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-3" data-testid="viable-leads">
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <CircleCheck className="size-4 text-confidence-high" aria-hidden /> Viable leads · {viable.length}
            </h3>
            {viable.length === 0 && <p className="text-sm text-muted-foreground">None yet: every lead depends on a hypothesis or unchecked link.</p>}
            {groups.map((g) => {
              const items = viable.filter((l) => l.group === g);
              return items.length ? (
                <div key={g}>
                  <p className="mb-1.5 text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{GROUP_COPY[g].title}.</span> {GROUP_COPY[g].hint}
                  </p>
                  <ul className="space-y-2">{items.map((l) => <LeadCard key={l.node.id} lead={l} />)}</ul>
                </div>
              ) : null;
            })}
          </div>
          <div className="space-y-3" data-testid="unsupported-leads">
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <CircleSlash className="size-4 text-confidence-low" aria-hidden /> Unsupported leads · {unsupported.length}
            </h3>
            {unsupported.length === 0 && <p className="text-sm text-muted-foreground">None: nothing here rests on a hypothesis.</p>}
            {groups.map((g) => {
              const items = unsupported.filter((l) => l.group === g);
              return items.length ? (
                <div key={g}>
                  <p className="mb-1.5 text-xs font-medium">{GROUP_COPY[g].title}</p>
                  <ul className="space-y-2">{items.map((l) => <LeadCard key={l.node.id} lead={l} />)}</ul>
                </div>
              ) : null;
            })}
          </div>
        </div>
      )}
    </section>
  );
}
