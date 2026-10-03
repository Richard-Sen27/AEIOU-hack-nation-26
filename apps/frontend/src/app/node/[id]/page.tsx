import type { Metadata } from "next";

import { NodeView } from "@/components/node/node-view";

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

/** `/node/<public graph id>`: one node, its full neighbourhood and the trust layer for every connection. */
export default async function NodePage(props: PageProps<"/node/[id]">) {
  const { id } = await props.params;
  const nodeId = decodeId(id);
  return <NodeView key={nodeId} nodeId={nodeId} />;
}
