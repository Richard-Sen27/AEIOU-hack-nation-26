"use client";

import { usePathname } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";

import { apiUrl } from "@/lib/api/config";
import { getSession, logout, unwrap } from "@/lib/api";
import type { SessionInfo, SessionUser } from "@/lib/api/types";
import type { AuthProvider } from "@/lib/api/generated/types.gen";

type SessionStatus = "loading" | "ready" | "offline";

type SessionContextValue = {
  /** `null` for guests (and while the API is unreachable). */
  user: SessionUser | null;
  /** Global Privacy Control as recorded by the API (or read from the browser). */
  gpc: boolean;
  demoMode: boolean;
  dataVersion: string | null;
  /** `offline`: the API could not be reached; the app runs as a guest. */
  status: SessionStatus;
  /** Sign-in methods the API offers (`openai` only where it can work, `google` only when enabled; may be empty). */
  signInMethods: AuthProvider[];
  /**
   * Navigate to the ChatGPT (default) or Google sign-in. `returnTo` must be a
   * relative path (defaults to the current page); never put health data in it.
   */
  signIn: (returnTo?: string, method?: AuthProvider) => void;
  signOut: () => Promise<void>;
  /** Re-fetch `/auth/session` (e.g. after a consent or role change). */
  refresh: () => Promise<SessionInfo | null>;
};

const SessionContext = createContext<SessionContextValue | null>(null);

const GUEST: SessionInfo = {
  user: null,
  gpc: false,
  demo_mode: false,
  data_version: null,
  sign_in_methods: ["openai"],
};

const noopSubscribe = () => () => {};
const readBrowserGpc = () =>
  (navigator as Navigator & { globalPrivacyControl?: boolean }).globalPrivacyControl === true;

/** Only same-origin relative paths; anything else falls back to `/`. */
export function safeReturnTo(path: string | undefined): string {
  if (!path || !path.startsWith("/") || path.startsWith("//")) return "/";
  return path;
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [session, setSession] = useState<SessionInfo>(GUEST);
  const [status, setStatus] = useState<SessionStatus>("loading");

  const refresh = useCallback(async () => {
    try {
      const data = await unwrap(getSession({ meta: { quiet: true }, cache: "no-store" }));
      const next = { ...GUEST, ...data };
      setSession(next);
      setStatus("ready");
      return next;
    } catch {
      // API down or not yet implemented: behave as a guest, never crash.
      setSession(GUEST);
      setStatus("offline");
      return null;
    }
  }, []);

  useEffect(() => {
    // Initial load; setState happens after the awaited fetch resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  const signIn = useCallback(
    (returnTo?: string, method: AuthProvider = "openai") => {
      // Keep only the path: query strings could carry user input.
      const target = safeReturnTo(returnTo ?? pathname ?? "/");
      const start = method === "google" ? "/auth/google/start" : "/auth/chatgpt/start";
      // Full navigation to the API's OAuth start (another origin).
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign(`${apiUrl(start)}?return_to=${encodeURIComponent(target)}`);
    },
    [pathname],
  );

  const signOut = useCallback(async () => {
    try {
      await unwrap(logout({ meta: { quiet: true } }));
    } catch {
      /* the cookie may already be gone; fall through */
    }
    setSession((s) => ({ ...s, user: null }));
    // Full reload on purpose: drops every in-memory trace of the signed-in user.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign("/");
  }, []);

  const browserGpc = useSyncExternalStore(noopSubscribe, readBrowserGpc, () => false);

  const value = useMemo<SessionContextValue>(
    () => ({
      user: session.user ?? null,
      gpc: !!session.gpc || browserGpc,
      demoMode: !!session.demo_mode,
      dataVersion: session.data_version ?? null,
      status,
      signInMethods: session.sign_in_methods ?? ["openai"],
      signIn,
      signOut,
      refresh,
    }),
    [session, status, signIn, signOut, refresh, browserGpc],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside <SessionProvider>");
  return ctx;
}
