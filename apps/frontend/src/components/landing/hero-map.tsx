"use client";

import { ArrowRight, Pause, Play } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { AtlasPreview } from "./atlas-preview";
import { cycleIds } from "./atlas-preview-model";
import { HERO_CYCLE_IDS, HERO_MAX_LINKS } from "./landing-config";
import { useAtlasPreview } from "./use-atlas-preview";

function subscribeReducedMotion(cb: () => void) {
  const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
}
const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function subscribeVisibility(cb: () => void) {
  document.addEventListener("visibilitychange", cb);
  return () => document.removeEventListener("visibilitychange", cb);
}
const pageHidden = () => document.visibilityState === "hidden";

/** Whether the element is on screen right now. */
function useOnScreen(ref: React.RefObject<Element | null>) {
  const [on, setOn] = useState(true);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([entry]) => setOn(entry.isIntersecting));
    io.observe(el);
    return () => io.disconnect();
  }, [ref]);
  return on;
}

/**
 * The live map as a wide strip under the hero. It cycles through a few nodes of
 * different kinds (landing-config), drawing each one's real links from the tree
 * payload loaded once; then it starts again. The strip is one link to the Atlas;
 * the pause control is its sibling, not nested in it. The cycle pauses while the
 * pointer or focus is on the map, off screen and in a hidden tab; reduced motion shows the first node
 * statically.
 */
export function HeroMap() {
  const preview = useAtlasPreview();
  const model = preview.status === "ready" ? preview.data : null;
  const ids = useMemo(() => (model ? cycleIds(model, HERO_CYCLE_IDS) : []), [model]);

  const reduce = useSyncExternalStore(subscribeReducedMotion, reducedMotion, () => false);
  const hidden = useSyncExternalStore(subscribeVisibility, pageHidden, () => false);
  const box = useRef<HTMLDivElement>(null);
  const onScreen = useOnScreen(box);
  const [hover, setHover] = useState(false);
  const [focusInside, setFocusInside] = useState(false);
  const [userPaused, setUserPaused] = useState(false);
  const [step, setStep] = useState(0);

  const cycling = !reduce && ids.length > 1;
  const paused = userPaused || hover || focusInside || !onScreen || hidden;
  const focusId = ids.length ? ids[cycling ? step % ids.length : 0] : model?.topDiseaseId ?? null;
  const next = useCallback(() => setStep((s) => s + 1), []);

  return (
    <section className="mx-auto w-full max-w-5xl px-4 pb-8 sm:px-6">
      <div
        ref={box}
        className="relative"
        data-testid="hero-map"
        data-cycle-step={cycling ? step : undefined}
        data-focus={focusId ?? undefined}
        data-paused={cycling ? String(paused) : undefined}
      >
        <Link
          href="/atlas"
          aria-label="Open the Atlas"
          data-testid="atlas-preview"
          data-state={preview.status}
          // Hover and focus on the map pause the cycle; the control (a sibling) does not,
          // so pressing Play starts it at once.
          onPointerEnter={() => setHover(true)}
          onPointerLeave={() => setHover(false)}
          onFocus={() => setFocusInside(true)}
          onBlur={() => setFocusInside(false)}
          className="group relative block rounded-2xl outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <div className="relative aspect-[4/3] w-full overflow-hidden rounded-2xl border bg-card/70 shadow-lg shadow-primary/5 transition-colors group-hover:border-primary/40 sm:aspect-[16/10]">
            {model ? (
              <AtlasPreview
                model={model}
                focusId={focusId}
                maxLinks={HERO_MAX_LINKS}
                showFocusLabel
                cycle={cycling ? { step, paused, onDone: next } : undefined}
              />
            ) : (
              preview.status === "loading" && (
                <div aria-hidden className="absolute inset-0 m-auto size-1/2 animate-pulse rounded-full bg-muted/60 motion-reduce:animate-none" />
              )
            )}
          </div>
          <span className="mx-auto mt-4 flex h-10 w-fit items-center gap-1.5 rounded-full bg-primary px-5 text-sm font-medium text-primary-foreground shadow-md transition-colors group-hover:bg-primary/85">
            Open the Atlas
            <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5 motion-reduce:transition-none" aria-hidden />
          </span>
        </Link>
        {cycling && (
          <button
            type="button"
            onClick={() => setUserPaused((p) => !p)}
            aria-label={userPaused ? "Play the map animation" : "Pause the map animation"}
            title={userPaused ? "Play" : "Pause"}
            data-testid="hero-cycle-toggle"
            className="absolute top-3 right-3 flex size-8 items-center justify-center rounded-full border bg-card/90 text-muted-foreground shadow-xs outline-none transition-colors hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {userPaused ? <Play className="size-3.5" aria-hidden /> : <Pause className="size-3.5" aria-hidden />}
          </button>
        )}
      </div>
    </section>
  );
}
