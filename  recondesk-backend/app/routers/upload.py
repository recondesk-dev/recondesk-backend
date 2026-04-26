import logging
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from app.auth import get_current_active_user
from app.config import get_settings
from app.models.upload import PresignedUrlRequest, PresignedUrlResponse, UploadResponse
from app.parsers.purchase_register_parser import parse_purchase_register
from app.services.r2_service import (
    create_presigned_upload_url,
    generate_file_key,
    upload_file_to_r2,
)
from app.utils.audit import log_action
from app.utils.storage import upload_file_raw
from app.utils.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_CONTENT_TYPES = {
    "text/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}
ALLOWED_PURCHASE_REGISTER_EXTENSIONS = {".xlsx", ".xls", ".csv"}


def _sanitize_filename(filename: str) -> str:
    name = re.sub(r"[/\\]", "", filename)
    name = re.sub(r"[^\w\s\-.]", "", name)
    return name.strip() or "upload"


def _max_bytes() -> int:
    return get_settings().MAX_FILE_SIZE_MB * 1024 * 1024


def _validate_upload_bytes(content: bytes, ext: str) -> None:
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="empty file",
        )
    if ext == ".json":
        if content[0:1] not in (b"{", b"["):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="JSON file must start with { or [",
            )
    elif ext == ".xlsx":
        if len(content) < 2 or content[0:2] != b"PK":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Excel file",
            )
    if len(content) > _max_bytes():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File exceeds {get_settings().MAX_FILE_SIZE_MB} MB limit",
        )


@router.post("/file", response_model=UploadResponse)
@limiter.limit("20/hour")
async def upload_file(
    request: Request,  # noqa: ARG001
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_active_user),
):
    """Direct file upload (server-side)."""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type",
        )
    ext = (Path(file.filename or "").suffix or "").lower()
    content = await file.read()
    _validate_upload_bytes(content, ext)
    try:
        file_key = generate_file_key(file.filename or "upload", str(current_user["id"]))
        public_url = upload_file_to_r2(
            content, file_key, file.content_type or "application/octet-stream"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("upload failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload could not be processed",
        ) from exc
    await log_action(
        str(current_user.get("id")),
        "FILE_UPLOAD",
        "file",
        file_key,
        {"name": file.filename},
        ip_address=None,
    )
    return UploadResponse(
        file_key=file_key,
        file_name=file.filename or "upload",
        file_size=len(content),
        content_type=file.content_type or "application/octet-stream",
        public_url=public_url,
        uploaded_at=datetime.now(timezone.utc),
    )


@router.post("/presign", response_model=PresignedUrlResponse)
@limiter.limit("20/hour")
async def get_presigned_url(
    request: Request,  # noqa: ARG001
    payload: PresignedUrlRequest,
    current_user: dict = Depends(get_current_active_user),
):
    if payload.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type",
        )
    file_key = generate_file_key(payload.file_name, str(current_user["id"]))
    upload_url = create_presigned_upload_url(file_key, payload.content_type)
    return PresignedUrlResponse(upload_url=upload_url, file_key=file_key)


@router.post("/purchase-register")
@limiter.limit("20/hour")
async def upload_purchase_register(
    request: Request,
    file: UploadFile = File(...),
    client_id: str = Form(...),
    run_id: str = Form(...),
    current_user: dict = Depends(get_current_active_user),
):
    """Parse a purchase-register file; requires authentication and tenant access."""
    from app.database import get_supabase
    from uuid import UUID

    sb = get_supabase()
    uid = str(current_user.get("id", ""))
    try:
        UUID(run_id.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid run_id",
        ) from exc
    res = (
        sb.table("reconciliation_run")
        .select("id, client_gstin_id")
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    run = res.data[0]
    if str(run.get("client_gstin_id", "")).strip() != str(client_id).strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    safe_name = _sanitize_filename(file.filename or "upload")
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_PURCHASE_REGISTER_EXTENSIONS:
        await log_action(
            uid,
            "UPLOAD_REJECTED",
            "purchase_register",
            run_id,
            {"reason": "bad_ext"},
            ip_address=(request.client.host if request.client else None),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .xlsx, .xls, and .csv files are accepted.",
        )
    content = await file.read()
    _validate_upload_bytes(content, ext)
    tmpdir = tempfile.mkdtemp(prefix=f"rd_u_{uid}_")
    tmp_path = Path(tmpdir) / f"pr{ext}"
    try:
        tmp_path.write_bytes(content)
        parse_result = parse_purchase_register(content, safe_name)
    except Exception as exc:  # noqa: BLE001
        await log_action(
            uid,
            "UPLOAD_REJECTED",
            "purchase_register",
            run_id,
            {"reason": "parse_error"},
            ip_address=(request.client.host if request.client else None),
        )
        logger.warning("parse failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The file could not be parsed",
        ) from exc
    r2_key = f"uploads/{client_id}/{run_id}/purchase_register{ext}"
    try:
        await upload_file_raw(content, r2_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("R2 upload failed for key '%s': %s", r2_key, type(exc).__name__)
    await log_action(
        uid,
        "FILE_UPLOAD",
        "purchase_register",
        run_id,
        {},
        ip_address=(request.client.host if request.client else None),
    )
    return parse_result
