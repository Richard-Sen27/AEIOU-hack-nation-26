import { ArrowRight, Database, Globe, HeartHandshake, LogIn, ShieldCheck, Stethoscope } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { AUDIENCE_LABEL, type Audience, type Feature, GUIDE, GUIDE_TOC, TRUST } from "@/components/guide/guide-content";
import { GuideSnippet } from "@/components/guide/guide-snippets";
import { OpenSearchButton } from "@/components/guide/open-search-button";
import { PageContainer, PageHeader } from "@/components/shell/page-placeholder";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: "Getting started",
  description: "Every feature of Amber in short: exploring the atlas, Dr. Wu, your account, studies, expert cards and messages.",
};

const AUDIENCE_ICON = {
  everyone: Globe,
  "signed-in": LogIn,
  patients: HeartHandshake,
  experts: Stethoscope,
} as const;

function AudienceBadge({ audience, className }: { audience: Audience; className?: string }) {
  const Icon = AUDIENCE_ICON[audience];
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center gap-1 rounded-full border px-2 text-[11px] font-medium whitespace-nowrap",
        audience === "everyone" ? "text-muted-foreground" : "border-primary/40 bg-primary/10 text-foreground",
        className,
      )}
      data-testid="guide-audience"
    >
      <Icon className="size-3" aria-hidden />
      {AUDIENCE_LABEL[audience]}
    </span>
  );
}

function TryIt({ feature }: { feature: Feature }) {
  if (feature.href === "search") return <OpenSearchButton />;
  return (
    <Link
      href={feature.href}
      className={buttonVariants({ variant: "outline", size: "sm", className: "shrink-0" })}
      data-testid="guide-try"
      data-try={feature.id}
    >
      Try it<span className="sr-only">: {feature.title}</span>
      <ArrowRight data-icon="inline-end" aria-hidden />
    </Link>
  );
}

function FeatureCard({ feature }: { feature: Feature }) {
  const Icon = feature.icon;
  return (
    <li
      id={feature.id}
      className="flex scroll-mt-20 flex-col gap-2.5 rounded-xl border bg-card p-4"
      data-testid="guide-feature"
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="flex min-w-0 items-center gap-2 text-[15px] leading-snug font-semibold tracking-tight">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
            <Icon className="size-4" aria-hidden />
          </span>
          {feature.title}
        </h3>
        <TryIt feature={feature} />
      </div>
      <p className="text-sm text-pretty text-muted-foreground">
        <AudienceBadge audience={feature.audience} className="mr-1.5 align-[1px]" />
        {feature.what}
      </p>
      {feature.snippet && (
        <div className="rounded-lg border border-dashed bg-background/60 px-3 py-2.5">
          <GuideSnippet name={feature.snippet} />
        </div>
      )}
      <ol className="space-y-1.5 text-sm">
        {feature.steps.map((s, i) => (
          <li key={s} className="flex gap-2.5">
            <span
              aria-hidden
              className="mt-px flex size-5 shrink-0 items-center justify-center rounded-full border bg-background font-mono text-[10px] text-muted-foreground"
            >
              {i + 1}
            </span>
            <span className="min-w-0 text-pretty">{s}</span>
          </li>
        ))}
      </ol>
    </li>
  );
}

function SectionHeading({ id, title, sub }: { id: string; title: string; sub: string }) {
  return (
    <div className="mb-4">
      <h2 id={`${id}-h`} className="text-xl font-semibold tracking-tight">
        {title}
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">{sub}</p>
    </div>
  );
}

export default function GuidePage() {
  return (
    <PageContainer className="max-w-6xl">
      <PageHeader
        eyebrow="Guide"
        title="Getting started with Amber"
        description="A map of rare diseases built from public sources. Each card is one feature: what it is, how to use it, and a link to try it."
      />

      <ul className="mt-5 flex flex-wrap gap-2" aria-label="Who a feature is for">
        {(Object.keys(AUDIENCE_LABEL) as Audience[]).map((a) => (
          <li key={a}>
            <AudienceBadge audience={a} />
          </li>
        ))}
      </ul>

      {/* Phones and tablets: the sections as a wrapping row (no sideways scrolling). */}
      <nav aria-label="Sections" className="mt-6 lg:hidden">
        <ul className="flex flex-wrap gap-1.5 text-sm">
          {GUIDE_TOC.map((t) => (
            <li key={t.id}>
              <a href={`#${t.id}`} className="inline-flex h-8 items-center rounded-full border bg-card px-3 text-muted-foreground hover:text-foreground">
                {t.title}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <div className="mt-8 grid gap-10 lg:mt-10 lg:grid-cols-[200px_minmax(0,1fr)]">
        <nav aria-label="On this page" className="hidden lg:block">
          <div className="sticky top-20">
            <p className="mb-2 font-mono text-[11px] tracking-[0.14em] text-muted-foreground uppercase">On this page</p>
            <ol className="space-y-0.5 text-sm">
              {GUIDE_TOC.map((t) => (
                <li key={t.id}>
                  <a href={`#${t.id}`} className="block rounded-md px-2 py-1 text-muted-foreground hover:bg-muted hover:text-foreground">
                    {t.title}
                  </a>
                </li>
              ))}
            </ol>
          </div>
        </nav>

        <div className="min-w-0 space-y-12">
          {GUIDE.map((section) => (
            <section key={section.id} id={section.id} aria-labelledby={`${section.id}-h`} className="scroll-mt-20" data-testid="guide-section">
              <SectionHeading id={section.id} title={section.title} sub={section.sub} />
              <ul className="grid gap-4 md:grid-cols-2 md:items-start">
                {section.features.map((f) => (
                  <FeatureCard key={f.id} feature={f} />
                ))}
              </ul>
            </section>
          ))}

          <section id="trust" aria-labelledby="trust-h" className="scroll-mt-20" data-testid="guide-section">
            <SectionHeading id="trust" title="Trust and privacy" sub="What Amber is, and what happens to your data." />
            <ul className="grid gap-px overflow-hidden rounded-xl border bg-border sm:grid-cols-3">
              {TRUST.map((t) => (
                <li key={t.title} className="bg-card p-4">
                  <p className="flex items-center gap-2 text-sm font-semibold">
                    <t.icon className="size-4 shrink-0 text-primary" aria-hidden />
                    {t.title}
                  </p>
                  <p className="mt-1 text-sm text-pretty text-muted-foreground">{t.body}</p>
                </li>
              ))}
            </ul>
            <div className="mt-4 flex flex-wrap gap-2">
              <Link href="/about-data" className={buttonVariants({ variant: "outline", size: "sm" })} data-testid="guide-try" data-try="about-data">
                <Database data-icon="inline-start" aria-hidden /> Where the data comes from
              </Link>
              <Link href="/privacy" className={buttonVariants({ variant: "outline", size: "sm" })} data-testid="guide-try" data-try="privacy">
                <ShieldCheck data-icon="inline-start" aria-hidden /> Privacy notice
              </Link>
            </div>
          </section>
        </div>
      </div>
    </PageContainer>
  );
}
