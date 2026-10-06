"""Tests for Sprint 2B reconciliation payload storage offloading (R2/S3 + DB fallback)."""

import base64
import gzip
import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.reconciliation_payload_store import (
    delete_reconciliation_payload,
    save_reconciliation_results,
)
from app.services.reconciliation_outcomes import load_payload, _req_cache


@pytest.fixture(autouse=True)
def clear_payload_cache():
    _req_cache().clear()
    yield
    _req_cache().clear()


def test_save_reconciliation_results_r2_success():
    """When R2 is configured, save_reconciliation_results uploads compressed payload to R2."""
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_sb.table.return_value = mock_table
    mock_table.delete.return_value.eq.return_value.execute.return_value = MagicMock()
    mock_table.insert.return_value.execute.return_value = MagicMock(data=[{"run_id": "run-123"}], error=None)

    sample_payload = {
        "engine": {"matched": [{"gstr_id": "g1", "pr_id": "p1"}]},
        "compliance": {},
        "decisions": {},
    }

    with patch("app.services.reconciliation_payload_store.is_r2_configured", return_value=True), \
         patch("app.services.reconciliation_payload_store.upload_bytes_to_r2") as mock_upload, \
         patch("app.config.settings.RECONCILIATION_PAYLOAD_STORAGE", "auto"):
        
        meta = save_reconciliation_results(
            mock_sb,
            "run-123",
            sample_payload,
            created_at="2026-10-06T12:00:00Z",
        )

        assert meta["storage_type"] == "r2"
        assert meta["storage_path"] == "reconciliation-payloads/run-123.json.gz"
        assert mock_upload.called
        uploaded_bytes, target_key = mock_upload.call_args[0][:2]
        assert target_key == "reconciliation-payloads/run-123.json.gz"
        # Decompress to verify uploaded payload
        decompressed = json.loads(gzip.decompress(uploaded_bytes).decode("utf-8"))
        assert decompressed == sample_payload

        # Verify DB insert payload was an R2 pointer stub
        insert_row = mock_table.insert.call_args[0][0]
        assert insert_row["run_id"] == "run-123"
        assert insert_row["storage_type"] == "r2"
        assert insert_row["storage_path"] == "reconciliation-payloads/run-123.json.gz"
        assert insert_row["payload"]["_storage"] == "r2"


def test_save_reconciliation_results_fallback_to_db_on_r2_error():
    """If R2 upload fails, it falls back to DB base64 storage without raising."""
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_sb.table.return_value = mock_table
    mock_table.delete.return_value.eq.return_value.execute.return_value = MagicMock()
    mock_table.insert.return_value.execute.return_value = MagicMock(data=[{"run_id": "run-456"}], error=None)

    sample_payload = {"engine": {"matched": []}}

    with patch("app.services.reconciliation_payload_store.is_r2_configured", return_value=True), \
         patch("app.services.reconciliation_payload_store.upload_bytes_to_r2", side_effect=RuntimeError("S3 network failure")), \
         patch("app.config.settings.RECONCILIATION_PAYLOAD_STORAGE", "auto"):
        
        meta = save_reconciliation_results(
            mock_sb,
            "run-456",
            sample_payload,
            created_at="2026-10-06T12:00:00Z",
        )

        assert meta["storage_type"] == "db"
        assert meta["storage_path"] is None

        insert_row = mock_table.insert.call_args[0][0]
        assert insert_row["storage_type"] == "db"
        assert isinstance(insert_row["payload"], str)  # base64 encoded


def test_save_reconciliation_results_legacy_db_schema_fallback():
    """If DB table does not yet have storage_type column, gracefully falls back to legacy insert."""
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_sb.table.return_value = mock_table
    mock_table.delete.return_value.eq.return_value.execute.return_value = MagicMock()

    # First insert raises column missing error; second (legacy) insert succeeds
    mock_table.insert.return_value.execute.side_effect = [
        Exception("column 'storage_type' of relation 'reconciliation_results' does not exist"),
        MagicMock(data=[{"run_id": "run-789"}], error=None),
    ]

    sample_payload = {"engine": {"matched": []}}

    with patch("app.services.reconciliation_payload_store.is_r2_configured", return_value=False), \
         patch("app.config.settings.RECONCILIATION_PAYLOAD_STORAGE", "db"):
        
        meta = save_reconciliation_results(
            mock_sb,
            "run-789",
            sample_payload,
            created_at="2026-10-06T12:00:00Z",
        )

        assert meta["storage_type"] == "db"
        assert mock_table.insert.call_count == 2
        legacy_call_args = mock_table.insert.call_args_list[1][0][0]
        assert "storage_type" not in legacy_call_args
        assert "run_id" in legacy_call_args
        assert "payload" in legacy_call_args


def test_load_payload_from_r2():
    """load_payload retrieves and decompresses data when storage_type is r2."""
    sample_payload = {
        "engine": {"matched": [{"gstr_id": "g-100", "pr_id": "p-100"}]},
        "compliance": {"rule37": []},
    }
    compressed_bytes = gzip.compress(json.dumps(sample_payload).encode("utf-8"))

    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_sb.table.return_value = mock_table
    mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[
            {
                "run_id": "run-r2",
                "storage_type": "r2",
                "storage_path": "reconciliation-payloads/run-r2.json.gz",
                "payload": {"_storage": "r2", "path": "reconciliation-payloads/run-r2.json.gz"},
            }
        ]
    )

    with patch("app.services.r2_service.download_file_from_r2", return_value=compressed_bytes) as mock_dl:
        loaded = load_payload(mock_sb, "run-r2")
        assert loaded == sample_payload
        mock_dl.assert_called_once_with("reconciliation-payloads/run-r2.json.gz")


def test_load_payload_from_legacy_db_base64():
    """load_payload correctly decompresses legacy DB base64 gzipped payload."""
    sample_payload = {"engine": {"matched": [{"gstr_id": "g-legacy"}]}}
    compressed_b64 = base64.b64encode(gzip.compress(json.dumps(sample_payload).encode("utf-8"))).decode("utf-8")

    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_sb.table.return_value = mock_table
    mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[
            {
                "run_id": "run-legacy",
                "storage_type": "db",
                "payload": compressed_b64,
            }
        ]
    )

    loaded = load_payload(mock_sb, "run-legacy")
    assert loaded == sample_payload


def test_delete_reconciliation_payload():
    """delete_reconciliation_payload removes R2 object and DB row."""
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_sb.table.return_value = mock_table
    mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[
            {
                "run_id": "run-del",
                "storage_type": "r2",
                "storage_path": "reconciliation-payloads/run-del.json.gz",
            }
        ]
    )
    mock_table.delete.return_value.eq.return_value.execute.return_value = MagicMock()

    with patch("app.services.reconciliation_payload_store.delete_file_from_r2") as mock_r2_del:
        delete_reconciliation_payload(mock_sb, "run-del")
        mock_r2_del.assert_called_once_with("reconciliation-payloads/run-del.json.gz")
        assert mock_table.delete.called


def test_save_reconciliation_results_forced_db_mode():
    """RECONCILIATION_PAYLOAD_STORAGE=db always writes to PostgreSQL even if R2 is configured."""
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_sb.table.return_value = mock_table
    mock_table.delete.return_value.eq.return_value.execute.return_value = MagicMock()
    mock_table.insert.return_value.execute.return_value = MagicMock(data=[{"run_id": "run-db-mode"}], error=None)

    sample_payload = {"engine": {"matched": []}}

    with patch("app.services.reconciliation_payload_store.is_r2_configured", return_value=True), \
         patch("app.services.reconciliation_payload_store.upload_bytes_to_r2") as mock_upload, \
         patch.dict("os.environ", {"RECONCILIATION_PAYLOAD_STORAGE": "db"}):
        
        meta = save_reconciliation_results(
            mock_sb,
            "run-db-mode",
            sample_payload,
            created_at="2026-10-06T12:00:00Z",
        )

        assert meta["storage_type"] == "db"
        assert meta["storage_path"] is None
        mock_upload.assert_not_called()


def test_path_traversal_sanitized_in_run_id():
    """Directory traversal sequences in run_id are stripped by os.path.basename."""
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_sb.table.return_value = mock_table
    mock_table.delete.return_value.eq.return_value.execute.return_value = MagicMock()
    mock_table.insert.return_value.execute.return_value = MagicMock(data=[{"run_id": "safe"}], error=None)

    sample_payload = {"engine": {"matched": []}}

    with patch("app.services.reconciliation_payload_store.is_r2_configured", return_value=True), \
         patch("app.services.reconciliation_payload_store.upload_bytes_to_r2") as mock_upload, \
         patch("app.config.settings.RECONCILIATION_PAYLOAD_STORAGE", "r2"):
        
        meta = save_reconciliation_results(
            mock_sb,
            "../../etc/passwd",
            sample_payload,
            created_at="2026-10-06T12:00:00Z",
        )

        assert meta["storage_path"] == "reconciliation-payloads/passwd.json.gz"
        assert ".." not in meta["storage_path"]


def test_delete_reconciliation_payload_error_idempotent():
    """delete_reconciliation_payload does not raise even if R2 delete fails."""
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_sb.table.return_value = mock_table
    mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[
            {
                "run_id": "run-fail",
                "storage_type": "r2",
                "storage_path": "reconciliation-payloads/run-fail.json.gz",
            }
        ]
    )
    mock_table.delete.return_value.eq.return_value.execute.return_value = MagicMock()

    with patch("app.services.reconciliation_payload_store.delete_file_from_r2", side_effect=RuntimeError("R2 unavailable")):
        # Must not raise
        delete_reconciliation_payload(mock_sb, "run-fail")
        assert mock_table.delete.called


def test_r2_payload_readable_when_mode_switched_to_db():
    """Existing R2-backed runs remain readable even if default storage mode is set to 'db'."""
    sample_payload = {"engine": {"matched": [{"gstr_id": "g-switch"}]}}
    compressed_bytes = gzip.compress(json.dumps(sample_payload).encode("utf-8"))

    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_sb.table.return_value = mock_table
    mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[
            {
                "run_id": "run-switch",
                "storage_type": "r2",
                "storage_path": "reconciliation-payloads/run-switch.json.gz",
            }
        ]
    )

    with patch("app.services.r2_service.download_file_from_r2", return_value=compressed_bytes), \
         patch("app.config.settings.RECONCILIATION_PAYLOAD_STORAGE", "db"):
        loaded = load_payload(mock_sb, "run-switch")
        assert loaded == sample_payload
