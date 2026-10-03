"use client";

import { MessageSquare, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import type { ChatSession } from "./types";

function when(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const today = new Date();
  return d.toDateString() === today.toDateString()
    ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function sessionTitle(s: ChatSession) {
  return s.title?.trim() || `Conversation of ${new Date(s.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;
}

/** Previous conversations: open, delete (with confirmation), start a new one. */
export function SessionList({
  status,
  items,
  activeId,
  disabled,
  onNew,
  onOpen,
  onDelete,
}: {
  status: "loading" | "ready" | "unavailable";
  items: ChatSession[];
  activeId: string | null;
  disabled?: boolean;
  onNew: () => void;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const [confirm, setConfirm] = useState<ChatSession | null>(null);
  return (
    <nav aria-label="Conversations" className="flex h-full min-h-0 flex-col gap-3" data-testid="session-list">
      <Button variant="outline" onClick={onNew} className="w-full justify-start" disabled={disabled}>
        <Plus aria-hidden /> New conversation
      </Button>
      <h2 className="px-1 font-mono text-[10.5px] uppercase tracking-[0.14em] text-muted-foreground">Previous</h2>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {status === "loading" && (
          <div className="space-y-2 px-1">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-4/5" />
          </div>
        )}
        {status === "unavailable" && (
          <p className="px-1 text-sm text-muted-foreground">Your previous conversations cannot be loaded right now.</p>
        )}
        {status === "ready" && items.length === 0 && (
          <p className="px-1 text-sm text-muted-foreground">No previous conversations yet.</p>
        )}
        <ul className="space-y-0.5">
          {items.map((s) => {
            const active = s.id === activeId;
            const title = sessionTitle(s);
            return (
              <li key={s.id} className={cn("group flex items-center rounded-lg", active ? "bg-accent" : "hover:bg-muted")} data-testid="session-item">
                <button
                  type="button"
                  onClick={() => onOpen(s.id)}
                  aria-current={active ? "true" : undefined}
                  disabled={disabled}
                  className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
                >
                  <MessageSquare className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                  <span className="min-w-0 flex-1 truncate" dir="auto">{title}</span>
                  <span className="shrink-0 text-[11px] text-muted-foreground">{when(s.updated_at)}</span>
                </button>
                <button
                  type="button"
                  onClick={() => setConfirm(s)}
                  aria-label={`Delete conversation: ${title}`}
                  className="mr-1 flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-destructive/10 hover:text-destructive focus-visible:ring-2 focus-visible:ring-ring sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
                >
                  <Trash2 className="size-3.5" aria-hidden />
                </button>
              </li>
            );
          })}
        </ul>
      </div>
      <AlertDialog open={confirm !== null} onOpenChange={(o) => !o && setConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this conversation?</AlertDialogTitle>
            <AlertDialogDescription>
              The conversation and its messages are deleted for good. Items you confirmed stay in
              your profile, where you can remove them.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                if (confirm) onDelete(confirm.id);
                setConfirm(null);
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </nav>
  );
}
