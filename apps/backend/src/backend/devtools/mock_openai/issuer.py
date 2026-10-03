"""Mock of auth.openai.com: discovery, authorize (dynamic registration), token, JWKS, revocation."""

import base64
import hashlib
import html
import secrets
import time
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from backend.devtools.mock_openai.state import MockState

DYNAMIC_CLIENT_ID = "dynamic_agent_client"
HOST_ID_PREFIXES = ("urn:uuid:", "urn:ietf:params:oauth:jwk-thumbprint:", "did:key:")


def issuer_of(state: MockState, request: Request) -> str:
    return state.fixed_issuer or str(request.base_url).rstrip("/")


def _oauth_error(code: str, description: str = "", status: int = 400) -> JSONResponse:
    return JSONResponse({"error": code, "error_description": description}, status_code=status)


def _redirect(uri: str, params: dict[str, str]) -> RedirectResponse:
    sep = "&" if "?" in uri else "?"
    return RedirectResponse(f"{uri}{sep}{urlencode(params)}", status_code=302)


def _loopback_ok(uri: str) -> bool:
    parts = urlsplit(uri)
    return (
        parts.scheme == "http" and parts.hostname == "127.0.0.1" and parts.path == "/auth/callback"
    )


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:system-ui;max-width:32rem;margin:3rem auto;padding:0 1rem}}
.u{{display:block;padding:.75rem 1rem;margin:.5rem 0;border:1px solid #ccc;border-radius:.5rem;
text-decoration:none;color:inherit}}.u:hover{{background:#f4f4f4}}.deny{{color:#a00}}
.warn{{background:#fff3cd;padding:.5rem 1rem;border-radius:.5rem}}</style></head>
<body>{body}</body></html>"""
    return HTMLResponse(doc, status_code=status)


def build_router(state: MockState) -> APIRouter:
    router = APIRouter()

    @router.get("/.well-known/openid-configuration")
    async def discovery(request: Request):
        iss = issuer_of(state, request)
        return {
            "issuer": iss,
            "authorization_endpoint": f"{iss}/api/accounts/authorize",
            "token_endpoint": f"{iss}/api/accounts/oauth/token",
            "jwks_uri": f"{iss}/.well-known/jwks.json",
            "revocation_endpoint": f"{iss}/api/accounts/oauth/revoke",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none", "client_secret_basic"],
            "scopes_supported": [
                "openid",
                "profile",
                "email",
                "offline_access",
                "resource.invoke",
                "chatgpt.tokens.use.direct",
            ],
        }

    @router.get("/.well-known/jwks.json")
    async def jwks():
        return state.jwks()

    @router.get("/api/accounts/authorize")
    async def authorize(request: Request):
        q = dict(request.query_params)
        state.record("authorize", {"params": {k: v for k, v in q.items()}})
        client_id = q.get("client_id", "")
        redirect_uri = q.get("redirect_uri", "")
        partner = client_id in state.partner_clients
        issued = state.clients.get(client_id)
        if not (partner or issued or client_id == DYNAMIC_CLIENT_ID):
            return _page("Error", "<h1>Unknown client_id</h1>", 400)
        if not partner and not _loopback_ok(redirect_uri):
            return _page(
                "Error",
                "<h1>Invalid redirect_uri</h1><p>Expected http://127.0.0.1:&lt;port&gt;"
                "/auth/callback</p>",
                400,
            )
        if not redirect_uri:
            return _page("Error", "<h1>Missing redirect_uri</h1>", 400)

        def fail(code: str, desc: str) -> Response:
            params = {"error": code, "error_description": desc}
            if q.get("state"):
                params["state"] = q["state"]
            return _redirect(redirect_uri, params)

        if q.get("response_type") != "code":
            return fail("unsupported_response_type", "response_type must be code")
        if q.get("code_challenge_method") != "S256" or not q.get("code_challenge"):
            return fail("invalid_request", "PKCE S256 required")
        if not q.get("state"):
            return fail("invalid_request", "state required")
        scopes = q.get("scope", "").split()
        if "openid" not in scopes:
            return fail("invalid_scope", "openid required")
        if not partner:
            host_id = q.get("ext_agent_host_id", "")
            if not host_id.startswith(HOST_ID_PREFIXES):
                return fail("invalid_request", "ext_agent_host_id required")
            if not q.get("resource"):
                return fail("invalid_request", "resource required")

        decision = q.get("mock_decision")
        user_key = q.get("mock_user")
        if decision == "deny" or state.config.deny_all:
            return _redirect(redirect_uri, {"error": "access_denied", "state": q["state"]})
        if not user_key:
            return _consent_page(state, request)
        if user_key not in state.users:
            return _page("Error", "<h1>Unknown mock user</h1>", 400)
        if issued and issued.user_key != user_key:
            return fail("invalid_request", "client_user_mismatch")

        new_registration = client_id == DYNAMIC_CLIENT_ID
        if new_registration:
            issued = state.issue_client(user_key, q["ext_agent_host_id"], q.get("agent_name_hint"))
            client_id = issued.client_id
        code = state.new_code(
            client_id=client_id,
            user_key=user_key,
            redirect_uri=redirect_uri,
            code_challenge=q["code_challenge"],
            nonce=q.get("nonce"),
            scope=" ".join(scopes),
            resource=q.get("resource"),
        )
        params = {"code": code.code, "scope": " ".join(sorted(scopes)), "state": q["state"]}
        if new_registration:
            params["client_id"] = client_id
        return _redirect(redirect_uri, params)

    @router.post("/api/accounts/oauth/token")
    async def token(request: Request):
        form = dict(await request.form())
        state.record("token", {"grant_type": form.get("grant_type"), "fields": sorted(form)})
        client_id = form.get("client_id", "")
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("basic "):
            try:
                cid, _, secret = base64.b64decode(auth[6:]).decode().partition(":")
            except ValueError:
                return _oauth_error("invalid_client", "bad basic auth", 401)
            if state.partner_clients.get(cid) != secret:
                return _oauth_error("invalid_client", "bad client credentials", 401)
            client_id = cid
        elif client_id in state.partner_clients:
            return _oauth_error("invalid_client", "client authentication required", 401)
        elif client_id not in state.clients:
            return _oauth_error("invalid_client", "unknown client")
        iss = issuer_of(state, request)
        grant = form.get("grant_type")
        if grant == "authorization_code":
            return _exchange(state, form, client_id, iss)
        if grant == "refresh_token":
            return _refresh(state, form, client_id, iss)
        return _oauth_error("unsupported_grant_type")

    @router.post("/api/accounts/oauth/revoke")
    async def revoke(request: Request):
        form = dict(await request.form())
        state.record("revoke", {"fields": sorted(form)})
        rec = state.refresh_tokens.get(form.get("token", ""))
        if rec is not None:
            rec.revoked = True
            state.revoked_families.add(rec.family)
        return Response(status_code=200)

    return router


def _consent_page(state: MockState, request: Request) -> HTMLResponse:
    base = str(request.url)
    links = "".join(
        f'<a class="u" href="{html.escape(base)}&amp;mock_user={u.key}"><b>{html.escape(u.name)}'
        f"</b><br><small>{html.escape(u.email)}</small></a>"
        for u in state.users.values()
    )
    body = (
        "<h1>Mock ChatGPT sign-in</h1>"
        '<p class="warn"><b>Development only.</b> This is a local stand-in for OpenAI. '
        "No real account is involved.</p><p>Continue as:</p>"
        f'{links}<a class="u deny" href="{html.escape(base)}&amp;mock_decision=deny">'
        "Deny access</a>"
    )
    return _page("Mock ChatGPT sign-in — development only", body)


def _s256(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )


def _exchange(state: MockState, form: dict, client_id: str, iss: str) -> JSONResponse:
    with state.lock:
        code = state.codes.get(form.get("code", ""))
        if code is None or code.used or code.expires_at < time.time():
            return _oauth_error("invalid_grant", "invalid or expired code")
        code.used = True
    if code.client_id != client_id:
        return _oauth_error("invalid_grant", "client mismatch")
    if form.get("redirect_uri") != code.redirect_uri:
        return _oauth_error("invalid_grant", "redirect_uri mismatch")
    verifier = form.get("code_verifier", "")
    if not verifier or not secrets.compare_digest(_s256(verifier), code.code_challenge):
        return _oauth_error("invalid_grant", "PKCE verification failed")
    if client_id in state.clients and form.get("resource") != code.resource:
        return _oauth_error("invalid_target", "resource mismatch")
    body = state.mint_tokens(
        issuer=iss,
        client_id=client_id,
        user_key=code.user_key,
        scope=code.scope,
        resource=code.resource,
        nonce=code.nonce,
    )
    return JSONResponse(body)


def _refresh(state: MockState, form: dict, client_id: str, iss: str) -> JSONResponse:
    if state.config.fail_refresh:
        return _oauth_error("invalid_grant", "refresh disabled by mock switch")
    with state.lock:
        rec = state.refresh_tokens.get(form.get("refresh_token", ""))
        if rec is None or rec.revoked:
            return _oauth_error("invalid_grant", "unknown or revoked refresh token")
        if rec.client_id != client_id:
            return _oauth_error("invalid_grant", "client mismatch")
        if rec.used:
            state.revoked_families.add(rec.family)
            return _oauth_error("refresh_token_reused", "refresh token already used")
        if client_id in state.clients and not form.get("resource"):
            return _oauth_error("invalid_target", "resource required")
        rec.used = True
    body = state.mint_tokens(
        issuer=iss,
        client_id=client_id,
        user_key=rec.user_key,
        scope=rec.scope,
        resource=form.get("resource"),
        nonce=None,
        family=rec.family,
        with_id_token=False,
    )
    return JSONResponse(body)
