from agent_helpers import DEMO

PATH = DEMO["path_edge_ids"]  # STXBP1 ~ SCN2A-DEE (inferred) -> org serves -> org runs registry


def _action(title, edge_ids, viable=True):
    return {
        "title": title,
        "type": "reuse_asset",
        "viable": viable,
        "edge_ids": edge_ids,
        "timeline_today": "Build a new registry: about 2 years",
        "timeline_proposed": "Join the existing registry: about 3 months",
        "assumptions": ["The registry accepts related diseases."],
    }


async def test_guest_gets_401(client):
    resp = await client.post("/proposal", json={"edge_ids": PATH})
    assert resp.status_code == 401


async def test_unknown_edge_404(make_user):
    user = await make_user(role="patient")
    resp = await user.client.post("/proposal", json={"edge_ids": ["e_ffffffffffff"]})
    assert resp.status_code == 404


async def test_proposal_content(make_user):
    user = await make_user(role="patient")
    body = {"edge_ids": PATH, "actions": [_action("Reuse the registry", PATH[1:])]}
    resp = await user.client.post("/proposal", json=body)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    html = resp.text
    assert html.startswith("<!doctype html>") and "@page" in html
    assert "<script" not in html and "<link" not in html and "src=" not in html
    assert "Who is connected and why" in html and "Hypothesis" in html and "Data" in html
    for eid in PATH:
        assert eid in html
    assert "Sodium Channel Epilepsy Registry" in html  # reusable asset
    assert "SCN2A Community Alliance" in html  # public contact
    assert "Viable lead" in html
    assert "Build a new registry: about 2 years" in html
    assert "Join the existing registry: about 3 months" in html
    assert "Not medical advice" in html
    assert "Data version" in html and "fixture" in html
    assert "AI system" in html
    again = await user.client.post("/proposal", json=body)
    assert again.text == html  # deterministic


async def test_viability_recomputed_and_escaped(make_user):
    user = await make_user(role="doctor")
    evil = '<img src=x onerror="alert(1)">'
    body = {
        "edge_ids": PATH,
        "title": f"Plan {evil}",
        "actions": [_action(f"Use hypothesis {evil}", PATH[:1], viable=True)],
    }
    resp = await user.client.post("/proposal", json=body)
    html = resp.text
    assert evil not in html and "<img" not in html
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html
    assert "Unsupported lead" in html and "Viable lead" not in html


async def test_german_lens(make_user):
    user = await make_user(role="patient")
    resp = await user.client.post("/proposal", json={"edge_ids": PATH, "language": "de"})
    assert "Keine medizinische Beratung" in resp.text and 'lang="de"' in resp.text
