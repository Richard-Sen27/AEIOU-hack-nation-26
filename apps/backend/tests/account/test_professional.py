"""Work details of doctors and researchers: /me/professional and its matches route."""

import json

import jwt
import pytest
from account_helpers import assert_error
from cryptography.fernet import Fernet

from backend.api.ratelimit import limiter
from backend.api.services.graph import get_graph
from backend.schemas.graph import Node

ORCID = "0000-0002-1825-0097"  # valid check digit
ORCID_X = "0000-0002-1694-233X"  # valid, check digit X
BAD_CHECKSUM = "0000-0002-1825-0098"
COLUMNS = "first_name, last_name, institutions, orcid_id, atlas_node_id, professional_updated_at"
CANDIDATE_KEYS = {"node_id", "type", "label", "orcid_id", "institutions", "matched_by"}


@pytest.fixture
def people(monkeypatch):
    """Researcher and doctor nodes with the attributes the pipeline writes (name_key, orcid).

    Fixture affiliations: RES:fx-alpha and RES:fx-beta -> INST:fx-neuro,
    RES:fx-gamma -> INST:fx-epilepsy, DOC:fx-one -> INST:fx-childrens.
    """
    store = get_graph()

    def patch(node_id: str, label: str, **attrs):
        node = store.nodes[node_id]
        monkeypatch.setitem(
            store.nodes,
            node_id,
            node.model_copy(update={"label": label, "attrs": {**node.attrs, **attrs}}),
        )

    patch("RES:fx-alpha", "José Müller", name_key="jose muller")
    patch("RES:fx-gamma", "Jose Muller", name_key="jose muller")
    patch(
        "DOC:fx-one",
        "José A. Müller",
        name_key="jose muller",
        affiliations=["Fixture Children's Hospital"],
    )
    patch("RES:fx-beta", "Ada Lovelace", name_key="ada lovelace", email="private@example.test")
    monkeypatch.setitem(
        store.nodes,
        f"ORCID:{ORCID}",
        Node(
            id=f"ORCID:{ORCID}",
            type="researcher",
            label="Orla Orcid",
            attrs={"orcid": ORCID, "name_key": "orla orcid"},
        ),
    )
    return store


@pytest.fixture
def encryption_key(monkeypatch):
    from backend.openai_auth.settings import get_openai_settings

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", key)
    get_openai_settings.cache_clear()
    yield key
    get_openai_settings.cache_clear()


async def _stored(superuser, user):
    return dict(
        await superuser.fetchrow(f"SELECT {COLUMNS} FROM profiles WHERE user_id = $1", user.id)
    )


async def test_guest(client):
    assert_error(await client.get("/me/professional"), 401, "sign_in_required")
    assert_error(await client.put("/me/professional", json={}), 401, "sign_in_required")
    assert_error(await client.delete("/me/professional"), 401, "sign_in_required")
    assert_error(await client.post("/me/professional/matches", json={}), 401, "sign_in_required")


@pytest.mark.parametrize("role", ["patient", None])
async def test_only_doctors_and_researchers(make_user, role):
    user = await make_user(role=role)
    assert_error(await user.client.get("/me/professional"), 403, "forbidden")
    assert_error(await user.client.put("/me/professional", json={}), 403, "forbidden")
    assert_error(await user.client.post("/me/professional/matches", json={}), 403, "forbidden")
    # Removal never depends on the role.
    assert (await user.client.delete("/me/professional")).status_code == 204


async def test_put_get_and_delete(make_user, superuser, people):
    user = await make_user(role="researcher")
    r = await user.client.get("/me/professional")
    assert r.status_code == 200, r.text
    assert r.json()["updated_at"] is None and r.json()["institutions"] == []

    body = {
        "first_name": "  José ",
        "last_name": "Müller",
        "orcid_id": ORCID_X.lower(),
        "institutions": [
            {"node_id": "INST:fx-neuro", "label": "ignored, the atlas label wins"},
            {"label": "St. Jude  Children's"},
            {"node_id": "INST:fx-neuro"},  # duplicate, dropped
        ],
        "atlas_node_id": "RES:fx-alpha",
    }
    r = await user.client.put("/me/professional", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["first_name"] == "José" and data["last_name"] == "Müller"
    assert data["orcid_id"] == ORCID_X
    assert data["institutions"] == [
        {"node_id": "INST:fx-neuro", "label": "Fixture University Neuroscience Institute"},
        {"node_id": None, "label": "St. Jude Children's"},
    ]
    assert data["linked_entry"] == {
        "node_id": "RES:fx-alpha",
        "type": "researcher",
        "label": "José Müller",
        "orcid_id": None,
        "institutions": [
            {"node_id": "INST:fx-neuro", "label": "Fixture University Neuroscience Institute"}
        ],
    }
    assert data["linked_entry_missing"] is False and data["updated_at"]
    assert (await user.client.get("/me/professional")).json() == data

    stored = await _stored(superuser, user)
    assert (
        stored["atlas_node_id"] == "RES:fx-alpha" and len(json.loads(stored["institutions"])) == 2
    )

    # The session greets with the confirmed name.
    session = (await user.client.get("/auth/session")).json()
    assert session["user"]["name"] == "José Müller"

    # A node that left the atlas: the link stays, flagged as missing.
    people.nodes.pop("RES:fx-alpha")
    data = (await user.client.get("/me/professional")).json()
    assert data["linked_entry"] is None and data["linked_entry_missing"] is True

    # PUT replaces everything.
    r = await user.client.put("/me/professional", json={"last_name": "Müller"})
    assert r.json()["first_name"] is None and r.json()["institutions"] == []
    assert r.json()["atlas_node_id"] is None and r.json()["orcid_id"] is None

    assert (await user.client.delete("/me/professional")).status_code == 204
    stored = await _stored(superuser, user)
    assert stored == {
        "first_name": None,
        "last_name": None,
        "institutions": "[]",
        "orcid_id": None,
        "atlas_node_id": None,
        "professional_updated_at": None,
    }
    session = (await user.client.get("/auth/session")).json()
    assert session["user"]["name"] == "Test"


@pytest.mark.parametrize(
    "body,field",
    [
        ({"orcid_id": BAD_CHECKSUM}, "orcid_id"),
        ({"orcid_id": "0000-0002-1825-009"}, "orcid_id"),
        ({"orcid_id": "https://orcid.org/" + ORCID}, "orcid_id"),
        ({"first_name": "x" * 101}, "first_name"),
        ({"last_name": "Smith\nDROP"}, "last_name"),
        ({"first_name": "Ana\x00"}, "first_name"),
        ({"institutions": [{"label": f"Inst {i}"} for i in range(4)]}, "institutions"),
        ({"institutions": [{"label": "x" * 201}]}, "institutions.0.label"),
        ({"institutions": [{"label": "Uni\tVienna"}]}, "institutions.0.label"),
        ({"institutions": [{}]}, "institutions.0"),
        ({"institutions": [{"node_id": "RES:fx-alpha"}]}, "institutions.0.node_id"),
        ({"institutions": [{"node_id": "INST:does-not-exist"}]}, "institutions.0.node_id"),
        ({"atlas_node_id": "INST:fx-neuro"}, "atlas_node_id"),
        ({"atlas_node_id": "MONDO:0013276"}, "atlas_node_id"),
        ({"atlas_node_id": "RES:does-not-exist"}, "atlas_node_id"),
        ({"title": "Prof."}, "title"),
    ],
)
async def test_validation(make_user, superuser, body, field):
    user = await make_user(role="doctor")
    r = await user.client.put("/me/professional", json=body)
    assert_error(r, 422, "validation_error")
    assert field in r.json()["error"]["message"]
    for value in ("Smith", "DROP", "Inst 3", "Vienna", "Prof.", "xxxx"):
        assert value not in r.json()["error"]["message"]
    assert (await _stored(superuser, user))["professional_updated_at"] is None
    if field.startswith(("orcid", "first", "last", "institutions")):
        r = await user.client.post("/me/professional/matches", json=body)
        assert_error(r, 422, "validation_error")


async def test_database_checks(superuser, make_user):
    user = await make_user(role="doctor")
    for sql, value in (
        ("UPDATE profiles SET institutions = $2::jsonb WHERE user_id = $1", "[{},{},{},{}]"),
        ("UPDATE profiles SET first_name = $2 WHERE user_id = $1", "x" * 101),
        ("UPDATE profiles SET last_name = $2 WHERE user_id = $1", ""),
    ):
        with pytest.raises(Exception, match="check constraint"):
            await superuser.execute(sql, user.id, value)


async def test_prefill_splits_the_account_name(make_user, superuser):
    user = await make_user(role="researcher")
    await superuser.execute("UPDATE users SET name = 'Ana María de la Cruz' WHERE id = $1", user.id)
    data = (await user.client.get("/me/professional")).json()
    assert data["suggested"] == {
        "first_name": "Ana María de la",
        "last_name": "Cruz",
        "source": "chatgpt",
    }
    assert data["first_name"] is None  # a suggestion, not stored
    assert (await _stored(superuser, user))["first_name"] is None

    await superuser.execute("UPDATE users SET name = NULL WHERE id = $1", user.id)
    assert (await user.client.get("/me/professional")).json()["suggested"] is None


async def test_prefill_prefers_id_token_claims(make_user, superuser, encryption_key):
    from backend.openai_auth import encrypt

    user = await make_user(role="doctor")
    token = jwt.encode(
        {"sub": user.sub, "name": "Test", "given_name": "Grace", "family_name": "Hopper"},
        "not-checked-here-" * 4,
        algorithm="HS256",
    )
    await superuser.execute(
        "INSERT INTO openai_tokens (user_id, access_token_enc, id_token_enc) VALUES ($1, 'x', $2)",
        user.id,
        encrypt(token).decode(),
    )
    suggested = (await user.client.get("/me/professional")).json()["suggested"]
    assert suggested == {"first_name": "Grace", "last_name": "Hopper", "source": "chatgpt"}
    stored = await _stored(superuser, user)
    assert stored["first_name"] is None and stored["last_name"] is None

    # An undecryptable token falls back to the account name.
    await superuser.execute(
        "UPDATE openai_tokens SET id_token_enc = 'garbage' WHERE user_id = $1", user.id
    )
    suggested = (await user.client.get("/me/professional")).json()["suggested"]
    assert suggested == {"first_name": "Test", "last_name": None, "source": "chatgpt"}


async def test_matches(make_user, superuser, people):
    user = await make_user(role="researcher")
    other = await make_user(role="doctor")
    r = await other.client.put(
        "/me/professional",
        json={"first_name": "Secret", "last_name": "Person", "atlas_node_id": "RES:fx-gamma"},
    )
    assert r.status_code == 200

    # ORCID first, then the same name key (accents folded), shared institution first.
    r = await user.client.post(
        "/me/professional/matches",
        json={
            "first_name": "Jose Antonio",
            "last_name": "MÜLLER",
            "orcid_id": ORCID,
            "institutions": [
                {"node_id": "INST:fx-epilepsy"},
                {"label": "FIXTURE CHILDREN’S HOSPITAL"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    candidates = r.json()["candidates"]
    assert [(c["node_id"], c["matched_by"]) for c in candidates] == [
        (f"ORCID:{ORCID}", "orcid"),
        ("DOC:fx-one", "name_and_institution"),  # matched on its free-text affiliation
        ("RES:fx-gamma", "name_and_institution"),
        ("RES:fx-alpha", "name"),
    ]
    for c in candidates:
        assert set(c) == CANDIDATE_KEYS
    assert candidates[0]["orcid_id"] == ORCID
    assert "Secret" not in r.text and "private@example.test" not in r.text

    # Without an institution every name match ranks the same.
    r = await user.client.post(
        "/me/professional/matches", json={"first_name": "josé", "last_name": "muller"}
    )
    assert {c["matched_by"] for c in r.json()["candidates"]} == {"name"}
    assert len(r.json()["candidates"]) == 3

    # Nothing to match on, or a name alone without a last name: no candidates.
    for body in ({}, {"first_name": "José"}, {"orcid_id": ORCID_X}):
        r = await user.client.post("/me/professional/matches", json=body)
        assert r.json() == {"candidates": []}

    # Matching stores nothing.
    stored = await _stored(superuser, user)
    assert stored["first_name"] is None and stored["professional_updated_at"] is None


async def test_matches_at_most_five(make_user, people, monkeypatch):
    for i in range(7):
        monkeypatch.setitem(
            people.nodes,
            f"RES:many-{i}",
            Node(
                id=f"RES:many-{i}",
                type="researcher",
                label="Kim Lee",
                attrs={"name_key": "kim lee"},
            ),
        )
    user = await make_user(role="doctor")
    r = await user.client.post(
        "/me/professional/matches", json={"first_name": "Kim", "last_name": "Lee"}
    )
    assert len(r.json()["candidates"]) == 5


async def test_matches_rate_limited(make_user):
    user = await make_user(role="researcher")
    limiter.reset()
    try:
        for _ in range(30):
            r = await user.client.post("/me/professional/matches", json={})
            assert r.status_code == 200
        assert_error(
            await user.client.post("/me/professional/matches", json={}), 429, "rate_limited"
        )
    finally:
        limiter.reset()


async def test_withdrawing_health_data_keeps_work_details(make_user, superuser):
    user = await make_user(role="doctor", consents=["health_data"])
    r = await user.client.put("/me/professional", json={"first_name": "Ada", "last_name": "Byron"})
    assert r.status_code == 200
    assert (await user.client.delete("/consents/health_data")).status_code == 204
    data = (await user.client.get("/me/professional")).json()
    assert (data["first_name"], data["last_name"]) == ("Ada", "Byron")


async def test_row_level_security(make_user, connect_as):
    a = await make_user(role="researcher")
    b = await make_user(role="doctor")
    r = await b.client.put(
        "/me/professional",
        json={"first_name": "Bea", "last_name": "Other", "orcid_id": ORCID},
    )
    assert r.status_code == 200
    app = await connect_as("atlas_app")
    async with app.transaction():
        await app.execute("SELECT set_config('app.user_id', $1, true)", str(a.id))
        rows = await app.fetch(f"SELECT {COLUMNS} FROM profiles WHERE user_id = $1", b.id)
        assert rows == []
        seen = await app.fetch("SELECT user_id, first_name FROM profiles")
        assert [r["user_id"] for r in seen] == [a.id]
        status = await app.execute(
            "UPDATE profiles SET first_name = 'Mallory' WHERE user_id = $1", b.id
        )
        assert status == "UPDATE 0"
    data = (await b.client.get("/me/professional")).json()
    assert data["first_name"] == "Bea"
