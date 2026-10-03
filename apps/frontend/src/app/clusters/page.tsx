import type { Metadata } from "next";

import { PagePlaceholder } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "Clusters" };

export default function ClustersPage() {
  return (
    <PagePlaceholder
      eyebrow="Clusters"
      title="Diseases grouped by what they share"
      description="Groups of diseases that share a mechanism or a symptom profile, found by graph analysis and labelled as hypotheses."
      planned={[
        "Cluster list with size, shared genes and pathways (GET /clusters)",
        "Each cluster's mechanism summary, marked as inferred",
        "Known counterexamples, e.g. same gene but a different mechanism",
        "Ranked view for mechanism queries in expert mode",
      ]}
    />
  );
}
