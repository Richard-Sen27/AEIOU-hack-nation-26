import type { Metadata } from "next";

import { PagePlaceholder } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "About this data" };

export default function AboutDataPage() {
  return (
    <PagePlaceholder
      eyebrow="About this data"
      title="Where the atlas comes from"
      description="The graph is built from public scientific databases and literature. Researchers and doctors appear only with public professional information and can claim or remove their profile."
      planned={[
        "Sources: MONDO, HGNC, HPO, ClinVar, ClinGen, Reactome, Orphanet, PubMed, ClinicalTrials.gov, NIH RePORTER",
        "How confidence is computed and what 'data' versus 'hypothesis' means",
        "Notice for people in the graph (GDPR Art. 14) and the claim-or-remove flow",
        "Current data version and when it was built",
      ]}
    />
  );
}
