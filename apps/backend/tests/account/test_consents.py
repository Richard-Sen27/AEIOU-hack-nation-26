"""Consents: explicit, granular, versioned; revoking deletes the data held under them."""

import json
import uuid

from account_helpers import ASSET, assert_error


async def test_guest_needs_sign_in(client):
    assert_error(await client.get("/consents"), 401, "sign_in_required")
    assert_error(
        await client.post(
            "/consents", json={"consent_type": "health_data", "version": "health-data-2026-10-04"}
        ),
        401,
        "sign_in_required",
    )
    assert_error(await client.delete("/consents/health_data"), 401, "sign_in_required")


async def test_no_consent_at_sign_up(make_user):
    user = await make_user()
    r = await user.client.get("/consents")
    assert r.status_code == 200
    assert r.json() == []
    assert (await user.client.get("/auth/session")).json()["user"]["consents"] == []


async def test_grant_list_revoke_regrant(make_user):
    user = await make_user()
    r = await user.client.post(
        "/consents", json={"consent_type": "health_data", "version": "health-data-2026-10-04"}
    )
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["consent_type"] == "health_data"
    assert first["version"] == "health-data-2026-10-04"
    assert first["active"] is True
    assert first["granted_at"]

    # Granular: health_data does not imply contribute.
    session = (await user.client.get("/auth/session")).json()["user"]
    assert session["consents"] == ["health_data"]

    # Idempotent while identical and active.
    again = await user.client.post(
        "/consents", json={"consent_type": "health_data", "version": "health-data-2026-10-04"}
    )
    assert again.json()["id"] == first["id"]

    assert (await user.client.delete("/consents/health_data")).status_code == 204
    assert_error(await user.client.delete("/consents/health_data"), 404, "not_found")

    r = await user.client.post(
        "/consents", json={"consent_type": "health_data", "version": "health-data-2026-10-04"}
    )
    assert r.status_code == 201
    assert r.json()["id"] != first["id"]

    history = (await user.client.get("/consents")).json()
    assert len(history) == 2
    assert [c["active"] for c in history] == [True, False]
    assert history[1]["revoked_at"] is not None


async def test_new_version_supersedes_and_keeps_contributions(make_user, superuser):
    user = await make_user(consents=["contribute"])
    assert (await user.client.post("/contributions", json=ASSET)).status_code == 201
    r = await user.client.post(
        "/consents", json={"consent_type": "contribute", "version": "contribute-2026-10-04"}
    )
    assert r.status_code == 201
    new_id = uuid.UUID(r.json()["id"])
    consent_ids = await superuser.fetch(
        "SELECT consent_id FROM contributions WHERE user_id = $1", user.id
    )
    assert [c["consent_id"] for c in consent_ids] == [new_id]
    shared = await superuser.fetch("SELECT id FROM shared_contributions()")
    assert len([s for s in shared]) >= 1


async def test_child_needs_parental_responsibility(make_user):
    user = await make_user()
    r = await user.client.post(
        "/consents",
        json={
            "consent_type": "health_data",
            "version": "health-data-2026-10-04",
            "about_child": True,
        },
    )
    assert_error(r, 422, "validation_error")
    r = await user.client.post(
        "/consents",
        json={
            "consent_type": "health_data",
            "version": "health-data-2026-10-04",
            "about_child": True,
            "parental_responsibility_confirmed": True,
        },
    )
    assert r.status_code == 201
    assert r.json()["about_child"] is True
    assert r.json()["parental_responsibility_confirmed"] is True


async def test_child_profile_requires_child_consent(make_user):
    user = await make_user()
    profile = {"about_child": True, "parental_responsibility_confirmed": True, "updated_at": None}
    assert (await user.client.put("/profile", json=profile)).status_code == 200
    r = await user.client.post(
        "/consents", json={"consent_type": "contribute", "version": "contribute-2026-10-04"}
    )
    assert_error(r, 422, "validation_error")


async def test_validation(make_user):
    user = await make_user()
    assert_error(
        await user.client.post("/consents", json={"consent_type": "marketing", "version": "v1"}),
        422,
        "validation_error",
    )
    assert_error(
        await user.client.post("/consents", json={"consent_type": "health_data"}),
        422,
        "validation_error",
    )
    assert_error(await user.client.delete("/consents/marketing"), 422, "validation_error")


async def test_revoke_health_data_deletes_documents_findings_and_profile_items(
    make_user, connect_as
):
    user = await make_user(consents=["health_data"])
    app = await connect_as("atlas_app")
    async with app.transaction():
        await app.execute("SELECT set_config('app.user_id', $1, true)", str(user.id))
        doc = await app.fetchval(
            "INSERT INTO documents (user_id) VALUES ($1) RETURNING id", user.id
        )
        finding = await app.fetchval(
            "INSERT INTO findings (document_id, user_id, type, value, normalized_id)"
            " VALUES ($1, $2, 'gene', 'STXBP1', 'HGNC:11444') RETURNING id",
            doc,
            user.id,
        )
        await app.execute(
            "INSERT INTO jobs (user_id, kind, document_id) VALUES ($1, 'document_extraction', $2)",
            user.id,
            doc,
        )
        profile = {
            "genes": [
                {
                    "id": "HGNC:11444",
                    "label": "STXBP1",
                    "source": "document",
                    "finding_id": str(finding),
                },
                {"id": "HGNC:10590", "label": "SCN1A", "source": "manual"},
            ],
            "phenotypes": [{"id": "HP:0001250", "label": "Seizure", "source": "chat"}],
        }
        await app.execute(
            "INSERT INTO patient_profiles (user_id, profile) VALUES ($1, $2::jsonb)",
            user.id,
            json.dumps(profile),
        )

    assert (await user.client.delete("/consents/health_data")).status_code == 204

    su = await connect_as("atlas")
    for table in ("documents", "findings", "jobs"):
        n = await su.fetchval(f"SELECT count(*) FROM {table} WHERE user_id = $1", user.id)
        assert n == 0, table
    kept = (await user.client.get("/profile")).json()
    assert [g["id"] for g in kept["genes"]] == ["HGNC:10590"]
    assert [p["id"] for p in kept["phenotypes"]] == ["HP:0001250"]
    assert (await user.client.get("/auth/session")).json()["user"]["consents"] == []


async def test_revoke_contribute_removes_contributions_from_shared_graph(make_user, superuser):
    user = await make_user(consents=["contribute"])
    r = await user.client.post("/contributions", json=ASSET)
    cid = uuid.UUID(r.json()["id"])
    shared = {row["id"] for row in await superuser.fetch("SELECT id FROM shared_contributions()")}
    assert cid in shared

    assert (await user.client.delete("/consents/contribute")).status_code == 204
    shared = {row["id"] for row in await superuser.fetch("SELECT id FROM shared_contributions()")}
    assert cid not in shared
    assert (
        await superuser.fetchval("SELECT count(*) FROM contributions WHERE user_id = $1", user.id)
        == 0
    )
    assert_error(await user.client.post("/contributions", json=ASSET), 403, "consent_required")


async def test_cross_user_isolation(make_user):
    a = await make_user(consents=["health_data", "contribute"])
    b = await make_user()
    assert (await b.client.get("/consents")).json() == []
    # B revoking affects only B (404: B has none); A's consents stay.
    assert_error(await b.client.delete("/consents/health_data"), 404, "not_found")
    assert len((await a.client.get("/consents")).json()) == 2


async def test_only_current_text_versions_are_accepted(make_user):
    user = await make_user()
    for body in (
        {"consent_type": "health_data", "version": "v1"},
        {"consent_type": "health_data", "version": "contribute-2026-10-04"},
        {"consent_type": "contribute", "version": "health-data-2026-10-04"},
        {"consent_type": "health_data", "version": "upload-2026-10-04"},
    ):
        r = await user.client.post("/consents", json=body)
        assert_error(r, 422, "validation_error")
        assert "version" in r.json()["error"]["message"]
    assert (await user.client.get("/consents")).json() == []
