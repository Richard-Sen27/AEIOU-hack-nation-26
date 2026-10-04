import { buildUrl, type ApiFetchOptions } from "./fetch";
import {
  ApiError,
  errorFromResponse,
  networkError,
  reportApiError,
} from "./errors";

/** A raw SSE frame. */
export type SSEFrame = { event: string; data: string; id?: string };

/** The API's SSE payloads are JSON objects discriminated by `type`. */
export type SSEEvent = { type: string } & Record<string, unknown>;

export type StreamSSEOptions<E extends SSEEvent> = {
  method?: "GET" | "POST";
  /** JSON body for POST. Health data goes here, never in `query`. */
  json?: unknown;
  query?: ApiFetchOptions["query"];
  signal?: AbortSignal;
  /** Called for every parsed event, in order, with the frame's SSE `id` (if any). */
  onEvent: (event: E, id?: string) => void;
  /** Called once the response is accepted (2xx) and streaming starts. */
  onOpen?: () => void;
  /** Do not route errors to the global dialogs / toast. */
  quiet?: boolean;
};

/**
 * Parse an SSE byte stream into frames (spec subset: `event:`, `data:`, `id:`,
 * comments, multi-line data, CRLF). Exported for tests.
 */
export async function* parseSSE(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SSEFrame> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let event = "message";
  let data: string[] = [];
  let id: string | undefined;

  const flush = (): SSEFrame | null => {
    if (data.length === 0) {
      event = "message";
      return null;
    }
    const frame = { event, data: data.join("\n"), id };
    event = "message";
    data = [];
    return frame;
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        buffer += decoder.decode();
        if (buffer && !/[\r\n]$/.test(buffer)) buffer += "\n";
      } else {
        buffer += decoder.decode(value, { stream: true });
      }
      let nl: number;
      while ((nl = buffer.search(/\r\n|\r|\n/)) >= 0) {
        // A trailing "\r" may be the first half of a "\r\n" split across chunks.
        if (!done && nl === buffer.length - 1 && buffer[nl] === "\r") break;
        const line = buffer.slice(0, nl);
        const sepLen = buffer.startsWith("\r\n", nl) ? 2 : 1;
        buffer = buffer.slice(nl + sepLen);
        if (line === "") {
          const frame = flush();
          if (frame) yield frame;
          continue;
        }
        if (line.startsWith(":")) continue;
        const colon = line.indexOf(":");
        const field = colon === -1 ? line : line.slice(0, colon);
        let val = colon === -1 ? "" : line.slice(colon + 1);
        if (val.startsWith(" ")) val = val.slice(1);
        if (field === "event") event = val;
        else if (field === "data") data.push(val);
        else if (field === "id") id = val;
      }
      if (done) break;
    }
    const frame = flush();
    if (frame) yield frame;
  } finally {
    reader.releaseLock();
  }
}

/**
 * Server-sent events over `fetch` (works for POST, sends the session cookie,
 * abortable). Resolves when the stream ends; rejects with `ApiError`.
 * An abort resolves quietly (code `aborted` is never reported).
 *
 * ```ts
 * const ctrl = new AbortController();
 * await streamSSE<ChatEvent>("/chat", {
 *   json: { message },
 *   signal: ctrl.signal,
 *   onEvent: (e) => { if (e.type === "summary_delta") ... },
 * });
 * ```
 *
 * If a frame's data is JSON without a `type`, the SSE `event:` name is used
 * as `type`. Non-JSON data arrives as `{ type: event, data: "<text>" }`.
 */
export async function streamSSE<E extends SSEEvent = SSEEvent>(
  path: string,
  {
    method = "POST",
    json,
    query,
    signal,
    onEvent,
    onOpen,
    quiet,
  }: StreamSSEOptions<E>,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(buildUrl(path, query), {
      method,
      credentials: "include",
      signal,
      headers: {
        Accept: "text/event-stream",
        ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: method === "POST" && json !== undefined ? JSON.stringify(json) : undefined,
      cache: "no-store",
    });
  } catch (cause) {
    const err = networkError(cause);
    if (err.isAbort) return;
    if (!quiet) reportApiError(err);
    throw err;
  }

  if (!res.ok || !res.body) {
    const err = res.ok
      ? new ApiError("network_error", "Empty response stream", res.status)
      : await errorFromResponse(res);
    if (!quiet) reportApiError(err);
    throw err;
  }

  onOpen?.();

  try {
    for await (const frame of parseSSE(res.body)) {
      let payload: SSEEvent;
      try {
        const parsed: unknown = JSON.parse(frame.data);
        payload =
          parsed && typeof parsed === "object" && !Array.isArray(parsed)
            ? ({ type: frame.event, ...(parsed as object) } as SSEEvent)
            : { type: frame.event, data: parsed };
      } catch {
        payload = { type: frame.event, data: frame.data };
      }
      onEvent(payload as E, frame.id);
    }
  } catch (cause) {
    const err = networkError(cause);
    if (err.isAbort) return;
    if (!quiet) reportApiError(err);
    throw err;
  }
}
