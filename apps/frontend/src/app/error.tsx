"use client";

import { RotateCcw, TriangleAlert } from "lucide-react";
import Link from "next/link";

import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// No logging here: error messages could echo user input (health data).
export default function RouteError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  return (
    <div className="mx-auto flex w-full max-w-lg flex-1 flex-col items-center justify-center gap-4 px-4 py-20 text-center">
      <span className="flex size-11 items-center justify-center rounded-full bg-destructive/10 text-destructive">
        <TriangleAlert className="size-5" aria-hidden />
      </span>
      <h1 className="text-xl font-semibold tracking-tight">This view could not be shown</h1>
      <p className="text-sm text-muted-foreground">
        The rest of Amber still works.
      </p>
      {error.digest && <p className="font-mono text-xs text-muted-foreground">Reference {error.digest}</p>}
      <div className="flex gap-2">
        <Button onClick={() => retry()}>
          <RotateCcw data-icon="inline-start" aria-hidden /> Try again
        </Button>
        <Link href="/" className={cn(buttonVariants({ variant: "outline" }))}>
          Go home
        </Link>
      </div>
    </div>
  );
}
