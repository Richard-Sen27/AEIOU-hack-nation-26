import httpx
import pytest

AUTH = {"Authorization": "Bearer mock-static-test"}
BASE = {"model": "gpt-mock-main", "input": [{"role": "user", "content": "hi"}]}


async def _post(mock, body, headers=AUTH):
    async with httpx.AsyncClient() as client:
        return await client.post(f"{mock.api_base}/responses", json=body, headers=headers)


@pytest.mark.parametrize(
    "body,param",
    [
        ({**BASE, "stream": True}, "store"),
        ({**BASE, "store": False}, "stream"),
        ({**BASE, "store": False, "stream": True, "temperature": 0.2}, "temperature"),
        ({**BASE, "store": False, "stream": True, "max_output_tokens": 10}, "max_output_tokens"),
        (
            {**BASE, "store": False, "stream": True, "previous_response_id": "r"},
            "previous_response_id",
        ),
        ({**BASE, "store": False, "stream": True, "input": "plain string"}, "input"),
        (
            {**BASE, "store": False, "stream": True, "input": [{"role": "system", "content": "s"}]},
            "input[0]",
        ),
        (
            {
                **BASE,
                "store": False,
                "stream": True,
                "tools": [{"type": "function", "name": "f", "parameters": {}}],
            },
            "tools",
        ),
        ({**BASE, "store": False, "stream": True, "tools": [{"type": "file_search"}]}, "tools"),
        (
            {
                **BASE,
                "store": False,
                "stream": True,
                "input": [{"type": "reasoning", "id": "rs_1", "summary": []}],
            },
            "input[0]",
        ),
    ],
)
async def test_rejects_requests_the_preview_rejects(mock_openai, body, param):
    resp = await _post(mock_openai, body)
    assert resp.status_code == 400
    assert resp.json()["error"]["param"] == param


async def test_streams_sse(mock_openai):
    resp = await _post(mock_openai, {**BASE, "store": False, "stream": True})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "response.output_text.delta" in resp.text and "response.completed" in resp.text


async def test_requires_valid_bearer(mock_openai):
    resp = await _post(mock_openai, {**BASE, "store": False, "stream": True}, headers={})
    assert resp.status_code == 401


async def test_control_endpoints(mock_openai):
    async with httpx.AsyncClient(base_url=mock_openai.url) as client:
        assert (await client.post("/_mock/queue", json={"text": "scripted"})).json()["queued"] == 1
        await client.post("/_mock/config", json={"stream_delay_s": 0})
        users = (await client.get("/_mock/users")).json()
        assert {u["key"] for u in users} == {"alice", "bob", "carol"}
    resp = await _post(mock_openai, {**BASE, "store": False, "stream": True})
    assert '"delta": "scripted"' in resp.text
    async with httpx.AsyncClient(base_url=mock_openai.url) as client:
        recorded = (await client.get("/_mock/requests", params={"kind": "responses"})).json()
    assert recorded[-1]["body"]["store"] is False


async def test_consent_page_without_mock_user(mock_openai, oai_settings):
    from backend.openai_auth import DYNAMIC_CLIENT_ID, AuthTransaction, OIDCClient, new_host_id

    oidc = OIDCClient(oai_settings)
    tx = AuthTransaction.new(
        redirect_uri="http://127.0.0.1:9/auth/callback", client_id=DYNAMIC_CLIENT_ID
    )
    url = oidc.authorize_url(await oidc.discovery(), tx, ext_agent_host_id=new_host_id())
    async with httpx.AsyncClient() as client:
        page = await client.get(url)
        bad = await client.get(url.replace("127.0.0.1%3A9", "localhost%3A9"))
    assert page.status_code == 200 and "development only" in page.text
    assert bad.status_code == 400
