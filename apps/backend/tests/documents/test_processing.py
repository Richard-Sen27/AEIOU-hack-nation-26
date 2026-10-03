import asyncio
import json
import uuid

import pytest
from docfiles import (
    FAKE_FILENAME,
    PII,
    REPORT_LINES,
    VARIANT_LINE,
    docx_bytes,
    job_events,
    model_inputs,
    text_image,
    text_pdf,
    upload,
    variant_extraction,
)

from backend.api.services import documents
from backend.api.services.documents.extract import tesseract_path
from backend.db.models import DocumentRecord, JobRecord
from backend.db.session import user_transaction
from backend.schemas.enums import VUS_NOTICE

GENETIC = {"json": {"doc_type": "genetic_report"}}


async def _rows(connect_as, user_id) -> str:
    """Every stored column of the user's documents, findings and jobs, as one string."""
    conn = await connect_as("atlas")
    parts = []
    for table in ("documents", "findings", "jobs", "patient_profiles"):
        rows = await conn.fetch(
            f"SELECT row_to_json(t)::text AS j FROM {table} t WHERE user_id = $1", user_id
        )
        parts.extend(r["j"] for r in rows)
    return "\n".join(parts)


async def _upload_report(user, llm, extraction=None, data=None, **kw):
    llm.enqueue(GENETIC, {"json": extraction or variant_extraction()})
    resp = await upload(user, data or text_pdf(), **kw)
    assert resp.status_code == 202, resp.text
    return resp.json()


async def test_genetic_report_flow_with_redaction(make_user, llm, connect_as):
    user = await make_user(consents=["upload"])
    accepted = await _upload_report(user, llm)

    events = await job_events(user, accepted["job_id"])
    assert events[-1]["type"] == "done"
    assert events[-1]["document_id"] == accepted["document_id"]
    assert events[-1]["finding_count"] == 2
    assert all(e["type"] in ("progress", "done") for e in events)

    docs = (await user.client.get("/documents")).json()
    assert docs[0]["id"] == accepted["document_id"]
    assert docs[0]["status"] == "ready"
    assert docs[0]["doc_type"] == "genetic_report"
    assert docs[0]["raw_deleted_at"] is not None
    assert "filename" not in docs[0]

    findings = (await user.client.get(f"/documents/{accepted['document_id']}/findings")).json()
    by_type = {f["type"]: f for f in findings}
    gene, variant = by_type["gene"], by_type["variant"]
    assert gene["normalized_id"] == "HGNC:11444"
    assert gene["page"] == 1 and gene["snippet"] == VARIANT_LINE
    assert variant["value"] == "STXBP1 NM_003165.6:c.1631G>A"
    assert variant["payload"]["classification"] == "uncertain_significance"
    assert variant["payload"]["zygosity"] == "heterozygous"
    assert variant["payload"]["test_date"] == "2026-03-14"
    assert variant["payload"]["gene_id"] == "HGNC:11444"
    assert variant["vus_notice"] == VUS_NOTICE
    assert gene["vus_notice"] is None
    assert all(f["confirmed"] is None for f in findings)

    # The model never received personal data or the file name; it did get the medical content.
    sent = model_inputs(llm)
    assert len(sent) == 2
    for body in sent:
        for value in (*PII, FAKE_FILENAME):
            assert value not in body
    assert "<PERSON>" in sent[0] and "STXBP1" in sent[1]

    # Nothing raw (personal data, file name) reached the database.
    stored = await _rows(connect_as, user.id)
    for value in (*PII, FAKE_FILENAME, "mustermann"):
        assert value.lower() not in stored.lower()


async def test_grounding_drops_hallucinated_findings(make_user, llm):
    user = await make_user(consents=["upload"])
    extraction = {
        "variants": [
            # snippet is not in the document at all
            {
                **variant_extraction()["variants"][0],
                "gene": "SCN1A",
                "snippet": "Gene: SCN1A Variant: c.999A>T",
                "hgvs": "c.999A>T",
            },
            # snippet is real, but the HGVS string is not in it: variant dropped, gene kept
            {**variant_extraction()["variants"][0], "hgvs": "NM_003165.6:c.1000C>T"},
            # snippet is real, but on the wrong page
            {**variant_extraction()["variants"][0], "page": 2},
        ]
    }
    accepted = await _upload_report(user, llm, extraction)
    findings = (await user.client.get(f"/documents/{accepted['document_id']}/findings")).json()
    assert [(f["type"], f["value"]) for f in findings] == [("gene", "STXBP1")]


async def test_unsupported_classification_is_cleared(make_user, llm):
    user = await make_user(consents=["upload"])
    accepted = await _upload_report(
        user, llm, variant_extraction(classification="pathogenic", test_date="2020-01-01")
    )
    findings = (await user.client.get(f"/documents/{accepted['document_id']}/findings")).json()
    variant = next(f for f in findings if f["type"] == "variant")
    assert variant["payload"]["classification"] is None  # report says VUS, not pathogenic
    assert variant["payload"]["test_date"] is None
    assert variant["vus_notice"] is None


async def test_clinical_letter_docx_maps_to_mondo_and_hpo(make_user, llm):
    user = await make_user(consents=["upload"])
    lines = [
        "Neuropaediatric clinic letter",
        "Dear colleague, we saw Mr. Peter Example today.",
        "Diagnosis: Dravet syndrome",
        "Findings: frequent seizures and global developmental delay.",
        "No feeding difficulties.",
    ]
    llm.enqueue(
        {"json": {"doc_type": "clinical_letter"}},
        {
            "json": {
                "diagnoses": [
                    {"label": "Dravet syndrome", "page": 1, "snippet": "Diagnosis: Dravet syndrome"}
                ],
                "symptoms": [
                    {
                        "label": "Seizures",
                        "excluded": False,
                        "page": 1,
                        "snippet": "frequent seizures and global developmental delay",
                    },
                    {
                        "label": "Global developmental delay",
                        "excluded": False,
                        "page": 1,
                        "snippet": "frequent seizures and global developmental delay",
                    },
                    {
                        "label": "Feeding difficulties",
                        "excluded": True,
                        "page": 1,
                        "snippet": "No feeding difficulties.",
                    },
                    {
                        "label": "Hearing loss",
                        "excluded": False,
                        "page": 1,
                        "snippet": "Hearing loss was noted.",
                    },
                ],
            }
        },
    )
    resp = await upload(user, docx_bytes(lines), "letter.docx", "application/octet-stream")
    assert resp.status_code == 202
    doc_id = resp.json()["document_id"]
    findings = (await user.client.get(f"/documents/{doc_id}/findings")).json()
    ids = {f["normalized_id"]: f for f in findings}
    assert ids["MONDO:0100135"]["type"] == "disease"
    assert ids["HP:0001250"]["type"] == "phenotype"
    assert ids["HP:0001263"]["type"] == "phenotype"
    assert ids["HP:0011968"]["payload"]["excluded"] is True
    assert not any(f["value"] == "Hearing loss" for f in findings)  # not in the document
    assert "Peter Example" not in json.dumps(model_inputs(llm))


@pytest.mark.skipif(not tesseract_path(), reason="tesseract not installed")
async def test_photo_is_ocred_locally(make_user, llm):
    user = await make_user(consents=["upload"])
    lines = ["Genetic Test Report", "Gene STXBP1 heterozygous variant c.1631G>A"]
    snippet = "Gene STXBP1 heterozygous variant c.1631G>A"
    extraction = variant_extraction(
        hgvs="c.1631G>A", snippet=snippet, classification=None, test_date=None
    )
    accepted = await _upload_report(
        user, llm, extraction, data=text_image(lines), filename="photo.png", ctype="image/png"
    )
    findings = (await user.client.get(f"/documents/{accepted['document_id']}/findings")).json()
    assert {f["type"] for f in findings} == {"gene", "variant"}
    for body in llm.state.recorded("responses"):
        assert "input_image" not in json.dumps(body)  # no image ever leaves the server


async def test_plain_text_upload(make_user, llm):
    user = await make_user(consents=["upload"])
    accepted = await _upload_report(
        user, llm, data="\n".join(REPORT_LINES).encode(), filename="r.txt", ctype="text/plain"
    )
    findings = (await user.client.get(f"/documents/{accepted['document_id']}/findings")).json()
    assert len(findings) == 2


async def test_failure_records_code_and_deletes_raw(make_user, llm, connect_as):
    user = await make_user(consents=["upload"])
    llm.configure(fail_mode="usage_limit")
    resp = await upload(user, text_pdf())
    accepted = resp.json()
    events = await job_events(user, accepted["job_id"])
    assert events[-1] == {
        "type": "error",
        "job_id": accepted["job_id"],
        "code": "rate_limited",
        "message": documents.JOB_ERRORS["llm_usage_limit_exceeded"][1],
    }
    doc = (await user.client.get("/documents")).json()[0]
    assert doc["status"] == "failed"
    assert doc["raw_deleted_at"] is not None
    stored = await _rows(connect_as, user.id)
    assert '"error":"llm_usage_limit_exceeded"' in stored
    for value in (*PII, FAKE_FILENAME):
        assert value not in stored


async def test_reauth_maps_to_sign_in_required(make_user, llm):
    user = await make_user(consents=["upload"])
    llm.enqueue({"error": {"status": 401, "code": "token_expired"}})
    accepted = (await upload(user, text_pdf())).json()
    events = await job_events(user, accepted["job_id"])
    assert events[-1]["code"] == "sign_in_required"


async def test_no_text_document_fails_cleanly(make_user, llm):
    user = await make_user(consents=["upload"])
    accepted = (await upload(user, text_pdf([" "]))).json()
    events = await job_events(user, accepted["job_id"])
    if tesseract_path():
        assert events[-1]["type"] == "error"
        assert events[-1]["code"] == "bad_request"
    assert llm.state.recorded("responses") == []


async def test_cancellation_still_deletes_raw(make_user, llm, monkeypatch):
    user = await make_user(consents=["upload"])
    async with user_transaction(user.id) as db:
        doc = DocumentRecord(user_id=user.id, status="queued", page_count=1)
        db.add(doc)
        await db.flush()
        job = JobRecord(
            user_id=user.id,
            kind="document_extraction",
            status="queued",
            result={"stage": "queued"},
            document_id=doc.id,
        )
        db.add(job)
        await db.flush()
        doc_id, job_id = doc.id, job.id

    started = asyncio.Event()

    async def _slow(kind, data):
        started.set()
        await asyncio.sleep(30)

    monkeypatch.setattr(documents, "extract_pages", _slow)
    task = asyncio.create_task(documents.process_document(job_id, doc_id, user.id, text_pdf()))
    await asyncio.wait_for(started.wait(), 10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with user_transaction(user.id) as db:
        doc = await db.get(DocumentRecord, doc_id)
        job = await db.get(JobRecord, job_id)
        assert doc.raw_deleted_at is not None
        assert doc.status == "failed"
        assert job.error == "cancelled"


async def test_owner_only_access(make_user, llm):
    alice = await make_user(consents=["upload"])
    bob = await make_user(consents=["upload"])
    accepted = await _upload_report(alice, llm)
    doc_id, job_id = accepted["document_id"], accepted["job_id"]
    findings = (await alice.client.get(f"/documents/{doc_id}/findings")).json()

    assert (await bob.client.get("/documents")).json() == []
    assert (await bob.client.get(f"/documents/{doc_id}/findings")).status_code == 404
    assert (await bob.client.get(f"/jobs/{job_id}")).status_code == 404
    assert (await bob.client.delete(f"/documents/{doc_id}")).status_code == 404
    for action in ("confirm", "reject"):
        resp = await bob.client.post(f"/findings/{findings[0]['id']}/{action}")
        assert resp.status_code == 404
    assert (await bob.client.get(f"/jobs/{uuid.uuid4()}")).status_code == 404
    assert len((await alice.client.get(f"/documents/{doc_id}/findings")).json()) == 2


async def test_guest_cannot_read(client):
    assert (await client.get("/documents")).status_code == 401
    assert (await client.get(f"/jobs/{uuid.uuid4()}")).status_code == 401
    assert (await client.post(f"/findings/{uuid.uuid4()}/confirm")).status_code == 401
