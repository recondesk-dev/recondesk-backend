"""Multi-Period Reconciliation Wizard Router.

Endpoints for managing multi-period batch reconciliations.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from app.auth import get_current_active_user
from app.database import get_supabase
from app.services import multi_period_wizard as mpw
from app.services.reconciliation_import_wizard.wizard_service import assert_client_access

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateBatchRequest(BaseModel):
    client_id: str = Field(..., description="UUID of client GSTIN")
    financial_year: str = Field(..., description="Financial year in YYYY-YY format, e.g. 2025-26")


def _assert_client(sb: Any, client_id: str, user_id: str) -> None:
    try:
        assert_client_access(sb, client_id, user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this client GSTIN",
        ) from exc


@router.post("/batches", status_code=status.HTTP_201_CREATED)
async def create_multi_period_batch(
    body: CreateBatchRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Create a new multi-period reconciliation batch for up to 12 periods."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    cid = body.client_id.strip()
    _assert_client(sb, cid, user_id)

    try:
        batch = mpw.create_batch(sb, cid, body.financial_year.strip(), user_id=user_id)
        return batch
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Failed to create multi-period batch: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create batch",
        ) from exc


@router.post("/batches/{batch_id}/fetch-gstr2b")
async def trigger_gstr2b_autofetch(
    batch_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_active_user),
):
    """Trigger asynchronous auto-fetch of GSTR-2B for all 12 periods via Sandbox API."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")

    try:
        batch = mpw.get_batch_with_items(sb, batch_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Batch not found",
        )

    _assert_client(sb, batch["client_gstin_id"], user_id)

    background_tasks.add_task(
        asyncio.run, asyncio.to_thread(mpw.fetch_gstr2b_for_batch, batch_id, user_id)
    )

    return {"status": "fetching", "message": "GSTR-2B auto-fetch started for batch"}


@router.get("/batches/{batch_id}/pr-status")
async def check_batch_pr_status(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Check PR availability (tally_bridge_existing / already_uploaded / missing) per period."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")

    try:
        batch = mpw.get_batch_with_items(sb, batch_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Batch not found",
        )

    _assert_client(sb, batch["client_gstin_id"], user_id)

    items_status = [
        {
            "period": item["period"],
            "pr_source": item["pr_source"],
            "pr_file_path": item["pr_file_path"],
            "is_ready": item["pr_source"] in ("tally_bridge_existing", "already_uploaded", "manual_upload"),
        }
        for item in batch["items"]
    ]

    return {
        "batch_id": batch_id,
        "financial_year": batch["financial_year"],
        "items": items_status,
    }


@router.post("/batches/{batch_id}/periods/{period}/upload-pr")
async def upload_manual_pr_for_period(
    batch_id: str,
    period: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_active_user),
):
    """Fallback manual PR upload for a specific period in the batch."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")

    try:
        batch = mpw.get_batch_with_items(sb, batch_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Batch not found",
        )

    _assert_client(sb, batch["client_gstin_id"], user_id)

    filename = file.filename or "pr.xlsx"
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "xlsx").lower()
    if ext not in ("csv", "xlsx", "xls"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be .csv, .xlsx, or .xls",
        )

    contents = await file.read()
    if not contents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    try:
        updated_batch = mpw.attach_manual_pr(sb, batch_id, period, contents, filename)
        return updated_batch
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Failed to attach manual PR: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload Purchase Register",
        ) from exc


@router.post("/batches/{batch_id}/run")
async def trigger_batch_reconciliation(
    batch_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_active_user),
):
    """Trigger background sequential batch reconciliation across all periods."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")

    try:
        batch = mpw.get_batch_with_items(sb, batch_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Batch not found",
        )

    _assert_client(sb, batch["client_gstin_id"], user_id)

    background_tasks.add_task(
        asyncio.run, asyncio.to_thread(mpw.run_batch, batch_id, user_id)
    )

    return {"status": "running", "message": "Batch reconciliation started"}


@router.get("/batches/{batch_id}")
async def get_multi_period_batch(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Get multi-period batch status and item details for progress polling."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")

    try:
        batch = mpw.get_batch_with_items(sb, batch_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Batch not found",
        )

    _assert_client(sb, batch["client_gstin_id"], user_id)
    return batch


@router.get("/batches/{batch_id}/summary")
async def get_batch_aggregated_summary(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Get aggregated annual rollup summary metrics and monthly trend array."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")

    try:
        summary = mpw.get_batch_summary(sb, batch_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Batch not found",
        )

    _assert_client(sb, summary["client_gstin_id"], user_id)
    return summary


@router.get("/batches")
async def list_multi_period_batches(
    client_id: str = Query(..., description="Client GSTIN ID"),
    current_user: dict = Depends(get_current_active_user),
):
    """List all multi-period reconciliation batches for a given client."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    cid = client_id.strip()
    _assert_client(sb, cid, user_id)

    res = (
        sb.table("multi_period_recon_batches")
        .select("*")
        .eq("client_gstin_id", cid)
        .order("created_at", desc=True)
        .execute()
    )

    batches = res.data or []
    return {"batches": batches}
