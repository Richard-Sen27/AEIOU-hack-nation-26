"""A turn that ends in an error is stored, shown again with its session, and retried in place."""

import asyncio

import pytest
from agent_helpers import post_sse

from backend.api.deps import build_lens
from backend.api.services import chat
from backend.schemas.account import CurrentUser
from backend.schemas.chat import ChatRequest
from backend.schemas.enums import Role

MESSAGE = "STXBP1 encephalopathy, who works on it?"
LIMIT = "Your ChatGPT plan's usage limit is reached. Please try again later."


def draft(summary: str = "A group serves this disease.") -> dict:
    return {
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


@pytest.fixture
async def doctor(make_user, user_llm):
    return await make_user(role="doctor", consents=["health_data"])


async def failed_turn(user, user_llm, **extra) -> list[dict]:
    user_llm.configure(fail_mode="usage_limit")
    status, events = await post_sse(user.client, "/chat", {"message": MESSAGE, **extra})
    user_llm.configure(fail_mode=None)
    assert status == 200 and events[-1]["type"] == "error", events
    return events


def turn_event(events: list[dict]) -> dict:
    return next(e for e in events if e["type"] == "turn")


async def test_failed_turn_is_stored_and_returned(doctor, user_llm):
    events = await failed_turn(doctor, user_llm)
    assert events[-1] == {"type": "error", "code": "rate_limited", "message": LIMIT}
    started = turn_event(events)
    detail = (await doctor.client.get(f"/chat/sessions/{started['session_id']}")).json()
    user_msg, failed = detail["messages"]
    assert user_msg["id"] == started["message_id"] and user_msg["role"] == "user"
    assert failed["role"] == "assistant" and failed["reply"] is None
    steps = [
        {"tool": e.get("tool"), "message": e["message"]} for e in events if e["type"] == "status"
    ]
    assert failed["error"] == {"code": "rate_limited", "message": LIMIT, "steps": steps}
    assert [s["message"] for s in steps][:2] == ["Checking your message", "Reading your message"]
    # Only the live turn's error and steps are stored: no message text, no tool output.
    assert failed["content"] == LIMIT
    assert "STXBP1" not in str(failed["error"])
    sessions = (await doctor.client.get("/chat/sessions")).json()
    assert [s["id"] for s in sessions] == [started["session_id"]]


async def test_failed_turn_is_left_out_of_the_next_turns_history(doctor, user_llm, llm_calls):
    sid = turn_event(await failed_turn(doctor, user_llm))["session_id"]
    user_llm.enqueue(draft())
    status, events = await post_sse(
        doctor.client, "/chat", {"message": "And the registry?", "session_id": sid}
    )
    assert events[-1]["type"] == "final"
    main = [b for b in llm_calls() if b.get("tools")][-1]
    roles = [i.get("role") for i in main["input"] if i.get("role") in ("user", "assistant")]
    assert roles == ["user", "user"]  # the failed turn adds no assistant text
    assert LIMIT not in str(main["input"])


async def test_retry_replaces_the_failed_turn_without_a_second_user_message(doctor, user_llm):
    started = turn_event(await failed_turn(doctor, user_llm))
    user_llm.enqueue(draft("Second try worked."))
    status, events = await post_sse(
        doctor.client,
        "/chat",
        {
            "message": "ignored on a retry",
            "session_id": started["session_id"],
            "retry_message_id": started["message_id"],
        },
    )
    assert status == 200 and events[-1]["type"] == "final", events
    again = turn_event(events)
    assert again["run_id"] != started["run_id"]
    assert again | {"run_id": None} == started | {"type": "turn", "run_id": None}
    detail = (await doctor.client.get(f"/chat/sessions/{started['session_id']}")).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][0]["content"] == MESSAGE
    assert detail["messages"][1]["reply"]["summary"] == "Second try worked."
    assert detail["messages"][1]["error"] is None


async def test_retry_that_fails_again_keeps_one_failed_turn(doctor, user_llm):
    started = turn_event(await failed_turn(doctor, user_llm))
    retry = {"session_id": started["session_id"], "retry_message_id": started["message_id"]}
    await failed_turn(doctor, user_llm, **retry)
    detail = (await doctor.client.get(f"/chat/sessions/{started['session_id']}")).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["error"]["code"] == "rate_limited"


async def test_retry_is_refused_for_answered_unknown_or_foreign_messages(
    doctor, make_user, user_llm
):
    user_llm.enqueue(draft())
    status, events = await post_sse(doctor.client, "/chat", {"message": MESSAGE})
    started = turn_event(events)
    body = {
        "message": "x",
        "session_id": started["session_id"],
        "retry_message_id": started["message_id"],
    }
    resp = await doctor.client.post("/chat", json=body)
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "conflict"
    resp = await doctor.client.post(
        "/chat", json={**body, "retry_message_id": events[-1]["message_id"]}
    )
    assert resp.status_code == 404
    resp = await doctor.client.post(
        "/chat", json={"message": "x", "retry_message_id": started["message_id"]}
    )
    assert resp.status_code == 422
    other = await make_user(role="doctor", consents=["health_data"])
    assert (await other.client.post("/chat", json=body)).status_code == 404


async def test_deadline_without_findings_is_stored_as_failed(doctor, user_llm, monkeypatch):
    from backend.api.services.chat import agent

    monkeypatch.setattr(agent, "TURN_DEADLINE_S", 0.3)
    user_llm.configure(stream_delay_s=0.2)
    status, events = await post_sse(doctor.client, "/chat", {"message": MESSAGE})
    assert events[-1]["type"] == "error" and "too long" in events[-1]["message"]
    sid = turn_event(events)["session_id"]
    detail = (await doctor.client.get(f"/chat/sessions/{sid}")).json()
    assert detail["messages"][1]["error"]["code"] == "upstream_error"
    assert "too long" in detail["messages"][1]["error"]["message"]


async def test_cut_stream_does_not_stop_the_turn(doctor, user_llm):
    """The client going away mid-turn ends only its stream: the run answers and stores it."""
    user_llm.enqueue(draft("Answered without a client."))
    user = CurrentUser(id=doctor.id, role=Role.doctor, age_confirmed=True)
    stream = await chat.start_turn(ChatRequest(message=MESSAGE), user, build_lens(user))
    seen = []
    async for _, event in stream:
        seen.append(event.root)
        if event.root.type == "turn":
            break
    await stream.aclose()  # the client went away mid-turn
    sid = next(e for e in seen if e.type == "turn").session_id
    for _ in range(100):
        detail = (await doctor.client.get(f"/chat/sessions/{sid}")).json()
        if len(detail["messages"]) == 2:
            break
        await asyncio.sleep(0.05)
    assert detail["messages"][1]["reply"]["summary"] == "Answered without a client."
    assert detail["run"] is None


async def test_export_and_deletion_cover_failed_turns(doctor, user_llm, connect_as):
    sid = turn_event(await failed_turn(doctor, user_llm))["session_id"]
    data = (await doctor.client.get("/me/export")).json()
    messages = next(s for s in data["chat_sessions"] if s["session"]["id"] == sid)["messages"]
    assert messages[1]["error"]["code"] == "rate_limited" and messages[1]["error"]["steps"]

    root = await connect_as("atlas")
    count = "SELECT count(*) FROM chat_messages WHERE user_id = $1"
    assert await root.fetchval(count, doctor.id) == 2
    assert (await doctor.client.delete("/consents/health_data")).status_code == 204
    assert await root.fetchval(count, doctor.id) == 0


async def test_account_deletion_removes_failed_turns(make_user, user_llm, connect_as):
    user = await make_user(role="doctor", consents=["health_data"])
    await failed_turn(user, user_llm)
    root = await connect_as("atlas")
    count = "SELECT count(*) FROM chat_messages WHERE user_id = $1"
    assert await root.fetchval(count, user.id) == 2
    assert (await user.client.delete("/me")).status_code in (200, 204)
    assert await root.fetchval(count, user.id) == 0
