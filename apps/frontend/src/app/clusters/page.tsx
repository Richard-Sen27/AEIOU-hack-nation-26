import type { Metadata } from "next";

import { ClustersView } from "@/components/clusters/clusters-view";

export const metadata: Metadata = {
  title: "Clusters",
  description: "Diseases grouped by shared mechanism and symptoms, found by graph analysis and labelled as hypotheses.",
};

export default function ClustersPage() {
  return <ClustersView />;
}
