import type { Metadata } from "next";

import { MyCalls } from "@/components/calls/my-calls";
import { PageContainer, PageHeader } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "My calls" };

export default function Page() {
  return (
    <PageContainer className="max-w-4xl">
      <PageHeader eyebrow="Studies" title="My calls" description="Surveys, studies and trials you publish." />
      <div className="mt-8">
        <MyCalls />
      </div>
    </PageContainer>
  );
}
