import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.auth import get_current_active_user
from app.database import supabase_client
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


async def _fetch_file_content(file_key: str) -> bytes:
    """Download file bytes from R2 via a presigned URL."""
    import httpx
    url = create_presigned_download_url(file_key)
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


@router.post("/jobs", response_model=ReconciliationJobResponse, status_code=status.HTTP_201_CREATED)
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
