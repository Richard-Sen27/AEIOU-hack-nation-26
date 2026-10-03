import io
import json
import stat
from datetime import timedelta

import httpx
import pytest

from backend.llm import LLMClient, LLMError
from backend.openai_auth import OAuthError
from backend.openai_auth.cli import (
    FileTokenProvider,
    load_cli_token_provider,
    load_credentials,
    login,
    logout,
    save_credentials,
    status,
)


def _browser(user="alice", deny=False):
    """Headless browser: follow the authorize URL to the loopback callback."""

    async def open_url(url: str) -> None:
        extra = "&mock_decision=deny" if deny else f"&mock_user={user}"
        async with httpx.AsyncClient(follow_redirects=True) as client:
            await client.get(url + extra)

    return open_url


async def test_login_status_logout(tmp_path, oai_settings, mock_openai):
    path = tmp_path / "openai.json"
    out = io.StringIO()
    creds = await login(path=path, settings=oai_settings, port=0, opener=_browser(), out=out)
    assert creds.client_id.startswith("oaiapp_mock_")
    assert creds.ext_agent_host_id.startswith("urn:uuid:")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    raw = json.loads(path.read_text())
    assert raw["tokens"]["refresh_token"]
    assert "Signed in as alice@example.test" in out.getvalue()

    authorize = mock_openai.state.recorded("authorize")[-1]["params"]
    assert authorize["redirect_uri"].startswith("http://127.0.0.1:")
    assert authorize["redirect_uri"].endswith("/auth/callback")

    printed = io.StringIO()
    info = status(path=path, out=printed)
    assert info["signed_in"] and info["plan_usage"]
    assert raw["tokens"]["access_token"] not in printed.getvalue()

    # Second login reuses host id and issued client id (no new registration).
    creds2 = await login(path=path, settings=oai_settings, port=0, opener=_browser(), out=out)
    assert creds2.client_id == creds.client_id
    assert creds2.ext_agent_host_id == creds.ext_agent_host_id
    second = mock_openai.state.recorded("authorize")[-1]["params"]
    assert second["client_id"] == creds.client_id
    assert "agent_name_hint" not in second and "id_token_hint" in second

    import backend.openai_auth.cli as cli

    old = cli.get_openai_settings
    cli.get_openai_settings = lambda: oai_settings
    try:
        await logout(path=path, out=out)
    finally:
        cli.get_openai_settings = old
    after = load_credentials(path)
    assert after.tokens is None and after.client_id == creds.client_id
    assert mock_openai.state.recorded("revoke")
    assert load_cli_token_provider(path) is None


async def test_login_denied(tmp_path, oai_settings):
    with pytest.raises(OAuthError) as exc:
        await login(
            path=tmp_path / "c.json",
            settings=oai_settings,
            port=0,
            opener=_browser(deny=True),
            out=io.StringIO(),
        )
    assert exc.value.code == "denied"
    assert load_credentials(tmp_path / "c.json").tokens is None


async def test_login_reregisters_when_saved_client_rejected(tmp_path, oai_settings, mock_openai):
    path = tmp_path / "c.json"
    first = await login(
        path=path, settings=oai_settings, port=0, opener=_browser("alice"), out=io.StringIO()
    )
    # Bob signs in on the same machine: alice's issued client id is rejected for him.
    second = await login(
        path=path, settings=oai_settings, port=0, opener=_browser("bob"), out=io.StringIO()
    )
    assert second.client_id != first.client_id
    assert second.email == "bob@example.test"


async def test_file_token_provider_refreshes_when_due(tmp_path, oai_settings, mock_openai):
    path = tmp_path / "c.json"
    await login(path=path, settings=oai_settings, port=0, opener=_browser(), out=io.StringIO())
    creds = load_credentials(path)
    creds.tokens.issued_at -= timedelta(hours=1)
    creds.tokens.expires_at = creds.tokens.issued_at + timedelta(minutes=61)
    save_credentials(creds, path)
    before = load_credentials(path).tokens
    provider = FileTokenProvider(path, settings=oai_settings)
    token = await provider.get_token()
    after = load_credentials(path).tokens
    assert token == after.access_token != before.access_token
    assert after.refresh_token != before.refresh_token

    llm = LLMClient(provider, base_url=oai_settings.api_base_url)
    assert (await llm.resolve_model("main")) == "gpt-mock-main"


async def test_file_token_provider_reauth_on_dead_refresh(tmp_path, oai_settings, mock_openai):
    path = tmp_path / "c.json"
    await login(path=path, settings=oai_settings, port=0, opener=_browser(), out=io.StringIO())
    mock_openai.configure(fail_refresh=True)
    provider = FileTokenProvider(path, settings=oai_settings)
    with pytest.raises(LLMError) as exc:
        await provider.force_refresh()
    assert exc.value.code == "reauth_required"
    assert load_credentials(path).tokens is None


def test_save_credentials_permissions(tmp_path):
    from backend.openai_auth.cli import Credentials

    path = tmp_path / "nested" / "c.json"
    save_credentials(Credentials(ext_agent_host_id="urn:uuid:x"), path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
