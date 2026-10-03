from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet

from backend.devtools.mock_openai.fixtures import (  # noqa: F401
    _mock_openai_server,
    mock_openai,
    mock_openai_env,
)
from backend.openai_auth.settings import OpenAISettings


@pytest.fixture
def oai_settings(mock_openai) -> OpenAISettings:  # noqa: F811
    return OpenAISettings(
        _env_file=None,
        openai_auth_issuer=mock_openai.issuer,
        openai_api_base_url=mock_openai.api_base,
        openai_client_id="",
        openai_client_secret="",
        openai_model_main="",
        openai_model_small="",
        openai_scope="",
        token_encryption_key=Fernet.generate_key().decode(),
    )


async def browser_authorize(url: str, user: str | None = "alice", deny: bool = False) -> dict:
    """Play the browser: hit the mock authorize URL and return the callback query params."""
    extra = "&mock_decision=deny" if deny else (f"&mock_user={user}" if user else "")
    async with httpx.AsyncClient() as client:
        resp = await client.get(url + extra, follow_redirects=False)
    assert resp.status_code == 302, resp.text
    location = resp.headers["location"]
    return {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}


@pytest.fixture
def authorize():
    return browser_authorize
