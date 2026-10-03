import type { Metadata } from "next";

import { PagePlaceholder } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "Path" };

export default function PathPage() {
  return (
    <PagePlaceholder
      eyebrow="Path"
      title="How two things are connected"
      description="The most trustworthy cited route between two nodes, step by step. If no supported route exists, Amber says so and names the missing evidence."
      planned={[
        "React Flow view of the top paths (GET /path?from=&to=&family=)",
        "Explanation in your lens, streamed with citations (POST /explain)",
        "No-supported-route report: sources queried, closest partial path, missing link",
        "Gap search for signed-in users; results stay pending review",
      ]}
    />
  );
}
