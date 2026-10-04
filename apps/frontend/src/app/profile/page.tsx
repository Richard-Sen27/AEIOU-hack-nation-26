import type { Metadata } from "next";

import { ProfilePage } from "@/components/account/profile-page";
import { PageContainer, PageHeader } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "Profile" };

export default function Page() {
  return (
    <PageContainer className="max-w-6xl">
      <PageHeader
        eyebrow="Profile and privacy"
        title="Your profile"
        description="Your health profile, settings, consents and data."
      />
      <div className="mt-8">
        <ProfilePage />
      </div>
    </PageContainer>
  );
}
