"use client";

import { ArrowRight } from "lucide-react";

import { useSearch } from "@/components/search/search-provider";
import { buttonVariants } from "@/components/ui/button";

/** The guide's "Try it" for the global search: opens the same dialog as ⌘K. */
export function OpenSearchButton({ className }: { className?: string }) {
  const { openSearch } = useSearch();
  return (
    <button
      type="button"
      onClick={() => openSearch()}
      className={buttonVariants({ variant: "outline", size: "sm", className: ["shrink-0", className].filter(Boolean).join(" ") })}
      data-testid="guide-try"
      data-try="search"
    >
      Try it <ArrowRight data-icon="inline-end" aria-hidden />
    </button>
  );
}
