"""Log setup for the API: key=value lines on stdout (the host collects them, docs/retention.md).

What a line may hold: route templates (`/node/{node_id}`), methods, status codes, durations,
sizes, error types and codes, model names, counts, a request id, the client kind and, for
signed-in users, `uh`: a pseudonym that changes every UTC day (keyed hash of the account id,
10 hex characters). Never: request or response bodies, raw paths or query strings, names,
e-mail addresses, ORCID iDs, node or other health-related ids, raw account ids, IP addresses,
tokens, prompts or model output (docs/compliance.md).
"""

import hashlib
import hmac
import logging
import sys
import time
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)

_HANDLER_NAME = "amber-stdout"
# Third-party loggers that would print URLs or keys at INFO (httpx logs every request URL,
# slowapi logs the limit key, which holds the account id) stay at WARNING or above.
_QUIET_LOGGERS = {
    "slowapi": logging.ERROR,  # its warnings name the rate-limit key (account id)
    "presidio-analyzer": logging.ERROR,
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
}
MAX_FRAMES = 6


class _UTCFormatter(logging.Formatter):
    converter = time.gmtime

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # noqa: N802
        t = time.strftime("%Y-%m-%dT%H:%M:%S", self.converter(record.created))
        return f"{t}.{int(record.msecs):03d}Z"


class _RequestIdFilter(logging.Filter):
    """Appends ` rid=<id>` to lines written while a request (or a task it started) runs."""

    def filter(self, record: logging.LogRecord) -> bool:
        rid = REQUEST_ID.get()
        record.rid = f" rid={rid}" if rid and "rid=" not in record.getMessage() else ""
        return True


def configure_logging(level: str = "info") -> None:
    """One stdout handler on the root logger; `backend.*` at `level`, everything else at
    WARNING. Idempotent (create_app may run more than once in one process)."""
    root = logging.getLogger()
    handler = next((h for h in root.handlers if h.get_name() == _HANDLER_NAME), None)
    if handler is None:
        handler = logging.StreamHandler(sys.stdout)
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(_UTCFormatter("%(asctime)s %(levelname)s %(name)s %(message)s%(rid)s"))
        handler.addFilter(_RequestIdFilter())
        root.addHandler(handler)
    if root.level == logging.NOTSET or root.level < logging.WARNING:
        root.setLevel(logging.WARNING)
    logging.getLogger("backend").setLevel(_level(level))
    for name, lvl in _QUIET_LOGGERS.items():
        logging.getLogger(name).setLevel(lvl)


def _level(name: str) -> int:
    value = logging.getLevelName(str(name).strip().upper())
    return value if isinstance(value, int) else logging.INFO


def current_request_id() -> str | None:
    return REQUEST_ID.get()


def user_tag(user_id: UUID | str, secret: str, day: str | None = None) -> str:
    """Daily pseudonym of an account for log lines: lines of one day can be grouped per account,
    lines of different days cannot, and nobody without SESSION_SECRET can compute it."""
    day = day or datetime.now(UTC).strftime("%Y-%m-%d")
    mac = hmac.new(secret.encode(), f"log-user\n{day}\n{user_id}".encode(), hashlib.sha256)
    return mac.hexdigest()[:10]


def safe_frames(exc: BaseException) -> str:
    """Where an exception happened, without its message or any local values: the exception
    types of the chain and `file:line:function` of the innermost frames of our own code plus
    the innermost frame overall. Messages are left out because they can carry data
    (KeyError('<value>'), ValueError(f"... {value}"))."""
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        frames = traceback.extract_tb(current.__traceback__)
        ours = [f for f in frames if _ours(f.filename)][-(MAX_FRAMES - 1) :]
        picked = ours + [frames[-1]] if frames and frames[-1] not in ours else ours
        where = " > ".join(f"{_short(f.filename)}:{f.lineno}:{f.name}" for f in picked)
        parts.append(f"{type(current).__name__} at {where or '?'}")
        current = current.__cause__ or current.__context__
    return " <- ".join(parts)


def _ours(filename: str) -> bool:
    return "/backend/" in filename and "/site-packages/" not in filename


def _short(filename: str) -> str:
    for marker in ("/site-packages/", "/src/"):
        if marker in filename:
            return filename.split(marker, 1)[1]
    return filename.rsplit("/", 1)[-1]


def mask_url(url: str) -> str:
    """scheme://host:port/db without user or password (database URLs in the start-up line)."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        netloc = f"{host}:{parts.port}" if parts.port else host
        return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except ValueError:
        return "(unparsable)"


def is_set(value: str | None) -> str:
    return "set" if value else "unset"
