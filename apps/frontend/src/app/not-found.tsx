import { Compass } from "lucide-react";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default function NotFound() {
  return (
    <div className="mx-auto flex w-full max-w-lg flex-1 flex-col items-center justify-center gap-4 px-4 py-20 text-center">
      <span className="flex size-11 items-center justify-center rounded-full bg-accent text-accent-foreground">
        <Compass className="size-5" aria-hidden />
      </span>
      <p className="font-mono text-xs uppercase tracking-[0.16em] text-muted-foreground">404</p>
      <h1 className="text-xl font-semibold tracking-tight">This page is not on the map</h1>
      <p className="text-sm text-muted-foreground">
        Mistyped, or renamed in a newer version of the atlas.
      </p>
      <div className="flex gap-2">
        <Link href="/atlas" className={cn(buttonVariants())}>
          Open the atlas
        </Link>
        <Link href="/" className={cn(buttonVariants({ variant: "outline" }))}>
          Go home
        </Link>
      </div>
    </div>
  );
}
