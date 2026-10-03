"use client";

import { ThemeProvider } from "next-themes";

import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

import { SearchProvider } from "@/components/search/search-provider";

import { GateProvider } from "./gate-provider";
import { LensProvider } from "./lens-provider";
import { SessionProvider } from "./session-provider";

/** All app-wide providers, in dependency order. Mounted once in the root layout. */
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <SessionProvider>
        <LensProvider>
          <TooltipProvider delay={300}>
            <GateProvider>
              <SearchProvider>
                {children}
                <Toaster position="bottom-right" closeButton />
              </SearchProvider>
            </GateProvider>
          </TooltipProvider>
        </LensProvider>
      </SessionProvider>
    </ThemeProvider>
  );
}

export { useSession } from "./session-provider";
export { useLens, ROLE_LABELS } from "./lens-provider";
export { useGate } from "./gate-provider";
export { useSearch } from "@/components/search/search-provider";
