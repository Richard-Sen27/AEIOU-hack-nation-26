"""App middleware: gzip for large JSON (never SSE), early rejection of oversized uploads."""

import asyncio
import json

from backend.api.services.documents import MAX_UPLOAD_BYTES


def _scope(method: str, path: str, headers: dict[str, str]) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }


async def test_atlas_is_gzipped_and_keeps_etag(client):
    plain = await client.get("/atlas.json", headers={"Accept-Encoding": "identity"})
    assert plain.status_code == 200
    assert "content-encoding" not in plain.headers

    resp = await client.get("/atlas.json", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers["content-encoding"] == "gzip"
    assert "accept-encoding" in resp.headers.get("vary", "").lower()
    assert int(resp.headers["content-length"]) < len(plain.content)
    assert resp.json() == plain.json()  # httpx decodes gzip
    etag = resp.headers["etag"]
    assert etag == plain.headers["etag"]

    again = await client.get(
        "/atlas.json", headers={"Accept-Encoding": "gzip", "If-None-Match": etag}
    )
    assert again.status_code == 304
    assert again.headers["etag"] == etag
    assert again.content == b""


async def test_sse_is_not_compressed_and_streams_incrementally(app, monkeypatch):
    """An SSE response flushes each event before the next one exists, even with gzip accepted."""
    from backend.api.routes import explain as explain_route
    from backend.api.services import explanation
    from backend.schemas.events import ExplainDeltaEvent, ExplainEvent, ExplainFinalEvent

    final = ExplainFinalEvent(
        path_id="p_x", text="t", citations=[], cached=True, role="patient", language="en"
    )

    async def cached(db, edge_ids, lens):
        return final

    gate = asyncio.Event()

    async def gated(_cached):
        yield ExplainEvent(ExplainDeltaEvent(text="first"))
        await gate.wait()
        yield ExplainEvent(final)

    monkeypatch.setattr(explanation, "get_cached", cached)
    monkeypatch.setattr(explain_route, "_replay", gated)

    body = json.dumps({"edge_ids": ["e_1"], "role": "patient"}).encode()
    scope = _scope(
        "POST",
        "/explain",
        {
            "host": "127.0.0.1:8000",
            "content-type": "application/json",
            "content-length": str(len(body)),
            "accept-encoding": "gzip",
        },
    )
    sent: list[dict] = []
    first_seen = asyncio.Event()
    done = asyncio.Event()
    body_delivered = False

    async def receive():
        nonlocal body_delivered
        if not body_delivered:
            body_delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        await done.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)
        if message["type"] == "http.response.body" and b"first" in message.get("body", b""):
            first_seen.set()

    task = asyncio.create_task(app(scope, receive, send))
    try:
        await asyncio.wait_for(first_seen.wait(), timeout=10)
        assert not gate.is_set()  # the first event left before the second was produced
        gate.set()
        await asyncio.wait_for(task, timeout=10)
    finally:
        done.set()
        if not task.done():
            task.cancel()

    start = next(m for m in sent if m["type"] == "http.response.start")
    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    assert start["status"] == 200
    assert headers["content-type"].startswith("text/event-stream")
    assert "content-encoding" not in headers
    stream = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert b"event: delta" in stream and b"event: final" in stream


async def _call(app, scope: dict) -> tuple[list[dict], bool]:
    sent: list[dict] = []
    read = False

    async def receive():
        nonlocal read
        read = True
        return {"type": "http.request", "body": b"x", "more_body": False}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    return sent, read


async def test_oversized_upload_rejected_before_body(app, make_user):
    user = await make_user(consents=["upload"])
    cookie = "; ".join(f"{k}={v}" for k, v in user.cookies.items())
    scope = _scope(
        "POST",
        "/documents",
        {
            "host": "127.0.0.1:8000",
            "origin": app.state.settings.frontend_url.rstrip("/"),
            "cookie": cookie,
            "content-type": "multipart/form-data; boundary=x",
            "content-length": str(MAX_UPLOAD_BYTES * 2),
        },
    )
    sent, read = await _call(app, scope)
    assert read is False  # the body was never read
    start = sent[0]
    assert start["status"] == 413
    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    assert headers["content-type"] == "application/json"
    assert "access-control-allow-origin" in headers  # CORS still wraps the rejection
    payload = json.loads(b"".join(m.get("body", b"") for m in sent[1:]))
    assert payload["error"]["code"] == "payload_too_large"


async def test_upload_within_limit_reaches_route(client, make_user):
    user = await make_user(consents=["upload"])
    r = await user.client.post(
        "/documents",
        files={"file": ("a.bin", b"\x00\x01", "application/octet-stream")},
    )
    assert r.status_code != 413
