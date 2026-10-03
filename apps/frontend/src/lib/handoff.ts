// In-memory handoff between routes for content that must never appear in a URL or in
// browser storage (free-text health descriptions, dropped files). Lost on reload by design.

let pendingChatMessage: string | null = null;
let pendingUploads: File[] = [];

export function setPendingChatMessage(text: string) {
  pendingChatMessage = text;
}

export function takePendingChatMessage(): string | null {
  const text = pendingChatMessage;
  pendingChatMessage = null;
  return text;
}

export function setPendingUploads(files: File[]) {
  pendingUploads = files;
}

export function takePendingUploads(): File[] {
  const files = pendingUploads;
  pendingUploads = [];
  return files;
}
