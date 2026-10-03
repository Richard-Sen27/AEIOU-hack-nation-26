import pytest
import respx

from backend.devtools.mock_openai.fixtures import (  # noqa: F401
    _mock_openai_server,
    mock_openai,
    mock_openai_env,
)

PUBLIC_IP = "93.184.215.14"
HOSTS = {"example.org": [PUBLIC_IP], "papers.example.org": [PUBLIC_IP]}


@pytest.fixture
def resolver(monkeypatch):
    """Deterministic DNS for fetch_page: test hosts map to addresses from this dict."""
    from backend.api.services.gap_search import fetch

    table = dict(HOSTS)

    async def _resolve(host, port):
        if host not in table:
            raise OSError("unknown host")
        return table[host]

    monkeypatch.setattr(fetch, "resolve_host", _resolve)
    return table


@pytest.fixture
def net(resolver):
    """respx router for outbound HTTP; local traffic (the mock OpenAI server) passes through."""
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        router.route(host="127.0.0.1").pass_through()
        yield router


@pytest.fixture
def llm(mock_openai_env, monkeypatch):  # noqa: F811
    from backend.api.ratelimit import limiter
    from backend.api.services import auth
    from backend.llm import LLMClient, StaticToken

    async def _llm_for_user(user_id):
        return LLMClient(StaticToken("mock-static-test"), base_url=mock_openai_env.api_base)

    monkeypatch.setattr(auth, "llm_for_user", _llm_for_user)
    limiter.reset()
    return mock_openai_env
