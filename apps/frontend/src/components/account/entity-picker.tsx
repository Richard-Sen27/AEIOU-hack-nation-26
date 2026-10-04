"use client";

import { Loader2, PenLine } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Command, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { nodeTypeMeta } from "@/lib/graph/meta";
import type { NodeType } from "@/lib/api/generated/types.gen";
import type { SearchHit } from "@/lib/api/types";
import { isEntityQuery, searchEntities } from "@/lib/search";
import { cn } from "@/lib/utils";

/**
 * Typeahead for one node type (disease → MONDO, gene → HGNC, phenotype →
 * HPO, institution) over `GET /search?types=`. Only short entity-like terms
 * are ever searched (lib/search enforces it); longer text is never sent.
 * With `onFreeText`, a "Use '…' as typed" item keeps what was typed, for
 * names the atlas does not have (or that are never searched, like "St. Jude").
 */
export function EntityPicker({
  types,
  label,
  placeholder,
  onSelect,
  onFreeText,
  freeTextMax = 200,
  idleHint = "Type a name, like a diagnosis, gene or symptom. Sentences are not searched.",
  disabled,
  exclude = [],
  className,
  testId,
}: {
  types: NodeType[];
  /** Accessible name of the input. */
  label: string;
  placeholder?: string;
  onSelect: (hit: SearchHit) => void;
  /** Offer the typed text itself as a choice. */
  onFreeText?: (text: string) => void;
  freeTextMax?: number;
  /** Shown while the typed text is not something that is searched. */
  idleHint?: string;
  disabled?: boolean;
  exclude?: string[];
  className?: string;
  testId?: string;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchHit[]>([]);
  const [state, setState] = useState<"idle" | "loading" | "error" | "done">("idle");
  const ctrlRef = useRef<AbortController | null>(null);
  const timerRef = useRef<number | undefined>(undefined);

  useEffect(
    () => () => {
      ctrlRef.current?.abort();
      window.clearTimeout(timerRef.current);
    },
    [],
  );

  function onChange(value: string) {
    setQ(value);
    ctrlRef.current?.abort();
    window.clearTimeout(timerRef.current);
    const term = value.trim();
    if (!isEntityQuery(term)) {
      setResults([]);
      setState("idle");
      return;
    }
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;
    setState("loading");
    timerRef.current = window.setTimeout(async () => {
      try {
        const res = await searchEntities(term, ctrl.signal, types);
        if (ctrl.signal.aborted) return;
        setResults(res.filter((h) => types.includes(h.type)));
        setState("done");
      } catch (e) {
        if ((e as { isAbort?: boolean })?.isAbort || ctrl.signal.aborted) return;
        setResults([]);
        setState("error");
      }
    }, 220);
  }

  const hits = results.filter((h) => !exclude.includes(h.id)).slice(0, 8);
  const typed = q.trim();
  const open = typed.length >= 2;
  const freeText = !!onFreeText && open && typed.length <= freeTextMax && !hits.some((h) => h.label.toLowerCase() === typed.toLowerCase());
  const meta = nodeTypeMeta(types[0]);

  return (
    <Command
      shouldFilter={false}
      className={cn(
        // One control: the outer box carries the normal input look (border,
        // background, focus ring); the shared CommandInput's own filled group
        // is flattened into it.
        "h-auto rounded-lg! border border-input bg-transparent p-0 text-foreground transition-colors focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50 dark:bg-input/30",
        "**:data-[slot=command-input-wrapper]:p-0 **:data-[slot=input-group]:border-0! **:data-[slot=input-group]:bg-transparent! **:data-[slot=input-group]:ring-0!",
        className,
      )}
      data-testid={testId}
      label={label}
    >
      <CommandInput value={q} onValueChange={onChange} placeholder={placeholder} aria-label={label} disabled={disabled} />
      {open && (
        <CommandList className="max-h-60 border-t px-1 pt-1 pb-1">
          {state === "loading" && (
            <div className="flex items-center gap-2 px-2 py-2 text-xs text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" aria-hidden /> Searching…
            </div>
          )}
          {state === "idle" && !freeText && <p className="px-2 py-2 text-xs text-muted-foreground">{idleHint}</p>}
          {state === "error" && (
            <p className="px-2 py-2 text-xs text-muted-foreground">Search is not available right now.</p>
          )}
          {state === "done" && hits.length === 0 && !freeText && (
            <p className="px-2 py-2 text-xs text-muted-foreground">No match. Try another name or spelling.</p>
          )}
          {hits.length > 0 && (
            <CommandGroup>
              {hits.map((h) => (
                <CommandItem
                  key={h.id}
                  value={h.id}
                  onSelect={() => {
                    onSelect(h);
                    onChange("");
                  }}
                >
                  <meta.icon className="size-3.5" style={{ color: `var(${meta.colorVar})` }} aria-hidden />
                  <span className="min-w-0 flex-1 truncate">
                    {h.label}
                    {h.matched_synonym && h.matched_synonym !== h.label && (
                      <span className="text-muted-foreground"> · {h.matched_synonym}</span>
                    )}
                  </span>
                  <span className="font-mono text-[10.5px] text-muted-foreground">{h.id}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          )}
          {freeText && (
            <CommandGroup>
              <CommandItem
                value="__free-text__"
                onSelect={() => {
                  onFreeText?.(typed);
                  onChange("");
                }}
              >
                <PenLine className="size-3.5 text-muted-foreground" aria-hidden />
                <span className="min-w-0 flex-1 truncate">Use &ldquo;{typed}&rdquo; as typed</span>
              </CommandItem>
            </CommandGroup>
          )}
        </CommandList>
      )}
    </Command>
  );
}
