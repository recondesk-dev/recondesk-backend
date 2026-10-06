"""Tests for vendor portal file upload validation (magic bytes & extension security)."""

from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile

from app.routers.vendor_followup import upload_vendor_portal_file


@pytest.mark.asyncio
async def test_vendor_upload_valid_pdf():
    """Valid PDF with %PDF magic bytes and matching content type succeeds."""
    pdf_bytes = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    upload = UploadFile(
        filename="invoice_101.pdf",
        file=BytesIO(pdf_bytes),
        headers={"content-type": "application/pdf"},
    )

    with patch("app.routers.vendor_followup.get_supabase"), \
         patch("app.routers.vendor_followup.vf_svc.get_vendor_portal_data"), \
         patch("app.utils.storage.upload_file_raw", new_callable=AsyncMock) as mock_upload:
        
        resp = await upload_vendor_portal_file(token="tok-valid", file=upload)
        assert resp["filename"] == "invoice_101.pdf"
        assert resp["file_size"] == len(pdf_bytes)
        assert "vendor-responses/tok-valid/" in resp["attachment_key"]
        mock_upload.assert_awaited_once()


@pytest.mark.asyncio
async def test_vendor_upload_valid_png():
    """Valid PNG with \x89PNG magic bytes succeeds."""
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    upload = UploadFile(
        filename="receipt.png",
        file=BytesIO(png_bytes),
        headers={"content-type": "image/png"},
    )

    with patch("app.routers.vendor_followup.get_supabase"), \
         patch("app.routers.vendor_followup.vf_svc.get_vendor_portal_data"), \
         patch("app.utils.storage.upload_file_raw", new_callable=AsyncMock):
        
        resp = await upload_vendor_portal_file(token="tok-png", file=upload)
        assert resp["filename"] == "receipt.png"
        assert resp["file_size"] == len(png_bytes)


@pytest.mark.asyncio
async def test_vendor_upload_valid_jpeg():
    """Valid JPEG with \xff\xd8\xff magic bytes succeeds."""
    jpg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF"
    upload = UploadFile(
        filename="bill.jpg",
        file=BytesIO(jpg_bytes),
        headers={"content-type": "image/jpeg"},
    )

    with patch("app.routers.vendor_followup.get_supabase"), \
         patch("app.routers.vendor_followup.vf_svc.get_vendor_portal_data"), \
         patch("app.utils.storage.upload_file_raw", new_callable=AsyncMock):
        
        resp = await upload_vendor_portal_file(token="tok-jpg", file=upload)
        assert resp["filename"] == "bill.jpg"
        assert resp["file_size"] == len(jpg_bytes)


@pytest.mark.asyncio
async def test_vendor_upload_rejects_spoofed_pdf():
    """Executable or text script disguised with .pdf extension and application/pdf header is rejected."""
    malicious_bytes = b"<?php echo 'malicious payload'; ?>"
    upload = UploadFile(
        filename="exploit.pdf",
        file=BytesIO(malicious_bytes),
        headers={"content-type": "application/pdf"},
    )

    with patch("app.routers.vendor_followup.get_supabase"), \
         patch("app.routers.vendor_followup.vf_svc.get_vendor_portal_data"):
        
        with pytest.raises(HTTPException) as exc_info:
            await upload_vendor_portal_file(token="tok-spoof", file=upload)
        assert exc_info.value.status_code == 400
        assert "Invalid file signature" in exc_info.value.detail


@pytest.mark.asyncio
async def test_vendor_upload_rejects_disallowed_extension():
    """Executable file with .exe extension is rejected immediately."""
    upload = UploadFile(
        filename="payload.exe",
        file=BytesIO(b"MZ\x90\x00"),
        headers={"content-type": "application/pdf"},
    )

    with patch("app.routers.vendor_followup.get_supabase"), \
         patch("app.routers.vendor_followup.vf_svc.get_vendor_portal_data"):
        
        with pytest.raises(HTTPException) as exc_info:
            await upload_vendor_portal_file(token="tok-ext", file=upload)
        assert exc_info.value.status_code == 400
        assert "Only files with .pdf, .png, .jpg, or .jpeg extensions are allowed" in exc_info.value.detail


@pytest.mark.asyncio
async def test_vendor_upload_rejects_empty_file():
    """Empty 0-byte file is rejected."""
    upload = UploadFile(
        filename="empty.pdf",
        file=BytesIO(b""),
        headers={"content-type": "application/pdf"},
    )

    with patch("app.routers.vendor_followup.get_supabase"), \
         patch("app.routers.vendor_followup.vf_svc.get_vendor_portal_data"):
        
        with pytest.raises(HTTPException) as exc_info:
            await upload_vendor_portal_file(token="tok-empty", file=upload)
        assert exc_info.value.status_code == 400
        assert "Uploaded file is empty" in exc_info.value.detail


@pytest.mark.asyncio
async def test_vendor_upload_rejects_extension_content_mismatch():
    """File named .png containing PDF header is rejected."""
    pdf_bytes = b"%PDF-1.4\n1 0 obj..."
    upload = UploadFile(
        filename="invoice.png",
        file=BytesIO(pdf_bytes),
        headers={"content-type": "image/png"},
    )

    with patch("app.routers.vendor_followup.get_supabase"), \
         patch("app.routers.vendor_followup.vf_svc.get_vendor_portal_data"):
        
        with pytest.raises(HTTPException) as exc_info:
            await upload_vendor_portal_file(token="tok-mismatch", file=upload)
        assert exc_info.value.status_code == 400
        assert "Invalid file signature" in exc_info.value.detail


@pytest.mark.asyncio
async def test_vendor_upload_rejects_truncated_file():
    """Truncated 2-byte file with incomplete signature is rejected."""
    upload = UploadFile(
        filename="corrupted.pdf",
        file=BytesIO(b"%P"),
        headers={"content-type": "application/pdf"},
    )

    with patch("app.routers.vendor_followup.get_supabase"), \
         patch("app.routers.vendor_followup.vf_svc.get_vendor_portal_data"):
        
        with pytest.raises(HTTPException) as exc_info:
            await upload_vendor_portal_file(token="tok-trunc", file=upload)
        assert exc_info.value.status_code == 400
        assert "Invalid file signature" in exc_info.value.detail


@pytest.mark.asyncio
async def test_vendor_upload_rejects_oversized_file():
    """File exceeding 10MB is rejected."""
    upload = UploadFile(
        filename="huge.pdf",
        file=BytesIO(b"%PDF" + b"0" * (10 * 1024 * 1024 + 1)),
        headers={"content-type": "application/pdf"},
    )

    with patch("app.routers.vendor_followup.get_supabase"), \
         patch("app.routers.vendor_followup.vf_svc.get_vendor_portal_data"):
        
        with pytest.raises(HTTPException) as exc_info:
            await upload_vendor_portal_file(token="tok-huge", file=upload)
        assert exc_info.value.status_code == 400
        assert "exceeds 10 MB limit" in exc_info.value.detail
