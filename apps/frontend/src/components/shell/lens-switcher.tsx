"use client";

import { ChevronDown, Database, Glasses, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { ROLE_LABELS, useLens } from "@/components/providers/lens-provider";
import { useSession } from "@/components/providers/session-provider";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { announce } from "@/lib/a11y";
import { ROLES, type Role } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

/** Switch the role lens: changes wording and starting point, never what is visible. */
export function LensSwitcher({ className, compact }: { className?: string; compact?: boolean }) {
  const { role, setRole, resetRole, overridden } = useLens();
  const { user } = useSession();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            size={compact ? "icon" : "default"}
            className={cn("gap-1.5 text-muted-foreground hover:text-foreground", className)}
            aria-label={`View as: ${ROLE_LABELS[role].label}. Change lens`}
            data-testid="lens-switcher"
          />
        }
      >
        <Glasses aria-hidden />
        {!compact && (
          <>
            <span className="text-foreground">{ROLE_LABELS[role].label}</span>
            <ChevronDown className="size-3.5 opacity-60" aria-hidden />
          </>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="px-2 py-1.5">
            <span className="block text-xs font-medium text-foreground">View as</span>
            <span className="block text-xs font-normal text-muted-foreground">
              Changes wording and where you start. Everyone sees the same evidence.
            </span>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuRadioGroup
          value={role}
          onValueChange={(v) => {
            setRole(v as Role);
            announce(`Lens changed to ${ROLE_LABELS[v as Role].label}`);
          }}
        >
          {ROLES.map((r) => (
            <DropdownMenuRadioItem key={r} value={r} className="items-start py-1.5">
              <span className="flex flex-col">
                <span>{ROLE_LABELS[r].label}</span>
                <span className="text-xs text-muted-foreground">{ROLE_LABELS[r].description}</span>
              </span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        {!user && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem render={<Link href="/privacy" />}>
              <ShieldCheck aria-hidden /> Privacy
            </DropdownMenuItem>
            <DropdownMenuItem render={<Link href="/about-data" />}>
              <Database aria-hidden /> About this data
            </DropdownMenuItem>
          </>
        )}
        {user?.role && overridden && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={resetRole}>
              Back to my role ({ROLE_LABELS[user.role].label})
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
