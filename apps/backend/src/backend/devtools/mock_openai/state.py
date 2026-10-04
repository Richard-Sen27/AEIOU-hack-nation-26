"""In-memory state of the mock OpenAI issuer + API. Development and tests only."""

import secrets
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

PLAN_SCOPE_TOKEN = "chatgpt.tokens.use.direct"
STATIC_TOKEN_PREFIX = "mock-static-"
KID = "mock-key-1"


@dataclass(frozen=True)
class MockUser:
    key: str
    sub: str
    email: str
    name: str


DEFAULT_USERS = {
    u.key: u
    for u in (
        MockUser("alice", "user-mock-alice-0001", "alice@example.test", "Alice Example"),
        MockUser("bob", "user-mock-bob-0002", "bob@example.test", "Bob Example"),
        MockUser("carol", "user-mock-carol-0003", "carol@example.test", "Carol Example"),
    )
}

DEFAULT_MODELS = [
    {"slug": "gpt-mock-main", "display_name": "Mock Main", "visibility": "list"},
    {"slug": "gpt-mock-mini", "display_name": "Mock Mini", "visibility": "list"},
    {"slug": "gpt-mock-hidden", "display_name": "Mock Hidden", "visibility": "hide"},
]


@dataclass
class MockConfig:
    """Switches a test can flip (via `state.configure(...)` or POST /_mock/config)."""

    access_token_ttl: int = 3600
    id_token_ttl: int = 3600
    # "usage_limit" | "usage_limit_stream" | "unavailable" | "unauthorized" | None
    fail_mode: str | None = None
    reject_function_tools: bool = False
    reject_namespace_tools: bool = False
    allow_top_level_functions: bool = False
    reject_json_schema: bool = False
    reject_include: bool = False
    # The docs list text, image and file input as supported; this switch is opt-in.
    reject_file_inputs: bool = False
    # Fail only the Nth /v1/responses call since the last reset (1-based), with a fail_mode.
    fail_on_request: int | None = None
    fail_on_request_mode: str = "usage_limit"
    fail_refresh: bool = False
    deny_all: bool = False
    stream_delay_s: float = 0.0
    models: list[dict[str, Any]] = field(default_factory=lambda: list(DEFAULT_MODELS))


@dataclass
class IssuedClient:
    client_id: str
    user_key: str
    host_id: str
    agent_name: str | None


@dataclass
class AuthCode:
    code: str
    client_id: str
    user_key: str
    redirect_uri: str
    code_challenge: str
    nonce: str | None
    scope: str
    resource: str | None
    expires_at: float
    used: bool = False


@dataclass
class RefreshRecord:
    token: str
    client_id: str
    user_key: str
    scope: str
    family: str
    used: bool = False
    revoked: bool = False


class MockState:
    def __init__(self, *, issuer: str | None = None):
        self.lock = threading.RLock()
        self.fixed_issuer = issuer
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.reset()

    def reset(self) -> None:
        with self.lock:
            self.config = MockConfig()
            self.users: dict[str, MockUser] = dict(DEFAULT_USERS)
            self.clients: dict[str, IssuedClient] = {}
            self.partner_clients: dict[str, str] = {"mock_partner_client": "mock_partner_secret"}
            self.codes: dict[str, AuthCode] = {}
            self.refresh_tokens: dict[str, RefreshRecord] = {}
            self.revoked_families: set[str] = set()
            self.queue: deque[dict[str, Any]] = deque()
            self.requests: list[dict[str, Any]] = []
            self.request_count = 0

    # ---- scripting ------------------------------------------------------------------------

    def configure(self, **switches: Any) -> None:
        with self.lock:
            for key, value in switches.items():
                if not hasattr(self.config, key):
                    raise AttributeError(f"unknown mock switch {key!r}")
                setattr(self.config, key, value)

    def enqueue(self, *responses: dict[str, Any]) -> None:
        """Queue exact responses for the next /v1/responses calls, e.g. {"text": "..."},
        {"json": {...}}, {"tool_calls": [{"name": ..., "arguments": {...}}]},
        {"error": {"status": 429, "code": "..."}}, {"fail": "<code>"}, {"incomplete": True}.

        An entry may carry "kind": "tools" (requests offering tools), "structured"
        (json_schema / JSON-only requests without tools) or "text"; it is then only used by a
        request of that kind, so e.g. a structured() call made inside a tool handler does not
        consume the tool loop's scripted answer. Entries without "kind" match any request."""
        with self.lock:
            self.queue.extend(responses)

    def pop_scripted(self, kind: str | None = None) -> dict[str, Any] | None:
        with self.lock:
            for i, entry in enumerate(self.queue):
                if entry.get("kind") in (None, "any", kind):
                    del self.queue[i]
                    return entry
            return None

    def next_request_number(self) -> int:
        with self.lock:
            self.request_count += 1
            return self.request_count

    def clear_requests(self) -> None:
        """Forget recorded requests (and the request counter); keep clients and tokens."""
        with self.lock:
            self.requests = []
            self.request_count = 0

    def record(self, kind: str, payload: dict[str, Any]) -> None:
        with self.lock:
            self.requests.append({"kind": kind, "at": time.time(), **payload})

    def recorded(self, kind: str | None = None) -> list[dict[str, Any]]:
        with self.lock:
            return [r for r in self.requests if kind is None or r["kind"] == kind]

    # ---- keys and tokens -----------------------------------------------------------------

    @property
    def private_key(self) -> rsa.RSAPrivateKey:
        return self._key

    def jwks(self) -> dict[str, Any]:
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self._key.public_key(), as_dict=True)
        return {"keys": [{**jwk, "kid": KID, "use": "sig", "alg": "RS256"}]}

    def sign(self, claims: dict[str, Any], *, key: Any = None, kid: str = KID) -> str:
        return jwt.encode(claims, key or self._key, algorithm="RS256", headers={"kid": kid})

    def issue_client(self, user_key: str, host_id: str, agent_name: str | None) -> IssuedClient:
        with self.lock:
            for client in self.clients.values():
                if client.user_key == user_key and client.host_id == host_id:
                    return client
            client = IssuedClient(
                f"oaiapp_mock_{secrets.token_hex(8)}", user_key, host_id, agent_name
            )
            self.clients[client.client_id] = client
            return client

    def new_code(self, **fields: Any) -> AuthCode:
        code = AuthCode(code=secrets.token_urlsafe(24), expires_at=time.time() + 120, **fields)
        with self.lock:
            self.codes[code.code] = code
        return code

    def mint_tokens(
        self,
        *,
        issuer: str,
        client_id: str,
        user_key: str,
        scope: str,
        resource: str | None,
        nonce: str | None,
        family: str | None = None,
        with_id_token: bool = True,
    ) -> dict[str, Any]:
        user = self.users[user_key]
        now = int(time.time())
        family = family or uuid.uuid4().hex
        access = self.sign(
            {
                "iss": issuer,
                "sub": user.sub,
                "aud": resource or issuer + "/v1",
                "client_id": client_id,
                "scope": scope,
                "iat": now,
                "nbf": now,
                "exp": now + self.config.access_token_ttl,
                "jti": uuid.uuid4().hex,
                "fam": family,
            }
        )
        body: dict[str, Any] = {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": self.config.access_token_ttl,
            "scope": scope,
            "earliest_refresh_at": now,
        }
        if "offline_access" in scope.split():
            refresh = f"mock_rt_{secrets.token_urlsafe(32)}"
            with self.lock:
                self.refresh_tokens[refresh] = RefreshRecord(
                    refresh, client_id, user_key, scope, family
                )
            body["refresh_token"] = refresh
        if with_id_token:
            claims = {
                "iss": issuer,
                "sub": user.sub,
                "aud": client_id,
                "iat": now,
                "exp": now + self.config.id_token_ttl,
                "email": user.email,
                "email_verified": True,
                "name": user.name,
            }
            if nonce:
                claims["nonce"] = nonce
            body["id_token"] = self.sign(claims)
        return body

    def check_access_token(self, token: str) -> dict[str, Any] | None:
        """Return claims for a valid, unrevoked mock access token (or a static dev token)."""
        if token.startswith(STATIC_TOKEN_PREFIX):
            return {"sub": "user-mock-static", "scope": PLAN_SCOPE_TOKEN, "client_id": "static"}
        try:
            claims = jwt.decode(
                token,
                self._key.public_key(),
                algorithms=["RS256"],
                options={"verify_aud": False, "verify_iss": False},
            )
        except jwt.PyJWTError:
            return None
        if claims.get("fam") in self.revoked_families:
            return None
        return claims
