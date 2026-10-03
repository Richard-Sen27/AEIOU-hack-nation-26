"use client";

import { Inter } from "next/font/google";

import { cn } from "@/lib/utils";
import { useSession } from "@/components/providers/session-provider";

// OpenAI's approved button formats use Inter; self-hosted by next/font.
const inter = Inter({ subsets: ["latin"], weight: "500", display: "swap" });

/**
 * "Continue with ChatGPT" in one of OpenAI's four approved formats
 * (https://developers.openai.com/siwc/website): 45px high, 20px gutter, 12px
 * gap, 12px radius, 15px/500 text, official logo (public/brand), black or
 * white. We use black on light surfaces and white on dark ones. Do not
 * restyle, recolour or change the text.
 */
export function ContinueWithChatGPT({
  returnTo,
  className,
  size = "default",
  onClick,
}: {
  /** Relative path to come back to after sign-in (defaults to the current page). */
  returnTo?: string;
  className?: string;
  /** `compact` keeps the format but fits the header (36px). */
  size?: "default" | "compact";
  onClick?: () => void;
}) {
  const { signIn } = useSession();
  const compact = size === "compact";
  return (
    <button
      type="button"
      onClick={() => {
        onClick?.();
        signIn(returnTo);
      }}
      className={cn(
        inter.className,
        "inline-flex max-w-full shrink-0 items-center justify-center whitespace-nowrap font-medium tracking-normal",
        "bg-black text-white dark:bg-white dark:text-black",
        "outline-none transition-opacity hover:opacity-90 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        compact
          ? "h-9 gap-2 rounded-[10px] px-3.5 text-[13px] leading-none"
          : "h-[45px] w-[242px] gap-3 rounded-[12px] px-5 text-[15px] leading-[18px]",
        className,
      )}
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- official SVG asset, unmodified */}
      <img
        src="/brand/chatgpt-logo-white.svg"
        alt=""
        width={compact ? 17 : 21}
        height={compact ? 17 : 21}
        className="block flex-none dark:hidden"
      />
      {/* eslint-disable-next-line @next/next/no-img-element -- official SVG asset, unmodified */}
      <img
        src="/brand/chatgpt-logo-black.svg"
        alt=""
        width={compact ? 17 : 21}
        height={compact ? 17 : 21}
        className="hidden flex-none dark:block"
      />
      <span>Continue with ChatGPT</span>
    </button>
  );
}
