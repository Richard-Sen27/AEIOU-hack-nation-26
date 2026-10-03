import type { Metadata } from "next";

import { PagePlaceholder } from "@/components/shell/page-placeholder";
import { PRIVACY_EMAIL } from "@/lib/api/config";

export const metadata: Metadata = { title: "Privacy" };

export default function PrivacyPage() {
  return (
    <PagePlaceholder
      eyebrow="Privacy"
      title="Privacy notice"
      description="What Amber collects, why, how long it is kept, and how to use your rights. Nothing is sold or shared, and there are no trackers or advertising cookies."
      planned={[
        "Layered notice in plain language: data, purposes, legal basis, retention",
        "Processors and international transfers",
        "Your rights under GDPR and California law, and how to use them",
        "Global Privacy Control is honoured",
      ]}
    >
      {PRIVACY_EMAIL && (
        <p className="text-sm">
          Privacy contact:{" "}
          <a className="font-medium underline underline-offset-2" href={`mailto:${PRIVACY_EMAIL}`}>
            {PRIVACY_EMAIL}
          </a>
        </p>
      )}
    </PagePlaceholder>
  );
}
