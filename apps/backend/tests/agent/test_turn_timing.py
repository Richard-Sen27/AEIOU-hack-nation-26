"""Turn deadline and the per-step timing log (names and numbers only)."""

import logging
import re
from pathlib import Path

import pytest
from agent_helpers import post_sse

from backend.api.services.chat import agent
from backend.llm import LLMClient

MESSAGE = "STXBP1 encephalopathy and seizures, my daughter Anna is 4"
STEP = re.compile(
    r"^chat step kind=(model|tool|check|prep|budget) name=[a-z_]+(:[A-Za-z0-9_-]+)?"
    r"( model=[A-Za-z0-9._-]+)? duration_ms=\d+ elapsed_ms=\d+( error=[A-Za-z_]+)?$"
)
TURN = re.compile(
    r"^chat turn outcome=(answered|partial|deadline|error|cancelled) total_ms=\d+ model_calls=\d+"
    r" tool_calls=\d+( error=[A-Za-z_]+)?$"
)
SPEC = Path(__file__).resolve().parents[4] / "docs" / "specs" / "agent.md"


@pytest.fixture
async def doctor(make_user, user_llm):
    return await make_user(role="doctor", consents=["health_data"])


@pytest.fixture
def timing(caplog):
    caplog.set_level(logging.INFO, logger=agent.timing_log.name)
    return lambda: [r.getMessage() for r in caplog.records if r.name == agent.timing_log.name]


async def test_turn_budget_and_deadline(doctor, user_llm, monkeypatch):
    assert agent.TURN_DEADLINE_S == 90.0
    assert (agent.MAX_TOOL_ROUNDS, agent.TOOL_PHASE_S) == (3, 15.0)
    assert "3 tool rounds and 15 s of tool work" in SPEC.read_text()
    assert "90 s deadline" in SPEC.read_text()
    seen = []
    original = LLMClient.run_tools

    async def spy(self, **kwargs):
        seen.append(kwargs)
        return await original(self, **kwargs)

    monkeypatch.setattr(LLMClient, "run_tools", spy)
    status, events = await post_sse(doctor.client, "/chat", {"message": "STXBP1"})
    assert status == 200 and events[-1]["type"] == "final"
    assert len(seen) == 1
    assert 85.0 < seen[0]["deadline_s"] <= 90.0  # what is left of the turn after the pre-step
    assert seen[0]["max_rounds"] == 3 and 10.0 < seen[0]["tools_for_s"] <= 15.0
    assert seen[0]["tool_effort"] == "low"


async def test_timing_log_per_step(doctor, user_llm, timing):
    status, events = await post_sse(doctor.client, "/chat", {"message": MESSAGE})
    assert status == 200 and events[-1]["type"] == "final"
    lines = timing()
    steps, turns = lines[:-1], lines[-1:]
    assert steps and all(STEP.match(line) for line in steps), lines
    assert len(turns) == 1 and TURN.match(turns[0]), lines
    assert turns[0].startswith("chat turn outcome=answered ")

    names = [line.split(" name=")[1].split(" ")[0] for line in steps]
    # Model list, then extraction and resolution before the first round of the main model.
    assert names[:4] == ["models", "structured:Extraction", "extract_entities", "resolve_to_ids"]
    assert names[4] == "tool_round"
    assert "search_graph" in names
    assert names[-1] == "postcheck"
    model_calls = sum(" kind=model " in line for line in steps)
    tool_calls = sum(" kind=tool " in line for line in steps)
    assert f"model_calls={model_calls} tool_calls={tool_calls}" in turns[0]

    elapsed = [int(re.search(r"elapsed_ms=(\d+)", line).group(1)) for line in steps]
    assert elapsed == sorted(elapsed)


async def test_timing_log_holds_no_content(doctor, user_llm, timing):
    status, events = await post_sse(doctor.client, "/chat", {"message": MESSAGE})
    reply = events[-1]["reply"]
    text = "\n".join(timing())
    assert text
    for word in ("STXBP1", "encephalopathy", "seizures", "daughter", "anna"):
        assert word.lower() not in text.lower()
    ids = {c["id"] for c in reply["chips"] if c["id"]}
    ids |= {e for c in reply["claims"] for e in c["edge_ids"]}
    ids |= {n for card in reply["cards"] for n in card["node_ids"]}
    assert ids and not any(i in text for i in ids)
    assert not re.search(r"[A-Z]+:\d", text)  # no CURIEs such as MONDO:… or HP:…
    assert str(doctor.id) not in text and doctor.sub not in text


async def test_timing_log_on_deadline(doctor, user_llm, monkeypatch, timing):
    monkeypatch.setattr(agent, "TURN_DEADLINE_S", 0.3)
    user_llm.configure(stream_delay_s=0.2)
    status, events = await post_sse(doctor.client, "/chat", {"message": MESSAGE})
    assert events[-1]["type"] == "error"
    lines = timing()
    assert lines[-1].startswith("chat turn outcome=deadline ")
    assert lines[-1].endswith(" error=timeout")
    assert any(" error=cancelled" in line for line in lines[:-1]), lines
    assert all(STEP.match(line) for line in lines[:-1]), lines
