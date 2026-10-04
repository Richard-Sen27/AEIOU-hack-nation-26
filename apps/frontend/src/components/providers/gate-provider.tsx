"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { ConsentDialog } from "@/components/gates/consent-dialog";
import { SignInDialog } from "@/components/gates/sign-in-dialog";
import { setApiErrorHandler, type ApiError } from "@/lib/api/errors";
import { isDaily, limitInfo, limitMessage } from "@/lib/api/limits";
import { hasConsent, type ConsentType } from "@/lib/api/types";

import { useSession } from "./session-provider";

type GateContextValue = {
  /**
   * Resolves `true` if the user is signed in. Otherwise opens the sign-in
   * dialog and resolves `false` when it is dismissed (signing in navigates
   * away and comes back to `returnTo`, so it never resolves `true` later).
   */
  requireSignIn: (reason?: string, returnTo?: string) => Promise<boolean>;
  /**
   * Resolves `true` if the signed-in user holds an active consent of `type`.
   * Otherwise asks for sign-in first, then opens the consent dialog.
   * `renew`: open the dialog even with an active consent, because it was
   * given to an earlier text (granting the current text supersedes it).
   */
  requireConsent: (type: ConsentType, reason?: string, options?: { renew?: boolean }) => Promise<boolean>;
  /** Open the sign-in dialog without waiting (e.g. from a header button). */
  openSignIn: (reason?: string) => void;
};

const GateContext = createContext<GateContextValue | null>(null);

type Pending = (ok: boolean) => void;

export function GateProvider({ children }: { children: React.ReactNode }) {
  const { user, refresh } = useSession();
  const [signIn, setSignIn] = useState<{ reason?: string; returnTo?: string } | null>(null);
  const [consentType, setConsentType] = useState<ConsentType | null>(null);
  const signInWaiters = useRef<Pending[]>([]);
  const consentWaiters = useRef<Pending[]>([]);

  const settle = (ref: React.RefObject<Pending[]>, ok: boolean) => {
    const waiters = ref.current;
    ref.current = [];
    waiters.forEach((w) => w(ok));
  };

  const openSignIn = useCallback((reason?: string, returnTo?: string) => {
    setSignIn({ reason, returnTo });
  }, []);

  const requireSignIn = useCallback(
    (reason?: string, returnTo?: string) => {
      if (user) return Promise.resolve(true);
      return new Promise<boolean>((resolve) => {
        signInWaiters.current.push(resolve);
        openSignIn(reason, returnTo);
      });
    },
    [user, openSignIn],
  );

  const requireConsent = useCallback(
    async (type: ConsentType, reason?: string, options?: { renew?: boolean }) => {
      if (!(await requireSignIn(reason))) return false;
      if (hasConsent(user, type) && !options?.renew) return true;
      return new Promise<boolean>((resolve) => {
        consentWaiters.current.push(resolve);
        setConsentType(type);
      });
    },
    [requireSignIn, user],
  );

  // Route API errors from anywhere in the app.
  useEffect(
    () =>
      setApiErrorHandler((error: ApiError) => {
        switch (error.code) {
          case "sign_in_required":
            openSignIn();
            return;
          case "reauth_required":
            openSignIn("Your ChatGPT sign-in has expired.");
            return;
          case "consent_required": {
            const t = error.details.consent_type;
            const contribute = t === "contribute" || /contribut/i.test(error.message);
            setConsentType(contribute ? "contribute" : "health_data");
            return;
          }
          case "assistant_unavailable":
            toast("Dr. Wu is not available for this sign-in", {
              id: "assistant-unavailable",
              description: "The atlas works as usual.",
            });
            return;
          case "upstream_error":
            toast("A connected service did not respond", {
              id: "upstream-error",
              description: "Please try again in a moment.",
            });
            return;
          case "network_error":
            toast("Amber's server is not reachable", {
              id: "api-offline",
              description: "You can keep browsing; some features are unavailable right now.",
            });
            return;
          case "not_implemented":
            toast("Not available yet", {
              id: "not-implemented",
              description: "This part of Amber is still being built.",
            });
            return;
          case "rate_limited": {
            const limit = limitInfo(error);
            toast(isDaily(limit) ? "Daily limit reached" : "Please wait a moment", {
              id: "rate-limited",
              description: limit ? limitMessage(limit, "this feature") : "Too many requests. Try again shortly.",
            });
            return;
          }
          case "busy":
            toast("Amber is busy", { id: "busy", description: "Try again in a moment." });
            return;
          default:
            if (error.status >= 500) {
              toast("Something went wrong on our side", { id: "server-error" });
            }
        }
      }),
    [openSignIn],
  );

  const value = useMemo<GateContextValue>(
    () => ({ requireSignIn, requireConsent, openSignIn }),
    [requireSignIn, requireConsent, openSignIn],
  );

  return (
    <GateContext.Provider value={value}>
      {children}
      <SignInDialog
        open={signIn !== null}
        reason={signIn?.reason}
        returnTo={signIn?.returnTo}
        onOpenChange={(open) => {
          if (!open) {
            setSignIn(null);
            settle(signInWaiters, false);
          }
        }}
      />
      <ConsentDialog
        type={consentType}
        onGranted={async () => {
          setConsentType(null);
          await refresh();
          settle(consentWaiters, true);
        }}
        onCancel={() => {
          setConsentType(null);
          settle(consentWaiters, false);
        }}
      />
    </GateContext.Provider>
  );
}

export function useGate(): GateContextValue {
  const ctx = useContext(GateContext);
  if (!ctx) throw new Error("useGate must be used inside <GateProvider>");
  return ctx;
}
