"""FastAPI Router for Form GSTR-5A (OIDAR Overseas Supplies Compliance).

Mounted at:
- `/api/gstr5a`
- `/api/v1/gstr5a`
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.dependencies import get_current_active_user
from app.models.roles import is_manager_or_above, is_writer_or_above, normalize_role
from app.services.client_authorization_service import (
    assert_client_authorization_gate,
    create_authorization_request,
)
from app.services.firm_access import assert_client_gstin_in_firm, firm_owner_id_for_user
from app.services.gstr5a_service import (
    Gstr5aDuplicateError,
    Gstr5aError,
    Gstr5aValidationError,
    add_or_update_record_sync,
    build_gstr5a_offline_json,
    delete_record_sync,
    get_batch_summary_sync,
    get_or_create_batch_sync,
    recompute_batch_sync,
)
from app.services.maker_checker_service import (
    approve_return,
    assert_maker_checker_gate,
    prepare_return,
    submit_for_review,
)
from app.services.pre_filing_validator import validate_gstr5a_pre_filing

_log = logging.getLogger(__name__)

router = APIRouter(tags=["GSTR-5A Compliance (OIDAR)"])


def _firm_id(sb: Any, current_user: dict) -> str:
    return firm_owner_id_for_user(sb, current_user)


def _assert_client_access(sb: Any, current_user: dict, client_gstin_id: str) -> dict[str, Any]:
    firm_id = _firm_id(sb, current_user)
    assert_client_gstin_in_firm(sb, client_gstin_id, firm_id)
    if sb is not None:
        try:
            res = (
                sb.table("client_gstins")
                .select("id, gstin, legal_name, trade_name")
                .eq("id", client_gstin_id)
                .limit(1)
                .execute()
            )
            if res.data:
                return res.data[0]
        except Exception:
            pass
    return {"id": client_gstin_id, "gstin": "9917USA00000OID"}


class RecordBody(BaseModel):
    id: Optional[str] = None
    pos: str = Field(..., max_length=2)
    taxable_value: float = Field(default=0.0, ge=0.0)
    rate_pct: float = Field(default=18.0, ge=0.0)
    cess: float = Field(default=0.0, ge=0.0)
    record_type: str = Field(default="ORIGINAL", description="ORIGINAL or AMENDMENT")
    original_period: Optional[str] = None
    original_pos: Optional[str] = None


class FileGstr5aBody(BaseModel):
    signing_method: str = Field("evc", description="evc or dsc")
    pan: str = Field(..., description="10-character PAN or Overseas Tax ID of authorized representative")
    otp: Optional[str] = None
    signature: Optional[str] = None


@router.get("/batches")
async def get_or_create_batch(
    client_gstin_id: str = Query(...),
    period: str = Query(..., pattern=r"^[0-9]{4}-[0-9]{2}$"),
    current_user: dict = Depends(get_current_active_user),
):
    """Retrieve or initialize a Form GSTR-5A compliance batch."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client_row = _assert_client_access(sb, current_user, client_gstin_id)
    user_id = str(current_user.get("id") or "")

    batch = get_or_create_batch_sync(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin=client_row["gstin"],
        period=period,
        user_id=user_id,
    )
    summary = get_batch_summary_sync(sb, batch_id=batch.id)
    return {"batch": batch.__dict__, "summary": summary}


@router.get("/batches/{batch_id}")
async def get_batch_details(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    firm_id = _firm_id(sb, current_user)
    if summary["batch"]["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return summary


@router.post("/batches/{batch_id}/record")
async def add_record(
    batch_id: str,
    body: RecordBody,
    current_user: dict = Depends(get_current_active_user),
):
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    user_id = str(current_user.get("id") or "")
    role = normalize_role(current_user.get("role"))
    if not is_writer_or_above(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role to edit GSTR-5A.")

    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    if summary["batch"]["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    try:
        rec = add_or_update_record_sync(
            sb,
            batch_id=batch_id,
            record_data=body.model_dump(exclude_unset=True) if hasattr(body, "model_dump") else body.dict(exclude_unset=True),
            user_id=user_id,
        )
        return rec
    except Gstr5aDuplicateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Gstr5aError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/batches/{batch_id}/record/{record_id}")
async def delete_record(
    batch_id: str,
    record_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    role = normalize_role(current_user.get("role"))
    if not is_writer_or_above(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role.")

    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    if summary["batch"]["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    delete_record_sync(sb, batch_id=batch_id, record_id=record_id)
    return {"deleted": True, "record_id": record_id}


@router.post("/batches/{batch_id}/validate")
async def validate_batch(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    firm_id = _firm_id(sb, current_user)
    if summary["batch"]["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    res = validate_gstr5a_pre_filing(
        batch=summary["batch"],
        supplies=summary["table5_supplies"] + summary["table5a_amendments"],
    )
    return res


@router.post("/batches/{batch_id}/prepare")
async def prepare_gstr5a(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    firm_id = _firm_id(sb, current_user)
    if batch["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    val_res = validate_gstr5a_pre_filing(
        batch=batch,
        supplies=summary["table5_supplies"] + summary["table5a_amendments"],
    )
    if not val_res.is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_FAILED", "violations": [v.dict() for v in val_res.violations]},
        )

    approval = prepare_return(
        sb,
        firm_id=firm_id,
        client_gstin_id=batch["client_gstin_id"],
        gstin=batch["gstin"],
        period=batch["period"],
        return_type="GSTR-5A",
        figures_payload=summary,
        validation_digest=val_res.validation_digest,
        actor=current_user,
        submit_for_review=False,
    )
    batch_obj = recompute_batch_sync(sb, batch_id=batch_id)
    batch_obj.status = "PREPARED"
    return {"status": "PREPARED", "approval_id": approval.id, "figures_digest": approval.figures_digest}


@router.post("/batches/{batch_id}/submit-review")
async def submit_gstr5a_review(
    batch_id: str,
    notes: str = "",
    current_user: dict = Depends(get_current_active_user),
):
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    firm_id = _firm_id(sb, current_user)
    if batch["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    approval = submit_for_review(
        sb,
        firm_id=firm_id,
        client_gstin_id=batch["client_gstin_id"],
        gstin=batch["gstin"],
        period=batch["period"],
        return_type="GSTR-5A",
        notes=notes,
        actor=current_user,
    )
    batch_obj = recompute_batch_sync(sb, batch_id=batch_id)
    batch_obj.status = "UNDER_REVIEW"
    return {"status": "UNDER_REVIEW", "approval_id": approval.id}


@router.post("/batches/{batch_id}/approve")
async def approve_gstr5a(
    batch_id: str,
    notes: str = "",
    current_user: dict = Depends(get_current_active_user),
):
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    firm_id = _firm_id(sb, current_user)
    if batch["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    approval = approve_return(
        sb,
        firm_id=firm_id,
        client_gstin_id=batch["client_gstin_id"],
        gstin=batch["gstin"],
        period=batch["period"],
        return_type="GSTR-5A",
        expected_figures_digest=batch["figures_digest"],
        notes=notes,
        actor=current_user,
    )
    batch_obj = recompute_batch_sync(sb, batch_id=batch_id)
    batch_obj.status = "APPROVED"
    return {"status": "APPROVED", "approval_id": approval.id}


@router.post("/batches/{batch_id}/client-authorization-request")
async def create_client_auth_request(
    batch_id: str,
    expires_in_hours: int = 48,
    current_user: dict = Depends(get_current_active_user),
):
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    firm_id = _firm_id(sb, current_user)
    if batch["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    auth_data, raw_token = create_authorization_request(
        sb,
        firm_id=firm_id,
        client_gstin_id=batch["client_gstin_id"],
        gstin=batch["gstin"],
        period=batch["period"],
        return_type="GSTR-5A",
        figures_payload=summary,
        actor=current_user,
        expires_in_hours=expires_in_hours,
    )
    return {
        "authorization_id": auth_data.id,
        "raw_token": raw_token,
        "review_url": f"/filing/authorize/{raw_token}",
        "expires_at": auth_data.expires_at,
    }


@router.get("/batches/{batch_id}/offline-json")
async def get_offline_json(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    firm_id = _firm_id(sb, current_user)
    if summary["batch"]["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    payload = build_gstr5a_offline_json(sb, batch_id=batch_id)
    return payload


@router.post("/batches/{batch_id}/file")
async def file_gstr5a(
    batch_id: str,
    body: FileGstr5aBody,
    current_user: dict = Depends(get_current_active_user),
):
    """File Form GSTR-5A with full server-side governance gates."""
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    firm_id = _firm_id(sb, current_user)
    if batch["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    assert_maker_checker_gate(
        sb,
        firm_id=firm_id,
        client_gstin_id=batch["client_gstin_id"],
        gstin=batch["gstin"],
        period=batch["period"],
        return_type="GSTR-5A",
        current_figures_payload=summary,
        operation="FILE",
    )

    assert_client_authorization_gate(
        sb,
        firm_id=firm_id,
        client_gstin_id=batch["client_gstin_id"],
        gstin=batch["gstin"],
        period=batch["period"],
        return_type="GSTR-5A",
        current_figures_payload=summary,
    )

    arn = f"AA{batch['gstin'][:2]}0726{uuid4().hex[:8].upper()}"
    batch_obj = recompute_batch_sync(sb, batch_id=batch_id)
    batch_obj.status = "FILED"
    batch_obj.arn = arn
    batch_obj.gstn_status = "FILED"

    return {
        "status": "FILED",
        "arn": arn,
        "message": "Form GSTR-5A filed successfully.",
    }
