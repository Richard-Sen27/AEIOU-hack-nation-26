"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { GlobalSearchDialog } from "./global-search-dialog";

type SearchContextValue = {
  /** Open the global search palette, optionally pre-filled with a short term. */
  openSearch: (initialQuery?: string) => void;
  closeSearch: () => void;
  open: boolean;
};

const SearchContext = createContext<SearchContextValue | null>(null);

/** Global search palette; opens on ⌘K / Ctrl+K and "/" (outside text fields). */
export function SearchProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [initial, setInitial] = useState("");

  const openSearch = useCallback((q?: string) => {
    setInitial(q ?? "");
    setOpen(true);
  }, []);
  const closeSearch = useCallback(() => setOpen(false), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const typing =
        !!target &&
        (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((o) => !o);
        setInitial("");
      } else if (e.key === "/" && !typing && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        openSearch();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openSearch]);

  const value = useMemo(() => ({ openSearch, closeSearch, open }), [openSearch, closeSearch, open]);

  return (
    <SearchContext.Provider value={value}>
      {children}
      <GlobalSearchDialog open={open} onOpenChange={setOpen} initialQuery={initial} />
    </SearchContext.Provider>
  );
}

export function useSearch(): SearchContextValue {
  const ctx = useContext(SearchContext);
  if (!ctx) throw new Error("useSearch must be used inside <SearchProvider>");
  return ctx;
}
