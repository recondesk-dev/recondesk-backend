import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.auth import get_current_active_user
from app.models.upload import PresignedUrlRequest, PresignedUrlResponse, UploadResponse
from app.parsers.purchase_register_parser import parse_purchase_register
from app.services.r2_service import (
    create_presigned_upload_url,
    generate_file_key,
    upload_file_to_r2,
)
from app.utils.storage import upload_file_raw

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_PURCHASE_REGISTER_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_CONTENT_TYPES = {
    "text/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}
ALLOWED_PURCHASE_REGISTER_EXTENSIONS = {".xlsx", ".xls", ".csv"}


def _sanitize_filename(filename: str) -> str:
    """Strip path separators and special characters from a filename."""
    name = re.sub(r"[/\\]", "", filename)
    name = re.sub(r"[^\w\s\-.]", "", name)
    return name.strip() or "upload"


@router.post("/file", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_active_user),
):
    """Direct file upload (server-side). Max 50 MB."""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {file.content_type}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds 50 MB limit",
        )

    file_key = generate_file_key(file.filename or "upload", str(current_user["id"]))
    public_url = upload_file_to_r2(content, file_key, file.content_type or "application/octet-stream")

    return UploadResponse(
        file_key=file_key,
        file_name=file.filename or "upload",
        file_size=len(content),
        content_type=file.content_type or "application/octet-stream",
        public_url=public_url,
        uploaded_at=datetime.now(timezone.utc),
    )


@router.post("/presign", response_model=PresignedUrlResponse)
async def get_presigned_url(
    payload: PresignedUrlRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Generate a presigned URL for direct browser-to-R2 uploads."""
    if payload.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {payload.content_type}",
        )
    file_key = generate_file_key(payload.file_name, str(current_user["id"]))
    upload_url = create_presigned_upload_url(file_key, payload.content_type)
    return PresignedUrlResponse(upload_url=upload_url, file_key=file_key)


@router.post("/purchase-register")
async def upload_purchase_register(
    file: UploadFile = File(...),
    client_id: str = Form(...),
    run_id: str = Form(...),
):
    """Parse a purchase-register file and return structured invoice records.

    Accepts multipart/form-data with:
    - ``file``      — .xlsx / .xls / .csv upload
    - ``client_id`` — tenant identifier (used for R2 key)
    - ``run_id``    — reconciliation run identifier (used for R2 key)

    The raw file is stored in R2 at
    ``uploads/{client_id}/{run_id}/purchase_register{ext}``
    after a successful parse attempt.
    """
    safe_name = _sanitize_filename(file.filename or "upload")
    ext = Path(safe_name).suffix.lower()

    if ext not in ALLOWED_PURCHASE_REGISTER_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file type '{ext}'. "
                "Only .xlsx, .xls, and .csv files are accepted."
            ),
        )

    content = await file.read()

    if len(content) > MAX_PURCHASE_REGISTER_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"File size {len(content):,} bytes exceeds the 10 MB limit "
                f"({MAX_PURCHASE_REGISTER_SIZE:,} bytes)."
            ),
        )

    parse_result = parse_purchase_register(content, safe_name)

    r2_key = f"uploads/{client_id}/{run_id}/purchase_register{ext}"
    try:
        await upload_file_raw(content, r2_key)
    except Exception as exc:
        logger.warning("R2 upload failed for key '%s': %s", r2_key, exc)

    return parse_result
