"use client";

import { Check, CircleCheck, Pencil, Undo2, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { useLens } from "@/components/providers/lens-provider";
import { VusNotice } from "@/components/graph-ui";
import { Spinner } from "@/components/ui/spinner";
import type { SearchHit } from "@/lib/api/types";
import { nodeTypeMeta } from "@/lib/graph/meta";
import { isVus } from "@/lib/graph/types";
import { isEntityQuery, searchEntities } from "@/lib/search";
import { cn } from "@/lib/utils";

import { useNodes } from "./graph-data";
import type { TurnChip } from "./types";

const CHIP_NODE_TYPE = { disease: "disease", gene: "gene", variant: "variant", symptom: "phenotype" } as const;

function CorrectPanel({
  chip,
  onPick,
  onCancel,
}: {
  chip: TurnChip;
  onPick: (hit: SearchHit) => void;
  onCancel: () => void;
}) {
  const id = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState(chip.label);
  const [state, setState] = useState<{ kind: "idle" | "loading" | "sentence" | "error" } | { kind: "hits"; hits: SearchHit[] }>({ kind: "idle" });
  const wanted = CHIP_NODE_TYPE[chip.type];

  useEffect(() => {
    inputRef.current?.select();
  }, []);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- derived from input
      setState({ kind: "idle" });
      return;
    }
    if (!isEntityQuery(term)) {
      setState({ kind: "sentence" });
      return;
    }
    const ctrl = new AbortController();
    setState({ kind: "loading" });
    const t = setTimeout(async () => {
      try {
        const hits = await searchEntities(term, ctrl.signal);
        const sameType = hits.filter((h) => h.type === wanted);
        setState({ kind: "hits", hits: (sameType.length ? sameType : hits).slice(0, 6) });
      } catch (e) {
        if ((e as { code?: string }).code !== "aborted") setState({ kind: "error" });
      }
    }, 200);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [q, wanted]);

  return (
    <div className="mt-2 rounded-lg border bg-popover p-2.5 shadow-sm" data-testid="chip-correct" onKeyDown={(e) => e.key === "Escape" && onCancel()}>
      <label htmlFor={id} className="text-xs font-medium">
        Correct “{chip.label}”: search for the right {nodeTypeMeta(wanted).label.plain.toLowerCase()}
      </label>
      <div className="mt-1.5 flex gap-2">
        <input
          id={id}
          ref={inputRef}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          maxLength={60}
          autoComplete="off"
          className="h-8 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <button type="button" onClick={onCancel} className="h-8 rounded-md px-2 text-sm text-muted-foreground hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring outline-none">
          Cancel
        </button>
      </div>
      <div className="mt-2 text-sm" aria-live="polite">
        {state.kind === "loading" && (
          <span className="flex items-center gap-2 text-muted-foreground">
            <Spinner className="size-3.5" /> Searching…
          </span>
        )}
        {state.kind === "sentence" && <p className="text-muted-foreground">Type a single name, not a sentence.</p>}
        {state.kind === "error" && <p className="text-muted-foreground">Search is not available right now.</p>}
        {state.kind === "hits" && state.hits.length === 0 && <p className="text-muted-foreground">No match in the atlas.</p>}
        {state.kind === "hits" && state.hits.length > 0 && (
          <ul className="space-y-1">
            {state.hits.map((h) => {
              const meta = nodeTypeMeta(h.type);
              const Icon = meta.icon;
              return (
                <li key={h.id}>
                  <button
                    type="button"
                    onClick={() => onPick(h)}
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <Icon className="size-3.5 shrink-0" style={{ color: `var(${meta.colorVar})` }} aria-hidden />
                    <span className="min-w-0 flex-1 truncate">
                      {h.label}
                      {h.matched_synonym && h.matched_synonym !== h.label && (
                        <span className="text-muted-foreground"> · {h.matched_synonym}</span>
                      )}
                    </span>
                    <span className="font-mono text-[10.5px] text-muted-foreground">{h.id}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

function ChipView({
  chip,
  correcting,
  onConfirm,
  onRemove,
  onUndo,
  onCorrect,
}: {
  chip: TurnChip;
  correcting: boolean;
  onConfirm: () => void;
  onRemove: () => void;
  onUndo: () => void;
  onCorrect: () => void;
}) {
  const { labelStyle } = useLens();
  const meta = nodeTypeMeta(CHIP_NODE_TYPE[chip.type]);
  const Icon = meta.icon;
  const name = `${chip.negated ? "No " : ""}${chip.label}`;
  const typeLabel = meta.label[labelStyle];

  if (chip.state === "removed") {
    return (
      <li className="inline-flex h-8 items-center gap-1.5 rounded-full border border-dashed px-3 text-[13px] text-muted-foreground" data-testid="chip" data-state="removed">
        <span className="line-through">{name}</span>
        <button type="button" onClick={onUndo} className="inline-flex items-center gap-1 rounded font-medium text-foreground outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">
          <Undo2 className="size-3" aria-hidden /> Undo<span className="sr-only"> removing {name}</span>
        </button>
      </li>
    );
  }

  const confirmed = chip.state === "confirmed";
  const iconBtn =
    "flex size-6 items-center justify-center rounded-full outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";
  return (
    <li
      className={cn(
        "inline-flex h-8 max-w-full items-center gap-1.5 rounded-full border bg-card pr-1 pl-2.5 text-[13px]",
        confirmed && "border-confidence-high/50 bg-confidence-high/10",
        chip.negated && "border-dashed",
        correcting && "ring-2 ring-ring/40",
      )}
      data-testid="chip"
      data-state={chip.state}
      data-negated={chip.negated || undefined}
    >
      <Icon className="size-3.5 shrink-0" style={{ color: `var(${meta.colorVar})` }} aria-hidden />
      <span className="sr-only">{typeLabel}: </span>
      {chip.negated && (
        <span className="rounded-sm bg-muted px-1 font-mono text-[10px] uppercase tracking-wide text-muted-foreground">Excluded</span>
      )}
      <span className="truncate font-medium" dir="auto">
        {chip.label}
      </span>
      {chip.id && labelStyle === "technical" && <span className="font-mono text-[10.5px] text-muted-foreground">{chip.id}</span>}
      {!chip.id && <span className="text-[11px] text-muted-foreground">not matched</span>}
      {confirmed && (
        <span className="inline-flex items-center gap-0.5 text-[11px] font-medium text-confidence-high">
          <CircleCheck className="size-3.5" aria-hidden /> In profile
        </span>
      )}
      {chip.saving ? (
        <Spinner className="mx-1 size-3.5" />
      ) : (
        <span className="flex items-center">
          {!confirmed && chip.id && (
            <button type="button" onClick={onConfirm} aria-label={`Confirm ${name}`} title="Confirm" className={cn(iconBtn, "text-confidence-high hover:bg-confidence-high/15")}>
              <Check className="size-3.5" aria-hidden />
            </button>
          )}
          <button type="button" onClick={onCorrect} aria-label={`Correct ${name}`} aria-expanded={correcting} title="Correct" className={cn(iconBtn, "text-muted-foreground hover:bg-muted hover:text-foreground")}>
            <Pencil className="size-3" aria-hidden />
          </button>
          <button type="button" onClick={onRemove} aria-label={`Remove ${name}`} title="Remove" className={cn(iconBtn, "text-muted-foreground hover:bg-destructive/10 hover:text-destructive")}>
            <X className="size-3.5" aria-hidden />
          </button>
        </span>
      )}
    </li>
  );
}

/**
 * What Dr. Wu understood, as chips. Only chips the user confirms enter the
 * profile; correcting re-resolves through entity search.
 */
export function Chips({
  chips,
  onConfirm,
  onRemove,
  onUndo,
  onCorrect,
}: {
  chips: TurnChip[];
  onConfirm: (i: number) => void;
  onRemove: (i: number) => void;
  onUndo: (i: number) => void;
  onCorrect: (i: number, hit: SearchHit) => void;
}) {
  const [correcting, setCorrecting] = useState<number | null>(null);
  const variantIds = chips.filter((c) => c.type === "variant" && c.id && c.state !== "removed").map((c) => c.id!);
  const variants = useNodes(variantIds);
  const hasVus = variantIds.some((id) => {
    const d = variants[id];
    return !!d && (!!d.vus_notice || isVus(d.classification ?? (d.node.attrs?.classification as string | undefined)));
  });
  if (chips.length === 0) return null;
  const pending = chips.filter((c) => c.state === "pending").length;
  return (
    <section aria-labelledby="chips-heading" className="rounded-xl border bg-muted/40 p-3" data-testid="chips">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 id="chips-heading" className="text-sm font-medium">What I understood</h3>
        <p className="text-xs text-muted-foreground">
          {pending > 0 ? "Confirm what is right. Only confirmed items are saved to your profile." : "Your profile uses only what you confirmed."}
        </p>
      </div>
      <ul className="mt-2.5 flex flex-wrap gap-1.5">
        {chips.map((chip, i) => (
          <ChipView
            key={i}
            chip={chip}
            correcting={correcting === i}
            onConfirm={() => onConfirm(i)}
            onRemove={() => onRemove(i)}
            onUndo={() => onUndo(i)}
            onCorrect={() => setCorrecting((c) => (c === i ? null : i))}
          />
        ))}
      </ul>
      {correcting !== null && chips[correcting] && (
        <CorrectPanel
          key={correcting}
          chip={chips[correcting]}
          onCancel={() => setCorrecting(null)}
          onPick={(hit) => {
            onCorrect(correcting, hit);
            setCorrecting(null);
          }}
        />
      )}
      {hasVus && <VusNotice className="mt-2.5" />}
    </section>
  );
}
