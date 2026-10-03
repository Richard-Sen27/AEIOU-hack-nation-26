import type { Metadata } from "next";

import { DocumentsPage } from "@/components/documents/documents-page";
import { PageContainer, PageHeader } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "Documents" };

export default function Page() {
  return (
    <PageContainer className="max-w-6xl">
      <PageHeader
        eyebrow="Documents"
        title="Your reports, turned into findings you control"
        description="Upload a genetic report or a clinical letter. Personal details are removed before any AI sees it, the original file is deleted after extraction, and nothing is used until you confirm it."
      />
      <div className="mt-8">
        <DocumentsPage />
      </div>
    </PageContainer>
  );
}
