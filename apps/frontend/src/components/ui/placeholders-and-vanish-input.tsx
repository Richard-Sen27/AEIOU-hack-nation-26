"use client";

// Aceternity UI "Placeholders and Vanish Input", adapted for Amber:
// theme tokens instead of hard-coded colours, an accessible label, typed
// particle data, and no animation under prefers-reduced-motion.

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

type Particle = { x: number; y: number; r: number; color: string };

export function PlaceholdersAndVanishInput({
  placeholders,
  onChange,
  onSubmit,
  ariaLabel,
  className,
  maxLength,
  name,
}: {
  placeholders: string[];
  onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  /** Receives the submitted value (the input clears itself afterwards). */
  onSubmit: (value: string, e: React.FormEvent<HTMLFormElement>) => void;
  ariaLabel: string;
  className?: string;
  maxLength?: number;
  name?: string;
}) {
  const reduceMotion = useReducedMotion();
  const [currentPlaceholder, setCurrentPlaceholder] = useState(0);

  useEffect(() => {
    if (reduceMotion || placeholders.length < 2) return;
    let interval: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      interval ??= setInterval(() => setCurrentPlaceholder((p) => (p + 1) % placeholders.length), 3500);
    };
    const stop = () => {
      if (interval) clearInterval(interval);
      interval = null;
    };
    const onVisibility = () => (document.visibilityState === "visible" ? start() : stop());
    start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [placeholders, reduceMotion]);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const particlesRef = useRef<Particle[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState("");
  const [animating, setAnimating] = useState(false);

  const draw = useCallback(() => {
    const input = inputRef.current;
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d", { willReadFrequently: true });
    if (!input || !canvas || !ctx) return;
    canvas.width = 800;
    canvas.height = 800;
    ctx.clearRect(0, 0, 800, 800);
    const styles = getComputedStyle(input);
    const fontSize = parseFloat(styles.getPropertyValue("font-size"));
    ctx.font = `${fontSize * 2}px ${styles.fontFamily}`;
    ctx.fillStyle = styles.color;
    ctx.fillText(input.value, 16, 40);
    const data = ctx.getImageData(0, 0, 800, 800).data;
    const next: Particle[] = [];
    for (let y = 0; y < 800; y++) {
      const row = 4 * y * 800;
      for (let x = 0; x < 800; x++) {
        const e = row + 4 * x;
        if (data[e + 3] > 0) {
          next.push({ x, y, r: 1, color: `rgba(${data[e]}, ${data[e + 1]}, ${data[e + 2]}, ${data[e + 3] / 255})` });
        }
      }
    }
    particlesRef.current = next;
  }, []);

  const animate = (start: number) => {
    const frame = (pos: number) => {
      requestAnimationFrame(() => {
        const kept: Particle[] = [];
        for (const p of particlesRef.current) {
          if (p.x < pos) kept.push(p);
          else if (p.r > 0) {
            p.x += Math.random() > 0.5 ? 1 : -1;
            p.y += Math.random() > 0.5 ? 1 : -1;
            p.r -= 0.05 * Math.random();
            kept.push(p);
          }
        }
        particlesRef.current = kept;
        const ctx = canvasRef.current?.getContext("2d");
        if (ctx) {
          ctx.clearRect(pos, 0, 800, 800);
          for (const p of kept) {
            if (p.x > pos) {
              ctx.beginPath();
              ctx.rect(p.x, p.y, p.r, p.r);
              ctx.fillStyle = p.color;
              ctx.strokeStyle = p.color;
              ctx.stroke();
            }
          }
        }
        if (kept.length > 0) frame(pos - 8);
        else {
          setValue("");
          setAnimating(false);
        }
      });
    };
    frame(start);
  };

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const submitted = inputRef.current?.value.trim() ?? "";
    if (!submitted || animating) return;
    onSubmit(submitted, e);
    if (reduceMotion) {
      setValue("");
      return;
    }
    setAnimating(true);
    draw();
    const maxX = particlesRef.current.reduce((m, p) => (p.x > m ? p.x : m), 0);
    animate(maxX);
  };

  return (
    <form
      role="search"
      className={cn(
        "relative mx-auto h-14 w-full max-w-xl overflow-hidden rounded-full border bg-card shadow-md transition duration-200 focus-within:ring-2 focus-within:ring-ring/60",
        className,
      )}
      onSubmit={handleSubmit}
    >
      <canvas
        aria-hidden
        className={cn(
          "pointer-events-none absolute top-[20%] left-2 origin-top-left scale-50 transform pr-20 text-base sm:left-8",
          animating ? "opacity-100" : "opacity-0",
        )}
        ref={canvasRef}
      />
      <input
        onChange={(e) => {
          if (!animating) {
            setValue(e.target.value);
            onChange?.(e);
          }
        }}
        ref={inputRef}
        value={value}
        name={name}
        maxLength={maxLength}
        type="text"
        autoComplete="off"
        aria-label={ariaLabel}
        className={cn(
          "relative z-10 h-full w-full rounded-full border-none bg-transparent pr-16 pl-5 text-base text-foreground focus:ring-0 focus:outline-none sm:pl-8",
          animating && "text-transparent",
        )}
      />
      <button
        disabled={!value}
        type="submit"
        aria-label="Submit"
        className="absolute top-1/2 right-2.5 z-10 flex size-9 -translate-y-1/2 items-center justify-center rounded-full bg-primary text-primary-foreground transition duration-200 disabled:bg-muted disabled:text-muted-foreground"
      >
        <motion.svg
          xmlns="http://www.w3.org/2000/svg"
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="size-4"
          aria-hidden
        >
          <path stroke="none" d="M0 0h24v24H0z" fill="none" />
          <motion.path
            d="M5 12l14 0"
            initial={{ strokeDasharray: "50%", strokeDashoffset: "50%" }}
            animate={{ strokeDashoffset: value ? 0 : "50%" }}
            transition={{ duration: 0.3, ease: "linear" }}
          />
          <path d="M13 18l6 -6" />
          <path d="M13 6l6 6" />
        </motion.svg>
      </button>
      <div className="pointer-events-none absolute inset-0 flex items-center rounded-full" aria-hidden>
        <AnimatePresence mode="wait">
          {!value && (
            <motion.p
              initial={{ y: 5, opacity: 0 }}
              key={`placeholder-${currentPlaceholder}`}
              animate={{ y: 0, opacity: 1 }}
              exit={{ y: -15, opacity: 0 }}
              transition={{ duration: 0.3, ease: "linear" }}
              className="w-[calc(100%-4.5rem)] truncate pl-5 text-left text-base font-normal text-muted-foreground sm:pl-8"
            >
              {placeholders[currentPlaceholder]}
            </motion.p>
          )}
        </AnimatePresence>
      </div>
    </form>
  );
}
