import httpx
import pytest

from pipeline import http as phttp


class _Flaky(httpx.AsyncBaseTransport):
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = 0

    async def handle_async_request(self, request):
        self.calls += 1
        return httpx.Response(self.statuses.pop(0), content=b"ok")


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(phttp, "wait_exponential_jitter", lambda **_: lambda rs: 0)
    monkeypatch.setattr(phttp, "rate_for", lambda source: 1000.0)
    phttp._limiters.clear()


async def test_429_then_200_is_retried():
    inner = _Flaky([429, 200])
    transport = phttp._LimitedRetryingTransport("test", inner)
    async with httpx.AsyncClient(transport=transport) as client:
        r = await client.get("https://example.org/x")
    assert r.status_code == 200
    assert inner.calls == 2


async def test_persistent_503_raises_transient():
    inner = _Flaky([503] * 10)
    transport = phttp._LimitedRetryingTransport("test", inner)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(phttp.TransientHTTPError):
            await client.get("https://example.org/x")
