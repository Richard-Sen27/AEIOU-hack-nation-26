import type { Metadata } from "next";

import { PagePlaceholder } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "Review findings" };

export default async function DocumentPage(props: PageProps<"/documents/[id]">) {
  await props.params;
  return (
    <PagePlaceholder
      eyebrow="Documents · Review"
      title="Review what was found"
      description="Confirm or reject each finding. Only confirmed findings go into your profile."
      planned={[
        "Findings with page and highlighted snippet (GET /documents/{id}/findings)",
        "Confirm or reject each one",
        "Variants of uncertain significance flagged with the standard notice",
        "Delete the document and its findings",
      ]}
    />
  );
}
