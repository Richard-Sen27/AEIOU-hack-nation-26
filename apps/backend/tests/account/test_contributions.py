"""Contributions: consent-gated, pending_review, de-identified, isolated per user."""

import copy
import uuid

from account_helpers import ASSET, EDGE, PHENO, assert_error

from backend.api.services import contributions as service
from backend.db.session import user_transaction


def variant(base: dict, **payload) -> dict:
    body = copy.deepcopy(base)
    body["payload"].update(payload)
    return body


async def test_guest(client):
    assert_error(await client.get("/contributions"), 401, "sign_in_required")
    assert_error(await client.post("/contributions", json=ASSET), 401, "sign_in_required")
    assert_error(await client.delete(f"/contributions/{uuid.uuid4()}"), 401, "sign_in_required")


async def test_needs_contribute_consent(make_user):
    user = await make_user(consents=["health_data"])
    assert_error(await user.client.post("/contributions", json=PHENO), 403, "consent_required")


async def test_create_list_delete(make_user, superuser):
    user = await make_user(consents=["contribute"])
    created = []
    for body in (PHENO, ASSET, EDGE):
        r = await user.client.post("/contributions", json=body)
        assert r.status_code == 201, r.text
        c = r.json()
        assert c["status"] == "pending_review"
        assert c["kind"] == body["kind"]
        assert c["consent_id"]
        created.append(c)
    assert [c["origin"] for c in created] == [
        "patient_reported",
        "patient_reported",
        "user_contributed",
    ]

    listed = (await user.client.get("/contributions")).json()
    assert {c["id"] for c in listed} == {c["id"] for c in created}

    shared = await superuser.fetch("SELECT * FROM shared_contributions()")
    assert {str(r["id"]) for r in shared} >= {c["id"] for c in created}
    assert "user_id" not in shared[0].keys()

    async with user_transaction(None) as db:
        public = await service.shared(db)
    by_id = {str(s.id): s for s in public}
    assert by_id[created[2]["id"]].origin == "user_contributed"

    assert (await user.client.delete(f"/contributions/{created[0]['id']}")).status_code == 204
    assert_error(await user.client.delete(f"/contributions/{created[0]['id']}"), 404, "not_found")
    shared = {str(r["id"]) for r in await superuser.fetch("SELECT id FROM shared_contributions()")}
    assert created[0]["id"] not in shared


async def test_validation(make_user):
    user = await make_user(consents=["contribute"])
    bad = [
        variant(PHENO, disease_id="OMIM:1234"),
        variant(PHENO, phenotype_ids=[]),
        variant(PHENO, phenotype_ids=["seizures"]),
        variant(PHENO, excluded_phenotype_ids=["HP:0001250"]),  # both present and absent
        variant(PHENO, age_range="born 2023-01-01"),
        variant(PHENO, name="Jane Doe"),  # unknown field
        variant(ASSET, name="Registry run by Maria Gonzalez"),
        variant(ASSET, name="Contact jane@example.org"),
        variant(ASSET, description="Call +43 664 1234567 for details"),
        variant(ASSET, url="javascript:alert(1)"),
        variant(ASSET, url="https://user:pw@example.org/"),
        variant(ASSET, disease_ids=["not-an-id"]),
        variant(ASSET, asset_type="patient_list"),
        variant(EDGE, relation="cures"),
        variant(EDGE, source_id="free text"),
        variant(EDGE, target_id="MONDO:0013276"),  # self loop
        variant(EDGE, source_id_ref=None),  # no source at all
        variant(EDGE, source_id_ref="my notes"),
        {"kind": "story", "payload": {}},
    ]
    for body in bad:
        r = await user.client.post("/contributions", json=body)
        assert_error(r, 422, "validation_error")
        assert "Gonzalez" not in r.text and "jane@" not in r.text
    assert (await user.client.get("/contributions")).json() == []


async def test_cross_user_isolation(make_user):
    a = await make_user(consents=["contribute"])
    b = await make_user(consents=["contribute"])
    cid = (await a.client.post("/contributions", json=ASSET)).json()["id"]
    assert (await b.client.get("/contributions")).json() == []
    assert_error(await b.client.delete(f"/contributions/{cid}"), 404, "not_found")
    assert [c["id"] for c in (await a.client.get("/contributions")).json()] == [cid]
