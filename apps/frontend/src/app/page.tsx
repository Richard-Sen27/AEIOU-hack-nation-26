import { Network, ShieldCheck, Users } from "lucide-react";
import Image from "next/image";

import { LandingStart } from "@/components/landing/landing-start";
import { FlipWords } from "@/components/ui/flip-words";

// The three questions Amber answers for a patient leader (system spec).
const QUESTIONS = [
  {
    icon: Users,
    title: "Who is like us?",
    body: "Same cause or symptoms, any name.",
  },
  {
    icon: Network,
    title: "What already exists?",
    body: "Registries, studies and trials to reuse.",
  },
  {
    icon: ShieldCheck,
    title: "What do we do next?",
    body: "Shared experts, funders and one next step.",
  },
];

export default function Home() {
  return (
    <div className="relative isolate flex flex-1 flex-col">
      <div
        aria-hidden
        className="bg-atlas-grid pointer-events-none absolute inset-0 -z-10 [mask-image:radial-gradient(ellipse_at_top,black_30%,transparent_75%)]"
      />
      <LandingStart
        heading={
          <>
            <Image
              src="/amber-logo-128.png"
              alt=""
              width={64}
              height={64}
              unoptimized
              priority
              className="mb-5 size-14 drop-shadow-md sm:size-16"
            />
            <h1 className="text-3xl font-semibold tracking-tight text-balance sm:text-5xl">
              Start from a{" "}
              <FlipWords words={["diagnosis", "gene", "symptom", "patient group", "mechanism"]} className="text-primary" />
              <br className="hidden sm:block" /> and find who you have in common.
            </h1>
            <p className="mt-4 max-w-xl text-base leading-relaxed text-pretty text-muted-foreground sm:text-lg">
              A rare disease map. Every link shows its source.
            </p>
          </>
        }
        summary={
          <section aria-labelledby="what-heading" className="mx-auto w-full max-w-5xl px-4 pb-10 sm:px-6">
            <h2 id="what-heading" className="sr-only">
              What Amber answers
            </h2>
            <ol className="grid gap-px overflow-hidden rounded-xl border bg-border sm:grid-cols-3">
              {QUESTIONS.map((q, i) => (
                <li key={q.title} className="bg-card p-4">
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <span className="font-mono text-[11px] tabular">0{i + 1}</span>
                    <q.icon className="size-4 text-primary" aria-hidden />
                  </div>
                  <h3 className="mt-2 text-[15px] font-semibold tracking-tight">{q.title}</h3>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{q.body}</p>
                </li>
              ))}
            </ol>
          </section>
        }
      />
    </div>
  );
}
