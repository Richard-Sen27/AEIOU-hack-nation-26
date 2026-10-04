"use client";

import { MessageSquare } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function messagesLabel(count: number, requests: number) {
  const parts = [count > 0 ? `${count} unread` : "", requests > 0 ? `${requests} waiting` : ""].filter(Boolean);
  return parts.length ? `Messages, ${parts.join(", ")}` : "Messages";
}

/** Unread count, or a dot when only requests are waiting. Counts only, never content. */
export function MessagesMark({ count, requests, className }: { count: number; requests: number; className?: string }) {
  if (count > 0) {
    return (
      <span
        className={cn(
          "flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 font-mono text-[10px] leading-none font-semibold text-primary-foreground tabular",
          className,
        )}
        aria-hidden
        data-testid="messages-count"
      >
        {count > 9 ? "9+" : count}
      </span>
    );
  }
  if (requests > 0) {
    return <span className={cn("size-2.5 rounded-full bg-primary ring-2 ring-background", className)} aria-hidden data-testid="messages-requests" />;
  }
  return null;
}

/** The header entry next to the bell. */
export function MessagesLink({ count, requests, active }: { count: number; requests: number; active: boolean }) {
  return (
    <Button
      variant="ghost"
      size="icon"
      className={cn("relative text-muted-foreground hover:text-foreground", active && "text-foreground")}
      aria-label={messagesLabel(count, requests)}
      aria-current={active ? "page" : undefined}
      nativeButton={false}
      render={<Link href="/messages" />}
      data-testid="messages-link"
    >
      <MessageSquare aria-hidden />
      <MessagesMark count={count} requests={requests} className="absolute -top-0.5 -right-0.5" />
    </Button>
  );
}
