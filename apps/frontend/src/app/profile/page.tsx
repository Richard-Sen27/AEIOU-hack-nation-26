import type { Metadata } from "next";

import { PagePlaceholder } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "Profile" };

export default function ProfilePage() {
  return (
    <PagePlaceholder
      eyebrow="Profile"
      title="Your profile"
      description="What Amber uses to find connections for you. Every field is editable, and only things you confirmed are here."
      planned={[
        "Role, language and expert mode",
        "Confirmed diagnoses, genes, variants and symptoms (GET/PUT /profile)",
        "Consents for upload and contribute, each withdrawable in one step",
        "Export all your data, or delete your account",
      ]}
    />
  );
}
