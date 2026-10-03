import type { Metadata } from "next";
import Link from "next/link";

import { FindingsReview } from "@/components/documents/findings-review";
import { PageContainer, PageHeader } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "Review findings" };

export default async function DocumentPage(props: PageProps<"/documents/[id]">) {
  const { id } = await props.params;
  return (
    <PageContainer className="max-w-5xl">
      <nav aria-label="Breadcrumb" className="mb-4 text-sm text-muted-foreground">
        <Link href="/documents" className="hover:text-foreground hover:underline underline-offset-2">
          Documents
        </Link>{" "}
        / Review
      </nav>
      <PageHeader
        eyebrow="Findings review"
        title="Review what was found"
        description="Confirm or reject each finding. Only confirmed findings go into your profile."
      />
      <div className="mt-8">
        <FindingsReview documentId={id} />
      </div>
    </PageContainer>
  );
}
