"use client";

import { BadgeCheck, Bot, FileSearch, ListChecks, MessageCircleQuestion, WifiOff } from "lucide-react";
import Link from "next/link";

import { ContinueWithChatGPT } from "@/components/gates/continue-with-chatgpt";
import { AiDisclosure } from "@/components/shell/ai-disclosure";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const POINTS = [
  { icon: ListChecks, title: "You stay in control", body: "It shows what it understood as items you confirm, correct or remove. Only confirmed items are saved to your private profile." },
  { icon: FileSearch, title: "Every claim is cited", body: "Each answer links to its sources, says whether it is data or a hypothesis, and shows contradicting findings." },
  { icon: MessageCircleQuestion, title: "One question at a time", body: "If it needs more detail, it asks one question you can always skip." },
  { icon: BadgeCheck, title: "A next step, not a diagnosis", body: "It ends with a concrete shared action, like a registry to join. It never diagnoses or advises on treatment." },
];

/** What Dr. Wu does, for guests, with the sign-in affordance. No broken chat. */
export function ChatGuest({ offline }: { offline?: boolean }) {
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
        Dr. Wu is an AI assistant that turns a diagnosis, a gene or symptoms into connections in the
        atlas: who shares your disease&apos;s characteristics, what already exists, and what to do
        together next. It runs on your own ChatGPT plan, so it needs you to sign in.
      </p>
      <AiDisclosure className="mt-6" />
      {offline && (
        <p className="mt-4 flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <WifiOff className="size-4" aria-hidden /> Amber&apos;s server can&apos;t be reached right now, so sign-in is unavailable.
        </p>
      )}
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <ContinueWithChatGPT returnTo="/chat" />
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
