"""Notifications for followers when a call (survey, study, trial) is published for a followed
disease: kind call_published, filled lazily in the follower's own transaction."""

import io
import json

import pytest

from backend import calls_cli
from backend.api.ratelimit import limiter
from backend.api.services import follows as follows_service
from backend.config import get_settings
from backend.schemas.account import CONSENT_TEXT_VERSIONS
from backend.schemas.enums import ConsentType

DRAVET = "MONDO:0100135"
STXBP1 = "MONDO:9900007"
SCN1A = "HGNC:10585"
NOW = "2026-10-01T10:00:00+00:00"

SURVEY = {
    "kind": "survey",
    "title": "Sleep in Dravet syndrome",
    "summary": "An online survey about sleep and night-time seizures.",
    "participation": "About 20 minutes online.",
    "disease_ids": [DRAVET],
    "remote": True,
    "requested_fields": ["diagnosis", "age_range"],
}


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()
    yield
    limiter.reset()


async def make_publisher(make_user, superuser, *, consents=()):
    pub = await make_user(role="researcher", consents=list(consents))
    await superuser.execute(
        "UPDATE profiles SET role_verified = true, verification_method = 'orcid_simulated',"
        " verified_name = 'Ada Doe', card_id = gen_random_uuid(), card_visible = true,"
        ' institutions = \'[{"node_id": null, "label": "Test Institute"}]\'::jsonb'
        " WHERE user_id = $1",
        pub.id,
    )
    return pub


async def create(pub, **changes) -> str:
    r = await pub.client.post("/me/calls", json={**SURVEY, **changes})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def publish(pub, **changes) -> str:
    call_id = await create(pub, **changes)
    r = await pub.client.post(f"/me/calls/{call_id}/submit")
    assert r.status_code == 200 and r.json()["status"] == "published", r.text
    return call_id


async def follower(make_user, *diseases):
    user = await make_user(consents=["health_data"])
    for d in diseases or (DRAVET,):
        assert (await user.client.put("/me/follows", json={"node_id": d})).status_code == 200
    return user


async def notes(user, kind="call_published") -> list[dict]:
    r = await user.client.get("/notifications")
    assert r.status_code == 200, r.text
    return [n for n in r.json()["items"] if n["kind"] == kind]


async def count(user) -> int:
    r = await user.client.get("/notifications/unread-count")
    assert r.status_code == 200, r.text
    return r.json()["count"]


async def rows(superuser, user, kind="call_published") -> int:
    return await superuser.fetchval(
        "SELECT count(*) FROM notifications WHERE user_id = $1 AND kind = $2", user.id, kind
    )


async def test_follower_is_notified_when_a_call_is_self_published(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    fan = await follower(make_user)
    call_id = await publish(pub)
    assert await count(fan) == 1
    (n,) = await notes(fan)
    assert n["call_id"] == call_id and n["item_id"] == call_id
    assert n["item_label"] == SURVEY["title"]
    assert n["disease_id"] == DRAVET and n["disease_label"] == "Dravet syndrome"
    assert n["gone"] is False and n["read_at"] is None
    # No text is stored: the title is looked up when read.
    stored = await superuser.fetchrow(
        "SELECT ref_id, subject_node_id, dedupe_key FROM notifications WHERE user_id = $1", fan.id
    )
    assert dict(stored) == {
        "ref_id": call_id,
        "subject_node_id": DRAVET,
        "dedupe_key": f"call|{call_id}",
    }


async def test_follower_is_notified_when_the_operator_approves(make_user, superuser, monkeypatch):
    monkeypatch.setattr(get_settings(), "calls_review_required", True)
    pub = await make_publisher(make_user, superuser)
    fan = await follower(make_user)
    call_id = await create(pub)
    r = await pub.client.post(f"/me/calls/{call_id}/submit")
    assert r.json()["status"] == "pending_review"
    assert await count(fan) == 0
    calls_cli.review(call_id, "approve", "Test Operator", None, out=io.StringIO())
    assert await count(fan) == 1
    assert [n["call_id"] for n in await notes(fan)] == [call_id]


async def test_nothing_for_calls_published_before_the_follow(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    await publish(pub)
    fan = await follower(make_user)
    assert await count(fan) == 0
    assert await notes(fan) == []


async def test_nothing_for_the_publishers_own_call(make_user, superuser):
    pub = await make_publisher(make_user, superuser, consents=["health_data"])
    assert (await pub.client.put("/me/follows", json={"node_id": DRAVET})).status_code == 200
    await publish(pub)
    assert await count(pub) == 0
    assert await notes(pub) == []


async def test_nothing_for_unlisted_calls(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    fan = await follower(make_user)
    # A draft, an expired call and a call whose publisher's card is hidden are not listed.
    await create(pub, title="Draft about Dravet")
    expired = await publish(pub, title="Expired survey")
    async with superuser.transaction():
        await superuser.execute("SET LOCAL session_replication_role = replica")  # calls_guard
        await superuser.execute(
            "UPDATE calls SET closes_at = current_date - 1 WHERE id = $1", expired
        )
    hidden_pub = await make_publisher(make_user, superuser)
    await publish(hidden_pub, title="Hidden publisher")
    await superuser.execute(
        "UPDATE profiles SET card_visible = false WHERE user_id = $1", hidden_pub.id
    )
    closed = await publish(pub, title="Closed at once")
    assert (await pub.client.post(f"/me/calls/{closed}/close")).status_code == 200
    # Not about a followed disease.
    await publish(pub, title="Another disease", disease_ids=[STXBP1])
    assert await notes(fan) == []
    assert await count(fan) == 0


async def test_one_per_call_even_for_several_followed_diseases(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    fan = await follower(make_user, DRAVET, STXBP1)
    call_id = await publish(pub, disease_ids=[DRAVET, STXBP1])
    (n,) = await notes(fan)
    assert n["call_id"] == call_id and n["disease_id"] == DRAVET
    await notes(fan)
    assert await rows(superuser, fan) == 1
    # Unfollowing one of them keeps the notification, now under the other disease.
    r = await fan.client.request("DELETE", "/me/follows", json={"node_id": DRAVET})
    assert r.status_code == 204
    (n,) = await notes(fan)
    assert n["disease_id"] == STXBP1 and n["read_at"] is None
    r = await fan.client.request("DELETE", "/me/follows", json={"node_id": STXBP1})
    assert await notes(fan) == []
    assert await rows(superuser, fan) == 0


async def test_gone_after_the_call_closes(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    fan = await follower(make_user)
    call_id = await publish(pub)
    assert await count(fan) == 1
    assert (await pub.client.post(f"/me/calls/{call_id}/close")).status_code == 200
    (n,) = await notes(fan)
    assert n["gone"] is True and n["item_label"] is None and n["call_id"] == call_id


async def test_followers_never_see_each_other(make_user, superuser, connect_as):
    pub = await make_publisher(make_user, superuser)
    a = await follower(make_user)
    b = await follower(make_user, STXBP1)
    call_id = await publish(pub)
    assert await count(a) == 1 and await count(b) == 0
    assert await notes(b) == []
    # Neither b nor the publisher can read a's rows in the database.
    app = await connect_as("atlas_app")
    for uid in (b.id, pub.id):
        async with app.transaction():
            await app.execute("SELECT set_config('app.user_id', $1, true)", str(uid))
            seen = await app.fetchval(
                "SELECT count(*) FROM notifications WHERE ref_id = $1", call_id
            )
            assert seen == 0
    # b's mark-all-read changes nothing for a.
    assert (await b.client.post("/notifications/read", json={"all": True})).status_code == 200
    assert await count(a) == 1


async def test_unfollow_deletes_call_notifications(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    fan = await follower(make_user)
    await publish(pub)
    assert await count(fan) == 1
    r = await fan.client.request("DELETE", "/me/follows", json={"node_id": DRAVET})
    assert r.status_code == 204
    assert await notes(fan) == [] and await count(fan) == 0
    assert await rows(superuser, fan) == 0


async def test_health_data_withdrawal_deletes_them(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    fan = await follower(make_user)
    await publish(pub)
    assert await count(fan) == 1
    assert (await fan.client.delete("/consents/health_data")).status_code == 204
    assert await rows(superuser, fan) == 0
    assert await count(fan) == 0


async def test_export_and_account_deletion(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    fan = await follower(make_user)
    other = await follower(make_user)
    call_id = await publish(pub)
    assert await count(fan) == 1 and await count(other) == 1
    data = (await fan.client.get("/me/export")).json()
    (n,) = data["notifications"]
    assert n["kind"] == "call_published" and n["ref_id"] == call_id
    assert n["subject_node_id"] == DRAVET
    assert (await fan.client.delete("/me")).status_code == 204
    assert await rows(superuser, fan) == 0
    assert await rows(superuser, other) == 1


async def test_retention_applies(make_user, superuser):
    pub = await make_publisher(make_user, superuser)
    fan = await follower(make_user)
    call_id = await publish(pub)
    assert await count(fan) == 1
    # Everything 91 days old: the notification is purged and the call is not notified again.
    async with superuser.transaction():
        await superuser.execute("SET LOCAL session_replication_role = replica")  # calls_guard
        await superuser.execute(
            "UPDATE calls SET published_at = now() - interval '91 days' WHERE id = $1", call_id
        )
        await superuser.execute(
            "UPDATE follows SET created_at = now() - interval '92 days' WHERE user_id = $1",
            fan.id,
        )
        await superuser.execute(
            "UPDATE notifications SET created_at = now() - interval '91 days' WHERE user_id = $1",
            fan.id,
        )
    # (Calls of other tests are newer than the backdated follow; only this one matters here.)
    assert call_id not in {n["call_id"] for n in await notes(fan)}
    assert not await superuser.fetchval(
        "SELECT count(*) FROM notifications WHERE user_id = $1 AND ref_id = $2", fan.id, call_id
    )


async def test_unread_count_fills_only_for_a_new_marker(make_user, superuser, monkeypatch):
    pub = await make_publisher(make_user, superuser)
    fan = await follower(make_user)
    fills: list[object] = []
    original = follows_service._fill_calls

    async def spy(db, user_id, marker):
        if user_id == fan.id:
            fills.append(marker)
        await original(db, user_id, marker)

    monkeypatch.setattr(follows_service, "_fill_calls", spy)
    assert await count(fan) == 0
    assert await count(fan) == 0
    assert len(fills) == 1
    await publish(pub)
    assert await count(fan) == 1
    assert await count(fan) == 1
    assert await count(fan) == 1
    assert len(fills) == 2
    await publish(pub, title="A second survey")
    assert await count(fan) == 2
    assert len(fills) == 3


async def test_no_duplicate_with_call_match(make_user, superuser):
    connect = CONSENT_TEXT_VERSIONS[ConsentType.connect]
    pub = await make_publisher(make_user, superuser)
    fan = await follower(make_user)
    await superuser.execute(
        "INSERT INTO consents (user_id, consent_type, version) VALUES ($1, 'connect', $2)",
        fan.id,
        connect,
    )
    await superuser.execute(
        "UPDATE profiles SET connect_age_group = '18_plus', suggestions_enabled = true"
        " WHERE user_id = $1",
        fan.id,
    )
    profile = {
        "diseases": [
            {"source": "manual", "confirmed_at": NOW, "id": DRAVET, "label": "Dravet syndrome"}
        ]
    }
    await superuser.execute(
        "INSERT INTO patient_profiles (user_id, profile) VALUES ($1, $2::jsonb)",
        fan.id,
        json.dumps(profile),
    )
    # (Earlier tests' Dravet calls match the profile too: count relative to them.)
    before = await count(fan)
    call_id = await publish(pub)
    assert await count(fan) == before + 1

    async def kinds() -> list[str]:
        r = await fan.client.get("/notifications?limit=200")
        return [x["kind"] for x in r.json()["items"] if x["call_id"] == call_id]

    assert await kinds() == ["call_match"]
    assert await rows(superuser, fan) == 0
    # Switching suggestions off deletes the call_match; the follow still notifies the call.
    r = await fan.client.put("/me/connect/suggestions", json={"enabled": False})
    assert r.status_code == 200, r.text
    assert await count(fan) == 1
    assert await kinds() == ["call_published"]
    # Switching back on turns the same row into the call_match (one notification per call).
    r = await fan.client.put("/me/connect/suggestions", json={"enabled": True})
    assert r.status_code == 200, r.text
    assert await kinds() == ["call_match"]
    assert await rows(superuser, fan) == 0
    assert await count(fan) == before + 1
