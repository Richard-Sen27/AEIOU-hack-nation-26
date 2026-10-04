"use client";

import { Roboto } from "next/font/google";

import { cn } from "@/lib/utils";
import { useSession } from "@/components/providers/session-provider";

// Google's sign-in button guidelines use Roboto Medium; self-hosted by next/font.
const roboto = Roboto({ subsets: ["latin"], weight: "500", display: "swap" });

/**
 * "Continue with Google" per Google's branding guidelines
 * (https://developers.google.com/identity/branding-guidelines): the standard
 * four-colour "G" mark unmodified, Roboto Medium, light theme (#FFFFFF fill,
 * #747775 stroke, #1F1F1F text) and dark theme (#131314, #8E918F, #E3E3E3).
 * Shown only when the API lists `google` in `sign_in_methods`.
 */
export function ContinueWithGoogle({
  returnTo,
  className,
  size = "default",
  onClick,
}: {
  returnTo?: string;
  className?: string;
  size?: "default" | "compact";
  onClick?: () => void;
}) {
  const { signIn } = useSession();
  const compact = size === "compact";
  return (
    <button
      type="button"
      data-testid="continue-with-google"
      onClick={() => {
        onClick?.();
        signIn(returnTo, "google");
      }}
      className={cn(
        roboto.className,
        "inline-flex max-w-full shrink-0 items-center justify-center whitespace-nowrap border font-medium tracking-normal",
        "border-[#747775] bg-white text-[#1F1F1F] dark:border-[#8E918F] dark:bg-[#131314] dark:text-[#E3E3E3]",
        "outline-none transition-opacity hover:opacity-90 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        compact
          ? "h-9 gap-2 rounded-[10px] px-3.5 text-[13px] leading-none"
          : "h-[45px] w-[242px] gap-3 rounded-[12px] px-5 text-[15px] leading-[18px]",
        className,
      )}
    >
      <GoogleMark size={compact ? 16 : 20} />
      <span>Continue with Google</span>
    </button>
  );
}

/** Google's standard "G" logo (unmodified colours and shape). */
function GoogleMark({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden className="block flex-none">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}
