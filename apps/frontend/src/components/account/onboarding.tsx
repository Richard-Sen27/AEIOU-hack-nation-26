"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { safeReturnTo, useSession } from "@/components/providers/session-provider";
import type { SessionUser } from "@/lib/api/types";

/** A signed-in user must pick a role and confirm 16+ before using features. */
export function needsOnboarding(user: SessionUser | null | undefined): boolean {
  return !!user && (!user.role || user.role === "guest" || !user.age_confirmed);
}

/** Pages a not-yet-onboarded user may still read (notices, the flow itself). */
const EXEMPT = ["/welcome", "/privacy", "/about-data"];

/** `/welcome?next=<path>`; the path only, never a query string. */
export function welcomeHref(returnTo: string | null | undefined): string {
  const next = safeReturnTo(returnTo ?? "/");
  return next === "/" ? "/welcome" : `/welcome?next=${encodeURIComponent(next)}`;
}

/**
 * Sends a signed-in user without role or 16+ confirmation to `/welcome`
 * (first sign-in), then back. Mounted once in the app providers.
 */
export function OnboardingRedirect() {
  const { user, status } = useSession();
  const pathname = usePathname() ?? "/";
  const router = useRouter();
  const incomplete = status === "ready" && needsOnboarding(user);
  const exempt = EXEMPT.some((p) => pathname === p || pathname.startsWith(`${p}/`));

  useEffect(() => {
    if (incomplete && !exempt) router.replace(welcomeHref(pathname));
  }, [incomplete, exempt, pathname, router]);

  return null;
}
