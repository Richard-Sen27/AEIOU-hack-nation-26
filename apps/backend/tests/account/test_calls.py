"""Calls: publishing (self-published or reviewed), browsing, wording check, row-level security,
rights, CLI."""

import io
import uuid

import asyncpg
import pytest
from account_helpers import assert_error

from backend import calls_cli, cli
from backend.api.ratelimit import limiter
from backend.api.services.calls import WORDING_RULES, wording_issues
from backend.config import Settings, get_settings
from backend.schemas.calls import REVIEW_BADGE, SELF_PUBLISHED_BADGE

DRAVET = "MONDO:0100135"
STXBP1 = "MONDO:9900007"

SURVEY = {
    "kind": "survey",
    "title": "Sleep in Dravet syndrome",
    "summary": "An online survey about sleep and night-time seizures.",
    "participation": "About 20 minutes online.",
    "disease_ids": [DRAVET],
    "gene_ids": ["HGNC:10585"],
    "phenotype_ids": ["HP:0001250"],
    "countries": ["DE"],
    "remote": True,
}
TRIAL = {
    **SURVEY,
    "kind": "trial",
    "title": "Observational trial in SCN1A epilepsy",
    "ethics_body": "Ethics committee X",
    "ethics_reference": "EC-2026-17",
    "registry_id": "NCT12345678",
    "external_url": "https://clinicaltrials.gov/study/NCT12345678",
    "run_by_node_id": "INST:fx-epilepsy",
}


async def make_publisher(make_user, connect_as, *, visible: bool = True, name: str = "Ada Doe"):
    user = await make_user(role="researcher")
    app = await connect_as("atlas_app")
    async with app.transaction():
        await app.execute("SELECT set_config('app.user_id', $1, true)", str(user.id))
        await app.execute(
            "UPDATE profiles SET role_verified = true, verification_method = 'orcid_simulated',"
            " verified_name = $2, card_id = gen_random_uuid(), card_visible = $3,"
            ' institutions = \'[{"node_id": null, "label": "Test Institute"}]\'::jsonb'
            " WHERE user_id = $1",
            user.id,
            name,
            visible,
        )
    return user


async def create(user, body=SURVEY):
    r = await user.client.post("/me/calls", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def submit(user, call_id):
    r = await user.client.post(f"/me/calls/{call_id}/submit")
    assert r.status_code == 200, r.text
    return r.json()


def approve(call_id, note=None):
    return calls_cli.review(call_id, "approve", "Test Operator", note, out=io.StringIO())


async def published(make_user, connect_as, body=SURVEY):
    pub = await make_publisher(make_user, connect_as)
    call = await create(pub, body)
    await submit(pub, call["id"])
    approve(call["id"])
    return pub, call


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(autouse=True)
def _review_required(monkeypatch):
    """The review flow (CALLS_REVIEW_REQUIRED=true) is the baseline of this module; the tests
    that take `self_publish` run in the default mode."""
    monkeypatch.setattr(get_settings(), "calls_review_required", True)


@pytest.fixture
def self_publish(_review_required, monkeypatch):
    monkeypatch.setattr(get_settings(), "calls_review_required", False)


async def as_user(connect_as, user_id, sql, *args):
    """Run one statement as the API role acting for `user_id` (None: no user)."""
    app = await connect_as("atlas_app")
    async with app.transaction():
        if user_id is not None:
            await app.execute("SELECT set_config('app.user_id', $1, true)", str(user_id))
        return await app.fetchval(sql, *args)


# ---- who may publish ----------------------------------------------------------------------


async def test_guest_sees_nothing(client):
    for method, path in (
        ("GET", "/calls"),
        ("GET", f"/calls/{uuid.uuid4()}"),
        ("GET", "/me/calls"),
        ("POST", "/me/calls"),
    ):
        r = await client.request(method, path, json=SURVEY if method == "POST" else None)
        assert_error(r, 401, "sign_in_required")


async def test_only_verified_visible_professionals_publish(make_user, connect_as):
    patient = await make_user()
    assert_error(await patient.client.post("/me/calls", json=SURVEY), 403, "forbidden")
    unverified = await make_user(role="doctor")
    assert_error(await unverified.client.post("/me/calls", json=SURVEY), 403, "forbidden")
    hidden = await make_publisher(make_user, connect_as, visible=False)
    assert_error(await hidden.client.post("/me/calls", json=SURVEY), 403, "forbidden")
    r = await hidden.client.get("/me/calls")
    assert r.status_code == 200 and r.json()["can_publish"] is False

    pub = await make_publisher(make_user, connect_as)
    call = await create(pub)
    assert call["status"] == "draft" and call["publisher"]["name"] == "Ada Doe"
    mine = (await pub.client.get("/me/calls")).json()
    assert mine["can_publish"] is True and [c["id"] for c in mine["items"]] == [call["id"]]


# ---- validation ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"kind": "study"}, "ethics_reference"),
        ({"kind": "trial", "ethics_reference": "EC-1"}, "registry_id"),
        ({"disease_ids": ["MONDO:0000001"]}, "disease_ids.0"),
        ({"disease_ids": ["HGNC:10585"]}, "disease_ids.0"),
        ({"gene_ids": ["HGNC:1"]}, "gene_ids.0"),
        ({"phenotype_ids": ["HP:9999999"]}, "phenotype_ids.0"),
        ({"run_by_node_id": "MONDO:0100135"}, "run_by_node_id"),
        ({"external_url": "http://example.org/study"}, "external_url"),
        ({"min_age": 18, "max_age": 10}, "max_age"),
        ({"opens_at": "2026-12-01", "closes_at": "2026-11-01"}, "closes_at"),
        ({"registry_id": "ABC123"}, "registry_id"),
        ({"title": "x" * 141}, "title"),
        ({"disease_ids": []}, "disease_ids"),
        ({"requested_fields": ["email"]}, "requested_fields.0"),
    ],
)
async def test_validation(make_user, connect_as, change, field):
    pub = await make_publisher(make_user, connect_as)
    r = await pub.client.post("/me/calls", json={**SURVEY, **change})
    assert_error(r, 422, "validation_error")
    assert field in r.json()["error"]["message"]


async def test_valid_trial(make_user, connect_as):
    pub = await make_publisher(make_user, connect_as)
    call = await create(pub, TRIAL)
    assert call["registry_url"] == "https://clinicaltrials.gov/study/NCT12345678"
    assert call["run_by_node"]["label"] == "Fixture Epilepsy Center"
    assert call["diseases"] == [{"id": DRAVET, "label": "Dravet syndrome"}]


# ---- wording check ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "A cure for Dravet syndrome",
        "Treatment available now",
        "Free medication for participants",
        "Results guaranteed",
        "Get the medication you need",
        "Buy at a reduced price",
        "Kostenlose Medikamente für alle",
        "Endlich Heilung",
    ],
)
def test_wording_rules_refuse(phrase):
    assert wording_issues({"summary": phrase})


@pytest.mark.parametrize(
    "phrase",
    [
        "There is no cure yet; we study sleep.",
        "Participants receive the study drug or placebo.",
        "Travel costs are reimbursed.",
        "Ask your doctor whether this study could apply to you.",
    ],
)
def test_wording_rules_allow(phrase):
    assert not wording_issues({"summary": phrase})


def test_wording_rules_cover_the_plan_blocklist():
    terms = {t for t, _ in WORDING_RULES}
    assert {"cure", "treatment available", "free medication", "guaranteed"} <= terms


async def test_submit_runs_the_wording_check(make_user, connect_as):
    pub = await make_publisher(make_user, connect_as)
    call = await create(pub, {**SURVEY, "summary": "Free medication and a cure, guaranteed."})
    assert {i["term"] for i in call["wording_issues"]} >= {"cure", "guaranteed", "free medication"}
    r = await pub.client.post(f"/me/calls/{call['id']}/submit")
    assert_error(r, 422, "validation_error")
    assert "summary ('cure')" in r.json()["error"]["message"]
    assert (await pub.client.get(f"/me/calls/{call['id']}")).json()["status"] == "draft"


# ---- status flow --------------------------------------------------------------------------


async def test_publish_flow_and_browse(make_user, connect_as, superuser):
    pub = await make_publisher(make_user, connect_as)
    patient = await make_user()
    call = await create(pub, TRIAL)
    assert (await patient.client.get("/calls")).json()["items"] == []
    assert_error(await patient.client.get(f"/calls/{call['id']}"), 404, "not_found")

    mine = (await pub.client.get("/me/calls")).json()
    assert mine["review_required"] is True and mine["items"][0]["review_badge"] == REVIEW_BADGE

    sent = await submit(pub, call["id"])
    assert sent["status"] == "pending_review" and sent["submitted_at"]
    assert sent["self_published"] is False
    assert (await patient.client.get("/calls")).json()["items"] == []
    # Editing a pending call takes it back to draft.
    r = await pub.client.put(f"/me/calls/{call['id']}", json={**TRIAL, "title": "New title"})
    assert r.status_code == 200 and r.json()["status"] == "draft"
    await submit(pub, call["id"])

    out = io.StringIO()
    calls_cli.pending("Test Operator", out=out)
    assert call["id"] in out.getvalue() and "wording check: clean" in out.getvalue()
    assert approve(call["id"]) == "published"

    listed = (await patient.client.get("/calls")).json()
    assert listed["heading"] == "Find trials and studies looking for participants"
    item = next(c for c in listed["items"] if c["id"] == call["id"])
    assert item["title"] == "New title" and item["publisher"]["name"] == "Ada Doe"
    assert item["publisher"]["institutions"] == [{"node_id": None, "label": "Test Institute"}]
    assert "not for scientific quality" in item["review_badge"]
    assert item["self_published"] is False
    assert "Ask your doctor" in item["notice"]
    assert "publisher_id" not in item and "status" not in item
    assert (await patient.client.get(f"/calls/{call['id']}")).json()["id"] == call["id"]
    assert (await patient.client.get("/calls?kind=survey")).json()["items"] == [] or all(
        c["kind"] == "survey"
        for c in (await patient.client.get("/calls?kind=survey")).json()["items"]
    )

    # Published calls are not edited, only closed.
    r = await pub.client.put(f"/me/calls/{call['id']}", json=TRIAL)
    assert_error(r, 409, "conflict")
    closed = (await pub.client.post(f"/me/calls/{call['id']}/close")).json()
    assert closed["status"] == "closed" and closed["closed_at"]
    assert call["id"] not in {c["id"] for c in (await patient.client.get("/calls")).json()["items"]}

    log = await superuser.fetch(
        "SELECT action, operator FROM call_reviews WHERE call_id = $1 ORDER BY created_at",
        uuid.UUID(call["id"]),
    )
    assert [r["action"] for r in log][-1] == "approved"
    assert "viewed" in {r["action"] for r in log}
    assert "self_published" not in {r["action"] for r in log}
    assert {r["operator"] for r in log} == {"Test Operator"}


# ---- self-publishing (CALLS_REVIEW_REQUIRED off, the default) ------------------------------


def test_review_is_off_by_default():
    assert Settings.model_fields["calls_review_required"].default is False


async def test_self_publish_from_the_form(self_publish, make_user, connect_as, superuser):
    pub = await make_publisher(make_user, connect_as)
    patient = await make_user()
    call = await create(pub, TRIAL)
    cid = uuid.UUID(call["id"])
    mine = (await pub.client.get("/me/calls")).json()
    assert mine["review_required"] is False
    assert mine["items"][0]["status"] == "draft"
    assert mine["items"][0]["review_badge"] == SELF_PUBLISHED_BADGE

    live = await submit(pub, call["id"])
    assert live["status"] == "published" and live["self_published"] is True
    assert live["published_at"] and live["submitted_at"] and live["reviewed_at"] is None
    assert live["review_badge"] == "Published by the expert. Not reviewed by the Amber team."
    # A second click changes nothing.
    again = await submit(pub, call["id"])
    assert again["status"] == "published" and again["published_at"] == live["published_at"]

    item = next(
        c for c in (await patient.client.get("/calls")).json()["items"] if c["id"] == call["id"]
    )
    assert item["self_published"] is True and item["review_badge"] == SELF_PUBLISHED_BADGE
    assert "Reviewed" not in item["review_badge"]
    assert item["publisher"]["name"] == "Ada Doe" and "Ask your doctor" in item["notice"]
    assert (await patient.client.get(f"/calls/{call['id']}")).json()["self_published"] is True

    # Logged, once, as a self-publication.
    log = await superuser.fetch("SELECT action, operator FROM call_reviews WHERE call_id = $1", cid)
    assert [(r["action"], r["operator"]) for r in log] == [("self_published", "publisher")]
    export = (await pub.client.get("/me/export")).json()
    assert [r["action"] for r in export["call_reviews"]] == ["self_published"]
    assert export["calls"][0]["self_published"] is True

    # Published content stays frozen: not through the API, not for the API role in the database.
    assert_error(await pub.client.put(f"/me/calls/{call['id']}", json=TRIAL), 409, "conflict")
    for sql in (
        "UPDATE calls SET summary = 'Free medication' WHERE id = $1",
        "UPDATE calls SET self_published = false WHERE id = $1",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await as_user(connect_as, pub.id, sql, cid)
    closed = (await pub.client.post(f"/me/calls/{call['id']}/close")).json()
    assert closed["status"] == "closed" and closed["review_badge"] == SELF_PUBLISHED_BADGE
    assert_error(await pub.client.post(f"/me/calls/{call['id']}/submit"), 409, "conflict")


async def test_self_publish_runs_the_wording_check(self_publish, make_user, connect_as):
    pub = await make_publisher(make_user, connect_as)
    call = await create(pub, {**SURVEY, "summary": "Free medication and a cure, guaranteed."})
    r = await pub.client.post(f"/me/calls/{call['id']}/submit")
    assert_error(r, 422, "validation_error")
    assert "summary ('cure')" in r.json()["error"]["message"]
    assert (await pub.client.get(f"/me/calls/{call['id']}")).json()["status"] == "draft"
    reader = await make_user()
    assert call["id"] not in {c["id"] for c in (await reader.client.get("/calls")).json()["items"]}


async def test_self_publish_only_for_the_owner_with_a_visible_card(
    self_publish, make_user, connect_as, superuser
):
    pub = await make_publisher(make_user, connect_as)
    call = await create(pub)
    cid = uuid.UUID(call["id"])
    publish = "SELECT publish_own_call($1)"

    # Another publisher: not through the API, not through the function.
    other = await make_publisher(make_user, connect_as, name="Bo Roe")
    assert_error(await other.client.post(f"/me/calls/{call['id']}/submit"), 404, "not_found")
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="no such call"):
        await as_user(connect_as, other.id, publish, cid)
    # No user at all.
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await as_user(connect_as, None, publish, cid)
    # A patient, even one who owns a call row, has no card.
    patient = await make_user()
    assert_error(await patient.client.post(f"/me/calls/{call['id']}/submit"), 403, "forbidden")
    theirs = await superuser.fetchval(
        "INSERT INTO calls (publisher_id, kind, title, summary, participation, disease_ids)"
        " VALUES ($1, 'survey', 't', 's', 'p', ARRAY['MONDO:0100135']) RETURNING id",
        patient.id,
    )
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="visible card"):
        await as_user(connect_as, patient.id, publish, theirs)

    # The owner, once their card is hidden.
    await as_user(
        connect_as,
        pub.id,
        "UPDATE profiles SET card_visible = false WHERE user_id = $1 RETURNING 1",
        pub.id,
    )
    assert_error(await pub.client.post(f"/me/calls/{call['id']}/submit"), 403, "forbidden")
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="visible card"):
        await as_user(connect_as, pub.id, publish, cid)
    assert await superuser.fetchval("SELECT status FROM calls WHERE id = $1", cid) == "draft"
    assert (
        await superuser.fetchval("SELECT count(*) FROM call_reviews WHERE call_id = $1", cid) == 0
    )

    # With the card back, the owner publishes; the function refuses a second run.
    await as_user(
        connect_as,
        pub.id,
        "UPDATE profiles SET card_visible = true WHERE user_id = $1 RETURNING 1",
        pub.id,
    )
    assert (await submit(pub, call["id"]))["status"] == "published"
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="status published"):
        await as_user(connect_as, pub.id, publish, cid)


async def test_self_publish_after_a_review_decision(make_user, connect_as, monkeypatch):
    """Calls left over from review mode: a pending one can be published by its owner, a rejected
    one only after it was edited."""
    pub = await make_publisher(make_user, connect_as)
    pending = await create(pub)
    rejected = await create(pub, {**SURVEY, "title": "Rejected one"})
    for call in (pending, rejected):
        assert (await submit(pub, call["id"]))["status"] == "pending_review"
    calls_cli.review(rejected["id"], "reject", "Op", "Add the ethics body.", out=io.StringIO())

    monkeypatch.setattr(get_settings(), "calls_review_required", False)
    assert (await submit(pub, pending["id"]))["status"] == "published"
    assert_error(await pub.client.post(f"/me/calls/{rejected['id']}/submit"), 409, "conflict")
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="status rejected"):
        await as_user(connect_as, pub.id, "SELECT publish_own_call($1)", uuid.UUID(rejected["id"]))
    r = await pub.client.put(f"/me/calls/{rejected['id']}", json={**SURVEY, "title": "Edited"})
    assert r.status_code == 200 and r.json()["status"] == "draft"
    live = await submit(pub, rejected["id"])
    assert live["status"] == "published" and live["self_published"] is True
    assert live["review_note"] is None


async def test_reject_and_resubmit(make_user, connect_as):
    pub = await make_publisher(make_user, connect_as)
    call = await create(pub)
    await submit(pub, call["id"])
    with pytest.raises(SystemExit, match="needs --note"):
        calls_cli.review(call["id"], "reject", "Op", None, out=io.StringIO())
    assert calls_cli.review(call["id"], "reject", "Op", "Add the ethics body.") == "rejected"
    mine = (await pub.client.get(f"/me/calls/{call['id']}")).json()
    assert mine["status"] == "rejected" and mine["review_note"] == "Add the ethics body."
    assert (await submit(pub, call["id"]))["status"] == "pending_review"
    with pytest.raises(SystemExit, match="waiting for review"):
        approve(str(uuid.uuid4()))
    with pytest.raises(SystemExit, match="refused: no such call"):
        calls_cli.review(str(uuid.uuid4()), "reject", "Op", "x", out=io.StringIO())


async def test_approve_refuses_wording_and_hidden_publisher(make_user, connect_as):
    pub = await make_publisher(make_user, connect_as)
    call = await create(pub)
    await submit(pub, call["id"])
    app = await connect_as("atlas_app")
    async with app.transaction():
        await app.execute("SELECT set_config('app.user_id', $1, true)", str(pub.id))
        await app.execute("UPDATE profiles SET card_visible = false WHERE user_id = $1", pub.id)
    with pytest.raises(SystemExit, match="verified, visible card"):
        approve(call["id"])


async def test_close_withdraws_unpublished_and_delete(make_user, connect_as):
    pub = await make_publisher(make_user, connect_as)
    call = await create(pub)
    r = await pub.client.post(f"/me/calls/{call['id']}/close")
    assert r.json()["status"] == "withdrawn"
    assert_error(await pub.client.post(f"/me/calls/{call['id']}/submit"), 409, "conflict")
    assert (await pub.client.delete(f"/me/calls/{call['id']}")).status_code == 204
    assert_error(await pub.client.get(f"/me/calls/{call['id']}"), 404, "not_found")


async def test_hidden_card_hides_published_calls(make_user, connect_as):
    pub, call = await published(make_user, connect_as)
    reader = await make_user()
    assert call["id"] in {c["id"] for c in (await reader.client.get("/calls")).json()["items"]}
    app = await connect_as("atlas_app")
    async with app.transaction():
        await app.execute("SELECT set_config('app.user_id', $1, true)", str(pub.id))
        await app.execute("UPDATE profiles SET card_visible = false WHERE user_id = $1", pub.id)
    assert call["id"] not in {c["id"] for c in (await reader.client.get("/calls")).json()["items"]}


async def test_open_call_limit(make_user, connect_as, superuser):
    pub = await make_publisher(make_user, connect_as)
    for _ in range(10):
        await superuser.execute(
            "INSERT INTO calls (publisher_id, kind, title, summary, participation, disease_ids)"
            " VALUES ($1, 'survey', 't', 's', 'p', ARRAY['MONDO:0100135'])",
            pub.id,
        )
    assert_error(await pub.client.post("/me/calls", json=SURVEY), 409, "conflict")


async def test_create_is_rate_limited(make_user, connect_as, superuser):
    pub = await make_publisher(make_user, connect_as)
    codes = []
    for _ in range(21):
        r = await pub.client.post("/me/calls", json=SURVEY)
        codes.append(r.status_code)
        await superuser.execute("DELETE FROM calls WHERE publisher_id = $1", pub.id)
    assert codes[:20] == [201] * 20 and codes[20] == 429


# ---- row-level security -------------------------------------------------------------------


async def test_rls(make_user, connect_as):
    pub, published_call = await published(make_user, connect_as)
    draft = await create(pub, {**SURVEY, "title": "Still a draft"})
    other = await make_user()
    app = await connect_as("atlas_app")
    pid, did = uuid.UUID(published_call["id"]), uuid.UUID(draft["id"])

    # Guests (no app.user_id) see no calls at all, not even published ones.
    assert await app.fetchval("SELECT count(*) FROM calls WHERE id = $1", pid) == 0
    assert await app.fetchval("SELECT count(*) FROM call_publisher_cards()") == 0

    async with app.transaction():
        await app.execute("SELECT set_config('app.user_id', $1, true)", str(other.id))
        assert await app.fetchval("SELECT count(*) FROM calls WHERE id = $1", pid) == 1
        assert await app.fetchval("SELECT count(*) FROM calls WHERE id = $1", did) == 0
        assert (await app.execute("UPDATE calls SET title = 'x' WHERE id = $1", pid)) == "UPDATE 0"
        assert (await app.execute("DELETE FROM calls WHERE id = $1", pid)) == "DELETE 0"
        assert await app.fetchval("SELECT count(*) FROM call_reviews") == 0
    # Through the API: another user's call is never theirs.
    assert_error(await other.client.get(f"/me/calls/{did}"), 404, "not_found")
    assert_error(await other.client.post(f"/me/calls/{pid}/close"), 404, "not_found")
    assert_error(await other.client.delete(f"/me/calls/{pid}"), 404, "not_found")
    r = await other.client.put(f"/me/calls/{did}", json=SURVEY)
    assert r.status_code in (403, 404)


async def test_database_refuses_self_publishing(make_user, connect_as):
    pub = await make_publisher(make_user, connect_as)
    call = await create(pub)
    app = await connect_as("atlas_app")
    for sql in (
        "UPDATE calls SET status = 'published' WHERE id = $1",
        "UPDATE calls SET review_note = 'ok' WHERE id = $1",
        "UPDATE calls SET demo = true WHERE id = $1",
        "UPDATE calls SET self_published = true WHERE id = $1",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with app.transaction():
                await app.execute("SELECT set_config('app.user_id', $1, true)", str(pub.id))
                await app.execute(sql, uuid.UUID(call["id"]))
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app.transaction():
            await app.execute("SELECT set_config('app.user_id', $1, true)", str(pub.id))
            await app.execute(
                "INSERT INTO calls (publisher_id, kind, title, summary, participation,"
                " disease_ids, status) VALUES ($1, 'survey', 't', 's', 'p',"
                " ARRAY['MONDO:0100135'], 'published')",
                pub.id,
            )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await as_user(
            connect_as,
            pub.id,
            "INSERT INTO calls (publisher_id, kind, title, summary, participation, disease_ids,"
            " self_published) VALUES ($1, 'survey', 't', 's', 'p', ARRAY['MONDO:0100135'], true)"
            " RETURNING id",
            pub.id,
        )
    for fn in ("pending_calls('x')", f"review_call('{call['id']}', 'approve', null, 'x')"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app.fetch(f"SELECT * FROM {fn}")
    # A published call's content cannot be changed by the API role either.
    await submit(pub, call["id"])
    approve(call["id"])
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app.transaction():
            await app.execute("SELECT set_config('app.user_id', $1, true)", str(pub.id))
            await app.execute(
                "UPDATE calls SET summary = 'Free medication' WHERE id = $1", uuid.UUID(call["id"])
            )


async def test_call_reviews_table_is_forced_rls(superuser):
    row = await superuser.fetchrow(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'call_reviews'"
    )
    assert tuple(row) == (True, True)


# ---- data rights --------------------------------------------------------------------------


async def test_export_role_switch_and_deletion(make_user, connect_as, superuser):
    pub, call = await published(make_user, connect_as)
    draft = await create(pub, {**SURVEY, "title": "Draft"})
    export = (await pub.client.get("/me/export")).json()
    assert {c["id"] for c in export["calls"]} == {call["id"], draft["id"]}
    assert "approved" in {r["action"] for r in export["call_reviews"]}

    r = await pub.client.patch("/me/settings", json={"role": "patient"})
    assert r.status_code == 200, r.text
    rows = await superuser.fetch("SELECT id, status FROM calls WHERE publisher_id = $1", pub.id)
    assert {str(r["id"]): r["status"] for r in rows} == {
        call["id"]: "closed",
        draft["id"]: "withdrawn",
    }

    assert (await pub.client.delete("/me")).status_code == 204
    for table in ("calls", "call_reviews"):
        n = await superuser.fetchval(
            f"SELECT count(*) FROM {table} WHERE publisher_id = $1", pub.id
        )
        assert n == 0, table


# ---- demo seed ----------------------------------------------------------------------------


def test_demo_seed_refuses_outside_local(monkeypatch):
    from backend.config import get_settings

    monkeypatch.setattr(get_settings(), "api_url", "https://amber.example.org")
    with pytest.raises(SystemExit, match="refusing"):
        calls_cli.demo_calls(out=io.StringIO())


def test_demo_help_says_demo(capsys):
    with pytest.raises(SystemExit):
        cli.main(["demo-calls", "--help"])
    assert "DEMO DATA" in capsys.readouterr().out


async def test_demo_seed_is_labelled_and_listed(make_user, superuser):
    ids = calls_cli.demo_calls(out=io.StringIO())
    assert len(ids) >= 2
    reader = await make_user()
    items = {c["id"]: c for c in (await reader.client.get("/calls")).json()["items"]}
    for call_id in ids:
        call = items[call_id]
        assert call["demo"] is True and call["title"].startswith("Demo:")
        assert not wording_issues(call)
        assert call["publisher"]["verification"]["simulated"] is True
    assert {d["id"] for c in ids for d in items[c]["diseases"]} >= {DRAVET, STXBP1}
    calls_cli.demo_calls(clear=True, out=io.StringIO())
    n = await superuser.fetchval(
        "SELECT count(*) FROM calls WHERE id = ANY($1::uuid[])", [uuid.UUID(i) for i in ids]
    )
    assert n == 0
