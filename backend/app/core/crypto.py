"""Token crypto: git credentials at rest are Fernet-encrypted, never plaintext.

Key order: AEROOPS_FERNET_KEY (raw 32-byte urlsafe base64) -> SHA-256 of
JWT_SECRET (always set, dev default included). Decryption happens only in
the delivery gate at push time; API responses never include the token.
"""
import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "fernet:"


def _key() -> bytes:
    raw = os.environ.get("AEROOPS_FERNET_KEY", "")
    if raw:
        return base64.urlsafe_b64decode(raw.encode())
    secret = os.environ.get("JWT_SECRET", "dev-only-change-me")
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())


def encrypt_token(plain: str) -> str:
    if not plain:
        return ""
    return PREFIX + Fernet(_key()).encrypt(plain.encode()).decode()


def decrypt_token(stored: str) -> str:
    if not stored:
        return ""
    if not stored.startswith(PREFIX):
        return ""  # refuse legacy/plaintext values outright
    try:
        return Fernet(_key()).decrypt(stored[len(PREFIX):].encode()).decode()
    except (InvalidToken, ValueError):
        return ""
