"""Fernet encryption for OpenAI tokens at rest. TOKEN_ENCRYPTION_KEY may hold several
comma-separated keys (newest first) to allow key rotation."""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from backend.openai_auth.settings import get_openai_settings


class TokenCryptoError(Exception):
    pass


def generate_key() -> str:
    return Fernet.generate_key().decode("ascii")


def _fernet(key: str | None = None) -> MultiFernet:
    raw = key if key is not None else get_openai_settings().token_encryption_key
    keys = [k.strip() for k in (raw or "").split(",") if k.strip()]
    if not keys:
        raise TokenCryptoError("TOKEN_ENCRYPTION_KEY is not set")
    try:
        return MultiFernet([Fernet(k.encode("ascii")) for k in keys])
    except ValueError:
        raise TokenCryptoError("TOKEN_ENCRYPTION_KEY is not a valid Fernet key") from None


def encrypt(plaintext: str, *, key: str | None = None) -> bytes:
    return _fernet(key).encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes | str, *, key: str | None = None, ttl: int | None = None) -> str:
    """Decrypt; with `ttl` (seconds) also reject ciphertexts older than that."""
    try:
        data = ciphertext.encode("ascii") if isinstance(ciphertext, str) else bytes(ciphertext)
        return _fernet(key).decrypt(data, ttl=ttl).decode("utf-8")
    except (InvalidToken, UnicodeError):
        raise TokenCryptoError("token ciphertext could not be decrypted") from None
