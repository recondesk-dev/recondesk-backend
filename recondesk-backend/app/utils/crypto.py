"""Authenticated encryption utility for sensitive tokens at rest.

Uses AES-256-GCM authenticated encryption with a versioned envelope format:
    v1:<nonce_hex>:<ciphertext_and_tag_hex>

Supports seamless backward compatibility: if a value does not begin with the
version prefix (e.g. legacy plaintext), `decrypt_secret` returns the legacy
plaintext without error so callers can transparently re-encrypt on next write.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

_log = logging.getLogger(__name__)

ENVELOPE_PREFIX_V1 = "v1:"
_fernet_instance = None


def get_encryption_key() -> bytes:
    """Derive a 32-byte AES-GCM key from configuration.
    
    Priority:
    1. settings.DATA_ENCRYPTION_KEY
    2. settings.SECRET_KEY
    3. settings.JWT_SECRET
    """
    settings = get_settings()
    configured_key = ""
    for attr in ("DATA_ENCRYPTION_KEY", "SECRET_KEY", "JWT_SECRET", "jwt_signing_key"):
        if hasattr(settings, attr):
            val = getattr(settings, attr)
            if callable(val):
                try:
                    val = val()
                except Exception:
                    val = ""
            if isinstance(val, str) and val.strip():
                configured_key = val.strip()
                break

    if not configured_key:
        for env_var in ("DATA_ENCRYPTION_KEY", "SECRET_KEY", "JWT_SECRET"):
            env_val = os.getenv(env_var, "").strip()
            if env_val:
                configured_key = env_val
                break

    if not configured_key:
        raise RuntimeError("No encryption key configured in settings (DATA_ENCRYPTION_KEY, SECRET_KEY, or JWT_SECRET required)")

    # Derive 32 bytes using SHA-256 with a domain-separation salt
    salt = b"recondesk_token_encryption_v1"
    return hashlib.sha256(salt + configured_key.encode("utf-8")).digest()


def is_encrypted_secret(value: Optional[str]) -> bool:
    """Check if value is formatted with an encrypted envelope."""
    if not value or not isinstance(value, str):
        return False
    return value.startswith(ENVELOPE_PREFIX_V1)


def encrypt_secret(plaintext: Optional[str], key: Optional[bytes] = None) -> Optional[str]:
    """Encrypt a secret string into a versioned AES-GCM envelope.
    
    Returns None if plaintext is None or empty.
    If plaintext is already encrypted with 'v1:', returns it unchanged to prevent double-encryption.
    """
    if plaintext is None:
        return None
    cleaned = str(plaintext).strip()
    if not cleaned:
        return ""
    if is_encrypted_secret(cleaned):
        return cleaned

    aes_key = key or get_encryption_key()
    aesgcm = AESGCM(aes_key)
    # 96-bit (12-byte) random nonce recommended for AES-GCM
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, cleaned.encode("utf-8"), None)

    return f"{ENVELOPE_PREFIX_V1}{nonce.hex()}:{ciphertext.hex()}"


def decrypt_secret(ciphertext: Optional[str], key: Optional[bytes] = None) -> Optional[str]:
    """Decrypt a secret value from an AES-GCM envelope.
    
    If the value does not start with 'v1:', it is treated as a legacy plaintext
    value and returned as-is for backward-compatibility.
    
    Raises ValueError if ciphertext is malformed or decryption authentication fails.
    """
    if ciphertext is None:
        return None
    cleaned = str(ciphertext).strip()
    if not cleaned:
        return ""

    if not cleaned.startswith(ENVELOPE_PREFIX_V1):
        # Legacy plaintext backward compatibility
        return cleaned

    payload = cleaned[len(ENVELOPE_PREFIX_V1):]
    parts = payload.split(":", 1)
    if len(parts) != 2:
        raise ValueError("Malformed encrypted secret envelope: expected nonce:ciphertext")

    nonce_hex, ct_hex = parts
    try:
        nonce = bytes.fromhex(nonce_hex)
        ct = bytes.fromhex(ct_hex)
    except ValueError as exc:
        raise ValueError("Invalid hex encoding in encrypted secret envelope") from exc

    aes_key = key or get_encryption_key()
    aesgcm = AESGCM(aes_key)

    try:
        decrypted_bytes = aesgcm.decrypt(nonce, ct, None)
        return decrypted_bytes.decode("utf-8")
    except Exception as exc:
        _log.error("Failed to decrypt secret envelope")
        raise ValueError("Decryption failed: integrity check failed or invalid key") from exc


# Backward-compatible aliases for existing callers
encrypt_string = encrypt_secret
decrypt_string = decrypt_secret
