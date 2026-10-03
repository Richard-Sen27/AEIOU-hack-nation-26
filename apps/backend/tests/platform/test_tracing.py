import subprocess
import sys

import pytest

from backend.observability import tracing


def test_noop_without_langfuse_env(monkeypatch):
    for var in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.setenv(var, "")
    tracing.get_tracer.cache_clear()
    tracer = tracing.get_tracer()
    assert not tracer.enabled
    with tracer.trace("turn", user_id="u1") as span:
        span.update(output="redacted", metadata={"cited_edge_ids": ["e_1"]}, usage={"input": 1})
        span.event("post_processor", {"removed": 1})
        with tracer.tool("tool:search") as child:
            child.update(metadata={"duration_ms": 1})
    tracer.flush()
    tracing.get_tracer.cache_clear()


def test_partial_env_stays_disabled(monkeypatch):
    monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:3999")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    tracing.get_tracer.cache_clear()
    assert not tracing.get_tracer().enabled
    tracing.get_tracer.cache_clear()


def test_span_reraises_and_marks_errors(monkeypatch):
    class Obs:
        def __init__(self):
            self.updates = []

        def update(self, **kw):
            self.updates.append(kw)

    class CM:
        def __init__(self, obs):
            self.obs = obs

        def __enter__(self):
            return self.obs

        def __exit__(self, *a):
            return False

    class Client:
        def __init__(self):
            self.obs = Obs()

        def start_as_current_observation(self, **kw):
            return CM(self.obs)

    client = Client()
    tracer = tracing.Tracer(client)
    with pytest.raises(ValueError):
        with tracer.span("x"):
            raise ValueError("boom")
    assert client.obs.updates[-1] == {"level": "ERROR", "status_message": "ValueError"}


def test_import_needs_no_network():
    code = (
        "import socket\n"
        "def deny(*a, **k): raise RuntimeError('network used')\n"
        "socket.socket.connect = deny\n"
        "import backend.observability.tracing as t, backend.llm, backend.openai_auth\n"
        "t.get_tracer()\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, env={"PATH": ""}, timeout=60)
