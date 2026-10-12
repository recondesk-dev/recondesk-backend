"""FastAPI Router for Form GSTR-10 (Final Return Compliance).

Mounted at:
- `/api/gstr10`
- `/api/v1/gstr10`
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
from app.services.gstr10_service import (
    Gstr10DuplicateError,
    Gstr10Error,
    Gstr10ValidationError,
    add_or_update_stock_record_sync,
    build_gstr10_offline_json,
    delete_stock_record_sync,
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
from app.services.pre_filing_validator import validate_gstr10_pre_filing

_log = logging.getLogger(__name__)

router = APIRouter(tags=["GSTR-10 Compliance (Final Return)"])


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
    return {"id": client_gstin_id, "gstin": "27AAACG0000A1Z5"}


class StockRecordBody(BaseModel):
    id: Optional[str] = None
    item_type: str = Field(..., description="8A, 8B, 8C, 8D")
    supplier_gstin: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    description: str = Field(..., max_length=255)
    uqc: str = Field(default="NOS", max_length=10)
    quantity: float = Field(default=1.0, ge=0.0)
    taxable_value: float = Field(default=0.0, ge=0.0)
    reverse_igst: float = Field(default=0.0, ge=0.0)
    reverse_cgst: float = Field(default=0.0, ge=0.0)
    reverse_sgst: float = Field(default=0.0, ge=0.0)
    reverse_cess: float = Field(default=0.0, ge=0.0)
    ca_name: Optional[str] = None
    ca_membership_number: Optional[str] = None


class FileGstr10Body(BaseModel):
    signing_method: str = Field("evc", description="evc or dsc")
    pan: str = Field(..., description="10-character PAN of authorized signatory")
    otp: Optional[str] = None
    signature: Optional[str] = None


@router.get("/batches")
async def get_or_create_batch(
    client_gstin_id: str = Query(...),
    period: str = Query(..., pattern=r"^[0-9]{4}-[0-9]{2}$"),
    cancellation_order_number: Optional[str] = "ORD/CANC/001",
    cancellation_order_date: Optional[str] = None,
    effective_cancellation_date: Optional[str] = None,
    cancellation_arn: Optional[str] = None,
    current_user: dict = Depends(get_current_active_user),
):
    """Retrieve or initialize a Form GSTR-10 compliance batch."""
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
        cancellation_order_number=cancellation_order_number or "ORD/CANC/001",
        cancellation_order_date=cancellation_order_date or "",
        effective_cancellation_date=effective_cancellation_date or "",
        cancellation_arn=cancellation_arn or "",
        user_id=user_id,
    )
    return {"batch": batch}


@router.get("/batches/{batch_id}")
async def get_batch_summary(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Fetch full GSTR-10 batch summary with stock line items."""
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    _assert_client_access(sb, current_user, batch["client_gstin_id"])
    return summary


@router.post("/batches/{batch_id}/stock-records")
async def add_or_update_stock_record(
    batch_id: str,
    payload: StockRecordBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Add or edit a closing stock line item (Table 8A, 8B, 8C, or 8D)."""
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
        record = add_or_update_stock_record_sync(
            sb,
            batch_id=batch_id,
            firm_id=batch["firm_id"],
            client_gstin_id=batch["client_gstin_id"],
            item_type=payload.item_type,
            supplier_gstin=payload.supplier_gstin,
            invoice_number=payload.invoice_number,
            invoice_date=payload.invoice_date,
            description=payload.description,
            uqc=payload.uqc,
            quantity=payload.quantity,
            taxable_value=payload.taxable_value,
            reverse_igst=payload.reverse_igst,
            reverse_cgst=payload.reverse_cgst,
            reverse_sgst=payload.reverse_sgst,
            reverse_cess=payload.reverse_cess,
            ca_name=payload.ca_name,
            ca_membership_number=payload.ca_membership_number,
            record_id=payload.id,
            current_user=current_user,
        )
        return {"status": "SUCCESS", "record": record}
    except Gstr10ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": str(exc)},
        ) from exc


@router.delete("/batches/{batch_id}/stock-records/{record_id}")
async def delete_stock_record(
    batch_id: str,
    record_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Remove a closing stock record and recompute reversal totals."""
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

    delete_stock_record_sync(sb, batch_id=batch_id, record_id=record_id, current_user=current_user)
    return {"status": "SUCCESS", "message": "Stock record deleted"}


@router.post("/batches/{batch_id}/validate")
async def validate_batch(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Run pre-filing validation checks for Form GSTR-10."""
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    _assert_client_access(sb, current_user, batch["client_gstin_id"])

    result = validate_gstr10_pre_filing(
        batch=batch,
        stock_records=summary["stock_records"],
    )
    return {"validation": result.__dict__}


@router.get("/batches/{batch_id}/offline-json")
async def export_offline_json(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Generate official GSTN Offline Tool format JSON for Form GSTR-10."""
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    _assert_client_access(sb, current_user, batch["client_gstin_id"])

    offline_payload = build_gstr10_offline_json(
        batch=batch,
        stock_records=summary["stock_records"],
    )
    return offline_payload


@router.post("/batches/{batch_id}/submit-review")
async def submit_batch_for_review(
    batch_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Maker transitions GSTR-10 batch from DRAFT/PREPARED to UNDER_REVIEW."""
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    firm_id = _firm_id(sb, current_user)
    _assert_client_access(sb, current_user, batch["client_gstin_id"])

    # Prepare first if draft
    if batch.get("status") == "DRAFT":
        prepare_return(
            sb,
            firm_id=firm_id,
            client_gstin_id=batch["client_gstin_id"],
            return_type="GSTR-10",
            period=batch["period"],
            actor=current_user,
            figures_digest=batch["figures_digest"],
        )

    res = submit_for_review(
        sb,
        firm_id=firm_id,
        client_gstin_id=batch["client_gstin_id"],
        return_type="GSTR-10",
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
    """Checker (Manager or Partner) approves GSTR-10 return."""
    sb = get_supabase()
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]
    firm_id = _firm_id(sb, current_user)
    _assert_client_access(sb, current_user, batch["client_gstin_id"])

    res = approve_return(
        sb,
        firm_id=firm_id,
        client_gstin_id=batch["client_gstin_id"],
        return_type="GSTR-10",
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
        return_type="GSTR-10",
        period=batch["period"],
        tax_payable=float(batch["total_reversal_liability"]),
        net_cash_payable=float(batch["total_reversal_liability"]),
        itc_claimed=0.0,
        figures_digest=batch["figures_digest"],
        client_signatory_name=signatory_name,
        client_signatory_email=signatory_email,
        client_signatory_phone=signatory_phone,
        actor=current_user,
    )
    return {"status": "SUCCESS", "authorization_request": req.to_dict()}


@router.post("/batches/{batch_id}/file")
async def file_gstr10(
    batch_id: str,
    payload: FileGstr10Body,
    current_user: dict = Depends(get_current_active_user),
):
    """File Form GSTR-10 with server-side maker-checker and client authorization gate enforcement."""
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
        return_type="GSTR-10",
        period=batch["period"],
        current_figures_digest=batch["figures_digest"],
    )

    # 2. Enforce Client Authorization Gate
    assert_client_authorization_gate(
        sb,
        firm_id=firm_id,
        client_gstin_id=batch["client_gstin_id"],
        return_type="GSTR-10",
        period=batch["period"],
        current_figures_digest=batch["figures_digest"],
    )

    # 3. Transparent GSTN API status
    return {
        "status": "UNSUPPORTED_BY_GSTN_API",
        "message": (
            "GSTR-10 direct filing API is not provided by GSTN for automated GSP transmission. "
            "Download the verified offline JSON payload and upload directly to the GST common portal."
        ),
        "offline_json": build_gstr10_offline_json(batch, summary["stock_records"]),
    }
