"""Fernet encryption of message bodies at rest.

MESSAGE_ENCRYPTION_KEY holds one or more comma-separated Fernet keys, newest first: new bodies
are encrypted with the first, every listed key can decrypt (MultiFernet), and `rotate()` re-encrypts
a body under the first key (the operator command `backend rotate-message-key`). Errors never carry
the plaintext or the key.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from backend.config import get_settings


class MessageCryptoError(Exception):
    pass


def _dev_key() -> str | None:
    """Local demo only: without MESSAGE_ENCRYPTION_KEY, derive a key from SESSION_SECRET while
    API and frontend are loopback addresses. Never outside loopback (messaging answers 501)."""
    settings = get_settings()
    if not settings.is_local:
        return None
    digest = hashlib.sha256(b"amber-messages-dev:" + settings.session_secret.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")


def _keys(raw: str | None) -> list[str]:
    value = raw if raw is not None else get_settings().message_encryption_key
    keys = [k.strip() for k in (value or "").split(",") if k.strip()]
    if not keys and raw is None:
        dev = _dev_key()
        keys = [dev] if dev else []
    return keys


def configured() -> bool:
    try:
        _fernet()
    except MessageCryptoError:
        return False
    return True


def _fernet(key: str | None = None) -> MultiFernet:
    keys = _keys(key)
    if not keys:
        raise MessageCryptoError("MESSAGE_ENCRYPTION_KEY is not set")
    try:
        return MultiFernet([Fernet(k.encode("ascii")) for k in keys])
    except (ValueError, UnicodeError):
        raise MessageCryptoError("MESSAGE_ENCRYPTION_KEY is not a valid Fernet key") from None


def encrypt(plaintext: str, *, key: str | None = None) -> bytes:
    return _fernet(key).encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes, *, key: str | None = None) -> str:
    try:
        return _fernet(key).decrypt(bytes(ciphertext)).decode("utf-8")
    except (InvalidToken, UnicodeError):
        raise MessageCryptoError("message body could not be decrypted") from None


def rotate(ciphertext: bytes, *, key: str | None = None) -> bytes:
    """Re-encrypt under the newest key (decrypting with any listed key)."""
    try:
        return _fernet(key).rotate(bytes(ciphertext))
    except InvalidToken:
        raise MessageCryptoError("message body could not be decrypted") from None
