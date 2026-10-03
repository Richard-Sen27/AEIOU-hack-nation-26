"use client";

import { LocateFixed } from "lucide-react";
import { useMemo, useState } from "react";

import { useLens } from "@/components/providers/lens-provider";
import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { nodeTypeMeta } from "@/lib/graph/meta";

import { searchAtlas, type AtlasIndex } from "./atlas-model";

/**
 * "Find on the map": filters the Atlas labels locally (nothing is sent to
 * the server) and focuses the chosen node.
 */
export function AtlasFind({ index, onPick }: { index: AtlasIndex; onPick: (id: string) => void }) {
  const { labelStyle } = useLens();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const hits = useMemo(() => searchAtlas(index, q, 10), [index, q]);

  return (
    <Popover
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) setQ("");
      }}
    >
      <PopoverTrigger
        render={
          <Button
            variant="outline"
            size="sm"
            data-testid="atlas-find"
            data-tour="find"
            className="data-[tour-active]:ring-2 data-[tour-active]:ring-primary data-[tour-active]:ring-offset-2 data-[tour-active]:ring-offset-background"
          />
        }
      >
        <LocateFixed data-icon="inline-start" aria-hidden />
        Find on map
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 p-0">
        <Command shouldFilter={false} loop className="rounded-lg">
          <CommandInput
            value={q}
            onValueChange={setQ}
            placeholder="Name or ID on the map…"
            aria-label="Find on the map"
            maxLength={80}
          />
          <CommandList className="max-h-72">
            {q.trim() && <CommandEmpty>Not on the map.</CommandEmpty>}
            {hits.map((n) => {
              const meta = nodeTypeMeta(n.type);
              const Icon = meta.icon;
              return (
                <CommandItem
                  key={n.id}
                  value={n.id}
                  onSelect={() => {
                    onPick(n.id);
                    setOpen(false);
                    setQ("");
                  }}
                  className="gap-2"
                >
                  <Icon className="size-3.5 shrink-0" style={{ color: `var(${meta.colorVar})` }} aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{n.label}</span>
                    <span className="block truncate text-[11px] text-muted-foreground">
                      {meta.label[labelStyle]} · <span className="font-mono">{n.id}</span>
                    </span>
                  </span>
                </CommandItem>
              );
            })}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
