"use client";

import { Bot, ChevronRight, CornerDownLeft, FolderTree, Search, SearchX, X } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { useLens } from "@/components/providers/lens-provider";
import { Kbd } from "@/components/ui/kbd";
import { Spinner } from "@/components/ui/spinner";
import type { SearchHit } from "@/lib/api/types";
import { announce } from "@/lib/a11y";
import type { LabelStyle } from "@/lib/graph/meta";
import { nodeTypeMeta } from "@/lib/graph/meta";
import { isEntityQuery, searchEntities, SEARCH_MAX_CHARS } from "@/lib/search";
import { cn } from "@/lib/utils";

import { categoryLabel, CATEGORY_META } from "./atlas-categories";
import { OffMapMark, OFF_MAP_LABEL } from "./atlas-offmap";
import type { AtlasSearchProps } from "./atlas-props";
import { ancestorsOf, searchTree, type AtlasTreeNode, type TreeIndex } from "./tree-model";

const LOCAL_LIMIT = 8;
/** `searchTree` stops at its limit in tree order, so take a wider pool and rank it here. */
const LOCAL_POOL = 300;
const SERVER_LIMIT = 5;
const EXACT_SYNONYM_TYPES = new Set(["disease", "gene", "phenotype"]);
const DEBOUNCE_MS = 220;

type Server =
  | { kind: "idle" }
  | { kind: "loading"; q: string }
  | { kind: "done"; q: string; hits: SearchHit[] }
  | { kind: "failed"; q: string };

type Option =
  | { key: string; kind: "node"; node: AtlasTreeNode; synonym?: string }
  /** A server hit that exists in the atlas but is not on the map (no tree node, no breadcrumb). */
  | { key: string; kind: "offmap"; hit: SearchHit; synonym?: string }
  | { key: string; kind: "ask" };

/** Types people most often look for come first among equally good matches. */
const TYPE_RANK = [
  "disease", "gene", "phenotype", "cluster", "branch", "institution", "doctor", "researcher",
  "patient_org", "mechanism", "pathway", "variant", "registry", "network", "trial", "grant", "paper", "claim",
];

/**
 * Exact names first, then names that start with the query, then a word
 * that starts with it, then anything containing it; ties by type (tree
 * branches right after conditions, genes and symptoms), then shorter names.
 */
function rankLocal(nodes: AtlasTreeNode[], query: string): AtlasTreeNode[] {
  const t = query.trim().toLowerCase();
  const score = (n: AtlasTreeNode) => {
    const label = n.label.toLowerCase();
    const name = label.split(" · ")[0];
    const match =
      name === t || n.id.toLowerCase() === t ? 0 : label.startsWith(t) ? 1 : new RegExp(`\\b${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`).test(label) ? 2 : 3;
    const type = TYPE_RANK.indexOf(n.kind === "entity" ? (n.entity_type ?? "") : "branch");
    return { match, type: type < 0 ? TYPE_RANK.length : type, len: label.length };
  };
  return nodes
    .map((n) => ({ n, s: score(n) }))
    .sort((a, b) => a.s.match - b.s.match || a.s.type - b.s.type || a.s.len - b.s.len)
    .map((x) => x.n);
}

/** Name shown for a tree node: categories follow the lens wording. */
function nodeName(n: AtlasTreeNode, labelStyle: LabelStyle): string {
  return n.kind === "category" && n.category ? categoryLabel(n.category, labelStyle) : n.label;
}

/** "Disease", "Gene", ... for entities; "Category" / "Group" for tree branches. */
function kindName(n: AtlasTreeNode, labelStyle: LabelStyle): string {
  if (n.kind === "entity" && n.entity_type) return nodeTypeMeta(n.entity_type).label[labelStyle];
  return n.kind === "category" ? "Category" : "Group";
}

/** Where a node sits in the tree, root excluded: "Conditions › Epilepsies › …". */
function breadcrumb(index: TreeIndex, n: AtlasTreeNode, labelStyle: LabelStyle): string[] {
  return ancestorsOf(index, n.id)
    .filter((a) => a.kind !== "root")
    .map((a) => nodeName(a, labelStyle));
}

function NodeIcon({ node }: { node: AtlasTreeNode }) {
  if (node.kind === "entity" && node.entity_type) {
    const meta = nodeTypeMeta(node.entity_type);
    const Icon = meta.icon;
    return <Icon className="size-4" style={{ color: `var(${meta.colorVar})` }} aria-hidden />;
  }
  const color = node.category ? `var(${CATEGORY_META[node.category].colorVar})` : undefined;
  return <FolderTree className="size-4" style={{ color }} aria-hidden />;
}

/**
 * "Search the map": a combobox centred at the top of the canvas. Matches
 * every tree node locally (groups and categories included) and merges in
 * synonym matches from `GET /search`, but only for short, name-like queries
 * (`isEntityQuery`). Server hits that are not on the map are listed too,
 * marked "Not on the map yet"; picking one opens its summary. Anything that
 * reads like a description is never sent anywhere; it can be handed to
 * Dr. Wu in memory instead.
 */
export function AtlasSearch({ index, onPick, onAskWu, className }: AtlasSearchProps) {
  const { labelStyle } = useLens();
  const uid = useId();
  const listId = `${uid}-list`;
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [server, setServer] = useState<Server>({ kind: "idle" });

  const q = query.trim();
  const entityQuery = isEntityQuery(q);

  const local = useMemo(() => rankLocal(searchTree(index, q, LOCAL_POOL), q).slice(0, LOCAL_LIMIT), [index, q]);

  // Synonym matches from the API: name-like queries only, debounced.
  useEffect(() => {
    if (!entityQuery) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- derived from input
      setServer({ kind: "idle" });
      return;
    }
    const ctrl = new AbortController();
    setServer({ kind: "loading", q });
    const t = setTimeout(async () => {
      try {
        const hits = await searchEntities(q, ctrl.signal);
        setServer({ kind: "done", q, hits });
      } catch (e) {
        if ((e as { code?: string }).code === "aborted" || ctrl.signal.aborted) return;
        setServer({ kind: "failed", q });
      }
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [q, entityQuery]);

  const options = useMemo<Option[]>(() => {
    const toOption = (hit: SearchHit): Option => {
      const node = index.nodes.get(hit.id);
      const synonym = hit.matched_synonym && hit.matched_synonym !== hit.label ? hit.matched_synonym : undefined;
      return node ? { key: hit.id, kind: "node", node, synonym } : { key: hit.id, kind: "offmap", hit, synonym };
    };
    const hits = server.kind === "done" && server.q === q ? server.hits : [];
    // An exact id or exact name/symbol match from the API (also one not on the map) comes first,
    // and so does an exact synonym of a condition, gene or symptom ("FOP", "ORPHA:337").
    const exact = hits
      .filter((h) => h.match_kind === "exact" && (!h.matched_synonym || EXACT_SYNONYM_TYPES.has(h.type)))
      .slice(0, SERVER_LIMIT);
    const out: Option[] = exact.map(toOption);
    const seen = new Set(exact.map((h) => h.id));
    for (const node of local) {
      if (!seen.has(node.id)) out.push({ key: node.id, kind: "node", node });
      seen.add(node.id);
    }
    let added = exact.length;
    for (const hit of hits) {
      if (added >= SERVER_LIMIT) break;
      if (seen.has(hit.id)) continue;
      seen.add(hit.id);
      added += 1;
      out.push(toOption(hit));
    }
    // Free text (or a name the map does not have) can go to Dr. Wu, in memory only.
    const searching = server.kind === "loading" && server.q === q;
    if (q.length >= 2 && (!entityQuery || (out.length === 0 && !searching))) {
      out.push({ key: "__ask", kind: "ask" });
    }
    return out;
  }, [local, server, q, entityQuery, index]);

  const searching = entityQuery && server.kind === "loading";
  const nodeCount = options.filter((o) => o.kind !== "ask").length;

  // Reset the highlighted option when the query changes, and when server results
  // put an exact match in front (other server results only append).
  const leadKey = options[0]?.key;
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- derived from input
    setActive(-1);
  }, [q, leadKey]);

  // Distinct records can share a name (two papers titled "Fibrodysplasia ossificans
  // progressiva."): those show their id as well.
  const sharedLabels = useMemo(() => {
    const counts = new Map<string, number>();
    for (const o of options) {
      const label = o.kind === "node" ? o.node.label : o.kind === "offmap" ? o.hit.label : null;
      if (label) counts.set(label.toLowerCase(), (counts.get(label.toLowerCase()) ?? 0) + 1);
    }
    return new Set([...counts].filter(([, n]) => n > 1).map(([l]) => l));
  }, [options]);
  const activeIndex = active < options.length ? active : -1;

  // Tell screen readers how many results there are, once the search settles.
  useEffect(() => {
    if (!open || q.length < 1 || searching) return;
    const t = setTimeout(() => {
      announce(
        nodeCount > 0
          ? `${nodeCount} ${nodeCount === 1 ? "result" : "results"}`
          : entityQuery || q.length < 2
            ? "Nothing on the map matches"
            : "This reads like a description. You can ask Dr. Wu instead.",
      );
    }, 400);
    return () => clearTimeout(t);
  }, [open, q, searching, nodeCount, entityQuery]);

  // Keep the highlighted option in view.
  useEffect(() => {
    if (active < 0) return;
    listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const reset = () => {
    setQuery("");
    setActive(-1);
  };

  const choose = (opt: Option | undefined) => {
    if (!opt) return;
    if (opt.kind === "ask") {
      onAskWu(q);
      announce("Your question is ready for Dr. Wu.");
    } else if (opt.kind === "offmap") {
      onPick(opt.hit.id);
      announce(`Showing ${opt.hit.label}. ${OFF_MAP_LABEL}.`);
    } else {
      onPick(opt.node.id);
      announce(`Showing ${nodeName(opt.node, labelStyle)} on the map`);
    }
    reset();
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    const n = options.length;
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        if (!open) setOpen(true);
        else if (n > 0) setActive((i) => (i >= n - 1 ? 0 : i + 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        if (!open) setOpen(true);
        else if (n > 0) setActive((i) => (i <= 0 || i >= n ? n - 1 : i - 1));
        break;
      case "Home":
      case "End":
        // Only while an option is highlighted; otherwise the caret moves as usual.
        if (open && activeIndex >= 0 && n > 0) {
          e.preventDefault();
          setActive(e.key === "Home" ? 0 : n - 1);
        }
        break;
      case "Enter":
        if (!open || n === 0) return;
        e.preventDefault();
        choose(options[activeIndex >= 0 ? activeIndex : 0]);
        break;
      case "Escape":
        if (open && q) {
          e.preventDefault();
          setOpen(false);
        } else if (q) {
          e.preventDefault();
          reset();
        } else {
          setOpen(false);
          inputRef.current?.blur();
        }
        break;
      case "Tab":
        setOpen(false);
        break;
    }
  };

  const showList = open;
  const activeId = activeIndex >= 0 ? `${uid}-opt-${activeIndex}` : undefined;
  const failed = server.kind === "failed" && server.q === q;

  return (
    <div
      data-testid="atlas-search"
      data-tour="search"
      className={cn(
        "relative w-full max-w-md rounded-xl",
        "data-[tour-active]:ring-2 data-[tour-active]:ring-primary data-[tour-active]:ring-offset-2 data-[tour-active]:ring-offset-background",
        className,
      )}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOpen(false);
      }}
    >
      <div
        className={cn(
          "flex h-10 items-center gap-2 rounded-xl border bg-background/95 px-3 shadow-sm ring-foreground/10 backdrop-blur transition-[border-color,box-shadow]",
          "focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50",
        )}
      >
        <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        <input
          ref={inputRef}
          data-slot="atlas-search-input"
          type="text"
          role="combobox"
          aria-label="Search the map"
          aria-autocomplete="list"
          aria-expanded={showList}
          aria-controls={listId}
          aria-activedescendant={showList ? activeId : undefined}
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="search"
          maxLength={SEARCH_MAX_CHARS * 3}
          placeholder="Search the map"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onClick={() => setOpen(true)}
          onKeyDown={onKeyDown}
          className="h-full min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-muted-foreground md:text-sm"
        />
        {searching && <Spinner className="size-3.5 text-muted-foreground" aria-label="Checking other names" />}
        {query ? (
          <button
            type="button"
            onClick={() => {
              reset();
              inputRef.current?.focus();
            }}
            className="-mr-1 flex size-6 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="size-3.5" aria-hidden />
            <span className="sr-only">Clear search</span>
          </button>
        ) : (
          <Kbd className="hidden sm:inline-flex" aria-hidden>
            /
          </Kbd>
        )}
      </div>

      <div
        className={cn(
          "absolute inset-x-0 top-full z-30 mt-1.5 animate-in overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-xl ring-1 ring-foreground/10 duration-150 ease-out fade-in-0 slide-in-from-top-1",
          !showList && "hidden",
        )}
      >
        <ul
          ref={listRef}
          id={listId}
          role="listbox"
          aria-label="Search results"
          className="max-h-[min(60vh,26rem)] overflow-y-auto overscroll-contain p-1"
        >
          {options.map((opt, i) => {
            const selected = i === activeIndex;
            const common = {
              id: `${uid}-opt-${i}`,
              role: "option" as const,
              "aria-selected": selected,
              "data-index": i,
              // Keep focus in the input so the combobox stays operable.
              onMouseDown: (e: React.MouseEvent) => e.preventDefault(),
              onMouseMove: () => active !== i && setActive(i),
              onClick: () => choose(opt),
            };
            if (opt.kind === "ask") {
              return (
                <li
                  key={opt.key}
                  {...common}
                  data-testid="atlas-search-ask"
                  className={cn(
                    "mt-1 flex cursor-default items-start gap-3 rounded-lg border border-dashed px-3 py-2.5 text-sm",
                    selected ? "border-primary/50 bg-primary/10" : "bg-muted/40",
                  )}
                >
                  <Bot className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium">Ask Dr. Wu</span>
                    <span className="block text-xs text-muted-foreground">
                      {entityQuery
                        ? "Or describe it in your own words. Dr. Wu can look for it."
                        : "This reads like a description. Dr. Wu can find the dots that fit it."}
                    </span>
                  </span>
                  <CornerDownLeft className="mt-1 size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                </li>
              );
            }
            if (opt.kind === "offmap") {
              const { hit, synonym } = opt;
              const meta = nodeTypeMeta(hit.type);
              const Icon = meta.icon;
              return (
                <li
                  key={opt.key}
                  {...common}
                  data-testid="atlas-search-option"
                  data-node-id={hit.id}
                  data-offmap="true"
                  className={cn(
                    "flex cursor-default items-center gap-3 rounded-lg px-2 py-1.5 text-sm",
                    selected && "bg-muted text-foreground",
                  )}
                >
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-dashed bg-background">
                    <Icon className="size-4" style={{ color: `var(${meta.colorVar})` }} aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline gap-2">
                      <span className="min-w-0 truncate">
                        {synonym && (
                          <>
                            <span className="text-muted-foreground">{synonym}</span>
                            <span aria-label=", now called " className="px-1.5 text-muted-foreground">
                              →
                            </span>
                          </>
                        )}
                        <span className="font-medium">{hit.label}</span>
                      </span>
                      <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">
                        {sharedLabels.has(hit.label.toLowerCase()) && (
                          <span className="font-mono" data-testid="atlas-search-id">{hit.id} · </span>
                        )}
                        {meta.label[labelStyle]}
                      </span>
                    </span>
                    <OffMapMark className="mt-0.5" />
                  </span>
                </li>
              );
            }
            const { node, synonym } = opt;
            const crumbs = breadcrumb(index, node, labelStyle);
            const name = nodeName(node, labelStyle);
            return (
              <li
                key={opt.key}
                {...common}
                data-testid="atlas-search-option"
                data-node-id={node.id}
                className={cn(
                  "flex cursor-default items-center gap-3 rounded-lg px-2 py-1.5 text-sm",
                  selected && "bg-muted text-foreground",
                )}
              >
                <span className="flex size-7 shrink-0 items-center justify-center rounded-md border bg-background">
                  <NodeIcon node={node} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-2">
                    <span className="min-w-0 truncate">
                      {synonym ? (
                        <>
                          <span className="text-muted-foreground">{synonym}</span>
                          <span aria-label=", now called " className="px-1.5 text-muted-foreground">
                            →
                          </span>
                          <span className="font-medium">{name}</span>
                        </>
                      ) : (
                        <span className="font-medium">{name}</span>
                      )}
                    </span>
                    <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">
                      {node.kind === "entity" && sharedLabels.has(node.label.toLowerCase()) && (
                        <span className="font-mono" data-testid="atlas-search-id">{node.id} · </span>
                      )}
                      {kindName(node, labelStyle)}
                      {node.kind !== "entity" && (
                        <span className="tabular-nums"> · {node.entity_count.toLocaleString("en")}</span>
                      )}
                    </span>
                  </span>
                  {crumbs.length > 0 && (
                    <span className="flex min-w-0 items-center gap-0.5 text-[11px] text-muted-foreground">
                      <span className="sr-only">In </span>
                      {crumbs.map((c, ci) => (
                        <span
                          key={ci}
                          className={cn("flex min-w-0 items-center gap-0.5", ci === 0 ? "shrink-0" : "truncate")}
                        >
                          {ci > 0 && <ChevronRight className="size-3 shrink-0 opacity-60" aria-hidden />}
                          <span className="truncate">{c}</span>
                          {ci < crumbs.length - 1 && <span className="sr-only">, </span>}
                        </span>
                      ))}
                    </span>
                  )}
                </span>
              </li>
            );
          })}
        </ul>

        {q.length === 0 && (
          <div className="px-3 py-4 text-sm text-muted-foreground">
            <p>
              Type a name, for example <span className="font-medium text-foreground">Seizure</span>,{" "}
              <span className="font-medium text-foreground">STXBP1</span> or a hospital.
            </p>
            <p className="mt-1 text-xs">Each result shows where it sits in the trees. Other names work too.</p>
          </div>
        )}
        {q.length > 0 && nodeCount === 0 && entityQuery && !searching && (
          <div className="flex items-start gap-2 px-3 pt-1 pb-3 text-sm text-muted-foreground" role="status">
            <SearchX className="mt-0.5 size-4 shrink-0" aria-hidden />
            <p>
              {failed
                ? "Nothing on the map by that name, and other names could not be checked right now."
                : "Nothing on the map by that name. Check the spelling or try another name."}
            </p>
          </div>
        )}
        {q.length === 1 && nodeCount === 0 && (
          <p className="px-3 pt-1 pb-3 text-sm text-muted-foreground">Keep typing…</p>
        )}
        {searching && nodeCount === 0 && (
          <p className="flex items-center gap-2 px-3 pt-1 pb-3 text-sm text-muted-foreground">
            <Spinner className="size-3.5" aria-hidden /> Searching…
          </p>
        )}
        {q.length > 0 && (
          <div className="hidden items-center gap-1.5 border-t bg-muted/50 px-3 py-1.5 text-[11px] text-muted-foreground sm:flex">
            <Kbd>↑</Kbd>
            <Kbd>↓</Kbd> move
            <Kbd className="ml-2">
              <CornerDownLeft className="size-3" aria-hidden />
            </Kbd>{" "}
            show
            <Kbd className="ml-2">esc</Kbd> close
            <span className="ml-auto">Descriptions are never searched.</span>
          </div>
        )}
      </div>
    </div>
  );
}
