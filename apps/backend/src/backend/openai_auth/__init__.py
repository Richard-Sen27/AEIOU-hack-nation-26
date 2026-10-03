"""Sign in with ChatGPT (OpenID Connect + PKCE) as a framework-free library."""

from backend.openai_auth.crypto import TokenCryptoError, decrypt, encrypt, generate_key
from backend.openai_auth.oidc import (
    CALLBACK_PATH,
    DYNAMIC_CLIENT_ID,
    PARTNER_SCOPE,
    PLAN_SCOPE,
    AuthTransaction,
    Discovery,
    IdentityClaims,
    OAuthError,
    OIDCClient,
    code_challenge,
    is_issued_client_id,
    new_code_verifier,
    new_host_id,
    new_nonce,
    new_state,
    validate_loopback_redirect,
)
from backend.openai_auth.settings import OpenAISettings, get_openai_settings
from backend.openai_auth.tokens import PLAN_USAGE_SCOPE, TokenSet

__all__ = [
    "CALLBACK_PATH",
    "DYNAMIC_CLIENT_ID",
    "PARTNER_SCOPE",
    "PLAN_SCOPE",
    "PLAN_USAGE_SCOPE",
    "AuthTransaction",
    "Discovery",
    "IdentityClaims",
    "OAuthError",
    "OIDCClient",
    "OpenAISettings",
    "TokenCryptoError",
    "TokenSet",
    "code_challenge",
    "decrypt",
    "encrypt",
    "generate_key",
    "get_openai_settings",
    "is_issued_client_id",
    "new_code_verifier",
    "new_host_id",
    "new_nonce",
    "new_state",
    "validate_loopback_redirect",
]
