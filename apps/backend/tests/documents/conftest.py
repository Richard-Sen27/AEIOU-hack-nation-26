import pytest

from backend.devtools.mock_openai.fixtures import (  # noqa: F401
    _mock_openai_server,
    mock_openai,
    mock_openai_env,
)


@pytest.fixture
def llm(mock_openai_env, monkeypatch):  # noqa: F811
    """Point llm_for_user at the mock; returns the mock server."""
    from backend.api.services import auth
    from backend.llm import LLMClient, StaticToken

    async def _llm_for_user(user_id):
        return LLMClient(StaticToken("mock-static-test"), base_url=mock_openai_env.api_base)

    monkeypatch.setattr(auth, "llm_for_user", _llm_for_user)
    return mock_openai_env
