"use client";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useGate } from "@/components/providers/gate-provider";
import { useSession } from "@/components/providers/session-provider";

import { ContinueWithChatGPT } from "./continue-with-chatgpt";
import { ContinueWithGoogle } from "./continue-with-google";

/**
 * Every sign-in method `/auth/session` lists (never decided at build time):
 * ChatGPT only where it can work, Google only when enabled. With neither, one
 * short line instead of a button.
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
  if (signInMethods.length === 0) return <SignInUnavailable className={className} />;
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {signInMethods.includes("openai") && (
        <ContinueWithChatGPT returnTo={returnTo} className={buttonClassName} onClick={onClick} />
      )}
      {signInMethods.includes("google") && (
        <ContinueWithGoogle returnTo={returnTo} className={buttonClassName} onClick={onClick} />
      )}
    </div>
  );
}

/** Shown where sign-in would be when the server offers no method. */
export function SignInUnavailable({ className }: { className?: string }) {
  return (
    <p className={cn("text-sm text-muted-foreground", className)} data-testid="sign-in-unavailable">
      Sign-in is not available here.
    </p>
  );
}

/** True when the server offers Google sign-in. */
export function useGoogleSignIn(): boolean {
  return useSession().signInMethods.includes("google");
}

/** True when the server offers ChatGPT sign-in (it can work there). */
export function useChatGPTSignIn(): boolean {
  return useSession().signInMethods.includes("openai");
}

/**
 * The header's sign-in slot: the compact ChatGPT button when it is the only
 * method, a short line when there is none, otherwise one "Sign in" button
 * that opens the sign-in dialog.
 */
export function HeaderSignIn() {
  const google = useGoogleSignIn();
  const chatgpt = useChatGPTSignIn();
  const { openSignIn } = useGate();
  if (!google && chatgpt) return <ContinueWithChatGPT size="compact" />;
  if (!google) return <SignInUnavailable className="whitespace-nowrap text-xs" />;
  return (
    <Button size="sm" className="h-9 px-3.5" onClick={() => openSignIn()} data-testid="header-sign-in">
      Sign in
    </Button>
  );
}
