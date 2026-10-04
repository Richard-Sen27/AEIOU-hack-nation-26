"use client";

import { Bell, ChevronDown, Menu, Search } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { ContinueWithChatGPT } from "@/components/gates/continue-with-chatgpt";
import { CountBadge, NotificationBell, unreadLabel } from "@/components/notifications/notification-bell";
import { NotificationList } from "@/components/notifications/notification-list";
import { useUnreadCount } from "@/components/notifications/use-unread-count";
import { useSession } from "@/components/providers/session-provider";
import { useSearch } from "@/components/search/search-provider";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

import { PrivacyMenu } from "./privacy-links";
import { ThemeToggle } from "./theme-toggle";
import { UserMenu } from "./user-menu";

export const PRIMARY_NAV = [
  { href: "/atlas", label: "Atlas" },
  { href: "/clusters", label: "Clusters" },
  { href: "/chat", label: "Ask Dr. Wu" },
  { href: "/documents", label: "Documents" },
] as const;

function isActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <Link href="/" className={cn("group flex items-center gap-2.5 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring", className)}>
      <Image
        src="/amber-logo-128.png"
        alt=""
        width={28}
        height={28}
        unoptimized
        priority
        className="size-7 drop-shadow-sm transition-transform group-hover:-rotate-6"
      />
      <span className="text-[15px] leading-none font-semibold tracking-tight">Amber</span>
      <span className="sr-only">, home</span>
    </Link>
  );
}

export function SiteHeader() {
  const pathname = usePathname() ?? "/";
  const { user, status } = useSession();
  const { openSearch } = useSearch();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [mobileList, setMobileList] = useState(false);
  const unread = useUnreadCount();

  return (
    <header className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur supports-[backdrop-filter]:bg-background/70">
      <div className="mx-auto flex h-14 w-full max-w-[1440px] items-center gap-3 px-4 sm:px-6">
        <Wordmark className="mr-2 shrink-0" />

        <nav aria-label="Primary" className="hidden shrink-0 md:block">
          <ul className="flex items-center gap-0.5">
            {PRIMARY_NAV.map((item) => {
              const active = isActive(pathname, item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "relative rounded-md px-3 py-1.5 text-sm whitespace-nowrap text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring",
                      active && "text-foreground after:absolute after:inset-x-3 after:-bottom-[13px] after:h-0.5 after:rounded-full after:bg-primary",
                    )}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="ml-auto flex min-w-0 items-center gap-1">
          <button
            type="button"
            onClick={() => openSearch()}
            className="hidden h-8 w-56 min-w-0 items-center gap-2 rounded-lg border bg-card/60 px-2.5 text-sm text-muted-foreground shadow-xs transition-colors outline-none hover:bg-card hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring sm:flex lg:w-64"
            aria-label="Search the atlas"
            aria-keyshortcuts="Meta+K Control+K"
            data-testid="search-trigger"
          >
            <Search className="size-4 shrink-0" aria-hidden />
            <span className="flex-1 truncate text-left">Search the atlas…</span>
            <Kbd className="shrink-0 text-[10px]">⌘K</Kbd>
          </button>
          <Button
            variant="ghost"
            size="icon"
            className="sm:hidden"
            aria-label="Search the atlas"
            onClick={() => openSearch()}
          >
            <Search aria-hidden />
          </Button>

          <div className="hidden shrink-0 items-center gap-1 md:flex">
            {!user && status !== "loading" && <PrivacyMenu />}
            <ThemeToggle />
            {unread.enabled && <NotificationBell count={unread.count} onCount={unread.setCount} />}
          </div>

          <div className="hidden min-w-9 shrink-0 items-center justify-end pl-1 md:flex">
            {user ? (
              <UserMenu />
            ) : status === "loading" ? (
              <span className="h-9 w-[178px]" aria-hidden />
            ) : (
              <ContinueWithChatGPT size="compact" />
            )}
          </div>

          <Sheet
            open={mobileOpen}
            onOpenChange={(open) => {
              setMobileOpen(open);
              if (!open) setMobileList(false);
            }}
          >
            <SheetTrigger
              render={
                <Button
                  variant="ghost"
                  size="icon"
                  className="relative md:hidden"
                  aria-label={unread.enabled && unread.count > 0 ? `Open menu, ${unread.count} unread` : "Open menu"}
                />
              }
            >
              <Menu aria-hidden />
              {unread.enabled && unread.count > 0 && (
                <span className="absolute top-1.5 right-1.5 size-2 rounded-full bg-primary" aria-hidden data-testid="menu-unread-dot" />
              )}
            </SheetTrigger>
            <SheetContent side="right" className="w-[86vw] max-w-sm gap-0 p-0">
              <SheetHeader className="border-b px-5 py-4">
                <SheetTitle>Menu</SheetTitle>
                <SheetDescription className="sr-only">Navigation and settings</SheetDescription>
              </SheetHeader>
              <nav aria-label="Primary" className="px-3 py-3">
                <ul className="space-y-0.5">
                  {PRIMARY_NAV.map((item) => (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        onClick={() => setMobileOpen(false)}
                        aria-current={isActive(pathname, item.href) ? "page" : undefined}
                        className="flex rounded-md px-3 py-2.5 text-base text-muted-foreground hover:bg-muted hover:text-foreground aria-[current=page]:bg-accent aria-[current=page]:text-accent-foreground"
                      >
                        {item.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </nav>
              {unread.enabled && (
                <>
                  <Separator />
                  <div className="px-3 py-2">
                    <button
                      type="button"
                      onClick={() => setMobileList((o) => !o)}
                      aria-expanded={mobileList}
                      aria-label={unreadLabel(unread.count)}
                      className="flex w-full items-center gap-2 rounded-md px-3 py-2.5 text-base text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                      data-testid="menu-notifications"
                    >
                      <Bell className="size-4" aria-hidden />
                      <span className="flex-1 text-left">Notifications</span>
                      <CountBadge count={unread.count} />
                      <ChevronDown className={cn("size-4 transition-transform", mobileList && "rotate-180")} aria-hidden />
                    </button>
                    {mobileList && (
                      <NotificationList className="px-2 pt-1" showTitle={false} onCount={unread.setCount} onNavigate={() => setMobileOpen(false)} />
                    )}
                  </div>
                </>
              )}
              <Separator />
              <div className="flex items-center justify-between px-5 py-3">
                <span className="text-sm text-muted-foreground">Theme</span>
                <ThemeToggle />
              </div>
              <Separator />
              <div className="px-5 py-4">
                {user ? (
                  <div className="flex items-center justify-between">
                    <span className="truncate text-sm">{user.name || user.email}</span>
                    <UserMenu />
                  </div>
                ) : (
                  <>
                    <ContinueWithChatGPT className="w-full" onClick={() => setMobileOpen(false)} />
                    <p className="mt-4 flex gap-4 text-sm">
                      <Link href="/privacy" onClick={() => setMobileOpen(false)} className="text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
                        Privacy
                      </Link>
                      <Link href="/about-data" onClick={() => setMobileOpen(false)} className="text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
                        About this data
                      </Link>
                    </p>
                  </>
                )}
              </div>
            </SheetContent>
          </Sheet>
        </div>
      </div>
    </header>
  );
}
