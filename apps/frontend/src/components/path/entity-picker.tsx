"use client";

import { ChevronDown, Search, X } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import {
  Button as AriaButton,
  ComboBox,
  ComboBoxStateContext,
  Group,
  Input,
  Label,
  ListBox,
  ListBoxItem,
  Popover,
  Text,
} from "react-aria-components";

import { useLens } from "@/components/providers/lens-provider";
import { Spinner } from "@/components/ui/spinner";
import type { SearchHit } from "@/lib/api/types";
import { nodeTypeMeta } from "@/lib/graph/meta";
import { isEntityQuery, searchEntities, SEARCH_MAX_CHARS } from "@/lib/search";
import { cn } from "@/lib/utils";

import type { Endpoint } from "./types";

type Status = "idle" | "loading" | "done" | "sentence" | "offline";

/**
 * Opens the list when typed results arrive while the input has focus. React
 * Aria only opens on keystrokes it sees, so a paste (one input event) could
 * otherwise leave the results hidden.
 */
function OpenOnResults({ status, input }: { status: Status; input: React.RefObject<HTMLInputElement | null> }) {
  const state = useContext(ComboBoxStateContext);
  useEffect(() => {
    if (!state || state.isOpen || status === "idle") return;
    if (typeof document !== "undefined" && document.activeElement === input.current) state.open(null, "input");
  }, [state, status, input]);
  return null;
}

/**
 * Typeahead against `GET /search`: typed results with the matched synonym
 * ("Ohtahara syndrome → STXBP1 encephalopathy"). Only short entity names
 * reach the URL (lib/search.ts).
 */
export function EntityPicker({
  label,
  value,
  onChange,
  placeholder,
  autoFocus,
  testId,
}: {
  label: string;
  value: Endpoint | null;
  onChange: (next: Endpoint | null) => void;
  placeholder?: string;
  autoFocus?: boolean;
  testId?: string;
}) {
  const { labelStyle } = useLens();
  const [input, setInput] = useState(value?.label ?? "");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [status, setStatus] = useState<Status>("idle");
  const typed = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Focus after hydration (a plain autoFocus attribute skips React Aria's focus tracking).
  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);

  // Follow the external value (prefill, swap) unless the user is typing.
  useEffect(() => {
    typed.current = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- sync to prop
    setInput(value?.label ?? "");
  }, [value?.id, value?.label]);

  useEffect(() => {
    if (!typed.current) return;
    const q = input.trim();
    if (q.length < 2) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- derived from input
      setHits([]);
      setStatus("idle");
      return;
    }
    if (!isEntityQuery(q)) {
      setHits([]);
      setStatus("sentence");
      return;
    }
    const ctrl = new AbortController();
    setStatus("loading");
    const t = setTimeout(async () => {
      try {
        const res = await searchEntities(q, ctrl.signal);
        setHits(res.slice(0, 12));
        setStatus("done");
      } catch (e) {
        if ((e as { code?: string }).code === "aborted") return;
        setHits([]);
        setStatus("offline");
      }
    }, 180);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [input]);

  return (
    <ComboBox
      className="group/picker flex min-w-0 flex-1 flex-col gap-1.5"
      items={hits}
      inputValue={input}
      onInputChange={(v) => {
        typed.current = true;
        setInput(v);
      }}
      selectedKey={value?.id ?? null}
      onSelectionChange={(key) => {
        if (key === null) return;
        const hit = hits.find((h) => h.id === key);
        if (hit) {
          typed.current = false;
          setInput(hit.label);
          onChange({ id: hit.id, label: hit.label, type: hit.type });
        }
      }}
      menuTrigger="input"
      allowsEmptyCollection
      allowsCustomValue
      onBlur={() => {
        // Leaving with half-typed text restores the chosen node.
        if (value && input !== value.label) {
          typed.current = false;
          setInput(value.label);
        }
      }}
      data-testid={testId}
    >
      <OpenOnResults status={status} input={inputRef} />
      <Label className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-muted-foreground">{label}</Label>
      <Group
        className={cn(
          "relative flex h-11 items-center gap-2 rounded-lg border bg-card pr-1 pl-3 shadow-xs transition-colors",
          "focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/40",
        )}
      >
        {value ? (
          (() => {
            const meta = nodeTypeMeta(value.type);
            const Icon = meta.icon;
            return <Icon className="size-4 shrink-0" style={{ color: `var(${meta.colorVar})` }} aria-hidden />;
          })()
        ) : (
          <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        )}
        <Input
          className="h-full min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-muted-foreground sm:text-sm"
          placeholder={placeholder}
          maxLength={SEARCH_MAX_CHARS * 2}
          ref={inputRef}
        />
        {status === "loading" && <Spinner className="size-4 text-muted-foreground" />}
        {value && (
          <button
            type="button"
            className="flex size-8 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => {
              typed.current = false;
              setInput("");
              onChange(null);
            }}
            aria-label={`Clear ${label.toLowerCase()}`}
          >
            <X className="size-4" aria-hidden />
          </button>
        )}
        <AriaButton className="flex size-8 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-muted data-[focus-visible]:ring-2 data-[focus-visible]:ring-ring">
          <ChevronDown className="size-4" aria-hidden />
        </AriaButton>
      </Group>
      {value && labelStyle === "technical" && (
        <Text slot="description" className="font-mono text-[11px] text-muted-foreground">
          {value.id}
        </Text>
      )}
      <Popover
        className="z-50 w-(--trigger-width) overflow-hidden rounded-lg border bg-popover text-popover-foreground shadow-lg outline-none data-[entering]:animate-in data-[entering]:fade-in-0 data-[exiting]:animate-out data-[exiting]:fade-out-0"
        offset={6}
      >
        <ListBox
          className="max-h-80 overflow-auto p-1 outline-none"
          renderEmptyState={() => (
            <p className="px-3 py-4 text-sm text-muted-foreground" role="status">
              {status === "loading"
                ? "Searching…"
                : status === "sentence"
                  ? "Please type a single name (a disease, gene, symptom or group), not a description."
                  : status === "offline"
                    ? "Search is unavailable right now."
                    : input.trim().length < 2
                      ? "Type at least two letters."
                      : "No matches in the atlas."}
            </p>
          )}
        >
          {(hit: SearchHit) => {
            const meta = nodeTypeMeta(hit.type);
            const Icon = meta.icon;
            const synonym = hit.matched_synonym && hit.matched_synonym !== hit.label ? hit.matched_synonym : null;
            return (
              <ListBoxItem
                id={hit.id}
                textValue={hit.label}
                className="flex cursor-default items-center gap-3 rounded-md px-2 py-2 text-sm outline-none data-[focused]:bg-muted data-[selected]:bg-accent"
              >
                <span
                  className="flex size-7 shrink-0 items-center justify-center rounded-md border bg-card"
                  style={{ color: `var(${meta.colorVar})` }}
                >
                  <Icon className="size-4" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate">
                    {synonym && (
                      <>
                        <span className="text-muted-foreground">{synonym}</span>
                        <span aria-label=" is now " className="px-1.5 text-muted-foreground">
                          →
                        </span>
                      </>
                    )}
                    <span className="font-medium">{hit.label}</span>
                  </span>
                  <span className="block truncate text-[11px] text-muted-foreground">
                    {meta.label[labelStyle]} · <span className="font-mono">{hit.id}</span>
                  </span>
                </span>
              </ListBoxItem>
            );
          }}
        </ListBox>
      </Popover>
    </ComboBox>
  );
}
