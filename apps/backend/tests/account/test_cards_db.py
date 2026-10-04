"""professional_cards() and pending_verification_requests(): who is listed and with what."""

import json
import uuid
from datetime import UTC, datetime

import asyncpg
import pytest

CARD_KEYS = {
    "card_id",
    "role",
    "name",
    "name_verified",
    "institutions",
    "orcid_id",
    "atlas_node_id",
    "headline",
    "accepts_patient_messages",
    "verification_method",
}


async def _new_user(app, role: str) -> uuid.UUID:
    uid = await app.fetchval(
        "SELECT auth_find_or_create_user($1, 'p@x.test', 'P')", f"p-{uuid.uuid4()}"
    )
    async with app.transaction():
        await app.execute("SELECT set_config('app.user_id', $1, true)", str(uid))
        await app.execute("UPDATE profiles SET role = $2 WHERE user_id = $1", uid, role)
    return uid


async def _set(app, uid, **cols) -> None:
    sets = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(cols))
    async with app.transaction():
        await app.execute("SELECT set_config('app.user_id', $1, true)", str(uid))
        await app.execute(f"UPDATE profiles SET {sets} WHERE user_id = $1", uid, *cols.values())


def _cards(rows, card_id):
    return [r for r in rows if r["card_id"] == card_id]


async def test_card_listed_only_when_visible_and_verified(connect_as):
    app = await connect_as("atlas_app")
    uid = await _new_user(app, "researcher")
    card_id = uuid.uuid4()
    await _set(
        app,
        uid,
        first_name="Ada",
        last_name="Lovelace",
        orcid_id="0000-0002-1825-0097",
        atlas_node_id="RES:fx-alpha",
        institutions=json.dumps([{"node_id": None, "label": "Private Inst"}]),
        card_id=card_id,
    )
    assert not _cards(await app.fetch("SELECT * FROM professional_cards()"), card_id)

    await _set(app, uid, card_visible=True)  # visible, not verified
    assert not _cards(await app.fetch("SELECT * FROM professional_cards()"), card_id)

    await _set(app, uid, role_verified=True, verification_method="institutional_email")
    rows = _cards(await app.fetch("SELECT * FROM professional_cards()"), card_id)
    assert len(rows) == 1
    row = rows[0]
    assert set(row.keys()) == CARD_KEYS  # never user_id, e-mail or private fields
    assert row["name"] == "Ada Lovelace" and row["name_verified"] is False
    # Self-declared ORCID iD and a name-matched atlas link stay private.
    assert row["orcid_id"] is None and row["atlas_node_id"] is None
    assert json.loads(row["institutions"]) == [{"node_id": None, "label": "Private Inst"}]

    await _set(app, uid, card_show_institutions=False, orcid_verified_at=None)
    row = _cards(await app.fetch("SELECT * FROM professional_cards()"), card_id)[0]
    assert json.loads(row["institutions"]) == []

    await _set(app, uid, role="patient")
    assert not _cards(await app.fetch("SELECT * FROM professional_cards()"), card_id)


async def test_verified_orcid_and_atlas_link_shown(connect_as):
    app = await connect_as("atlas_app")
    uid = await _new_user(app, "doctor")
    card_id = uuid.uuid4()
    await _set(
        app,
        uid,
        orcid_id="0000-0002-1694-233X",
        atlas_node_id="DOC:fx-one",
        card_id=card_id,
        card_visible=True,
        role_verified=True,
        verification_method="orcid",
        verified_name="Clinician One",
    )
    await _set(app, uid, orcid_verified_at=datetime.now(UTC), atlas_link_verified=True)
    row = _cards(await app.fetch("SELECT * FROM professional_cards()"), card_id)[0]
    assert row["orcid_id"] == "0000-0002-1694-233X"
    assert row["atlas_node_id"] == "DOC:fx-one" and row["name_verified"] is True
    await _set(app, uid, card_show_atlas_entry=False)
    row = _cards(await app.fetch("SELECT * FROM professional_cards()"), card_id)[0]
    assert row["atlas_node_id"] is None


async def test_card_visible_needs_card_id(connect_as):
    app = await connect_as("atlas_app")
    uid = await _new_user(app, "doctor")
    with pytest.raises(asyncpg.CheckViolationError):
        await _set(app, uid, card_visible=True)


async def test_confirmed_orcid_is_unique(connect_as):
    app = await connect_as("atlas_app")
    a = await _new_user(app, "researcher")
    b = await _new_user(app, "researcher")
    orcid = "0000-0001-5109-3700"
    await _set(app, a, orcid_id=orcid, orcid_verified_at=datetime.now(UTC))
    await _set(app, b, orcid_id=orcid)  # self-declared duplicates are allowed
    with pytest.raises(asyncpg.UniqueViolationError):
        await _set(app, b, orcid_verified_at=datetime.now(UTC))


async def test_pending_requests_not_for_the_api_role(connect_as):
    app = await connect_as("atlas_app")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app.fetch("SELECT * FROM pending_verification_requests()")
    owner = await connect_as("atlas_owner")
    uid = await _new_user(app, "doctor")
    await _set(
        app,
        uid,
        verification_request=json.dumps(
            {
                "status": "pending",
                "requested_at": "2026-10-04T00:00:00Z",
                "institutional_email": "a@uni.test",
            }
        ),
    )
    rows = await owner.fetch("SELECT * FROM pending_verification_requests()")
    assert uid in {r["user_id"] for r in rows}


async def test_definer_reads_only_scoped_columns(connect_as):
    su = await connect_as("atlas")
    cols = {
        r["column_name"]
        for r in await su.fetch(
            "SELECT column_name FROM information_schema.column_privileges"
            " WHERE grantee = 'atlas_definer' AND table_name = 'profiles'"
            " AND privilege_type = 'SELECT'"
        )
    }
    assert "user_id" in cols and "card_id" in cols
    assert not {"language", "gpc_opt_out", "verification_reason", "age_confirmed_at"} & cols
