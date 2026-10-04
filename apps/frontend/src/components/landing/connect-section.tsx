import { BadgeCheck, Bell, Check } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import { CONNECT_HREF, CONNECT_STATUS, type ConnectItem, type ConnectStatus } from "./landing-config";
import { SectionHead } from "./section-head";

/** Small mock UIs built from the app's own styles. Illustrations only. */
function FollowMock() {
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg border bg-card px-3 py-2.5">
      <span className="flex items-center gap-2 text-sm font-medium">
        <span className="size-2 rounded-full bg-node-disease" />
        Dravet syndrome
      </span>
      <span className="inline-flex h-7 items-center gap-1 rounded-full bg-primary/15 px-2.5 text-xs font-medium text-foreground">
        <Bell className="size-3.5 fill-current text-primary" />
        Following
      </span>
    </div>
  );
}

function StudyMock() {
  return (
    <div className="rounded-lg border bg-card px-3 py-2.5">
      <p className="text-sm font-medium">Sleep survey</p>
      <p className="mt-1.5 inline-flex items-center gap-1 text-xs text-muted-foreground">
        <BadgeCheck className="size-3.5 text-confidence-high" />
        ORCID iD confirmed
      </p>
    </div>
  );
}

function ChooseMock() {
  const items: Array<[string, boolean]> = [
    ["Age range", true],
    ["Symptoms", true],
    ["Country", false],
  ];
  return (
    <div className="rounded-lg border bg-card px-3 py-2.5">
      <ul className="space-y-1.5">
        {items.map(([label, on]) => (
          <li key={label} className="flex items-center gap-2 text-sm">
            <span
              className={cn(
                "flex size-4 items-center justify-center rounded-[4px] border",
                on ? "border-primary bg-primary text-primary-foreground" : "border-input bg-background",
              )}
            >
              {on && <Check className="size-3" strokeWidth={3} />}
            </span>
            <span className={cn(!on && "text-muted-foreground")}>{label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const STEPS: Array<{ key: ConnectItem; title: string; mock: React.ReactNode }> = [
  { key: "follow", title: "Follow a disease", mock: <FollowMock /> },
  { key: "calls", title: "Expert posts a study", mock: <StudyMock /> },
  { key: "choose", title: "You choose to answer", mock: <ChooseMock /> },
];

/** S4: experts ask, patients decide. Each card is "coming" until its stage lands (landing-config). */
export function ConnectSection() {
  return (
    <section aria-labelledby="connect-heading" className="mx-auto w-full max-w-5xl px-4 py-12 sm:px-6 sm:py-14" data-testid="connect-section">
      <SectionHead
        id="connect-heading"
        title="Experts ask. Patients decide."
        sub="Patients are never listed or searchable. They choose whom to answer."
      />
      <ol className="mt-10 grid gap-4 sm:grid-cols-3">
        {STEPS.map((s, i) => {
          const status = CONNECT_STATUS[s.key] as ConnectStatus;
          const href = status === "live" ? CONNECT_HREF[s.key] : undefined;
          const body = (
            <>
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Example</span>
                {status === "coming" && (
                  <Badge variant="outline" className="bg-background text-muted-foreground">
                    Coming soon
                  </Badge>
                )}
              </div>
              <div aria-hidden className="mt-4">
                {s.mock}
              </div>
              <h3 className="mt-4 text-[15px] font-semibold tracking-tight">
                <span className="mr-1.5 font-mono text-[11px] font-normal text-muted-foreground tabular">0{i + 1}</span>
                {s.title}
              </h3>
            </>
          );
          const card = cn(
            "flex h-full flex-col rounded-xl p-4",
            status === "coming" ? "border border-dashed border-muted-foreground/40 bg-muted/30" : "border bg-card",
          );
          return (
            <li key={s.key} data-testid={`connect-${s.key}`} data-status={status}>
              {href ? (
                <Link href={href} className={cn(card, "outline-none transition-colors hover:border-primary/50 focus-visible:ring-3 focus-visible:ring-ring/50")}>
                  {body}
                </Link>
              ) : (
                <div className={card}>{body}</div>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
