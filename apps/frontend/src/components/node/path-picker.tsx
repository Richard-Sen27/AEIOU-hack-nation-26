"use client";

import { Route, WifiOff } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useLens } from "@/components/providers/lens-provider";
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import type { SearchHit } from "@/lib/api/types";
import { nodeTypeMeta } from "@/lib/graph/meta";
import { isEntityQuery, searchEntities, SEARCH_MAX_CHARS } from "@/lib/search";

/**
 * "Find a path to…": pick a target by name, then go to
 * `/path?from=<id>&to=<id>` (public graph ids only in the URL).
 */
export function PathPicker({
  fromId,
  fromLabel,
  open,
  onOpenChange,
}: {
  fromId: string;
  fromLabel: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const { labelStyle } = useLens();
  const [q, setQ] = useState("");
  const [state, setState] = useState<{ kind: "idle" | "loading" | "offline" } | { kind: "results"; hits: SearchHit[] }>({ kind: "idle" });

  useEffect(() => {
    const t = q.trim();
    if (!open || t.length < 2 || !isEntityQuery(t)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- derived from input
      setState({ kind: "idle" });
      return;
    }
    const ctrl = new AbortController();
    setState({ kind: "loading" });
    const timer = setTimeout(async () => {
      try {
        const hits = await searchEntities(t, ctrl.signal);
        setState({ kind: "results", hits: hits.filter((h) => h.id !== fromId) });
      } catch (e) {
        if ((e as { code?: string }).code !== "aborted") setState({ kind: "offline" });
      }
    }, 180);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [q, open, fromId]);

  const pick = (to: string) => {
    onOpenChange(false);
    setQ("");
    router.push(`/path?from=${encodeURIComponent(fromId)}&to=${encodeURIComponent(to)}`);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o);
        if (!o) setQ("");
      }}
    >
      <DialogContent showCloseButton={false} className="top-[14vh] translate-y-0 gap-0 overflow-hidden p-0 sm:max-w-lg" data-testid="path-picker">
        <div className="border-b px-4 pt-4 pb-3">
          <DialogTitle className="flex items-center gap-2 text-base">
            <Route className="size-4 text-primary" aria-hidden /> Find a path from {fromLabel}
          </DialogTitle>
          <DialogDescription className="mt-1 text-xs">
            Choose where the path should end: a disease, gene, symptom, patient group or mechanism.
          </DialogDescription>
        </div>
        <Command shouldFilter={false} loop className="rounded-none bg-popover p-1">
          <CommandInput
            value={q}
            onValueChange={setQ}
            maxLength={SEARCH_MAX_CHARS}
            placeholder="Search for the end point…"
            aria-label="Path end point"
          />
          <CommandList className="max-h-72">
            {state.kind === "loading" && (
              <div className="flex items-center gap-2 px-3 py-4 text-sm text-muted-foreground" role="status">
                <Spinner className="size-4" /> Searching…
              </div>
            )}
            {state.kind === "offline" && (
              <div className="flex items-center gap-2 px-3 py-4 text-sm text-muted-foreground" role="status">
                <WifiOff className="size-4" aria-hidden /> Search is not available right now.
              </div>
            )}
            {state.kind === "results" && <CommandEmpty>No matches.</CommandEmpty>}
            {state.kind === "results" &&
              state.hits.map((h) => {
                const meta = nodeTypeMeta(h.type);
                const Icon = meta.icon;
                return (
                  <CommandItem key={h.id} value={h.id} onSelect={() => pick(h.id)} className="gap-2.5 py-2">
                    <Icon className="size-4 shrink-0" style={{ color: `var(${meta.colorVar})` }} aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{h.label}</span>
                      <span className="block truncate text-[11px] text-muted-foreground">
                        {meta.label[labelStyle]} · <span className="font-mono">{h.id}</span>
                      </span>
                    </span>
                  </CommandItem>
                );
              })}
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
