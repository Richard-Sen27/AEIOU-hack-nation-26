"use client";

import { ArrowLeft, ArrowRight, Check, Loader2, MessageCircle, ShieldCheck, UserRound, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { routeGlobalError } from "@/components/account/api-errors";
import { CLASSIFICATION_LABEL, DOC_TYPE_LABEL, ZYGOSITY_LABEL, formatDate } from "@/components/account/labels";
import { SessionLoading, SignInPrompt } from "@/components/account/sign-in-prompt";
import { NodeChip, VusNotice } from "@/components/graph-ui";
import { useSession } from "@/components/providers/session-provider";
import { AiDisclosure } from "@/components/shell/ai-disclosure";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { announce } from "@/lib/a11y";
import { apiFetch } from "@/lib/api/fetch";
import type {
  Document,
  Finding,
  FindingType,
  VariantClassification,
  Zygosity,
} from "@/lib/api/generated/types.gen";
import { cn } from "@/lib/utils";

import { DeleteDocumentButton } from "./document-list";

const TYPE_LABEL: Record<FindingType, string> = {
  disease: "Diagnosis",
  gene: "Gene",
  variant: "Variant",
  phenotype: "Symptom",
  candidate_edge: "Suggested link",
};

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
  if (f.type === "phenotype" && p.excluded === true) {
    return <Badge variant="outline">Noted as not present</Badge>;
  }
  return null;
}

function FindingCard({
  f,
  onDecide,
  busy,
}: {
  f: Finding;
  onDecide: (f: Finding, confirm: boolean) => void;
  busy: boolean;
}) {
  const decided = f.confirmed === true ? "confirmed" : f.confirmed === false ? "rejected" : "open";
  const nodeType = NODE_TYPE[f.type];
  const terms = [f.value, str(f.payload?.hgvs) ?? "", str(f.payload?.gene) ?? ""];

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
              <Check aria-hidden /> In your profile
            </Badge>
          )}
          {decided === "rejected" && <Badge variant="outline">Rejected, not used</Badge>}
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
          <p className="text-xs text-muted-foreground">If you confirm, it is suggested to the atlas as pending review. It is never used as evidence until checked.</p>
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
        <div className="flex flex-wrap justify-end gap-2">
          {decided !== "rejected" && (
            <Button variant="outline" onClick={() => onDecide(f, false)} disabled={busy} aria-label={`Reject ${TYPE_LABEL[f.type].toLowerCase()} ${f.value}`}>
              <X aria-hidden /> {decided === "confirmed" ? "Remove" : "Reject"}
            </Button>
          )}
          {decided !== "confirmed" && (
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

  const fetchAll = useCallback(async () => {
    try {
      const [docs, list] = await Promise.all([
        apiFetch<Document[]>("/documents", { quiet: true, cache: "no-store" }),
        apiFetch<Finding[]>(`/documents/${encodeURIComponent(documentId)}/findings`, { quiet: true, cache: "no-store" }),
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
      await apiFetch(`/findings/${encodeURIComponent(f.id)}/${confirm ? "confirm" : "reject"}`, { method: "POST", quiet: true });
      setFindings((list) => list.map((x) => (x.id === f.id ? { ...x, confirmed: confirm, decided_at: new Date().toISOString() } : x)));
      announce(confirm ? `${f.value} confirmed and added to your profile.` : `${f.value} rejected. It will not be used.`);
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
  const confirmed = findings.filter((f) => f.confirmed === true).length;
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
          Check each finding against the sentence it came from. Confirmed findings go into your private profile; rejected ones
          are never used. The snippets come from the redacted text: personal details were removed and the original file is
          already deleted.
        </p>
        <p className="flex flex-wrap items-center gap-2 text-muted-foreground">
          <AiDisclosure variant="inline" />
          These findings were extracted by an AI model and can be wrong. This is not a diagnosis.
        </p>
      </div>

      {reviewable === 0 ? (
        <p className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">
          No findings were extracted from this document. You can delete it, or add details to your profile by hand.
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
              <FindingCard key={f.id} f={f} onDecide={(x, c) => void decide(x, c)} busy={busy === f.id} />
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
              Dr. Wu can use your updated profile to look for related diseases, patient communities and research.
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
