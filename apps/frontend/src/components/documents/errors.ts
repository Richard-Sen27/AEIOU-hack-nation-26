/** Upload limits from the system spec (Backend services → Documents). */
export const MAX_BYTES = 20 * 1024 * 1024;
export const MAX_PAGES = 30;
export const UPLOADS_PER_HOUR = 10;

export const ACCEPT =
  ".pdf,.png,.jpg,.jpeg,.heic,.heif,.docx,.txt,application/pdf,image/png,image/jpeg,image/heic,image/heif,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain";

const EXT_OK = /\.(pdf|png|jpe?g|heic|heif|docx|txt)$/i;
const MIME_OK = new Set([
  "application/pdf",
  "image/png",
  "image/jpeg",
  "image/heic",
  "image/heif",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
]);

/** Client-side pre-check; the server checks again (python-magic, page count). */
export function precheck(file: File): string | null {
  if (!EXT_OK.test(file.name) && !MIME_OK.has(file.type)) return "unsupported_media_type";
  if (file.size > MAX_BYTES) return "payload_too_large";
  if (file.size === 0) return "empty_file";
  return null;
}

/** The file name is never sent (it can contain a patient's name). */
export function anonymousName(file: File): string {
  const ext = file.name.match(/\.([a-z0-9]{2,5})$/i)?.[1]?.toLowerCase();
  return ext ? `document.${ext}` : "document";
}

/** Plain-language message per stable error code. Never echoes content. */
export function uploadErrorMessage(code: string, serverMessage?: string): string {
  // The API's messages for these codes are specific ("more than 30 pages",
  // "password-protected") and never echo content; add what to do next.
  const specific = serverMessage && !/^Request failed/.test(serverMessage) ? `${serverMessage} ` : "";
  switch (code) {
    case "payload_too_large":
      return `${specific || "This file is too large or too long. "}Documents can be up to 20 MB and ${MAX_PAGES} pages.`;
    case "unsupported_media_type":
      return `${specific || "This file type is not supported. "}Please use a PDF, a photo (PNG, JPEG, HEIC), a Word document (DOCX) or a text file.`;
    case "bad_request":
      return `${specific || "This document could not be read. "}Your original file has been deleted.`;
    case "empty_file":
      return "This file is empty.";
    case "rate_limited":
      return `You have uploaded ${UPLOADS_PER_HOUR} documents in the last hour, which is the limit. Please try again later.`;
    case "consent_required":
      return "Uploading needs your consent. Nothing was uploaded.";
    case "sign_in_required":
    case "reauth_required":
      return "Please sign in again. Nothing was uploaded.";
    case "age_confirmation_required":
      return "Please confirm your age first. Nothing was uploaded.";
    case "not_implemented":
      return "Document upload is not available yet. Nothing was uploaded.";
    case "network_error":
      return "Amber's server is not reachable. Please try again in a moment.";
    case "validation_error":
      return serverMessage || "This file could not be read. Please check it and try again.";
    case "unreadable_document":
      return "This document could not be read. Please try another copy, for example a PDF instead of a photo. Your original file has been deleted.";
    case "encrypted_document":
      return "This document is password-protected. Please upload a copy without a password. Your original file has been deleted.";
    case "no_text_found":
      return "No readable text was found in this document. A sharper photo or the original PDF may work better. Your original file has been deleted.";
    case "llm_reauth_required":
      return "Please sign in with ChatGPT again, then upload the document once more. Your original file has been deleted.";
    case "llm_usage_limit_exceeded":
      return "Your ChatGPT plan's usage limit has been reached. You can review usage and update settings for your plan in your ChatGPT settings, then try again. Your original file has been deleted.";
    case "timeout":
      return "Reading this document took too long. Please try again, or try a shorter document. Your original file has been deleted.";
    case "cancelled":
      return "Reading this document was cancelled. Your original file has been deleted.";
    case "upstream_error":
      return "A connected service did not respond. Your original file has been deleted; please try again.";
    default:
      if (code.startsWith("ocr_")) {
        return "Text recognition did not work for this image. Please try a PDF or a sharper photo. Your original file has been deleted.";
      }
      if (code.startsWith("llm_")) {
        return "The AI service did not respond as expected. Please try again in a moment. Your original file has been deleted.";
      }
      return serverMessage || "Something went wrong while reading this document. Your original file has been deleted.";
  }
}
