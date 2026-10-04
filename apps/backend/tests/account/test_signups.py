"""Connect stage 4: suggestions of calls and sign-ups (matching, consent, 16-17 rules, RLS,
the publisher's view and decline, withdrawal, retention, consent withdrawal, rights, demo)."""

import io
import json
import uuid

import asyncpg
import pytest
from account_helpers import assert_error

from backend import calls_cli
from backend.api.ratelimit import limiter
from backend.api.services.messaging import operator
from backend.db.models import SIGNUP_TABLES
from backend.schemas.account import CONSENT_TEXT_VERSIONS
from backend.schemas.enums import ConsentType
from backend.schemas.signups import AUTHORIZATION_VERSION, MINOR_LABEL

DRAVET = "MONDO:0100135"
GEFS = "MONDO:9900001"
SCN1A = "HGNC:10585"
STXBP1 = "HGNC:11444"
CONNECT = CONSENT_TEXT_VERSIONS[ConsentType.connect]
NOW = "2026-10-01T10:00:00+00:00"

SURVEY = {
    "kind": "survey",
    "title": "Sleep in Dravet syndrome",
    "summary": "An online survey about sleep and night-time seizures.",
    "participation": "About 20 minutes online.",
    "disease_ids": [DRAVET],
    "gene_ids": [SCN1A],
    "phenotype_ids": ["HP:0001250", "HP:0002133", "HP:0001263"],
    "countries": ["DE"],
    "min_age": 2,
    "max_age": 40,
    "remote": True,
    "requested_fields": ["diagnosis", "genetic_findings", "symptoms", "age_range", "country"],
}


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()
    yield
    limiter.reset()


def item(item_id, label, **extra):
    return {"source": "manual", "confirmed_at": NOW, "id": item_id, "label": label, **extra}


DRAVET_PROFILE = {
    "diseases": [item(DRAVET, "Dravet syndrome")],
    "genes": [item(SCN1A, "SCN1A")],
    "variants": [],
    "phenotypes": [item("HP:0001250", "Seizure")],
    "age_years": 7,
    "country": "DE",
}


async def make_publisher(make_user, superuser, *, name="Ada Doe"):
    pub = await make_user(role="researcher")
    await superuser.execute(
        "UPDATE profiles SET role_verified = true, verification_method = 'orcid_simulated',"
        " verified_name = $2, card_id = gen_random_uuid(), card_visible = true,"
        ' institutions = \'[{"node_id": null, "label": "Test Institute"}]\'::jsonb'
        " WHERE user_id = $1",
        pub.id,
        name,
    )
    return pub


async def publish(pub, body=SURVEY, **changes):
    r = await pub.client.post("/me/calls", json={**body, **changes})
    assert r.status_code == 201, r.text
    call_id = r.json()["id"]
    r = await pub.client.post(f"/me/calls/{call_id}/submit")
    assert r.status_code == 200 and r.json()["status"] == "published", r.text
    return call_id


async def make_patient(
    make_user, superuser, profile=DRAVET_PROFILE, *, age="18_plus", consent=True, suggest=False
):
    user = await make_user()
    if consent:
        await superuser.execute(
            "INSERT INTO consents (user_id, consent_type, version) VALUES ($1, 'connect', $2)",
            user.id,
            CONNECT,
        )
    await superuser.execute(
        "UPDATE profiles SET connect_age_group = $2, suggestions_enabled = $3 WHERE user_id = $1",
        user.id,
        age,
        suggest,
    )
    if profile is not None:
        await superuser.execute(
            "INSERT INTO patient_profiles (user_id, profile) VALUES ($1, $2::jsonb)",
            user.id,
            json.dumps(profile),
        )
    return user


def signup_body(items=(), **extra):
    return {
        "display_name": "Mia's mum",
        "items": list(items),
        "authorized": True,
        "authorization_version": AUTHORIZATION_VERSION,
        **extra,
    }


async def sign_up(patient, call_id, items=(f"diagnosis:{DRAVET}",), **extra):
    return await patient.client.post(f"/calls/{call_id}/signup", json=signup_body(items, **extra))


# ---- suggestions ----------------------------------------------------------------------------


async def test_suggestions_need_consent_and_the_setting(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    await publish(pub)
    for consent, suggest in ((False, False), (True, False), (False, True)):
        p = await make_patient(make_user, superuser, consent=consent, suggest=suggest)
        r = await p.client.get("/calls/suggested")
        assert r.status_code == 200 and r.json()["items"] == []
        assert (r.json()["consent_active"], r.json()["enabled"]) == (consent, suggest)
    # An old-text consent (messaging only) is not enough.
    old = await make_patient(make_user, superuser, consent=False, suggest=True)
    await superuser.execute(
        "INSERT INTO consents (user_id, consent_type, version)"
        " VALUES ($1, 'connect', 'connect-2026-10-04')",
        old.id,
    )
    assert (await old.client.get("/calls/suggested")).json()["items"] == []
    assert (await old.client.get("/me/connect")).json()["consent_current"] is False
    assert_error(
        await old.client.put("/me/connect/suggestions", json={"enabled": True}),
        403,
        "consent_required",
    )


async def test_switch_on_and_off(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    call_id = await publish(pub)
    p = await make_patient(make_user, superuser)
    r = await p.client.put("/me/connect/suggestions", json={"enabled": True})
    assert r.status_code == 200 and r.json()["enabled"] and r.json()["enabled_at"]
    items = (await p.client.get("/calls/suggested")).json()["items"]
    assert call_id in [i["call"]["id"] for i in items]  # calls of other tests may match too
    notes = (await p.client.get("/notifications")).json()["items"]
    match = [n for n in notes if n["kind"] == "call_match" and n["call_id"] == call_id]
    assert len(match) == 1 and match[0]["call_id"] == call_id
    assert match[0]["item_label"] == SURVEY["title"] and match[0]["gone"] is False
    r = await p.client.put("/me/connect/suggestions", json={"enabled": False})
    assert r.json()["enabled"] is False
    assert (
        await superuser.fetchval(
            "SELECT count(*) FROM notifications WHERE user_id = $1 AND kind = 'call_match'", p.id
        )
        == 0
    )


async def test_matching_rules_and_reasons(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    by_disease = await publish(pub, disease_ids=[DRAVET], gene_ids=[], phenotype_ids=[])
    by_gene = await publish(pub, title="Gene call", disease_ids=[GEFS], phenotype_ids=[])
    by_symptoms = await publish(
        pub,
        title="Symptom call",
        disease_ids=[GEFS],
        gene_ids=[],
        phenotype_ids=["HP:0001250", "HP:0002133"],
    )
    one_symptom = await publish(
        pub, title="One symptom", disease_ids=[GEFS], gene_ids=[], phenotype_ids=["HP:0001250"]
    )
    no_match = await publish(
        pub, title="Other", disease_ids=["MONDO:9900007"], gene_ids=[STXBP1], phenotype_ids=[]
    )
    profile = {
        "diseases": [
            item(DRAVET, "Dravet syndrome"),
            {**item("MONDO:9900007", "STXBP1 encephalopathy"), "confirmed_at": None},
        ],
        "genes": [],
        "variants": [{"source": "manual", "confirmed_at": NOW, "gene_id": SCN1A, "hgvs": "c.1A>G"}],
        "phenotypes": [
            item("HP:0001250", "Seizure"),
            item("HP:0002133", "Status epilepticus"),
            {**item("HP:0001263", "Delay"), "excluded": True},
        ],
        "age_years": 50,
    }
    p = await make_patient(make_user, superuser, profile, suggest=True)
    mine = {by_disease, by_gene, by_symptoms, one_symptom, no_match}
    listed = (await p.client.get("/calls/suggested")).json()["items"]
    items = {i["call"]["id"]: i for i in listed if i["call"]["id"] in mine}
    assert set(items) == {by_disease, by_gene, by_symptoms}
    assert one_symptom not in items and no_match not in items  # unconfirmed disease ignored
    d = items[by_disease]
    assert [r["kind"] for r in d["reasons"]] == ["disease"] and d["score"] == 3
    assert d["sentence"] == (
        "Suggested because your profile lists Dravet syndrome. This is not an eligibility "
        "check; only the study team decides."
    )
    g = items[by_gene]["reasons"]
    assert [r["kind"] for r in g] == ["gene"] and g[0]["via_variant"] is True
    assert "SCN1A" in items[by_gene]["sentence"]
    s = items[by_symptoms]["reasons"]
    assert [r["kind"] for r in s] == ["symptoms"]
    assert {x["id"] for x in s[0]["items"]} == {"HP:0001250", "HP:0002133"}
    # Age is information only: 50 is outside 2-40 and the call is still suggested.
    assert d["age_fits"] is False and d["country_listed"] is None
    order = [i["call"]["id"] for i in listed if i["call"]["id"] in mine]
    assert order[0] == by_disease  # strongest first (by_disease was published first)


async def test_suggestions_store_nothing_and_publishers_learn_nothing(
    make_user, superuser, connect_as
):
    pub = await make_publisher(make_user, superuser)
    call_id = await publish(pub)
    p = await make_patient(make_user, superuser, suggest=True)
    before = await superuser.fetchval("SELECT count(*) FROM call_signups")
    await p.client.get("/calls/suggested")
    await p.client.get("/notifications")
    assert await superuser.fetchval("SELECT count(*) FROM call_signups") == before
    rows = await superuser.fetch(
        "SELECT user_id, kind FROM notifications WHERE ref_id = $1", str(call_id)
    )
    assert [(r["user_id"], r["kind"]) for r in rows] == [(p.id, "call_match")]
    # The publisher's views carry nothing about suggested users.
    for path in ("/me/calls", f"/me/calls/{call_id}", f"/me/calls/{call_id}/signups"):
        body = (await pub.client.get(path)).text
        assert str(p.id) not in body and "suggest" not in body.lower()
    signups = (await pub.client.get(f"/me/calls/{call_id}/signups")).json()
    assert signups["items"] == [] and signups["active_count"] == 0
    # Nor through the database: the publisher cannot read the patient's notifications.
    app = await connect_as("atlas_app")
    async with app.transaction():
        await app.execute("SELECT set_config('app.user_id', $1, true)", str(pub.id))
        n = await app.fetchval("SELECT count(*) FROM notifications WHERE kind = 'call_match'")
        assert n == 0


# ---- sign-ups -------------------------------------------------------------------------------


async def test_options_offer_only_allowed_items(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    call_id = await publish(pub, requested_fields=["diagnosis", "symptoms"])
    p = await make_patient(make_user, superuser)
    r = await p.client.get(f"/calls/{call_id}/signup")
    assert r.status_code == 200, r.text
    body = r.json()
    keys = {o["key"]: o for o in body["options"]}
    # SCN1A is a target but genetic findings are not requested; age and country neither.
    assert set(keys) == {f"diagnosis:{DRAVET}", "symptom:HP:0001250"}
    assert keys[f"diagnosis:{DRAVET}"]["preselected"] is True
    assert keys["symptom:HP:0001250"]["preselected"] is False
    assert body["recipient"] == "Ada Doe, Test Institute"
    assert "Ada Doe, Test Institute" in body["authorization_text"]
    assert body["availability"]["can_sign_up"] and body["consent_active"]
    for i, bad in enumerate((f"gene:{SCN1A}", "age_range", "country", "diagnosis:MONDO:9900007")):
        r = await sign_up(p, call_id, [f"diagnosis:{DRAVET}", bad])
        assert_error(r, 422, "validation_error")
        assert "items.1" in r.json()["error"]["message"], i


async def test_sign_up_shares_only_ticked_items(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    call_id = await publish(pub)
    p = await make_patient(make_user, superuser)
    r = await sign_up(p, call_id, [f"diagnosis:{DRAVET}", "age_range"], note="  Hello team  ")
    assert r.status_code == 201, r.text
    mine = r.json()
    assert mine["status"] == "active" and mine["note"] == "Hello team"
    assert [d["id"] for d in mine["shared"]["diagnoses"]] == [DRAVET]
    assert mine["shared"]["age_range"] == "6-12" and mine["shared"]["country"] is None
    assert mine["shared"]["genes"] == [] and mine["shared"]["symptoms"] == []
    assert mine["authorization_version"] == AUTHORIZATION_VERSION and mine["authorized_at"]
    assert mine["guardian_agreed_at"] is None and mine["call_open"] is True
    row = await superuser.fetchrow(
        "SELECT * FROM call_signups WHERE id = $1", uuid.UUID(mine["id"])
    )
    assert row["recipient_name"] == "Ada Doe, Test Institute" and row["call_closes_at"] is None
    listed = (await p.client.get("/me/signups")).json()["items"]
    assert [s["id"] for s in listed] == [mine["id"]]
    seen = (await pub.client.get(f"/me/calls/{call_id}/signups")).json()
    assert seen["active_count"] == 1
    got = seen["items"][0]
    assert got["display_name"] == "Mia's mum" and got["note"] == "Hello team"
    assert got["minor"] is False and got["minor_label"] is None
    assert str(p.id) not in json.dumps(seen) and "email" not in json.dumps(seen)


@pytest.mark.parametrize("field", ["authorized", "authorization_version"])
async def test_authorization_required(make_user, superuser, field):
    pub = await make_publisher(make_user, superuser)
    call_id = await publish(pub)
    p = await make_patient(make_user, superuser)
    bad = {"authorized": False} if field == "authorized" else {"authorization_version": "old"}
    r = await p.client.post(f"/calls/{call_id}/signup", json={**signup_body(), **bad})
    assert_error(r, 422, "validation_error")
    assert field in r.json()["error"]["message"]


async def test_sign_up_refusals(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    call_id = await publish(pub, max_signups=1)
    # No consent, no age group.
    nobody = await make_patient(make_user, superuser, consent=False)
    assert_error(await sign_up(nobody, call_id), 403, "consent_required")
    no_age = await make_patient(make_user, superuser, age=None)
    assert_error(await sign_up(no_age, call_id), 403, "age_group_required")
    # Experts never sign up, the publisher not to their own call.
    expert = await make_user(role="doctor")
    assert_error(await sign_up(expert, call_id), 403, "forbidden")
    assert_error(await sign_up(pub, call_id), 403, "forbidden")
    # First one is fine, a duplicate and the second patient (max 1) are refused.
    a = await make_patient(make_user, superuser)
    assert (await sign_up(a, call_id)).status_code == 201
    r = await sign_up(a, call_id)
    assert_error(r, 409, "conflict")
    assert "already" in r.json()["error"]["message"]
    b = await make_patient(make_user, superuser)
    r = await sign_up(b, call_id)
    assert_error(r, 409, "conflict")
    assert "all the sign-ups" in r.json()["error"]["message"]
    # Unknown, closed and expired calls; a hidden publisher card.
    assert_error(await sign_up(b, uuid.uuid4()), 404, "not_found")
    closed = await publish(pub)
    await pub.client.post(f"/me/calls/{closed}/close")
    assert_error(await sign_up(b, closed), 404, "not_found")
    expired = await publish(pub)
    await superuser.execute(
        "ALTER TABLE calls DISABLE TRIGGER calls_guard;"
        " UPDATE calls SET closes_at = current_date - 1 WHERE id = '" + expired + "';"
        " ALTER TABLE calls ENABLE TRIGGER calls_guard"
    )
    r = await sign_up(b, expired)
    assert_error(r, 409, "conflict")
    assert "closed on" in r.json()["error"]["message"]
    hidden = await publish(pub)
    await superuser.execute("UPDATE profiles SET card_visible = false WHERE user_id = $1", pub.id)
    r = await sign_up(b, hidden)
    assert_error(r, 409, "conflict")
    assert "cannot receive" in r.json()["error"]["message"]


async def test_database_refuses_direct_inserts(make_user, superuser, connect_as):
    pub = await make_publisher(make_user, superuser)
    call_id = await publish(pub, max_signups=1)
    p = await make_patient(make_user, superuser)
    app = await connect_as("atlas_app")
    sql = (
        "INSERT INTO call_signups (call_id, patient_id, call_title_snapshot, recipient_name,"
        " display_name, authorization_version, status) VALUES ($1, $2, 't', 'r', 'n', 'v', $3)"
    )
    for uid, status, error in (
        (pub.id, "active", asyncpg.CheckViolationError),  # own call
        (p.id, "withdrawn", asyncpg.InsufficientPrivilegeError),  # status is not the client's
        (pub.id, "active", asyncpg.CheckViolationError),
    ):
        with pytest.raises(error):
            async with app.transaction():
                await app.execute("SELECT set_config('app.user_id', $1, true)", str(uid))
                await app.execute(sql, uuid.UUID(call_id), uid, status)
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        async with app.transaction():
            await app.execute("SELECT set_config('app.user_id', $1, true)", str(p.id))
            other = await make_user()
            await app.execute(sql, uuid.UUID(call_id), other.id, "active")


async def test_minor_needs_guardian_and_adults_only(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    call_id = await publish(pub)
    adults = await publish(pub, title="Adults only", min_age=18, max_age=None)
    minor = await make_patient(make_user, superuser, age="16_17", suggest=True)
    opts = (await minor.client.get(f"/calls/{call_id}/signup")).json()
    assert opts["guardian_required"] is True and "Ada Doe" in opts["guardian_text"]
    assert_error(await sign_up(minor, call_id), 403, "guardian_agreement_required")
    r = await sign_up(minor, call_id, guardian_agreed=True)
    assert r.status_code == 201, r.text
    assert r.json()["guardian_agreed_at"] and r.json()["guardian_text_version"]
    seen = (await pub.client.get(f"/me/calls/{call_id}/signups")).json()["items"][0]
    assert seen["minor"] is True and seen["minor_label"] == MINOR_LABEL
    # A call for adults: suggested (age never hides) but no sign-up for a 16- or 17-year-old.
    sug = {i["call"]["id"]: i for i in (await minor.client.get("/calls/suggested")).json()["items"]}
    assert sug[adults]["signup"]["can_sign_up"] is False
    assert sug[adults]["signup"]["blocked_by"] == "for_adults"
    assert_error(await sign_up(minor, adults, guardian_agreed=True), 403, "forbidden")
    adult = await make_patient(make_user, superuser)
    assert (await sign_up(adult, adults)).status_code == 201


async def test_child_profile_needs_parental_responsibility(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    call_id = await publish(pub)
    p = await make_patient(
        make_user,
        superuser,
        {
            **DRAVET_PROFILE,
            "about_child": True,
            "parental_responsibility_confirmed": True,
        },  # fmt: skip
    )
    r = await sign_up(p, call_id)
    assert r.status_code == 201 and r.json()["about_child"] is True
    seen = (await pub.client.get(f"/me/calls/{call_id}/signups")).json()["items"][0]
    assert seen["about_child"] is True
    # A stored child profile without the confirmation is unreadable, so nothing is offered.
    q = await make_patient(make_user, superuser, {**DRAVET_PROFILE, "about_child": True})
    assert_error(await sign_up(q, call_id), 422, "validation_error")


async def test_rls_between_patient_publisher_and_third_user(make_user, superuser, connect_as):
    pub = await make_publisher(make_user, superuser)
    call_id = await publish(pub)
    p = await make_patient(make_user, superuser)
    sid = uuid.UUID((await sign_up(p, call_id)).json()["id"])
    third = await make_user()
    other_pub = await make_publisher(make_user, superuser, name="Bo Roe")
    app = await connect_as("atlas_app")
    su_rls = await superuser.fetchrow(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = $1",
        SIGNUP_TABLES[0],
    )
    assert tuple(su_rls) == (True, True)

    async def visible(uid):
        async with app.transaction():
            await app.execute("SELECT set_config('app.user_id', $1, true)", str(uid or ""))
            return await app.fetchval("SELECT count(*) FROM call_signups WHERE id = $1", sid)

    assert await visible(p.id) == 1 and await visible(pub.id) == 1
    assert await visible(third.id) == 0 and await visible(other_pub.id) == 0
    assert await visible(None) == 0
    for uid in (pub.id, third.id):  # nobody else can change or delete it
        async with app.transaction():
            await app.execute("SELECT set_config('app.user_id', $1, true)", str(uid))
            r1 = await app.execute("UPDATE call_signups SET note = 'x' WHERE id = $1", sid)
            r2 = await app.execute("DELETE FROM call_signups WHERE id = $1", sid)
            assert r1 == "UPDATE 0" and r2 == "DELETE 0"
    # The patient cannot rewrite what was shared, the authorization or re-activate.
    for change in ("shared = '{}'::jsonb", "authorization_version = 'x'", "purge_after = now()"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with app.transaction():
                await app.execute("SELECT set_config('app.user_id', $1, true)", str(p.id))
                await app.execute(f"UPDATE call_signups SET {change} WHERE id = $1", sid)
    # The other publisher and the third user see no sign-ups through the API either.
    assert_error(await other_pub.client.get(f"/me/calls/{call_id}/signups"), 404, "not_found")
    assert (await third.client.get("/me/signups")).json()["items"] == []
    r = await third.client.delete(f"/me/signups/{sid}")
    assert_error(r, 404, "not_found")
    r = await other_pub.client.post(f"/me/calls/{call_id}/signups/{sid}/decline")
    assert_error(r, 404, "not_found")


async def test_publisher_declines(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    call_id = await publish(pub)
    p = await make_patient(make_user, superuser)
    sid = (await sign_up(p, call_id, note="please")).json()["id"]
    r = await pub.client.post(f"/me/calls/{call_id}/signups/{sid}/decline")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "declined" and r.json()["note"] is None
    assert r.json()["shared"]["diagnoses"] == [] and r.json()["declined_at"]
    assert (await pub.client.post(f"/me/calls/{call_id}/signups/{sid}/decline")).status_code == 200
    mine = (await p.client.get("/me/signups")).json()["items"][0]
    assert mine["status"] == "declined" and mine["delete_after"]
    r = await sign_up(p, call_id)  # no second sign-up after a decline
    assert_error(r, 409, "conflict")


async def test_withdraw_keeps_a_stub_then_purges(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    call_id = await publish(pub)
    p = await make_patient(make_user, superuser)
    sid = (await sign_up(p, call_id, note="hi", open_conversation=True)).json()["id"]
    thread_id = await superuser.fetchval(
        "SELECT thread_id FROM call_signups WHERE id = $1", uuid.UUID(sid)
    )
    assert thread_id is not None
    assert (await p.client.delete(f"/me/signups/{sid}")).status_code == 204
    assert (await p.client.delete(f"/me/signups/{sid}")).status_code == 204  # idempotent
    row = await superuser.fetchrow("SELECT * FROM call_signups WHERE id = $1", uuid.UUID(sid))
    assert row["status"] == "withdrawn" and row["note"] is None and row["shared"] == "{}"
    assert row["purge_after"] is not None
    assert await superuser.fetchval("SELECT status FROM threads WHERE id = $1", thread_id) == (
        "closed"
    )
    stub = (await pub.client.get(f"/me/calls/{call_id}/signups")).json()["items"][0]
    assert stub["status"] == "withdrawn" and stub["shared"]["diagnoses"] == []
    # A withdrawn sign-up can be followed by a new one.
    assert (await sign_up(p, call_id)).status_code == 201
    # After 30 days the stub disappears for the publisher and is deleted when the patient reads.
    await superuser.execute(
        "UPDATE call_signups SET purge_after = now() - interval '1 minute' WHERE id = $1",
        uuid.UUID(sid),
    )
    ids = [s["id"] for s in (await pub.client.get(f"/me/calls/{call_id}/signups")).json()["items"]]
    assert sid not in ids
    await p.client.get("/me/signups")
    assert (
        await superuser.fetchval("SELECT count(*) FROM call_signups WHERE id = $1", uuid.UUID(sid))
        == 0
    )


async def test_closed_call_purged_after_90_days_and_operator_purge(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    call_id = await publish(pub)
    p = await make_patient(make_user, superuser)
    sid = uuid.UUID((await sign_up(p, call_id)).json()["id"])
    await pub.client.post(f"/me/calls/{call_id}/close")
    row = await superuser.fetchrow("SELECT * FROM call_signups WHERE id = $1", sid)
    assert row["status"] == "call_closed" and row["call_ended_at"] is not None
    days = await superuser.fetchval(
        "SELECT round(extract(epoch FROM purge_after - now()) / 86400) FROM call_signups"
        " WHERE id = $1",
        sid,
    )
    assert days == 90
    # The publisher still sees it (items kept) until then.
    seen = (await pub.client.get(f"/me/calls/{call_id}/signups")).json()["items"][0]
    assert seen["status"] == "call_closed" and seen["shared"]["diagnoses"]
    await superuser.execute(
        "UPDATE call_signups SET purge_after = now() - interval '1 day' WHERE id = $1", sid
    )
    counts = operator.purge(out=io.StringIO())
    assert counts["call_signups"] >= 1
    assert await superuser.fetchval("SELECT count(*) FROM call_signups WHERE id = $1", sid) == 0


async def test_deleted_call_leaves_a_stub(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    call_id = await publish(pub)
    p = await make_patient(make_user, superuser)
    sid = uuid.UUID((await sign_up(p, call_id, open_conversation=True)).json()["id"])
    assert (await pub.client.delete(f"/me/calls/{call_id}")).status_code == 204
    row = await superuser.fetchrow("SELECT * FROM call_signups WHERE id = $1", sid)
    assert row["call_id"] is None and row["status"] == "call_closed" and row["shared"] == "{}"
    thread = await superuser.fetchrow(
        "SELECT call_id, signup_id FROM threads WHERE signup_id = $1", sid
    )
    assert thread["call_id"] is None and thread["signup_id"] == sid
    mine = (await p.client.get("/me/signups")).json()["items"][0]
    assert mine["call_id"] is None and mine["call_open"] is False


async def test_signup_thread_policy_and_keys(make_user, superuser, connect_as):
    pub = await make_publisher(make_user, superuser)
    call_id = uuid.UUID(await publish(pub))
    p = await make_patient(make_user, superuser)
    r = await sign_up(p, call_id, open_conversation=True)
    sid = uuid.UUID(r.json()["id"])
    tid = uuid.UUID(r.json()["thread_id"])
    t = await superuser.fetchrow("SELECT * FROM threads WHERE id = $1", tid)
    assert (t["opener_id"], t["recipient_id"], t["origin"], t["status"]) == (
        p.id,
        pub.id,
        "signup",
        "open",
    )
    assert t["opener_name"] == "Mia's mum" and t["recipient_name"] == "Ada Doe"
    # The publisher sees the conversation in their list.
    threads = (await pub.client.get("/me/threads")).json()["items"]
    assert [x["id"] for x in threads] == [str(tid)]
    # The insert policy: only the sign-up's own patient, to its publisher, once.
    app = await connect_as("atlas_app")
    third = await make_patient(make_user, superuser)
    sql = (
        "INSERT INTO threads (opener_id, recipient_id, origin, call_id, signup_id, opener_name,"
        " recipient_name, status) VALUES ($1, $2, 'signup', $3, $4, 'x', 'y', 'open')"
    )
    for uid, rid in ((third.id, pub.id), (p.id, pub.id), (p.id, third.id)):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with app.transaction():
                await app.execute("SELECT set_config('app.user_id', $1, true)", str(uid))
                await app.execute(sql, uid, rid, call_id, sid)
    # The foreign keys hold for every role (here the superuser, past row-level security).
    for call_ref, signup_ref in ((uuid.uuid4(), sid), (call_id, uuid.uuid4())):
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await superuser.execute(sql, p.id, pub.id, call_ref, signup_ref)
    with pytest.raises(asyncpg.CheckViolationError):  # card threads carry no call or sign-up
        await superuser.execute(sql.replace("'signup'", "'card'"), p.id, pub.id, call_id, sid)


async def test_connect_withdrawal(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    call_id = await publish(pub)
    p = await make_patient(make_user, superuser, suggest=True)
    sid = (await sign_up(p, call_id, note="n", open_conversation=True)).json()["id"]
    await p.client.get("/notifications")
    assert (
        await superuser.fetchval(
            "SELECT count(*) FROM notifications WHERE user_id = $1 AND kind = 'call_match'", p.id
        )
        >= 1
    )
    assert (await p.client.delete("/consents/connect")).status_code == 204
    row = await superuser.fetchrow("SELECT * FROM call_signups WHERE id = $1", uuid.UUID(sid))
    assert row["status"] == "withdrawn" and row["shared"] == "{}" and row["note"] is None
    stub = (await pub.client.get(f"/me/calls/{call_id}/signups")).json()["items"][0]
    assert stub["status"] == "withdrawn"
    assert (
        await superuser.fetchval(
            "SELECT count(*) FROM notifications WHERE user_id = $1 AND kind = 'call_match'", p.id
        )
        == 0
    )
    assert (
        await superuser.fetchval(
            "SELECT suggestions_enabled FROM profiles WHERE user_id = $1", p.id
        )
        is False
    )
    r = await p.client.get("/calls/suggested")
    assert r.json()["items"] == [] and r.json()["enabled"] is False
    assert (await p.client.get("/me/signups")).status_code == 200  # still readable


async def test_health_data_withdrawal_keeps_signups(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    call_id = await publish(pub)
    p = await make_patient(make_user, superuser, suggest=True)
    await superuser.execute(
        "INSERT INTO consents (user_id, consent_type, version) VALUES ($1, 'health_data', 'v1')",
        p.id,
    )
    await sign_up(p, call_id)
    await p.client.get("/notifications")
    assert (await p.client.delete("/consents/health_data")).status_code == 204
    assert (await p.client.get("/me/signups")).json()["items"][0]["status"] == "active"
    assert (
        await superuser.fetchval(
            "SELECT count(*) FROM notifications WHERE user_id = $1 AND kind = 'call_match'", p.id
        )
        == 0
    )


async def test_export_and_account_deletion(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    call_id = await publish(pub)
    p = await make_patient(make_user, superuser, suggest=True)
    sid = (await sign_up(p, call_id)).json()["id"]
    export = (await p.client.get("/me/export")).json()
    assert export["signups"]["suggestions_enabled"] is True
    assert [s["id"] for s in export["signups"]["signups"]] == [sid]
    assert export["signups"]["signups"][0]["shared"]["diagnoses"][0]["id"] == DRAVET
    # The publisher's export holds their calls, never the sign-ups of others.
    pub_export = (await pub.client.get("/me/export")).json()
    assert pub_export["signups"]["signups"] == [] and sid not in json.dumps(pub_export)
    # Deleting the patient deletes the sign-up; deleting the publisher leaves the patient a stub.
    q = await make_patient(make_user, superuser)
    qid = uuid.UUID((await sign_up(q, call_id)).json()["id"])
    assert (await p.client.delete("/me")).status_code == 204
    assert (
        await superuser.fetchval("SELECT count(*) FROM call_signups WHERE id = $1", uuid.UUID(sid))
        == 0
    )
    assert (await pub.client.delete("/me")).status_code == 204
    row = await superuser.fetchrow("SELECT * FROM call_signups WHERE id = $1", qid)
    assert row["call_id"] is None and row["status"] == "call_closed" and row["shared"] == "{}"


async def test_demo_seed_gets_suggested(make_user, superuser):
    ids = calls_cli.demo_calls(out=io.StringIO())
    try:
        p = await make_patient(make_user, superuser, suggest=True)
        items = (await p.client.get("/calls/suggested")).json()["items"]
        suggested = {i["call"]["id"] for i in items}
        dravet_calls = {
            str(r["id"])
            for r in await superuser.fetch(
                "SELECT id FROM calls WHERE demo AND $1 = ANY(disease_ids)", DRAVET
            )
        }
        assert dravet_calls and dravet_calls <= suggested and dravet_calls <= set(ids)
        demo = next(i for i in items if i["call"]["id"] in dravet_calls)
        assert demo["call"]["demo"] is True and demo["signup"]["can_sign_up"] is True
        r = await sign_up(p, demo["call"]["id"])
        assert r.status_code == 201, r.text
    finally:
        calls_cli.demo_calls(clear=True, out=io.StringIO())
