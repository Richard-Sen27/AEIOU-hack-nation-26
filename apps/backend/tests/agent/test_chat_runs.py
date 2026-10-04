"""Dr. Wu turns as detached server-side runs: attach, replay, stop, one run per session,
checkpoints under row-level security, deletion, export, pruning and restart behaviour."""

import asyncio
import json
import uuid

import pytest
from agent_helpers import post_sse
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from backend.api.deps import build_lens
from backend.api.services import chat
from backend.api.services.chat import runs
from backend.api.services.chat.checkpoints import load_state
from backend.schemas.account import CurrentUser
from backend.schemas.chat import ChatRequest
from backend.schemas.enums import Role

MESSAGE = "STXBP1 encephalopathy, who works on it? Write to anna.berger@example.com"
EMAIL = "anna.berger@example.com"


def draft(summary: str = "A group serves this disease.", delay_s: float = 0.0) -> dict:
    script = {
        "kind": "tools",
        "json": {
            "summary": summary,
            "uncertainty": None,
            "claims": [],
            "contradictions": [],
            "missing_evidence": [],
            "cards": [],
            "graph_focus": None,
            "actions": [],
            "follow_up": None,
        },
    }
    if delay_s:
        script["delay_s"] = delay_s
    return script


def parse_frames(body: str) -> list[tuple[int | None, dict]]:
    frames = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        lines = block.split("\n")
        data = [line[5:].strip() for line in lines if line.startswith("data:")]
        ids = [line[3:].strip() for line in lines if line.startswith("id:")]
        if data:
            frames.append((int(ids[0]) if ids else None, json.loads("\n".join(data))))
    return frames


@pytest.fixture
async def doctor(make_user, user_llm):
    return await make_user(role="doctor", consents=["health_data"])


def current(user) -> CurrentUser:
    return CurrentUser(id=user.id, role=Role.doctor, age_confirmed=True)


async def slow_turn(user, user_llm, delay_s: float = 1.5, **request):
    """Start a turn whose final model round takes `delay_s`, without reading its stream.
    Returns (run, turn event)."""
    user_llm.enqueue(draft("Slow answer.", delay_s=delay_s))
    me = current(user)
    stream = await chat.start_turn(ChatRequest(message=MESSAGE, **request), me, build_lens(me))
    turn = None
    async for _, event in stream:
        if event.root.type == "turn":
            turn = event.root
            break
    await stream.aclose()
    return runs.get(user.id, turn.run_id), turn


async def wait_done(run, timeout: float = 10.0) -> None:
    async with asyncio.timeout(timeout):
        while not run.done:
            await asyncio.sleep(0.02)


async def wait_checkpoint(root, run_id, node_steps: int = 2) -> dict:
    for _ in range(200):
        row = await root.fetchrow(
            "SELECT checkpoint_type, checkpoint FROM chat_runs WHERE id = $1", run_id
        )
        state = load_state(row["checkpoint_type"], row["checkpoint"]) if row else None
        if state and len(state.get("steps") or []) >= node_steps:
            return {"row": row, "state": state}
        await asyncio.sleep(0.02)
    raise AssertionError("no checkpoint")


RUN_ROWS = "SELECT count(*) FROM chat_runs WHERE user_id = $1"


async def test_lifecycle_sequence_numbers_and_pruning(doctor, user_llm, connect_as):
    user_llm.enqueue(draft("Answered."))
    resp = await doctor.client.post("/chat", json={"message": MESSAGE}, timeout=60)
    frames = parse_frames(resp.text)
    assert [seq for seq, _ in frames] == list(range(1, len(frames) + 1))
    types = [e["type"] for _, e in frames]
    assert types[:2] == ["status", "turn"] and types[-1] == "final"
    turn = frames[1][1]
    assert uuid.UUID(turn["run_id"])
    # The reply is stored and the run's row (with its checkpoint) is gone.
    root = await connect_as("atlas")
    assert await root.fetchval(RUN_ROWS, doctor.id) == 0
    detail = (await doctor.client.get(f"/chat/sessions/{turn['session_id']}")).json()
    assert detail["run"] is None and detail["messages"][1]["reply"]["summary"] == "Answered."
    assert (await doctor.client.get("/chat/runs")).json() == []
    # A finished run stays attachable for a short while (a client that switched views).
    again = parse_frames(
        (await doctor.client.get(f"/chat/runs/{turn['run_id']}/events?after=0")).text
    )
    assert [e for _, e in again] == [e for _, e in frames]


async def test_attach_replays_from_a_sequence_number(doctor, user_llm):
    run, turn = await slow_turn(doctor, user_llm)
    listed = (await doctor.client.get("/chat/runs")).json()
    assert [r["id"] for r in listed] == [str(run.id)]
    assert listed[0]["session_id"] == str(turn.session_id)
    assert listed[0]["message_id"] == str(turn.message_id)
    detail = (await doctor.client.get(f"/chat/sessions/{turn.session_id}")).json()
    assert detail["run"]["id"] == str(run.id)
    assert [m["role"] for m in detail["messages"]] == ["user"]

    full = parse_frames((await doctor.client.get(f"/chat/runs/{run.id}/events")).text)
    tail = parse_frames((await doctor.client.get(f"/chat/runs/{run.id}/events?after=2")).text)
    assert full[0][1]["type"] == "status" and full[-1][1]["type"] == "final"
    assert tail == full[2:] and tail[0][0] == 3
    assert full[-1][1]["reply"]["summary"] == "Slow answer."


async def test_disconnect_does_not_cancel_and_stop_does(doctor, user_llm, connect_as):
    before = len(user_llm.state.recorded("responses"))
    run, turn = await slow_turn(doctor, user_llm, delay_s=5.0)
    for _ in range(200):  # the slow final round has started (its script is consumed)
        if len(user_llm.state.recorded("responses")) >= before + 2:
            break
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.2)
    assert not run.done  # nobody is reading, it keeps running
    assert (await doctor.client.delete(f"/chat/runs/{run.id}")).status_code == 204
    assert run.done
    root = await connect_as("atlas")
    assert await root.fetchval(RUN_ROWS, doctor.id) == 0
    detail = (await doctor.client.get(f"/chat/sessions/{turn.session_id}")).json()
    failed = detail["messages"][1]
    assert failed["error"]["code"] == "interrupted"
    assert failed["error"]["steps"][0]["message"] == "Checking your message"
    # The stopped turn can be tried again without storing the message twice.
    user_llm.enqueue(draft("Second try."))
    status, events = await post_sse(
        doctor.client,
        "/chat",
        {
            "message": "x",
            "session_id": str(turn.session_id),
            "retry_message_id": str(turn.message_id),
        },
    )
    assert status == 200 and events[-1]["reply"]["summary"] == "Second try."
    detail = (await doctor.client.get(f"/chat/sessions/{turn.session_id}")).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]


async def test_one_active_run_per_session(doctor, user_llm):
    run, turn = await slow_turn(doctor, user_llm, delay_s=3.0)
    resp = await doctor.client.post(
        "/chat", json={"message": "another", "session_id": str(turn.session_id)}
    )
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "conflict"
    detail = (await doctor.client.get(f"/chat/sessions/{turn.session_id}")).json()
    assert [m["content"] for m in detail["messages"] if m["role"] == "user"] == [
        detail["messages"][0]["content"]
    ]  # the refused message was not stored
    await runs.cancel(doctor.id, run.id)


async def test_checkpoints_hold_redacted_content_under_rls(make_user, doctor, user_llm, connect_as):
    other = await make_user(role="doctor", consents=["health_data"])
    run, _ = await slow_turn(doctor, user_llm, delay_s=3.0)
    root = await connect_as("atlas")
    found = await wait_checkpoint(root, run.id)
    state, blob = found["state"], bytes(found["row"]["checkpoint"])
    assert EMAIL not in state["message"] and EMAIL.encode() not in blob
    assert b"mock-static-test" not in blob  # no credentials
    assert b"profile" not in blob  # the profile lives in the runtime context only
    assert state["steps"][0]["message"] == "Checking your message"

    # Row-level security: the other user sees, attaches to and stops nothing.
    app = await connect_as("atlas_app")
    async with app.transaction():
        await app.execute("SELECT set_config('app.user_id', $1, true)", str(other.id))
        assert await app.fetchval("SELECT count(*) FROM chat_runs") == 0
        assert await app.execute("DELETE FROM chat_runs WHERE id = $1", run.id) == "DELETE 0"
    assert (await other.client.get("/chat/runs")).json() == []
    assert (await other.client.get(f"/chat/runs/{run.id}/events")).status_code == 404
    assert (await other.client.delete(f"/chat/runs/{run.id}")).status_code == 404
    assert not run.done
    await runs.cancel(doctor.id, run.id)


async def test_export_includes_unfinished_runs(doctor, user_llm, connect_as):
    run, _ = await slow_turn(doctor, user_llm, delay_s=3.0)
    await wait_checkpoint(await connect_as("atlas"), run.id)
    exported = (await doctor.client.get("/me/export")).json()["chat_runs"]
    assert [r["id"] for r in exported] == [str(run.id)]
    assert exported[0]["state"]["steps"][0]["message"] == "Checking your message"
    await runs.cancel(doctor.id, run.id)
    assert (await doctor.client.get("/me/export")).json()["chat_runs"] == []


async def test_session_deletion_stops_the_run(doctor, user_llm, connect_as):
    run, turn = await slow_turn(doctor, user_llm, delay_s=3.0)
    assert (await doctor.client.delete(f"/chat/sessions/{turn.session_id}")).status_code == 204
    assert run.done
    root = await connect_as("atlas")
    assert await root.fetchval(RUN_ROWS, doctor.id) == 0
    assert (
        await root.fetchval("SELECT count(*) FROM chat_messages WHERE user_id = $1", doctor.id) == 0
    )
    assert (await doctor.client.get(f"/chat/runs/{run.id}/events")).status_code == 404


async def test_consent_withdrawal_stops_and_deletes_runs(doctor, user_llm, connect_as):
    run, _ = await slow_turn(doctor, user_llm, delay_s=3.0)
    root = await connect_as("atlas")
    await wait_checkpoint(root, run.id)
    assert (await doctor.client.delete("/consents/health_data")).status_code == 204
    assert run.done
    assert await root.fetchval(RUN_ROWS, doctor.id) == 0
    assert (
        await root.fetchval("SELECT count(*) FROM chat_messages WHERE user_id = $1", doctor.id) == 0
    )
    assert (await doctor.client.get(f"/chat/runs/{run.id}/events")).status_code == 404


async def test_account_deletion_stops_and_deletes_runs(make_user, user_llm, connect_as):
    user = await make_user(role="doctor", consents=["health_data"])
    run, _ = await slow_turn(user, user_llm, delay_s=3.0)
    root = await connect_as("atlas")
    await wait_checkpoint(root, run.id)
    assert (await user.client.delete("/me")).status_code in (200, 204)
    assert run.done
    assert await root.fetchval(RUN_ROWS, user.id) == 0
    assert run.id not in runs._runs


async def test_restart_orphan_is_stored_as_interrupted_and_can_be_retried(
    doctor, user_llm, connect_as
):
    """A run left by a process that is gone (another worker id) is closed as an interrupted
    failed turn with the steps of its last checkpoint, and the existing retry works."""
    user_llm.enqueue(draft("First."))
    status, events = await post_sse(doctor.client, "/chat", {"message": MESSAGE})
    sid = next(e for e in events if e["type"] == "turn")["session_id"]
    app = await connect_as("atlas_app")
    kind, blob = JsonPlusSerializer().dumps_typed(
        {
            "v": 1,
            "id": "x",
            "channel_values": {
                "message": "redacted",
                "steps": [
                    {"tool": None, "message": "Checking your message"},
                    {"tool": "extract_entities", "message": "Reading your message"},
                ],
            },
        }
    )
    async with app.transaction():
        await app.execute("SELECT set_config('app.user_id', $1, true)", str(doctor.id))
        mid = await app.fetchval(
            "INSERT INTO chat_messages (session_id, user_id, role, content)"
            " VALUES ($1, $2, 'user', 'a later question') RETURNING id",
            uuid.UUID(sid),
            doctor.id,
        )
        await app.execute(
            "INSERT INTO chat_runs (user_id, session_id, user_message_id, worker,"
            " checkpoint_id, checkpoint_type, checkpoint) VALUES ($1, $2, $3, 'gone', 'x', $4, $5)",
            doctor.id,
            uuid.UUID(sid),
            mid,
            kind,
            blob,
        )
    assert (await doctor.client.get("/chat/runs")).json() == []
    detail = (await doctor.client.get(f"/chat/sessions/{sid}")).json()
    failed = detail["messages"][-1]
    assert failed["error"]["code"] == "interrupted"
    assert [s["message"] for s in failed["error"]["steps"]] == [
        "Checking your message",
        "Reading your message",
    ]
    root = await connect_as("atlas")
    assert await root.fetchval(RUN_ROWS, doctor.id) == 0

    user_llm.enqueue(draft("Answered after the restart."))
    status, events = await post_sse(
        doctor.client, "/chat", {"message": "x", "session_id": sid, "retry_message_id": str(mid)}
    )
    assert status == 200 and events[-1]["reply"]["summary"] == "Answered after the restart."
    detail = (await doctor.client.get(f"/chat/sessions/{sid}")).json()
    assert [m.get("error") is None for m in detail["messages"]] == [True] * 4


async def test_failed_run_is_stored_with_its_steps_and_ends_the_run(doctor, user_llm, connect_as):
    user_llm.configure(fail_mode="usage_limit")
    status, events = await post_sse(doctor.client, "/chat", {"message": MESSAGE})
    user_llm.configure(fail_mode=None)
    assert events[-1]["type"] == "error"
    sid = next(e for e in events if e["type"] == "turn")["session_id"]
    root = await connect_as("atlas")
    assert await root.fetchval(RUN_ROWS, doctor.id) == 0
    detail = (await doctor.client.get(f"/chat/sessions/{sid}")).json()
    assert detail["run"] is None and detail["messages"][1]["error"]["code"] == "rate_limited"
