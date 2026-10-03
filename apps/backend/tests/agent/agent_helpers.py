"""Shared helpers for tests/agent (importable: pytest puts this directory on sys.path)."""

import json

import httpx

from backend.fixtures.load import read_fixture

DEMO = read_fixture()["demo"]


def parse_sse(body: str) -> list[dict]:
    events = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        data = [line[5:].strip() for line in block.split("\n") if line.startswith("data:")]
        if data:
            events.append(json.loads("\n".join(data)))
    return events


async def post_sse(client: httpx.AsyncClient, url: str, payload: dict) -> tuple[int, list[dict]]:
    resp = await client.post(url, json=payload, timeout=120)
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        return resp.status_code, parse_sse(resp.text)
    return resp.status_code, [resp.json()]
