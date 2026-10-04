import type { Metadata } from "next";

import { CallForm } from "@/components/calls/call-form";
import { PageContainer, PageHeader } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "New call" };

export default function Page() {
  return (
    <PageContainer className="max-w-3xl">
      <PageHeader eyebrow="My calls" title="New call" description="Looking for participants for a survey, study or trial." />
      <div className="mt-6">
        <CallForm callId={null} />
      </div>
    </PageContainer>
  );
}
