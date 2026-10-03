import { ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

/** A styled native <select>: accessible everywhere, matches the input style. */
export function NativeSelect({ className, children, ...props }: React.ComponentProps<"select">) {
  return (
    <span className={cn("relative inline-flex w-full", className)}>
      <select
        {...props}
        className="h-9 w-full appearance-none rounded-lg border border-input bg-transparent py-1 pr-8 pl-2.5 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50 dark:bg-input/30 [&>option]:bg-popover [&>option]:text-popover-foreground"
      >
        {children}
      </select>
      <ChevronDown
        className="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
    </span>
  );
}
