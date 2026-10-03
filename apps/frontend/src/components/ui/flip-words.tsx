"use client";

// Aceternity UI "Flip Words", adapted: theme colours, timer cleanup, and a
// static word under prefers-reduced-motion. Screen readers get the full list.

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

export const FlipWords = ({
  words,
  duration = 3000,
  className,
}: {
  words: string[];
  duration?: number;
  className?: string;
}) => {
  const reduceMotion = useReducedMotion();
  const [index, setIndex] = useState(0);
  const [isAnimating, setIsAnimating] = useState(false);

  useEffect(() => {
    if (reduceMotion || isAnimating || words.length < 2) return;
    const t = setTimeout(() => {
      setIndex((i) => (i + 1) % words.length);
      setIsAnimating(true);
    }, duration);
    return () => clearTimeout(t);
  }, [isAnimating, duration, words.length, reduceMotion]);

  const currentWord = words[index] ?? "";

  return (
    <span className="relative inline-block">
      <span className="sr-only">{words.join(", ")}</span>
      <AnimatePresence onExitComplete={() => setIsAnimating(false)}>
        <motion.span
          aria-hidden
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ type: "spring", stiffness: 100, damping: 10 }}
          exit={{ opacity: 0, y: -40, x: 40, filter: "blur(8px)", scale: 2, position: "absolute" }}
          className={cn("relative z-10 inline-block text-left", className)}
          key={currentWord}
        >
          {currentWord.split(" ").map((word, wordIndex) => (
            <motion.span
              key={word + wordIndex}
              initial={{ opacity: 0, y: 10, filter: "blur(8px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              transition={{ delay: wordIndex * 0.3, duration: 0.3 }}
              className="inline-block whitespace-nowrap"
            >
              {word.split("").map((letter, letterIndex) => (
                <motion.span
                  key={word + letterIndex}
                  initial={{ opacity: 0, y: 10, filter: "blur(8px)" }}
                  animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                  transition={{ delay: wordIndex * 0.3 + letterIndex * 0.05, duration: 0.2 }}
                  className="inline-block"
                >
                  {letter}
                </motion.span>
              ))}
              {wordIndex < currentWord.split(" ").length - 1 && <span className="inline-block">&nbsp;</span>}
            </motion.span>
          ))}
        </motion.span>
      </AnimatePresence>
    </span>
  );
};
