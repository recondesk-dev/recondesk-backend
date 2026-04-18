"""
Import pipeline API — GSTR-2B and purchase register uploads, status polling.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import math

import pandas as pd
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel

from app.auth import get_current_active_user
from app.config import settings
from app.database import get_supabase
from app.utils.storage import upload_file_raw

router = APIRouter()
_logger = logging.getLogger(__name__)


def _enqueue_import_task(run_id: str, file_type: str, r2_key: str) -> None:
    """Queue the import job via Celery, or run it in-process (daemon thread) when configured."""
    if settings.IMPORT_USE_THREAD_WORKER:
        from app.worker.tasks import run_import_job_in_api_thread

        def _run() -> None:
            try:
                run_import_job_in_api_thread(run_id, file_type, r2_key)
            except Exception:
                _logger.exception(
                    "Import job crashed (thread worker run_id=%s type=%s)",
                    run_id,
                    file_type,
                )

        threading.Thread(target=_run, daemon=True).start()
        return

    try:
        from app.worker.celery_app import celery_app
    except ImportError as e:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Import worker is not available (Celery not installed or misconfigured).",
        ) from e
    try:
        celery_app.send_task(
            "worker.run_import_job",
            args=[run_id, file_type, r2_key],
        )
    except Exception as e:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Could not queue import job (broker unavailable). "
                "Ensure Redis is running and REDIS_URL is set in the API environment."
            ),
        ) from e

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
PR_REQUIRED = frozenset(
    {
        "supplier_gstin",
        "invoice_number",
        "invoice_date",
        "taxable_value",
        "igst",
        "cgst",
        "sgst",
    }
)

_RL_LOCK = threading.Lock()
_RL_BUCKETS: dict[str, list[float]] = {}


def _rate_limit_10_per_minute(client_gstin_id: str) -> None:
    """Max 10 upload requests per minute per client_gstin_id (Redis if available)."""
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        try:
            import redis

            r = redis.from_url(redis_url, decode_responses=True)
            key = f"import:upload:{client_gstin_id}"
            n = r.incr(key)
            if n == 1:
                r.expire(key, 60)
            if n > 10:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Maximum 10 import uploads per minute for this client.",
                )
            return
        except HTTPException:
            raise
        except Exception:
            pass
    now = time.monotonic()
    window = 60.0
    with _RL_LOCK:
        bucket = _RL_BUCKETS.setdefault(client_gstin_id, [])
        cutoff = now - window
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)
        if len(bucket) >= 10:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Maximum 10 import uploads per minute for this client.",
            )
        bucket.append(now)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_active_run_lock(
    client_gstin_id: str,
    period: str,
    override: bool = False,
) -> None:
    client = get_supabase()
    resp = (
        client.table("reconciliation_run")
        .select("id,status")
        .eq("client_gstin_id", client_gstin_id)
        .eq("period", period)
        .execute()
    )
    for row in resp.data or []:
        st = row.get("status") or ""
        if st in ("queued", "importing", "matching"):
            if override:
                continue
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=(
                    f"An import is already active for this period (run status '{st}'). "
                    "Re-uploading the same file is idempotent and does not need override. "
                    "To upload a different file while a run is still queued, pass ?override=true."
                ),
            )
        if st == "partial_success" and not override:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=(
                    "A previous import finished with partial success for this period. "
                    "Pass ?override=true after review."
                ),
            )


def _validate_gstr2b_schema_bytes(raw: bytes) -> dict:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON: {e.msg} at line {e.lineno}",
        ) from e
    if not isinstance(payload, dict) or "data" not in payload:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="GSTR-2B JSON must contain a top-level 'data' object.",
        )
    d = payload["data"]
    if not isinstance(d, dict):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="'data' must be an object.",
        )
    section_keys = ("b2b", "b2ba", "cdnr", "cdnra")

    def _sections_non_empty(obj: Any) -> bool:
        if not isinstance(obj, dict):
            return False
        return any(obj.get(k) for k in section_keys)

    has_sections = _sections_non_empty(d)
    docdata = d.get("docdata")
    if isinstance(docdata, dict):
        has_sections = has_sections or _sections_non_empty(docdata)

    p_dd = d.get("docDetails")
    p_it = d.get("itms")
    portal_keys = "docDetails" in d and "itms" in d
    portal_nonempty = False
    if portal_keys:
        dd_ok = isinstance(p_dd, dict) and len(p_dd) > 0
        if isinstance(p_it, list):
            it_ok = len(p_it) > 0
        elif isinstance(p_it, dict):
            it_ok = len(p_it) > 0
        else:
            it_ok = bool(p_it)
        portal_nonempty = dd_ok or it_ok

    if not portal_nonempty and not has_sections:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=(
                "GSTR-2B JSON must include non-empty data.docDetails or data.itms, "
                "or at least one populated section among b2b, b2ba, cdnr, cdnra "
                "(including under data.docdata)."
            ),
        )
    return payload


def _validate_pr_headers(content: bytes, filename: str) -> None:
    ext = Path(filename).suffix.lower()
    try:
        if ext == ".csv":
            df = pd.read_csv(io.BytesIO(content), header=0, nrows=0)
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(io.BytesIO(content), header=0, nrows=0)
        else:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Purchase register must be .csv, .xlsx, or .xls.",
            )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read purchase register headers: {e}",
        ) from e

    cols = {str(c).strip().lower() for c in df.columns}
    missing: list[str] = []
    for req in PR_REQUIRED:
        if req == "supplier_gstin":
            if "supplier_gstin" not in cols and "gstin" not in cols:
                missing.append("supplier_gstin")
        elif req not in cols:
            missing.append(req)
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required column(s): {', '.join(sorted(missing))}.",
        )


def _client_gstin_from_user(user: dict) -> str:
    uid = user.get("id")
    if not uid:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="User profile has no client_gstin_id.",
        )
    client = get_supabase()
    try:
        resp = (
            client.table("client_gstins")
            .select("id")
            .eq("assigned_to", str(uid))
            .limit(1)
            .execute()
        )
    except Exception as e:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Could not load client GSTIN assignment from database.",
        ) from e
    rows = resp.data or []
    if not rows:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="User profile has no client_gstin_id.",
        )
    return str(rows[0]["id"])


@router.post("/gstr2b")
async def import_gstr2b(
    file: UploadFile = File(...),
    client_gstin_id: str = Form(...),
    period: str = Form(...),
    override: bool = Query(False),
    current_user: dict = Depends(get_current_active_user),
):
    p = period.strip()
    if len(p) != 7 or p[4] != "-":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="period must be in YYYY-MM format.",
        )

    uid_gstin = _client_gstin_from_user(current_user)
    if client_gstin_id.strip() != uid_gstin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="client_gstin_id does not match authenticated profile.",
        )

    _rate_limit_10_per_minute(uid_gstin)

    if not (file.filename or "").lower().endswith(".json"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="GSTR-2B upload must be a .json file.",
        )

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="File exceeds 50 MB limit.",
        )

    file_hash = _sha256_hex(raw)

    client = get_supabase()
    dup = (
        client.table("reconciliation_run")
        .select("id,status,r2_key")
        .eq("client_gstin_id", uid_gstin)
        .eq("period", p)
        .eq("file_type", "gstr2b")
        .eq("file_hash", file_hash)
        .limit(1)
        .execute()
    )
    if dup.data:
        r = dup.data[0]
        rid = str(r["id"])
        st = r.get("status") or ""
        # Same file hash as a failed run: retry (unique constraint blocks a second insert).
        if st == "failed" and r.get("r2_key"):
            (
                client.table("reconciliation_run")
                .update(
                    {
                        "status": "queued",
                        "retry_count": 0,
                        "status_message": None,
                    }
                )
                .eq("id", rid)
                .execute()
            )
            _enqueue_import_task(rid, "gstr2b", str(r["r2_key"]))
            return {"run_id": rid, "status": "queued"}
        return {"run_id": rid, "status": st or "queued"}

    # New file for this period: block only after idempotent same-hash handling above.
    check_active_run_lock(uid_gstin, p, override=override)

    _validate_gstr2b_schema_bytes(raw)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    r2_key = f"uploads/{uid_gstin}/{p}/gstr2b_{ts}.json"
    try:
        await upload_file_raw(raw, r2_key)
    except (ClientError, OSError) as e:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Could not store file in object storage (R2). Check credentials and bucket.",
        ) from e

    try:
        insert_resp = (
            client.table("reconciliation_run")
            .insert(
                {
                    "client_gstin_id": uid_gstin,
                    "period": p,
                    "file_type": "gstr2b",
                    "r2_key": r2_key,
                    "status": "queued",
                    "file_hash": file_hash,
                    "retry_count": 0,
                }
            )
            .execute()
        )
    except Exception as e:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Could not create reconciliation run in database.",
        ) from e
    if not insert_resp.data:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create reconciliation run.",
        )
    run_row = insert_resp.data[0]
    run_id = str(run_row["id"])

    _enqueue_import_task(run_id, "gstr2b", r2_key)

    return {"run_id": run_id, "status": "queued"}


@router.post("/purchase-register")
async def import_purchase_register(
    file: UploadFile = File(...),
    run_id: str = Form(...),
    override: bool = Query(False),
    current_user: dict = Depends(get_current_active_user),
):
    uid_gstin = _client_gstin_from_user(current_user)
    _rate_limit_10_per_minute(uid_gstin)

    try:
        rid = str(UUID(run_id.strip()))
    except ValueError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="run_id must be a valid UUID.",
        ) from e

    client = get_supabase()
    run_resp = (
        client.table("reconciliation_run")
        .select("*")
        .eq("id", str(rid))
        .limit(1)
        .execute()
    )
    if not run_resp.data:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Unknown reconciliation run.")
    run_row = run_resp.data[0]
    if str(run_row.get("client_gstin_id")) != uid_gstin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Run does not belong to the current client.",
        )
    if str(run_row.get("file_type")) != "gstr2b":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Purchase register must be linked to a GSTR-2B reconciliation run.",
        )

    period = str(run_row["period"])
    check_active_run_lock(uid_gstin, period, override=override)
    safe_name = Path(file.filename or "upload").name
    ext = Path(safe_name).suffix.lower()
    if ext not in (".xlsx", ".xls", ".csv"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="File must be .xlsx, .xls, or .csv.",
        )

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="File exceeds 50 MB limit.",
        )

    pr_hash = _sha256_hex(raw)

    dup = (
        client.table("reconciliation_run")
        .select("id,status,sanity_report")
        .eq("client_gstin_id", uid_gstin)
        .eq("period", period)
        .eq("file_type", "purchase_register")
        .eq("file_hash", pr_hash)
        .limit(1)
        .execute()
    )
    if dup.data:
        row = dup.data[0]
        parent = (row.get("sanity_report") or {}).get("parent_run_id")
        return {
            "run_id": parent or str(row["id"]),
            "status": row.get("status", "queued"),
        }

    _validate_pr_headers(raw, safe_name)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    r2_key = f"uploads/{uid_gstin}/{period}/pr_{ts}{ext}"
    try:
        await upload_file_raw(raw, r2_key)
    except (ClientError, OSError) as e:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Could not store file in object storage (R2). Check credentials and bucket.",
        ) from e

    parent_id = str(rid)
    stub = (
        client.table("reconciliation_run")
        .insert(
            {
                "client_gstin_id": uid_gstin,
                "period": period,
                "file_type": "purchase_register",
                "file_hash": pr_hash,
                "r2_key": r2_key,
                "status": "queued",
                "retry_count": 0,
                "sanity_report": {"parent_run_id": parent_id},
            }
        )
        .execute()
    )
    if not stub.data:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not register purchase register upload.",
        )

    _enqueue_import_task(parent_id, "purchase_register", r2_key)

    return {"run_id": parent_id, "status": "queued"}


class ImportStatusResponse(BaseModel):
    run_id: str
    status: str
    progress_percent: float
    status_message: Optional[str] = None
    gstr_records_imported: int = 0
    pr_records_imported: int = 0
    failed_records: int = 0
    sanity_checks: list[Any] = []
    recent_logs: list[dict[str, Any]]


@router.get("/status/{run_id}", response_model=ImportStatusResponse)
async def import_status(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    uid_gstin = _client_gstin_from_user(current_user)
    client = get_supabase()
    try:
        UUID(run_id)
    except ValueError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="run_id must be a valid UUID.",
        ) from e

    try:
        run_resp = (
            client.table("reconciliation_run")
            .select("*")
            .eq("id", run_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Could not load reconciliation run from database.",
        ) from e
    if not run_resp.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Run not found.")
    row = run_resp.data[0]
    if str(row.get("client_gstin_id")) != uid_gstin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Access denied.")

    recent: list[dict[str, Any]] = []
    try:
        logs = (
            client.table("job_logs")
            .select("step_name,status,error_details,created_at")
            .eq("run_id", run_id)
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )
        for lg in logs.data or []:
            recent.append(
                {
                    "step_name": lg.get("step_name"),
                    "status": lg.get("status"),
                    "error_details": lg.get("error_details"),
                    "created_at": lg.get("created_at"),
                }
            )
    except Exception:
        pass

    def _num(v: Any, default: float = 0.0) -> float:
        try:
            x = float(v)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(x):
            return default
        return x

    def _int(v: Any, default: int = 0) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    sr = row.get("sanity_report")
    sanity_checks: list[Any] = []
    if isinstance(sr, dict) and "issues" in sr:
        sanity_checks = sr["issues"] if isinstance(sr["issues"], list) else [sr["issues"]]
    elif isinstance(sr, dict) and sr:
        sanity_checks = [sr]

    try:
        sanity_checks = json.loads(json.dumps(sanity_checks, default=str))
    except (TypeError, ValueError):
        sanity_checks = []

    return ImportStatusResponse(
        run_id=str(row["id"]),
        status=str(row.get("status", "queued")),
        progress_percent=_num(row.get("progress_percent"), 0.0),
        status_message=row.get("status_message"),
        gstr_records_imported=_int(row.get("gstr_records_imported"), 0),
        pr_records_imported=_int(row.get("pr_records_imported"), 0),
        failed_records=_int(row.get("failed_records"), 0),
        sanity_checks=sanity_checks,
        recent_logs=recent,
    )
