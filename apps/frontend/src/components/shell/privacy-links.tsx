"use client";

import { Database, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/**
 * Privacy notice and about-this-data page for signed-out visitors (signed-in
 * users have them in the account menu). Application views have no footer, and
 * docs/compliance.md wants both reachable from every view.
 */
export function PrivacyMenu() {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            aria-label="Privacy and data"
            className="text-muted-foreground hover:text-foreground"
            data-testid="privacy-menu"
          />
        }
      >
        <ShieldCheck aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48">
        <DropdownMenuItem render={<Link href="/privacy" />}>
          <ShieldCheck aria-hidden /> Privacy
        </DropdownMenuItem>
        <DropdownMenuItem render={<Link href="/about-data" />}>
          <Database aria-hidden /> About this data
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
