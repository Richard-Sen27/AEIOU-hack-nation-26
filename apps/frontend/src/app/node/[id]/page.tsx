import type { Metadata } from "next";

import { PagePlaceholder } from "@/components/shell/page-placeholder";

function decodeId(raw: string) {
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

export async function generateMetadata(props: PageProps<"/node/[id]">): Promise<Metadata> {
  const { id } = await props.params;
  return { title: decodeId(id) };
}

export default async function NodePage(props: PageProps<"/node/[id]">) {
  const { id } = await props.params;
  const nodeId = decodeId(id);
  return (
    <PagePlaceholder
      eyebrow="Node"
      title={<span className="font-mono">{nodeId}</span>}
      description="One node and everything connected to it. Every link shows its source, confidence and whether it is data or a hypothesis."
      planned={[
        "Cytoscape.js neighbourhood view, starting where your lens starts",
        "Side panel with the node summary (GET /node/{id})",
        "Each connection with its evidence, confidence and contradictions",
        "Follow any connection: nothing is hidden by role",
      ]}
    />
  );
}
