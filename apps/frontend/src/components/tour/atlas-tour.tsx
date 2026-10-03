"use client";

import { Popover as PopoverPrimitive } from "@base-ui/react/popover";
import { ArrowLeft, ArrowRight, Bot } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { ConfidenceBadge, OriginBadge } from "@/components/graph-ui";
import { Button } from "@/components/ui/button";
import { announce } from "@/lib/a11y";
import { cn } from "@/lib/utils";

type Step = {
  /** `data-tour` value of the element to point at; none = centred. */
  target?: string;
  title: string;
  body: React.ReactNode;
};

function LineSample({ dash }: { dash?: string }) {
  return (
    <svg width="30" height="8" viewBox="0 0 30 8" aria-hidden className="shrink-0">
      <line x1="1" y1="4" x2="29" y2="4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeDasharray={dash} />
    </svg>
  );
}

export const TOUR_STEPS: Step[] = [
  {
    target: "canvas",
    title: "Every dot is one thing",
    body: (
      <p>
        A dot can be a condition, a gene, a symptom, a patient group or a study. Bigger dots have more
        connections. Scroll or pinch to zoom in and read the names.
      </p>
    ),
  },
  {
    target: "legend",
    title: "Lines show how things are linked",
    body: (
      <ul className="space-y-1.5">
        <li className="flex items-center gap-2">
          <LineSample /> <span><strong className="font-semibold">Solid</strong>: found in a published source.</span>
        </li>
        <li className="flex items-center gap-2">
          <LineSample dash="6 4" /> <span><strong className="font-semibold">Dashed</strong>: a guess from analysis, not proven.</span>
        </li>
        <li className="flex items-center gap-2">
          <LineSample dash="1.5 3" /> <span><strong className="font-semibold">Dotted</strong>: shared by people, not checked yet.</span>
        </li>
      </ul>
    ),
  },
  {
    title: "How sure are we?",
    body: (
      <div className="space-y-2">
        <p>Every link has a badge. More bars means stronger sources. Click a badge to see why.</p>
        <div className="flex flex-wrap items-center gap-1.5">
          <ConfidenceBadge confidence={0.92} />
          <ConfidenceBadge confidence={0.62} />
          <ConfidenceBadge confidence={0.3} />
        </div>
        <p className="flex flex-wrap items-center gap-1.5">
          <OriginBadge origin="observed" /> means data. <OriginBadge origin="inferred" /> means a guess.
        </p>
      </div>
    ),
  },
  {
    target: "find",
    title: "Open a condition",
    body: (
      <p>
        Click a dot, then choose <strong className="font-semibold">Open</strong> to see everything linked to it.
        Or find a name here, or with the search at the top.
      </p>
    ),
  },
  {
    title: "Want help reading it?",
    body: (
      <p className="flex gap-2">
        <Bot className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
        <span>
          Signing in adds Dr. Wu, an AI assistant that explains what you see. Exploring the map stays free,
          with no account.
        </span>
      </p>
    ),
  },
];

function centred() {
  return {
    getBoundingClientRect: () => {
      const x = window.innerWidth / 2;
      const y = window.innerHeight / 2;
      return { x, y, top: y, left: x, right: x, bottom: y, width: 0, height: 0, toJSON: () => ({}) } as DOMRect;
    },
  };
}

function findTarget(name?: string): HTMLElement | null {
  if (!name) return null;
  const el = document.querySelector<HTMLElement>(`[data-tour="${name}"]`);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 ? el : null;
}

/**
 * Guided tour for the Atlas, in very simple language. Short, skippable,
 * keyboard-accessible (←/→ to move, Esc to skip). Built on the Base UI
 * popover primitive, anchored to `[data-tour]` elements.
 */
export function AtlasTour({
  open,
  onOpenChange,
  onBeforeStep,
  steps = TOUR_STEPS,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onBeforeStep?: (target: string | undefined) => void;
  steps?: Step[];
}) {
  const [i, setI] = useState(0);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const step = steps[Math.min(i, steps.length - 1)];
  const last = i === steps.length - 1;

  useEffect(() => {
    if (open) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- restart from step 1 on open
      setI(0);
    }
  }, [open]);

  useEffect(() => {
    if (open) onBeforeStep?.(step.target);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when the step changes
  }, [open, i]);

  // Resolve and spotlight the target after the step's view is in place.
  useLayoutEffect(() => {
    if (!open) return;
    let el: HTMLElement | null = null;
    const id = requestAnimationFrame(() => {
      el = findTarget(step.target);
      setAnchor(el);
      if (el) el.setAttribute("data-tour-active", "");
    });
    announce(`Tour step ${i + 1} of ${steps.length}: ${step.title}`);
    return () => {
      cancelAnimationFrame(id);
      el?.removeAttribute("data-tour-active");
    };
  }, [open, i, step, steps.length]);

  const close = () => onOpenChange(false);
  const go = (d: number) => setI((n) => Math.max(0, Math.min(steps.length - 1, n + d)));

  return (
    <PopoverPrimitive.Root
      open={open}
      modal={false}
      onOpenChange={(o) => {
        if (!o) close();
      }}
    >
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Positioner
          anchor={anchor ?? centred()}
          side={anchor ? "bottom" : "top"}
          align="center"
          sideOffset={anchor ? 10 : -120}
          collisionPadding={12}
          className="isolate z-50"
        >
          <PopoverPrimitive.Popup
            initialFocus={nextRef}
            data-testid="atlas-tour"
            onKeyDown={(e) => {
              if (e.key === "ArrowRight") {
                e.preventDefault();
                if (!last) go(1);
              } else if (e.key === "ArrowLeft") {
                e.preventDefault();
                go(-1);
              }
            }}
            className={cn(
              "w-[min(22rem,calc(100vw-1.5rem))] rounded-xl border bg-popover p-4 text-sm text-popover-foreground shadow-xl ring-1 ring-foreground/10 outline-none",
              "duration-150 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0",
            )}
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="font-mono text-[10.5px] tracking-[0.14em] text-muted-foreground uppercase">
                Tour · {i + 1} of {steps.length}
              </span>
              <span className="flex gap-1" aria-hidden>
                {steps.map((_, n) => (
                  <span key={n} className={cn("h-1 w-4 rounded-full", n <= i ? "bg-primary" : "bg-muted")} />
                ))}
              </span>
            </div>
            <PopoverPrimitive.Title className="mb-1.5 text-base font-semibold tracking-tight">{step.title}</PopoverPrimitive.Title>
            <div className="leading-relaxed text-muted-foreground [&_strong]:text-foreground">{step.body}</div>
            <div className="mt-4 flex items-center gap-2">
              <Button variant="ghost" size="sm" onClick={close} data-testid="tour-skip">
                {last ? "Close" : "Skip tour"}
              </Button>
              <span className="flex-1" />
              {i > 0 && (
                <Button variant="outline" size="sm" onClick={() => go(-1)}>
                  <ArrowLeft data-icon="inline-start" aria-hidden /> Back
                </Button>
              )}
              <Button
                ref={nextRef}
                size="sm"
                onClick={() => (last ? close() : go(1))}
                data-testid="tour-next"
              >
                {last ? "Start exploring" : "Next"}
                {!last && <ArrowRight data-icon="inline-end" aria-hidden />}
              </Button>
            </div>
          </PopoverPrimitive.Popup>
        </PopoverPrimitive.Positioner>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
