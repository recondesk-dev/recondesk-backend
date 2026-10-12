"""Phase 4.2: Form GSTR-8 (TCS under Section 52) API Router.

Endpoints for GSTR-8 return preparation, supplier-wise net taxable supply reconciliation,
statutory TCS rate calculation, maker-checker governance, client authorization,
offline JSON export, and GSTN filing integration.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth import get_current_active_user
from app.models.roles import is_admin_or_partner, is_manager_or_above, is_writer_or_above
from app.database import get_supabase
from app.services.firm_access import list_accessible_client_gstin_ids
from app.utils.audit import resolve_firm_id
from app.services.maker_checker_service import (
    ApprovalStatus,
    approve_return,
    assert_maker_checker_gate,
    get_return_approval,
    prepare_return,
    reject_return,
    submit_for_review,
)
from app.services.client_authorization_service import (
    assert_client_authorization_gate,
    get_latest_client_authorization,
)
from app.services.pre_filing_validator import validate_gstr8_pre_filing
from app.services.gstr8_service import (
    Gstr8DuplicateError,
    Gstr8Error,
    Gstr8ValidationError,
    add_or_update_gstr8_record_sync,
    build_gstr8_offline_json,
    delete_gstr8_record_sync,
    get_batch_summary_sync,
    get_or_create_batch_sync,
)
from app.filing.sandbox_filing_client import (
    FilingApiError,
    FilingClientError,
    FilingGstnError,
    get_filing_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["gstr8"],
    redirect_slashes=False,
)


def _firm_id(sb: Any, user: dict) -> str:
    firm = resolve_firm_id(sb, user)
    if not firm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not resolve firm_id for user",
        )
    return firm


def _assert_client_access(sb: Any, user: dict, client_gstin_id: str) -> dict[str, Any]:
    allowed = list_accessible_client_gstin_ids(sb, user)
    if client_gstin_id not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied for this client GSTIN",
        )
    res = (
        sb.table("client_gstins")
        .select("id, gstin, filing_frequency, state_code")
        .eq("id", client_gstin_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client GSTIN record not found",
        )
    return res.data[0]


class Gstr8RecordBody(BaseModel):
    id: Optional[str] = None
    supply_type: str = Field("B2B", description="B2B (registered) or B2C (unregistered)")
    record_type: str = Field("ORIGINAL", description="ORIGINAL (Table 3) or AMENDMENT (Table 4)")
    supplier_gstin: Optional[str] = Field(None, description="15-character supplier GSTIN (required for B2B)")
    pos: Optional[str] = Field(None, description="2-digit Place of Supply code")
    gross_supplies: float = Field(..., description="Gross value of taxable supplies made")
    returned_supplies: float = Field(0.0, description="Value of supplies returned")
    tcs_igst: Optional[float] = None
    tcs_cgst: Optional[float] = None
    tcs_sgst: Optional[float] = None
    original_period: Optional[str] = Field(None, description="YYYY-MM for Table 4 amendments")
    original_supplier_gstin: Optional[str] = Field(None, description="Original supplier GSTIN for Table 4A")
    original_pos: Optional[str] = Field(None, description="Original POS for Table 4B")
    tax_deposited: Optional[float] = Field(0.0, description="Tax deposited amount")


class MakerCheckerActionBody(BaseModel):
    notes: Optional[str] = None
    rejection_reason: Optional[str] = None


class FileGstr8Body(BaseModel):
    signing_method: str = Field("evc", description="evc or dsc")
    pan: str = Field(..., description="10-character PAN of authorized signatory")
    otp: Optional[str] = None
    signature: Optional[str] = None


@router.get("/batches")
async def get_or_create_batch(
    client_gstin_id: str = Query(...),
    period: str = Query(..., pattern=r"^[0-9]{4}-[0-9]{2}$"),
    current_user: dict = Depends(get_current_active_user),
):
    """Retrieve or initialize a Form GSTR-8 compliance batch."""
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
    return batch


@router.get("/batches/{batch_id}")
async def get_batch_summary(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Fetch complete GSTR-8 batch details, Table 3 & 4 records, and exception dashboard."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    try:
        summary = get_batch_summary_sync(sb, batch_id=batch_id)
    except Gstr8Error as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if summary["batch"]["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return summary


@router.post("/batches/{batch_id}/records")
async def add_or_update_record(
    batch_id: str,
    body: Gstr8RecordBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Add or update a TCS supply record in Form GSTR-8."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    user_id = str(current_user.get("id") or "")
    role = str(current_user.get("role") or "").lower()

    if not is_writer_or_above(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Role lacks write permissions")

    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    if summary["batch"]["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    try:
        rec = add_or_update_gstr8_record_sync(
            sb,
            batch_id=batch_id,
            record_data=body.model_dump(exclude_unset=True) if hasattr(body, "model_dump") else body.dict(exclude_unset=True),
            user_id=user_id,
        )
        return rec
    except Gstr8DuplicateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Gstr8ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Gstr8Error as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/batches/{batch_id}/records/{record_id}")
async def delete_record(
    batch_id: str,
    record_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Delete a TCS supply record from Form GSTR-8."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    user_id = str(current_user.get("id") or "")
    role = str(current_user.get("role") or "").lower()

    if not is_writer_or_above(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Role lacks write permissions")

    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    if summary["batch"]["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    ok = delete_gstr8_record_sync(sb, batch_id=batch_id, record_id=record_id, user_id=user_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")
    return {"status": "deleted", "id": record_id}


@router.post("/batches/{batch_id}/validate")
async def validate_batch(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Run statutory pre-filing validation on Form GSTR-8."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)

    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    if batch["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    all_records = (
        summary["table3_b2b"]
        + summary["table3_b2c"]
        + summary["table4_b2b"]
        + summary["table4_b2c"]
    )

    result = validate_gstr8_pre_filing(
        gstin=batch["gstin"],
        period=batch["period"],
        batch=batch,
        records=all_records,
    )
    return result.to_dict()


@router.post("/batches/{batch_id}/prepare")
async def prepare_gstr8(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Preparer marks GSTR-8 as PREPARED with bound figures digest."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    user_id = str(current_user.get("id") or "")
    role = str(current_user.get("role") or "").lower()

    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    if batch["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    all_records = (
        summary["table3_b2b"]
        + summary["table3_b2c"]
        + summary["table4_b2b"]
        + summary["table4_b2c"]
    )
    val = validate_gstr8_pre_filing(
        gstin=batch["gstin"],
        period=batch["period"],
        batch=batch,
        records=all_records,
    )
    if not val.is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Pre-filing validation failed with critical errors: {[v.message for v in val.critical_errors]}",
        )

    approval = prepare_return(
        sb,
        firm_id=firm_id,
        client_gstin_id=batch["client_gstin_id"],
        gstin=batch["gstin"],
        period=batch["period"],
        return_type="GSTR-8",
        preparer_id=user_id,
        preparer_name=str(current_user.get("full_name") or "Preparer"),
        preparer_role=role,
        figures_digest=batch["figures_digest"],
        validation_digest=val.validation_digest,
        figures_summary={"total_records": len(all_records), "net_taxable_value": batch["net_taxable_value"]},
    )
    return {"status": "PREPARED", "approval_id": approval.id}


@router.post("/batches/{batch_id}/submit-review")
async def submit_review_gstr8(
    batch_id: str,
    body: MakerCheckerActionBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Submit PREPARED GSTR-8 for checker approval."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    user_id = str(current_user.get("id") or "")
    role = str(current_user.get("role") or "").lower()

    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    if batch["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    appr = get_return_approval(sb, firm_id, batch["client_gstin_id"], batch["period"], "GSTR-8")
    if not appr:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval record not found")

    res = submit_for_review(
        sb,
        approval_id=appr.id,
        actor_id=user_id,
        actor_name=str(current_user.get("full_name") or "Preparer"),
        actor_role=role,
        notes=body.notes,
    )
    return {"status": res.status.value}


@router.post("/batches/{batch_id}/approve")
async def approve_gstr8(
    batch_id: str,
    body: MakerCheckerActionBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Checker approves GSTR-8 (Enforces 4-eyes principle; preparer cannot approve)."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    user_id = str(current_user.get("id") or "")
    role = str(current_user.get("role") or "").lower()

    if not is_manager_or_above(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Managers and Partners can approve")

    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    if batch["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    appr = get_return_approval(sb, firm_id, batch["client_gstin_id"], batch["period"], "GSTR-8")
    if not appr:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval record not found")

    res = approve_return(
        sb,
        approval_id=appr.id,
        approver_id=user_id,
        approver_name=str(current_user.get("full_name") or "Approver"),
        approver_role=role,
        notes=body.notes,
        current_figures_digest=batch["figures_digest"],
    )
    return {"status": res.status.value}


@router.post("/batches/{batch_id}/reject")
async def reject_gstr8(
    batch_id: str,
    body: MakerCheckerActionBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Checker rejects GSTR-8 with required justification."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    user_id = str(current_user.get("id") or "")
    role = str(current_user.get("role") or "").lower()

    if not is_manager_or_above(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Managers and Partners can reject")

    if not body.rejection_reason or not body.rejection_reason.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rejection reason is required")

    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    if batch["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    appr = get_return_approval(sb, firm_id, batch["client_gstin_id"], batch["period"], "GSTR-8")
    if not appr:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval record not found")

    res = reject_return(
        sb,
        approval_id=appr.id,
        rejector_id=user_id,
        rejector_name=str(current_user.get("full_name") or "Rejector"),
        rejector_role=role,
        reason=body.rejection_reason,
    )
    return {"status": res.status.value}


@router.get("/batches/{batch_id}/offline-json")
async def get_offline_json(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Export official GSTN offline utility compliant JSON for Form GSTR-8."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)

    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    if batch["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    offline_json = build_gstr8_offline_json(sb, batch_id=batch_id)
    return offline_json


@router.post("/batches/{batch_id}/save")
async def save_to_gstn(
    batch_id: str,
    taxpayer_token: str = Query(...),
    current_user: dict = Depends(get_current_active_user),
):
    """Save Form GSTR-8 to GSTN (Enforces Maker-Checker gate)."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)

    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    if batch["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    assert_maker_checker_gate(
        sb,
        firm_id=firm_id,
        client_gstin_id=batch["client_gstin_id"],
        period=batch["period"],
        return_type="GSTR-8",
        action="SAVE",
        current_figures_digest=batch["figures_digest"],
    )

    offline_json = build_gstr8_offline_json(sb, batch_id=batch_id)
    client = get_filing_client()

    try:
        res = client.save_gstr8(taxpayer_token, period=batch["period"], save_body=offline_json)
        return {"status": "SAVED", "gstn_response": res.data}
    except FilingGstnError as exc:
        if exc.error_cd == "UNSUPPORTED_BY_GSTN_API":
            return {
                "status": "SAVED_OFFLINE_READY",
                "notice": str(exc),
                "offline_json": offline_json,
            }
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("GSTR-8 Save failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/batches/{batch_id}/file")
async def file_to_gstn(
    batch_id: str,
    body: FileGstr8Body,
    taxpayer_token: str = Query(...),
    current_user: dict = Depends(get_current_active_user),
):
    """File Form GSTR-8 with GSTN (Enforces Maker-Checker & Client Authorization gates)."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)

    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    if batch["firm_id"] != firm_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Enforce Maker-Checker gate
    assert_maker_checker_gate(
        sb,
        firm_id=firm_id,
        client_gstin_id=batch["client_gstin_id"],
        period=batch["period"],
        return_type="GSTR-8",
        action="FILE",
        current_figures_digest=batch["figures_digest"],
    )

    # Enforce Client Authorization gate
    assert_client_authorization_gate(
        sb,
        firm_id=firm_id,
        client_gstin_id=batch["client_gstin_id"],
        period=batch["period"],
        return_type="GSTR-8",
        current_figures_digest=batch["figures_digest"],
    )

    offline_json = build_gstr8_offline_json(sb, batch_id=batch_id)
    client = get_filing_client()

    try:
        res = client.file_gstr8(
            taxpayer_token,
            period=batch["period"],
            pan=body.pan,
            otp=body.otp,
            signature=body.signature,
            signing_method=body.signing_method,
            file_body=offline_json,
        )
        return {"status": "FILED", "arn": res.ack_number, "gstn_response": res.data}
    except FilingGstnError as exc:
        if exc.error_cd == "UNSUPPORTED_BY_GSTN_API":
            return {
                "status": "OFFLINE_EXPORT_READY",
                "notice": str(exc),
                "offline_json": offline_json,
            }
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("GSTR-8 File failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
