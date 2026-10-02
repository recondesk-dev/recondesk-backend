"""Tests for Cloud Storage Migration (Cloudflare R2 -> Amazon S3).

Verifies:
1. Native AWS S3 direct upload, download, existence check, and deletion.
2. Presigned PUT (upload) and GET (download) URL generation targeting AWS S3.
3. SHA-256 integrity verification and corrupted payload rejection.
4. Dual-read fallback and transparent sync-on-read.
5. Tenant path isolation and key formatting.
6. Binary Excel/document byte parity.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException

from app.services.storage_service import StorageService, get_storage_service


@pytest.fixture
def storage_service():
    """Return isolated StorageService instance."""
    return StorageService()


def test_storage_service_singleton():
    """Verify singleton accessor returns consistent instance."""
    s1 = get_storage_service()
    s2 = get_storage_service()
    assert s1 is s2
    assert s1.s3_bucket is not None


def test_tenant_path_isolation(storage_service):
    """Verify generated keys enforce strict tenant prefix isolation."""
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    key_a = storage_service.generate_file_key("sales_register.xlsx", tenant_a)
    key_b = storage_service.generate_file_key("sales_register.xlsx", tenant_b)

    assert key_a.startswith(f"uploads/{tenant_a}/")
    assert key_b.startswith(f"uploads/{tenant_b}/")
    assert key_a != key_b
    assert key_a.endswith(".xlsx")


def test_presigned_upload_url_generation(storage_service):
    """Verify presigned upload URL points to S3 bucket with correct parameters."""
    mock_s3 = MagicMock()
    mock_s3.generate_presigned_url.return_value = (
        "https://recondesk-storage-991216470563.s3.ap-south-1.amazonaws.com/test_key.xlsx?sig=xyz"
    )

    with patch.object(storage_service, "get_s3_client", return_value=mock_s3):
        url = storage_service.generate_presigned_upload_url(
            key="test/sample.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            expires_in=900,
        )
        assert "amazonaws.com" in url
        mock_s3.generate_presigned_url.assert_called_once_with(
            "put_object",
            Params={
                "Bucket": storage_service.s3_bucket,
                "Key": "test/sample.xlsx",
                "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
            ExpiresIn=900,
        )


def test_presigned_download_url_generation(storage_service):
    """Verify presigned download URL points to S3 bucket and includes disposition."""
    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {"ContentLength": 1024}
    mock_s3.generate_presigned_url.return_value = (
        "https://recondesk-storage-991216470563.s3.ap-south-1.amazonaws.com/test_key.xlsx?sig=abc"
    )

    with patch.object(storage_service, "get_s3_client", return_value=mock_s3):
        url = storage_service.generate_presigned_download_url(
            key="test/sample.xlsx",
            expires_in=600,
            filename="my_download.xlsx",
        )
        assert "amazonaws.com" in url
        mock_s3.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={
                "Bucket": storage_service.s3_bucket,
                "Key": "test/sample.xlsx",
                "ResponseContentDisposition": 'attachment; filename="my_download.xlsx"',
            },
            ExpiresIn=600,
        )


def test_sha256_verification_pass_and_fail(storage_service):
    """Verify SHA-256 verification succeeds on match and rejects mismatch/overflow."""
    sample_content = b"ReconDesk integrity verified payload 12345"
    valid_hash = hashlib.sha256(sample_content).hexdigest()
    corrupt_hash = hashlib.sha256(b"corrupted payload").hexdigest()

    mock_download = MagicMock(return_value=sample_content)
    with patch.object(storage_service, "download_bytes", mock_download):
        # 1. Matching hash -> returns length
        length = storage_service.verify_sha256("test/key.txt", valid_hash)
        assert length == len(sample_content)

        # 2. Corrupt hash -> raises HTTPException(400)
        with pytest.raises(HTTPException) as exc_info:
            storage_service.verify_sha256("test/key.txt", corrupt_hash)
        assert exc_info.value.status_code == 400
        assert "File hash mismatch" in exc_info.value.detail

        # 3. Max size exceeded -> raises HTTPException(400)
        with pytest.raises(HTTPException) as exc_info_size:
            storage_service.verify_sha256("test/key.txt", valid_hash, max_bytes=10)
        assert exc_info_size.value.status_code == 400
        assert "File too large" in exc_info_size.value.detail


def test_dual_read_fallback_and_sync_on_read(storage_service):
    """Verify that an S3 miss triggers R2 fallback and automatically syncs to S3."""
    mock_s3 = MagicMock()
    mock_r2 = MagicMock()

    # S3 returns NoSuchKey
    mock_s3.get_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "Not found"}}, "GetObject"
    )

    # R2 has the object
    legacy_bytes = b"Legacy R2 unmigrated invoice data"
    mock_r2.get_object.return_value = {
        "Body": io.BytesIO(legacy_bytes),
        "ContentType": "application/pdf",
        "ContentLength": len(legacy_bytes),
    }

    with patch.object(storage_service, "get_s3_client", return_value=mock_s3), \
         patch.object(storage_service, "get_r2_client", return_value=mock_r2):

        obj = storage_service.get_object("uploads/user_123/legacy_doc.pdf")
        downloaded = obj["Body"].read()
        assert downloaded == legacy_bytes

        # Verify S3 was called to check first
        mock_s3.get_object.assert_called_once()

        # Verify R2 was checked second
        mock_r2.get_object.assert_called_once()

        # Verify transparent sync-on-read uploaded object to S3
        mock_s3.put_object.assert_called_once_with(
            Bucket=storage_service.s3_bucket,
            Key="uploads/user_123/legacy_doc.pdf",
            Body=legacy_bytes,
            ContentType="application/pdf",
            ServerSideEncryption="AES256",
            Metadata={"migrated_from": "r2_fallback_sync"},
        )


def test_delete_object_both_stores(storage_service):
    """Verify deletion targets both S3 and R2 to prevent ghost recurrence."""
    mock_s3 = MagicMock()
    mock_r2 = MagicMock()

    with patch.object(storage_service, "get_s3_client", return_value=mock_s3), \
         patch.object(storage_service, "get_r2_client", return_value=mock_r2):

        result = storage_service.delete_object("uploads/user_123/file.csv")
        assert result is True

        mock_s3.delete_object.assert_called_once_with(
            Bucket=storage_service.s3_bucket,
            Key="uploads/user_123/file.csv",
        )
        mock_r2.delete_object.assert_called_once_with(
            Bucket=storage_service.r2_bucket,
            Key="uploads/user_123/file.csv",
        )


def test_excel_binary_integrity(storage_service):
    """Verify arbitrary binary payloads (e.g. zip/xlsx) roundtrip without corruption."""
    # Simulate binary xlsx header (PK..)
    binary_payload = b"PK\x03\x04\x14\x00\x06\x00\x08\x00\x00\x00!\x00" + (b"\x99" * 4096)

    mock_s3 = MagicMock()
    mock_s3.get_object.return_value = {
        "Body": io.BytesIO(binary_payload),
        "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "ContentLength": len(binary_payload),
    }

    with patch.object(storage_service, "get_s3_client", return_value=mock_s3):
        retrieved = storage_service.download_bytes("test/binary_excel.xlsx")
        assert retrieved == binary_payload
        assert len(retrieved) == len(binary_payload)
