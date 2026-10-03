"""Pytest fixtures for the mock. In a test module or conftest:

    from backend.devtools.mock_openai.fixtures import mock_openai, mock_openai_env  # noqa: F401

`mock_openai` is one server per session, reset before each test. `mock_openai_env` additionally
points OPENAI_AUTH_ISSUER / OPENAI_API_BASE_URL (and a fresh TOKEN_ENCRYPTION_KEY) at it and
clears the cached settings.
"""

from collections.abc import Iterator

import pytest

from backend.devtools.mock_openai.server import MockOpenAIServer


@pytest.fixture(scope="session")
def _mock_openai_server() -> Iterator[MockOpenAIServer]:
    server = MockOpenAIServer().start()
    yield server
    server.stop()


@pytest.fixture
def mock_openai(_mock_openai_server: MockOpenAIServer) -> Iterator[MockOpenAIServer]:
    from backend.llm import client as llm_client

    _mock_openai_server.reset()
    llm_client._capabilities.clear()
    llm_client._models_cache.clear()
    yield _mock_openai_server
    _mock_openai_server.reset()


@pytest.fixture
def mock_openai_env(
    mock_openai: MockOpenAIServer, monkeypatch: pytest.MonkeyPatch
) -> Iterator[MockOpenAIServer]:
    from cryptography.fernet import Fernet

    from backend.openai_auth.settings import get_openai_settings

    monkeypatch.setenv("OPENAI_AUTH_ISSUER", mock_openai.issuer)
    monkeypatch.setenv("OPENAI_API_BASE_URL", mock_openai.api_base)
    monkeypatch.setenv("OPENAI_CLIENT_ID", "")
    monkeypatch.setenv("OPENAI_CLIENT_SECRET", "")
    monkeypatch.setenv("OPENAI_MODEL_MAIN", "")
    monkeypatch.setenv("OPENAI_MODEL_SMALL", "")
    monkeypatch.setenv("OPENAI_SCOPE", "")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_openai_settings.cache_clear()
    yield mock_openai
    get_openai_settings.cache_clear()
