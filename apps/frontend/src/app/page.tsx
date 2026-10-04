import Image from "next/image";

import { ConnectSection } from "@/components/landing/connect-section";
import { DemoJourney } from "@/components/landing/demo-journey";
import { GraphSection } from "@/components/landing/graph-section";
import { LandingStart } from "@/components/landing/landing-start";
import { PrepSection } from "@/components/landing/prep-section";

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
              className="mb-5 size-12 drop-shadow-md sm:size-14"
            />
            <h1 className="text-3xl font-semibold tracking-tight text-balance sm:text-5xl">
              Rare diseases, connected by what they share.
            </h1>
            <p className="mt-4 max-w-xl text-base leading-relaxed text-pretty text-muted-foreground sm:text-lg">
              Genes, symptoms, experts and patient groups on one map.
            </p>
          </>
        }
      />
      <GraphSection />
      <PrepSection />
      <ConnectSection />
      <DemoJourney />
    </div>
  );
}
