import type { Metadata } from "next";

import { MySignups } from "@/components/calls/my-signups";
import { PageContainer, PageHeader } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "My sign-ups" };

export default function Page() {
  return (
    <PageContainer className="max-w-4xl">
      <PageHeader eyebrow="Studies" title="My sign-ups" description="What you sent, to whom. Withdraw any time." />
      <div className="mt-8">
        <MySignups />
      </div>
    </PageContainer>
  );
}
