"""Backend Service for Credit Notes & Debit Notes (CDNR Module).

Handles creation, editing, tax calculation, finalization, IRP submission,
and PDF generation for Credit and Debit Notes linked to original e-invoices.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from fastapi import HTTPException, status
from supabase import Client

from app.models.billing import (
    CdnCreateInput,
    CdnNoteType,
    CdnReason,
    CdnUpdateInput,
    InvoiceLineItemInput,
)
from app.services.billing.invoice_service import (
    calculate_line_item_tax,
    get_invoice_detail,
)
from app.services.billing.irp_submission_service import (
    _assert_access,
    build_irp_payload,
    get_client_credentials,
    get_valid_session_token,
    normalize_gstin,
    einvoice_client,
    EinvoiceClientError,
    EinvoiceDownError,
    EinvoiceAuthError,
)

logger = logging.getLogger(__name__)


def _generate_next_cdn_number(db: Client, company_profile_id: str) -> str:
    """Generate next atomic CDN number using company profile sequence."""
    cp_res = (
        db.table("billing_company_profiles")
        .select("cdn_number_prefix, cdn_number_next_seq")
        .eq("id", company_profile_id)
        .limit(1)
        .execute()
    )
    if not cp_res.data:
        prefix = "CRN/"
        seq = 1
    else:
        cp = cp_res.data[0]
        prefix = cp.get("cdn_number_prefix") or "CRN/"
        seq = cp.get("cdn_number_next_seq") or 1

    next_seq = seq + 1
    db.table("billing_company_profiles").update(
        {"cdn_number_next_seq": next_seq, "updated_at": datetime.now().isoformat()}
    ).eq("id", company_profile_id).execute()

    return f"{prefix}{seq:07d}"


def create_credit_debit_note(
    db: Client, payload: CdnCreateInput, user_or_id: Any
) -> Dict[str, Any]:
    """Create a draft Credit Note or Debit Note linked to an original invoice.
    
    CRITICAL RULE: Rejects creation if original invoice is not registered on IRP!
    """
    _assert_access(db, payload.client_gstin_id, user_or_id)

    # 1. Fetch & validate original invoice
    orig_inv_res = (
        db.table("billing_invoices")
        .select("*")
        .eq("id", payload.original_invoice_id)
        .eq("client_gstin_id", payload.client_gstin_id)
        .limit(1)
        .execute()
    )
    if not orig_inv_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original invoice not found for this client GSTIN.",
        )

    orig_inv = orig_inv_res.data[0]
    irp_status_str = str(orig_inv.get("irp_status") or "").lower()
    has_irn = bool(orig_inv.get("irn"))

    # Strictly reject if invoice is not IRP-registered
    if not (irp_status_str == "irp_registered" or has_irn):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credit Notes or Debit Notes can only be issued against invoices that have been registered on IRP (irp_registered).",
        )

    # 2. Compute CDN line item taxes reusing invoice_service tax logic
    computed_lines = [calculate_line_item_tax(line, orig_inv["is_interstate"]) for line in payload.line_items]
    subtotal_paise = sum(item["taxable_value_paise"] for item in computed_lines)
    total_tax_paise = sum(
        item["cgst_paise"] + item["sgst_paise"] + item["igst_paise"] + item["cess_paise"]
        for item in computed_lines
    )
    total_paise = sum(item["line_total_paise"] for item in computed_lines)

    # 3. Generate separate CDN number sequence
    note_number = _generate_next_cdn_number(db, orig_inv["company_profile_id"])

    cdn_data = {
        "client_gstin_id": payload.client_gstin_id,
        "original_invoice_id": payload.original_invoice_id,
        "note_type": payload.note_type.value,
        "note_number": note_number,
        "note_date": payload.note_date.isoformat(),
        "reason": payload.reason.value,
        "reason_detail": payload.reason_detail,
        "subtotal_paise": subtotal_paise,
        "total_tax_paise": total_tax_paise,
        "total_paise": total_paise,
        "status": "draft",
        "notes": payload.notes,
    }

    cdn_res = db.table("billing_credit_debit_notes").insert(cdn_data).execute()
    new_cdn = cdn_res.data[0]
    cdn_id = new_cdn["id"]

    for line in computed_lines:
        line["cdn_id"] = cdn_id
    lines_res = db.table("billing_cdn_line_items").insert(computed_lines).execute()

    return get_cdn_detail(db, cdn_id, payload.client_gstin_id, user_or_id)


def list_cdns(
    db: Client,
    client_gstin_id: str,
    original_invoice_id: Optional[str] = None,
    user_or_id: Any = None,
) -> List[Dict[str, Any]]:
    """List Credit Notes / Debit Notes for a client GSTIN."""
    if user_or_id:
        _assert_access(db, client_gstin_id, user_or_id)

    query = db.table("billing_credit_debit_notes").select("*").eq("client_gstin_id", client_gstin_id)
    if original_invoice_id:
        query = query.eq("original_invoice_id", original_invoice_id)

    res = query.order("created_at", desc=True).execute()
    return res.data or []


def get_cdn_detail(
    db: Client, cdn_id: str, client_gstin_id: str, user_or_id: Any = None
) -> Dict[str, Any]:
    """Get full CDN details including line items, original invoice, seller, and buyer."""
    if user_or_id:
        _assert_access(db, client_gstin_id, user_or_id)

    cdn_res = (
        db.table("billing_credit_debit_notes")
        .select("*")
        .eq("id", cdn_id)
        .eq("client_gstin_id", client_gstin_id)
        .limit(1)
        .execute()
    )
    if not cdn_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credit/Debit note not found.",
        )

    cdn = cdn_res.data[0]

    lines_res = (
        db.table("billing_cdn_line_items")
        .select("*")
        .eq("cdn_id", cdn_id)
        .execute()
    )
    cdn["line_items"] = lines_res.data or []

    # Include original invoice details
    orig_detail = get_invoice_detail(db, cdn["original_invoice_id"], client_gstin_id)
    cdn["original_invoice"] = orig_detail
    cdn["company_profile"] = orig_detail.get("company_profile")
    cdn["customer"] = orig_detail.get("customer")

    return cdn


def update_cdn(
    db: Client,
    cdn_id: str,
    client_gstin_id: str,
    payload: CdnUpdateInput,
    user_or_id: Any,
) -> Dict[str, Any]:
    """Edit draft CDN. Rejects edit if status is not draft."""
    _assert_access(db, client_gstin_id, user_or_id)

    existing_cdn = get_cdn_detail(db, cdn_id, client_gstin_id)
    if existing_cdn["status"] != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only draft Credit/Debit notes can be edited.",
        )

    update_dict: Dict[str, Any] = {"updated_at": datetime.now().isoformat()}
    if payload.note_type is not None:
        update_dict["note_type"] = payload.note_type.value
    if payload.reason is not None:
        update_dict["reason"] = payload.reason.value
    if payload.reason_detail is not None:
        update_dict["reason_detail"] = payload.reason_detail
    if payload.note_date is not None:
        update_dict["note_date"] = payload.note_date.isoformat()
    if payload.notes is not None:
        update_dict["notes"] = payload.notes

    if payload.line_items is not None:
        is_interstate = existing_cdn["original_invoice"]["is_interstate"]
        computed_lines = [calculate_line_item_tax(line, is_interstate) for line in payload.line_items]
        update_dict["subtotal_paise"] = sum(item["taxable_value_paise"] for item in computed_lines)
        update_dict["total_tax_paise"] = sum(
            item["cgst_paise"] + item["sgst_paise"] + item["igst_paise"] + item["cess_paise"]
            for item in computed_lines
        )
        update_dict["total_paise"] = sum(item["line_total_paise"] for item in computed_lines)

        db.table("billing_cdn_line_items").delete().eq("cdn_id", cdn_id).execute()
        for line in computed_lines:
            line["cdn_id"] = cdn_id
        db.table("billing_cdn_line_items").insert(computed_lines).execute()

    db.table("billing_credit_debit_notes").update(update_dict).eq("id", cdn_id).execute()
    return get_cdn_detail(db, cdn_id, client_gstin_id)


def finalize_cdn(
    db: Client, cdn_id: str, client_gstin_id: str, user_or_id: Any
) -> Dict[str, Any]:
    """Finalize CDN (locks editing)."""
    _assert_access(db, client_gstin_id, user_or_id)

    cdn = get_cdn_detail(db, cdn_id, client_gstin_id)
    if cdn["status"] == "finalized":
        return cdn
    if cdn["status"] != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot finalize CDN in '{cdn['status']}' status.",
        )

    db.table("billing_credit_debit_notes").update(
        {"status": "finalized", "updated_at": datetime.now().isoformat()}
    ).eq("id", cdn_id).execute()

    return get_cdn_detail(db, cdn_id, client_gstin_id)


def submit_cdn_to_irp(
    db: Client, cdn_id: str, client_gstin_id: str, user_or_id: Any
) -> Dict[str, Any]:
    """Submit finalized Credit/Debit note to Sandbox IRP portal for IRN generation."""
    _assert_access(db, client_gstin_id, user_or_id)

    cdn = get_cdn_detail(db, cdn_id, client_gstin_id)
    if cdn["status"] != "finalized":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CDN must be finalized before submitting to IRP.",
        )

    company = cdn["company_profile"]
    customer = cdn["customer"]
    lines = cdn["line_items"]

    # DocType: CRN or DBN
    doc_type = "CRN" if cdn["note_type"] == "credit" else "DBN"

    # Adapt invoice structure for IRP payload builder
    inv_adapter = {
        "invoice_number": cdn["note_number"],
        "invoice_date": cdn["note_date"],
        "place_of_supply": cdn["original_invoice"]["place_of_supply"],
        "subtotal_paise": cdn["subtotal_paise"],
        "total_paise": cdn["total_paise"],
    }
    payload_json = build_irp_payload(inv_adapter, company, customer, lines)
    payload_json["DocDtls"]["Typ"] = doc_type

    # Credentials & Session Token
    username, password = get_client_credentials(db, client_gstin_id)
    auth_token = get_valid_session_token(username, password)

    try:
        resp = einvoice_client.generate_irn(auth_token, payload_json)
        irn = resp.get("Irn")
        ack_no = resp.get("AckNo")
        ack_dt = resp.get("AckDt")
        qr_code = resp.get("SignedQRCode")

        update_data = {
            "irn": irn,
            "irn_ack_number": str(ack_no) if ack_no else None,
            "irn_ack_date": ack_dt,
            "irn_qr_code": qr_code,
            "irn_signed_json": resp,
            "irp_status": "irp_registered",
            "irp_error_detail": None,
            "updated_at": datetime.now().isoformat(),
        }
        db.table("billing_credit_debit_notes").update(update_data).eq("id", cdn_id).execute()
    except (EinvoiceClientError, EinvoiceAuthError, EinvoiceDownError) as exc:
        db.table("billing_credit_debit_notes").update(
            {"irp_status": "irp_rejected", "irp_error_detail": str(exc), "updated_at": datetime.now().isoformat()}
        ).eq("id", cdn_id).execute()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"IRP Submission Failed: {exc}")

    return get_cdn_detail(db, cdn_id, client_gstin_id)
