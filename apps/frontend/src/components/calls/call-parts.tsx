import { ChevronRight, Globe2, MapPin } from "lucide-react";
import Link from "next/link";

import { VerificationLabel } from "@/components/people/verification-label";
import { cn } from "@/lib/utils";

import { ageText, callHref, countryName, formatDate, KIND_META, runByText, STATUS_META, type Call, type CallKind, type CallStatus } from "./call-meta";

export function KindBadge({ kind, className }: { kind: CallKind; className?: string }) {
  const meta = KIND_META[kind];
  return (
    <span
      className={cn("inline-flex h-5 items-center gap-1 rounded-full border px-2 text-[11px] font-medium whitespace-nowrap", className)}
      data-testid="call-kind"
      data-kind={kind}
    >
      <meta.icon className="size-3" style={{ color: "var(--color-node-trial)" }} aria-hidden />
      {meta.label}
    </span>
  );
}

/** Seeded demo data: always visible, never mistaken for a real study. */
export function DemoMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded-full border border-dashed border-status-flag px-2 text-[11px] font-medium whitespace-nowrap text-foreground",
        className,
      )}
      data-testid="call-demo"
    >
      Demo, not a real study
    </span>
  );
}

export function StatusBadge({ status, expired }: { status: CallStatus; expired?: boolean }) {
  const meta = STATUS_META[status];
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded-full px-2 text-[11px] font-medium whitespace-nowrap",
        meta.tone === "live" && "bg-primary/15 text-foreground",
        meta.tone === "wait" && "bg-accent text-accent-foreground",
        meta.tone === "bad" && "bg-destructive/10 text-destructive",
        meta.tone === "muted" && "bg-muted text-muted-foreground",
      )}
      data-testid="call-status"
      data-status={status}
    >
      {expired ? "Past closing date" : meta.label}
    </span>
  );
}

/** Where and for whom, as a short line of facts. */
export function CallFacts({ call, className }: { call: Call; className?: string }) {
  const age = ageText(call);
  const closes = formatDate(call.closes_at);
  const where = call.countries.length ? call.countries.slice(0, 3).map(countryName).join(", ") + (call.countries.length > 3 ? ` +${call.countries.length - 3}` : "") : null;
  const facts = [
    call.remote ? { icon: Globe2, text: "Remote" } : null,
    where ? { icon: MapPin, text: where } : null,
    age ? { text: age } : null,
    call.children_ok && !call.adults_only ? { text: "Children can take part" } : null,
    closes ? { text: `Until ${closes}` } : null,
  ].filter(Boolean) as Array<{ icon?: typeof Globe2; text: string }>;
  if (!facts.length) return null;
  return (
    <ul className={cn("flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground", className)}>
      {facts.map((f) => (
        <li key={f.text} className="inline-flex items-center gap-1">
          {f.icon && <f.icon className="size-3.5" aria-hidden />}
          {f.text}
        </li>
      ))}
    </ul>
  );
}

/** One call in a list: links to its page. */
export function CallRow({ call, compact = false }: { call: Call; compact?: boolean }) {
  const runBy = call.publisher?.name ?? runByText(call);
  const diseases = call.diseases.map((d) => d.label ?? d.id);
  return (
    <Link
      href={callHref(call.id)}
      className={cn("group flex items-start gap-3 rounded-xl border bg-card transition-colors hover:bg-muted/60", compact ? "px-3 py-2.5" : "px-4 py-3.5")}
      data-testid="call-row"
    >
      <span className="min-w-0 flex-1 space-y-1.5">
        <span className="flex flex-wrap items-center gap-1.5">
          <KindBadge kind={call.kind} />
          {call.demo && <DemoMark />}
          {call.publisher?.verification.simulated && <VerificationLabel verification={call.publisher.verification} short />}
        </span>
        <span className={cn("block font-medium text-pretty", compact ? "text-sm" : "text-[15px]")}>{call.title}</span>
        {!compact && (
          <span className="block truncate text-xs text-muted-foreground">
            {diseases.slice(0, 3).join(" · ")}
            {diseases.length > 3 && ` +${diseases.length - 3}`}
            {runBy && <> · {runBy}</>}
          </span>
        )}
        {!compact && <CallFacts call={call} />}
      </span>
      <ChevronRight className="mt-1 size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden />
    </Link>
  );
}
