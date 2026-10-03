import type { Metadata } from "next";

import { PagePlaceholder } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "Welcome" };

export default function WelcomePage() {
  return (
    <PagePlaceholder
      eyebrow="Welcome"
      title="How would you like to use Amber?"
      description="Pick the view that fits you. It changes where you start and how things are explained, never what you can see. You can switch at any time."
      planned={[
        "Role choice: patient or family, doctor, researcher",
        "Confirmation that Dr. Wu uses your ChatGPT plan, shown once",
        "Return to where you were before signing in",
      ]}
    />
  );
}
