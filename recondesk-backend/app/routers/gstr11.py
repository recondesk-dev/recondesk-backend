"""FastAPI Router for Form GSTR-11 (UIN Inward Supplies & Refund Statement Compliance).

Mounted at:
- `/api/gstr11`
- `/api/v1/gstr11`
"""

from __future__ import annotations

import logging
from typing import Any, Optional

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
from app.services.gstr11_service import (
    Gstr11DuplicateError,
    Gstr11Error,
    Gstr11ValidationError,
    add_or_update_inward_supply_sync,
    build_gstr11_offline_json,
    delete_inward_supply_sync,
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
from app.services.pre_filing_validator import validate_gstr11_pre_filing

_log = logging.getLogger(__name__)

router = APIRouter(tags=["GSTR-11 Compliance (UIN Return)"])


def _firm_id(sb: Any, current_user: dict) -> str:
    return firm_owner_id_for_user(sb, current_user)


def _assert_client_access(sb: Any, current_user: dict, client_gstin_id: str) -> dict[str, Any]:
    firm_id = _firm_id(sb, current_user)
    assert_client_gstin_in_firm(sb, client_gstin_id, firm_id)
    if sb is not None:
        try:
            res = sb.table("client_gstins").select("id, gstin, legal_name, trade_name").eq("id", client_gstin_id).limit(1).execute()
            if res.data:
                return res.data[0]
        except Exception:
            pass
    return {"id": client_gstin_id, "gstin": "0717USA00001UN1"}


class InwardSupplyBody(BaseModel):
    id: Optional[str] = None
    supply_type: str = Field(..., description="3A (Invoice) or 3B (Credit/Debit Note)")
    supplier_gstin: str = Field(..., max_length=15)
    supplier_name: Optional[str] = None
    doc_number: str = Field(..., max_length=100)
    doc_date: str = Field(...)
    taxable_value: float = Field(default=0.0, ge=0.0)
    igst: float = Field(default=0.0, ge=0.0)
    cgst: float = Field(default=0.0, ge=0.0)
    sgst: float = Field(default=0.0, ge=0.0)
    cess: float = Field(default=0.0, ge=0.0)
    cdn_type: Optional[str] = Field(default=None, description="C for Credit Note, D for Debit Note")
    original_invoice_number: Optional[str] = None
    original_invoice_date: Optional[str] = None
    is_eligible_for_refund: bool = Field(default=True)


class FileGstr11Body(BaseModel):
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
    """Retrieve or initialize a Form GSTR-11 compliance batch."""
    sb = get_supabase()
    firm_id = _firm_id(sb, current_user)
    client_row = _assert_client_access(sb, current_user, client_gstin_id)
    user_id = str(current_user.get("id") or "")

    batch = get_or_create_batch_sync(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        uin=client_row["gstin"],
        period=period,
        user_id=user_id,
    )
    return {"batch": batch}


@router.get("/batches/{batch_id}")
async def get_batch_summary(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Fetch full GSTR-11 batch summary with inward supply line items and refund total."""
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    _assert_client_access(sb, current_user, batch["client_gstin_id"])
    return summary


@router.post("/batches/{batch_id}/inward-supplies")
async def add_or_update_inward_supply(
    batch_id: str,
    payload: InwardSupplyBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Add or edit an inward supply record (Table 3A Inward Invoice or Table 3B CDN)."""
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    _assert_client_access(sb, current_user, batch["client_gstin_id"])

    role = normalize_role(current_user.get("role"))
    if not is_writer_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Write permission required."},
        )

    try:
        record = add_or_update_inward_supply_sync(
            sb,
            batch_id=batch_id,
            firm_id=batch["firm_id"],
            client_gstin_id=batch["client_gstin_id"],
            supply_type=payload.supply_type,
            supplier_gstin=payload.supplier_gstin,
            supplier_name=payload.supplier_name,
            doc_number=payload.doc_number,
            doc_date=payload.doc_date,
            taxable_value=payload.taxable_value,
            igst=payload.igst,
            cgst=payload.cgst,
            sgst=payload.sgst,
            cess=payload.cess,
            cdn_type=payload.cdn_type,
            original_invoice_number=payload.original_invoice_number,
            original_invoice_date=payload.original_invoice_date,
            is_eligible_for_refund=payload.is_eligible_for_refund,
            record_id=payload.id,
            current_user=current_user,
        )
        return {"status": "SUCCESS", "record": record}
    except Gstr11ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": str(exc)},
        ) from exc


@router.delete("/batches/{batch_id}/inward-supplies/{record_id}")
async def delete_inward_supply(
    batch_id: str,
    record_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Remove an inward supply record and recompute refund totals."""
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    _assert_client_access(sb, current_user, batch["client_gstin_id"])

    role = normalize_role(current_user.get("role"))
    if not is_writer_or_above(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Write permission required."},
        )

    delete_inward_supply_sync(sb, batch_id=batch_id, record_id=record_id, current_user=current_user)
    return {"status": "SUCCESS", "message": "Inward supply record deleted"}


@router.post("/batches/{batch_id}/validate")
async def validate_batch(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Run pre-filing validation checks for Form GSTR-11."""
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    _assert_client_access(sb, current_user, batch["client_gstin_id"])

    result = validate_gstr11_pre_filing(
        batch=batch,
        inward_records=summary["inward_records"],
    )
    return {"validation": result.__dict__}


@router.get("/batches/{batch_id}/offline-json")
async def export_offline_json(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Generate official GSTN Offline Tool format JSON for Form GSTR-11."""
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    _assert_client_access(sb, current_user, batch["client_gstin_id"])

    offline_payload = build_gstr11_offline_json(
        batch=batch,
        inward_records=summary["inward_records"],
    )
    return offline_payload


@router.post("/batches/{batch_id}/submit-review")
async def submit_batch_for_review(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Maker transitions GSTR-11 batch from DRAFT/PREPARED to UNDER_REVIEW."""
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    firm_id = _firm_id(sb, current_user)
    _assert_client_access(sb, current_user, batch["client_gstin_id"])

    if batch.get("status") == "DRAFT":
        prepare_return(
            sb,
            firm_id=firm_id,
            client_gstin_id=batch["client_gstin_id"],
            return_type="GSTR-11",
            period=batch["period"],
            actor=current_user,
            figures_digest=batch["figures_digest"],
        )

    res = submit_for_review(
        sb,
        firm_id=firm_id,
        client_gstin_id=batch["client_gstin_id"],
        return_type="GSTR-11",
        period=batch["period"],
        actor=current_user,
        figures_digest=batch["figures_digest"],
    )
    return {"status": "SUCCESS", "approval": res.to_dict()}


@router.post("/batches/{batch_id}/approve")
async def approve_batch(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Checker (Manager or Partner) approves GSTR-11 return."""
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    firm_id = _firm_id(sb, current_user)
    _assert_client_access(sb, current_user, batch["client_gstin_id"])

    res = approve_return(
        sb,
        firm_id=firm_id,
        client_gstin_id=batch["client_gstin_id"],
        return_type="GSTR-11",
        period=batch["period"],
        actor=current_user,
        figures_digest=batch["figures_digest"],
    )
    return {"status": "SUCCESS", "approval": res.to_dict()}


@router.post("/batches/{batch_id}/request-authorization")
async def request_client_authorization(
    batch_id: str,
    signatory_name: str = Query(...),
    signatory_email: str = Query(...),
    signatory_phone: Optional[str] = None,
    current_user: dict = Depends(get_current_active_user),
):
    """Create a client filing authorization request with cryptographic figures digest binding."""
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    firm_id = _firm_id(sb, current_user)
    _assert_client_access(sb, current_user, batch["client_gstin_id"])

    req = create_authorization_request(
        sb,
        firm_id=firm_id,
        client_gstin_id=batch["client_gstin_id"],
        return_type="GSTR-11",
        period=batch["period"],
        tax_payable=0.0,
        net_cash_payable=0.0,
        itc_claimed=float(batch["total_net_refund_claimed"]),  # Tracked as refund claim amount
        figures_digest=batch["figures_digest"],
        client_signatory_name=signatory_name,
        client_signatory_email=signatory_email,
        client_signatory_phone=signatory_phone,
        actor=current_user,
    )
    return {"status": "SUCCESS", "authorization_request": req.to_dict()}


@router.post("/batches/{batch_id}/file")
async def file_gstr11(
    batch_id: str,
    payload: FileGstr11Body,
    current_user: dict = Depends(get_current_active_user),
):
    """File Form GSTR-11 with server-side maker-checker and client authorization gate enforcement."""
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    firm_id = _firm_id(sb, current_user)
    _assert_client_access(sb, current_user, batch["client_gstin_id"])

    # 1. Enforce Maker-Checker Gate
    assert_maker_checker_gate(
        sb,
        firm_id=firm_id,
        client_gstin_id=batch["client_gstin_id"],
        return_type="GSTR-11",
        period=batch["period"],
        current_figures_digest=batch["figures_digest"],
    )

    # 2. Enforce Client Authorization Gate
    assert_client_authorization_gate(
        sb,
        firm_id=firm_id,
        client_gstin_id=batch["client_gstin_id"],
        return_type="GSTR-11",
        period=batch["period"],
        current_figures_digest=batch["figures_digest"],
    )

    # 3. Transparent GSTN API status
    return {
        "status": "UNSUPPORTED_BY_GSTN_API",
        "message": (
            "GSTR-11 direct filing API is not provided by GSTN for automated GSP transmission. "
            "Download the verified offline JSON payload and upload directly to the GST common portal to substantiate Form GST RFD-10."
        ),
        "offline_json": build_gstr11_offline_json(batch, summary["inward_records"]),
    }
