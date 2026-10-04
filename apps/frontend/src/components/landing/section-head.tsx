import { cn } from "@/lib/utils";

/** Heading of a landing section: a few words and at most one line under them. */
export function SectionHead({ id, title, sub, className }: { id: string; title: string; sub: string; className?: string }) {
  return (
    <div className={cn("mx-auto max-w-2xl text-center", className)}>
      <h2 id={id} className="text-2xl font-semibold tracking-tight text-balance sm:text-3xl">
        {title}
      </h2>
      <p className="mt-2 text-base text-pretty text-muted-foreground">{sub}</p>
    </div>
  );
}
