"""Tests for Tally Bridge API key hashing and backward compatibility."""

import hashlib
import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException

from app.routers.tally_sync import _lookup_bridge_key
from app.services.tally_bridge_sync import (
    API_KEY_PREFIX,
    generate_tally_bridge_api_key,
    hash_tally_bridge_api_key,
)


def test_tally_key_prefix():
    key = generate_tally_bridge_api_key()
    assert key.startswith("rd_tb_")
    assert len(key) > 40


def test_tally_key_hashing_sha256():
    raw = "rd_tb_sample_key_12345"
    expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert hash_tally_bridge_api_key(raw) == expected


def test_lookup_bridge_key_matches_hashed_key(monkeypatch):
    raw_key = "rd_tb_test_secure_key_123"
    hashed_key = hash_tally_bridge_api_key(raw_key)

    mock_sb = MagicMock()
    mock_sb.table().select().eq().limit().execute.return_value.data = [
        {
            "id": "key-id-1",
            "api_key": hashed_key,
            "account_id": "firm-1",
            "company_name": "Test Co",
            "last_synced_at": None,
            "revoked_at": None,
        }
    ]
    monkeypatch.setattr("app.routers.tally_sync.get_supabase", lambda: mock_sb)

    row = _lookup_bridge_key(raw_key)
    assert row["id"] == "key-id-1"
    assert row["account_id"] == "firm-1"


def test_lookup_bridge_key_migrates_legacy_plaintext_key(monkeypatch):
    raw_key = "rdb_legacy_unhashed_key_xyz"
    hashed_key = hash_tally_bridge_api_key(raw_key)

    mock_sb = MagicMock()
    # First query (eq hashed_key) returns empty
    # Second query (eq raw_key) returns legacy row
    exec_mock = MagicMock()
    exec_mock.execute.side_effect = [
        MagicMock(data=[]),  # hashed lookup misses
        MagicMock(data=[{    # plaintext lookup hits
            "id": "legacy-key-id",
            "api_key": raw_key,
            "account_id": "firm-2",
            "company_name": "Legacy Co",
            "last_synced_at": None,
            "revoked_at": None,
        }]),
        MagicMock(data=[]),  # update query result
    ]
    mock_sb.table().select().eq().limit.return_value = exec_mock
    monkeypatch.setattr("app.routers.tally_sync.get_supabase", lambda: mock_sb)

    row = _lookup_bridge_key(raw_key)
    assert row["id"] == "legacy-key-id"
    # Row's api_key upgraded in memory and in DB
    assert row["api_key"] == hashed_key
    mock_sb.table().update.assert_called_with({"api_key": hashed_key})


def test_lookup_bridge_key_rejects_wrong_key(monkeypatch):
    mock_sb = MagicMock()
    mock_sb.table().select().eq().limit().execute.return_value.data = []
    monkeypatch.setattr("app.routers.tally_sync.get_supabase", lambda: mock_sb)

    with pytest.raises(HTTPException) as exc:
        _lookup_bridge_key("invalid_key_999")
    assert exc.value.status_code == 401
    assert "invalid api key" in exc.value.detail


def test_lookup_bridge_key_rejects_revoked_key(monkeypatch):
    raw_key = "rd_tb_revoked_key"
    mock_sb = MagicMock()
    mock_sb.table().select().eq().limit().execute.return_value.data = [
        {
            "id": "key-id-revoked",
            "api_key": hash_tally_bridge_api_key(raw_key),
            "account_id": "firm-1",
            "company_name": "Revoked Co",
            "last_synced_at": None,
            "revoked_at": "2026-01-01T00:00:00Z",
        }
    ]
    monkeypatch.setattr("app.routers.tally_sync.get_supabase", lambda: mock_sb)

    with pytest.raises(HTTPException) as exc:
        _lookup_bridge_key(raw_key)
    assert exc.value.status_code == 401
    assert "revoked" in exc.value.detail
