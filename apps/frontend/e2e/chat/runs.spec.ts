import { expect, test, type Page } from "@playwright/test";

import { mockApi, signedInSession } from "../helpers";
import { atlasTreePayload, summaryMock } from "../graph/fixtures";
import { fullTurnEvents, graphMocks, reply, SESSION_ID, STORY } from "./fixtures";

/*
 * A Dr. Wu turn runs on the server: a reload or a switch between the Atlas dock and the full
 * chat page attaches to the same run (its events replay from the start) and never sends the
 * message again.
 */

const RUN_ID = "44444444-4444-4444-8444-444444444444";
const MESSAGE_ID = "22222222-2222-4222-8222-222222222222";
const run = { id: RUN_ID, session_id: SESSION_ID, message_id: MESSAGE_ID, created_at: "2026-10-04T08:00:00Z" };
const session = { id: SESSION_ID, title: "STXBP1", created_at: "2026-10-04T08:00:00Z", updated_at: "2026-10-04T08:00:00Z" };
const userMessage = { id: MESSAGE_ID, session_id: SESSION_ID, role: "user", content: STORY, reply: null, error: null, created_at: "2026-10-04T08:00:00Z" };
const answer = { id: "55555555-5555-4555-8555-555555555555", session_id: SESSION_ID, role: "assistant", content: reply.summary, reply, error: null, created_at: "2026-10-04T08:00:30Z" };

/** The run's events as the server replays them: SSE frames with their sequence numbers. */
function replayBody() {
  const events = [
    { type: "status", tool: null, message: "Checking your message" },
    { type: "turn", session_id: SESSION_ID, message_id: MESSAGE_ID, run_id: RUN_ID },
    ...fullTurnEvents(),
  ];
  return {
    contentType: "text/event-stream",
    body: events.map((e, i) => `id: ${i + 1}\nevent: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(""),
  };
}

/** A server whose run is in flight until its events were replayed once. */
async function server(page: Page, extra: Record<string, unknown> = {}) {
  const seen = { posts: 0, attaches: [] as string[], finished: false };
  await mockApi(page, {
    "GET /auth/session": signedInSession({ consents: ["health_data"] }),
    "GET /chat/sessions": [session],
    "GET /profile": { updated_at: "2026-10-03T00:00:00Z" },
    "GET /atlas/tree.json": atlasTreePayload(),
    "GET /atlas/summary/*": summaryMock(),
    ...graphMocks,
    // The POST starts the run; its stream never gets far here (the page goes away first).
    "POST /chat": () => {
      seen.posts += 1;
      return new Promise(() => {});
    },
    "GET /chat/runs": () => ({ json: seen.posts > 0 && !seen.finished ? [run] : [] }),
    "GET /chat/sessions/*": () => ({
      json: seen.finished
        ? { session, messages: [userMessage, answer], run: null }
        : { session, messages: [userMessage], run },
    }),
    [`GET /chat/runs/${RUN_ID}/events`]: (req: { url: string }) => {
      seen.attaches.push(new URL(req.url).searchParams.get("after") ?? "");
      seen.finished = true;
      return replayBody();
    },
    ...extra,
  });
  return seen;
}

test.describe("chat runs", () => {
  test("a reload mid-turn continues the same turn without sending the message again", async ({ page }) => {
    const seen = await server(page);
    await page.goto("/chat");
    const box = page.getByRole("textbox", { name: "Message Dr. Wu" });
    await box.fill(STORY);
    await box.press("Enter");
    await expect(page.getByTestId("assistant-turn").last()).toHaveAttribute("data-phase", "streaming");
    await expect.poll(() => seen.posts).toBe(1);

    await page.reload();
    const turn = page.getByTestId("assistant-turn").last();
    await expect(turn).toHaveAttribute("data-phase", "done");
    await expect(turn.getByTestId("summary")).toHaveText(reply.summary);
    await expect(page.getByText(STORY)).toBeVisible();
    expect(seen.posts).toBe(1);
    expect(seen.attaches).toEqual(["0"]);
  });

  test("switching from the dock to the full page mid-turn keeps the turn, and back", async ({ page }) => {
    const seen = await server(page);
    await page.goto("/atlas");
    const dock = page.getByTestId("atlas-wu-dock");
    await dock.getByTestId("atlas-wu-open").click();
    const box = dock.getByRole("textbox", { name: "Message Dr. Wu" });
    await box.fill(STORY);
    await box.press("Enter");
    await expect(dock.getByTestId("atlas-wu-turn")).toHaveAttribute("data-phase", "streaming");
    await expect.poll(() => seen.posts).toBe(1);

    await dock.getByTestId("atlas-wu-full").click();
    await expect(page).toHaveURL(/\/chat$/);
    const turn = page.getByTestId("assistant-turn").last();
    await expect(turn).toHaveAttribute("data-phase", "done");
    await expect(turn.getByTestId("summary")).toHaveText(reply.summary);
    expect(seen.posts).toBe(1);
    expect(seen.attaches).toEqual(["0"]);

    // Back on the Atlas, the dock shows the same conversation's answer.
    await page.goBack();
    await expect(page).toHaveURL(/\/atlas$/);
    await page.getByTestId("atlas-wu-open").click();
    await expect(page.getByTestId("atlas-wu-dock").getByTestId("summary")).toHaveText(reply.summary);
    expect(seen.posts).toBe(1);
  });

  test("stop cancels the run on the server", async ({ page }) => {
    const deletes: string[] = [];
    await server(page, {
      "GET /chat/runs": [],
      "POST /chat": async () => {
        await new Promise((r) => setTimeout(r, 1500));
        return replayBody();
      },
      [`DELETE /chat/runs/${RUN_ID}`]: (req: { url: string }) => {
        deletes.push(req.url);
        return { status: 204, body: "" };
      },
    });
    await page.goto("/chat");
    const box = page.getByRole("textbox", { name: "Message Dr. Wu" });
    await box.fill(STORY);
    await box.press("Enter");
    await page.getByRole("button", { name: "Stop the answer" }).click();
    const turn = page.getByTestId("assistant-turn").last();
    await expect(turn).toHaveAttribute("data-phase", "stopped");
    await expect.poll(() => deletes.length).toBe(1);
    await expect(turn).toHaveAttribute("data-phase", "stopped");
  });
});
