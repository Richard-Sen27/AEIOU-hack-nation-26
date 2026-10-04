"""Verification (ORCID mock, manual review), the opt-in public card and card lookups."""

from urllib.parse import parse_qs, urlsplit

import pytest
from account_helpers import assert_error
from pydantic import ValidationError

from backend.api.ratelimit import limiter
from backend.api.services import people as people_service
from backend.api.services.graph import get_graph
from backend.config import Settings, get_settings

OTHER_ORCID = "0000-0002-1694-233X"  # never confirmed in these tests
PERSON = "RES:fx-alpha"
WORK = {"first_name": "Ada", "last_name": "Lovelace", "institutions": [{"label": "Uni Test"}]}
CARD_KEYS = {
    "card_id",
    "role",
    "role_self_declared",
    "name",
    "name_source",
    "institutions",
    "orcid_id",
    "orcid_url",
    "atlas_node_id",
    "atlas_node_label",
    "headline",
    "accepts_patient_messages",
    "verification",
}


@pytest.fixture
def orcid_mock(monkeypatch):
    monkeypatch.setenv("ORCID_MOCK", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("ORCID_MOCK")
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fresh_limits():
    limiter.reset()
    yield
    limiter.reset()


def _new_orcid() -> str:
    """A random ORCID iD with a valid check digit (the confirmed iD is unique per account)."""
    import random

    base = f"{random.randrange(10**15):015d}"
    total = 0
    for ch in base:
        total = (total + int(ch)) * 2
    check = (12 - total % 11) % 11
    digits = base + ("X" if check == 10 else str(check))
    return "-".join(digits[i : i + 4] for i in range(0, 16, 4))


def _path(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}"


async def _orcid_flow(user, orcid: str | None = None, name: str = "Ada Lovelace"):
    """Run the simulated sign-in up to the callback URL (not yet called)."""
    r = await user.client.post("/me/professional/orcid/start", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["simulated"] is True
    page = await user.client.get(_path(body["authorize_url"]))
    assert page.status_code == 200 and "verification simulated" in page.text
    q = parse_qs(urlsplit(body["authorize_url"]).query)
    r = await user.client.get(
        "/_mock/orcid/oauth/decide",
        params={
            "redirect_uri": q["redirect_uri"][0],
            "state": q["state"][0],
            "orcid": orcid or _new_orcid(),
            "name": name,
            "decision": "allow",
        },
    )
    assert r.status_code == 302
    return _path(r.headers["location"])


def _result(r) -> str:
    assert r.status_code == 302, r.text
    return parse_qs(urlsplit(r.headers["location"]).query)["orcid"][0]


async def _verified_researcher(make_user, orcid=None, link: str | None = None, superuser=None):
    user = await make_user(role="researcher")
    assert (await user.client.put("/me/professional", json=WORK)).status_code == 200
    callback = await _orcid_flow(user, orcid)
    assert _result(await user.client.get(callback)) == "confirmed"
    if link is not None:
        await superuser.execute(
            "UPDATE profiles SET atlas_node_id = $2, atlas_link_verified = true WHERE user_id = $1",
            user.id,
            link,
        )
    return user


async def _show(user, **extra):
    r = await user.client.put("/me/professional/card", json={"visible": True, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _disease_of(node_id: str) -> str:
    diseases = people_service._person_diseases(get_graph(), node_id)
    assert diseases, "fixture researcher has no linked disease"
    return sorted(diseases)[0]


# ---- access ------------------------------------------------------------------------------


async def test_guest(client):
    assert_error(await client.get("/me/professional/card"), 401, "sign_in_required")
    assert_error(await client.put("/me/professional/card", json={}), 401, "sign_in_required")
    assert_error(
        await client.post("/me/professional/orcid/start", json={}), 401, "sign_in_required"
    )
    assert_error(
        await client.get("/people", params={"disease": "MONDO:0100135"}), 401, "sign_in_required"
    )
    assert_error(
        await client.get("/people/00000000-0000-0000-0000-000000000000"), 401, "sign_in_required"
    )


async def test_patient_cannot_verify_or_show(make_user, orcid_mock):
    patient = await make_user(role="patient")
    assert_error(
        await patient.client.post("/me/professional/orcid/start", json={}), 403, "forbidden"
    )
    r = await patient.client.post(
        "/me/professional/verification-request",
        json={"institutional_email": "a@uni.test", "profile_url": "https://uni.test/a"},
    )
    assert_error(r, 403, "forbidden")
    assert_error(
        await patient.client.put("/me/professional/card", json={"visible": True}), 403, "forbidden"
    )
    me = (await patient.client.get("/me/professional/card")).json()
    assert me["can_show"] is False and me["blocked_reason"] == "role" and me["preview"] is None


# ---- ORCID with the mock -------------------------------------------------------------------


async def test_orcid_mock_confirms_and_labels_simulated(make_user, orcid_mock, superuser):
    user = await make_user(role="researcher")
    await user.client.put("/me/professional", json=WORK)
    orcid = _new_orcid()
    callback = await _orcid_flow(user, orcid)
    r = await user.client.get(callback)
    assert _result(r) == "confirmed"
    assert r.headers["location"].startswith("http://127.0.0.1:3100/profile?")
    me = (await user.client.get("/me/professional/card")).json()
    v = me["verification"]
    assert v["verified"] and v["method"] == "orcid_simulated" and v["simulated"]
    assert "verification simulated" in v["label"].lower() and v["orcid_id_confirmed"]
    row = await superuser.fetchrow(
        "SELECT role_verified, orcid_id, verified_name FROM profiles WHERE user_id = $1", user.id
    )
    assert row["role_verified"] and row["orcid_id"] == orcid
    assert row["verified_name"] == "Ada Lovelace"
    # The confirmed iD is locked.
    r = await user.client.put("/me/professional", json={**WORK, "orcid_id": OTHER_ORCID})
    assert_error(r, 422, "validation_error")
    r = await user.client.put("/me/professional", json={**WORK, "orcid_id": orcid})
    assert r.status_code == 200


async def test_orcid_replay_and_wrong_user_fail(make_user, orcid_mock):
    alice = await make_user(role="researcher")
    mallory = await make_user(role="researcher")
    callback = await _orcid_flow(alice)
    assert _result(await mallory.client.get(callback)) == "failed"  # bound to alice
    assert _result(await alice.client.get(callback)) == "confirmed"
    assert _result(await alice.client.get(callback)) == "failed"  # replay
    mine = (await mallory.client.get("/me/professional/card")).json()
    assert mine["verification"]["verified"] is False


async def test_orcid_bad_state_deny_and_signed_out(make_user, client, orcid_mock):
    user = await make_user(role="doctor")
    r = await user.client.get("/me/professional/orcid/callback", params={"state": "x", "code": "y"})
    assert _result(r) == "failed"
    start = (await user.client.post("/me/professional/orcid/start", json={})).json()
    q = parse_qs(urlsplit(start["authorize_url"]).query)
    r = await user.client.get(
        "/_mock/orcid/oauth/decide",
        params={"redirect_uri": q["redirect_uri"][0], "state": q["state"][0], "decision": "deny"},
    )
    assert _result(await user.client.get(_path(r.headers["location"]))) == "denied"
    assert _result(await client.get(_path(r.headers["location"]))) == "failed"  # signed out
    # A forged code with a fresh valid state fails too.
    start = (await user.client.post("/me/professional/orcid/start", json={})).json()
    state = parse_qs(urlsplit(start["authorize_url"]).query)["state"][0]
    r = await user.client.get(
        "/me/professional/orcid/callback", params={"state": state, "code": "forged"}
    )
    assert _result(r) == "failed"


async def test_orcid_confirmed_on_one_account_only(make_user, orcid_mock):
    orcid = _new_orcid()
    await _verified_researcher(make_user, orcid)
    other = await make_user(role="researcher")
    callback = await _orcid_flow(other, orcid)
    assert _result(await other.client.get(callback)) == "already_linked"


async def test_mock_off_by_default(make_user):
    user = await make_user(role="researcher")
    assert_error(
        await user.client.post("/me/professional/orcid/start", json={}), 501, "not_implemented"
    )
    assert (await user.client.get("/_mock/orcid/oauth/authorize")).status_code == 404
    assert (await user.client.get("/_mock/orcid/oauth/decide")).status_code == 404
    me = (await user.client.get("/me/professional/card")).json()
    assert me["verification"]["orcid_available"] is False


def test_mock_refused_under_production_settings():
    prod = {
        "api_url": "https://api.amber.example",
        "frontend_url": "https://amber.example",
        "session_secret": "a-real-random-secret-for-this-test-only",
        "cookie_secure": True,
    }
    Settings(**prod)  # fine without the mock
    with pytest.raises(ValidationError, match="ORCID_MOCK"):
        Settings(**prod, orcid_mock=True)


def test_mock_not_served_when_not_local(monkeypatch):
    """Defence in depth: even with ORCID_MOCK set, nothing runs off loopback."""
    from types import SimpleNamespace

    from backend.api.services import orcid

    fake = SimpleNamespace(
        orcid_mock=True, is_local=False, orcid_client_id="", orcid_client_secret=""
    )
    monkeypatch.setattr(orcid, "get_settings", lambda: fake)
    assert orcid.mock_enabled() is False and orcid.mode() is None


# ---- the card ----------------------------------------------------------------------------


async def test_card_needs_verification_and_opt_in(make_user, orcid_mock, superuser):
    user = await make_user(role="researcher")
    await user.client.put("/me/professional", json=WORK)
    assert_error(
        await user.client.put("/me/professional/card", json={"visible": True}), 409, "conflict"
    )
    orcid = _new_orcid()
    await user.client.get(await _orcid_flow(user, orcid))
    me = (await user.client.get("/me/professional/card")).json()
    assert me["settings"]["visible"] is False and me["card_id"] is None  # off by default
    assert me["can_show"] is True and me["preview"]["name"] == "Ada Lovelace"
    shown = await _show(user, headline="Epilepsy genetics")
    assert shown["settings"]["visible"] and shown["settings"]["visible_since"]
    card_id = shown["card_id"]

    viewer = await make_user(role="patient")
    r = await viewer.client.get(f"/people/{card_id}")
    assert r.status_code == 200
    card = r.json()
    assert set(card) == CARD_KEYS
    assert card == shown["preview"]
    assert card["role"] == "researcher" and card["role_self_declared"] is True
    assert card["name_source"] == "orcid" and card["orcid_id"] == orcid
    assert card["verification"]["simulated"] is True
    assert "simulated" in card["verification"]["label"].lower()
    assert card["accepts_patient_messages"] is False
    assert card["institutions"] == [{"node_id": None, "label": "Uni Test"}]
    text = r.text
    for private in (str(user.id), user.sub, "@example.test"):
        assert private not in text

    # Hiding institutions removes them from the card.
    await _show(user, show_institutions=False)
    assert (await viewer.client.get(f"/people/{card_id}")).json()["institutions"] == []

    # Off removes it at once; the card id stays the same when switched on again.
    off = await user.client.put("/me/professional/card", json={"visible": False})
    assert off.json()["settings"]["visible"] is False
    assert_error(await viewer.client.get(f"/people/{card_id}"), 404, "not_found")
    assert (await _show(user))["card_id"] == card_id


async def test_name_matched_link_stays_private(make_user, orcid_mock, superuser):
    user = await make_user(role="researcher")
    await user.client.put("/me/professional", json={**WORK, "atlas_node_id": PERSON})
    await user.client.get(await _orcid_flow(user))  # ORCID not in the atlas: link unverified
    card = (await _show(user))["preview"]
    assert card["atlas_node_id"] is None
    viewer = await make_user(role="patient")
    listed = await viewer.client.get("/people", params={"disease": _disease_of(PERSON)})
    assert card["card_id"] not in {c["card_id"] for c in listed.json()["items"]}


async def test_list_by_disease_and_cache_refresh(make_user, orcid_mock, superuser):
    user = await _verified_researcher(make_user, link=PERSON, superuser=superuser)
    shown = await _show(user)
    card_id = shown["card_id"]
    assert shown["preview"]["atlas_node_id"] == PERSON
    disease = _disease_of(PERSON)
    viewer = await make_user(role="doctor")
    r = await viewer.client.get("/people", params={"disease": disease})
    assert r.status_code == 200
    assert card_id in {c["card_id"] for c in r.json()["items"]}
    await user.client.put("/me/professional/card", json={"visible": False})
    r = await viewer.client.get("/people", params={"disease": disease})
    assert card_id not in {c["card_id"] for c in r.json()["items"]}
    assert_error(
        await viewer.client.get("/people", params={"disease": "MONDO:0000001"}), 404, "not_found"
    )
    assert (await viewer.client.get("/people", params={"disease": "HP:0001250"})).status_code == 422


async def test_atlas_summary_card_id(make_user, client, orcid_mock, superuser):
    user = await _verified_researcher(make_user, link=PERSON, superuser=superuser)
    card_id = (await _show(user))["card_id"]
    viewer = await make_user(role="patient")

    async def card_ids(c, disease):
        r = await c.get(f"/atlas/summary/{disease}")
        assert r.status_code == 200
        return {
            i["id"]: i.get("card_id")
            for s in r.json()["sections"]
            if s["key"] in ("researchers", "doctors")
            for i in s["items"]
        }

    disease = None
    for d in sorted(people_service._person_diseases(get_graph(), PERSON)):
        if PERSON in await card_ids(viewer.client, d):
            disease = d
            break
    if disease is None:
        pytest.skip("fixture researcher is not in any disease's top researchers")
    ids = await card_ids(viewer.client, disease)
    assert ids[PERSON] == card_id
    assert all(v is None for k, v in ids.items() if k != PERSON)
    assert (await card_ids(client, disease))[PERSON] is None  # guests never see it
    await user.client.put("/me/professional/card", json={"visible": False})
    assert (await card_ids(viewer.client, disease))[PERSON] is None


async def test_headline_validation(make_user):
    user = await make_user(role="researcher")
    for bad in ("x" * 161, "mail me: a@b.test", "see https://x.test", "call 0664123456"):
        r = await user.client.put("/me/professional/card", json={"headline": bad})
        assert_error(r, 422, "validation_error")


# ---- role switch, deletion, export -----------------------------------------------------------


async def test_role_switch_hides_or_deletes_the_card(make_user, orcid_mock, superuser):
    user = await _verified_researcher(make_user)
    card_id = (await _show(user))["card_id"]
    viewer = await make_user(role="patient")
    assert (await viewer.client.get(f"/people/{card_id}")).status_code == 200

    await user.client.patch("/me/settings", json={"role": "doctor"})
    assert_error(await viewer.client.get(f"/people/{card_id}"), 404, "not_found")
    me = (await user.client.get("/me/professional/card")).json()
    assert me["verification"]["verified"] is False and me["settings"]["visible"] is False

    await user.client.patch("/me/settings", json={"role": "patient"})
    row = await superuser.fetchrow(
        "SELECT first_name, orcid_id, card_id, card_visible, role_verified, verified_name"
        " FROM profiles WHERE user_id = $1",
        user.id,
    )
    assert dict(row) == {
        "first_name": None,
        "orcid_id": None,
        "card_id": None,
        "card_visible": False,
        "role_verified": False,
        "verified_name": None,
    }


async def test_delete_work_details_removes_card(make_user, orcid_mock):
    user = await _verified_researcher(make_user)
    card_id = (await _show(user))["card_id"]
    viewer = await make_user(role="patient")
    assert (await user.client.delete("/me/professional")).status_code == 204
    assert_error(await viewer.client.get(f"/people/{card_id}"), 404, "not_found")


async def test_account_deletion_removes_card(make_user, orcid_mock, superuser):
    user = await _verified_researcher(make_user, link=PERSON, superuser=superuser)
    card_id = (await _show(user))["card_id"]
    viewer = await make_user(role="patient")
    assert (await user.client.delete("/me")).status_code == 204
    assert_error(await viewer.client.get(f"/people/{card_id}"), 404, "not_found")
    listed = await viewer.client.get("/people", params={"disease": _disease_of(PERSON)})
    assert card_id not in {c["card_id"] for c in listed.json()["items"]}
    assert card_id not in {str(k) for k in people_service._cache.cards}


async def test_health_data_withdrawal_keeps_the_card(make_user, orcid_mock):
    user = await make_user(role="researcher", consents=["health_data"])
    await user.client.put("/me/professional", json=WORK)
    await user.client.get(await _orcid_flow(user))
    card_id = (await _show(user))["card_id"]
    assert (await user.client.delete("/consents/health_data")).status_code == 204
    viewer = await make_user(role="patient")
    assert (await viewer.client.get(f"/people/{card_id}")).status_code == 200


async def test_export_contains_verification_and_card(make_user, orcid_mock):
    user = await _verified_researcher(make_user)
    card_id = (await _show(user, headline="Hello"))["card_id"]
    exp = (await user.client.get("/me/export")).json()["professional"]
    assert exp["verification_method"] == "orcid_simulated" and exp["orcid_verified_at"]
    assert exp["card_id"] == card_id and exp["card_visible"] is True
    assert exp["card_headline"] == "Hello" and exp["verified_name"] == "Ada Lovelace"


# ---- manual review -------------------------------------------------------------------------


async def test_manual_review_flow(make_user, superuser):
    from backend.cli import verification_requests, verify_professional

    user = await make_user(role="doctor")
    await user.client.put("/me/professional", json=WORK)
    body = {"institutional_email": "ada@uni.test", "profile_url": "https://uni.test/ada"}
    r = await user.client.post("/me/professional/verification-request", json=body)
    assert r.status_code == 200
    assert r.json()["verification"]["request"]["status"] == "pending"
    assert str(user.id) in {str(row["user_id"]) for row in verification_requests(out=_Null())}

    with pytest.raises(SystemExit):
        verify_professional(str(user.id), reason=" ", out=_Null())
    assert verify_professional(str(user.id), reason="staff page lists her", out=_Null()) == (
        "approved"
    )
    row = await superuser.fetchrow(
        "SELECT role_verified, verification_method, verification_request, verified_name,"
        " verification_reason FROM profiles WHERE user_id = $1",
        user.id,
    )
    assert row["role_verified"] and row["verification_method"] == "institutional_email"
    assert row["verification_request"] is None  # e-mail and link dropped
    assert row["verified_name"] == "Ada Lovelace"
    assert row["verification_reason"] == "staff page lists her"
    card = (await _show(user))["preview"]
    assert card["name_source"] == "reviewed" and card["orcid_id"] is None
    assert card["verification"]["label"].startswith("Identity checked by the Amber team")

    # Editing the reviewed name ends the verification and hides the card.
    await user.client.put("/me/professional", json={**WORK, "first_name": "Eve"})
    me = (await user.client.get("/me/professional/card")).json()
    assert me["verification"]["verified"] is False and me["settings"]["visible"] is False
    viewer = await make_user(role="patient")
    assert_error(await viewer.client.get(f"/people/{card['card_id']}"), 404, "not_found")


async def test_manual_review_reject_and_withdraw(make_user, superuser):
    from backend.cli import verify_professional

    user = await make_user(role="researcher")
    body = {"institutional_email": "x@uni.test", "profile_url": "https://uni.test/x"}
    await user.client.post("/me/professional/verification-request", json=body)
    assert verify_professional(str(user.id), reason="no match", reject=True, out=_Null()) == (
        "rejected"
    )
    req = (await user.client.get("/me/professional/card")).json()["verification"]["request"]
    assert req["status"] == "rejected" and req["institutional_email"] is None
    assert (await user.client.delete("/me/professional/verification-request")).status_code == 204
    assert (
        await superuser.fetchval(
            "SELECT verification_request FROM profiles WHERE user_id = $1", user.id
        )
        is None
    )
    for bad in ({**body, "profile_url": "http://uni.test/x"}, {**body, "institutional_email": "x"}):
        r = await user.client.post("/me/professional/verification-request", json=bad)
        assert_error(r, 422, "validation_error")


async def test_rate_limits(make_user, orcid_mock):
    user = await make_user(role="researcher")
    body = {"institutional_email": "x@uni.test", "profile_url": "https://uni.test/x"}
    for _ in range(3):
        r = await user.client.post("/me/professional/verification-request", json=body)
        assert r.status_code == 200
    r = await user.client.post("/me/professional/verification-request", json=body)
    assert_error(r, 429, "rate_limited")
    for _ in range(10):
        assert (await user.client.post("/me/professional/orcid/start", json={})).status_code == 200
    assert_error(
        await user.client.post("/me/professional/orcid/start", json={}), 429, "rate_limited"
    )


class _Null:
    def write(self, _s: str) -> int:
        return 0

    def flush(self) -> None:
        pass
