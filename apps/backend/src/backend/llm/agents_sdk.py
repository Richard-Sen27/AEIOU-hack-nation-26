"""OpenAI Agents SDK bound to an `LLMClient`'s bearer and base URL (for the gap-search agent).

Constraints of ChatGPT plan usage that callers must keep:
- run agents with `Runner.run_streamed(...)` only (plain `Runner.run` sends `stream=false`);
- function tools must be grouped in a namespace: wrap them with `namespaced_tools(...)`;
- do not set temperature, top_p, max_tokens, truncation, metadata or prompt_cache_retention
  in ModelSettings; `model_settings()` returns compatible settings (store=False).
Budgets (max steps via `max_turns`, wall clock via asyncio.timeout) stay the caller's job.
"""

from typing import Any

from agents import ModelSettings, OpenAIResponsesModel, RunConfig, set_tracing_disabled
from agents.tool import FunctionTool, tool_namespace
from openai import AsyncOpenAI

from backend.llm.client import TOOL_NAMESPACE, LLMClient, ModelKind

set_tracing_disabled(True)


async def build_agents_model(llm: LLMClient, *, kind: ModelKind = "main") -> OpenAIResponsesModel:
    """A Responses model for the Agents SDK using the user's current access token.

    The token is captured now (access tokens live 1 h), so build one per run."""
    slug = await llm.resolve_model(kind)
    client = AsyncOpenAI(api_key=await llm.bearer(), base_url=llm.base_url, max_retries=0)
    return OpenAIResponsesModel(model=slug, openai_client=client)


def model_settings(*, include_reasoning: bool = True, **overrides: Any) -> ModelSettings:
    settings: dict[str, Any] = {"store": False}
    if include_reasoning:
        settings["response_include"] = ["reasoning.encrypted_content"]
    settings.update(overrides)
    return ModelSettings(**settings)


def run_config(**overrides: Any) -> RunConfig:
    """RunConfig with SDK trace export disabled and plan-usage-compatible model settings."""
    return RunConfig(
        tracing_disabled=True,
        trace_include_sensitive_data=False,
        model_settings=overrides.pop("model_settings", None) or model_settings(),
        **overrides,
    )


def namespaced_tools(
    tools: list[FunctionTool],
    *,
    name: str = TOOL_NAMESPACE,
    description: str = "Amber rare-disease atlas tools",
) -> list[FunctionTool]:
    return tool_namespace(name=name, description=description, tools=tools)
