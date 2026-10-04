"use client";

import { ArrowLeft, ArrowRight, Check, Loader2, MessageCircle, Pencil, ShieldCheck, UserRound, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { routeGlobalError } from "@/components/account/api-errors";
import { CLASSIFICATION_LABEL, DOC_TYPE_LABEL, ZYGOSITY_LABEL, formatDate } from "@/components/account/labels";
import { SessionLoading, SignInPrompt } from "@/components/account/sign-in-prompt";
import { CorrectPanel } from "@/components/chat/chips";
import type { TurnChip } from "@/components/chat/types";
import { NodeChip, VusNotice } from "@/components/graph-ui";
import { useGate } from "@/components/providers/gate-provider";
import { useSession } from "@/components/providers/session-provider";
import { AiDisclosure } from "@/components/shell/ai-disclosure";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { announce } from "@/lib/a11y";
import { confirmFinding, getProfile, listDocuments, listFindings, putProfile, rejectFinding, unwrap } from "@/lib/api";
import type {
  Document,
  Finding,
  FindingType,
  PatientProfile,
  VariantClassification,
  Zygosity,
} from "@/lib/api/generated/types.gen";
import type { SearchHit } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { DeleteDocumentButton } from "./document-list";

const TYPE_LABEL: Record<FindingType, string> = {
  disease: "Diagnosis",
  gene: "Gene",
  variant: "Variant",
  phenotype: "Symptom",
  candidate_edge: "Suggested link",
};

/** Finding types that can be corrected by picking the right entity from search. */
const CORRECTABLE: Partial<Record<FindingType, TurnChip["type"]>> = {
  disease: "disease",
  gene: "gene",
  phenotype: "symptom",
};

type Corrected = { id: string; label: string };

/** Put the corrected entity into the profile, linked to the finding it replaces. */
function addCorrected(profile: PatientProfile, f: Finding, pick: Corrected): PatientProfile {
  const item = { id: pick.id, label: pick.label, source: "document" as const, finding_id: f.id, confirmed_at: new Date().toISOString() };
  switch (f.type) {
    case "disease":
      return { ...profile, diseases: [...(profile.diseases ?? []).filter((d) => d.id !== pick.id), item] };
    case "gene":
      return { ...profile, genes: [...(profile.genes ?? []).filter((g) => g.id !== pick.id), item] };
    case "phenotype":
      return {
        ...profile,
        phenotypes: [
          ...(profile.phenotypes ?? []).filter((p) => p.id !== pick.id),
          { ...item, excluded: f.payload?.excluded === true },
        ],
      };
    default:
      return profile;
  }
}

const NODE_TYPE: Partial<Record<FindingType, string>> = {
  disease: "disease",
  gene: "gene",
  variant: "variant",
  phenotype: "phenotype",
};

function str(v: unknown): string | null {
  return typeof v === "string" && v ? v : null;
}

function isVus(f: Finding) {
  return !!f.vus_notice || f.payload?.classification === "uncertain_significance";
}

/** Highlight the extracted value inside the (redacted) snippet. */
function Snippet({ text, terms }: { text: string; terms: string[] }) {
  const lower = text.toLowerCase();
  for (const t of terms) {
    const i = t ? lower.indexOf(t.toLowerCase()) : -1;
    if (i >= 0) {
      return (
        <>
          {text.slice(0, i)}
          <mark className="rounded-sm bg-primary/30 px-0.5 text-foreground">{text.slice(i, i + t.length)}</mark>
          {text.slice(i + t.length)}
        </>
      );
    }
  }
  return <>{text}</>;
}

function Details({ f }: { f: Finding }) {
  const p = f.payload ?? {};
  if (f.type === "variant") {
    const rows: Array<[string, string | null]> = [
      ["HGVS", str(p.hgvs)],
      ["Gene", str(p.gene) ?? str(p.gene_symbol)],
      ["Zygosity", ZYGOSITY_LABEL[p.zygosity as Zygosity] ?? str(p.zygosity)],
      ["Classification", CLASSIFICATION_LABEL[p.classification as VariantClassification] ?? str(p.classification)],
      ["Test date", str(p.test_date)],
    ];
    return (
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        {rows
          .filter(([, v]) => v)
          .map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-muted-foreground">{k}</dt>
              <dd className={cn(k === "HGVS" && "font-mono text-[13px] break-all")}>{v}</dd>
            </div>
          ))}
      </dl>
    );
  }
  if (f.type === "candidate_edge") {
    return (
      <div className="space-y-1.5 text-sm">
        <p>
          <span className="font-medium">{str(p.source_label) ?? str(p.subject)}</span>
          <span className="text-muted-foreground"> {str(p.relation)?.replaceAll("_", " ") ?? "related to"} </span>
          <span className="font-medium">{str(p.target_label) ?? str(p.object)}</span>
        </p>
        {str(p.source_id_ref) && <p className="font-mono text-xs text-muted-foreground">{str(p.source_id_ref)}</p>}
      </div>
    );
  }
  if (f.type === "phenotype" && p.excluded === true) {
    return <Badge variant="outline">Noted as not present</Badge>;
  }
  return null;
}

function FindingCard({
  f,
  onDecide,
  onCorrect,
  corrected,
  busy,
}: {
  f: Finding;
  onDecide: (f: Finding, confirm: boolean) => void;
  onCorrect: (f: Finding, pick: Corrected) => void;
  corrected?: Corrected;
  busy: boolean;
}) {
  const [correcting, setCorrecting] = useState(false);
  const decided = corrected ? "corrected" : f.confirmed === true ? "confirmed" : f.confirmed === false ? "rejected" : "open";
  const chipType = CORRECTABLE[f.type];
  const nodeType = NODE_TYPE[f.type];
  const terms = [f.value, str(f.payload?.hgvs) ?? "", str(f.payload?.gene) ?? "", str(f.payload?.symbol) ?? "", str(f.payload?.matched_synonym) ?? "", str(f.payload?.quote) ?? ""];

  return (
    <li
      data-testid="finding"
      data-state={decided}
      className={cn(
        "grid gap-4 rounded-xl border bg-card p-4 sm:p-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]",
        decided === "confirmed" && "border-secondary/60",
        decided === "rejected" && "opacity-70",
      )}
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[11px] tracking-[0.12em] text-muted-foreground uppercase">{TYPE_LABEL[f.type]}</span>
          {decided === "confirmed" && (
            <Badge variant="secondary">
              <Check aria-hidden /> {f.type === "candidate_edge" ? "Confirmed" : "In your profile"}
            </Badge>
          )}
          {decided === "rejected" && <Badge variant="outline">Rejected, not used</Badge>}
          {corrected && (
            <Badge variant="secondary" data-testid="finding-corrected">
              <Check aria-hidden /> Corrected to {corrected.label}, in your profile
            </Badge>
          )}
        </div>
        <p className="text-base font-semibold tracking-tight break-words">{f.value}</p>
        {f.normalized_id && nodeType && (
          <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            Matched in the atlas as
            <NodeChip id={f.normalized_id} type={nodeType} label={str(f.payload?.label) ?? f.normalized_id} size="sm" showId />
          </p>
        )}
        <Details f={f} />
        {f.type === "candidate_edge" && (
          <p className="text-xs text-muted-foreground" data-testid="candidate-edge-note">
            Confirming does not change your profile. With contribute consent and a DOI or PMID, the link is suggested to the
            shared atlas as pending review, never used as evidence until checked; otherwise it stays private. Rejecting it or
            deleting this document withdraws it.
          </p>
        )}
        {isVus(f) && <VusNotice />}
      </div>

      <div className="flex flex-col gap-3">
        <figure className="flex-1 rounded-lg border bg-muted/40 p-3">
          <figcaption className="mb-1.5 flex items-center justify-between text-[11px] text-muted-foreground">
            <span>From the redacted text</span>
            {f.page ? <span>Page {f.page}</span> : null}
          </figcaption>
          {f.snippet ? (
            <blockquote className="text-sm leading-relaxed" data-testid="finding-snippet">
              &ldquo;<Snippet text={f.snippet} terms={terms} />&rdquo;
            </blockquote>
          ) : (
            <p className="text-sm text-muted-foreground">No snippet available.</p>
          )}
        </figure>
        {correcting && chipType && (
          <CorrectPanel
            chip={{ type: chipType, id: f.normalized_id ?? null, label: f.value, negated: false, confirmed: false, state: "pending" }}
            onPick={(hit: SearchHit) => {
              setCorrecting(false);
              onCorrect(f, { id: hit.id, label: hit.label });
            }}
            onCancel={() => setCorrecting(false)}
          />
        )}
        <div className="flex flex-wrap justify-end gap-2">
          {chipType && !corrected && f.confirmed !== true && (
            <Button
              variant="ghost"
              onClick={() => setCorrecting((c) => !c)}
              disabled={busy}
              aria-expanded={correcting}
              aria-label={`Correct ${TYPE_LABEL[f.type].toLowerCase()} ${f.value}`}
            >
              <Pencil aria-hidden /> Correct
            </Button>
          )}
          {decided !== "rejected" && decided !== "corrected" && (
            <Button variant="outline" onClick={() => onDecide(f, false)} disabled={busy} aria-label={`Reject ${TYPE_LABEL[f.type].toLowerCase()} ${f.value}`}>
              <X aria-hidden /> {decided === "confirmed" ? "Remove" : "Reject"}
            </Button>
          )}
          {decided !== "confirmed" && decided !== "corrected" && (
            <Button onClick={() => onDecide(f, true)} disabled={busy} aria-label={`Confirm ${TYPE_LABEL[f.type].toLowerCase()} ${f.value}`}>
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Check aria-hidden />}
              {decided === "rejected" ? "Confirm instead" : "Confirm"}
            </Button>
          )}
        </div>
      </div>
    </li>
  );
}

type Load = { kind: "loading" } | { kind: "ready" } | { kind: "error"; message: string; notFound?: boolean };

export function FindingsReview({ documentId }: { documentId: string }) {
  const { user, status } = useSession();
  const router = useRouter();
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [doc, setDoc] = useState<Document | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [corrected, setCorrected] = useState<Record<string, Corrected>>({});
  const { requireConsent } = useGate();

  const fetchAll = useCallback(async () => {
    try {
      const [docs, list] = await Promise.all([
        unwrap(listDocuments({ meta: { quiet: true }, cache: "no-store" })),
        unwrap(listFindings({ path: { document_id: documentId }, meta: { quiet: true }, cache: "no-store" })),
      ]);
      setDoc(docs.find((d) => d.id === documentId) ?? null);
      setFindings(list);
      setLoad({ kind: "ready" });
    } catch (e) {
      const err = routeGlobalError(e);
      setLoad({
        kind: "error",
        notFound: err?.code === "not_found" || err?.code === "validation_error",
        message:
          err?.code === "not_found" || err?.code === "validation_error"
            ? "This document does not exist or was deleted."
            : err?.code === "not_implemented"
              ? "Findings review is not available yet."
              : err?.code === "network_error"
                ? "Amber's server is not reachable. Please try again in a moment."
                : "The findings could not be loaded.",
      });
    }
  }, [documentId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on sign-in, state set after await
    if (user) void fetchAll();
  }, [user, fetchAll]);

  async function decide(f: Finding, confirm: boolean) {
    setBusy(f.id);
    try {
      await unwrap((confirm ? confirmFinding : rejectFinding)({ path: { finding_id: f.id }, meta: { quiet: true } }));
      setFindings((list) => list.map((x) => (x.id === f.id ? { ...x, confirmed: confirm, decided_at: new Date().toISOString() } : x)));
      announce(
        confirm
          ? f.type === "candidate_edge"
            ? `${f.value} confirmed.`
            : `${f.value} confirmed and added to your profile.`
          : `${f.value} rejected. It will not be used.`,
      );
    } catch (e) {
      routeGlobalError(e);
      toast("Not saved", { description: "Please try again." });
    } finally {
      setBusy(null);
    }
  }

  /**
   * The extraction was wrong: the finding itself is rejected (the API stores
   * findings as extracted) and the entity the user picked goes into the
   * profile instead, linked to that finding.
   */
  async function correct(f: Finding, pick: Corrected) {
    if (!(await requireConsent("health_data", "Saving to your profile needs your consent to use health information."))) return;
    setBusy(f.id);
    try {
      if (f.confirmed !== false) {
        await unwrap(rejectFinding({ path: { finding_id: f.id }, meta: { quiet: true } }));
      }
      for (let attempt = 0; ; attempt++) {
        const current = (await unwrap(getProfile({ meta: { quiet: true }, cache: "no-store" }))) ?? {};
        try {
          await unwrap(putProfile({ body: addCorrected(current, f, pick), meta: { quiet: true } }));
          break;
        } catch (e) {
          if (attempt === 0 && (e as { status?: number }).status === 409) continue;
          throw e;
        }
      }
      setFindings((list) => list.map((x) => (x.id === f.id ? { ...x, confirmed: false, decided_at: new Date().toISOString() } : x)));
      setCorrected((c) => ({ ...c, [f.id]: pick }));
      announce(`Corrected to ${pick.label} and added to your profile.`);
    } catch (e) {
      routeGlobalError(e);
      toast("Not saved", { description: "Please try again." });
    } finally {
      setBusy(null);
    }
  }

  if (status === "loading") return <SessionLoading />;
  if (!user) {
    return (
      <SignInPrompt
        title="Sign in to review findings"
        description="Findings from your documents are private to your account."
        returnTo={`/documents/${documentId}`}
      />
    );
  }
  if (load.kind === "loading") {
    return (
      <div className="space-y-3" aria-busy="true" aria-label="Loading findings">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (load.kind === "error") {
    return (
      <div className="space-y-3 rounded-xl border border-dashed p-6 text-sm" role="status">
        <p className="text-muted-foreground">{load.message}</p>
        <div className="flex gap-2">
          {!load.notFound && (
            <Button variant="outline" onClick={() => void fetchAll()}>
              Try again
            </Button>
          )}
          <Link href="/documents" className={buttonVariants({ variant: "ghost" })}>
            <ArrowLeft data-icon="inline-start" aria-hidden /> Your documents
          </Link>
        </div>
      </div>
    );
  }

  const open = findings.filter((f) => f.confirmed == null).length;
  const confirmed =
    findings.filter((f) => f.confirmed === true && f.type !== "candidate_edge").length + Object.keys(corrected).length;
  const reviewable = findings.length;

  return (
    <div className="space-y-6">
      <section aria-label="About this document" className="flex flex-wrap items-start gap-x-8 gap-y-4 rounded-xl border bg-card p-4 sm:p-5">
        <div>
          <p className="text-xs text-muted-foreground">Document type (recognised by AI)</p>
          <p className="text-sm font-semibold" data-testid="doc-type">
            {doc?.doc_type ? DOC_TYPE_LABEL[doc.doc_type] : "Not recognised"}
          </p>
        </div>
        {doc && (
          <div>
            <p className="text-xs text-muted-foreground">Uploaded</p>
            <p className="text-sm">
              {formatDate(doc.created_at, true)}
              {doc.page_count ? ` · ${doc.page_count} ${doc.page_count === 1 ? "page" : "pages"}` : ""}
            </p>
          </div>
        )}
        <div className="flex items-start gap-2">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-secondary" aria-hidden />
          <div>
            <p className="text-xs text-muted-foreground">Original file</p>
            <p className="text-sm" data-testid="raw-deleted">
              {doc?.raw_deleted_at ? `Deleted ${formatDate(doc.raw_deleted_at, true)}` : "Deleted after extraction"}
            </p>
          </div>
        </div>
        <div className="ml-auto">
          <DeleteDocumentButton id={documentId} onDeleted={() => router.push("/documents")} label="Delete document" />
        </div>
      </section>

      <div className="space-y-3 rounded-xl border border-primary/40 bg-primary/10 p-4 text-sm" data-testid="review-notice">
        <p className="font-semibold">Nothing is used until you confirm it.</p>
        <p className="text-muted-foreground">
          Check each finding against its sentence. Snippets come from the redacted text; the file is already deleted.
        </p>
        <p className="flex flex-wrap items-center gap-2 text-muted-foreground">
          <AiDisclosure variant="inline" />
          Extracted by AI and can be wrong. Not a diagnosis.
        </p>
      </div>

      {reviewable === 0 ? (
        <p className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">
          No findings matched the atlas, so nothing will be added. Delete it, or add details to your profile by hand.
        </p>
      ) : (
        <>
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-lg font-semibold tracking-tight">Findings</h2>
            <p className="text-sm text-muted-foreground" data-testid="review-progress" aria-live="polite">
              {reviewable - open} of {reviewable} reviewed
            </p>
          </div>
          <ul className="space-y-3">
            {findings.map((f) => (
              <FindingCard
                key={f.id}
                f={f}
                onDecide={(x, c) => void decide(x, c)}
                onCorrect={(x, pick) => void correct(x, pick)}
                corrected={corrected[f.id]}
                busy={busy === f.id}
              />
            ))}
          </ul>
        </>
      )}

      {reviewable > 0 && open === 0 && (
        <section aria-labelledby="next-h" className="flex flex-col gap-4 rounded-xl border bg-card p-5 sm:flex-row sm:items-center" data-testid="review-done">
          <div className="flex-1 space-y-1">
            <h2 id="next-h" className="text-base font-semibold">
              All reviewed
            </h2>
            <p className="text-sm text-muted-foreground">
              {confirmed
                ? `${confirmed} ${confirmed === 1 ? "finding is" : "findings are"} now in your profile.`
                : "Nothing was added to your profile."}{" "}
              Dr. Wu can now use it.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href="/profile" className={buttonVariants({ variant: "outline", size: "lg" })}>
              <UserRound data-icon="inline-start" aria-hidden /> See my profile
            </Link>
            <Link href="/chat" className={buttonVariants({ size: "lg" })}>
              <MessageCircle data-icon="inline-start" aria-hidden /> Ask Dr. Wu <ArrowRight data-icon="inline-end" aria-hidden />
            </Link>
          </div>
        </section>
      )}
    </div>
  );
}
