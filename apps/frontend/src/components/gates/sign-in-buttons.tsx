"use client";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useGate } from "@/components/providers/gate-provider";
import { useSession } from "@/components/providers/session-provider";

import { ContinueWithChatGPT } from "./continue-with-chatgpt";
import { ContinueWithGoogle } from "./continue-with-google";

/**
 * Every sign-in method the API offers: ChatGPT always, Google only when
 * `/auth/session` lists it (never decided at build time).
 */
export function SignInButtons({
  returnTo,
  className,
  buttonClassName,
  onClick,
}: {
  returnTo?: string;
  className?: string;
  buttonClassName?: string;
  onClick?: () => void;
}) {
  const { signInMethods } = useSession();
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <ContinueWithChatGPT returnTo={returnTo} className={buttonClassName} onClick={onClick} />
      {signInMethods.includes("google") && (
        <ContinueWithGoogle returnTo={returnTo} className={buttonClassName} onClick={onClick} />
      )}
    </div>
  );
}

/** True when the server offers Google next to ChatGPT. */
export function useGoogleSignIn(): boolean {
  return useSession().signInMethods.includes("google");
}

/**
 * The header's sign-in slot: the compact ChatGPT button when it is the only
 * method, otherwise one "Sign in" button that opens the sign-in dialog.
 */
export function HeaderSignIn() {
  const google = useGoogleSignIn();
  const { openSignIn } = useGate();
  if (!google) return <ContinueWithChatGPT size="compact" />;
  return (
    <Button size="sm" className="h-9 px-3.5" onClick={() => openSignIn()} data-testid="header-sign-in">
      Sign in
    </Button>
  );
}
