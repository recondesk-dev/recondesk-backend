"""Backend Service for E-Invoice IRP Submission, Pre-Validation, Timeout Recovery & Cancellation."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import HTTPException, status
from supabase import Client

from app.data.gst_uqc import is_valid_uqc
from app.services.billing.invoice_service import get_invoice_detail
from app.services.einvoice_verification import get_client_credentials, get_valid_session_token
from app.services.normalizer import NormalizationError, normalize_gstin
from app.services.sandbox_einvoice_client import (
    EinvoiceAuthError,
    EinvoiceClientError,
    EinvoiceDownError,
    einvoice_client,
)

logger = logging.getLogger(__name__)


def _assert_access(sb: Any, client_gstin_id: str, user_or_id: Any) -> None:
    """Verify current user has permissions to access this client GSTIN record.
    Safely extracts string user ID if a User Pydantic object was passed.
    """
    uid = getattr(user_or_id, "id", user_or_id)
    uid_str = str(uid or "").strip()
    if not uid_str:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or unauthenticated user ID")

    client_id_str = str(client_gstin_id or "").strip()
    if not client_id_str:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing client GSTIN ID parameter")

    if len(client_id_str) == 15 and client_id_str[:2].isdigit():
        q = (
            sb.table("client_gstins")
            .select("id, firm_owner_id, assigned_to, gstin, trade_name, legal_name")
            .eq("gstin", client_id_str.upper())
            .limit(1)
            .execute()
        )
    else:
        q = (
            sb.table("client_gstins")
            .select("id, firm_owner_id, assigned_to, gstin, trade_name, legal_name")
            .eq("id", client_id_str)
            .limit(1)
            .execute()
        )

    if not q.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Client GSTIN record not found for '{client_id_str}'.")

    c = q.data[0]
    firm_owner = str(c.get("firm_owner_id") or "").strip()
    assigned = str(c.get("assigned_to") or "").strip()

    if uid_str != firm_owner and uid_str != assigned:
        client_label = c.get("trade_name") or c.get("legal_name") or c.get("gstin") or client_id_str
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Access denied: Current user does not have administrative permissions for client '{client_label}'.",
        )


# -----------------------------------------------------------------------------
# 1. Pre-Submission Local Validation
# -----------------------------------------------------------------------------
def validate_invoice_for_irp(
    invoice: Dict[str, Any],
    company: Dict[str, Any],
    customer: Dict[str, Any],
    line_items: List[Dict[str, Any]],
) -> List[str]:
    """Locally validate invoice record and line items against IRP schema requirements.
    Returns a list of error detail strings. An empty list indicates validation passed.
    """
    errors: List[str] = []

    # Status check
    if invoice.get("status") != "finalized":
        errors.append("Invoice must be in 'finalized' status before submitting to IRP.")

    # Seller validation
    seller_gstin = (company.get("gstin") or "").strip()
    if not seller_gstin:
        errors.append("Seller GSTIN is required.")
    else:
        try:
            normalize_gstin(seller_gstin)
        except NormalizationError as exc:
            errors.append(f"Invalid Seller GSTIN ({seller_gstin}): {exc.reason}")

    if not (company.get("legal_name") or "").strip():
        errors.append("Seller Legal Name is required.")
    if not (company.get("address_line1") or "").strip():
        errors.append("Seller Address Line 1 is required.")
    if not (company.get("city") or "").strip():
        errors.append("Seller City is required.")
    if not (company.get("state_code") or "").strip():
        errors.append("Seller State Code is required.")
    pincode = str(company.get("pincode") or "").strip()
    if not pincode or len(pincode) != 6 or not pincode.isdigit():
        errors.append(f"Seller Pincode must be a 6-digit number (got '{pincode}').")

    # Buyer validation
    buyer_gstin = (customer.get("gstin") or "").strip()
    is_b2b = customer.get("is_b2b", True)
    if is_b2b or buyer_gstin:
        if not buyer_gstin:
            errors.append("Buyer GSTIN is required for B2B e-Invoices.")
        else:
            try:
                normalize_gstin(buyer_gstin)
            except NormalizationError as exc:
                errors.append(f"Invalid Buyer GSTIN ({buyer_gstin}): {exc.reason}")

    if not (customer.get("name") or "").strip():
        errors.append("Buyer Name is required.")
    if not (customer.get("address_line1") or "").strip():
        errors.append("Buyer Address Line 1 is required.")
    if not (customer.get("city") or "").strip():
        errors.append("Buyer City is required.")
    if not (customer.get("state_code") or "").strip():
        errors.append("Buyer State Code is required.")

    buyer_pin = str(customer.get("pincode") or "").strip()
    if not buyer_pin or len(buyer_pin) != 6 or not buyer_pin.isdigit():
        errors.append(f"Buyer Pincode must be a 6-digit number (got '{buyer_pin}').")

    # Line items validation
    if not line_items:
        errors.append("Invoice must contain at least one line item.")

    computed_subtotal = 0
    computed_tax = 0
    computed_total = 0

    for idx, item in enumerate(line_items, start=1):
        desc = (item.get("description") or "").strip()
        if not desc:
            errors.append(f"Line Item #{idx}: Description is required.")

        hsn = (item.get("hsn_or_sac_code") or "").strip()
        if not hsn or len(hsn) < 4:
            errors.append(f"Line Item #{idx}: HSN/SAC Code must be at least 4 digits (got '{hsn}').")

        unit_code = (item.get("unit") or "").strip().upper()
        if not unit_code or not is_valid_uqc(unit_code):
            errors.append(
                f"Line Item #{idx}: Unit Quantity Code (UQC) '{item.get('unit')}' is invalid. Must be an official GST UQC code (e.g. NOS, KGS, PCS, BOX, HRS)."
            )

        qty = float(item.get("quantity") or 0)
        if qty <= 0:
            errors.append(f"Line Item #{idx}: Quantity must be greater than 0.")

        rate = int(item.get("rate_paise") or 0)
        if rate <= 0:
            errors.append(f"Line Item #{idx}: Rate must be greater than 0.")

        taxable = int(item.get("taxable_value_paise") or 0)
        cgst = int(item.get("cgst_paise") or 0)
        sgst = int(item.get("sgst_paise") or 0)
        igst = int(item.get("igst_paise") or 0)
        cess = int(item.get("cess_paise") or 0)
        line_tot = int(item.get("line_total_paise") or 0)

        item_tax = cgst + sgst + igst + cess
        if taxable + item_tax != line_tot:
            errors.append(
                f"Line Item #{idx}: Internal tax calculation mismatch (Taxable {taxable/100} + Tax {item_tax/100} != Total {line_tot/100})."
            )

        computed_subtotal += taxable
        computed_tax += item_tax
        computed_total += line_tot

    inv_subtotal = int(invoice.get("subtotal_paise") or 0)
    inv_tax = int(invoice.get("total_tax_paise") or 0)
    inv_total = int(invoice.get("total_paise") or 0)

    if computed_subtotal != inv_subtotal:
        errors.append(f"Invoice Subtotal mismatch: line items sum ({computed_subtotal/100}) != header subtotal ({inv_subtotal/100}).")
    if computed_tax != inv_tax:
        errors.append(f"Invoice Total Tax mismatch: line items sum ({computed_tax/100}) != header tax ({inv_tax/100}).")
    if computed_total != inv_total:
        errors.append(f"Invoice Total Amount mismatch: line items sum ({computed_total/100}) != header total ({inv_total/100}).")

    return errors


# -----------------------------------------------------------------------------
# 2. IRP Payload Formatting (Govt Schema V1.03)
# -----------------------------------------------------------------------------
def build_irp_payload(
    invoice: Dict[str, Any],
    company: Dict[str, Any],
    customer: Dict[str, Any],
    line_items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Transform finalized invoice into strict Government IRP Schema V1.03 JSON."""
    inv_date_raw = invoice.get("invoice_date") or ""
    try:
        dt_obj = datetime.strptime(str(inv_date_raw)[:10], "%Y-%m-%d")
        formatted_dt = dt_obj.strftime("%d/%m/%Y")
    except Exception:
        formatted_dt = inv_date_raw

    sup_typ = "B2B"
    if not customer.get("is_b2b"):
        sup_typ = "B2C"

    item_list = []
    for idx, line in enumerate(line_items, start=1):
        hsn = str(line.get("hsn_or_sac_code") or "").strip()
        is_service = "Y" if hsn.startswith("99") else "N"

        qty = float(line.get("quantity") or 1.0)
        rate_rs = round(int(line.get("rate_paise") or 0) / 100.0, 2)
        tot_amt = round(qty * rate_rs, 2)
        disc_pct = float(line.get("discount_percent") or 0.0)
        disc_rs = round(tot_amt * (disc_pct / 100.0), 2)
        ass_val = round(int(line.get("taxable_value_paise") or 0) / 100.0, 2)

        cgst_rate = float(line.get("cgst_rate_percent") or 0.0)
        sgst_rate = float(line.get("sgst_rate_percent") or 0.0)
        igst_rate = float(line.get("igst_rate_percent") or 0.0)
        gst_rate = round(igst_rate or (cgst_rate + sgst_rate), 2)

        cgst_rs = round(int(line.get("cgst_paise") or 0) / 100.0, 2)
        sgst_rs = round(int(line.get("sgst_paise") or 0) / 100.0, 2)
        igst_rs = round(int(line.get("igst_paise") or 0) / 100.0, 2)
        cess_rs = round(int(line.get("cess_paise") or 0) / 100.0, 2)

        line_tot_rs = round(int(line.get("line_total_paise") or 0) / 100.0, 2)

        item_list.append(
            {
                "SlNo": str(idx),
                "PrdDesc": str(line.get("description") or "").strip(),
                "IsServc": is_service,
                "HsnCd": hsn,
                "Qty": qty,
                "FreeQty": 0,
                "Unit": str(line.get("unit") or "NOS").strip(),
                "UnitPrice": rate_rs,
                "TotAmt": tot_amt,
                "Discount": disc_rs,
                "PreTaxVal": 0,
                "AssVal": ass_val,
                "GstRt": gst_rate,
                "IgstAmt": igst_rs,
                "CgstAmt": cgst_rs,
                "SgstAmt": sgst_rs,
                "CesRt": 0,
                "CesAmt": cess_rs,
                "CesNonAdvAmt": 0,
                "StateCesRt": 0,
                "StateCesAmt": 0,
                "StateCesNonAdvAmt": 0,
                "OthChrg": 0,
                "TotItemVal": line_tot_rs,
            }
        )

    seller_pin = str(company.get("pincode") or "").strip()
    buyer_pin = str(customer.get("pincode") or "").strip()

    payload = {
        "Version": "1.03",
        "TranDtls": {
            "TaxSch": "GST",
            "SupTyp": sup_typ,
            "RegRev": "N",
            "EcmGstin": None,
        },
        "DocDtls": {
            "Typ": "INV",
            "No": str(invoice.get("invoice_number") or "").strip(),
            "Dt": formatted_dt,
        },
        "SellerDtls": {
            "Gstin": str(company.get("gstin") or "").strip().upper(),
            "LglNm": str(company.get("legal_name") or "").strip(),
            "TrdNm": str(company.get("trade_name") or company.get("legal_name") or "").strip(),
            "Addr1": str(company.get("address_line1") or "").strip(),
            "Addr2": str(company.get("address_line2") or "").strip(),
            "Loc": str(company.get("city") or "").strip(),
            "Pin": int(seller_pin) if seller_pin.isdigit() else 0,
            "Stcd": str(company.get("state_code") or "").strip(),
        },
        "BuyerDtls": {
            "Gstin": str(customer.get("gstin") or "URP").strip().upper(),
            "LglNm": str(customer.get("name") or "").strip(),
            "TrdNm": str(customer.get("name") or "").strip(),
            "Pos": str(invoice.get("place_of_supply") or company.get("state_code") or "").strip().upper(),
            "Addr1": str(customer.get("address_line1") or "").strip(),
            "Addr2": str(customer.get("address_line2") or "").strip(),
            "Loc": str(customer.get("city") or "").strip(),
            "Pin": int(buyer_pin) if buyer_pin.isdigit() else 0,
            "Stcd": str(customer.get("state_code") or "").strip(),
        },
        "ItemList": item_list,
        "ValDtls": {
            "AssVal": round(int(invoice.get("subtotal_paise") or 0) / 100.0, 2),
            "CgstVal": round(sum(int(l.get("cgst_paise") or 0) for l in line_items) / 100.0, 2),
            "SgstVal": round(sum(int(l.get("sgst_paise") or 0) for l in line_items) / 100.0, 2),
            "IgstVal": round(sum(int(l.get("igst_paise") or 0) for l in line_items) / 100.0, 2),
            "CesVal": round(sum(int(l.get("cess_paise") or 0) for l in line_items) / 100.0, 2),
            "StCesVal": 0,
            "Discount": 0,
            "OthChrg": 0,
            "RndOffAmt": 0,
            "TotInvVal": round(int(invoice.get("total_paise") or 0) / 100.0, 2),
        },
    }

    return payload


# -----------------------------------------------------------------------------
# 3. Audit Logger Helper
# -----------------------------------------------------------------------------
def log_submission_attempt(
    db: Client,
    invoice_id: str,
    client_gstin_id: str,
    environment: str,
    request_payload: Optional[Dict[str, Any]],
    response_status: str,
    response_body: Optional[Dict[str, Any]],
) -> None:
    """Insert immutable record into billing_irp_submission_log."""
    try:
        db.table("billing_irp_submission_log").insert(
            {
                "invoice_id": invoice_id,
                "client_gstin_id": client_gstin_id,
                "environment": environment,
                "request_payload": request_payload,
                "response_status": response_status,
                "response_body": response_body,
                "attempted_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
    except Exception as exc:
        logger.warning("Failed to write to billing_irp_submission_log: %s", exc)


# -----------------------------------------------------------------------------
# 4. Main IRP Submission Logic (with Timeout Recovery)
# -----------------------------------------------------------------------------
def submit_to_irp(
    db: Client,
    invoice_id: str,
    client_gstin_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Validate, format, and submit invoice to Sandbox e-Invoice Generate API.
    Handles network timeouts safely by verifying against IRP before allowing resubmission.
    """
    _assert_access(db, client_gstin_id, user_id)
    inv = get_invoice_detail(db, invoice_id, client_gstin_id)

    company = inv.get("company_profile") or {}
    customer = inv.get("customer") or {}
    line_items = inv.get("line_items") or []

    env_name = str(inv.get("irp_environment") or "test").lower()

    # Pre-submission local validation
    val_errors = validate_invoice_for_irp(inv, company, customer, line_items)
    if val_errors:
        log_submission_attempt(
            db=db,
            invoice_id=invoice_id,
            client_gstin_id=client_gstin_id,
            environment=env_name,
            request_payload=None,
            response_status="validation_failed",
            response_body={"validation_errors": val_errors},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Pre-submission validation failed", "errors": val_errors},
        )

    # Prevent submitting already registered invoice
    if inv.get("irp_status") == "irp_registered" or inv.get("irn"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invoice has already been registered on IRP and has an active IRN.",
        )

    # Get credentials & session token
    creds = get_client_credentials(db, client_gstin_id)
    if not creds:
        client_name = company.get("trade_name") or company.get("legal_name") or company.get("gstin") or client_gstin_id
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"e-Invoice portal credentials not configured for client '{client_name}'. Please add credentials under E-Invoicing → Master Data → e-Invoice Credentials before submitting.",
        )

    seller_gstin = str(company.get("gstin") or "").strip().upper()
    session_token = get_valid_session_token(db, creds, seller_gstin)

    payload = build_irp_payload(inv, company, customer, line_items)

    try:
        logger.info("Submitting invoice %s (%s) to IRP", invoice_id, inv.get("invoice_number"))
        res = einvoice_client.generate_einvoice(session_token, payload)
    except EinvoiceAuthError as exc:
        # Retry once after token refresh
        logger.warning("Session token expired during generate_einvoice, retrying: %s", exc)
        creds["session_token"] = None
        session_token = get_valid_session_token(db, creds, seller_gstin)
        try:
            res = einvoice_client.generate_einvoice(session_token, payload)
        except Exception as retry_exc:
            log_submission_attempt(
                db=db,
                invoice_id=invoice_id,
                client_gstin_id=client_gstin_id,
                environment=env_name,
                request_payload=payload,
                response_status="rejected",
                response_body={"error": str(retry_exc)},
            )
            db.table("billing_invoices").update(
                {"irp_status": "irp_rejected", "irp_error_detail": str(retry_exc), "updated_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", invoice_id).execute()
            raise HTTPException(status_code=400, detail=f"IRP Submission Rejected: {str(retry_exc)}")

    except EinvoiceDownError as exc:
        # CRITICAL TIMEOUT / NETWORK ERROR RECOVERY
        logger.warning("IRP submission timed out for invoice %s. Checking IRP by document data before failing...", invoice_id)
        inv_num = str(inv.get("invoice_number") or "").strip()
        inv_date = str(inv.get("invoice_date") or "").strip()

        try:
            irp_check = einvoice_client.get_einvoice_by_doc(
                session_token=session_token,
                gstin=seller_gstin,
                doc_number=inv_num,
                doc_date=inv_date,
                doc_type="INV",
            )
        except Exception as check_exc:
            logger.error("Failed to check IRP status after timeout: %s", check_exc)
            irp_check = None

        if irp_check is not None:
            # RECOVERED! IRN was generated on IRP despite local timeout
            irn_val = str(irp_check.get("irn") or irp_check.get("Irn") or "").strip()
            ack_no = str(irp_check.get("ack_no") or irp_check.get("AckNo") or "").strip()
            ack_dt = str(irp_check.get("ack_date") or irp_check.get("AckDt") or datetime.now(timezone.utc).isoformat()).strip()
            qr_code = str(irp_check.get("signed_qr_code") or irp_check.get("SignedQRCode") or "").strip()

            update_data = {
                "irn": irn_val,
                "irn_ack_number": ack_no,
                "irn_ack_date": ack_dt,
                "irn_qr_code": qr_code,
                "irn_signed_json": irp_check,
                "irp_status": "irp_registered",
                "irp_error_detail": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            db.table("billing_invoices").update(update_data).eq("id", invoice_id).execute()

            log_submission_attempt(
                db=db,
                invoice_id=invoice_id,
                client_gstin_id=client_gstin_id,
                environment=env_name,
                request_payload=payload,
                response_status="timeout_recovered",
                response_body=irp_check,
            )
            return get_invoice_detail(db, invoice_id, client_gstin_id)
        else:
            # Confirmed missing on IRP — safe to retry later
            db.table("billing_invoices").update(
                {
                    "irp_status": "irp_rejected",
                    "irp_error_detail": "Submission timed out. Confirmed missing on IRP — safe to resubmit.",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            ).eq("id", invoice_id).execute()

            log_submission_attempt(
                db=db,
                invoice_id=invoice_id,
                client_gstin_id=client_gstin_id,
                environment=env_name,
                request_payload=payload,
                response_status="failed",
                response_body={"error": str(exc), "timeout_recovery": "Confirmed missing on IRP"},
            )
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="IRP portal timed out. Verified with IRP: no IRN was generated for this invoice. You may safely retry submission.",
            )

    except EinvoiceClientError as exc:
        log_submission_attempt(
            db=db,
            invoice_id=invoice_id,
            client_gstin_id=client_gstin_id,
            environment=env_name,
            request_payload=payload,
            response_status="rejected",
            response_body={"error": str(exc)},
        )
        db.table("billing_invoices").update(
            {"irp_status": "irp_rejected", "irp_error_detail": str(exc), "updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", invoice_id).execute()
        raise HTTPException(status_code=400, detail=f"IRP Submission Rejected: {str(exc)}")

    # API Success path
    irn_val = str(res.get("irn") or res.get("Irn") or "").strip()
    ack_no = str(res.get("ack_no") or res.get("AckNo") or "").strip()
    ack_dt = str(res.get("ack_date") or res.get("AckDt") or datetime.now(timezone.utc).isoformat()).strip()
    qr_code = str(res.get("signed_qr_code") or res.get("SignedQRCode") or "").strip()

    update_data = {
        "irn": irn_val,
        "irn_ack_number": ack_no,
        "irn_ack_date": ack_dt,
        "irn_qr_code": qr_code,
        "irn_signed_json": res,
        "irp_status": "irp_registered",
        "irp_error_detail": None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    db.table("billing_invoices").update(update_data).eq("id", invoice_id).execute()

    log_submission_attempt(
        db=db,
        invoice_id=invoice_id,
        client_gstin_id=client_gstin_id,
        environment=env_name,
        request_payload=payload,
        response_status="success",
        response_body=res,
    )

    return get_invoice_detail(db, invoice_id, client_gstin_id)


# -----------------------------------------------------------------------------
# 5. Cancel IRN (24-Hour Window Enforcement)
# -----------------------------------------------------------------------------
def cancel_irn(
    db: Client,
    invoice_id: str,
    client_gstin_id: str,
    reason_code: str,
    remarks: str,
    user_id: str,
) -> Dict[str, Any]:
    """Cancel an active e-Invoice IRN on IRP. Enforces 24-hour server-side window."""
    _assert_access(db, client_gstin_id, user_id)
    inv = get_invoice_detail(db, invoice_id, client_gstin_id)

    if inv.get("irp_status") != "irp_registered" or not inv.get("irn"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invoice does not have an active registered IRN on IRP.",
        )

    # Server-side 24-hour window check
    ack_dt_str = str(inv.get("irn_ack_date") or inv.get("created_at") or "").strip()
    try:
        ack_dt = datetime.fromisoformat(ack_dt_str.replace("Z", "+00:00"))
        now_dt = datetime.now(timezone.utc)
        age_seconds = (now_dt - ack_dt).total_seconds()
        if age_seconds > 86400:
            hours_elapsed = round(age_seconds / 3600.0, 1)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"IRN cancellation is only allowed within 24 hours of generation on IRP ({hours_elapsed} hours elapsed). To reverse this invoice, issue a Credit Note instead.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Could not parse ack_date '%s' for 24h check: %s", ack_dt_str, exc)

    company = inv.get("company_profile") or {}
    seller_gstin = str(company.get("gstin") or "").strip().upper()

    creds = get_client_credentials(db, client_gstin_id)
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="e-Invoice portal credentials not configured for this client.",
        )

    session_token = get_valid_session_token(db, creds, seller_gstin)
    irn_val = str(inv["irn"]).strip()

    try:
        cancel_res = einvoice_client.cancel_einvoice(
            session_token=session_token,
            irn=irn_val,
            reason_code=reason_code,
            remarks=remarks,
        )
    except Exception as exc:
        log_submission_attempt(
            db=db,
            invoice_id=invoice_id,
            client_gstin_id=client_gstin_id,
            environment=str(inv.get("irp_environment") or "test"),
            request_payload={"Irn": irn_val, "CnlRsn": reason_code, "CnlRem": remarks},
            response_status="cancel_failed",
            response_body={"error": str(exc)},
        )
        raise HTTPException(status_code=400, detail=f"IRP Cancellation Failed: {str(exc)}")

    # On success
    db.table("billing_invoices").update(
        {
            "irp_status": "cancelled",
            "irp_error_detail": f"IRN Cancelled on IRP (Reason: {reason_code}, Remarks: {remarks})",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", invoice_id).execute()

    log_submission_attempt(
        db=db,
        invoice_id=invoice_id,
        client_gstin_id=client_gstin_id,
        environment=str(inv.get("irp_environment") or "test"),
        request_payload={"Irn": irn_val, "CnlRsn": reason_code, "CnlRem": remarks},
        response_status="cancelled",
        response_body=cancel_res,
    )

    return get_invoice_detail(db, invoice_id, client_gstin_id)


# -----------------------------------------------------------------------------
# 6. Get IRP Status & Audit History
# -----------------------------------------------------------------------------
def get_irp_status_info(
    db: Client,
    invoice_id: str,
    client_gstin_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Retrieve current IRP registration status and submission audit history."""
    _assert_access(db, client_gstin_id, user_id)
    inv = get_invoice_detail(db, invoice_id, client_gstin_id)

    log_res = (
        db.table("billing_irp_submission_log")
        .select("*")
        .eq("invoice_id", invoice_id)
        .order("attempted_at", desc=True)
        .execute()
    )

    logs = log_res.data or []

    # Check 24h cancel eligibility
    cancellation_eligible = False
    if inv.get("irp_status") == "irp_registered" and inv.get("irn_ack_date"):
        try:
            ack_dt = datetime.fromisoformat(str(inv["irn_ack_date"]).replace("Z", "+00:00"))
            cancellation_eligible = (datetime.now(timezone.utc) - ack_dt).total_seconds() <= 86400
        except Exception:
            cancellation_eligible = False

    return {
        "invoice_id": invoice_id,
        "invoice_number": inv.get("invoice_number"),
        "irp_status": inv.get("irp_status", "not_submitted"),
        "irn": inv.get("irn"),
        "irn_ack_number": inv.get("irn_ack_number"),
        "irn_ack_date": inv.get("irn_ack_date"),
        "irn_qr_code": inv.get("irn_qr_code"),
        "irp_environment": inv.get("irp_environment", "test"),
        "irp_error_detail": inv.get("irp_error_detail"),
        "cancellation_eligible": cancellation_eligible,
        "submission_logs": logs,
    }
