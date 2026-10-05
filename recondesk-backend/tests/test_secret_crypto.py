"""Tests for authenticated AES-GCM secret encryption at rest."""

import os
import pytest

from app.utils.crypto import (
    ENVELOPE_PREFIX_V1,
    decrypt_secret,
    encrypt_secret,
    get_encryption_key,
    is_encrypted_secret,
)


def test_encryption_roundtrip():
    secret = "gstn_session_token_xyz_12345"
    encrypted = encrypt_secret(secret)
    assert encrypted is not None
    assert encrypted.startswith(ENVELOPE_PREFIX_V1)
    assert secret not in encrypted

    decrypted = decrypt_secret(encrypted)
    assert decrypted == secret


def test_unique_nonce_per_encryption():
    secret = "fixed_secret_value"
    enc1 = encrypt_secret(secret)
    enc2 = encrypt_secret(secret)

    assert enc1 != enc2
    assert decrypt_secret(enc1) == secret
    assert decrypt_secret(enc2) == secret


def test_legacy_plaintext_backward_compatibility():
    legacy_secret = "legacy_unencrypted_token_123"
    assert not is_encrypted_secret(legacy_secret)

    # Calling decrypt_secret on unencrypted legacy value returns the plaintext as-is
    decrypted = decrypt_secret(legacy_secret)
    assert decrypted == legacy_secret


def test_idempotent_encryption_no_double_wrapping():
    secret = "my_api_key_secret"
    enc = encrypt_secret(secret)
    assert enc.startswith(ENVELOPE_PREFIX_V1)

    # Re-encrypting already encrypted string returns same string
    enc_again = encrypt_secret(enc)
    assert enc_again == enc
    assert decrypt_secret(enc_again) == secret


def test_malformed_envelope_handling():
    with pytest.raises(ValueError, match="Malformed encrypted secret envelope"):
        decrypt_secret("v1:only_one_part")

    with pytest.raises(ValueError, match="Invalid hex"):
        decrypt_secret("v1:not_hex:not_hex")


def test_tampered_ciphertext_fails_integrity():
    secret = "sensitive_data"
    encrypted = encrypt_secret(secret)
    parts = encrypted.split(":")
    nonce_hex = parts[1]
    ct_hex = parts[2]

    # Tamper with the last byte of ciphertext
    tampered_ct = ct_hex[:-2] + ("00" if ct_hex[-2:] != "00" else "11")
    tampered_envelope = f"v1:{nonce_hex}:{tampered_ct}"

    with pytest.raises(ValueError, match="Decryption failed"):
        decrypt_secret(tampered_envelope)


def test_wrong_key_fails_decryption():
    key1 = os.urandom(32)
    key2 = os.urandom(32)
    secret = "secret_to_protect"

    encrypted = encrypt_secret(secret, key=key1)
    with pytest.raises(ValueError, match="Decryption failed"):
        decrypt_secret(encrypted, key=key2)


def test_none_and_empty_inputs():
    assert encrypt_secret(None) is None
    assert encrypt_secret("") == ""
    assert decrypt_secret(None) is None
    assert decrypt_secret("") == ""
