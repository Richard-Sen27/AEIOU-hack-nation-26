import type { Metadata } from "next";

import { CallView } from "@/components/calls/call-detail";
import { PageContainer } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "Study" };

/** `/calls/<call id>`: one published survey, study or trial (signed-in readers). */
export default async function Page(props: PageProps<"/calls/[id]">) {
  const { id } = await props.params;
  return (
    <PageContainer className="max-w-5xl">
      <CallView key={id} id={id} />
    </PageContainer>
  );
}
