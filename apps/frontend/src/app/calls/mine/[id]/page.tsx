import type { Metadata } from "next";

import { CallForm } from "@/components/calls/call-form";
import { PageContainer, PageHeader } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "Edit call" };

export default async function Page(props: PageProps<"/calls/mine/[id]">) {
  const { id } = await props.params;
  return (
    <PageContainer className="max-w-3xl">
      <PageHeader eyebrow="My calls" title="Edit call" />
      <div className="mt-6">
        <CallForm key={id} callId={id} />
      </div>
    </PageContainer>
  );
}
