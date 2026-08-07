"""Encryption/decryption utility for client passwords and sensitive credentials at rest using Fernet (AES-128-CBC + HMAC-SHA256 authenticated encryption)."""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet

from app.config import get_settings

logger = logging.getLogger(__name__)

_fernet_instance: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance is None:
        settings = get_settings()
        import os
        secret = (
            os.getenv("CREDENTIAL_ENCRYPTION_KEY")
            or settings.jwt_signing_key
            or settings.SECRET_KEY
            or ""
        ).strip()
        if not secret:
            raise RuntimeError(
                "No encryption key configured for credential storage at rest. "
                "Set CREDENTIAL_ENCRYPTION_KEY, JWT_SECRET, or SECRET_KEY environment variable."
            )
        key_bytes = hashlib.sha256(secret.encode("utf-8")).digest()
        fernet_key = base64.urlsafe_b64encode(key_bytes)
        _fernet_instance = Fernet(fernet_key)
    return _fernet_instance


def encrypt_string(plain_text: str) -> str:
    """Encrypt plain text string into Fernet token string."""
    if not plain_text:
        return ""
    f = _get_fernet()
    return f.encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_string(encrypted_token: str) -> str:
    """Decrypt Fernet token string back into plain text."""
    if not encrypted_token:
        return ""
    f = _get_fernet()
    try:
        return f.decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        logger.error("Failed to decrypt string: %s", exc)
        raise ValueError("Invalid or corrupted encrypted token") from exc
