"use client";

import { usePathname } from "next/navigation";
import Script from "next/script";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import {
  ANALYTICS_HOSTNAMES,
  ANALYTICS_SCRIPT_SRC,
  ANALYTICS_WEBSITE_ID,
  BEFORE_SEND_GLOBAL,
  analyticsAllowed,
  beforeSend,
  redactReferrer,
  routePattern,
  umamiClient,
} from "@/lib/analytics";

const noSubscribe = () => () => {};
const allowedOnClient = () => analyticsAllowed(window.location.hostname);
const neverOnServer = () => false;

/**
 * Counts page views by route pattern on the hosted site only (see lib/analytics.ts); other
 * hosts, dev builds and NEXT_PUBLIC_ANALYTICS=off never load the script. Automatic tracking is
 * off: every view is sent here, with the route pattern instead of the path, no title, and a
 * redacted referrer. Feature events go through `trackEvent`.
 */
export function PageCounter() {
  const pathname = usePathname();
  const allowed = useSyncExternalStore(noSubscribe, allowedOnClient, neverOnServer);
  const [loaded, setLoaded] = useState(false);
  const lastPath = useRef<string | null>(null);

  useEffect(() => {
    if (allowed) (window as unknown as Record<string, unknown>)[BEFORE_SEND_GLOBAL] = beforeSend;
  }, [allowed]);

  useEffect(() => {
    const umami = umamiClient();
    if (!allowed || !loaded || !umami || !pathname || pathname === lastPath.current) return;
    const referrer =
      lastPath.current === null
        ? redactReferrer(document.referrer, window.location.origin)
        : routePattern(lastPath.current);
    lastPath.current = pathname;
    const url = routePattern(pathname);
    void umami.track((props) => ({
      website: props.website,
      hostname: props.hostname,
      screen: props.screen,
      language: props.language,
      url,
      ...(referrer ? { referrer } : {}),
    }));
  }, [allowed, loaded, pathname]);

  if (!allowed) return null;
  return (
    <Script
      src={ANALYTICS_SCRIPT_SRC}
      strategy="afterInteractive"
      referrerPolicy="no-referrer"
      data-website-id={ANALYTICS_WEBSITE_ID}
      data-auto-track="false"
      data-exclude-search="true"
      data-exclude-hash="true"
      data-domains={ANALYTICS_HOSTNAMES.join(",")}
      data-before-send={BEFORE_SEND_GLOBAL}
      onLoad={() => setLoaded(true)}
    />
  );
}
