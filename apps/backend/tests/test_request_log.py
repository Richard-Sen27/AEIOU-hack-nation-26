"""Request log: one line per request with the route template, never a raw path, query string,
body, raw account id or address; a request id in the header and in error envelopes; unhandled
errors logged by type and location only."""

import logging
import re

import pytest

from backend.api.services import graph as graph_service
from backend.observability.logs import safe_frames, user_tag

NODE = "MONDO:0100135"  # Dravet syndrome: a health-related id that must stay out of the log
SECRET = "my daughter has seizures since march"


@pytest.fixture
def records(caplog):
    caplog.set_level(logging.DEBUG, logger="backend")

    def _all() -> list[logging.LogRecord]:
        return list(caplog.records)

    return _all


def _text(rec: logging.LogRecord) -> str:
    return " ".join(filter(None, [rec.getMessage(), rec.exc_text or "", str(rec.args or "")]))


def _request_lines(records) -> list[str]:
    return [
        r.getMessage()
        for r in records()
        if r.name == "backend.request" and r.getMessage().startswith("request ")
    ]


def _fields(line: str) -> dict[str, str]:
    return dict(re.findall(r"(\w+)=(\S+)", line))


async def test_request_line_fields_for_a_guest(client, records):
    r = await client.get(f"/node/{NODE}", params={"role": "patient", "q": SECRET})
    assert r.status_code == 200
    rid = r.headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{16}", rid)

    [line] = [ln for ln in _request_lines(records) if f"rid={rid}" in ln]
    fields = _fields(line)
    assert fields["method"] == "GET"
    assert fields["route"] == "/node/{node_id}"
    assert fields["status"] == "200"
    assert int(fields["ms"]) >= 0
    assert int(fields["bytes"]) > 0
    assert fields["client"] == "guest"
    assert "uh" not in fields

    everything = "\n".join(_text(rec) for rec in records())
    assert NODE not in everything
    assert "MONDO" not in everything
    assert "role=patient" not in everything
    assert "seizures" not in everything
    assert "127.0.0.1" not in everything  # the client address


async def test_signed_in_line_has_daily_pseudonym_not_the_id(make_user, records, monkeypatch):
    from backend.api.services import chat as chat_service

    async def fake_start_turn(body, user, lens, on_end=None):
        if on_end:
            on_end()

        async def empty():
            return
            yield

        return empty()

    monkeypatch.setattr(chat_service, "start_turn", fake_start_turn)
    user = await make_user(consents=["health_data"])
    r = await user.client.post("/chat", json={"message": SECRET})
    assert r.status_code == 200

    [line] = [ln for ln in _request_lines(records) if "route=/chat " in ln]
    fields = _fields(line)
    assert fields["client"] == "user"
    from backend.config import get_settings

    assert fields["uh"] == user_tag(user.id, get_settings().session_secret)
    assert re.fullmatch(r"[0-9a-f]{10}", fields["uh"])

    everything = "\n".join(_text(rec) for rec in records())
    assert str(user.id) not in everything
    assert user.id.hex not in everything
    assert "seizures" not in everything
    assert "daughter" not in everything


def test_daily_pseudonym_changes_per_day_and_secret():
    uid = "00000000-0000-0000-0000-000000000001"
    assert user_tag(uid, "s", "2026-10-04") == user_tag(uid, "s", "2026-10-04")
    assert user_tag(uid, "s", "2026-10-04") != user_tag(uid, "s", "2026-10-05")
    assert user_tag(uid, "s", "2026-10-04") != user_tag(uid, "t", "2026-10-04")


async def test_health_checks_are_debug_only(client, records):
    def line_for(route: str) -> logging.LogRecord:
        [rec] = [
            r
            for r in records()
            if r.name == "backend.request" and f"route={route} " in r.getMessage()
        ]
        return rec

    await client.get("/health")
    assert line_for("/health").levelno == logging.DEBUG
    await client.get("/stats")
    assert line_for("/stats").levelno == logging.INFO


async def test_unmatched_path_is_not_logged_raw(client, records):
    r = await client.get(f"/no-such-route/{NODE}")
    assert r.status_code == 404
    assert r.json()["error"]["request_id"] == r.headers["x-request-id"]
    [line] = [ln for ln in _request_lines(records) if f"rid={r.headers['x-request-id']}" in ln]
    assert "route=unmatched" in line
    assert NODE not in line and "no-such-route" not in line


async def test_error_envelopes_carry_the_request_id(client):
    r = await client.get("/profile")
    assert r.status_code == 401
    assert r.json()["error"]["request_id"] == r.headers["x-request-id"]


async def test_unhandled_error_logged_without_payload(client, records, monkeypatch):
    def boom(node_id, lens):
        raise KeyError(f"{node_id} {SECRET}")

    monkeypatch.setattr(graph_service, "node_detail", boom)
    r = await client.get(f"/node/{NODE}")
    assert r.status_code == 500
    rid = r.headers["x-request-id"]
    assert r.json() == {
        "error": {"code": "internal_error", "message": "Something went wrong.", "request_id": rid}
    }

    errors = [rec for rec in records() if rec.levelno >= logging.ERROR]
    [err] = [rec for rec in errors if "unhandled error" in rec.getMessage()]
    msg = err.getMessage()
    assert f"rid={rid}" in msg
    assert "route=/node/{node_id}" in msg
    assert "exc=KeyError" in msg
    assert "test_request_log.py" in msg and ":boom" in msg  # where it happened
    assert err.exc_info is None  # no stock traceback (it would print the message)

    everything = "\n".join(_text(rec) for rec in records())
    assert NODE not in everything
    assert "seizures" not in everything
    [line] = [ln for ln in _request_lines(records) if f"rid={rid}" in ln]
    assert "status=500" in line


def test_safe_frames_leave_out_messages():
    try:
        try:
            raise ValueError(SECRET)
        except ValueError as inner:
            raise RuntimeError(f"wrapped {NODE}") from inner
    except RuntimeError as exc:
        text = safe_frames(exc)
    assert text.startswith("RuntimeError at ")
    assert "<- ValueError at " in text
    assert SECRET not in text and NODE not in text


async def test_slowapi_never_logs_the_key(make_user, caplog):
    """slowapi's own warning names the limit key (the account id); it is silenced."""
    caplog.set_level(logging.DEBUG, logger="backend")
    user = await make_user()
    for _ in range(11):
        r = await user.client.get("/me/export")
    assert r.status_code == 429
    assert not any(str(user.id) in rec.getMessage() for rec in caplog.records)
    assert not any(rec.name == "slowapi" for rec in caplog.records)


async def test_model_error_line_names_status_and_code_only(mock_llm_error_env, records):
    """An upstream rejection logs provider, credential, model, step, status, codes, duration."""
    llm, prompt = mock_llm_error_env
    from backend.llm import LLMError

    with pytest.raises(LLMError):
        await llm.complete_text(instructions="Be brief.", input=prompt)
    [line] = [r.getMessage() for r in records() if "model call failed" in r.getMessage()]
    fields = _fields(line)
    assert fields["provider"] == "openai"
    assert fields["credential"] == "chatgpt_plan"
    assert fields["status"] == "400"
    assert fields["upstream_code"] == "unsupported_value"
    assert fields["param"] == "stream"
    assert fields["step"] == "complete_text"
    assert "ms" in fields
    everything = "\n".join(_text(rec) for rec in records())
    assert prompt not in everything
    assert "organization must be verified" not in everything


@pytest.fixture
def mock_llm_error_env():
    """An LLMClient against a fake upstream that rejects every call like an unverified
    organisation does (400 unsupported_value on `stream`)."""
    import httpx

    from backend.llm import LLMClient, StaticToken

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "Your organization must be verified to stream this model.",
                    "type": "invalid_request_error",
                    "param": "stream",
                    "code": "unsupported_value",
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    llm = LLMClient(
        StaticToken("t"),
        base_url="http://upstream.test/v1",
        http_client=client,
        model_overrides={"main": "gpt-test", "small": "gpt-test"},
    )
    return llm, "patient note: " + SECRET
