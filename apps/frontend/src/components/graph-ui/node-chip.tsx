"use client";

import Link from "next/link";

import { useLens } from "@/components/providers/lens-provider";
import { nodeTypeMeta } from "@/lib/graph/meta";
import type { NodeType } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

/**
 * A node reference: type icon + colour dot + label, optional id (always shown
 * in the researcher lens). Links to `/node/[id]` unless `href={null}`.
 */
export function NodeChip({
  id,
  type,
  label,
  href,
  showId,
  className,
  size = "default",
}: {
  id: string;
  type: NodeType | string;
  label: string;
  /** Defaults to `/node/<id>`; pass `null` for a non-link chip. */
  href?: string | null;
  showId?: boolean;
  className?: string;
  size?: "default" | "sm";
}) {
  const { labelStyle } = useLens();
  const meta = nodeTypeMeta(type);
  const Icon = meta.icon;
  const withId = showId ?? labelStyle === "technical";
  const target = href === undefined ? `/node/${encodeURIComponent(id)}` : href;
  const body = (
    <>
      <Icon
        className={cn("shrink-0", size === "sm" ? "size-3" : "size-3.5")}
        style={{ color: `var(${meta.colorVar})` }}
        aria-hidden
      />
      <span className="truncate">{label}</span>
      {withId && <span className="font-mono text-[10.5px] text-muted-foreground">{id}</span>}
      <span className="sr-only">({meta.label[labelStyle]})</span>
    </>
  );
  const cls = cn(
    "inline-flex max-w-full items-center gap-1.5 rounded-md border bg-card font-medium whitespace-nowrap",
    size === "sm" ? "h-6 px-1.5 text-xs" : "h-7 px-2 text-[13px]",
    target && "outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring",
    className,
  );
  return target ? (
    <Link href={target} className={cls} data-testid="node-chip" data-node-type={type} title={meta.label[labelStyle]}>
      {body}
    </Link>
  ) : (
    <span className={cls} data-testid="node-chip" data-node-type={type} title={meta.label[labelStyle]}>
      {body}
    </span>
  );
}
