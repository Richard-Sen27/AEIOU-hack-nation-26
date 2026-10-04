"use client";

import { ChevronRight, ChevronsDownUp, FolderTree, Search } from "lucide-react";
import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

import { useLens } from "@/components/providers/lens-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { announce } from "@/lib/a11y";
import type { LabelStyle } from "@/lib/graph/meta";
import { nodeTypeMeta } from "@/lib/graph/meta";
import { cn } from "@/lib/utils";

import { categoryLabel, CATEGORY_META } from "./atlas-categories";
import type { AtlasOutlineProps } from "./atlas-props";
import { ancestorsOf, type AtlasTreeNode, type TreeIndex } from "./tree-model";

/** Most filter matches shown at once; the user is asked to type more beyond that. */
const MATCH_LIMIT = 300;

type Row = {
  node: AtlasTreeNode;
  /** 1 for categories. */
  level: number;
  setSize: number;
  posInSet: number;
  hasChildren: boolean;
  expanded: boolean;
  /** Matches the filter (filter mode only). */
  match: boolean;
};

function nodeName(n: AtlasTreeNode, labelStyle: LabelStyle): string {
  return n.kind === "category" && n.category ? categoryLabel(n.category, labelStyle) : n.label;
}

function kindName(n: AtlasTreeNode, labelStyle: LabelStyle): string {
  if (n.kind === "entity" && n.entity_type) return nodeTypeMeta(n.entity_type).label[labelStyle];
  return n.kind === "category" ? "Category" : "Group";
}

/**
 * Visible rows in pre-order. Only expanded branches are walked, so the cost
 * follows what is on screen, not the ~7,000 nodes of the whole tree. With a
 * filter, only matches and their ancestors are kept.
 */
function visibleRows(
  index: TreeIndex,
  isExpanded: (id: string) => boolean,
  keep: ((id: string) => boolean) | null,
  matches: Set<string> | null,
): Row[] {
  const rows: Row[] = [];
  const walk = (parentId: string, level: number) => {
    const all = index.children.get(parentId) ?? [];
    const kids = keep ? all.filter(keep) : all;
    kids.forEach((id, i) => {
      const node = index.nodes.get(id);
      if (!node) return;
      const childIds = index.children.get(id) ?? [];
      const hasChildren = keep ? childIds.some(keep) : childIds.length > 0;
      const expanded = hasChildren && isExpanded(id);
      rows.push({
        node,
        level,
        setSize: kids.length,
        posInSet: i + 1,
        hasChildren,
        expanded,
        match: matches?.has(id) ?? false,
      });
      if (expanded) walk(id, level + 1);
    });
  };
  walk(index.rootId, 1);
  return rows;
}

/**
 * The outline: the whole Atlas tree as an ARIA treeview, the keyboard and
 * screen-reader alternative to the canvas. Unlike the graph, branches here
 * open and close. Arrow keys move and open, Home/End jump, Enter shows the
 * item on the map, typing a few letters jumps to a matching name.
 */
export function AtlasOutline({ index, selectedId, onSelect, className }: AtlasOutlineProps) {
  const { labelStyle } = useLens();
  const treeRef = useRef<HTMLUListElement>(null);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const query = useDeferredValue(filter.trim().toLowerCase());
  // Branches the user closed while filtering; reset when the filter changes.
  const [filterClosed, setFilterClosed] = useState<{ q: string; ids: Set<string> }>({ q: "", ids: new Set() });

  // Filter: matches (capped) and the ancestors that lead to them.
  const filtered = useMemo(() => {
    if (!query) return null;
    const matches = new Set<string>();
    let total = 0;
    for (const n of index.nodes.values()) {
      if (n.kind === "root") continue;
      const name = nodeName(n, labelStyle).toLowerCase();
      if (name.includes(query) || (n.kind === "entity" && n.id.toLowerCase() === query)) {
        total += 1;
        if (matches.size < MATCH_LIMIT) matches.add(n.id);
      }
    }
    const path = new Set<string>();
    for (const id of matches) {
      for (const a of ancestorsOf(index, id)) {
        if (path.has(a.id)) break;
        path.add(a.id);
      }
    }
    return { matches, path, total };
  }, [index, query, labelStyle]);

  const closedInFilter = filterClosed.q === query ? filterClosed.ids : null;

  const rows = useMemo(() => {
    if (!filtered) return visibleRows(index, (id) => expanded.has(id), null, null);
    const { matches, path } = filtered;
    return visibleRows(
      index,
      (id) => path.has(id) && !closedInFilter?.has(id),
      (id) => matches.has(id) || path.has(id),
      matches,
    );
  }, [index, expanded, filtered, closedInFilter]);

  useEffect(() => {
    if (!filtered) return;
    const t = setTimeout(() => {
      announce(
        filtered.total === 0
          ? "Nothing matches"
          : `${filtered.total.toLocaleString("en")} ${filtered.total === 1 ? "match" : "matches"}`,
      );
    }, 400);
    return () => clearTimeout(t);
  }, [filtered]);

  // Reveal the selected node: open its ancestors and make it the focusable row.
  useEffect(() => {
    if (!selectedId || !index.nodes.has(selectedId)) return;
    const ancestors = ancestorsOf(index, selectedId).map((a) => a.id);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- follow the selection from the map
    setExpanded((prev) => {
      if (ancestors.every((id) => prev.has(id))) return prev;
      const next = new Set(prev);
      for (const id of ancestors) next.add(id);
      return next;
    });
    setFocusedId(selectedId);
    const frame = requestAnimationFrame(() => {
      treeRef.current
        ?.querySelector<HTMLElement>(`[data-id="${CSS.escape(selectedId)}"]`)
        ?.scrollIntoView({ block: "nearest" });
    });
    return () => cancelAnimationFrame(frame);
  }, [selectedId, index]);

  // The roving tabindex needs one row that is focusable.
  const tabbableId = rows.some((r) => r.node.id === focusedId)
    ? focusedId
    : rows.some((r) => r.node.id === selectedId)
      ? selectedId
      : (rows[0]?.node.id ?? null);

  const focusRow = useCallback((id: string) => {
    setFocusedId(id);
    requestAnimationFrame(() => {
      const el = treeRef.current?.querySelector<HTMLElement>(`[data-id="${CSS.escape(id)}"]`);
      el?.focus({ preventScroll: true });
      el?.scrollIntoView({ block: "nearest" });
    });
  }, []);

  const setOpen = useCallback(
    (id: string, open: boolean) => {
      if (filtered) {
        setFilterClosed((prev) => {
          const ids = new Set(prev.q === query ? prev.ids : []);
          if (open) ids.delete(id);
          else ids.add(id);
          return { q: query, ids };
        });
        return;
      }
      setExpanded((prev) => {
        if (prev.has(id) === open) return prev;
        const next = new Set(prev);
        if (open) next.add(id);
        else next.delete(id);
        return next;
      });
    },
    [filtered, query],
  );

  const activate = (row: Row) => {
    onSelect(row.node.id);
    if (row.hasChildren && !row.expanded) setOpen(row.node.id, true);
  };

  // Typeahead: letters typed in quick succession jump to the next matching name.
  const typeahead = useRef({ text: "", at: 0 });
  const jumpTo = (char: string, fromIndex: number) => {
    const now = Date.now();
    const ta = typeahead.current;
    ta.text = now - ta.at < 600 ? ta.text + char : char;
    ta.at = now;
    const text = ta.text.toLowerCase();
    // A repeated single letter cycles; a longer prefix starts at the current row.
    const start = text.length === 1 ? fromIndex + 1 : fromIndex;
    for (let k = 0; k < rows.length; k++) {
      const row = rows[(start + k) % rows.length];
      if (nodeName(row.node, labelStyle).toLowerCase().startsWith(text)) {
        focusRow(row.node.id);
        return;
      }
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLUListElement>) => {
    const i = rows.findIndex((r) => r.node.id === tabbableId);
    if (i < 0) return;
    const row = rows[i];
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        if (i < rows.length - 1) focusRow(rows[i + 1].node.id);
        break;
      case "ArrowUp":
        e.preventDefault();
        if (i > 0) focusRow(rows[i - 1].node.id);
        break;
      case "ArrowRight":
        e.preventDefault();
        if (row.hasChildren && !row.expanded) setOpen(row.node.id, true);
        else if (row.expanded && rows[i + 1]) focusRow(rows[i + 1].node.id);
        break;
      case "ArrowLeft": {
        e.preventDefault();
        if (row.expanded) {
          setOpen(row.node.id, false);
          break;
        }
        const parent = row.node.parent_id;
        if (parent && parent !== index.rootId) focusRow(parent);
        break;
      }
      case "Home":
        e.preventDefault();
        if (rows[0]) focusRow(rows[0].node.id);
        break;
      case "End":
        e.preventDefault();
        if (rows.length) focusRow(rows[rows.length - 1].node.id);
        break;
      case "Enter":
      case " ":
        e.preventDefault();
        activate(row);
        break;
      default:
        if (e.key.length === 1 && /\S/.test(e.key) && !e.ctrlKey && !e.metaKey && !e.altKey) {
          e.preventDefault();
          jumpTo(e.key, i);
        }
    }
  };

  const total = index.nodes.size - 1;

  return (
    <div data-testid="atlas-outline" className={cn("flex h-full min-h-0 flex-col", className)}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-3">
        <label className="relative w-full max-w-sm">
          <span className="sr-only">Filter the outline by name</span>
          <Search
            className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter by name"
            className="pl-8"
            maxLength={80}
            autoComplete="off"
            data-testid="atlas-outline-filter"
          />
        </label>
        <p className="text-xs text-muted-foreground" data-testid="atlas-outline-status">
          {filtered
            ? filtered.total === 0
              ? "Nothing matches"
              : filtered.total > MATCH_LIMIT
                ? `First ${MATCH_LIMIT} of ${filtered.total.toLocaleString("en")} matches. Type more to narrow it down.`
                : `${filtered.total.toLocaleString("en")} ${filtered.total === 1 ? "match" : "matches"}`
            : `${index.categories.size} trees · ${total.toLocaleString("en")} items`}
        </p>
        {!filtered && expanded.size > 0 && (
          <Button variant="ghost" size="sm" className="ml-auto" onClick={() => setExpanded(new Set())}>
            <ChevronsDownUp data-icon="inline-start" aria-hidden />
            Collapse all
          </Button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain py-1">
        {rows.length === 0 ? (
          <p className="p-6 text-center text-sm text-muted-foreground">
            Nothing matches. Try another name or part of a name.
          </p>
        ) : (
          <ul
            ref={treeRef}
            role="tree"
            aria-label="Everything on the map, as an outline"
            aria-describedby="atlas-outline-help"
            onKeyDown={onKeyDown}
            className="px-2 pb-4"
          >
            {rows.map((row) => {
              const { node } = row;
              const selected = node.id === selectedId;
              const name = nodeName(node, labelStyle);
              const color =
                node.kind === "entity" && node.entity_type
                  ? `var(${nodeTypeMeta(node.entity_type).colorVar})`
                  : node.category
                    ? `var(${CATEGORY_META[node.category].colorVar})`
                    : undefined;
              const Icon = node.kind === "entity" && node.entity_type ? nodeTypeMeta(node.entity_type).icon : FolderTree;
              return (
                <li
                  key={node.id}
                  role="treeitem"
                  data-id={node.id}
                  data-testid="atlas-outline-item"
                  aria-level={row.level}
                  aria-setsize={row.setSize}
                  aria-posinset={row.posInSet}
                  aria-expanded={row.hasChildren ? row.expanded : undefined}
                  aria-selected={selected}
                  tabIndex={node.id === tabbableId ? 0 : -1}
                  onFocus={() => setFocusedId(node.id)}
                  onClick={() => activate(row)}
                  style={{ paddingLeft: `${(row.level - 1) * 1.125 + 0.25}rem` }}
                  className={cn(
                    "group flex min-h-8 cursor-default items-center gap-1.5 rounded-md pr-2 text-sm outline-none [contain-intrinsic-size:auto_2rem] [content-visibility:auto]",
                    "hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset",
                    selected && "bg-primary/10 font-medium text-foreground hover:bg-primary/15",
                    node.kind === "category" && "font-medium",
                  )}
                >
                  <span
                    aria-hidden
                    onClick={(e) => {
                      if (!row.hasChildren) return;
                      e.stopPropagation();
                      setOpen(node.id, !row.expanded);
                      setFocusedId(node.id);
                    }}
                    className={cn(
                      "flex size-6 shrink-0 items-center justify-center rounded text-muted-foreground",
                      row.hasChildren && "hover:bg-muted hover:text-foreground",
                    )}
                  >
                    {row.hasChildren && (
                      <ChevronRight className={cn("size-3.5 transition-transform motion-reduce:transition-none", row.expanded && "rotate-90")} />
                    )}
                  </span>
                  <Icon className="size-3.5 shrink-0" style={{ color }} aria-hidden />
                  <span className={cn("min-w-0 flex-1 truncate", row.match && "underline decoration-primary/60 underline-offset-2")}>
                    {name}
                  </span>
                  <span className="hidden shrink-0 text-[11px] text-muted-foreground sm:inline">
                    {kindName(node, labelStyle)}
                  </span>
                  {node.kind !== "entity" && (
                    <span className="shrink-0 font-mono text-[11px] text-muted-foreground tabular-nums">
                      <span className="sr-only">, </span>
                      {node.entity_count.toLocaleString("en")}
                      <span className="sr-only"> items</span>
                    </span>
                  )}
                  {selected && <span className="sr-only">, shown on the map</span>}
                </li>
              );
            })}
          </ul>
        )}
        <p id="atlas-outline-help" className="sr-only">
          Arrow keys move and open branches, Home and End jump, Enter shows the item on the map. Type letters to jump
          to a name.
        </p>
      </div>
    </div>
  );
}
