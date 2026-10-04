"use client";

// Smooth reveal of streamed text, shared by Dr. Wu's answers and the Atlas summary.
// Text that has arrived is revealed word by word at a steady pace, however it arrived (one
// chunk, a few, or a stream); each word fades in softly. The pace adapts: about 28 words a
// second, faster while a lot is waiting, so a summary of 60 to 100 words takes about 3 s and a
// long answer about 6 to 8 s. No animation under prefers-reduced-motion. Screen readers get the
// complete text once (an sr-only copy), never the word-by-word spans.

import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/** The calm pace, in words a second; the reveal never goes slower than this. */
export const REVEAL_BASE_WPS = 28;
/** What is waiting is revealed within about this many seconds (faster than the base pace when a lot waits). */
export const REVEAL_HORIZON_S = 2.4;
/** The fade of one word (the `.smooth-word` animation in globals.css). */
export const REVEAL_FADE_MS = 180;

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

export function useReducedMotion(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mq = window.matchMedia(REDUCED_MOTION);
      mq.addEventListener("change", onChange);
      return () => mq.removeEventListener("change", onChange);
    },
    () => window.matchMedia(REDUCED_MOTION).matches,
    () => false,
  );
}

/** The end offset of each word (with its trailing space) in `text`. */
function wordEnds(text: string): number[] {
  const ends: number[] = [];
  for (const m of text.matchAll(/\S+\s*/g)) ends.push(m.index + m[0].length);
  return ends;
}

function endOf(text: string, ends: number[], words: number): number {
  const n = Math.floor(words);
  if (n >= ends.length) return text.length;
  return n <= 0 ? 0 : ends[n - 1];
}

/**
 * How far each keyed reveal got, so a second view of the same live turn (the dock, then the
 * full page) continues where the first was instead of starting over. In memory only: it holds
 * word counts and times, no text.
 */
const progress = new Map<string, { words: number; at: number }>();
const MAX_KEYS = 50;

function record(key: string, words: number) {
  progress.delete(key);
  progress.set(key, { words, at: performance.now() });
  if (progress.size > MAX_KEYS) progress.delete(progress.keys().next().value!);
}

/** Where a reveal with this key would be by now, had it run on at the base pace. */
function resumeAt(key: string | null | undefined): number {
  const p = key ? progress.get(key) : undefined;
  return p ? p.words + ((performance.now() - p.at) / 1000) * REVEAL_BASE_WPS : 0;
}

/** A reveal with this key was shown live in this tab (it may still be running). */
export function hasRevealProgress(key: string | null | undefined): boolean {
  return !!key && progress.has(key);
}

export type Reveal = {
  /** Characters of the text to show (always at a word boundary). */
  shown: number;
  /** Everything has been revealed and its fade has ended. */
  done: boolean;
  /** Words are being animated right now (render the spans, hide them from screen readers). */
  active: boolean;
};

/**
 * Reveal `text` smoothly as it grows. `animate: false` (a stored reply) and reduced motion show
 * it at once. With `key`, a remount continues where the last view of that key would be by now.
 * A text that no longer starts with what was shown (a new attempt) starts over.
 */
export function useSmoothReveal(text: string, { animate = true, key }: { animate?: boolean; key?: string | null } = {}): Reveal {
  const reduced = useReducedMotion();
  const on = animate && !reduced;
  const ends = useMemo(() => wordEnds(text), [text]);
  const cursor = useRef<number | null>(null);
  const [shownText, setShownText] = useState(() => (on ? text.slice(0, endOf(text, ends, resumeAt(key))) : text));
  const [doneText, setDoneText] = useState<string | null>(() => (shownText.length >= text.length ? text : null));
  const at = text.startsWith(shownText) ? shownText.length : 0;

  useEffect(() => {
    if (!on) return;
    let pos = cursor.current ?? Math.max(resumeAt(key), wordEnds(shownText).length);
    if (!text.startsWith(shownText)) pos = 0;
    cursor.current = pos;
    if (endOf(text, ends, pos) >= text.length && shownText.length >= text.length) return;
    let raf = 0;
    let last = performance.now();
    let shownLen = text.startsWith(shownText) ? shownText.length : 0;
    const tick = (now: number) => {
      const dt = Math.min(0.25, Math.max(0, (now - last) / 1000));
      last = now;
      const total = ends.length;
      // The calm base pace, faster while a lot waits: what is waiting is shown within about REVEAL_HORIZON_S.
      const rate = Math.max(REVEAL_BASE_WPS, (total - pos) / REVEAL_HORIZON_S);
      if (pos < total) pos = Math.min(total, pos + rate * dt);
      cursor.current = pos;
      const end = endOf(text, ends, pos);
      if (end !== shownLen) {
        shownLen = end;
        setShownText(text.slice(0, end));
      }
      if (key) record(key, pos);
      if (end < text.length) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // `shownText` is read only to pick up where the reveal stands; the loop drives it from here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [on, text, ends, key]);

  // "Done" waits for the last word's fade, so the spans are not swapped for plain text mid-fade.
  const full = at >= text.length;
  useEffect(() => {
    if (!on || !full || doneText === text) return;
    const id = setTimeout(() => setDoneText(text), REVEAL_FADE_MS);
    return () => clearTimeout(id);
  }, [on, full, text, doneText]);

  if (!on) return { shown: text.length, done: true, active: false };
  const done = full && doneText === text;
  return { shown: at, done, active: !done };
}

/** The words of `text` as fading spans, keyed by their offset so a shown word never fades twice. */
export function fadeWords(text: string, offset = 0): ReactNode[] {
  const out: ReactNode[] = [];
  for (const m of text.matchAll(/\s*\S+\s*|\s+/g)) {
    out.push(
      <span key={`w${offset + m.index}`} className="smooth-word">
        {m[0]}
      </span>,
    );
  }
  return out;
}

/**
 * Text revealed by `useSmoothReveal`: while it animates, screen readers get the complete text
 * once (sr-only) and the fading words are hidden from them; afterwards it is plain text.
 */
export function RevealText({ text, reveal }: { text: string; reveal: Reveal }) {
  if (!reveal.active) return <>{text}</>;
  return (
    <>
      <span className="sr-only">{text}</span>
      <span aria-hidden data-smooth-visible="">
        {fadeWords(text.slice(0, reveal.shown))}
      </span>
    </>
  );
}

/**
 * A box whose height follows its content with a short transition while `active`, so a new line
 * of revealed text lets the box grow instead of jumping.
 */
export function GrowSmoothly({ active, className, children }: { active: boolean; className?: string; children: ReactNode }) {
  const inner = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState<number | null>(null);
  useLayoutEffect(() => {
    const el = inner.current;
    if (!active || !el) {
      setHeight(null);
      return;
    }
    const measure = () => setHeight(el.offsetHeight);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [active]);
  return (
    <div
      className={cn(active && "overflow-hidden transition-[height] duration-200 ease-out motion-reduce:transition-none", className)}
      style={active && height !== null ? { height } : undefined}
    >
      <div ref={inner}>{children}</div>
    </div>
  );
}

/**
 * A part of a live reply that comes in after the text: a soft fade and slide, `index` steps
 * after the one before. Without `animate` (a stored reply) it is just shown.
 */
export function riseClass(animate: boolean): string | undefined {
  return animate ? "smooth-rise" : undefined;
}

export function riseStyle(animate: boolean, index: number): React.CSSProperties | undefined {
  return animate ? ({ "--rise-i": index } as React.CSSProperties) : undefined;
}
