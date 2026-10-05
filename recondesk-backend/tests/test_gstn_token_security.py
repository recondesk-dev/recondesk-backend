"""Tests for GSTN token encryption at rest and leak prevention in API responses."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.routers.clients import serialize_client
from app.utils.crypto import decrypt_secret, encrypt_secret, is_encrypted_secret
from app.services.gst_fetch.token import ensure_fresh_gstn_token

client = TestClient(app)


def test_serialize_client_strips_sensitive_tokens():
    raw_client = {
        "id": "11111111-1111-1111-1111-111111111111",
        "gstin": "27AAPFU0939F1ZV",
        "trade_name": "Acme Corp",
        "gstn_access_token": "v1:0123456789abcdef:fedcba9876543210",
        "gstn_refresh_token": "secret_refresh",
        "einvoice_password": "secret_password",
        "api_secret": "secret_api",
        "gstn_token_expiry": "2026-12-31T23:59:59Z",
    }

    serialized = serialize_client(raw_client)
    assert serialized is not None
    assert serialized["id"] == raw_client["id"]
    assert serialized["gstin"] == raw_client["gstin"]

    # Secrets stripped
    assert serialized["gstn_access_token"] is None
    assert "gstn_refresh_token" not in serialized
    assert "einvoice_password" not in serialized
    assert "api_secret" not in serialized

    # Safe presence flags preserved
    assert serialized["has_gstn_token"] is True
    assert serialized["is_gstn_connected"] is True


def test_serialize_client_empty_token():
    raw_client = {
        "id": "11111111-1111-1111-1111-111111111111",
        "gstin": "27AAPFU0939F1ZV",
        "gstn_access_token": None,
        "gstn_token_expiry": None,
    }

    serialized = serialize_client(raw_client)
    assert serialized["gstn_access_token"] is None
    assert serialized["has_gstn_token"] is False
    assert serialized["is_gstn_connected"] is False


def test_ensure_fresh_gstn_token_decrypts_encrypted_token():
    mock_sb = MagicMock()
    raw_token = "live_taxpayer_token_999888"
    encrypted_envelope = encrypt_secret(raw_token)

    client_row = {
        "id": "client-uuid-1",
        "gstin": "27AAPFU0939F1ZV",
        "gstn_access_token": encrypted_envelope,
        "gstn_token_expiry": "2030-01-01T00:00:00Z",
    }

    token = ensure_fresh_gstn_token(mock_sb, client_row)
    assert token == raw_token


def test_ensure_fresh_gstn_token_handles_legacy_plaintext():
    mock_sb = MagicMock()
    legacy_token = "legacy_unencrypted_token_plaintext"

    client_row = {
        "id": "client-uuid-2",
        "gstin": "27AAPFU0939F1ZV",
        "gstn_access_token": legacy_token,
        "gstn_token_expiry": "2030-01-01T00:00:00Z",
    }

    token = ensure_fresh_gstn_token(mock_sb, client_row)
    assert token == legacy_token
