"use client";

import { LogOut, ShieldCheck, UserRound } from "lucide-react";
import Link from "next/link";

import { ROLE_LABELS } from "@/components/providers/lens-provider";
import { useSession } from "@/components/providers/session-provider";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

function initials(name?: string | null, email?: string | null) {
  const src = (name || email || "?").trim();
  const parts = src.split(/[\s@._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts[1]?.[0] ?? "")).toUpperCase();
}

export function UserMenu() {
  const { user, signOut } = useSession();
  if (!user) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="ghost" size="icon" className="rounded-full" aria-label="Account menu" data-testid="user-menu" />
        }
      >
        <Avatar className="size-7">
          <AvatarFallback className="bg-accent text-[11px] font-medium text-accent-foreground">
            {initials(user.name, user.email)}
          </AvatarFallback>
        </Avatar>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="px-2 py-1.5">
            <span className="block truncate text-sm font-medium text-foreground">
              {user.name || "Signed in"}
            </span>
            {user.email && (
              <span className="block truncate text-xs font-normal text-muted-foreground">{user.email}</span>
            )}
            {user.role && (
              <span className="mt-1 block text-xs font-normal text-muted-foreground">
                {ROLE_LABELS[user.role].label}
                {user.role_verified ? " · verified" : ""}
              </span>
            )}
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem render={<Link href="/profile" />}>
          <UserRound aria-hidden /> Profile
        </DropdownMenuItem>
        <DropdownMenuItem render={<Link href="/privacy" />}>
          <ShieldCheck aria-hidden /> Privacy and data
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => void signOut()}>
          <LogOut aria-hidden /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
