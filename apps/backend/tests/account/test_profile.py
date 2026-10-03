"""PatientProfile: strict validation, every field editable, lost-update safe, mergeable."""

import json
import uuid

import pytest
from account_helpers import assert_error
from sqlalchemy import text

from backend.api.errors import ApiError
from backend.api.services.account import (
    merge_profile_items,
    remove_profile_items,
    validate_profile,
)
from backend.db.session import user_transaction
from backend.schemas.enums import ProfileSource
from backend.schemas.profile import PatientProfile, ProfileGene, ProfilePhenotype

PROFILE = {
    "diseases": [{"id": "MONDO:0013276", "label": "STXBP1 encephalopathy", "source": "chat"}],
    "genes": [{"id": "HGNC:11444", "label": "STXBP1", "source": "manual"}],
    "variants": [
        {
            "hgvs": "NM_003165.6:c.1631G>A",
            "gene_id": "HGNC:11444",
            "zygosity": "heterozygous",
            "classification": "pathogenic",
            "source": "manual",
        }
    ],
    "phenotypes": [
        {"id": "HP:0001250", "label": "Seizure", "source": "chat"},
        {"id": "HP:0011968", "label": "Feeding difficulties", "source": "chat", "excluded": True},
    ],
    "age_years": 2,
    "country": "AT",
    "updated_at": None,
}


async def test_guest_needs_sign_in(client):
    assert_error(await client.get("/profile"), 401, "sign_in_required")
    assert_error(await client.put("/profile", json=PROFILE), 401, "sign_in_required")


async def test_empty_then_put_then_get(make_user):
    user = await make_user(consents=["health_data"])
    empty = (await user.client.get("/profile")).json()
    assert empty["diseases"] == [] and empty["updated_at"] is None

    r = await user.client.put("/profile", json=PROFILE)
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["updated_at"] is not None
    assert all(item["confirmed_at"] for item in saved["phenotypes"])
    assert saved["phenotypes"][1]["excluded"] is True
    assert (await user.client.get("/profile")).json() == saved

    # Every field editable (Art. 16): remove a phenotype, change the age.
    edited = {**saved, "phenotypes": saved["phenotypes"][:1], "age_years": 3}
    r = await user.client.put("/profile", json=edited)
    assert r.status_code == 200, r.text
    assert len(r.json()["phenotypes"]) == 1
    assert r.json()["age_years"] == 3


async def test_lost_update_is_rejected(make_user):
    user = await make_user(consents=["health_data"])
    first = (await user.client.put("/profile", json=PROFILE)).json()
    second = await user.client.put("/profile", json={**first, "age_years": 4})
    assert second.status_code == 200
    stale = await user.client.put("/profile", json={**first, "age_years": 5})
    assert_error(stale, 409, "conflict")
    # A client that never read the profile cannot blindly overwrite it.
    assert_error(await user.client.put("/profile", json=PROFILE), 409, "conflict")


async def test_validation(make_user):
    user = await make_user(consents=["health_data"])
    cases = [
        {**PROFILE, "name": "Jane Doe"},  # unknown field
        {**PROFILE, "birth_date": "2023-01-01"},
        {**PROFILE, "diseases": [{"id": "OMIM:123", "label": "x", "source": "chat"}]},
        {
            **PROFILE,
            "genes": [{"id": "HGNC:11444", "label": "Jane Doe lives here", "source": "chat"}],
        },
        {**PROFILE, "phenotypes": [{"id": "HP:1", "label": "Seizure", "source": "chat"}]},
        {
            **PROFILE,
            "phenotypes": [{"id": "HP:0001250", "label": "call 0664123456", "source": "chat"}],
        },
        {**PROFILE, "phenotypes": [{"id": "HP:0001250", "label": "a@b.example", "source": "chat"}]},
        {**PROFILE, "variants": [{"hgvs": "has spaces in it", "source": "chat"}]},
        {**PROFILE, "variants": [{"hgvs": "Jane c.1A>G", "source": "chat"}]},
        {**PROFILE, "variants": [{"source": "chat"}]},
        {**PROFILE, "country": "Austria"},
        {**PROFILE, "age_years": 200},
        {**PROFILE, "onset": "born at 12 Main Street 1010 Vienna"},
        {**PROFILE, "about_child": True},  # no parental responsibility
        {**PROFILE, "diseases": [{"id": "MONDO:0013276", "label": "x", "source": "fax"}]},
    ]
    for body in cases:
        r = await user.client.put("/profile", json=body)
        assert_error(r, 422, "validation_error")
        assert "Jane" not in r.text and "0664" not in r.text


async def test_variant_strings_are_storable(make_user):
    """The digit-run rule keeps phone numbers out of labels; HGVS and ClinVar strings are exempt."""
    user = await make_user(consents=["health_data"])
    hgvs_values = [
        "NM_003165.6:c.1216C>T",
        "c.12345G>A",
        "NC_000009.12:g.127663352C>T",
        "NM_003165.6(STXBP1):c.1216C>T (p.Arg406Cys)",  # ClinVar variation name
        "STXBP1 c.1216C>T",  # ClinVar-derived node label, as a confirmed chat chip sends it
        "STXBP1 p.Arg406Cys",
    ]
    variants = [
        {"hgvs": h, "clinvar_id": f"CLINVAR:{100000 + i}", "source": "chat"}
        for i, h in enumerate(hgvs_values)
    ]
    variants.append(
        {"clinvar_id": "CLINVAR:1234567", "gene_id": "HGNC:11444", "source": "document"}
    )
    r = await user.client.put("/profile", json={**PROFILE, "variants": variants})
    assert r.status_code == 200, r.text
    assert [v["hgvs"] for v in r.json()["variants"][: len(hgvs_values)]] == hgvs_values


async def test_age_confirmation_required_for_put(make_user):
    user = await make_user(age_confirmed=False, consents=["health_data"])
    assert (await user.client.get("/profile")).status_code == 200
    assert_error(await user.client.put("/profile", json=PROFILE), 403, "age_confirmation_required")


async def test_merge_and_remove_helpers(make_user):
    user = await make_user(consents=["health_data"])
    finding = uuid.uuid4()
    async with user_transaction(user.id) as db:
        merged = await merge_profile_items(
            db,
            user.id,
            [
                ProfileGene(
                    id="HGNC:11444",
                    label="STXBP1",
                    source=ProfileSource.document,
                    finding_id=finding,
                ),
                ProfilePhenotype(id="HP:0001250", label="Seizure", source=ProfileSource.chat),
            ],
        )
    assert [g.id for g in merged.genes] == ["HGNC:11444"]
    assert merged.genes[0].confirmed_at is not None
    assert merged.updated_at is not None

    # Merging the same item again replaces it rather than duplicating.
    async with user_transaction(user.id) as db:
        again = await merge_profile_items(
            db, user.id, [ProfilePhenotype(id="HP:0001250", label="Seizures", source="chat")]
        )
    assert [(p.id, p.label) for p in again.phenotypes] == [("HP:0001250", "Seizures")]

    async with user_transaction(user.id) as db:
        removed = await remove_profile_items(db, user.id, finding_ids=[finding])
    assert removed is not None and removed.genes == [] and len(removed.phenotypes) == 1


async def test_merge_invalidates_stale_put(make_user):
    user = await make_user(consents=["health_data"])
    read = (await user.client.put("/profile", json=PROFILE)).json()
    async with user_transaction(user.id) as db:
        await merge_profile_items(
            db, user.id, [ProfileGene(id="HGNC:10590", label="SCN1A", source="document")]
        )
    assert_error(await user.client.put("/profile", json=read), 409, "conflict")


async def test_cross_user_isolation(make_user):
    a = await make_user(consents=["health_data"])
    b = await make_user(consents=["health_data"])
    await a.client.put("/profile", json=PROFILE)
    assert (await b.client.get("/profile")).json()["diseases"] == []
    await b.client.put("/profile", json={"updated_at": None, "age_years": 40})
    assert (await a.client.get("/profile")).json()["age_years"] == 2


async def test_child_profile_needs_parental_responsibility(make_user):
    user = await make_user(consents=["health_data"])
    for body in (
        {**PROFILE, "about_child": True},
        {**PROFILE, "about_child": True, "parental_responsibility_confirmed": False},
    ):
        r = await user.client.put("/profile", json=body)
        assert_error(r, 422, "validation_error")
        assert "parental_responsibility_confirmed" in r.json()["error"]["message"]
        assert "STXBP1" not in r.text
    ok = {**PROFILE, "about_child": True, "parental_responsibility_confirmed": True}
    saved = (await user.client.put("/profile", json=ok)).json()
    assert saved["about_child"] is True and saved["parental_responsibility_confirmed"] is True
    # Not about a child (the default): no confirmation needed, and none is kept.
    plain = {**PROFILE, "updated_at": saved["updated_at"]}
    assert (await user.client.put("/profile", json=plain)).json()["about_child"] is False


async def test_merge_rejects_child_profile_without_parental_responsibility(make_user):
    user = await make_user(consents=["health_data"])
    async with user_transaction(user.id) as db:
        await db.execute(
            text(
                "INSERT INTO patient_profiles (user_id, profile) VALUES (:uid, CAST(:p AS jsonb))"
            ),
            {"uid": user.id, "p": json.dumps({"about_child": True})},
        )
    with pytest.raises(ApiError) as exc:
        async with user_transaction(user.id) as db:
            await merge_profile_items(
                db, user.id, [ProfileGene(id="HGNC:10590", label="SCN1A", source="document")]
            )
    assert exc.value.status_code == 422
    assert "parental_responsibility_confirmed" in exc.value.message
    unsafe = PatientProfile.model_construct(**{**PatientProfile().__dict__, "about_child": True})
    with pytest.raises(ApiError):
        validate_profile(unsafe)
