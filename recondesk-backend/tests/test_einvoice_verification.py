"""Unit tests for e-Invoice live verification service & Sandbox client integration."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.einvoice_verification import (
    get_client_credentials,
    upsert_client_credentials,
    verify_irn_missing_batch,
    verify_irn_missing_row,
)
from app.services.sandbox_einvoice_client import (
    EinvoiceAuthError,
    EinvoiceDownError,
)
from app.utils.crypto import decrypt_string, encrypt_string


def test_crypto_encryption_decryption():
    """Verify Fernet password encryption and decryption round-trip."""
    secret_pass = "TaxpayerSecret@123"
    enc = encrypt_string(secret_pass)

    assert enc != secret_pass
    assert len(enc) > 20

    dec = decrypt_string(enc)
    assert dec == secret_pass


def test_crypto_missing_secret_raises_runtime_error():
    """Verify that RuntimeError is raised when no encryption secret keys are configured."""
    from app.utils import crypto
    old_instance = crypto._fernet_instance
    try:
        crypto._fernet_instance = None
        mock_settings = MagicMock()
        mock_settings.jwt_signing_key = ""
        mock_settings.SECRET_KEY = ""

        with patch("app.utils.crypto.get_settings", return_value=mock_settings), \
             patch("os.getenv", return_value=""):
            with pytest.raises(RuntimeError) as exc_info:
                crypto.encrypt_string("test_password")
            assert "No encryption key configured" in str(exc_info.value)
    finally:
        crypto._fernet_instance = old_instance


def test_verify_irn_missing_row_upgrade_to_matched():
    """When IRP returns invoice, row is upgraded to MATCHED with irp_live_lookup."""
    mock_sb = MagicMock()

    # Mock einvoice_recon_results query
    mock_sb.table().select().eq().limit().execute.side_effect = [
        # 1. einvoice_recon_results
        MagicMock(data=[{
            "id": "res-101",
            "client_gstin_id": "client-1",
            "category": "IRN_MISSING",
            "invoice_number": "INV-100",
            "period": "2024-04",
            "details": {"invoice_date": "2024-04-10"},
        }]),
        # 2. client_einvoice_credentials
        MagicMock(data=[{
            "id": "cred-1",
            "client_gstin_id": "client-1",
            "einvoice_username": "taxpayer_user",
            "einvoice_password": encrypt_string("secret_pass"),
            "session_token": "valid_token_123",
            "session_token_expiry": "2099-01-01T00:00:00+00:00",
        }]),
        # 3. client_gstins
        MagicMock(data=[{"gstin": "27AAPCS1429B1Z0"}]),
    ]

    # Mock client_gstins access check
    mock_sb.table().select().eq().limit().execute.side_effect = [
        MagicMock(data=[{
            "id": "res-101",
            "client_gstin_id": "client-1",
            "category": "IRN_MISSING",
            "invoice_number": "INV-100",
            "period": "2024-04",
            "details": {"invoice_date": "2024-04-10"},
        }]),
        MagicMock(data=[{
            "id": "cred-1",
            "client_gstin_id": "client-1",
            "einvoice_username": "taxpayer_user",
            "einvoice_password": encrypt_string("secret_pass"),
            "session_token": "valid_token_123",
            "session_token_expiry": "2099-01-01T00:00:00+00:00",
        }]),
        MagicMock(data=[{"gstin": "27AAPCS1429B1Z0"}]),
    ]

    # Mock update query
    mock_sb.table().update().eq().execute.return_value = MagicMock(data=[{
        "id": "res-101",
        "invoice_number": "INV-100",
        "category": "MATCHED",
        "irn": "IRN_FOUND_123",
        "irn_status": "Active",
        "verification_source": "irp_live_lookup",
        "verified_at": "2026-08-07T18:00:00+00:00",
        "details": {"verification_source": "irp_live_lookup"},
    }])

    with patch("app.services.einvoice_verification.ws.assert_client_access"), \
         patch("app.services.einvoice_verification.einvoice_client.get_einvoice_by_doc") as mock_get_doc:

        mock_get_doc.return_value = {
            "irn": "IRN_FOUND_123",
            "status": "Active",
            "ack_no": "ACK98765",
            "ack_date": "2024-04-10",
        }

        res = verify_irn_missing_row(mock_sb, "res-101", "user-1")

        assert res["category"] == "MATCHED"
        assert res["irn"] == "IRN_FOUND_123"
        assert res["verification_source"] == "irp_live_lookup"


def test_verify_irn_missing_row_confirmed_missing():
    """When IRP returns 404/None, category remains IRN_MISSING with irp_verified_missing."""
    mock_sb = MagicMock()

    mock_sb.table().select().eq().limit().execute.side_effect = [
        MagicMock(data=[{
            "id": "res-102",
            "client_gstin_id": "client-1",
            "category": "IRN_MISSING",
            "invoice_number": "INV-200",
            "period": "2024-04",
            "details": {"invoice_date": "2024-04-12"},
        }]),
        MagicMock(data=[{
            "id": "cred-1",
            "client_gstin_id": "client-1",
            "einvoice_username": "taxpayer_user",
            "einvoice_password": encrypt_string("secret_pass"),
            "session_token": "valid_token_123",
            "session_token_expiry": "2099-01-01T00:00:00+00:00",
        }]),
        MagicMock(data=[{"gstin": "27AAPCS1429B1Z0"}]),
    ]

    mock_sb.table().update().eq().execute.return_value = MagicMock(data=[{
        "id": "res-102",
        "invoice_number": "INV-200",
        "category": "IRN_MISSING",
        "verification_source": "irp_verified_missing",
        "verified_at": "2026-08-07T18:00:00+00:00",
    }])

    with patch("app.services.einvoice_verification.ws.assert_client_access"), \
         patch("app.services.einvoice_verification.einvoice_client.get_einvoice_by_doc") as mock_get_doc:

        mock_get_doc.return_value = None  # 404 Not Found

        res = verify_irn_missing_row(mock_sb, "res-102", "user-1")

        assert res["category"] == "IRN_MISSING"
        assert res["verification_source"] == "irp_verified_missing"


def test_verify_irn_missing_row_api_error_leaves_row_unchanged():
    """When IRP encounters 5xx/network error, exception is raised and DB row is not updated."""
    mock_sb = MagicMock()

    mock_sb.table().select().eq().limit().execute.side_effect = [
        MagicMock(data=[{
            "id": "res-103",
            "client_gstin_id": "client-1",
            "category": "IRN_MISSING",
            "invoice_number": "INV-300",
            "period": "2024-04",
            "details": {"invoice_date": "2024-04-15"},
        }]),
        MagicMock(data=[{
            "id": "cred-1",
            "client_gstin_id": "client-1",
            "einvoice_username": "taxpayer_user",
            "einvoice_password": encrypt_string("secret_pass"),
            "session_token": "valid_token_123",
            "session_token_expiry": "2099-01-01T00:00:00+00:00",
        }]),
        MagicMock(data=[{"gstin": "27AAPCS1429B1Z0"}]),
    ]

    with patch("app.services.einvoice_verification.ws.assert_client_access"), \
         patch("app.services.einvoice_verification.einvoice_client.get_einvoice_by_doc") as mock_get_doc:

        mock_get_doc.side_effect = EinvoiceDownError("IRP gateway error 502")

        with pytest.raises(EinvoiceDownError):
            verify_irn_missing_row(mock_sb, "res-103", "user-1")

        # Verify update was NOT called
        mock_sb.table().update.assert_not_called()


def test_verify_irn_missing_row_credit_note_doc_type():
    """Verify that Credit Note document type ('CRN') is dynamically passed to IRP lookup."""
    mock_sb = MagicMock()

    mock_sb.table().select().eq().limit().execute.side_effect = [
        MagicMock(data=[{
            "id": "res-cn-1",
            "client_gstin_id": "client-1",
            "category": "IRN_MISSING",
            "invoice_number": "CN-501",
            "period": "2024-04",
            "details": {"invoice_date": "2024-04-15", "doc_type": "Credit Note"},
        }]),
        MagicMock(data=[{
            "id": "cred-1",
            "client_gstin_id": "client-1",
            "einvoice_username": "taxpayer_user",
            "einvoice_password": encrypt_string("secret_pass"),
            "session_token": "valid_token_123",
            "session_token_expiry": "2099-01-01T00:00:00+00:00",
        }]),
        MagicMock(data=[{"gstin": "27AAPCS1429B1Z0"}]),
    ]

    mock_sb.table().update().eq().execute.return_value = MagicMock(data=[{
        "id": "res-cn-1",
        "invoice_number": "CN-501",
        "category": "MATCHED",
        "irn": "IRN_CN_999",
        "verification_source": "irp_live_lookup",
    }])

    with patch("app.services.einvoice_verification.ws.assert_client_access"), \
         patch("app.services.einvoice_verification.einvoice_client.get_einvoice_by_doc") as mock_get_doc:

        mock_get_doc.return_value = {"irn": "IRN_CN_999", "status": "Active"}

        res = verify_irn_missing_row(mock_sb, "res-cn-1", "user-1")

        mock_get_doc.assert_called_once_with(
            session_token="valid_token_123",
            gstin="27AAPCS1429B1Z0",
            doc_number="CN-501",
            doc_date="2024-04-15",
            doc_type="CRN",
        )
        assert res["category"] == "MATCHED"


def test_verify_irn_missing_batch_rate_limiting():
    """Verify batch processing calls time.sleep(1.0) between items to respect 1 req/sec limit."""
    mock_sb = MagicMock()

    with patch("app.services.einvoice_verification.verify_irn_missing_row") as mock_verify_row, \
         patch("app.services.einvoice_verification.time.sleep") as mock_sleep:

        mock_verify_row.side_effect = [
            {"id": "r1", "category": "MATCHED"},
            {"id": "r2", "category": "IRN_MISSING"},
            {"id": "r3", "category": "MATCHED"},
        ]

        res = verify_irn_missing_batch(mock_sb, ["r1", "r2", "r3"], "user-1")

        assert res["total_requested"] == 3
        assert res["verified_count"] == 3
        assert res["matched_upgrades"] == 2
        # time.sleep(1.0) should be called between items (i.e. 2 times for 3 items)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(1.0)

