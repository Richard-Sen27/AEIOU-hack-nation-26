import { Construction } from "lucide-react";

import { cn } from "@/lib/utils";

/** Standard page frame: eyebrow, title, lede. Use for real pages too. */
export function PageHeader({
  eyebrow,
  title,
  description,
  children,
  className,
}: {
  eyebrow?: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div className="max-w-2xl space-y-2">
        {eyebrow && (
          <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-muted-foreground">{eyebrow}</p>
        )}
        <h1 className="text-2xl font-semibold tracking-tight text-balance sm:text-3xl">{title}</h1>
        {description && <p className="text-[15px] leading-relaxed text-pretty text-muted-foreground">{description}</p>}
      </div>
      {children && <div className="flex shrink-0 items-center gap-2">{children}</div>}
    </header>
  );
}

export function PageContainer({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("mx-auto w-full max-w-[1440px] px-4 py-8 sm:px-6 sm:py-10", className)}>{children}</div>;
}

/**
 * Informative placeholder body for a route a feature agent still has to
 * build. Replace the whole page content when implementing the feature.
 */
export function PagePlaceholder({
  eyebrow,
  title,
  description,
  planned,
  children,
}: {
  eyebrow?: string;
  title: React.ReactNode;
  description: React.ReactNode;
  /** What this page will show, from the spec. */
  planned: string[];
  children?: React.ReactNode;
}) {
  return (
    <PageContainer>
      <PageHeader eyebrow={eyebrow} title={title} description={description} />
      <section
        aria-label="Coming soon"
        className="bg-atlas-grid mt-8 rounded-xl border border-dashed bg-card/40 p-6 sm:p-8"
      >
        <div className="flex items-center gap-2 text-sm font-medium">
          <Construction className="size-4 text-primary" aria-hidden />
          This view is being built
        </div>
        <ul className="mt-4 grid gap-2 text-sm text-muted-foreground sm:grid-cols-2">
          {planned.map((p) => (
            <li key={p} className="flex gap-2">
              <span className="mt-2 size-1 shrink-0 rounded-full bg-muted-foreground/60" aria-hidden />
              <span>{p}</span>
            </li>
          ))}
        </ul>
        {children && <div className="mt-6">{children}</div>}
      </section>
    </PageContainer>
  );
}
