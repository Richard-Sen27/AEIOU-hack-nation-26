"use client";

import { BadgeCheck, Bot, FileSearch, ListChecks, MessageCircleQuestion, WifiOff } from "lucide-react";
import Link from "next/link";

import { SignInButtons, useGoogleSignIn } from "@/components/gates/sign-in-buttons";
import { AiDisclosure } from "@/components/shell/ai-disclosure";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const POINTS = [
  { icon: ListChecks, title: "You stay in control", body: "Only what you confirm is saved." },
  { icon: FileSearch, title: "Every claim is cited", body: "Sources, data or hypothesis, and contradictions." },
  { icon: MessageCircleQuestion, title: "One question at a time", body: "You can always skip it." },
  { icon: BadgeCheck, title: "A next step, not a diagnosis", body: "Like a registry to join. Never treatment advice." },
];

/** What Dr. Wu does, for guests, with the sign-in affordance. No broken chat. */
export function ChatGuest({ offline }: { offline?: boolean }) {
  const google = useGoogleSignIn();
  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6 sm:py-14" data-testid="chat-guest">
      <span className="flex size-11 items-center justify-center rounded-full bg-primary/15 text-primary">
        <Bot className="size-5" aria-hidden />
      </span>
      <p className="mt-5 font-mono text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Ask Dr. Wu</p>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight text-balance sm:text-3xl">
        Describe it in your own words, get cited connections back
      </h1>
      <p className="mt-3 text-[15px] leading-relaxed text-pretty text-muted-foreground">
        {google ? "An AI assistant. Sign in to start." : "An AI assistant on your own ChatGPT plan. Sign in to start."}
      </p>
      <AiDisclosure className="mt-6" />
      {offline && (
        <p className="mt-4 flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <WifiOff className="size-4" aria-hidden /> Amber&apos;s server can&apos;t be reached, so sign-in is unavailable.
        </p>
      )}
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <SignInButtons returnTo="/chat" />
        <Link href="/atlas" className={cn(buttonVariants({ variant: "outline", size: "lg" }), "h-[45px] px-4")}>
          Explore the atlas without an account
        </Link>
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        You must be 16 or older. Nothing is sold or shared.{" "}
        <Link href="/privacy" className="underline underline-offset-2">Privacy notice</Link>
      </p>
      <ul className="mt-10 grid gap-3 sm:grid-cols-2">
        {POINTS.map((p) => (
          <li key={p.title} className="rounded-xl border bg-card p-4">
            <p className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
              <p.icon className="size-4 text-primary" aria-hidden /> {p.title}
            </p>
            <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{p.body}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
