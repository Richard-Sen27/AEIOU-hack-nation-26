"""Shared HTTP layer: hishel cache, per-source rate limits, tenacity retries, streamed downloads."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from aiolimiter import AsyncLimiter
from hishel import AsyncSqliteStorage, BaseFilter, FilterPolicy, Request, Response
from hishel.httpx import AsyncCacheTransport
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from pipeline.config import rate_for, settings
from pipeline.contracts import raw_record, record_raw
from pipeline.paths import CACHE, RAW

log = logging.getLogger(__name__)

USER_AGENT = f"AmberRareDiseaseAtlas/0.1 (+mailto:{settings.contact_email})"
TRANSIENT_STATUS = {408, 425, 429, 500, 502, 503, 504}

_limiters: dict[str, AsyncLimiter] = {}


def limiter(source: str) -> AsyncLimiter:
    if source not in _limiters:
        # One request per 1/rate seconds: no bursts (NCBI answers bursts with 429).
        _limiters[source] = AsyncLimiter(1, 1 / rate_for(source))
    return _limiters[source]


class TransientHTTPError(Exception):
    def __init__(self, response: httpx.Response, request: httpx.Request):
        super().__init__(f"{response.status_code} for {request.url}")
        self.response = response
        self.request = request


def _is_transient(exc: BaseException) -> bool:
    return isinstance(exc, TransientHTTPError | httpx.TransportError)


def _retrying() -> AsyncRetrying:
    return AsyncRetrying(
        retry=retry_if_exception(_is_transient),
        stop=stop_after_attempt(settings.http_retries),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )


class _LimitedRetryingTransport(httpx.AsyncBaseTransport):
    """Rate-limits and retries real network requests (cache hits never reach this layer)."""

    def __init__(self, source: str, inner: httpx.AsyncBaseTransport):
        self.source = source
        self.inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        async for attempt in _retrying():
            with attempt:
                async with limiter(self.source):
                    response = await self.inner.handle_async_request(request)
                if response.status_code in TRANSIENT_STATUS:
                    await response.aread()
                    await response.aclose()
                    raise TransientHTTPError(response, request)
                return response
        raise AssertionError("unreachable")

    async def aclose(self) -> None:
        await self.inner.aclose()


class _OkOnly(BaseFilter[Response]):
    def needs_body(self) -> bool:
        return False

    def apply(self, item: Response, body: bytes | None) -> bool:
        return item.status_code == 200


class _CacheableMethod(BaseFilter[Request]):
    def needs_body(self) -> bool:
        return False

    def apply(self, item: Request, body: bytes | None) -> bool:
        return item.method in {"GET", "POST"}


def get_client(source: str, *, cache: bool = True, **kwargs) -> httpx.AsyncClient:
    """An AsyncClient for API calls of one source.

    Responses (200 only, GET and POST, keyed by URL + body) are cached in data/cache/http so
    re-runs are fast and offline-friendly. Use as ``async with get_client("pubmed") as c: ...``.
    """
    inner: httpx.AsyncBaseTransport = _LimitedRetryingTransport(
        source, httpx.AsyncHTTPTransport(retries=0)
    )
    if cache:
        CACHE.joinpath("http").mkdir(parents=True, exist_ok=True)
        policy = FilterPolicy(request_filters=[_CacheableMethod()], response_filters=[_OkOnly()])
        policy.use_body_key = True
        storage = AsyncSqliteStorage(
            database_path=CACHE / "http" / f"{source}.db",
            default_ttl=settings.cache_ttl_days * 86400,
        )
        inner = AsyncCacheTransport(next_transport=inner, storage=storage, policy=policy)
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    return httpx.AsyncClient(
        transport=inner,
        headers=headers,
        timeout=kwargs.pop("timeout", settings.http_timeout),
        follow_redirects=True,
        **kwargs,
    )


@asynccontextmanager
async def stream(source: str, url: str, **kwargs) -> AsyncIterator[httpx.Response]:
    """Stream a (large) response without caching, with rate limit and retries on connect."""
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(settings.http_timeout, read=300.0),
        follow_redirects=True,
    ) as client:
        async for attempt in _retrying():
            with attempt:
                async with limiter(source):
                    request = client.build_request("GET", url, **kwargs)
                    response = await client.send(request, stream=True)
                if response.status_code in TRANSIENT_STATUS:
                    await response.aclose()
                    raise TransientHTTPError(response, request)
        try:
            response.raise_for_status()
            yield response
        finally:
            await response.aclose()


async def download(
    source: str,
    url: str,
    filename: str,
    *,
    source_version: str | Callable[[httpx.Response], str | None] | None = None,
    force: bool = False,
    **meta,
) -> Path:
    """Stream ``url`` to data/raw/<source>/<filename> and record its metadata.

    Idempotent: an existing file with a metadata record is reused unless ``force``.
    ``source_version`` may be a callable deriving the version from the response headers.
    """
    dest = RAW / source / filename
    if dest.exists() and raw_record(source, filename) and not force:
        log.info("%s: cached %s", source, filename)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    log.info("%s: downloading %s", source, url)
    async with stream(source, url) as response:
        with tmp.open("wb") as f:
            async for chunk in response.aiter_bytes(1 << 20):
                f.write(chunk)
        version = source_version(response) if callable(source_version) else source_version
        version = version or response.headers.get("last-modified") or response.headers.get("etag")
    tmp.replace(dest)
    record_raw(source, url, dest, version, **meta)
    return dest
