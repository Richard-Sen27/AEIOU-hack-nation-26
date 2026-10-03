"""Outbound HTTP for the gap-search agent: polite clients for public APIs and an SSRF-safe
fetcher for model-chosen URLs.

`safe_get` allows http/https on the default ports only, resolves the host itself and refuses
loopback, private, link-local, CGNAT, multicast and reserved addresses, pins the connection to
the checked address (TLS still verifies the real host name), re-checks every redirect hop, caps
size and time, and never sends cookies or credentials.
"""

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

USER_AGENT = (
    "AmberRareDiseaseAtlas/0.1 (rare-disease research atlas; gap-search agent; "
    "public literature only)"
)
FETCH_TIMEOUT_S = 12.0
FETCH_MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 4
ALLOWED_PORTS = {None, 80, 443}
TEXT_TYPES = ("text/html", "text/plain", "application/xhtml+xml", "text/xml", "application/xml")
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa", ".lan")


class BlockedURL(Exception):
    """`code` is a short reason safe to hand back to the model."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass
class FetchResult:
    url: str
    status: int
    content_type: str
    body: bytes
    truncated: bool


async def _getaddrinfo(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


resolve_host = _getaddrinfo  # replaced in tests


def is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip.sixtofour is not None or ip.teredo is not None:
            return False
    return ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_loopback)


def check_url(url: str) -> tuple[str, str, int]:
    """(scheme, host, port) of an allowed URL; raises BlockedURL otherwise."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        raise BlockedURL("invalid_url") from None
    if parts.scheme not in ("http", "https"):
        raise BlockedURL("scheme_not_allowed")
    if parts.username is not None or parts.password is not None:
        raise BlockedURL("credentials_not_allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise BlockedURL("invalid_url")
    if port not in ALLOWED_PORTS:
        raise BlockedURL("port_not_allowed")
    if host == "localhost" or host.endswith(_BLOCKED_SUFFIXES):
        raise BlockedURL("host_not_allowed")
    try:
        ipaddress.ip_address(host)
        literal = True
    except ValueError:
        literal = False
    if literal and not is_public_ip(host):
        raise BlockedURL("address_not_allowed")
    if not literal and "." not in host:
        raise BlockedURL("host_not_allowed")
    return parts.scheme, host, port or (443 if parts.scheme == "https" else 80)


async def _public_address(host: str, port: int) -> str:
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    try:
        addresses = await resolve_host(host, port)
    except (OSError, UnicodeError):
        raise BlockedURL("dns_failed") from None
    if not addresses:
        raise BlockedURL("dns_failed")
    if not all(is_public_ip(a) for a in addresses):
        raise BlockedURL("address_not_allowed")
    return addresses[0]


async def safe_get(
    url: str,
    *,
    max_bytes: int = FETCH_MAX_BYTES,
    timeout_s: float = FETCH_TIMEOUT_S,
    accept: str = "text/html,application/xhtml+xml,text/plain;q=0.8",
) -> FetchResult:
    try:
        async with asyncio.timeout(timeout_s):
            return await _safe_get(url, max_bytes=max_bytes, accept=accept, timeout_s=timeout_s)
    except TimeoutError:
        raise BlockedURL("timeout") from None


async def _safe_get(url: str, *, max_bytes: int, accept: str, timeout_s: float) -> FetchResult:
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        scheme, host, port = check_url(current)
        address = await _public_address(host, port)
        parts = urlsplit(current)
        ip_host = f"[{address}]" if ":" in address else address
        default = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
        netloc = ip_host if default else f"{ip_host}:{port}"
        pinned = urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))
        headers = {
            "Host": host if default else f"{host}:{port}",
            "User-Agent": USER_AGENT,
            "Accept": accept,
        }
        extensions = {"sni_hostname": host} if scheme == "https" else {}
        # A fresh client per hop: no cookie jar carries over, no env proxies or credentials.
        async with httpx.AsyncClient(
            follow_redirects=False, trust_env=False, timeout=timeout_s
        ) as client:
            request = client.build_request("GET", pinned, headers=headers, extensions=extensions)
            response = await client.send(request, stream=True)
            try:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise BlockedURL("bad_redirect")
                    current = urljoin(current, location)
                    continue
                body = bytearray()
                truncated = False
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        del body[max_bytes:]
                        truncated = True
                        break
                return FetchResult(
                    url=current,
                    status=response.status_code,
                    content_type=response.headers.get("content-type", "").split(";")[0].lower(),
                    body=bytes(body),
                    truncated=truncated,
                )
            finally:
                await response.aclose()
    raise BlockedURL("too_many_redirects")


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "template", "svg", "head", "nav", "footer", "form"}
    _BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed markup: keep what we have
        pass
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


def decode_text(result: FetchResult) -> str | None:
    if result.content_type and not result.content_type.startswith(TEXT_TYPES):
        return None
    raw = result.body.decode("utf-8", errors="replace")
    if "html" in result.content_type or raw.lstrip()[:15].lower().startswith(
        ("<!doctype", "<html")
    ):
        return html_to_text(raw)
    return raw


# ---- polite client for the fixed public APIs ---------------------------------------------------


class HostThrottle:
    """Minimum interval between requests to one host (process-wide)."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}

    async def wait(self, host: str, interval: float) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            delay = self._last.get(host, 0.0) + interval - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last[host] = time.monotonic()


throttle = HostThrottle()


def api_client(timeout_s: float = 15.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout_s,
        trust_env=False,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
