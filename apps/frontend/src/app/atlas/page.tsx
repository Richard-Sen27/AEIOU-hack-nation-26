import type { Metadata } from "next";
import { Suspense } from "react";

import { AtlasView } from "@/components/atlas/atlas-view";

export const metadata: Metadata = {
  title: "Atlas",
  description: "The whole map of rare diseases, grouped by shared mechanism and symptoms rather than by name.",
};

/** `/atlas?focus=<node id>` selects and centres a node; `?tour=1` starts the guided tour. */
export default function AtlasPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-[calc(100dvh-3.5rem)] flex-col">
          <h1 className="border-b px-6 py-3 text-base font-semibold">Atlas</h1>
        </div>
      }
    >
      <AtlasView />
    </Suspense>
  );
}
