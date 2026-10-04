"""Rate limits and overload protection (backend.api.ratelimit): the general and expensive-read
limits, explanations, the daily model budget and ceiling, concurrency, the client key behind
proxies, Retry-After, and that normal browsing stays far below every limit."""

import asyncio
import logging

import httpx
import pytest
from starlette.requests import Request

from backend.api import ratelimit
from backend.api.errors import ApiError
from backend.api.routes import explain as explain_route
from backend.api.services import auth as auth_service
from backend.api.services import chat as chat_service
from backend.api.services import explanation
from backend.schemas.events import ExplainDeltaEvent, ExplainEvent

BASE_URL = "http://127.0.0.1:8000"
EDGES = ["e_3b8845b635b8", "e_0af807385728", "e_558f7d2a940d"]  # the fixture's demo path


@pytest.fixture
def settings(app, monkeypatch):
    """The app's settings, changeable per test (restored afterwards)."""
    s = app.state.settings

    def _set(**values):
        for k, v in values.items():
            monkeypatch.setattr(s, k, v)

    return _set


def _guest(app, *, xff: str | None = None, ua: str = "browser-a") -> httpx.AsyncClient:
    headers = {"User-Agent": ua}
    if xff is not None:
        headers["X-Forwarded-For"] = xff
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE_URL, headers=headers
    )


def _assert_429(r: httpx.Response, reason: str = "rate") -> int:
    assert r.status_code == 429, r.text
    retry = int(r.headers["retry-after"])
    assert retry >= 1
    err = r.json()["error"]
    assert err["code"] == "rate_limited"
    assert err["reason"] == reason
    assert err["retry_after"] == retry
    assert err["request_id"] == r.headers["x-request-id"]
    return retry


# ---- general and expensive reads -------------------------------------------------------------


async def test_general_limit_per_client(app, settings, caplog):
    caplog.set_level(logging.INFO, logger="backend")
    settings(rate_limit_general="5/minute")
    async with _guest(app) as c:
        for _ in range(5):
            assert (await c.get("/stats")).status_code == 200
        r = await c.get("/stats")
        retry = _assert_429(r)
        assert retry <= 60
        assert (await c.get("/health")).status_code == 200  # health checks are exempt
    lines = [rec.getMessage() for rec in caplog.records if "rate limited" in rec.getMessage()]
    assert lines == ["rate limited kind=guest route=/stats limit=general"]


async def test_expensive_read_limit(app, monkeypatch):
    monkeypatch.setitem(ratelimit.READ_LIMITS, ("GET", "/search"), "3/minute")
    async with _guest(app) as c:
        for q in ("dra", "drav", "dravet"):
            assert (await c.get("/search", params={"q": q})).status_code == 200
        _assert_429(await c.get("/search", params={"q": "dravet s"}))
        assert (await c.get("/stats")).status_code == 200  # other routes are unaffected


async def test_signed_in_users_are_keyed_on_the_account(app, settings, make_user):
    settings(rate_limit_general="3/minute")
    a, b = await make_user(), await make_user()
    for _ in range(3):
        assert (await a.client.get("/stats")).status_code == 200
    _assert_429(await a.client.get("/stats"))
    assert (await b.client.get("/stats")).status_code == 200


async def test_route_limit_has_retry_after(make_user):
    user = await make_user()
    for _ in range(10):
        assert (await user.client.get("/me/export")).status_code == 200
    retry = _assert_429(await user.client.get("/me/export"))
    assert retry <= 3600


# ---- client key behind proxies -----------------------------------------------------------------


def _request(headers: dict[str, str], peer: str = "10.0.0.2") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 40000),
    }
    return Request(scope)


def test_client_address_ignores_forwarded_without_trusted_hops():
    req = _request({"X-Forwarded-For": "203.0.113.9"})
    assert ratelimit.client_address(req, 0) == ("10.0.0.2", "peer")


def test_client_address_takes_the_entry_the_trusted_proxy_appended():
    req = _request({"X-Forwarded-For": "203.0.113.9"})
    assert ratelimit.client_address(req, 1) == ("203.0.113.9", "forwarded")
    # A client sending its own header only adds entries on the left.
    spoofed = _request({"X-Forwarded-For": "198.51.100.1, 203.0.113.9"})
    assert ratelimit.client_address(spoofed, 1) == ("203.0.113.9", "forwarded")
    two = _request({"X-Forwarded-For": "198.51.100.1, 203.0.113.9, 10.0.0.5"})
    assert ratelimit.client_address(two, 2) == ("203.0.113.9", "forwarded")


def test_client_address_falls_back_to_the_peer_when_the_header_is_short(caplog):
    caplog.set_level(logging.WARNING, logger="backend")
    ratelimit._warned_short_forwarded = False
    assert ratelimit.client_address(_request({}), 1) == ("10.0.0.2", "peer")
    assert any("TRUSTED_PROXY_HOPS" in r.getMessage() for r in caplog.records)


def test_guest_keys_hold_no_raw_address():
    req = _request({"X-Forwarded-For": "203.0.113.9", "User-Agent": "a"})
    from backend.config import get_settings

    s = get_settings().model_copy(update={"trusted_proxy_hops": 1})
    client = ratelimit.identify(req, s)
    assert client.kind == "guest"
    assert "203.0.113.9" not in client.key and "203.0.113.9" not in (client.network or "")
    other_browser = ratelimit.identify(
        _request({"X-Forwarded-For": "203.0.113.9", "User-Agent": "b"}), s
    )
    assert other_browser.key != client.key
    assert other_browser.network == client.network


async def test_guests_behind_the_proxy_get_their_own_key(app, settings):
    settings(rate_limit_general="3/minute", trusted_proxy_hops=1)
    async with _guest(app, xff="203.0.113.5") as a, _guest(app, xff="203.0.113.6") as b:
        for _ in range(3):
            assert (await a.get("/stats")).status_code == 200
        _assert_429(await a.get("/stats"))
        assert (await b.get("/stats")).status_code == 200
    # A spoofed entry on the left does not give the limited guest a fresh key.
    async with _guest(app, xff="198.51.100.77, 203.0.113.5") as spoof:
        _assert_429(await spoof.get("/stats"))


async def test_without_trusted_hops_a_forwarded_header_changes_nothing(app, settings):
    settings(rate_limit_general="2/minute", trusted_proxy_hops=0)
    async with _guest(app, xff="203.0.113.5") as a, _guest(app, xff="203.0.113.6") as b:
        assert (await a.get("/stats")).status_code == 200
        assert (await b.get("/stats")).status_code == 200  # same peer and User-Agent: one key
        _assert_429(await a.get("/stats"))


async def test_changing_the_user_agent_hits_the_network_limit(app, settings):
    settings(rate_limit_general="2/minute")
    ok = 0
    for i in range(ratelimit.GUEST_NETWORK_FACTOR + 1):
        async with _guest(app, ua=f"script-{i}") as c:
            for _ in range(2):
                r = await c.get("/stats")
                ok += r.status_code == 200
    assert ok == 2 * ratelimit.GUEST_NETWORK_FACTOR  # then the address as a whole is limited
    async with _guest(app, ua="script-new") as c:
        _assert_429(await c.get("/stats"))


# ---- model-calling requests --------------------------------------------------------------------


def _fake_explanations(monkeypatch) -> list[int]:
    started: list[int] = []

    async def no_cache(*args, **kwargs):
        return None

    async def fake_start(edge_ids, lens, user, *, steps=False, **scope):
        started.append(1)

        async def stream():
            yield ExplainEvent(ExplainDeltaEvent(text="Explained."))

        return stream()

    monkeypatch.setattr(explanation, "get_cached", no_cache)
    monkeypatch.setattr(explanation, "start_generation", fake_start)
    return started


def _server_key(monkeypatch, value: bool = True) -> None:
    async def uses(user_id):
        return value

    monkeypatch.setattr(auth_service, "uses_server_key", uses)


async def test_explanations_are_limited_per_account(make_user, monkeypatch):
    _fake_explanations(monkeypatch)
    _server_key(monkeypatch, False)
    monkeypatch.setattr(explain_route, "EXPLAIN_LIMIT", "2/minute")
    user = await make_user()
    for _ in range(2):
        r = await user.client.post("/explain", json={"edge_ids": EDGES})
        assert r.status_code == 200
    _assert_429(await user.client.post("/explain", json={"edge_ids": EDGES}))
    other = await make_user()
    assert (await other.client.post("/explain", json={"edge_ids": EDGES})).status_code == 200


async def test_cached_explanations_cost_nothing(client, monkeypatch):
    """Guests read cached explanations; no model limit applies to them."""
    from backend.schemas.events import ExplainFinalEvent

    async def cached(*args, **kwargs):
        return ExplainFinalEvent(
            path_id="p",
            text="Cached text.",
            citations=[],
            cached=True,
            role="guest",
            language="en",
            data_version="test",
            reading_grade=None,
        )

    monkeypatch.setattr(explanation, "get_cached", cached)
    monkeypatch.setattr(explain_route, "EXPLAIN_LIMIT", "1/minute")
    for _ in range(3):
        assert (await client.post("/explain", json={"edge_ids": EDGES})).status_code == 200
    assert ratelimit.gate.started == 0


async def test_daily_budget_for_server_key_accounts(make_user, settings, monkeypatch):
    _fake_explanations(monkeypatch)
    _server_key(monkeypatch, True)
    settings(model_daily_budget=2, model_daily_ceiling=0)
    user = await make_user()
    for _ in range(2):
        assert (await user.client.post("/explain", json={"edge_ids": EDGES})).status_code == 200
    r = await user.client.post("/explain", json={"edge_ids": EDGES})
    retry = _assert_429(r, "budget")
    assert retry <= 24 * 3600
    assert r.json()["error"]["message"] == "The AI usage limit is reached. Please try again later."
    fresh = await make_user()
    assert (await fresh.client.post("/explain", json={"edge_ids": EDGES})).status_code == 200


async def test_chatgpt_plan_accounts_are_not_charged(make_user, settings, monkeypatch):
    _fake_explanations(monkeypatch)
    _server_key(monkeypatch, False)
    settings(model_daily_budget=1, model_daily_ceiling=1)
    user = await make_user()
    for _ in range(4):
        assert (await user.client.post("/explain", json={"edge_ids": EDGES})).status_code == 200
    assert ratelimit.gate.spent_today() == 0


async def test_global_daily_ceiling(make_user, settings, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="backend")
    _fake_explanations(monkeypatch)
    _server_key(monkeypatch, True)
    settings(model_daily_budget=0, model_daily_ceiling=3)
    a, b = await make_user(), await make_user()
    for c in (a.client, a.client, b.client):
        assert (await c.post("/explain", json={"edge_ids": EDGES})).status_code == 200
    _assert_429(await b.client.post("/explain", json={"edge_ids": EDGES}), "budget")
    fresh = await make_user()
    _assert_429(await fresh.client.post("/explain", json={"edge_ids": EDGES}), "budget")
    assert sum("ceiling reached" in r.getMessage() for r in caplog.records) == 1


async def test_failed_start_refunds_the_budget(make_user, settings, monkeypatch):
    from backend.api.errors import not_found

    _server_key(monkeypatch, True)
    settings(model_daily_budget=1)

    async def no_cache(*args, **kwargs):
        return None

    async def unknown(*args, **kwargs):
        raise not_found("Unknown edge IDs.")

    monkeypatch.setattr(explanation, "get_cached", no_cache)
    monkeypatch.setattr(explanation, "start_generation", unknown)
    user = await make_user()
    for _ in range(3):
        assert (await user.client.post("/explain", json={"edge_ids": EDGES})).status_code == 404
    assert ratelimit.gate.spent_today(user.id) == 0
    assert ratelimit.gate.running() == 0


def _held_chat(monkeypatch) -> list:
    """POST /chat starts a run that keeps its slot until the test calls the stored on_end."""
    ends: list = []

    async def fake_start_turn(body, user, lens, on_end=None):
        ends.append(on_end)

        async def empty():
            return
            yield

        return empty()

    monkeypatch.setattr(chat_service, "start_turn", fake_start_turn)
    return ends


async def test_concurrent_runs_per_account(make_user, settings, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="backend")
    ends = _held_chat(monkeypatch)
    _server_key(monkeypatch, False)
    settings(model_max_concurrent_per_account=2)
    user = await make_user(consents=["health_data"])
    for _ in range(2):
        assert (await user.client.post("/chat", json={"message": "hi"})).status_code == 200
    r = await user.client.post("/chat", json={"message": "hi"})
    assert _assert_429(r, "busy") == ratelimit.BUSY_RETRY_S
    assert "still running" in r.json()["error"]["message"]
    ends[0]()  # one run ends
    assert (await user.client.post("/chat", json={"message": "hi"})).status_code == 200
    assert any("model busy scope=account route=/chat" in rec.getMessage() for rec in caplog.records)


async def test_concurrent_runs_per_process(make_user, settings, monkeypatch):
    _held_chat(monkeypatch)
    _server_key(monkeypatch, False)
    settings(model_max_concurrent=2, model_max_concurrent_per_account=5)
    users = [await make_user(consents=["health_data"]) for _ in range(3)]
    assert (await users[0].client.post("/chat", json={"message": "hi"})).status_code == 200
    assert (await users[1].client.post("/chat", json={"message": "hi"})).status_code == 200
    r = await users[2].client.post("/chat", json={"message": "hi"})
    _assert_429(r, "busy")
    assert r.json()["error"]["message"] == ratelimit.BUSY_PROCESS


async def test_parallel_requests_cannot_overshoot_the_slots(make_user, settings, monkeypatch):
    _held_chat(monkeypatch)
    _server_key(monkeypatch, False)
    settings(model_max_concurrent_per_account=2)
    user = await make_user(consents=["health_data"])
    results = await asyncio.gather(
        *(user.client.post("/chat", json={"message": "hi"}) for _ in range(6))
    )
    assert sorted(r.status_code for r in results) == [200, 200, 429, 429, 429, 429]


async def test_explanation_stream_frees_its_slot(make_user, settings, monkeypatch):
    _fake_explanations(monkeypatch)
    _server_key(monkeypatch, False)
    settings(model_max_concurrent_per_account=1)
    user = await make_user()
    for _ in range(3):  # each stream ends before the next request: never busy
        assert (await user.client.post("/explain", json={"edge_ids": EDGES})).status_code == 200
    assert ratelimit.gate.running() == 0


def test_expired_slot_frees_itself(monkeypatch):
    from uuid import uuid4

    from backend.config import get_settings

    s = get_settings().model_copy(update={"model_max_concurrent_per_account": 1})
    gate = ratelimit.ModelGate()
    uid = uuid4()
    gate.admit(uid, s, route="/chat", server_key=False)  # never released
    with pytest.raises(ApiError):
        gate.admit(uid, s, route="/chat", server_key=False)
    monkeypatch.setattr(ratelimit, "SLOT_MAX_HOLD_S", 0)
    for slot, (owner, _) in list(gate._slots.items()):
        gate._slots[slot] = (owner, 0.0)
    gate.admit(uid, s, route="/chat", server_key=False)


# ---- normal use stays far below every limit -----------------------------------------------------


async def test_normal_browsing_never_hits_a_limit(app, make_user):
    """A fast session compressed into seconds (the counters' windows are a minute or longer):
    an Atlas load, twenty node visits with summaries, ten searches typed letter by letter, a few
    paths, and a minute of polling (bell 60 s, header 60 s, message list 30 s, thread 15 s), for
    a guest and a signed-in user."""
    user = await make_user()
    async with _guest(app) as guest:
        for c in (guest, user.client):
            statuses: list[int] = []

            async def get(path, _c=c, _statuses=statuses, **params):
                r = await _c.get(path, params=params or None)
                _statuses.append(r.status_code)
                return r

            await get("/auth/session")
            await get("/atlas/tree.json")
            await get("/stats")
            hits = (await get("/search", q="epilepsy")).json()
            ids = [h["id"] for h in (hits["results"] if isinstance(hits, dict) else hits)][:5]
            assert ids
            for i in range(20):
                node = ids[i % len(ids)]
                await get(f"/atlas/summary/{node}")
                await get(f"/node/{node}")
                await get(f"/neighborhood/{node}")
                await get(f"/edge/{EDGES[i % 3]}/evidence")
            for word in ("dravet", "stxbp1", "seizure", "scn1a", "ataxia") * 2:
                for n in range(2, len(word) + 1):
                    await get("/search", q=word[:n])
            for _ in range(3):
                await get("/path", **{"from": ids[0], "to": ids[-1]})
            await get("/clusters")
            if c is user.client:
                for _ in range(2):
                    await get("/notifications/unread-count")
                    await get("/me/threads/unread-count")
                    await get("/me/threads")
                for _ in range(4):
                    await get("/me/threads/unread-count")
            assert 429 not in statuses, statuses
            assert len(statuses) > 130
