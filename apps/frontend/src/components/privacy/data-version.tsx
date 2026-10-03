"use client";

import { useSession } from "@/components/providers/session-provider";

/** The graph data version served by the API (from `/auth/session`). */
export function DataVersion() {
  const { dataVersion, status } = useSession();
  if (status === "loading") return <span className="text-muted-foreground">loading…</span>;
  if (!dataVersion) return <span data-testid="data-version">not available right now</span>;
  return (
    <code data-testid="data-version" className="rounded bg-muted px-1.5 py-0.5 font-mono text-[13px] text-foreground">
      {dataVersion}
    </code>
  );
}
