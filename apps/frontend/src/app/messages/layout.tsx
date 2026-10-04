import type { Metadata } from "next";

import { MessagesShell } from "@/components/messages/messages-shell";

// A fixed title: never a name or anything from a conversation.
export const metadata: Metadata = { title: "Messages", robots: { index: false, follow: false } };

export default function MessagesLayout({ children }: LayoutProps<"/messages">) {
  return <MessagesShell>{children}</MessagesShell>;
}
