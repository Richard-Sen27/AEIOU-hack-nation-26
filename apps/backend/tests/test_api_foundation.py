import time

from backend.api.security import COOKIE_NAME, create_session_token
from backend.schemas.enums import TIER_WEIGHTS, compute_confidence, confidence_level, edge_id


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_session_guest(client):
    r = await client.get("/auth/session")
    assert r.status_code == 200
    body = r.json()
    assert body["user"] is None
    assert body["gpc"] is False
    assert body["data_version"] == "fixture"


async def test_session_signed_in(make_user):
    user = await make_user(role="researcher", consents=["health_data"])
    r = await user.client.get("/auth/session", headers={"Sec-GPC": "1"})
    assert r.status_code == 200
    body = r.json()
    assert body["gpc"] is True
    assert body["user"]["id"] == str(user.id)
    assert body["user"]["role"] == "researcher"
    assert body["user"]["age_confirmed"] is True
    assert body["user"]["consents"] == ["health_data"]


async def test_gpc_recorded_on_profile(make_user, connect_as):
    user = await make_user()
    await user.client.get("/health")
    await user.client.get("/auth/session", headers={"Sec-GPC": "1"})
    su = await connect_as("atlas")
    assert await su.fetchval("SELECT gpc_opt_out FROM profiles WHERE user_id = $1", user.id)


async def test_invalid_cookie_is_guest(client):
    client.cookies.set(COOKIE_NAME, "garbage")
    r = await client.get("/auth/session")
    assert r.json()["user"] is None


async def test_sliding_refresh(make_user, client):
    user = await make_user()
    old = create_session_token(user.id, now=time.time() - 40 * 60)
    client.cookies.set(COOKIE_NAME, old)
    r = await client.get("/auth/session")
    assert r.json()["user"]["id"] == str(user.id)
    assert COOKIE_NAME in r.headers.get("set-cookie", "")
    fresh = await user.client.get("/auth/session")
    assert "set-cookie" not in fresh.headers


async def test_require_user(client):
    r = await client.get("/profile")
    assert r.status_code == 401
    assert r.json() == {
        "error": {
            "code": "sign_in_required",
            "message": "Sign in to use this feature.",
            "request_id": r.headers["x-request-id"],
        }
    }


async def test_require_consent(make_user):
    body = {"kind": "asset", "payload": {"asset_type": "registry", "name": "x"}}
    no_consent = await make_user(consents=["health_data"])
    r = await no_consent.client.post("/contributions", json=body)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "consent_required"

    r = await no_consent.client.post("/documents", files={"file": ("a.txt", b"x", "text/plain")})
    assert r.status_code != 403

    with_consent = await make_user(consents=["contribute"])
    r = await with_consent.client.post("/contributions", json=body)
    assert r.status_code == 201


async def test_guest_upload_needs_sign_in(client):
    r = await client.post("/documents", files={"file": ("a.txt", b"x", "text/plain")})
    assert r.status_code == 401


async def test_validation_error_does_not_echo_input(make_user):
    user = await make_user(consents=["health_data"])
    secret = "my daughter has seizures"
    r = await user.client.put("/profile", json={"diseases": secret})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert secret not in r.text


async def test_update_settings(make_user):
    user = await make_user(role=None, age_confirmed=False)
    r = await user.client.patch(
        "/me/settings", json={"role": "researcher", "language": "de", "age_confirmed_16": True}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "researcher"
    assert body["language"] == "de"
    assert body["expert_mode"] is True  # default for researchers
    assert body["age_confirmed"] is True

    r = await user.client.patch("/me/settings", json={"role": "guest"})
    assert r.status_code == 422


async def test_openapi_has_event_models(client):
    spec = (await client.get("/openapi.json")).json()
    schemas = spec["components"]["schemas"]
    for name in ("ChatEvent", "ExplainEvent", "GapSearchEvent", "JobEvent", "AgentReply"):
        assert name in schemas
    chat_200 = spec["paths"]["/chat"]["post"]["responses"]["200"]["content"]
    assert chat_200["text/event-stream"]["schema"] == {"$ref": "#/components/schemas/ChatEvent"}
    assert (await client.get("/docs")).status_code == 200


def test_confidence_helpers():
    assert compute_confidence([TIER_WEIGHTS["curated_db"]], 0) == 0.9
    assert compute_confidence([0.7, 0.9], 1) == round(1 - 0.3 * 0.1 - 0.1, 6)
    assert compute_confidence([], 3) == 0.0
    assert confidence_level(0.8) == "high"
    assert confidence_level(0.5) == "medium"
    assert confidence_level(0.49) == "low"
    a, b = "MONDO:1", "MONDO:2"
    assert edge_id(a, "similar_symptoms", b) == edge_id(b, "similar_symptoms", a)
    assert edge_id(a, "serves", b) != edge_id(b, "serves", a)


async def test_sse_wire_format(client, monkeypatch):
    from backend.api.services import explanation
    from backend.schemas.events import ExplainFinalEvent

    async def cached(db, edge_ids, lens):
        return ExplainFinalEvent(
            path_id="p_x",
            text="t [e_1]",
            citations=["e_1"],
            cached=True,
            role=lens.role,
            language=lens.language,
        )

    monkeypatch.setattr(explanation, "get_cached", cached)
    r = await client.post("/explain", json={"edge_ids": ["e_1"], "role": "patient"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    lines = [line for line in r.text.splitlines() if line.startswith(("event:", "data:"))]
    assert lines[0] == "event: delta"
    assert lines[2] == "event: final"
    assert '"type":"final"' in lines[3] and '"role":"patient"' in lines[3]


async def test_explain_uncached_needs_sign_in(client, monkeypatch):
    from backend.api.services import explanation

    async def none(db, edge_ids, lens):
        return None

    monkeypatch.setattr(explanation, "get_cached", none)
    r = await client.post("/explain", json={"edge_ids": ["e_1"]})
    assert r.status_code == 401
