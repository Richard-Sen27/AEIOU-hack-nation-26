import time
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.openai_auth import (
    DYNAMIC_CLIENT_ID,
    PLAN_SCOPE,
    AuthTransaction,
    OAuthError,
    OIDCClient,
    TokenCryptoError,
    decrypt,
    encrypt,
    generate_key,
    new_host_id,
    validate_loopback_redirect,
)

REDIRECT = "http://127.0.0.1:1455/auth/callback"


async def _sign_in(
    oidc: OIDCClient, authorize, *, client_id=DYNAMIC_CLIENT_ID, user="alice", host=None
):
    disc = await oidc.discovery()
    tx = AuthTransaction.new(redirect_uri=REDIRECT, client_id=client_id)
    url = oidc.authorize_url(disc, tx, ext_agent_host_id=host or new_host_id())
    params = await authorize(url, user)
    assert params["state"] == tx.state
    issued = params.get("client_id", client_id)
    tokens, claims = await oidc.exchange_code(tx, params["code"], client_id=issued)
    return tx, params, tokens, claims


async def test_authorize_url_dynamic_registration(oai_settings):
    oidc = OIDCClient(oai_settings)
    disc = await oidc.discovery()
    tx = AuthTransaction.new(redirect_uri=REDIRECT, client_id=DYNAMIC_CLIENT_ID)
    url = oidc.authorize_url(disc, tx, ext_agent_host_id="urn:uuid:1234")
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert url.startswith(f"{oai_settings.issuer}/api/accounts/authorize?")
    assert q["client_id"] == DYNAMIC_CLIENT_ID
    assert q["scope"] == PLAN_SCOPE
    assert q["resource"] == oai_settings.api_base_url
    assert q["code_challenge_method"] == "S256"
    assert q["ext_agent_host_id"] == "urn:uuid:1234"
    assert q["agent_name_hint"] == "Amber Rare Disease Atlas"
    assert q["redirect_uri"] == REDIRECT
    assert "code_verifier" not in q

    tx2 = AuthTransaction.new(redirect_uri=REDIRECT, client_id="oaiapp_x")
    url2 = oidc.authorize_url(disc, tx2, ext_agent_host_id="urn:uuid:1234", id_token_hint="idt")
    q2 = parse_qs(urlsplit(url2).query)
    assert "agent_name_hint" not in q2
    assert q2["id_token_hint"] == ["idt"]


async def test_full_round_trip_and_reuse_of_issued_client(oai_settings, mock_openai, authorize):
    oidc = OIDCClient(oai_settings)
    host = new_host_id()
    _, params, tokens, claims = await _sign_in(oidc, authorize, host=host)
    issued = params["client_id"]
    assert issued.startswith("oaiapp_mock_")
    assert tokens.client_id == issued
    assert tokens.has_plan_usage and tokens.refresh_token
    assert claims.sub == "user-mock-alice-0001" and claims.email == "alice@example.test"

    _, params2, tokens2, claims2 = await _sign_in(oidc, authorize, client_id=issued, host=host)
    assert "client_id" not in params2
    assert tokens2.client_id == issued and claims2.sub == claims.sub
    token_calls = mock_openai.state.recorded("token")
    assert all("client_secret" not in c["fields"] for c in token_calls)
    assert all("code_verifier" in c["fields"] for c in token_calls)


async def test_denied_consent(oai_settings, authorize):
    oidc = OIDCClient(oai_settings)
    disc = await oidc.discovery()
    tx = AuthTransaction.new(redirect_uri=REDIRECT, client_id=DYNAMIC_CLIENT_ID)
    params = await authorize(
        oidc.authorize_url(disc, tx, ext_agent_host_id=new_host_id()), deny=True
    )
    assert params == {"error": "access_denied", "state": tx.state}


async def test_pkce_mismatch_rejected(oai_settings, authorize):
    oidc = OIDCClient(oai_settings)
    disc = await oidc.discovery()
    tx = AuthTransaction.new(redirect_uri=REDIRECT, client_id=DYNAMIC_CLIENT_ID)
    params = await authorize(oidc.authorize_url(disc, tx, ext_agent_host_id=new_host_id()))
    tx.code_verifier = "wrong" * 10
    with pytest.raises(OAuthError) as exc:
        await oidc.exchange_code(tx, params["code"], client_id=params["client_id"])
    assert exc.value.code == "invalid_grant"


async def test_code_is_single_use(oai_settings, authorize):
    oidc = OIDCClient(oai_settings)
    tx, params, _, _ = await _sign_in(oidc, authorize)
    with pytest.raises(OAuthError):
        await oidc.exchange_code(tx, params["code"], client_id=params["client_id"])


def _claims(mock, issuer, aud, nonce, over=None):
    now = int(time.time())
    claims = {"iss": issuer, "sub": "s1", "aud": aud, "iat": now, "exp": now + 600, "nonce": nonce}
    claims.update(over or {})
    return {k: v for k, v in claims.items() if v is not None}


@pytest.mark.parametrize(
    "case,reason",
    [
        ("signature", "signature"),
        ("issuer", "issuer"),
        ("audience", "audience"),
        ("nonce", "nonce"),
        ("expired", "expired"),
    ],
)
async def test_id_token_validation_failures(oai_settings, mock_openai, case, reason):
    oidc = OIDCClient(oai_settings)
    iss = oai_settings.issuer
    over: dict = {}
    key = None
    if case == "signature":
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    elif case == "issuer":
        over["iss"] = "https://evil.example"
    elif case == "audience":
        over["aud"] = "oaiapp_other"
    elif case == "nonce":
        over["nonce"] = "other-nonce"
    elif case == "expired":
        over["exp"] = int(time.time()) - 3600
    token = mock_openai.state.sign(_claims(mock_openai, iss, "oaiapp_me", "n1", over), key=key)
    with pytest.raises(OAuthError) as exc:
        await oidc.validate_id_token(token, client_id="oaiapp_me", nonce="n1")
    assert exc.value.code == "invalid_id_token"
    assert reason in str(exc.value)


async def test_id_token_valid(oai_settings, mock_openai):
    oidc = OIDCClient(oai_settings)
    token = mock_openai.state.sign(
        _claims(mock_openai, oai_settings.issuer, "oaiapp_me", "n1", {"email": "a@b.test"})
    )
    claims = await oidc.validate_id_token(token, client_id="oaiapp_me", nonce="n1")
    assert claims.sub == "s1" and claims.email == "a@b.test"


async def test_refresh_rotation_and_reuse_detection(oai_settings, mock_openai, authorize):
    oidc = OIDCClient(oai_settings)
    _, _, tokens, _ = await _sign_in(oidc, authorize)
    rotated = await oidc.refresh(tokens)
    assert rotated.refresh_token != tokens.refresh_token
    assert rotated.access_token != tokens.access_token
    assert rotated.id_token == tokens.id_token
    assert rotated.client_id == tokens.client_id
    with pytest.raises(OAuthError) as exc:
        await oidc.refresh(tokens)
    assert exc.value.reauth_required


async def test_revocation(oai_settings, mock_openai, authorize):
    oidc = OIDCClient(oai_settings)
    _, _, tokens, _ = await _sign_in(oidc, authorize)
    assert await oidc.revoke(tokens) is True
    with pytest.raises(OAuthError) as exc:
        await oidc.refresh(tokens)
    assert exc.value.reauth_required
    assert mock_openai.state.check_access_token(tokens.access_token) is None


async def test_partner_mode_uses_client_secret_basic(oai_settings, mock_openai, authorize):
    settings = oai_settings.model_copy(
        update={
            "openai_client_id": "mock_partner_client",
            "openai_client_secret": "mock_partner_secret",
        }
    )
    oidc = OIDCClient(settings)
    disc = await oidc.discovery()
    tx = AuthTransaction.new(
        redirect_uri="http://127.0.0.1:8000/auth/callback", client_id=oidc.default_client_id()
    )
    url = oidc.authorize_url(disc, tx)
    q = parse_qs(urlsplit(url).query)
    assert q["scope"] == ["openid profile email"]
    assert "ext_agent_host_id" not in q and "resource" not in q
    params = await authorize(url)
    tokens, claims = await oidc.exchange_code(tx, params["code"])
    assert tokens.client_id == "mock_partner_client"
    assert not tokens.has_plan_usage
    assert claims.sub == "user-mock-alice-0001"


def test_loopback_redirect_rules():
    validate_loopback_redirect("http://127.0.0.1:8000/auth/callback")
    for bad in (
        "http://localhost:8000/auth/callback",
        "http://127.0.0.1:8000/callback",
        "https://127.0.0.1:8000/auth/callback",
    ):
        with pytest.raises(ValueError):
            validate_loopback_redirect(bad)


def test_token_encryption_roundtrip():
    key = generate_key()
    ct = encrypt("secret-token", key=key)
    assert b"secret-token" not in ct
    assert decrypt(ct, key=key) == "secret-token"
    with pytest.raises(TokenCryptoError):
        decrypt(ct, key=generate_key())
    rotated = f"{generate_key()},{key}"
    assert decrypt(ct, key=rotated) == "secret-token"


def test_token_set_repr_hides_tokens():
    from datetime import UTC, datetime

    from backend.openai_auth import TokenSet

    ts = TokenSet(
        access_token="AT-SECRET",
        refresh_token="RT-SECRET",
        expires_at=datetime.now(UTC),
        client_id="c",
    )
    assert "SECRET" not in repr(ts) and "SECRET" not in str(ts)
