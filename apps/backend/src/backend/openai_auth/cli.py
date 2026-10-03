"""Sign in with ChatGPT for offline tools (the pipeline): loopback OAuth on 127.0.0.1.

    uv run python -m backend.openai_auth.cli login | logout | status

Credentials (host id, issued client id, tokens) live in a 0600 JSON file:
~/.config/amber/openai.json, override with AMBER_OPENAI_CREDENTIALS.
"""

import argparse
import asyncio
import contextlib
import fcntl
import inspect
import json
import os
import sys
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel

from backend.openai_auth.oidc import (
    CALLBACK_PATH,
    DYNAMIC_CLIENT_ID,
    AuthTransaction,
    OAuthError,
    OIDCClient,
    is_issued_client_id,
    new_host_id,
)
from backend.openai_auth.settings import OpenAISettings, get_openai_settings
from backend.openai_auth.tokens import TokenSet

DEFAULT_PORT = 1455
LOGIN_TIMEOUT_S = 300.0


def credentials_path() -> Path:
    raw = os.environ.get("AMBER_OPENAI_CREDENTIALS") or "~/.config/amber/openai.json"
    return Path(raw).expanduser()


class Credentials(BaseModel):
    issuer: str | None = None
    ext_agent_host_id: str | None = None
    client_id: str | None = None
    tokens: TokenSet | None = None
    email: str | None = None


def load_credentials(path: Path | None = None) -> Credentials:
    path = path or credentials_path()
    try:
        return Credentials.model_validate_json(path.read_text())
    except FileNotFoundError:
        return Credentials()
    except ValueError:
        raise SystemExit(
            f"Credentials file {path} is corrupt; delete it and log in again."
        ) from None


def save_credentials(creds: Credentials, path: Path | None = None) -> None:
    path = path or credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(creds.model_dump_json(indent=2))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


@contextlib.asynccontextmanager
async def _file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path.with_suffix(path.suffix + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        await asyncio.to_thread(fcntl.flock, fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class FileTokenProvider:
    """TokenProvider backed by the CLI credentials file; refreshes (file-locked) when due."""

    def __init__(self, path: Path | None = None, settings: OpenAISettings | None = None):
        self.path = path or credentials_path()
        self.settings = settings or get_openai_settings()
        self._oidc = OIDCClient(self.settings)
        self._lock = asyncio.Lock()

    def __repr__(self) -> str:
        return f"FileTokenProvider({str(self.path)!r})"

    async def get_token(self) -> str:
        creds = load_credentials(self.path)
        if creds.tokens and not creds.tokens.needs_refresh():
            return creds.tokens.access_token
        return await self._refresh(force=False)

    async def force_refresh(self) -> str:
        return await self._refresh(force=True)

    async def _refresh(self, *, force: bool) -> str:
        from backend.llm.types import LLMError

        async with self._lock, _file_lock(self.path):
            creds = load_credentials(self.path)
            tokens = creds.tokens
            if tokens is None:
                raise LLMError("reauth_required", "not signed in; run the login command")
            if not force and not tokens.needs_refresh():
                return tokens.access_token
            try:
                creds.tokens = await self._oidc.refresh(tokens)
            except OAuthError as exc:
                if exc.reauth_required or exc.code == "invalid_client":
                    creds.tokens = None
                    save_credentials(creds, self.path)
                    raise LLMError("reauth_required", "sign-in expired; log in again") from None
                raise LLMError("upstream", f"token refresh failed ({exc.code})") from None
            save_credentials(creds, self.path)
            return creds.tokens.access_token


def load_cli_token_provider(path: Path | None = None) -> FileTokenProvider | None:
    """The CLI's TokenProvider if someone has logged in on this machine, else None."""
    path = path or credentials_path()
    creds = load_credentials(path)
    return FileTokenProvider(path) if creds.tokens else None


class _CallbackServer:
    """One-shot HTTP listener on 127.0.0.1 for /auth/callback."""

    def __init__(self) -> None:
        self.result: asyncio.Future[dict[str, str]] = asyncio.get_running_loop().create_future()
        self.server: asyncio.Server | None = None
        self.port = 0

    async def start(self, preferred: int) -> int:
        for port in (preferred, 0):
            try:
                self.server = await asyncio.start_server(self._handle, "127.0.0.1", port)
                break
            except OSError:
                continue
        assert self.server is not None
        self.port = self.server.sockets[0].getsockname()[1]
        return self.port

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = (await reader.readline()).decode("latin-1")
            while (await reader.readline()) not in (b"\r\n", b"\n", b""):
                pass
            parts = request_line.split(" ")
            target = urlsplit(parts[1]) if len(parts) > 1 else urlsplit("/")
            if target.path != CALLBACK_PATH:
                body, status = "Not found", "404 Not Found"
            else:
                params = {k: v[0] for k, v in parse_qs(target.query).items()}
                if not self.result.done():
                    self.result.set_result(params)
                ok = "error" not in params
                body = (
                    "Signed in. You can close this window and return to the terminal."
                    if ok
                    else "Sign-in was not completed. You can close this window."
                )
                status = "200 OK"
            payload = (
                f"<!doctype html><meta charset=utf-8><title>Amber</title><p>{body}</p>"
            ).encode()
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
                + payload
            )
            await writer.drain()
        finally:
            writer.close()

    async def close(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()


Opener = Callable[[str], Any]


async def login(
    *,
    path: Path | None = None,
    settings: OpenAISettings | None = None,
    port: int = DEFAULT_PORT,
    opener: Opener | None = webbrowser.open,
    timeout_s: float = LOGIN_TIMEOUT_S,
    out=sys.stdout,
) -> Credentials:
    """Run the loopback sign-in. `opener` receives the authorize URL (may be async)."""
    path = path or credentials_path()
    settings = settings or get_openai_settings()
    oidc = OIDCClient(settings)
    creds = load_credentials(path)
    if creds.issuer and creds.issuer != settings.issuer:
        creds = Credentials(ext_agent_host_id=creds.ext_agent_host_id)
    creds.issuer = settings.issuer
    if not creds.ext_agent_host_id:
        creds.ext_agent_host_id = settings.openai_agent_host_id or new_host_id()
        save_credentials(creds, path)

    remembered = creds.client_id if is_issued_client_id(creds.client_id) else None
    for attempt in range(2):
        client_id = oidc.default_client_id(remembered)
        try:
            tokens, claims = await _attempt(
                oidc, creds, client_id, port=port, opener=opener, timeout_s=timeout_s, out=out
            )
        except OAuthError as exc:
            if attempt == 0 and remembered and client_id == remembered and exc.code != "denied":
                print("Saved registration was rejected; registering again.", file=out)
                remembered = None
                creds.client_id = None
                creds.tokens = None
                save_credentials(creds, path)
                continue
            raise
        creds.client_id = tokens.client_id
        creds.tokens = tokens
        creds.email = claims.email
        save_credentials(creds, path)
        print(f"Signed in{f' as {claims.email}' if claims.email else ''}.", file=out)
        if not tokens.has_plan_usage:
            print("Warning: plan usage scope was not granted; LLM calls will fail.", file=out)
        return creds
    raise OAuthError("failed")


async def _attempt(
    oidc: OIDCClient,
    creds: Credentials,
    client_id: str,
    *,
    port: int,
    opener: Opener | None,
    timeout_s: float,
    out,
) -> tuple[TokenSet, Any]:
    discovery = await oidc.discovery()
    callback = _CallbackServer()
    actual_port = await callback.start(port)
    try:
        redirect_uri = f"http://127.0.0.1:{actual_port}{CALLBACK_PATH}"
        tx = AuthTransaction.new(redirect_uri=redirect_uri, client_id=client_id)
        id_hint = creds.tokens.id_token if creds.tokens and client_id != DYNAMIC_CLIENT_ID else None
        url = oidc.authorize_url(
            discovery,
            tx,
            ext_agent_host_id=creds.ext_agent_host_id,
            id_token_hint=id_hint,
        )
        print("Open this URL to sign in with ChatGPT:", file=out)
        print(url, file=out)
        opener_task = None
        if opener is not None:
            res = opener(url)
            if inspect.isawaitable(res):
                opener_task = asyncio.ensure_future(res)
        try:
            params = await asyncio.wait_for(callback.result, timeout_s)
        except TimeoutError:
            raise OAuthError("timeout", "no callback received") from None
        finally:
            if opener_task is not None:
                with contextlib.suppress(BaseException):
                    await asyncio.wait_for(opener_task, 5)
    finally:
        await callback.close()
    if params.get("state") != tx.state:
        raise OAuthError("state_mismatch")
    if "error" in params:
        code = "denied" if params["error"] == "access_denied" else params["error"]
        raise OAuthError(code)
    if "code" not in params:
        raise OAuthError("missing_code")
    issued = params.get("client_id") if client_id == DYNAMIC_CLIENT_ID else client_id
    if not issued or issued == DYNAMIC_CLIENT_ID:
        raise OAuthError("missing_issued_client_id")
    return await oidc.exchange_code(tx, params["code"], client_id=issued)


async def logout(*, path: Path | None = None, out=sys.stdout) -> None:
    path = path or credentials_path()
    creds = load_credentials(path)
    if not creds.tokens:
        print("Not signed in.", file=out)
        return
    confirmed = await OIDCClient(get_openai_settings()).revoke(creds.tokens)
    creds.tokens = None
    creds.email = None
    save_credentials(creds, path)
    print(
        "Signed out." if confirmed else "Signed out locally; remote revocation not confirmed.",
        file=out,
    )


def status(*, path: Path | None = None, out=sys.stdout) -> dict[str, Any]:
    path = path or credentials_path()
    creds = load_credentials(path)
    info: dict[str, Any] = {
        "credentials_file": str(path),
        "signed_in": creds.tokens is not None,
        "issuer": creds.issuer,
        "email": creds.email,
        "client_id": creds.client_id,
    }
    if creds.tokens:
        info.update(
            access_token_expires_at=creds.tokens.expires_at.isoformat(),
            access_token_expired=creds.tokens.is_expired(),
            plan_usage=creds.tokens.has_plan_usage,
            scopes=creds.tokens.scopes,
        )
    print(json.dumps(info, indent=2), file=out)
    return info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backend.openai_auth.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p_login = sub.add_parser("login", help="Sign in with ChatGPT in the browser")
    p_login.add_argument("--no-browser", action="store_true", help="only print the URL")
    p_login.add_argument("--port", type=int, default=DEFAULT_PORT)
    sub.add_parser("logout", help="Revoke and forget the stored tokens")
    sub.add_parser("status", help="Show sign-in status (never prints tokens)")
    args = parser.parse_args(argv)
    try:
        if args.command == "login":
            opener = None if args.no_browser else webbrowser.open
            asyncio.run(login(port=args.port, opener=opener))
        elif args.command == "logout":
            asyncio.run(logout())
        else:
            status()
    except OAuthError as exc:
        print(f"Sign-in failed: {exc.code}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
