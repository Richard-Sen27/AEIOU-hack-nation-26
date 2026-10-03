import type { Metadata } from "next";

import { PagePlaceholder } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "Documents" };

export default function DocumentsPage() {
  return (
    <PagePlaceholder
      eyebrow="Documents"
      title="Your reports, turned into findings you control"
      description="Upload a genetic report or a clinical letter. Personal details are removed before any AI sees it, the original file is deleted after extraction, and nothing is used until you confirm it."
      planned={[
        "Drop zone for PDF, image, DOCX or text (needs sign-in and upload consent)",
        "Progress while text is extracted, redacted and classified",
        "Your documents, with delete",
        "Findings review: each item next to the snippet it came from",
      ]}
    />
  );
}
