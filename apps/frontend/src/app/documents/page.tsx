import type { Metadata } from "next";

import { DocumentsPage } from "@/components/documents/documents-page";
import { PageContainer, PageHeader } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "Documents" };

export default function Page() {
  return (
    <PageContainer className="max-w-6xl">
      <PageHeader
        eyebrow="Documents"
        title="Your reports, turned into findings"
        description="A genetic report or clinical letter. Nothing is used until you confirm it."
      />
      <div className="mt-8">
        <DocumentsPage />
      </div>
    </PageContainer>
  );
}
