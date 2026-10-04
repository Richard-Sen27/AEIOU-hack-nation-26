"""Followed diseases and in-app notifications: /me/follows*, /notifications*, rights, demo CLI."""

import io
import uuid

import pytest
from account_helpers import assert_error

from backend import cli
from backend.api.services import follows as follows_service
from backend.api.services.graph import get_graph
from backend.schemas.follows import MAX_FOLLOWS

DRAVET = "MONDO:0100135"
STXBP1 = "MONDO:9900007"
TRIAL = "NCT99000001"  # recruiting, studies Dravet
PAPER = "PMID:FX0003"  # 2022, about Dravet
ORG = "ORG:fx-dravet-families"


async def follow(user, node_id: str = DRAVET):
    return await user.client.put("/me/follows", json={"node_id": node_id})


async def add_change(
    su,
    node_id: str,
    node_type: str,
    change: str = "added",
    disease_id: str = DRAVET,
    version: str | None = None,
    age: str | None = None,
) -> str:
    """Insert a graph_changes row like the pipeline does (as the superuser)."""
    version = version or f"v-{uuid.uuid4().hex[:8]}"
    await su.execute(
        "INSERT INTO graph_changes (data_version, previous_version, disease_id, node_id,"
        " node_type, change, created_at) VALUES ($1, 'fixture', $2, $3, $4, $5,"
        " CASE WHEN $6::text IS NULL THEN clock_timestamp() ELSE now() - $6::text::interval END)",
        version,
        disease_id,
        node_id,
        node_type,
        change,
        age,
    )
    return version


async def notifications(user) -> dict:
    r = await user.client.get("/notifications")
    assert r.status_code == 200, r.text
    return r.json()


async def count(user) -> int:
    r = await user.client.get("/notifications/unread-count")
    assert r.status_code == 200, r.text
    return r.json()["count"]


# ---- access and consent -------------------------------------------------------------------


async def test_guest_needs_sign_in(client):
    for method, path, body in (
        ("GET", "/me/follows", None),
        ("PUT", "/me/follows", {"node_id": DRAVET}),
        ("DELETE", "/me/follows", {"node_id": DRAVET}),
        ("POST", "/me/follows/from-profile", None),
        ("GET", "/notifications", None),
        ("GET", "/notifications/unread-count", None),
        ("POST", "/notifications/read", {"all": True}),
    ):
        r = await client.request(method, path, json=body)
        assert_error(r, 401, "sign_in_required")


async def test_following_needs_health_data_consent(make_user):
    user = await make_user()
    assert_error(await follow(user), 403, "consent_required")
    assert_error(await user.client.post("/me/follows/from-profile"), 403, "consent_required")
    # Reading and deleting one's own data never needs the consent.
    assert (await user.client.get("/me/follows")).json()["items"] == []
    r = await user.client.request("DELETE", "/me/follows", json={"node_id": DRAVET})
    assert r.status_code == 204
    assert await count(user) == 0


async def test_only_atlas_diseases(make_user):
    user = await make_user(consents=["health_data"])
    assert_error(await follow(user, "HGNC:11444"), 422, "validation_error")
    assert_error(await follow(user, "MONDO:0000001"), 404, "not_found")
    assert_error(await follow(user, "MONDO:0100135 "), 422, "validation_error")
    r = await user.client.put("/me/follows", json={"node_id": DRAVET, "extra": 1})
    assert_error(r, 422, "validation_error")
    assert (await user.client.get("/me/follows")).json()["items"] == []


# ---- follows ------------------------------------------------------------------------------


async def test_follow_list_unfollow(make_user, monkeypatch):
    user = await make_user(consents=["health_data"])
    r = await follow(user)
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["node_id"] == DRAVET
    assert first["label"] == "Dravet syndrome"
    assert first["in_atlas"] is True and first["updates_available"] is True
    assert first["since_version"] == "fixture"
    assert (await follow(user)).json() == first  # idempotent
    assert (await follow(user, STXBP1)).status_code == 200

    # A core disease (attrs.tier = "core") can be followed but has no updates.
    monkeypatch.setitem(get_graph().nodes[STXBP1].attrs, "tier", "core")
    data = (await user.client.get("/me/follows")).json()
    assert data["limit"] == MAX_FOLLOWS
    assert [f["node_id"] for f in data["items"]] == [STXBP1, DRAVET]
    assert [f["updates_available"] for f in data["items"]] == [False, True]

    r = await user.client.request("DELETE", "/me/follows", json={"node_id": DRAVET})
    assert r.status_code == 204
    assert [f["node_id"] for f in (await user.client.get("/me/follows")).json()["items"]] == [
        STXBP1
    ]


async def test_follow_that_left_the_atlas(make_user, connect_as):
    user = await make_user(consents=["health_data"])
    app = await connect_as("atlas_app")
    async with app.transaction():
        await app.execute("SELECT set_config('app.user_id', $1, true)", str(user.id))
        await app.execute(
            "INSERT INTO follows (user_id, node_id) VALUES ($1, 'MONDO:0000002')", user.id
        )
    (item,) = (await user.client.get("/me/follows")).json()["items"]
    assert item == {**item, "label": None, "in_atlas": False, "updates_available": False}


async def test_limit_of_50(make_user, connect_as):
    user = await make_user(consents=["health_data"])
    assert (await follow(user)).status_code == 200
    app = await connect_as("atlas_app")
    async with app.transaction():
        await app.execute("SELECT set_config('app.user_id', $1, true)", str(user.id))
        for i in range(MAX_FOLLOWS - 1):
            await app.execute(
                "INSERT INTO follows (user_id, node_id) VALUES ($1, $2)",
                user.id,
                f"MONDO:{8000000 + i:07d}",
            )
    assert_error(await follow(user, STXBP1), 409, "conflict")
    assert (await follow(user)).status_code == 200  # already followed: still fine
    assert len((await user.client.get("/me/follows")).json()["items"]) == MAX_FOLLOWS


async def test_follow_from_profile(make_user):
    user = await make_user(consents=["health_data"])
    profile = {
        "updated_at": None,
        "diseases": [
            {"id": DRAVET, "label": "Dravet syndrome", "source": "manual"},
            {"id": "MONDO:0000003", "label": "Not in the atlas", "source": "chat"},
            {"id": STXBP1, "label": "STXBP1 encephalopathy", "source": "document"},
        ],
    }
    assert (await user.client.put("/profile", json=profile)).status_code == 200
    assert (await follow(user, STXBP1)).status_code == 200
    r = await user.client.post("/me/follows/from-profile")
    assert r.status_code == 200, r.text
    result = r.json()
    assert [f["node_id"] for f in result["added"]] == [DRAVET]
    assert result["added"][0]["label"] == "Dravet syndrome"
    assert result["already_following"] == [STXBP1]
    assert result["not_in_atlas"] == ["MONDO:0000003"]
    assert result["limit_reached"] is False
    again = (await user.client.post("/me/follows/from-profile")).json()
    assert again["added"] == [] and sorted(again["already_following"]) == [DRAVET, STXBP1]


async def test_follow_from_profile_respects_the_limit(make_user, connect_as):
    user = await make_user(consents=["health_data"])
    profile = {
        "updated_at": None,
        "diseases": [{"id": DRAVET, "label": "Dravet syndrome", "source": "manual"}],
    }
    assert (await user.client.put("/profile", json=profile)).status_code == 200
    app = await connect_as("atlas_app")
    async with app.transaction():
        await app.execute("SELECT set_config('app.user_id', $1, true)", str(user.id))
        for i in range(MAX_FOLLOWS):
            await app.execute(
                "INSERT INTO follows (user_id, node_id) VALUES ($1, $2)",
                user.id,
                f"MONDO:{8100000 + i:07d}",
            )
    result = (await user.client.post("/me/follows/from-profile")).json()
    assert result["added"] == [] and result["limit_reached"] is True


# ---- lazy fill ----------------------------------------------------------------------------


async def test_lazy_fill_resolves_labels(make_user, superuser):
    user = await make_user(consents=["health_data"])
    assert (await follow(user)).status_code == 200
    await add_change(superuser, TRIAL, "trial", "added", age="1 hour")  # older than the follow
    await add_change(superuser, PAPER, "paper", "added", version="fixture")  # live at follow
    assert await count(user) == 0

    version = await add_change(superuser, TRIAL, "trial", "now_recruiting")
    await add_change(superuser, TRIAL, "trial", "added", version=version)
    await add_change(superuser, PAPER, "paper", "added", version=version)
    await add_change(superuser, ORG, "patient_org", "added", version=version)
    await add_change(superuser, "PMID:FX0002", "paper", "added", disease_id=STXBP1)  # unfollowed

    data = await notifications(user)
    assert data["unread_count"] == 4
    by_key = {(n["kind"], n["item_id"]): n for n in data["items"]}
    assert set(by_key) == {
        ("now_recruiting", TRIAL),
        ("added", TRIAL),
        ("added", PAPER),
        ("added", ORG),
    }
    recruiting = by_key[("now_recruiting", TRIAL)]
    assert recruiting["disease_id"] == DRAVET
    assert recruiting["disease_label"] == "Dravet syndrome"
    assert recruiting["item_type"] == "trial"
    assert recruiting["item_label"].startswith("Fixture interventional study")
    assert recruiting["registry_id"] == TRIAL
    assert recruiting["year"] is None and recruiting["gone"] is False
    assert recruiting["data_version"] == version and recruiting["read_at"] is None
    paper = by_key[("added", PAPER)]
    assert paper["item_type"] == "paper" and paper["year"] == 2022
    assert paper["registry_id"] is None
    assert by_key[("added", ORG)]["item_type"] == "patient_org"

    # Dedupe: reading again creates nothing new.
    again = await notifications(user)
    assert sorted(n["id"] for n in again["items"]) == sorted(n["id"] for n in data["items"])
    assert await count(user) == 4


async def test_unread_count_fills_once_per_change(make_user, superuser, monkeypatch):
    user = await make_user(consents=["health_data"])
    assert (await follow(user)).status_code == 200
    calls: list[object] = []
    original = follows_service._fill

    async def spy(db, user_id, marker):
        if user_id == user.id:
            calls.append(marker)
        await original(db, user_id, marker)

    monkeypatch.setattr(follows_service, "_fill", spy)
    await add_change(superuser, PAPER, "paper")
    assert await count(user) == 1
    assert await count(user) == 1
    assert await count(user) == 1
    assert len(calls) == 1
    await add_change(superuser, TRIAL, "trial", "now_recruiting")
    assert await count(user) == 2
    assert len(calls) == 2


async def test_node_that_left_the_graph(make_user, superuser):
    user = await make_user(consents=["health_data"])
    assert (await follow(user)).status_code == 200
    await add_change(superuser, "PMID:GONE0001", "paper")
    (item,) = (await notifications(user))["items"]
    assert item["gone"] is True
    assert item["item_id"] == "PMID:GONE0001"
    assert item["item_label"] is None and item["item_type"] is None and item["year"] is None
    assert item["disease_label"] == "Dravet syndrome"


async def test_unfollow_deletes_its_notifications(make_user, superuser):
    user = await make_user(consents=["health_data"])
    assert (await follow(user)).status_code == 200
    await add_change(superuser, PAPER, "paper")
    assert await count(user) == 1
    r = await user.client.request("DELETE", "/me/follows", json={"node_id": DRAVET})
    assert r.status_code == 204
    assert (await notifications(user))["items"] == []


async def test_purge_after_90_days(make_user, connect_as, superuser):
    user = await make_user(consents=["health_data"])
    app = await connect_as("atlas_app")
    async with app.transaction():
        await app.execute("SELECT set_config('app.user_id', $1, true)", str(user.id))
        for key, age in (("old", "91 days"), ("recent", "89 days")):
            await app.execute(
                "INSERT INTO notifications (user_id, kind, ref_id, subject_node_id, dedupe_key,"
                " created_at) VALUES ($1, 'added', $2, $3, $4, now() - $5::text::interval)",
                user.id,
                PAPER,
                DRAVET,
                key,
                age,
            )
    assert await count(user) == 1
    assert len((await notifications(user))["items"]) == 1
    left = await superuser.fetch("SELECT dedupe_key FROM notifications WHERE user_id = $1", user.id)
    assert [r["dedupe_key"] for r in left] == ["recent"]


async def test_mark_read(make_user, superuser):
    user = await make_user(consents=["health_data"])
    other = await make_user(consents=["health_data"])
    for u in (user, other):
        assert (await follow(u)).status_code == 200
    version = await add_change(superuser, PAPER, "paper")
    await add_change(superuser, TRIAL, "trial", version=version)
    await add_change(superuser, ORG, "patient_org", version=version)
    items = (await notifications(user))["items"]
    assert len(items) == 3
    theirs = (await notifications(other))["items"]

    for body in ({}, {"ids": [items[0]["id"]], "all": True}, {"all": False}):
        assert_error(
            await user.client.post("/notifications/read", json=body), 422, "validation_error"
        )

    r = await user.client.post("/notifications/read", json={"ids": [items[0]["id"]]})
    assert r.status_code == 200 and r.json() == {"count": 2}
    read = {n["id"]: n["read_at"] for n in (await notifications(user))["items"]}
    assert read[items[0]["id"]] is not None

    # Another user's ids change nothing for them.
    r = await user.client.post("/notifications/read", json={"ids": [n["id"] for n in theirs]})
    assert r.json() == {"count": 2}
    assert await count(other) == 3

    r = await user.client.post("/notifications/read", json={"all": True})
    assert r.json() == {"count": 0}
    assert await count(user) == 0
    assert await count(other) == 3


async def test_users_never_see_each_other(make_user, superuser):
    a = await make_user(consents=["health_data"])
    b = await make_user(consents=["health_data"])
    assert (await follow(a)).status_code == 200
    await add_change(superuser, PAPER, "paper")
    assert await count(a) == 1
    assert (await b.client.get("/me/follows")).json()["items"] == []
    assert (await notifications(b))["items"] == []
    assert await count(b) == 0
    r = await b.client.request("DELETE", "/me/follows", json={"node_id": DRAVET})
    assert r.status_code == 204
    assert len((await a.client.get("/me/follows")).json()["items"]) == 1
    assert await count(a) == 1


# ---- consent withdrawal, export, deletion -------------------------------------------------


async def test_withdrawing_health_data_deletes_follows_and_notifications(make_user, superuser):
    user = await make_user(consents=["health_data"])
    assert (await follow(user)).status_code == 200
    await add_change(superuser, PAPER, "paper")
    assert await count(user) == 1
    assert (await user.client.delete("/consents/health_data")).status_code == 204
    for table in ("follows", "notifications"):
        n = await superuser.fetchval(f"SELECT count(*) FROM {table} WHERE user_id = $1", user.id)
        assert n == 0, table
    assert (await user.client.get("/me/follows")).json()["items"] == []
    assert await count(user) == 0


async def test_export_includes_follows_and_notifications(make_user, superuser):
    user = await make_user(consents=["health_data"])
    assert (await follow(user)).status_code == 200
    version = await add_change(superuser, PAPER, "paper")
    assert await count(user) == 1
    data = (await user.client.get("/me/export")).json()
    assert [f["node_id"] for f in data["follows"]] == [DRAVET]
    (n,) = data["notifications"]
    assert n["kind"] == "added" and n["ref_id"] == PAPER
    assert n["subject_node_id"] == DRAVET and n["data_version"] == version
    other = await make_user()
    data = (await other.client.get("/me/export")).json()
    assert data["follows"] == [] and data["notifications"] == []


async def test_account_deletion_removes_both(make_user, superuser):
    user = await make_user(consents=["health_data"])
    other = await make_user(consents=["health_data"])
    for u in (user, other):
        assert (await follow(u)).status_code == 200
    await add_change(superuser, PAPER, "paper")
    assert await count(user) == 1 and await count(other) == 1
    assert (await user.client.delete("/me")).status_code == 204
    for table in ("follows", "notifications"):
        assert (
            await superuser.fetchval(f"SELECT count(*) FROM {table} WHERE user_id = $1", user.id)
            == 0
        ), table
        assert (
            await superuser.fetchval(f"SELECT count(*) FROM {table} WHERE user_id = $1", other.id)
            == 1
        ), table


# ---- demo command -------------------------------------------------------------------------


def _settings_with(**changes):
    from backend.config import get_settings

    return get_settings().model_copy(update=changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"api_url": "https://api.amber.example"},
        {"pipeline_database_url": "postgresql://atlas_pipeline:x@db.amber.example:5432/atlas"},
    ],
)
def test_demo_command_refuses_outside_loopback(monkeypatch, changes):
    from backend import config

    settings = _settings_with(**changes)
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    with pytest.raises(SystemExit, match="refusing"):
        cli.demo_graph_changes(DRAVET, out=io.StringIO())
    with pytest.raises(SystemExit, match="refusing"):
        cli.demo_graph_changes("", clear=True, out=io.StringIO())


def test_demo_command_help_says_demo(capsys):
    with pytest.raises(SystemExit):
        cli.main(["demo-graph-changes", "--help"])
    assert "DEMO DATA" in capsys.readouterr().out


async def test_demo_command_produces_notifications(make_user, superuser):
    user = await make_user(consents=["health_data"])
    assert (await follow(user)).status_code == 200
    out = io.StringIO()
    rows = cli.demo_graph_changes(DRAVET, out=out)
    assert "DEMO DATA" in out.getvalue()
    assert {(r["change"], r["node_type"]) for r in rows} == {
        ("added", "trial"),
        ("added", "paper"),
        ("added", "patient_org"),
        ("now_recruiting", "trial"),
    }
    stored = await superuser.fetch(
        "SELECT data_version, previous_version FROM graph_changes WHERE data_version LIKE 'demo-%'"
    )
    assert stored and all(r["previous_version"] == "fixture" for r in stored)
    data = await notifications(user)
    assert data["unread_count"] == 4
    assert all(n["data_version"].startswith("demo-") for n in data["items"])

    with pytest.raises(SystemExit, match="no such disease"):
        cli.demo_graph_changes("MONDO:0000004", out=io.StringIO())
    cli.demo_graph_changes("", clear=True, out=out)
    assert (
        await superuser.fetchval(
            "SELECT count(*) FROM graph_changes WHERE data_version LIKE 'demo-%'"
        )
        == 0
    )
    # Notifications already made stay; labels still resolve from the graph.
    items = (await notifications(user))["items"]
    assert [n["disease_label"] for n in items] == ["Dravet syndrome"] * 4
