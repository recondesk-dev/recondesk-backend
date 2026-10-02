"""Import API: GSTR-2B JSON and purchase register uploads, run status."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from supabase import Client, create_client

from app.auth import get_current_active_user
from app.config import get_settings
from app.services.normalizer import NormalizationError, normalize_gstin
from app.utils.audit import client_display_label, log_action, log_audit
from app.worker.celery_app import celery_app

router = APIRouter()
_log = logging.getLogger(__name__)

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ALLOWED_PR_EXT = {".xlsx", ".xls", ".csv", ".zip"}


@lru_cache(maxsize=1)
def _supabase() -> Client:
    s = get_settings()
    return create_client(s.SUPABASE_URL, s.SUPABASE_SERVICE_ROLE_KEY)


def _s3():
    from app.services.storage_service import get_storage_service
    return get_storage_service().get_s3_client()


def _dispatch_import_job(run_id: str, file_type: str, r2_key: str) -> bool:
    """Run import: queue to Celery if IMPORT_USE_CELERY, else in-process ``apply``.

    If enqueue fails (e.g. broker down), falls back to ``apply`` so work still runs.
    Returns True if executed in-process, False if only queued for a worker.
    """
    from app.worker.tasks import run_import_job

    if get_settings().import_use_celery:
        try:
            celery_app.send_task(
                "worker.run_import_job",
                args=[run_id, file_type, r2_key],
            )
            return False
        except Exception as exc:
            _log.warning(
                "Celery enqueue failed; running import synchronously: %s",
                exc,
                exc_info=True,
            )
            run_import_job.apply(args=[run_id, file_type, r2_key])
            return True
    run_import_job.apply(args=[run_id, file_type, r2_key])
    return True


def _assigned_client_gstin_id(sb: Client, current_user: dict) -> str:
    """Resolve the user's client GSTIN record id from ``client_gstins.assigned_to``."""
    user_id = str(current_user.get("id", "")).strip()
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing user id",
        )
    res = (
        sb.table("client_gstins")
        .select("id")
        .eq("firm_owner_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no client_gstin assigned to this user",
        )
    return str(res.data[0]["id"]).strip()


def _gstr2b_buyer_gstin_from_raw(
    raw: bytes, filename: str | None = None
) -> str | None:
    """Best-effort buyer GSTIN from GSTR-2B JSON or alt Excel export."""
    from app.parsers.gstr2b_excel import (
        excel_to_alt_2b_dict,
        is_gstr2b_excel_bytes,
        is_gstr2b_excel_filename,
    )

    name = filename or ""
    if is_gstr2b_excel_filename(name) or (
        not name.lower().endswith(".json") and is_gstr2b_excel_bytes(raw)
    ):
        try:
            alt = excel_to_alt_2b_dict(raw, name or "gstr2b.xlsx")
        except ValueError:
            return None
        gst = alt.get("gstin")
        if gst is None:
            return None
        s = str(gst).strip()
        return s or None

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    root = data.get("data")
    gst: Any = None
    if isinstance(root, dict):
        gst = root.get("gstin")
        if not gst:
            gst = data.get("gstnId") or data.get("gstin")
    else:
        gst = data.get("gstnId") or data.get("gstin")
    if gst is None:
        from app.parsers.gstr2b_parser import (
            _alt_extract_buyer_gstin,
            is_alt_gstr2b_schema,
        )

        if is_alt_gstr2b_schema(data):
            alt = _alt_extract_buyer_gstin(data)
            return alt or None
        return None
    s = str(gst).strip()
    return s or None


def _gstin_norm_for_compare(raw: str) -> str:
    try:
        return normalize_gstin(raw)
    except NormalizationError:
        return re.sub(r"\s+", "", raw).upper()


@router.post("/gstr2b")
async def import_gstr2b(
    request: Request,
    file: UploadFile = File(...),
    client_gstin_id: str = Form(...),
    period: str = Form(...),
    current_user: dict = Depends(get_current_active_user),
):
    if not file.filename or not file.filename.lower().endswith(
        (".json", ".xlsx", ".xls")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file must have .json, .xlsx, or .xls extension",
        )
    if not PERIOD_RE.match(period.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period must be YYYY-MM",
        )
    period_norm = period.strip()

    sb = _supabase()
    cg = str(client_gstin_id).strip()
    role = str(current_user.get("role") or "staff").strip().lower()
    if role != "admin":
        assigned_cg = _assigned_client_gstin_id(sb, current_user)
        if cg != assigned_cg:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="client_gstin_id does not match your assigned client_gstin",
            )

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file exceeds 50MB limit",
        )
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="empty file",
        )

    file_hash = hashlib.sha256(raw).hexdigest()
    fname_lower = (file.filename or "").lower()
    is_excel = fname_lower.endswith((".xlsx", ".xls"))
    if is_excel:
        from app.parsers.gstr2b_excel import is_gstr2b_excel_bytes

        if not is_gstr2b_excel_bytes(raw):
            await log_action(
                str(current_user.get("id")),
                "UPLOAD_REJECTED",
                "gstr2b",
                cg,
                {"reason": "not_excel_bytes"},
                ip_address=(request.client.host if request.client else None),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Excel file is not a valid .xls/.xlsx workbook",
            )
    elif raw[0:1] not in (b"{", b"["):
        await log_action(
            str(current_user.get("id")),
            "UPLOAD_REJECTED",
            "gstr2b",
            cg,
            {"reason": "not_json_start"},
            ip_address=(request.client.host if request.client else None),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="JSON file must start with { or [",
        )
    if len(raw) > get_settings().MAX_FILE_SIZE_MB * 1024 * 1024:
        await log_action(
            str(current_user.get("id")),
            "UPLOAD_REJECTED",
            "gstr2b",
            cg,
            {"reason": "over_max_bytes"},
            ip_address=(request.client.host if request.client else None),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"file exceeds {get_settings().MAX_FILE_SIZE_MB}MB limit",
        )

    try:
        cg_res = (
            sb.table("client_gstins")
            .select("gstin")
            .eq("id", cg)
            .limit(1)
            .execute()
        )
        client_gstin_raw = ""
        if cg_res.data and cg_res.data[0].get("gstin") is not None:
            client_gstin_raw = str(cg_res.data[0]["gstin"]).strip()
        file_gstin_raw = _gstr2b_buyer_gstin_from_raw(raw, filename=file.filename) or ""
        if client_gstin_raw and file_gstin_raw:
            n_file = _gstin_norm_for_compare(file_gstin_raw)
            n_client = _gstin_norm_for_compare(client_gstin_raw)
            if n_file != n_client:
                return JSONResponse(
                    status_code=200,
                    content={
                        "checks": [
                            {
                                "name": "GSTIN match",
                                "status": "ERROR",
                                "message": (
                                    f"GSTIN in file ({file_gstin_raw}) does not match "
                                    f"client GSTIN ({client_gstin_raw}). Upload the correct file."
                                ),
                            }
                        ]
                    },
                )
    except Exception as exc:
        _log.warning(
            "GSTIN sanity preflight failed (%s); continuing with import",
            exc,
            exc_info=True,
        )

    start_uid = str(current_user.get("id", "")).strip()
    dup = (
        sb.table("reconciliation_run")
        .select("id, status, created_at")
        .eq("client_gstin_id", cg)
        .eq("period", period_norm)
        .eq("file_hash", file_hash)
        .eq("file_type", "gstr2b")
        .limit(1)
        .execute()
    )
    if dup.data:
        row = dup.data[0]
        prev_status = (row.get("status") or "").strip().lower()
        if prev_status in (
            "pending",
            "processing",
            "uploading",
            "queued",
        ) or prev_status in (
            "gstr_import_complete",
            "purchase_import_complete",
            "ready",
            "matching",
        ):
            return {"run_id": row["id"], "status": row.get("status", "queued")}
        # Same file already imported or in flight — short-circuit.
        if prev_status not in ("failed", "uploading"):
            return {"run_id": row["id"], "status": row.get("status", "queued")}
        # Previous init failed or stuck in uploading — retry full init on same run.
        run_id = row["id"]
        ts = int(datetime.now(timezone.utc).timestamp())
        upload_ext = "xlsx" if fname_lower.endswith(".xlsx") else (
            "xls" if fname_lower.endswith(".xls") else "json"
        )
        r2_key = f"uploads/{cg}/{period_norm}/gstr2b_{ts}.{upload_ext}"
        now = datetime.now(timezone.utc).isoformat()
        sb.table("reconciliation_run").update(
            {
                "r2_key": r2_key,
                "status": "uploading",
                "progress_percent": 0,
                "status_message": None,
                "sanity_report": None,
                "updated_at": now,
            }
        ).eq("id", run_id).execute()
    else:
        run_id = str(uuid4())
        ts = int(datetime.now(timezone.utc).timestamp())
        upload_ext = "xlsx" if fname_lower.endswith(".xlsx") else (
            "xls" if fname_lower.endswith(".xls") else "json"
        )
        r2_key = f"uploads/{cg}/{period_norm}/gstr2b_{ts}.{upload_ext}"
        now = datetime.now(timezone.utc).isoformat()
        insert_row = {
            "id": run_id,
            "client_gstin_id": cg,
            "period": period_norm,
            "file_type": "gstr2b",
            "file_hash": file_hash,
            "r2_key": r2_key,
            "status": "uploading",
            "progress_percent": 0,
            "created_at": now,
            "updated_at": now,
        }
        sb.table("reconciliation_run").insert(insert_row).execute()

    ran_import_sync = False
    try:
        content_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if upload_ext == "xlsx"
            else "application/vnd.ms-excel"
            if upload_ext == "xls"
            else "application/json"
        )
        from app.services.storage_service import get_storage_service
        get_storage_service().upload_bytes(
            body=raw,
            key=r2_key,
            content_type=content_type,
        )
        queued_at = datetime.now(timezone.utc).isoformat()
        sb.table("reconciliation_run").update(
            {"status": "queued", "updated_at": queued_at}
        ).eq("id", run_id).execute()
        ran_import_sync = _dispatch_import_job(run_id, "gstr2b", r2_key)
    except Exception as e:
        _log.exception("=== IMPORT INITIALIZATION ERROR ===")

        try:
            sb.table("reconciliation_run").update(
                {
                    "status": "failed",
                    "status_message": str(e),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            ).eq("id", run_id).execute()
        except Exception as db_error:
            _log.error("FAILED TO UPDATE DB STATUS: %s", db_error, exc_info=True)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again.",
        ) from e

    if ran_import_sync:
        st_res = (
            sb.table("reconciliation_run")
            .select("status")
            .eq("id", run_id)
            .limit(1)
            .execute()
        )
        row_status = st_res.data[0]["status"] if st_res.data else "queued"
        await log_audit(
            sb,
            current_user,
            "FILE_UPLOADED",
            "file",
            run_id,
            file.filename or "gstr2b.json",
            {"file_type": "gstr2b", "period": period_norm},
            ip_address=(request.client.host if request.client else None),
        )
        return {"run_id": run_id, "status": row_status}

    await log_audit(
        sb,
        current_user,
        "FILE_UPLOADED",
        "file",
        run_id,
        file.filename or "gstr2b.json",
        {"file_type": "gstr2b", "period": period_norm},
        ip_address=(request.client.host if request.client else None),
    )
    return {"run_id": run_id, "status": "queued"}


@router.post("/purchase-register")
async def import_purchase_register(
    file: UploadFile = File(...),
    run_id: str = Form(...),
    current_user: dict = Depends(get_current_active_user),
):
    sb = _supabase()
    assigned_cg = _assigned_client_gstin_id(sb, current_user)

    try:
        UUID(run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid run_id",
        ) from exc

    res = (
        sb.table("reconciliation_run")
        .select("id, client_gstin_id, period, status")
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="run not found",
        )
    run = res.data[0]
    if str(run.get("client_gstin_id", "")).strip() != assigned_cg:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="run does not belong to your client_gstin_id",
        )

    filename = file.filename or "upload.bin"
    ext = ""
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_PR_EXT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file must be .xlsx, .xls, .csv, or .zip",
        )

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file exceeds 50MB limit",
        )
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="empty file",
        )

    cg = str(run["client_gstin_id"]).strip()
    period_norm = str(run["period"]).strip()
    ts = int(datetime.now(timezone.utc).timestamp())
    r2_key = f"uploads/{cg}/{period_norm}/pr_{ts}{ext}"
    if ext == ".csv":
        content_type = "text/csv"
    elif ext == ".xls":
        content_type = "application/vnd.ms-excel"
    else:
        content_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    from app.services.storage_service import get_storage_service
    get_storage_service().upload_bytes(body=raw, key=r2_key, content_type=content_type)

    now = datetime.now(timezone.utc).isoformat()
    sb.table("reconciliation_run").update(
        {
            "r2_key": r2_key,
            "status": "queued",
            "progress_percent": 0,
            "updated_at": now,
        }
    ).eq("id", run_id).execute()

    ran_import_sync = _dispatch_import_job(run_id, "purchase_register", r2_key)

    if ran_import_sync:
        st_res = (
            sb.table("reconciliation_run")
            .select("status")
            .eq("id", run_id)
            .limit(1)
            .execute()
        )
        row_status = st_res.data[0]["status"] if st_res.data else "queued"
        await log_audit(
            sb,
            current_user,
            "FILE_UPLOADED",
            "file",
            run_id,
            file.filename or f"purchase_register{ext}",
            {"file_type": "purchase_register"},
        )
        return {"run_id": run_id, "status": row_status}

    await log_audit(
        sb,
        current_user,
        "FILE_UPLOADED",
        "file",
        run_id,
        file.filename or f"purchase_register{ext}",
        {"file_type": "purchase_register"},
    )
    return {"run_id": run_id, "status": "queued"}


@router.get("/status/{run_id}")
async def import_status(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    sb = _supabase()
    assigned_cg = _assigned_client_gstin_id(sb, current_user)

    try:
        UUID(run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid run_id",
        ) from exc

    res = (
        sb.table("reconciliation_run")
        .select(
            "id, client_gstin_id, status, progress_percent, status_message, "
            "gstr_records_imported, pr_records_imported, sanity_report"
        )
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="run not found",
        )
    row = res.data[0]
    if str(row.get("client_gstin_id", "")).strip() != assigned_cg:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="run does not belong to your client_gstin_id",
        )

    sanity = row.get("sanity_report")
    sanity_checks: Any = sanity if isinstance(sanity, list) else []

    return {
        "run_id": row["id"],
        "status": row.get("status"),
        "progress_percent": row.get("progress_percent"),
        "status_message": row.get("status_message"),
        "gstr_records_imported": row.get("gstr_records_imported"),
        "pr_records_imported": row.get("pr_records_imported"),
        "sanity_checks": sanity_checks,
    }
