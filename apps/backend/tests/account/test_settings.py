"""Onboarding settings, the 16+ gate and Global Privacy Control."""

from account_helpers import ASSET, assert_error


async def test_guest(client):
    assert_error(
        await client.patch("/me/settings", json={"language": "de"}), 401, "sign_in_required"
    )
    r = await client.get("/auth/session", headers={"Sec-GPC": "1"})
    assert r.json() == {**r.json(), "user": None, "gpc": True}


async def test_role_choice_and_expert_default(make_user):
    user = await make_user(role=None)
    r = await user.client.patch("/me/settings", json={"role": "patient"})
    assert r.json()["role"] == "patient" and r.json()["expert_mode"] is False
    r = await user.client.patch("/me/settings", json={"expert_mode": True})
    assert r.json()["expert_mode"] is True  # open to everyone
    r = await user.client.patch("/me/settings", json={"role": "researcher"})
    assert r.json()["expert_mode"] is True
    r = await user.client.patch("/me/settings", json={"role": "doctor", "expert_mode": False})
    assert r.json()["role"] == "doctor" and r.json()["expert_mode"] is False


async def test_validation(make_user):
    user = await make_user()
    for body in (
        {"role": "guest"},
        {"language": "not a language"},
        {"age_confirmed_16": False},
        {"role": "admin"},
    ):
        assert_error(await user.client.patch("/me/settings", json=body), 422, "validation_error")


async def test_age_gate(make_user, edge_ids):
    user = await make_user(age_confirmed=False, consents=["contribute"])
    gated = [
        user.client.put("/profile", json={"updated_at": None}),
        user.client.post(
            "/consents", json={"consent_type": "health_data", "version": "health-data-2026-10-04"}
        ),
        user.client.post("/contributions", json=ASSET),
        user.client.post(f"/edges/{edge_ids[0]}/flag", json={"reason": "Wrong direction"}),
        user.client.post("/chat", json={"message": "hello"}),
        user.client.post("/documents", files={"file": ("a.txt", b"x", "text/plain")}),
        user.client.get("/chat/sessions"),
    ]
    for request in gated:
        assert_error(await request, 403, "age_confirmation_required")

    # Onboarding, withdrawal and data rights stay available.
    for request in (
        user.client.get("/auth/session"),
        user.client.get("/profile"),
        user.client.get("/consents"),
        user.client.get("/contributions"),
        user.client.get("/me/export"),
    ):
        assert (await request).status_code == 200
    assert (await user.client.delete("/consents/contribute")).status_code == 204

    r = await user.client.patch("/me/settings", json={"age_confirmed_16": True})
    assert r.json()["age_confirmed"] is True
    r = await user.client.post(
        "/consents", json={"consent_type": "health_data", "version": "health-data-2026-10-04"}
    )
    assert r.status_code == 201


async def test_gpc_recorded_and_reported(make_user, superuser):
    user = await make_user()
    r = await user.client.get("/auth/session")
    assert r.json()["gpc"] is False and r.json()["user"]["gpc_opt_out"] is False

    await user.client.get("/consents", headers={"Sec-GPC": "1"})
    assert await superuser.fetchval("SELECT gpc_opt_out FROM profiles WHERE user_id = $1", user.id)
    r = await user.client.get("/auth/session")
    assert r.json()["gpc"] is False  # not on this request
    assert r.json()["user"]["gpc_opt_out"] is True  # but recorded
    export = (await user.client.get("/me/export")).json()
    assert export["settings"]["gpc_opt_out"] is True
