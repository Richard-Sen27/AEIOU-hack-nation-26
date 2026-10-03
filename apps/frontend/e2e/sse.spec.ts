import { expect, test } from "@playwright/test";

import { parseSSE } from "../src/lib/api/sse";

function streamOf(chunks: string[]) {
  const enc = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(c) {
      chunks.forEach((s) => c.enqueue(enc.encode(s)));
      c.close();
    },
  });
}

async function collect(chunks: string[]) {
  const out = [];
  for await (const f of parseSSE(streamOf(chunks))) out.push(f);
  return out;
}

test("parseSSE handles CRLF split across chunks, comments, multi-line data", async () => {
  const frames = await collect([
    ": keep-alive\r\n\r\nevent: summary_delta\r",
    '\ndata: {"type":"summary_delta","text":"Hi"}\r\n\r\n',
    "data: line1\ndata: line2\n\n",
    'event: done\ndata: {"type":"done"}', // no trailing blank line
  ]);
  expect(frames).toEqual([
    { event: "summary_delta", data: '{"type":"summary_delta","text":"Hi"}', id: undefined },
    { event: "message", data: "line1\nline2", id: undefined },
    { event: "done", data: '{"type":"done"}', id: undefined },
  ]);
});
