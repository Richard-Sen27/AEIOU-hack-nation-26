import type { Metadata } from "next";

import { WelcomeFlow } from "@/components/account/welcome-flow";
import { PageContainer, PageHeader } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "Welcome" };

export default async function WelcomePage(props: PageProps<"/welcome">) {
  const { next } = await props.searchParams;
  return (
    <PageContainer className="max-w-3xl">
      <PageHeader
        eyebrow="Welcome"
        title="Welcome to Amber"
        description="Two quick choices and you are ready. Nothing here is shared, and you can change it later in your profile."
      />
      <div className="mt-8">
        <WelcomeFlow next={typeof next === "string" ? next : undefined} />
      </div>
    </PageContainer>
  );
}
