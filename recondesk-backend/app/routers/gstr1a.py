"""Phase 4.1: GSTR-1A Amendment Intelligence & Filing Router.

Endpoints for Form GSTR-1A amendment curation, field-level original vs revised diffs,
outward liability delta calculation, GSTR-3B Table 3.1 impact, maker-checker approval,
client authorization gates, official offline JSON export, and GSTN filing.
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
from app.services.pre_filing_validator import validate_gstr1a_pre_filing
from app.services.gstr1a_service import (
    Gstr1aDuplicateError,
    Gstr1aError,
    Gstr1aValidationError,
    Gstr1aWindowClosedError,
    add_or_update_amendment_item_sync,
    build_gstr1a_offline_json,
    compute_gstr1a_window_for_gstin,
    delete_amendment_item_sync,
    get_gstr1a_liability_impact_sync,
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
    tags=["gstr1a"],
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


class AmendmentItemCreateBody(BaseModel):
    table_name: str = Field(..., description="E.g. 4A, 4B, 5, 6A, 9A_B2B, 9B_CDNR, 10")
    action_type: str = Field("ADDITION", description="ADDITION, AMENDMENT, or DELETE")
    original_invoice_number: Optional[str] = None
    original_invoice_date: Optional[str] = None
    amended_invoice_number: Optional[str] = None
    amended_invoice_date: Optional[str] = None
    recipient_gstin: Optional[str] = None
    pos: Optional[str] = None
    supply_type: Optional[str] = None
    original_payload: Optional[dict[str, Any]] = Field(default_factory=dict)
    amended_payload: dict[str, Any] = Field(default_factory=dict)
    source_note: Optional[str] = None
    skip_window_check: bool = False


class PrepareBody(BaseModel):
    notes: Optional[str] = None


class SubmitReviewBody(BaseModel):
    notes: Optional[str] = None


class ApproveBody(BaseModel):
    notes: Optional[str] = None


class RejectBody(BaseModel):
    reason: str = Field(..., min_length=3)


class SaveGstr1aBody(BaseModel):
    session_id: str


class FileGstr1aBody(BaseModel):
    session_id: str
    pan: str
    signing_method: str = "evc"
    otp: Optional[str] = None
    signature: Optional[str] = None


@router.get("/{client_gstin_id}/{period}/window")
def get_window_status(
    client_gstin_id: str,
    period: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Check Rule 59(1A) window status, GSTR-1 & GSTR-3B filing dates, and QRMP state due dates."""
    sb = get_supabase()
    client = _assert_client_access(sb, current_user, client_gstin_id)
    gstin = client["gstin"]
    freq = client.get("filing_frequency") or "monthly"

    # Query filing runs for period to discover if GSTR-1 or GSTR-3B have been filed
    runs_res = (
        sb.table("filing_runs")
        .select("return_type, status, filed_at, created_at")
        .eq("client_gstin_id", client_gstin_id)
        .eq("period", period.strip())
        .execute()
    )
    g1_filed_date: str | None = None
    g3_filed_date: str | None = None
    for r in runs_res.data or []:
        rt = str(r.get("return_type") or "").upper()
        st = str(r.get("status") or "").lower()
        if st == "filed":
            filed_time = r.get("filed_at") or r.get("created_at")
            if "GSTR-1" in rt or rt == "GSTR1":
                g1_filed_date = filed_time
            elif "GSTR-3B" in rt or rt == "GSTR3B":
                g3_filed_date = filed_time

    window_info = compute_gstr1a_window_for_gstin(
        gstin,
        period=period.strip(),
        gstr1_filed_date=g1_filed_date,
        gstr3b_filed_date=g3_filed_date,
        filing_frequency=freq,
    )
    return {
        "client_gstin_id": client_gstin_id,
        "gstin": gstin,
        "period": period.strip(),
        "window": window_info,
    }


@router.get("/{client_gstin_id}/{period}/batch")
def get_gstr1a_batch(
    client_gstin_id: str,
    period: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Retrieve the GSTR-1A amendment batch, all amendment items, and maker-checker status."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client = _assert_client_access(sb, current_user, client_gstin_id)
    gstin = client["gstin"]
    norm_period = period.strip()

    batch = get_or_create_batch_sync(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin=gstin,
        period=norm_period,
    )
    batch_id = str(batch["id"])

    items_res = (
        sb.table("gstr1a_amendment_items")
        .select("*")
        .eq("batch_id", batch_id)
        .order("created_at", desc=False)
        .execute()
    )
    items = items_res.data or []

    # Get maker-checker approval record if exists
    approval = get_return_approval(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        period=norm_period,
        return_type="GSTR-1A",
    )

    # Get latest client authorization if exists
    client_auth = get_latest_client_authorization(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        period=norm_period,
        return_type="GSTR-1A",
    )

    return {
        "batch": batch,
        "items": items,
        "approval": approval.to_dict() if approval else None,
        "client_authorization": client_auth.to_dict() if client_auth else None,
    }


@router.post("/{client_gstin_id}/{period}/items")
def add_amendment_item(
    client_gstin_id: str,
    period: str,
    body: AmendmentItemCreateBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Add or update an invoice addition or amendment in the GSTR-1A batch."""
    role = str(current_user.get("role") or "").strip().lower()
    if not is_writer_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Writer or higher role required to modify GSTR-1A amendments",
        )

    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client = _assert_client_access(sb, current_user, client_gstin_id)
    gstin = client["gstin"]
    norm_period = period.strip()

    actor_id = str(current_user.get("id") or "")
    actor_name = str(current_user.get("full_name") or current_user.get("email") or "Accountant")

    try:
        item = add_or_update_amendment_item_sync(
            sb,
            firm_id=firm_id,
            client_gstin_id=client_gstin_id,
            gstin=gstin,
            period=norm_period,
            table_name=body.table_name,
            action_type=body.action_type,
            amended_payload=body.amended_payload,
            original_payload=body.original_payload,
            original_invoice_number=body.original_invoice_number,
            original_invoice_date=body.original_invoice_date,
            amended_invoice_number=body.amended_invoice_number,
            amended_invoice_date=body.amended_invoice_date,
            recipient_gstin=body.recipient_gstin,
            pos=body.pos,
            supply_type=body.supply_type,
            source_note=body.source_note,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=role,
            skip_window_check=body.skip_window_check,
        )
        return {"success": True, "item": item}
    except Gstr1aWindowClosedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Gstr1aDuplicateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Gstr1aValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Gstr1aError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{client_gstin_id}/{period}/items/{item_id}")
def delete_amendment_item(
    client_gstin_id: str,
    period: str,
    item_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Delete an amendment item from the GSTR-1A batch and recompute totals."""
    role = str(current_user.get("role") or "").strip().lower()
    if not is_writer_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Writer or higher role required to delete GSTR-1A amendment items",
        )

    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    _assert_client_access(sb, current_user, client_gstin_id)

    actor_id = str(current_user.get("id") or "")
    actor_name = str(current_user.get("full_name") or current_user.get("email") or "Accountant")

    try:
        res = delete_amendment_item_sync(
            sb,
            firm_id=firm_id,
            client_gstin_id=client_gstin_id,
            period=period.strip(),
            item_id=item_id,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=role,
        )
        return {"success": True, **res}
    except Gstr1aError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{client_gstin_id}/{period}/liability-impact")
def get_liability_impact(
    client_gstin_id: str,
    period: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Retrieve net outward liability adjustments and direct impact on GSTR-3B Table 3.1."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    _assert_client_access(sb, current_user, client_gstin_id)

    impact = get_gstr1a_liability_impact_sync(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        period=period.strip(),
    )
    return impact


@router.post("/{client_gstin_id}/{period}/export-json")
def export_gstr1a_offline_json(
    client_gstin_id: str,
    period: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Export official GSTN offline JSON format for Form GSTR-1A."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client = _assert_client_access(sb, current_user, client_gstin_id)
    gstin = client["gstin"]
    norm_period = period.strip()

    batch = get_or_create_batch_sync(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin=gstin,
        period=norm_period,
    )
    batch_id = str(batch["id"])

    items_res = (
        sb.table("gstr1a_amendment_items")
        .select("*")
        .eq("batch_id", batch_id)
        .order("created_at", desc=False)
        .execute()
    )
    items = items_res.data or []

    payload = build_gstr1a_offline_json(batch, items)
    return {
        "filename": f"GSTR1A_{gstin}_{norm_period.replace('-', '')}.json",
        "payload": payload,
        "figures_digest": batch.get("figures_digest"),
    }


@router.post("/{client_gstin_id}/{period}/prepare")
def prepare_gstr1a(
    client_gstin_id: str,
    period: str,
    body: PrepareBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Prepare GSTR-1A return and bind figures digest."""
    role = str(current_user.get("role") or "").strip().lower()
    if not is_writer_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Writer role required to prepare return",
        )

    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client = _assert_client_access(sb, current_user, client_gstin_id)
    gstin = client["gstin"]
    norm_period = period.strip()

    batch = get_or_create_batch_sync(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin=gstin,
        period=norm_period,
    )
    batch_id = str(batch["id"])

    items_res = (
        sb.table("gstr1a_amendment_items")
        .select("*")
        .eq("batch_id", batch_id)
        .execute()
    )
    items = items_res.data or []

    val_result = validate_gstr1a_pre_filing(
        gstin=gstin,
        period=norm_period,
        batch=batch,
        items=items,
    )

    approval = prepare_return(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin=gstin,
        period=norm_period,
        return_type="GSTR-1A",
        figures_payload=dict(batch),
        preparer_id=str(current_user.get("id")),
        preparer_name=str(current_user.get("full_name") or current_user.get("email")),
        preparer_role=role,
        validation_digest=val_result.validation_digest,
        submission_notes=body.notes or "",
    )

    # Update batch status
    sb.table("gstr1a_amendment_batches").update({
        "status": "PREPARED",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", batch_id).execute()

    return {"success": True, "approval": approval.to_dict(), "validation": val_result.to_dict()}


@router.post("/{client_gstin_id}/{period}/submit-review")
def submit_gstr1a_review(
    client_gstin_id: str,
    period: str,
    body: SubmitReviewBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Submit prepared GSTR-1A return for maker-checker review."""
    role = str(current_user.get("role") or "").strip().lower()
    if not is_writer_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Writer role required to submit for review",
        )

    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client = _assert_client_access(sb, current_user, client_gstin_id)
    norm_period = period.strip()

    approval = submit_for_review(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        period=norm_period,
        return_type="GSTR-1A",
        actor_id=str(current_user.get("id")),
        actor_name=str(current_user.get("full_name") or current_user.get("email")),
        actor_role=role,
        notes=body.notes or "",
    )

    # Update batch status
    sb.table("gstr1a_amendment_batches").update({
        "status": "UNDER_REVIEW",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("firm_id", firm_id).eq("client_gstin_id", client_gstin_id).eq("period", norm_period).execute()

    return {"success": True, "approval": approval.to_dict()}


@router.post("/{client_gstin_id}/{period}/approve")
def approve_gstr1a(
    client_gstin_id: str,
    period: str,
    body: ApproveBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Approve GSTR-1A return (enforces separation of duties: preparer != approver)."""
    role = str(current_user.get("role") or "").strip().lower()
    if not is_manager_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager or higher role required to approve return",
        )

    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client = _assert_client_access(sb, current_user, client_gstin_id)
    norm_period = period.strip()

    batch_res = (
        sb.table("gstr1a_amendment_batches")
        .select("*")
        .eq("firm_id", firm_id)
        .eq("client_gstin_id", client_gstin_id)
        .eq("period", norm_period)
        .execute()
    )
    if not batch_res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GSTR-1A batch not found")
    batch = batch_res.data[0]

    approval = approve_return(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        period=norm_period,
        return_type="GSTR-1A",
        approver_id=str(current_user.get("id")),
        approver_name=str(current_user.get("full_name") or current_user.get("email")),
        approver_role=role,
        approval_notes=body.notes or "",
        current_figures_payload=batch,
    )

    sb.table("gstr1a_amendment_batches").update({
        "status": "APPROVED",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", batch.get("id")).execute()

    return {"success": True, "approval": approval.to_dict()}


@router.post("/{client_gstin_id}/{period}/reject")
def reject_gstr1a(
    client_gstin_id: str,
    period: str,
    body: RejectBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Reject GSTR-1A submission with rejection reason."""
    role = str(current_user.get("role") or "").strip().lower()
    if not is_manager_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager or higher role required to reject return",
        )

    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    _assert_client_access(sb, current_user, client_gstin_id)
    norm_period = period.strip()

    approval = reject_return(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        period=norm_period,
        return_type="GSTR-1A",
        rejected_by=str(current_user.get("id")),
        rejected_by_name=str(current_user.get("full_name") or current_user.get("email")),
        rejected_by_role=role,
        rejection_reason=body.reason,
    )

    sb.table("gstr1a_amendment_batches").update({
        "status": "REJECTED",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("firm_id", firm_id).eq("client_gstin_id", client_gstin_id).eq("period", norm_period).execute()

    return {"success": True, "approval": approval.to_dict()}


@router.post("/{client_gstin_id}/{period}/save")
def save_gstr1a_to_gstn(
    client_gstin_id: str,
    period: str,
    body: SaveGstr1aBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Save GSTR-1A payload to GSTN (Enforces Maker-Checker Gate)."""
    role = str(current_user.get("role") or "").strip().lower()
    if not is_writer_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Writer role required to save return",
        )

    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client = _assert_client_access(sb, current_user, client_gstin_id)
    gstin = client["gstin"]
    norm_period = period.strip()

    # Fetch batch & items
    batch = get_or_create_batch_sync(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin=gstin,
        period=norm_period,
    )
    items_res = (
        sb.table("gstr1a_amendment_items")
        .select("*")
        .eq("batch_id", batch["id"])
        .execute()
    )
    items = items_res.data or []

    # Maker-Checker Gate Enforcement
    assert_maker_checker_gate(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin=gstin,
        period=norm_period,
        return_type="GSTR-1A",
        current_figures_payload=dict(batch),
        operation="SAVE",
    )

    # Load filing session
    sess_res = (
        sb.table("filing_sessions")
        .select("session_token, status")
        .eq("id", body.session_id)
        .eq("firm_id", firm_id)
        .limit(1)
        .execute()
    )
    if not sess_res.data or sess_res.data[0].get("status") != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Active taxpayer OTP session is required",
        )
    taxpayer_token = str(sess_res.data[0]["session_token"])

    save_payload = build_gstr1a_offline_json(batch, items)

    try:
        with get_filing_client() as filing_client:
            api_res = filing_client.save_gstr1a(
                taxpayer_token,
                period=norm_period,
                save_body=save_payload,
            )
    except FilingGstnError as exc:
        if exc.error_cd == "UNSUPPORTED_BY_GSTN_API":
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail={"code": "UNSUPPORTED_BY_GSTN_API", "message": str(exc)},
            ) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FilingClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    # Update batch
    ref_id = api_res.reference_id
    sb.table("gstr1a_amendment_batches").update({
        "status": "SAVED",
        "gstn_reference_id": ref_id,
        "gstn_status": "REC",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", batch["id"]).execute()

    return {
        "success": True,
        "reference_id": ref_id,
        "status": "save_accepted",
    }


@router.post("/{client_gstin_id}/{period}/file")
def file_gstr1a_on_gstn(
    client_gstin_id: str,
    period: str,
    body: FileGstr1aBody,
    current_user: dict = Depends(get_current_active_user),
):
    """File Form GSTR-1A on GSTN (Enforces Maker-Checker & Client Consent Gates)."""
    role = str(current_user.get("role") or "").strip().lower()
    if not is_writer_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Writer role required to file return",
        )

    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client = _assert_client_access(sb, current_user, client_gstin_id)
    gstin = client["gstin"]
    norm_period = period.strip()

    batch = get_or_create_batch_sync(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin=gstin,
        period=norm_period,
    )
    items_res = (
        sb.table("gstr1a_amendment_items")
        .select("*")
        .eq("batch_id", batch["id"])
        .execute()
    )
    items = items_res.data or []

    # 1. Enforce Maker-Checker Gate
    assert_maker_checker_gate(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin=gstin,
        period=norm_period,
        return_type="GSTR-1A",
        current_figures_payload=dict(batch),
        operation="FILE",
    )

    # 2. Enforce Client Authorization Gate
    assert_client_authorization_gate(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin=gstin,
        period=norm_period,
        return_type="GSTR-1A",
        current_figures_payload=dict(batch),
    )

    # 3. Load session
    sess_res = (
        sb.table("filing_sessions")
        .select("session_token, status")
        .eq("id", body.session_id)
        .eq("firm_id", firm_id)
        .limit(1)
        .execute()
    )
    if not sess_res.data or sess_res.data[0].get("status") != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Active taxpayer OTP session is required",
        )
    taxpayer_token = str(sess_res.data[0]["session_token"])

    file_payload = build_gstr1a_offline_json(batch, items)

    try:
        with get_filing_client() as filing_client:
            api_res = filing_client.file_gstr1a(
                taxpayer_token,
                period=norm_period,
                pan=body.pan,
                otp=body.otp,
                signature=body.signature,
                signing_method=body.signing_method,
                file_body=file_payload,
            )
    except FilingGstnError as exc:
        if exc.error_cd == "UNSUPPORTED_BY_GSTN_API":
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail={"code": "UNSUPPORTED_BY_GSTN_API", "message": str(exc)},
            ) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FilingClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    arn = api_res.ack_number
    if not arn:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Filing did not return an authoritative acknowledgement ARN from GSTN",
        )

    sb.table("gstr1a_amendment_batches").update({
        "status": "FILED",
        "arn": arn,
        "gstn_status": "P",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", batch["id"]).execute()

    return {
        "success": True,
        "arn": arn,
        "status": "FILED",
    }
