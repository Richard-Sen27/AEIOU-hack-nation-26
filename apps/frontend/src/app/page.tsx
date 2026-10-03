import { ArrowRight, Network, ShieldCheck, Users } from "lucide-react";
import Image from "next/image";
import Link from "next/link";

import { HeroInput } from "@/components/landing/hero-input";
import { buttonVariants } from "@/components/ui/button";
import { FlipWords } from "@/components/ui/flip-words";
import { cn } from "@/lib/utils";

const QUESTIONS = [
  { icon: Users, title: "Who shares our disease characteristics?", body: "Diseases with the same mechanism or a similar symptom profile, even under a different name." },
  { icon: Network, title: "What useful work already exists?", body: "Registries, natural history studies, models and trials you could reuse instead of rebuilding." },
  { icon: ShieldCheck, title: "What should we do together next?", body: "Shared researchers and funders, and one concrete next step, with every link cited." },
];

export default function Home() {
  return (
    <div className="relative isolate flex flex-1 flex-col">
      <div
        aria-hidden
        className="bg-atlas-grid pointer-events-none absolute inset-0 -z-10 [mask-image:radial-gradient(ellipse_at_top,black_30%,transparent_75%)]"
      />
      <section className="mx-auto flex w-full max-w-4xl flex-col items-center px-4 pt-14 pb-12 text-center sm:px-6 sm:pt-20">
        <Image
          src="/amber-logo-128.png"
          alt=""
          width={72}
          height={72}
          unoptimized
          priority
          className="mb-6 size-16 drop-shadow-md sm:size-[72px]"
        />
        <p className="mb-4 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          Rare Disease Atlas
        </p>
        <h1 className="text-3xl font-semibold tracking-tight text-balance sm:text-5xl">
          Start from a <FlipWords words={["diagnosis", "gene", "symptom", "patient group", "mechanism"]} className="text-primary" />
          <br className="hidden sm:block" /> and find who you have in common.
        </h1>
        <p className="mt-5 max-w-2xl text-base leading-relaxed text-pretty text-muted-foreground sm:text-lg">
          About 10,000 rare diseases, one sourced map. Every connection shows where it comes from,
          how sure we are, and whether it is data or a hypothesis.
        </p>

        <div className="mt-9 w-full">
          <HeroInput />
        </div>

        <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
          <Link href="/atlas" className={cn(buttonVariants({ variant: "outline", size: "lg" }), "px-4")}>
            Explore the atlas <ArrowRight data-icon="inline-end" aria-hidden />
          </Link>
          <Link href="/clusters" className={cn(buttonVariants({ variant: "ghost", size: "lg" }), "px-4")}>
            Browse clusters
          </Link>
        </div>
      </section>

      <section aria-label="What Amber answers" className="mx-auto w-full max-w-5xl px-4 pb-16 sm:px-6">
        <ol className="grid gap-px overflow-hidden rounded-xl border bg-border sm:grid-cols-3">
          {QUESTIONS.map((q, i) => (
            <li key={q.title} className="bg-card p-5">
              <div className="flex items-center gap-2 text-muted-foreground">
                <span className="font-mono text-[11px] tabular">0{i + 1}</span>
                <q.icon className="size-4 text-primary" aria-hidden />
              </div>
              <h2 className="mt-3 text-[15px] font-semibold tracking-tight">{q.title}</h2>
              <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{q.body}</p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
