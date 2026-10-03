import { cn } from "@/lib/utils";

/** Layout for layered notices: a short summary first, a table of contents, then sections. */
export function NoticeLayout({
  toc,
  children,
}: {
  toc: Array<{ id: string; title: string }>;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-10 lg:grid-cols-[220px_minmax(0,1fr)]">
      <nav aria-label="On this page" className="hidden lg:block">
        <p className="mb-2 font-mono text-[11px] tracking-[0.14em] text-muted-foreground uppercase">On this page</p>
        <ol className="sticky top-20 space-y-0.5 text-sm">
          {toc.map((t) => (
            <li key={t.id}>
              <a href={`#${t.id}`} className="block rounded-md px-2 py-1 text-muted-foreground hover:bg-muted hover:text-foreground">
                {t.title}
              </a>
            </li>
          ))}
        </ol>
      </nav>
      <div className="min-w-0 max-w-3xl space-y-12">{children}</div>
    </div>
  );
}

export function NoticeSection({
  id,
  title,
  children,
  className,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-h`} className={cn("scroll-mt-20 space-y-4", className)}>
      <h2 id={`${id}-h`} className="text-xl font-semibold tracking-tight">
        {title}
      </h2>
      <div className="space-y-4 text-[15px] leading-relaxed text-muted-foreground [&_strong]:font-medium [&_strong]:text-foreground">
        {children}
      </div>
    </section>
  );
}

export function NoticeSub({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <h3 className="text-base font-semibold text-foreground">{title}</h3>
      {children}
    </div>
  );
}

export function List({ items }: { items: React.ReactNode[] }) {
  return (
    <ul className="list-disc space-y-1.5 pl-5 marker:text-muted-foreground/70">
      {items.map((it, i) => (
        <li key={i}>{it}</li>
      ))}
    </ul>
  );
}

/** Simple responsive table: stacks into cards on narrow screens. */
export function NoticeTable({ head, rows, caption }: { head: string[]; rows: React.ReactNode[][]; caption?: string }) {
  return (
    <div className="overflow-hidden rounded-xl border bg-card text-sm text-foreground">
      <table className="w-full border-collapse">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead className="hidden bg-muted/60 text-left sm:table-header-group">
          <tr>
            {head.map((h) => (
              <th key={h} scope="col" className="px-4 py-2.5 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="block border-t px-4 py-3 first:border-t-0 sm:table-row sm:p-0 sm:first:border-t">
              {r.map((cell, j) => (
                <td key={j} className="block py-0.5 align-top sm:table-cell sm:px-4 sm:py-3">
                  <span className="text-xs text-muted-foreground sm:hidden">{head[j]}: </span>
                  <span className={cn(j > 0 && "text-muted-foreground", j === 0 && "font-medium")}>{cell}</span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Summary({ items }: { items: Array<{ title: string; body: React.ReactNode }> }) {
  return (
    <ul className="grid gap-px overflow-hidden rounded-xl border bg-border sm:grid-cols-2" aria-label="Summary">
      {items.map((it) => (
        <li key={it.title} className="bg-card p-4">
          <p className="text-sm font-semibold">{it.title}</p>
          <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{it.body}</p>
        </li>
      ))}
    </ul>
  );
}
