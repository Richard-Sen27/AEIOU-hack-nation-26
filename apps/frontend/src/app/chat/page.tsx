import type { Metadata } from "next";

import { ChatPage } from "@/components/chat/chat-page";

export const metadata: Metadata = { title: "Ask Dr. Wu" };

export default function Page() {
  return <ChatPage />;
}
