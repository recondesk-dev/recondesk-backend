import logging
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from supabase import Client

from app.auth import get_current_active_user
from app.database import get_supabase, supabase_client
from app.routers.import_router import _assigned_client_gstin_id
from app.worker.reconciliation_task import execute_reconciliation
from app.models.reconciliation import (
    ReconciliationJobCreate,
    ReconciliationJobResponse,
    ReconciliationRow,
    ReconciliationStatus,
)
from app.parsers.file_router import parse_file
from app.services.r2_service import create_presigned_download_url
from app.services.reconciliation_service import reconcile
from app.services.email_service import send_reconciliation_complete_email

router = APIRouter()
start_router = APIRouter()
_log = logging.getLogger(__name__)


class ReconciliationStartRequest(BaseModel):
    run_id: str = Field(..., min_length=1)


class ReconciliationStartResponse(BaseModel):
    run_id: str
    status: str


class ReconciliationStatusResponse(BaseModel):
    run_id: str
    status: str
    progress_percent: Optional[float] = None
    status_message: Optional[str] = None
    processing_started_at: Optional[str] = None
    completed_at: Optional[str] = None
    summary: Optional[dict[str, Any]] = None
    matching_version: Optional[str] = None
    rules_version: Optional[str] = None
    decision_version: Optional[str] = None


async def _fetch_file_content(file_key: str) -> bytes:
    """Download file bytes from R2 via a presigned URL."""
    import httpx
    url = create_presigned_download_url(file_key)
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


@router.post("/jobs", response_model=ReconciliationJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    payload: ReconciliationJobCreate,
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),
):
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    job_record = {
        "id": job_id,
        "user_id": str(current_user["id"]),
        "name": payload.name,
        "status": ReconciliationStatus.PROCESSING,
        "source_file_key": payload.source_file_key,
        "target_file_key": payload.target_file_key,
        "match_columns": payload.match_columns,
        "tolerance": payload.tolerance,
        "created_at": now,
    }
    db.table("reconciliation_jobs").insert(job_record).execute()

    try:
        source_bytes = await _fetch_file_content(payload.source_file_key)
        target_bytes = await _fetch_file_content(payload.target_file_key)

        source_df = parse_file(source_bytes, payload.source_file_key.split("/")[-1])
        target_df = parse_file(target_bytes, payload.target_file_key.split("/")[-1])

        rows, summary = reconcile(source_df, target_df, payload.match_columns, payload.tolerance or 0.0)

        # Persist row results
        row_records = [
            {
                "id": str(uuid.uuid4()),
                "job_id": job_id,
                **r.model_dump(),
            }
            for r in rows
        ]
        if row_records:
            db.table("reconciliation_rows").insert(row_records).execute()

        # Update job summary
        db.table("reconciliation_jobs").update(
            {
                "status": ReconciliationStatus.COMPLETED,
                "total_rows": summary["total"],
                "matched_rows": summary["matched"],
                "unmatched_rows": summary["unmatched"],
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", job_id).execute()

        send_reconciliation_complete_email(current_user["email"], payload.name, summary)

    except Exception as exc:
        db.table("reconciliation_jobs").update(
            {"status": ReconciliationStatus.FAILED}
        ).eq("id", job_id).execute()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    result = db.table("reconciliation_jobs").select("*").eq("id", job_id).single().execute()
    return ReconciliationJobResponse(**result.data)


@router.get("/jobs", response_model=List[ReconciliationJobResponse])
async def list_jobs(
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),
):
    result = (
        db.table("reconciliation_jobs")
        .select("*")
        .eq("user_id", str(current_user["id"]))
        .order("created_at", desc=True)
        .execute()
    )
    return [ReconciliationJobResponse(**row) for row in result.data]


@router.get("/jobs/{job_id}", response_model=ReconciliationJobResponse)
async def get_job(
    job_id: str,
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),
):
    result = (
        db.table("reconciliation_jobs")
        .select("*")
        .eq("id", job_id)
        .eq("user_id", str(current_user["id"]))
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return ReconciliationJobResponse(**result.data)


@router.get("/jobs/{job_id}/rows", response_model=List[ReconciliationRow])
async def get_job_rows(
    job_id: str,
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),
):
    # Verify ownership
    job = (
        db.table("reconciliation_jobs")
        .select("id")
        .eq("id", job_id)
        .eq("user_id", str(current_user["id"]))
        .single()
        .execute()
    )
    if not job.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    rows = db.table("reconciliation_rows").select("*").eq("job_id", job_id).execute()
    return [ReconciliationRow(**r) for r in rows.data]


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: str,
    current_user: dict = Depends(get_current_active_user),
    db: Client = Depends(supabase_client),
):
    result = (
        db.table("reconciliation_jobs")
        .delete()
        .eq("id", job_id)
        .eq("user_id", str(current_user["id"]))
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")


@start_router.post("/start", response_model=ReconciliationStartResponse , status_code=status.HTTP_202_ACCEPTED)
async def start_reconciliation_run(
    payload: ReconciliationStartRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Queue async reconciliation for a *READY* run with GSTR + PR data loaded."""
    try:
        UUID(payload.run_id.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid run_id",
        ) from exc
    run_id = str(payload.run_id).strip()
    sb = get_supabase()
    assigned = _assigned_client_gstin_id(sb, current_user)
    # Query 1 — fetch the run
    res = (
        sb.table("reconciliation_run")
        .select(
            "id, client_gstin_id, status, gstr_records_imported, pr_records_imported"
        )
        .eq("id", run_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="run not found",
        )
    row = res.data[0]
    if str(row.get("client_gstin_id", "")).strip() != assigned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="run does not belong to your client scope",
        )
    st = (row.get("status") or "").strip().upper()
    if st != "READY":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"run is not runnable in current state: {row.get('status')}",
        )
    gi = int(row.get("gstr_records_imported") or 0)
    pi = int(row.get("pr_records_imported") or 0)
    if gi <= 0 or pi <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GSTR and purchase register data must both be imported",
        )
    now = datetime.now(timezone.utc).isoformat()
    # Query 2 — update the run (atomic READY → MATCHING)
    upd = (
        sb.table("reconciliation_run")
        .update(
            {
                "status": "MATCHING",
                "processing_started_at": now,
                "progress_percent": 0.0,
                "status_message": "Queued for processing",
                "updated_at": now,
            }
        )
        .eq("id", run_id)
        .eq("status", "READY")
        .execute()
    )
    if not upd.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="reconciliation is already in progress or not in READY state",
        )
    try:
        execute_reconciliation.delay(run_id)
    except Exception as exc:
        _log.exception("Celery enqueue failed for run_id=%s", run_id)
        sb.table("reconciliation_run").update(
            {
                "status": "READY",
                "status_message": f"Queue rejected: {exc!s}"[:2000],
                "processing_started_at": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", run_id).execute()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reconciliation task queue is unavailable. Try again later.",
        ) from exc
    return ReconciliationStartResponse(run_id=run_id, status="MATCHING")


@start_router.get("/status/{run_id}", response_model=ReconciliationStatusResponse)
async def get_reconciliation_run_status(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    try:
        UUID(run_id.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid run_id",
        ) from exc
    sb = get_supabase()
    assigned = _assigned_client_gstin_id(sb, current_user)
    res = (
        sb.table("reconciliation_run")
        .select(
            "id, client_gstin_id, status, progress_percent, status_message, "
            "processing_started_at, completed_at, run_summary, matching_version, rules_version, "
            "decision_version"
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
    if str(row.get("client_gstin_id", "")).strip() != str(assigned).strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="run does not belong to your client scope",
        )

    summary = row.get("run_summary")
    if not isinstance(summary, dict):
        summary = None
    st = str(row.get("status") or "")
    u = st.upper()
    if u in (
        "MATCHING",
        "PROCESSING",
        "COMPLETED",
        "FAILED",
        "READY",
        "GSTR_IMPORT_COMPLETE",
        "PURCHASE_IMPORT_COMPLETE",
    ):
        st = u
    return ReconciliationStatusResponse(
        run_id=row["id"],
        status=st,
        progress_percent=row.get("progress_percent"),
        status_message=row.get("status_message"),
        processing_started_at=row.get("processing_started_at"),
        completed_at=row.get("completed_at"),
        summary=summary,
        matching_version=row.get("matching_version"),
        rules_version=row.get("rules_version"),
        decision_version=row.get("decision_version"),
    )
