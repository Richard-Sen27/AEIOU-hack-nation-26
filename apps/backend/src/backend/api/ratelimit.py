"""Rate limits and overload protection. Counters live in this process's memory (one API process
today; several instances would need a shared store, docs/homework.md).

Layers, each answering 429 `rate_limited` in the error envelope with `Retry-After`:

1. General: every API request per client (RATE_LIMIT_GENERAL), plus tighter limits on the
   expensive reads (READ_LIMITS). An app-wide dependency, `request_limits`.
2. Per route: the slowapi decorators on single routes (chat, uploads, gap search, calls, ...).
3. Model calls (`admit_model_request`): new explanations per account (EXPLAIN_LIMIT), runs at
   once per account and per process (MODEL_MAX_CONCURRENT*, answer "busy"), and, for accounts on
   the operator's OPENAI_API_KEY only, a daily budget per account (MODEL_DAILY_BUDGET) and per
   process (MODEL_DAILY_CEILING), answered with the usual "usage limit" message.

The client is the account for signed-in users. A guest is a browser: a keyed hash of the client
address and its User-Agent, plus the address alone (`network`) with GUEST_NETWORK_FACTOR times
the limits, so changing the User-Agent does not escape a limit while several people behind one
address do not share one. The address comes from X-Forwarded-For only as far as
TRUSTED_PROXY_HOPS allows (a client cannot spoof it); it is hashed with a random per-process key
before use and never logged or stored.
"""

import contextlib
import hashlib
import hmac
import logging
import math
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Literal
from uuid import UUID

from limits import RateLimitItem, parse_many
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from slowapi import Limiter
from starlette.requests import Request

from backend.api.errors import ApiError
from backend.api.security import COOKIE_NAME, verify_session_token
from backend.config import Settings, get_settings
from backend.schemas.enums import ErrorCode

log = logging.getLogger(__name__)

UPLOAD_LIMIT = "10/hour"
GAP_SEARCH_LIMIT = "20/hour"
# New explanations ("Write a summary", path explanations); cached ones only count as requests.
EXPLAIN_LIMIT = "20/minute;200/day"

# Expensive reads, per client on top of the general limit. Keys are route templates.
READ_LIMITS: dict[tuple[str, str], str] = {
    ("GET", "/search"): "120/minute",
    ("GET", "/neighborhood/{node_id}"): "60/minute",
    ("GET", "/path"): "30/minute",
    ("GET", "/clusters"): "30/minute",
    ("GET", "/atlas/tree.json"): "30/minute",
    ("GET", "/atlas/summary/{node_id}"): "120/minute",
    ("GET", "/atlas.json"): "10/minute",
    ("GET", "/export/graph"): "30/hour",
}
EXEMPT_ROUTES = {"/health"}
GUEST_NETWORK_FACTOR = 4
BUSY_RETRY_S = 5
# A slot whose release was missed (a stream never started) frees itself after this long.
SLOT_MAX_HOLD_S = 15 * 60

TOO_MANY = "Too many requests in a short time. Please wait a moment."
USAGE_LIMIT = "The AI usage limit is reached. Please try again later."
BUSY_ACCOUNT = "Your other answers are still running. Try again in a moment."
BUSY_PROCESS = "Amber is busy right now. Try again in a moment."

Reason = Literal["rate", "busy", "budget"]

_SALT = os.urandom(16)  # per process: hashed addresses mean nothing after a restart
_storage = MemoryStorage()
_window = MovingWindowRateLimiter(_storage)
_warned_short_forwarded = False


# ---- client ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Client:
    kind: Literal["user", "guest"]
    key: str  # "user:<account id>" or "guest:<hash of address and User-Agent>"
    network: str | None = None  # guests: "net:<hash of address>"
    user_id: UUID | None = None
    via: Literal["peer", "forwarded"] = "peer"


def _digest(*parts: str) -> str:
    return hmac.new(_SALT, "\n".join(parts).encode(), hashlib.sha256).hexdigest()[:16]


def client_address(request: Request, hops: int) -> tuple[str, Literal["peer", "forwarded"]]:
    """The client's address: with `hops` trusted proxies that append to X-Forwarded-For, the
    hops-th entry from the right (entries further left were sent by the client and are not
    trusted); with 0, or a header too short for the setting, the connection's address."""
    global _warned_short_forwarded
    peer = request.client.host if request.client else "unknown"
    if hops <= 0:
        return peer, "peer"
    entries = [
        part.strip()
        for value in request.headers.getlist("x-forwarded-for")
        for part in value.split(",")
        if part.strip()
    ]
    if len(entries) >= hops:
        return entries[-hops], "forwarded"
    if not _warned_short_forwarded:
        _warned_short_forwarded = True
        log.warning(
            "X-Forwarded-For has fewer entries than TRUSTED_PROXY_HOPS=%d; guests are keyed on "
            "the connection's address (check the setting)",
            hops,
        )
    return peer, "peer"


def identify(request: Request, settings: Settings | None = None) -> Client:
    """The rate-limit client of a request (computed once, kept on request.state)."""
    cached = getattr(request.state, "amber_client", None)
    if cached is not None:
        return cached
    token = request.cookies.get(COOKIE_NAME)
    claims = verify_session_token(token) if token else None
    settings = settings or get_settings()
    address, via = client_address(request, settings.trusted_proxy_hops)
    if claims is not None:
        client = Client("user", f"user:{claims.user_id}", None, claims.user_id, via)
    else:
        agent = request.headers.get("user-agent", "")
        key, network = f"guest:{_digest(address, agent)}", f"net:{_digest(address)}"
        client = Client("guest", key, network, None, via)
    request.state.amber_client = client
    return client


def user_or_ip(request: Request) -> str:
    """slowapi key: the account, or the guest's browser key (never a raw address)."""
    return identify(request).key


limiter = Limiter(key_func=user_or_ip)


# ---- counting -------------------------------------------------------------------------------


def _scaled(item: RateLimitItem, factor: int) -> RateLimitItem:
    return type(item)(item.amount * factor, item.multiples)


def hit(limit: str, scope: str, key: str, factor: int = 1) -> int | None:
    """Count one request; None while within `limit`, else the seconds until it frees up."""
    for item in parse_many(limit):
        item = _scaled(item, factor) if factor != 1 else item
        if not _window.hit(item, scope, key):
            reset = _window.get_window_stats(item, scope, key).reset_time
            return max(1, math.ceil(reset - time.time()))
    return None


def hit_client(client: Client, limit: str, scope: str) -> int | None:
    retry = hit(limit, scope, client.key)
    if retry is None and client.network is not None:
        retry = hit(limit, scope, client.network, GUEST_NETWORK_FACTOR)
    return retry


def reset() -> None:
    """Clear every counter, slot and budget (tests)."""
    _storage.reset()
    limiter.reset()
    gate.reset()


def rejection(retry_after: int, message: str = TOO_MANY, reason: Reason = "rate") -> ApiError:
    return ApiError(
        429,
        ErrorCode.rate_limited,
        message,
        headers={"Retry-After": str(retry_after)},
        extra={"reason": reason, "retry_after": retry_after},
    )


def route_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or "unmatched"


def log_rejection(kind: str, route: str, limit: str) -> None:
    log.info("rate limited kind=%s route=%s limit=%s", kind, route, limit)


async def request_limits(request: Request) -> None:
    """App-wide dependency: the general limit and the expensive-read limits."""
    template = route_template(request)
    if template in EXEMPT_ROUTES or request.method == "OPTIONS":
        return
    settings: Settings = getattr(request.app.state, "settings", None) or get_settings()
    client = identify(request, settings)
    checks = [("general", settings.rate_limit_general)]
    read = READ_LIMITS.get((request.method, template))
    if read:
        checks.append(("read", read))
    for name, limit in checks:
        retry = hit_client(client, limit, name if name == "general" else template)
        if retry is not None:
            log_rejection(client.kind, template, name)
            raise rejection(retry)


# ---- model calls ----------------------------------------------------------------------------


def _seconds_to_midnight() -> int:
    now = datetime.now(UTC)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, math.ceil((midnight - now).total_seconds()))


@dataclass
class ModelTicket:
    """One admitted model-calling request: a concurrency slot (released when the run ends) and,
    for server-key accounts, one unit of the daily budget (refunded if it never starts)."""

    gate: "ModelGate"
    user_id: UUID
    slot: int | None = None
    charged: str | None = None  # the UTC day charged

    def release(self) -> None:
        if self.slot is not None:
            self.gate._slots.pop(self.slot, None)
            self.slot = None

    def cancel(self) -> None:
        """The request failed before its run started: free the slot, refund the budget."""
        self.release()
        if self.charged is not None:
            self.gate._refund(self.user_id, self.charged)
            self.charged = None


class ModelGate:
    def __init__(self) -> None:
        self._ids = count(1)
        self._slots: dict[int, tuple[UUID, float]] = {}
        self._day = ""
        self._spent: dict[UUID, int] = {}
        self._total = 0
        self._ceiling_logged = False
        self.started = 0  # model-calling requests admitted since start

    def reset(self) -> None:
        self.__init__()

    def _roll(self) -> str:
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        if day != self._day:
            if self._day:
                log.info(
                    "model budget day closed requests=%d accounts=%d",
                    self._total,
                    len(self._spent),
                )
            self._day, self._spent, self._total, self._ceiling_logged = day, {}, 0, False
        return day

    def _prune(self) -> None:
        now = time.monotonic()
        for slot, (_, expires) in list(self._slots.items()):
            if expires <= now:
                self._slots.pop(slot, None)
                log.warning("model slot expired without release")

    def running(self, user_id: UUID | None = None) -> int:
        self._prune()
        if user_id is None:
            return len(self._slots)
        return sum(1 for uid, _ in self._slots.values() if uid == user_id)

    def spent_today(self, user_id: UUID | None = None) -> int:
        self._roll()
        return self._total if user_id is None else self._spent.get(user_id, 0)

    def _refund(self, user_id: UUID, day: str) -> None:
        if day == self._day and self._spent.get(user_id, 0) > 0:
            self._spent[user_id] -= 1
            self._total -= 1

    def admit(
        self,
        user_id: UUID,
        settings: Settings,
        *,
        route: str,
        server_key: bool,
        slot: bool = True,
    ) -> ModelTicket:
        """Raise 429 (busy or usage limit) or return a ticket. Synchronous on purpose: the check
        and the take happen without a pause, so parallel requests cannot overshoot."""
        ticket = ModelTicket(self, user_id)
        if slot:
            if self.running(user_id) >= settings.model_max_concurrent_per_account:
                log.info("model busy scope=account route=%s", route)
                raise rejection(BUSY_RETRY_S, BUSY_ACCOUNT, "busy")
            if self.running() >= settings.model_max_concurrent:
                log.warning("model busy scope=process route=%s running=%d", route, self.running())
                raise rejection(BUSY_RETRY_S, BUSY_PROCESS, "busy")
        if server_key:
            day = self._roll()
            budget, ceiling = settings.model_daily_budget, settings.model_daily_ceiling
            if budget and self._spent.get(user_id, 0) >= budget:
                log.info("model budget reached scope=account route=%s budget=%d", route, budget)
                raise rejection(_seconds_to_midnight(), USAGE_LIMIT, "budget")
            if ceiling and self._total >= ceiling:
                if not self._ceiling_logged:
                    self._ceiling_logged = True
                    log.warning("model daily ceiling reached ceiling=%d", ceiling)
                raise rejection(_seconds_to_midnight(), USAGE_LIMIT, "budget")
            self._spent[user_id] = self._spent.get(user_id, 0) + 1
            self._total += 1
            ticket.charged = day
        if slot:
            ticket.slot = next(self._ids)
            self._slots[ticket.slot] = (user_id, time.monotonic() + SLOT_MAX_HOLD_S)
        self.started += 1
        return ticket


gate = ModelGate()


async def admit_model_request(
    request: Request,
    user_id: UUID,
    *,
    limit: str | None = None,
    slot: bool = True,
) -> ModelTicket:
    """Before a request starts model calls: its own per-account rate limit (`limit`), then the
    concurrency and budget checks of `gate`. ChatGPT-plan accounts are not charged."""
    from backend.api.services import auth as auth_service

    route = route_template(request)
    if limit is not None:
        retry = hit(limit, f"model:{route}", f"user:{user_id}")
        if retry is not None:
            log_rejection("user", route, "model")
            raise rejection(retry)
    settings: Settings = getattr(request.app.state, "settings", None) or get_settings()
    server_key = await auth_service.uses_server_key(user_id)
    return gate.admit(user_id, settings, route=route, server_key=server_key, slot=slot)


async def hold_stream[T](stream: AsyncIterator[T], ticket: ModelTicket) -> AsyncIterator[T]:
    """Pass `stream` through and release the ticket's slot when it ends or the client leaves."""
    try:
        async with contextlib.aclosing(stream) as items:  # type: ignore[type-var]
            async for item in items:
                yield item
    finally:
        ticket.release()
