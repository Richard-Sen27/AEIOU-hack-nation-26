"use client";

import { ArrowLeft, ArrowUpRight, Info, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { routeGlobalError } from "@/components/account/api-errors";
import { SignInPrompt } from "@/components/account/sign-in-prompt";
import { NodeChip } from "@/components/graph-ui";
import { useSession } from "@/components/providers/session-provider";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getCall } from "@/lib/api";
import type { ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

import { ageText, callErrorText, countryName, formatDate, KIND_META, runByText, type Call } from "./call-meta";
import { DemoMark, KindBadge } from "./call-parts";
import { CallSignupSlot } from "./call-signup-slot";
import { PublisherLine } from "./publisher-line";

function Block({ title, children, className, testId }: { title: string; children: React.ReactNode; className?: string; testId?: string }) {
  return (
    <section className={cn("space-y-1.5", className)} data-testid={testId}>
      <h2 className="text-sm font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Prose({ text }: { text: string }) {
  return <p className="text-sm leading-relaxed whitespace-pre-line text-pretty">{text}</p>;
}

function Facts({ rows }: { rows: Array<[string, React.ReactNode] | null | false> }) {
  const shown = rows.filter(Boolean) as Array<[string, React.ReactNode]>;
  if (!shown.length) return null;
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
      {shown.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function ExternalLink({ href, children, testId }: { href: string; children: React.ReactNode; testId?: string }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer" className="inline-flex items-center gap-0.5 font-medium underline underline-offset-2" data-testid={testId}>
      {children}
      <ArrowUpRight className="size-3.5" aria-hidden />
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  );
}

/**
 * Everything a reader needs to decide whether to look further: what it is,
 * who runs it, who can take part, what taking part involves, ethics and
 * registry, dates. `preview`: the publisher's own view (no sign-up slot).
 */
export function CallDetail({ call, preview = false }: { call: Call; preview?: boolean }) {
  const { user } = useSession();
  // The sign-up slot (with the study's link) is not shown to experts or in a preview.
  const expert = user?.role === "doctor" || user?.role === "researcher";
  const age = ageText(call);
  const runBy = runByText(call);
  const opens = formatDate(call.opens_at);
  const closes = formatDate(call.closes_at);
  const published = formatDate(call.published_at);
  const where = call.countries.map(countryName).join(", ");
  const topics = [
    ...call.diseases.map((d) => ({ ...d, type: "disease" })),
    ...call.genes.map((d) => ({ ...d, type: "gene" })),
    ...call.phenotypes.map((d) => ({ ...d, type: "phenotype" })),
  ];

  return (
    <article className="space-y-6" data-testid="call-detail" data-kind={call.kind}>
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <KindBadge kind={call.kind} />
          {call.demo && <DemoMark />}
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-balance sm:text-3xl">{call.title}</h1>
        <div
          className="flex items-start gap-2.5 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2.5 text-sm"
          data-testid="call-notice"
        >
          <Info className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
          <p className="text-pretty">{call.notice}</p>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-5">
          <Block title={`What this ${KIND_META[call.kind].label.toLowerCase()} is about`}>
            <Prose text={call.summary} />
          </Block>
          <Block title="What taking part involves">
            <Prose text={call.participation} />
          </Block>
          <Block title="Who can take part" testId="call-eligibility">
            {call.eligibility_text && <Prose text={call.eligibility_text} />}
            <Facts
              rows={[
                age ? ["Age", age] : null,
                ["Children", call.children_ok && !call.adults_only ? "Can take part, with a parent" : "No"],
                where ? ["Where", where] : null,
                ["Remote", call.remote ? "Yes, no visits needed" : "No"],
              ]}
            />
          </Block>
          {topics.length > 0 && (
            <Block title="Conditions">
              <ul className="flex flex-wrap gap-1.5">
                {topics.map((t) => (
                  <li key={t.id}>
                    <NodeChip id={t.id} type={t.type} label={t.label ?? t.id} size="sm" href={t.label ? undefined : null} />
                  </li>
                ))}
              </ul>
            </Block>
          )}
          {!preview && <CallSignupSlot call={call} />}
        </div>

        <aside className="min-w-0 space-y-5 lg:border-l lg:pl-6">
          {call.publisher && (
            <Block title="Published by">
              <PublisherLine card={call.publisher} />
            </Block>
          )}
          {runBy && (
            <Block title="Run by">
              {call.run_by_node ? (
                <NodeChip id={call.run_by_node.id} type="institution" label={runBy} size="sm" />
              ) : (
                <p className="text-sm">{runBy}</p>
              )}
            </Block>
          )}
          {(call.ethics_reference || call.ethics_body || call.registry_id) && (
            <Block title="Ethics and registry" testId="call-ethics">
              <Facts
                rows={[
                  call.ethics_body ? ["Approved by", call.ethics_body] : null,
                  call.ethics_reference ? ["Reference", <span key="r" className="font-mono text-xs">{call.ethics_reference}</span>] : null,
                  call.registry_id
                    ? [
                        "Registry",
                        call.registry_url ? (
                          <ExternalLink key="reg" href={call.registry_url} testId="call-registry-link">
                            <span className="font-mono text-xs">{call.registry_id}</span>
                          </ExternalLink>
                        ) : (
                          <span key="reg" className="font-mono text-xs">{call.registry_id}</span>
                        ),
                      ]
                    : null,
                ]}
              />
            </Block>
          )}
          {(opens || closes || published) && (
            <Block title="Dates">
              <Facts rows={[published ? ["Listed", published] : null, opens ? ["Opens", opens] : null, closes ? ["Closes", closes] : null]} />
            </Block>
          )}
          {call.external_url && (preview || expert) && (
            <Block title="Study page">
              <p className="text-sm">
                <ExternalLink href={call.external_url}>{hostname(call.external_url)}</ExternalLink>
              </p>
            </Block>
          )}
          <p className="flex items-start gap-1.5 text-xs text-muted-foreground" data-testid="call-review-badge">
            <ShieldCheck className="mt-px size-3.5 shrink-0" aria-hidden />
            {call.review_badge}
          </p>
        </aside>
      </div>
    </article>
  );
}

function hostname(url: string) {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

type Load = { kind: "loading" } | { kind: "ready"; call: Call } | { kind: "error"; error: ApiError | null };

/** `/calls/[id]`: one published call for a signed-in reader. */
export function CallView({ id }: { id: string }) {
  const { user, status } = useSession();
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const userId = user?.id ?? null;

  useEffect(() => {
    if (!userId) return;
    let live = true;
    getCall({ path: { call_id: id }, meta: { quiet: true }, cache: "no-store" }).then(({ data, error }) => {
      if (!live) return;
      if (data) setLoad({ kind: "ready", call: data });
      else setLoad({ kind: "error", error: routeGlobalError(error) });
    });
    return () => {
      live = false;
    };
  }, [id, userId]);

  const back = (
    <Link href="/calls" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground" data-testid="calls-back">
      <ArrowLeft className="size-4" aria-hidden /> All open calls
    </Link>
  );

  if (status !== "loading" && !user) {
    return (
      <div className="space-y-6">
        {back}
        <SignInPrompt
          title="Sign in to see this call"
          description="Surveys, studies and trials from verified researchers and doctors. Nothing about what you read is stored."
          returnTo={`/calls/${encodeURIComponent(id)}`}
        />
      </div>
    );
  }
  if (status === "loading" || load.kind === "loading") {
    return (
      <div className="space-y-4" aria-busy="true" aria-label="Loading the call">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-9 w-2/3" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (load.kind === "error") {
    const gone = load.error?.code === "not_found" || load.error?.code === "validation_error";
    return (
      <div className="space-y-4" data-testid="call-error">
        {back}
        <p className="text-sm text-muted-foreground">{gone ? "This call is closed or no longer listed." : callErrorText(load.error)}</p>
        {!gone && (
          <Button variant="outline" size="sm" onClick={() => window.location.reload()}>
            Try again
          </Button>
        )}
      </div>
    );
  }
  return (
    <div className="space-y-6">
      {back}
      <CallDetail call={load.call} />
    </div>
  );
}
