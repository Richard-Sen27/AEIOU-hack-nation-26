"use client";

import { Bell } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

import { NotificationList } from "./notification-list";

export function unreadLabel(count: number) {
  return count > 0 ? `Notifications, ${count} unread` : "Notifications";
}

export function CountBadge({ count, className }: { count: number; className?: string }) {
  if (count <= 0) return null;
  return (
    <span
      className={cn(
        "flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 font-mono text-[10px] leading-none font-semibold text-primary-foreground tabular",
        className,
      )}
      aria-hidden
      data-testid="notifications-count"
    >
      {count > 9 ? "9+" : count}
    </span>
  );
}

/** The header bell: unread count, and the list in a popover. */
export function NotificationBell({ count, onCount }: { count: number; onCount: (count: number) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            className="relative text-muted-foreground hover:text-foreground"
            aria-label={unreadLabel(count)}
            data-testid="notifications-bell"
          />
        }
      >
        <Bell aria-hidden />
        <CountBadge count={count} className="absolute -top-0.5 -right-0.5" />
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[min(24rem,calc(100vw-2rem))] p-2">
        {open && <NotificationList onCount={onCount} onNavigate={() => setOpen(false)} />}
      </PopoverContent>
    </Popover>
  );
}
