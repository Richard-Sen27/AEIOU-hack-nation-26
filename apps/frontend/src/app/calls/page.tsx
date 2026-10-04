import type { Metadata } from "next";

import { CallsBrowser } from "@/components/calls/calls-browser";
import { MyCallsLink } from "@/components/calls/my-calls-link";
import { SuggestedCalls } from "@/components/calls/suggested-calls";
import { PageContainer, PageHeader } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "Studies" };

export default function Page() {
  return (
    <PageContainer className="max-w-4xl">
      <PageHeader
        eyebrow="Studies"
        title="Find trials and studies looking for participants"
        description="Surveys, studies and trials from verified researchers and doctors."
      >
        <MyCallsLink />
      </PageHeader>
      <div className="mt-8 space-y-8">
        <SuggestedCalls />
        <CallsBrowser />
      </div>
    </PageContainer>
  );
}
