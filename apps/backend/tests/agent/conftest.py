from collections.abc import Callable

import pytest

from backend.devtools.mock_openai.fixtures import (  # noqa: F401
    _mock_openai_server,
    mock_openai,
    mock_openai_env,
)
from backend.llm import LLMClient, StaticToken


@pytest.fixture
def llm_calls(mock_openai_env) -> Callable[[], list[dict]]:  # noqa: F811
    """Request bodies the mock /v1/responses endpoint received."""
    return lambda: [r["body"] for r in mock_openai_env.state.recorded("responses")]


@pytest.fixture
def user_llm(mock_openai_env, monkeypatch):  # noqa: F811
    """Route llm_for_user to the mock (no stored tokens needed); returns the mock server."""
    from backend.api.services import auth

    async def _fake(user_id):
        return LLMClient(StaticToken("mock-static-test"), base_url=mock_openai_env.api_base)

    monkeypatch.setattr(auth, "llm_for_user", _fake)
    return mock_openai_env


@pytest.fixture
def mock_llm(mock_openai_env) -> LLMClient:  # noqa: F811
    return LLMClient(StaticToken("mock-static-test"), base_url=mock_openai_env.api_base)
