"use client";

import Link from "next/link";
import { Bot } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { SignInButtons, useChatGPTSignIn, useGoogleSignIn } from "./sign-in-buttons";

/**
 * The inline sign-in dialog (system spec, Sign-in → Flow, step 2) with the
 * notice at collection required by docs/compliance.md (CCPA) and the 16+
 * statement (GDPR Art. 8).
 */
export function SignInDialog({
  open,
  reason,
  returnTo,
  onOpenChange,
}: {
  open: boolean;
  /** One short sentence naming the feature, e.g. "Asking Dr. Wu needs an account." */
  reason?: string;
  returnTo?: string;
  onOpenChange: (open: boolean) => void;
}) {
  const google = useGoogleSignIn();
  const chatgpt = useChatGPTSignIn();
  const intro =
    chatgpt && google
      ? "With ChatGPT, Dr. Wu runs on your own plan. The atlas stays open to everyone."
      : chatgpt
        ? "Dr. Wu, the AI assistant, runs on your own ChatGPT plan. The atlas stays open to everyone."
        : "The atlas stays open to everyone.";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-0 overflow-hidden p-0 sm:max-w-md" data-testid="sign-in-dialog">
        <div className="space-y-5 p-6">
          <DialogHeader className="gap-3">
            <span className="flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <Bot className="size-5" aria-hidden />
            </span>
            <DialogTitle className="text-lg font-semibold tracking-tight">
              Sign in to continue
            </DialogTitle>
            <DialogDescription className="text-sm leading-relaxed text-muted-foreground">
              {reason ? `${reason} ` : ""}
              {intro}
            </DialogDescription>
          </DialogHeader>

          <SignInButtons returnTo={returnTo} buttonClassName="w-full" />

          <p className="text-xs text-muted-foreground">
            By continuing you confirm that you are <strong className="font-medium text-foreground">16 or older</strong>.
          </p>
        </div>

        <section
          aria-labelledby="notice-at-collection"
          className="space-y-2 border-t bg-muted/60 px-6 py-4 text-xs leading-relaxed text-muted-foreground"
        >
          <h3 id="notice-at-collection" className="font-medium text-foreground">
            What we collect and why
          </h3>
          <ul className="list-disc space-y-1 pl-4">
            <li>
              <span className="text-foreground">
                {chatgpt && google ? "From OpenAI or Google:" : google ? "From Google:" : "From OpenAI:"}
              </span>{" "}
              your name, email address and account ID to create your account.
              {chatgpt &&
                " With ChatGPT also an access token, stored encrypted, so Dr. Wu's requests run on your ChatGPT plan."}{" "}
              Doctors and researchers may add work details later, optional and private.
            </li>
            <li>
              <span className="text-foreground">A session cookie</span> that keeps you signed in.
              No tracking or advertising cookies.
            </li>
            <li>
              Health information (a profile, chats, documents) only if you add it and give your
              consent; contributing to the shared atlas needs a separate one.
            </li>
          </ul>
          <p>
            Used only to provide the features you ask for. Nothing is sold or shared. Account data
            is kept until you delete your account; server logs for at most 30 days.{" "}
            <Link href="/privacy" className="font-medium text-foreground underline underline-offset-2">
              Privacy notice
            </Link>
          </p>
        </section>
      </DialogContent>
    </Dialog>
  );
}
