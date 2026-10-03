"use client";

import { ArrowRight, Bot, CornerDownLeft, SearchX, WifiOff } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useLens } from "@/components/providers/lens-provider";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/kbd";
import { Spinner } from "@/components/ui/spinner";
import type { SearchHit } from "@/lib/api/types";
import { announce } from "@/lib/a11y";
import { nodeTypeMeta } from "@/lib/graph/meta";
import { NODE_TYPES } from "@/lib/graph/types";
import { isEntityQuery, searchEntities, SEARCH_MAX_CHARS } from "@/lib/search";

type State =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "results"; hits: SearchHit[] }
  | { kind: "sentence" }
  | { kind: "offline"; reason: "network" | "unavailable" };

export function GlobalSearchDialog({
  open,
  onOpenChange,
  initialQuery = "",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialQuery?: string;
}) {
  const router = useRouter();
  const { labelStyle } = useLens();
  const [query, setQuery] = useState(initialQuery);
  const [state, setState] = useState<State>({ kind: "idle" });

  // Reset when (re)opened.
  useEffect(() => {
    if (open) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reset on open
      setQuery(initialQuery);
      setState({ kind: "idle" });
    }
  }, [open, initialQuery]);

  useEffect(() => {
    if (!open) return;
    const q = query.trim();
    if (q.length < 2) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- derived from input
      setState({ kind: "idle" });
      return;
    }
    if (!isEntityQuery(q)) {
      setState({ kind: "sentence" });
      return;
    }
    const ctrl = new AbortController();
    setState({ kind: "loading" });
    const t = setTimeout(async () => {
      try {
        const hits = await searchEntities(q, ctrl.signal);
        setState({ kind: "results", hits });
        announce(hits.length ? `${hits.length} results` : "No results");
      } catch (e) {
        const code = (e as { code?: string }).code;
        if (code === "aborted") return;
        setState({ kind: "offline", reason: code === "network_error" ? "network" : "unavailable" });
      }
    }, 180);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [query, open]);

  const groups = useMemo(() => {
    if (state.kind !== "results") return [];
    const byType = new Map<string, SearchHit[]>();
    for (const h of state.hits) byType.set(h.type, [...(byType.get(h.type) ?? []), h]);
    return [...byType.entries()].sort(
      ([a], [b]) =>
        NODE_TYPES.indexOf(a as (typeof NODE_TYPES)[number]) -
        NODE_TYPES.indexOf(b as (typeof NODE_TYPES)[number]),
    );
  }, [state]);

  const go = (href: string) => {
    onOpenChange(false);
    router.push(href);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="top-[12vh] translate-y-0 gap-0 overflow-hidden p-0 sm:max-w-xl"
        data-testid="global-search"
      >
        <DialogTitle className="sr-only">Search the atlas</DialogTitle>
        <DialogDescription className="sr-only">
          Find a disease, gene, symptom, patient group or mechanism by name.
        </DialogDescription>
        <Command shouldFilter={false} className="rounded-none! bg-popover p-0" loop>
          <div className="border-b p-2">
            <CommandInput
              value={query}
              onValueChange={setQuery}
              maxLength={SEARCH_MAX_CHARS * 3}
              placeholder="Disease, gene, symptom, patient group…"
              aria-label="Search the atlas"
              className="h-10 text-base sm:text-sm"
            />
          </div>
          <CommandList className="max-h-[min(60vh,420px)] p-1">
            {state.kind === "idle" && (
              <div className="px-3 py-6 text-sm text-muted-foreground">
                <p>Type a name, for example <span className="font-mono text-foreground">STXBP1</span>,{" "}
                  <span className="font-mono text-foreground">Dravet</span> or{" "}
                  <span className="font-mono text-foreground">epileptic spasms</span>.</p>
                <p className="mt-1 text-xs">Synonyms work too: old names lead to the current one.</p>
              </div>
            )}
            {state.kind === "loading" && (
              <div className="flex items-center gap-2 px-3 py-6 text-sm text-muted-foreground" role="status">
                <Spinner className="size-4" /> Searching…
              </div>
            )}
            {state.kind === "offline" && (
              <div className="flex items-start gap-3 px-3 py-6 text-sm text-muted-foreground" role="status">
                <WifiOff className="mt-0.5 size-4 shrink-0" aria-hidden />
                <p>
                  {state.reason === "network"
                    ? "Search is unavailable because Amber's server can't be reached. Try again in a moment."
                    : "Search is not available right now. Try again in a moment."}
                </p>
              </div>
            )}
            {state.kind === "sentence" && (
              <div className="space-y-3 px-3 py-5 text-sm">
                <p className="text-muted-foreground">
                  That reads like a description rather than a name. Search works best with a single
                  name. To describe a situation in your own words, ask Dr. Wu instead.
                </p>
                <CommandItem value="__ask" onSelect={() => go("/chat")} className="gap-3">
                  <Bot className="text-primary" aria-hidden />
                  <span>Ask Dr. Wu</span>
                  <ArrowRight className="ml-auto" aria-hidden />
                </CommandItem>
              </div>
            )}
            {state.kind === "results" && (
              <CommandEmpty className="flex flex-col items-center gap-2 py-8 text-muted-foreground">
                <SearchX className="size-5" aria-hidden />
                No matches in the atlas.
              </CommandEmpty>
            )}
            {groups.map(([type, hits]) => {
              const meta = nodeTypeMeta(type);
              const Icon = meta.icon;
              return (
                <CommandGroup key={type} heading={meta.plural[labelStyle]}>
                  {hits.map((hit) => (
                    <CommandItem
                      key={hit.id}
                      value={hit.id}
                      onSelect={() => go(`/node/${encodeURIComponent(hit.id)}`)}
                      className="gap-3 py-2"
                    >
                      <span
                        className="flex size-7 shrink-0 items-center justify-center rounded-md border"
                        style={{ color: `var(${meta.colorVar})` }}
                      >
                        <Icon className="size-4" aria-hidden />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate">
                          {hit.matched_synonym && hit.matched_synonym !== hit.label ? (
                            <>
                              <span className="text-muted-foreground">{hit.matched_synonym}</span>
                              <span aria-label=" is now " className="px-1.5 text-muted-foreground">→</span>
                              <span className="font-medium">{hit.label}</span>
                            </>
                          ) : (
                            <span className="font-medium">{hit.label}</span>
                          )}
                        </span>
                        <span className="block truncate font-mono text-[11px] text-muted-foreground">
                          {hit.id}
                        </span>
                      </span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              );
            })}
          </CommandList>
          <div className="flex items-center justify-between gap-4 border-t bg-muted/50 px-3 py-2 text-[11px] text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <Kbd><CornerDownLeft className="size-3" aria-hidden /></Kbd> open
              <Kbd className="ml-2">↑</Kbd><Kbd>↓</Kbd> move
              <Kbd className="ml-2">esc</Kbd> close
            </span>
            <span className="hidden sm:inline">Names only, please. No personal details.</span>
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
