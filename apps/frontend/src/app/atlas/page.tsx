import type { Metadata } from "next";
import { Suspense } from "react";

import { AtlasView } from "@/components/atlas/atlas-view";

export const metadata: Metadata = {
  title: "Atlas",
  description: "The whole map of rare diseases: one tree each for conditions, symptoms, genes, researchers, doctors and more, around one hub.",
};

/** `/atlas?focus=<node id>` selects and centres a node; `?tour=1` starts the guided tour. */
export default function AtlasPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-0 flex-1 flex-col" data-fit-viewport>
          <h1 className="border-b px-6 py-3 text-base font-semibold">Atlas</h1>
        </div>
      }
    >
      <AtlasView />
    </Suspense>
  );
}
