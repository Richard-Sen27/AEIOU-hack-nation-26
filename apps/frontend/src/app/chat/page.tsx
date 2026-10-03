import type { Metadata } from "next";

import { AiDisclosure } from "@/components/shell/ai-disclosure";
import { PagePlaceholder } from "@/components/shell/page-placeholder";

export const metadata: Metadata = { title: "Ask Dr. Wu" };

export default function ChatPage() {
  return (
    <PagePlaceholder
      eyebrow="Ask Dr. Wu"
      title="Describe it in your own words"
      description="Dr. Wu turns a diagnosis, a gene or symptoms into cited connections in the atlas. It runs on your own ChatGPT plan, so it needs you to sign in."
      planned={[
        "Chat over SSE (POST /chat) with chips you confirm, correct or remove",
        "At most one skippable follow-up question at a time",
        "Answers as cards: mini graph, patient groups, evidence, Open in Atlas",
        "Drop a report into the chat to extract findings",
      ]}
    >
      <AiDisclosure />
    </PagePlaceholder>
  );
}
