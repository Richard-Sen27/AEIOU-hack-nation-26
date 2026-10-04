"""LLM access for the pipeline, on the pipeline user's own ChatGPT plan.

`login` / `logout` / `whoami` delegate to `backend.openai_auth.cli`. `get_llm()` returns an
`LLMClient` bound to the stored credentials, or None when nobody is logged in. `LLMRun` wraps it
for bulk extraction: a disk cache under data/cache/llm (re-runs cost nothing, and cached results
are served even without a login), a concurrency limit and a hard per-run call budget. When the
budget or the plan's usage limit is hit, it stops calling and lets the build continue.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from pipeline.config import settings
from pipeline.paths import CACHE, ENV_FILE

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
LLM_CACHE = CACHE / "llm"
STOP_CODES = {"usage_limit_exceeded", "usage_unavailable", "reauth_required"}


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIPELINE_LLM_", env_file=ENV_FILE, extra="ignore")

    max_calls: int = 300  # uncached model calls per run; cache hits are free
    disabled: bool = False


def _auth_cli(*args: str) -> int:
    cmd = [sys.executable, "-m", "backend.openai_auth.cli", *args]
    try:
        return subprocess.run(cmd).returncode
    except FileNotFoundError:
        log.error("could not run %s", " ".join(cmd))
        return 1


def login() -> None:
    """Sign in with ChatGPT once; LLM steps then run on your plan."""
    if _auth_cli("login") != 0:
        raise SystemExit(1)


def logout() -> None:
    if _auth_cli("logout") != 0:
        raise SystemExit(1)


def whoami() -> None:
    if _auth_cli("status") != 0:
        raise SystemExit(1)


def get_llm():
    """An `LLMClient` on the logged-in user's plan, or None (not logged in / auth unavailable)."""
    if LLMSettings().disabled:
        return None
    try:
        from backend.llm import LLMClient
        from backend.openai_auth.cli import load_cli_token_provider
    except ImportError as exc:
        log.debug("LLM login not available: %s", exc)
        return None
    try:
        provider = load_cli_token_provider()
    except (Exception, SystemExit) as exc:  # unreadable credentials behave like no login
        log.warning("could not load ChatGPT credentials (%s)", type(exc).__name__)
        return None
    return LLMClient(provider) if provider is not None else None


def cache_key(kind: str, schema: type[BaseModel], instructions: str, input: Any) -> str:
    payload = json.dumps(
        {
            "kind": kind,
            "schema": schema.model_json_schema(),
            "instructions": instructions,
            "input": input,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class LLMRun:
    """One extraction run: cache, concurrency limit, budget and stop-on-usage-limit."""

    client: Any | None
    max_calls: int
    concurrency: int = 8
    calls: int = 0
    cache_hits: int = 0
    skipped: int = 0
    errors: Counter = field(default_factory=Counter)
    stop_reason: str | None = None
    _sem: asyncio.Semaphore | None = None

    @classmethod
    def start(cls, client: Any | None = None, max_calls: int | None = None) -> LLMRun:
        client = client if client is not None else get_llm()
        run = cls(
            client=client,
            max_calls=LLMSettings().max_calls if max_calls is None else max_calls,
            concurrency=settings.llm_concurrency,
        )
        if client is None:
            log.warning(
                "LLM extraction: not logged in with ChatGPT, using cached results only "
                "(run `atlas-pipeline login` to extract new ones)"
            )
        return run

    @property
    def mode(self) -> str:
        return "cache_only" if self.client is None else "live"

    @property
    def can_call(self) -> bool:
        return self.client is not None and self.stop_reason is None

    async def structured(
        self, schema: type[T], *, instructions: str, input: str, kind: str = "small"
    ) -> T | None:
        key = cache_key(kind, schema, instructions, input)
        path = LLM_CACHE / key[:2] / f"{key}.json"
        if path.exists():
            try:
                out = schema.model_validate(json.loads(path.read_text())["output"])
                self.cache_hits += 1
                return out
            except Exception:
                path.unlink(missing_ok=True)
        if self._sem is None:
            self._sem = asyncio.Semaphore(max(1, self.concurrency))
        async with self._sem:
            if not self.can_call:
                self.skipped += 1
                return None
            if self.calls >= self.max_calls:
                self._stop("budget", f"call budget of {self.max_calls} reached")
                self.skipped += 1
                return None
            self.calls += 1
            try:
                out = await self.client.structured(
                    schema, instructions=instructions, input=input, kind=kind
                )
            except Exception as exc:
                code = getattr(exc, "code", None) or type(exc).__name__
                self.errors[code] += 1
                if code in STOP_CODES:
                    self._stop(code, f"ChatGPT plan reported {code}")
                return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"kind": kind, "output": out.model_dump(mode="json")}))
        return out

    def _stop(self, reason: str, message: str) -> None:
        if self.stop_reason is None:
            self.stop_reason = reason
            log.warning("LLM extraction stopped: %s; keeping what was extracted", message)

    def summary(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "llm_calls": self.calls,
            "cache_hits": self.cache_hits,
            "skipped_uncached": self.skipped,
            "errors": dict(self.errors),
            "stop_reason": self.stop_reason,
            "max_calls": self.max_calls,
        }

    def log_summary(self) -> None:
        log.info("LLM run: %s", self.summary())
