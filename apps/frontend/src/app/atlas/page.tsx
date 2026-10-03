import type { Metadata } from "next";

import { PagePlaceholder } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "Atlas" };

export default function AtlasPage() {
  return (
    <PagePlaceholder
      eyebrow="Atlas"
      title="The whole map of rare diseases"
      description="Zoomed out: every disease in the atlas, grouped by shared mechanism and symptoms rather than by name."
      planned={[
        "Sigma.js view of all diseases with precomputed ForceAtlas2 positions",
        "Clusters labelled by their shared mechanism, with counterexamples",
        "Filter by connection type: shared biology, symptoms, research, community",
        "Click a node for a summary; open it for the full neighbourhood",
      ]}
    />
  );
}
