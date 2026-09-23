import logging
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from app.auth import get_current_active_user
from app.config import get_r2_s3_endpoint_url, get_settings
from app.database import get_supabase
from app.models.upload import PresignedUrlRequest, PresignedUrlResponse, UploadResponse
from app.parsers.purchase_register_parser import parse_purchase_register
from app.services.r2_service import (
    create_presigned_upload_url,
    generate_file_key,
    upload_file_to_r2,
)
from app.utils.audit import log_action, log_audit
from app.utils.rate_limit import limiter
from app.utils.storage import upload_file_raw

logger = logging.getLogger(__name__)

router = APIRouter()
public_router = APIRouter()

ALLOWED_CONTENT_TYPES = {
    "text/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}
ALLOWED_PURCHASE_REGISTER_EXTENSIONS = {".xlsx", ".xls", ".csv"}

ALLOWED_CLIENT_CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
    "application/pdf",
    "application/zip",
    "application/x-zip-compressed",
}

ALLOWED_CLIENT_EXTENSIONS = {".xlsx", ".csv", ".pdf", ".zip"}

EXTENSION_CONTENT_TYPES: dict[str, set[str]] = {
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".csv": {"text/csv"},
    ".pdf": {"application/pdf"},
    ".zip": {"application/zip", "application/x-zip-compressed"},
}

PRESIGNED_URL_EXPIRY_SECONDS = 300


class ClientPresignedUrlRequest(BaseModel):
    token: str = Field(..., min_length=1)
    filename: str = Field(..., min_length=1)
    content_type: str = Field(..., min_length=1)


class ClientPresignedUrlResponse(BaseModel):
    upload_url: str
    public_url: str


class UploadRequestInfoResponse(BaseModel):
    id: str
    token: str
    title: str
    description: str | None = None
    expires_at: str | None = None
    is_expired: bool = False
    client_name: str | None = None
    client_gstin: str | None = None
    firm_name: str | None = None
    firm_city: str | None = None
    ca_name: str | None = None
    created_at: str | None = None


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


def _get_r2_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=get_r2_s3_endpoint_url(),
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def _parse_expires_at(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validate_client_upload(payload: ClientPresignedUrlRequest) -> tuple[str, str]:
    if payload.content_type not in ALLOWED_CLIENT_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File type not allowed",
        )

    safe_filename = _sanitize_filename(payload.filename)
    ext = Path(safe_filename).suffix.lower()
    if ext not in ALLOWED_CLIENT_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File type not allowed",
        )

    allowed_for_ext = EXTENSION_CONTENT_TYPES.get(ext, set())
    if payload.content_type not in allowed_for_ext:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File extension does not match content type",
        )

    return safe_filename, ext


def _get_upload_request_by_token(token: str) -> dict:
    supabase = get_supabase()
    result = (
        supabase.table("upload_requests")
        .select("id, client_id, created_by_user_id, title, description, expires_at, created_at")
        .eq("token", token)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload link not found",
        )
    return rows[0]


@public_router.get("/info/{token}", response_model=UploadRequestInfoResponse)
async def get_upload_request_info(token: str) -> UploadRequestInfoResponse:
    row = _get_upload_request_by_token(token.strip())
    expires_at_raw = row.get("expires_at")
    is_expired = False
    if expires_at_raw:
        try:
            is_expired = _parse_expires_at(str(expires_at_raw)) < datetime.now(timezone.utc)
        except Exception:
            is_expired = False

    client_name = None
    client_gstin = None
    firm_name = None
    firm_city = None
    ca_name = None

    supabase = get_supabase()
    client_id = row.get("client_id")
    if client_id:
        try:
            c_res = (
                supabase.table("client_gstins")
                .select("trade_name, legal_name, gstin")
                .eq("id", str(client_id))
                .limit(1)
                .execute()
            )
            c_rows = c_res.data or []
            if c_rows:
                client_name = c_rows[0].get("trade_name") or c_rows[0].get("legal_name")
                client_gstin = c_rows[0].get("gstin")
        except Exception as e:
            logger.warning("Could not fetch client details for upload token: %s", e)

    created_by = row.get("created_by_user_id")
    if created_by:
        try:
            u_res = (
                supabase.table("user_profiles")
                .select("firm_name, full_name, firm_city")
                .eq("id", str(created_by))
                .limit(1)
                .execute()
            )
            u_rows = u_res.data or []
            if u_rows:
                firm_name = u_rows[0].get("firm_name")
                ca_name = u_rows[0].get("full_name")
                firm_city = u_rows[0].get("firm_city")
        except Exception as e:
            logger.warning("Could not fetch firm details for upload token: %s", e)

    return UploadRequestInfoResponse(
        id=str(row["id"]),
        token=token.strip(),
        title=str(row.get("title") or "Document Upload Request"),
        description=row.get("description"),
        expires_at=str(expires_at_raw) if expires_at_raw else None,
        is_expired=is_expired,
        client_name=client_name,
        client_gstin=client_gstin,
        firm_name=firm_name or "Chartered Accountant & Tax Advisors",
        firm_city=firm_city,
        ca_name=ca_name,
        created_at=str(row.get("created_at")) if row.get("created_at") else None,
    )


@public_router.post("/presigned-url", response_model=ClientPresignedUrlResponse)
async def create_client_presigned_url(payload: ClientPresignedUrlRequest) -> ClientPresignedUrlResponse:
    upload_request = _get_upload_request_by_token(payload.token.strip())

    expires_at = upload_request.get("expires_at")
    if expires_at:
        if _parse_expires_at(str(expires_at)) < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Upload link has expired",
            )

    safe_filename, _ext = _validate_client_upload(payload)
    upload_request_id = str(upload_request["id"])
    object_key = f"uploads/{upload_request_id}/{uuid.uuid4()}_{safe_filename}"

    settings = get_settings()
    client = _get_r2_client()
    upload_url = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.R2_BUCKET_NAME,
            "Key": object_key,
            "ContentType": payload.content_type,
        },
        ExpiresIn=PRESIGNED_URL_EXPIRY_SECONDS,
    )

    public_base = (settings.R2_PUBLIC_URL or "").rstrip("/")
    public_url = f"{public_base}/{object_key}"

    return ClientPresignedUrlResponse(upload_url=upload_url, public_url=public_url)


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
    await log_audit(
        get_supabase(),
        current_user,
        "FILE_UPLOADED",
        "file",
        file_key,
        file.filename or "upload",
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
        parse_body = content
        parse_name = safe_name
        from app.services import client_import_mapping as cim

        saved = cim.get_mappings_or_none(sb, str(client_id).strip())
        if saved:
            try:
                headers = cim.extract_headers_from_file(content, safe_name)
            except Exception:  # noqa: BLE001
                headers = []
            if headers and cim.mapping_covers_headers(saved, headers):
                parse_body, parse_name = cim.reshape_file_with_mapping(
                    content, safe_name, saved
                )
            elif headers and not cim.columns_match_expected_schema(headers):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "message": "Column mapping required",
                        "headers": headers,
                        "saved_mapping": saved,
                    },
                )
        else:
            try:
                headers = cim.extract_headers_from_file(content, safe_name)
            except Exception:  # noqa: BLE001
                headers = []
            if headers and not cim.columns_match_expected_schema(headers):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "message": "Column mapping required",
                        "headers": headers,
                        "saved_mapping": None,
                    },
                )
        client_gstin_str = None
        try:
            cg_res = (
                sb.table("client_gstins")
                .select("gstin")
                .eq("id", str(client_id).strip())
                .limit(1)
                .execute()
            )
            if cg_res.data and cg_res.data[0].get("gstin"):
                client_gstin_str = str(cg_res.data[0]["gstin"]).strip()
        except Exception:
            client_gstin_str = None
        parse_result = parse_purchase_register(
            parse_body, parse_name, client_gstin=client_gstin_str
        )
    except HTTPException:
        raise
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
    await log_audit(
        sb,
        current_user,
        "FILE_UPLOADED",
        "file",
        run_id,
        safe_name,
        {"file_type": "purchase_register"},
        ip_address=(request.client.host if request.client else None),
    )
    return parse_result
