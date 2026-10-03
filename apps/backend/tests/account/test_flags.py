"""Edge flags: any signed-in user, one open flag per user and edge, visible to everyone."""

from account_helpers import assert_error

REASON = {"reason": "The cited paper does not support this relation"}


async def counts(superuser) -> dict[str, int]:
    return {
        r["edge_id"]: r["open_flags"]
        for r in await superuser.fetch("SELECT * FROM edge_flag_counts()")
    }


async def test_guest(client, edge_ids):
    assert_error(
        await client.post(f"/edges/{edge_ids[0]}/flag", json=REASON), 401, "sign_in_required"
    )


async def test_flag_marks_edge_under_review(make_user, edge_ids, superuser):
    edge = edge_ids[2]
    before = (await counts(superuser)).get(edge, 0)
    a = await make_user()  # no consent needed
    r = await a.client.post(f"/edges/{edge}/flag", json=REASON)
    assert r.status_code == 201, r.text
    assert r.json() == {"edge_id": edge, "status": "under_review", "open_flags": before + 1}
    assert (await counts(superuser))[edge] == before + 1

    assert_error(await a.client.post(f"/edges/{edge}/flag", json=REASON), 409, "conflict")

    b = await make_user(role="researcher")
    r = await b.client.post(f"/edges/{edge}/flag", json=REASON)
    assert r.json()["open_flags"] == before + 2

    export_a = (await a.client.get("/me/export")).json()["edge_flags"]
    export_b = (await b.client.get("/me/export")).json()["edge_flags"]
    assert len(export_a) == 1 and len(export_b) == 1 and export_a[0]["id"] != export_b[0]["id"]


async def test_unknown_edge(make_user):
    user = await make_user()
    assert_error(
        await user.client.post("/edges/e_doesnotexist/flag", json=REASON), 404, "not_found"
    )


async def test_reason_is_screened(make_user, edge_ids):
    user = await make_user()
    for reason in (
        "",
        "x" * 600,
        "My son John Smith has this",
        "mail me at a@b.example",
        "see https://tracker.example/me",
        "patient no. 12345678",
    ):
        r = await user.client.post(f"/edges/{edge_ids[0]}/flag", json={"reason": reason})
        assert_error(r, 422, "validation_error")
        assert "John" not in r.text
