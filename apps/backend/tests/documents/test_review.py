from docfiles import job_events, text_pdf, upload, variant_extraction

GENETIC = {"json": {"doc_type": "genetic_report"}}

PAPER_LINES = [
    "Journal of Synthetic Neurology, doi: 10.1234/jsn.2026.001",
    "Abstract",
    "We show that Dravet syndrome is caused by variants in SCN1A in most patients.",
    "Methods and results follow.",
]
PAPER_QUOTE = "We show that Dravet syndrome is caused by variants in SCN1A in most patients."


async def _report(user, llm):
    llm.enqueue(GENETIC, {"json": variant_extraction()})
    accepted = (await upload(user, text_pdf())).json()
    findings = (await user.client.get(f"/documents/{accepted['document_id']}/findings")).json()
    return accepted["document_id"], {f["type"]: f for f in findings}


async def _paper(user, llm):
    llm.enqueue(
        {"json": {"doc_type": "research_paper"}},
        {
            "json": {
                "relations": [
                    {
                        "subject": "Dravet syndrome",
                        "relation": "caused_by_variant_in",
                        "object": "SCN1A",
                        "page": 1,
                        "quote": PAPER_QUOTE,
                    },
                    {
                        "subject": "Dravet syndrome",
                        "relation": "has_phenotype",
                        "object": "Ataxia",
                        "page": 1,
                        "quote": "Ataxia is common in Dravet syndrome.",
                    },
                ]
            }
        },
    )
    accepted = (await upload(user, text_pdf(PAPER_LINES))).json()
    return (await user.client.get(f"/documents/{accepted['document_id']}/findings")).json()


async def test_nothing_unconfirmed_reaches_profile(make_user, llm):
    user = await make_user(consents=["health_data"])
    await _report(user, llm)
    profile = (await user.client.get("/profile")).json()
    assert profile["genes"] == [] and profile["variants"] == []


async def test_confirm_merges_and_is_idempotent(make_user, llm):
    user = await make_user(consents=["health_data"])
    _, f = await _report(user, llm)

    resp = await user.client.post(f"/findings/{f['variant']['id']}/confirm")
    assert resp.status_code == 200
    profile = resp.json()
    assert len(profile["variants"]) == 1
    v = profile["variants"][0]
    assert v["source"] == "document" and v["finding_id"] == f["variant"]["id"]
    assert v["hgvs"] == "NM_003165.6:c.1631G>A"
    assert v["classification"] == "uncertain_significance"
    assert v["gene_id"] == "HGNC:11444"
    assert v["test_date"] == "2026-03-14"
    assert profile["genes"] == []  # the gene finding is reviewed on its own

    again = (await user.client.post(f"/findings/{f['variant']['id']}/confirm")).json()
    assert again["variants"] == profile["variants"]

    profile = (await user.client.post(f"/findings/{f['gene']['id']}/confirm")).json()
    assert [(g["id"], g["label"], g["source"]) for g in profile["genes"]] == [
        ("HGNC:11444", "STXBP1", "document")
    ]
    findings = (await user.client.get(f"/documents/{f['gene']['document_id']}/findings")).json()
    assert all(x["confirmed"] is True and x["decided_at"] for x in findings)


async def test_reject_keeps_out_and_removes_after_confirm(make_user, llm):
    user = await make_user(consents=["health_data"])
    _, f = await _report(user, llm)
    profile = (await user.client.post(f"/findings/{f['gene']['id']}/reject")).json()
    assert profile["genes"] == []
    assert (await user.client.post(f"/findings/{f['gene']['id']}/reject")).status_code == 200

    await user.client.post(f"/findings/{f['variant']['id']}/confirm")
    profile = (await user.client.post(f"/findings/{f['variant']['id']}/reject")).json()
    assert profile["variants"] == []
    findings = (await user.client.get(f"/documents/{f['gene']['document_id']}/findings")).json()
    assert {x["confirmed"] for x in findings} == {False}


async def test_delete_cascades_to_findings_jobs_and_profile(make_user, llm, connect_as):
    user = await make_user(consents=["health_data"])
    doc_id, f = await _report(user, llm)
    await user.client.post(f"/findings/{f['gene']['id']}/confirm")
    await user.client.post(f"/findings/{f['variant']['id']}/confirm")
    # an item from chat stays
    profile = (await user.client.get("/profile")).json()
    profile["diseases"] = [{"id": "MONDO:0100135", "label": "Dravet syndrome", "source": "chat"}]
    assert (await user.client.put("/profile", json=profile)).status_code == 200

    assert (await user.client.delete(f"/documents/{doc_id}")).status_code == 204
    assert (await user.client.get("/documents")).json() == []
    assert (await user.client.get(f"/documents/{doc_id}/findings")).status_code == 404
    profile = (await user.client.get("/profile")).json()
    assert profile["genes"] == [] and profile["variants"] == []
    assert [d["id"] for d in profile["diseases"]] == ["MONDO:0100135"]
    conn = await connect_as("atlas")
    for table in ("findings", "jobs", "documents"):
        n = await conn.fetchval(f"SELECT count(*) FROM {table} WHERE user_id = $1", user.id)
        assert n == 0, table
    assert (await user.client.delete(f"/documents/{doc_id}")).status_code == 404


async def test_research_paper_candidate_edges_stay_private_without_consent(make_user, llm):
    user = await make_user(role="researcher", consents=["health_data"])
    findings = await _paper(user, llm)
    assert len(findings) == 1  # the ataxia quote is not in the paper
    edge = findings[0]
    assert edge["type"] == "candidate_edge"
    assert edge["payload"]["source_id"] == "MONDO:0100135"
    assert edge["payload"]["target_id"] == "HGNC:10585"
    assert edge["payload"]["relation"] == "caused_by_variant_in"
    assert edge["payload"]["origin"] == "user_contributed"
    assert edge["payload"]["status"] == "pending_review"
    assert edge["payload"]["source_id_ref"] == "DOI:10.1234/jsn.2026.001"

    profile = (await user.client.post(f"/findings/{edge['id']}/confirm")).json()
    assert profile["diseases"] == [] and profile["genes"] == []
    assert (await user.client.get("/contributions")).json() == []


async def test_confirmed_candidate_edge_becomes_contribution_with_consent(make_user, llm):
    user = await make_user(role="researcher", consents=["health_data", "contribute"])
    edge = (await _paper(user, llm))[0]
    await user.client.post(f"/findings/{edge['id']}/confirm")
    await user.client.post(f"/findings/{edge['id']}/confirm")  # idempotent
    contributions = (await user.client.get("/contributions")).json()
    assert len(contributions) == 1
    c = contributions[0]
    assert c["kind"] == "candidate_edge" and c["status"] == "pending_review"
    assert c["origin"] == "user_contributed"
    assert c["payload"]["source_id"] == "MONDO:0100135"

    # rejecting withdraws the contribution again
    await user.client.post(f"/findings/{edge['id']}/reject")
    assert (await user.client.get("/contributions")).json() == []


async def test_job_stream_reports_stages(make_user, llm):
    user = await make_user(consents=["health_data"])
    llm.enqueue(GENETIC, {"json": variant_extraction()})
    accepted = (await upload(user, text_pdf())).json()
    events = await job_events(user, accepted["job_id"])
    assert events[-2] == {
        "type": "progress",
        "job_id": accepted["job_id"],
        "stage": "done",
        "percent": 100,
    }
    assert events[-1]["type"] == "done"
