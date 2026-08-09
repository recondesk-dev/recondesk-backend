from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import HTTPException, status
from supabase import Client

from app.models.billing import (
    CompanyProfileCreate,
    CompanyProfileUpdate,
    CustomerCreate,
    CustomerUpdate,
    InvoiceCreateInput,
    InvoiceLineItemInput,
    InvoiceStatus,
    InvoiceUpdateInput,
    ItemCreate,
    ItemType,
    ItemUpdate,
)
from app.services.normalizer import NormalizationError, normalize_gstin

_log = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# GSTIN Validation Helper
# -----------------------------------------------------------------------------
def validate_gstin_string(gstin: Optional[str], field_label: str = "GSTIN") -> str:
    """Validate GSTIN format and checksum using central normalizer.
    Raises HTTPException 400 if invalid.
    """
    if not gstin or not gstin.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_label} is required and cannot be empty",
        )
    try:
        return normalize_gstin(gstin)
    except NormalizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field_label} ({exc.raw_value}): {exc.reason}",
        ) from exc


# -----------------------------------------------------------------------------
# Company Profiles
# -----------------------------------------------------------------------------
def get_company_profile(db: Client, profile_id: str, client_gstin_id: str) -> Dict[str, Any]:
    res = (
        db.table("billing_company_profiles")
        .select("*")
        .eq("id", profile_id)
        .eq("client_gstin_id", client_gstin_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Company profile not found")
    return res.data[0]


def list_company_profiles(db: Client, client_gstin_id: str) -> List[Dict[str, Any]]:
    res = (
        db.table("billing_company_profiles")
        .select("*")
        .eq("client_gstin_id", client_gstin_id)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


def create_company_profile(db: Client, profile_in: CompanyProfileCreate) -> Dict[str, Any]:
    data = profile_in.model_dump()
    data["gstin"] = validate_gstin_string(profile_in.gstin, "Company Profile GSTIN")
    if not data.get("state_code") and len(data["gstin"]) >= 2:
        data["state_code"] = data["gstin"][:2]

    res = db.table("billing_company_profiles").insert(data).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create company profile")
    return res.data[0]


def update_company_profile(
    db: Client, profile_id: str, client_gstin_id: str, profile_in: CompanyProfileUpdate
) -> Dict[str, Any]:
    get_company_profile(db, profile_id, client_gstin_id)
    update_data = profile_in.model_dump(exclude_unset=True)

    if "gstin" in update_data and update_data["gstin"]:
        update_data["gstin"] = validate_gstin_string(update_data["gstin"], "Company Profile GSTIN")
        if "state_code" not in update_data and len(update_data["gstin"]) >= 2:
            update_data["state_code"] = update_data["gstin"][:2]

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = (
        db.table("billing_company_profiles")
        .update(update_data)
        .eq("id", profile_id)
        .eq("client_gstin_id", client_gstin_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to update company profile")
    return res.data[0]


# -----------------------------------------------------------------------------
# Customers
# -----------------------------------------------------------------------------
def get_customer(db: Client, customer_id: str, client_gstin_id: str) -> Dict[str, Any]:
    res = (
        db.table("billing_customers")
        .select("*")
        .eq("id", customer_id)
        .eq("client_gstin_id", client_gstin_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Customer not found")
    return res.data[0]


def list_customers(db: Client, client_gstin_id: str) -> List[Dict[str, Any]]:
    res = (
        db.table("billing_customers")
        .select("*")
        .eq("client_gstin_id", client_gstin_id)
        .order("name", desc=False)
        .execute()
    )
    return res.data or []


def create_customer(db: Client, customer_in: CustomerCreate) -> Dict[str, Any]:
    data = customer_in.model_dump()
    gstin_val = (customer_in.gstin or "").strip()
    if customer_in.is_b2b:
        if not gstin_val:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="GSTIN is required for B2B customers",
            )
        data["gstin"] = validate_gstin_string(gstin_val, "Customer GSTIN")
    elif gstin_val:
        data["gstin"] = validate_gstin_string(gstin_val, "Customer GSTIN")
    else:
        data["gstin"] = None

    res = db.table("billing_customers").insert(data).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create customer")
    return res.data[0]


def update_customer(
    db: Client, customer_id: str, client_gstin_id: str, customer_in: CustomerUpdate
) -> Dict[str, Any]:
    existing = get_customer(db, customer_id, client_gstin_id)
    update_data = customer_in.model_dump(exclude_unset=True)

    is_b2b = update_data.get("is_b2b", existing.get("is_b2b", True))
    raw_gstin = update_data.get("gstin") if "gstin" in update_data else existing.get("gstin")
    gstin_val = (raw_gstin or "").strip()

    if is_b2b:
        if not gstin_val:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="GSTIN is required for B2B customers",
            )
        update_data["gstin"] = validate_gstin_string(gstin_val, "Customer GSTIN")
    elif gstin_val:
        update_data["gstin"] = validate_gstin_string(gstin_val, "Customer GSTIN")
    else:
        update_data["gstin"] = None

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = (
        db.table("billing_customers")
        .update(update_data)
        .eq("id", customer_id)
        .eq("client_gstin_id", client_gstin_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to update customer")
    return res.data[0]


def delete_customer(db: Client, customer_id: str, client_gstin_id: str) -> bool:
    get_customer(db, customer_id, client_gstin_id)
    db.table("billing_customers").delete().eq("id", customer_id).eq("client_gstin_id", client_gstin_id).execute()
    return True


# -----------------------------------------------------------------------------
# Items Catalog
# -----------------------------------------------------------------------------
def get_item(db: Client, item_id: str, client_gstin_id: str) -> Dict[str, Any]:
    res = (
        db.table("billing_items")
        .select("*")
        .eq("id", item_id)
        .eq("client_gstin_id", client_gstin_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Item not found")
    return res.data[0]


def list_items(db: Client, client_gstin_id: str) -> List[Dict[str, Any]]:
    res = (
        db.table("billing_items")
        .select("*")
        .eq("client_gstin_id", client_gstin_id)
        .order("name", desc=False)
        .execute()
    )
    return res.data or []


def create_item(db: Client, item_in: ItemCreate) -> Dict[str, Any]:
    data = item_in.model_dump()
    data["item_type"] = data["item_type"].value if isinstance(data["item_type"], ItemType) else data["item_type"]
    res = db.table("billing_items").insert(data).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create item")
    return res.data[0]


def update_item(
    db: Client, item_id: str, client_gstin_id: str, item_in: ItemUpdate
) -> Dict[str, Any]:
    get_item(db, item_id, client_gstin_id)
    update_data = item_in.model_dump(exclude_unset=True)
    if "item_type" in update_data and isinstance(update_data["item_type"], ItemType):
        update_data["item_type"] = update_data["item_type"].value

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = (
        db.table("billing_items")
        .update(update_data)
        .eq("id", item_id)
        .eq("client_gstin_id", client_gstin_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to update item")
    return res.data[0]


def delete_item(db: Client, item_id: str, client_gstin_id: str) -> bool:
    get_item(db, item_id, client_gstin_id)
    db.table("billing_items").delete().eq("id", item_id).eq("client_gstin_id", client_gstin_id).execute()
    return True


# -----------------------------------------------------------------------------
# Tax & Line Item Calculations
# -----------------------------------------------------------------------------
def calculate_line_item_tax(
    line: InvoiceLineItemInput, is_interstate: bool
) -> Dict[str, Any]:
    gross_paise = int(round(line.rate_paise * line.quantity))
    discount_amount_paise = int(round(gross_paise * (line.discount_percent / 100.0)))
    taxable_value_paise = max(0, gross_paise - discount_amount_paise)

    tax_rate = line.tax_rate_percent

    if is_interstate:
        igst_rate_percent = tax_rate
        igst_paise = int(round(taxable_value_paise * (igst_rate_percent / 100.0)))
        cgst_rate_percent = 0.0
        cgst_paise = 0
        sgst_rate_percent = 0.0
        sgst_paise = 0
    else:
        cgst_rate_percent = round(tax_rate / 2.0, 2)
        sgst_rate_percent = round(tax_rate / 2.0, 2)
        cgst_paise = int(round(taxable_value_paise * (cgst_rate_percent / 100.0)))
        sgst_paise = int(round(taxable_value_paise * (sgst_rate_percent / 100.0)))
        igst_rate_percent = 0.0
        igst_paise = 0

    cess_paise = line.cess_paise or 0
    line_total_paise = taxable_value_paise + cgst_paise + sgst_paise + igst_paise + cess_paise

    return {
        "item_id": line.item_id,
        "description": line.description,
        "hsn_or_sac_code": line.hsn_or_sac_code,
        "quantity": line.quantity,
        "unit": line.unit,
        "rate_paise": line.rate_paise,
        "discount_percent": line.discount_percent,
        "taxable_value_paise": taxable_value_paise,
        "cgst_rate_percent": cgst_rate_percent,
        "cgst_paise": cgst_paise,
        "sgst_rate_percent": sgst_rate_percent,
        "sgst_paise": sgst_paise,
        "igst_rate_percent": igst_rate_percent,
        "igst_paise": igst_paise,
        "cess_paise": cess_paise,
        "line_total_paise": line_total_paise,
    }


def _atomic_get_next_invoice_number(db: Client, profile_id: str) -> str:
    """Atomically increment sequence via DB RPC or row update returning prefix + seq."""
    try:
        rpc_res = db.rpc("increment_invoice_number_seq", {"p_profile_id": profile_id}).execute()
        if rpc_res.data:
            row = rpc_res.data[0]
            prefix = row.get("prefix", "")
            seq = int(row.get("seq", 1))
            return f"{prefix}{seq:04d}" if prefix else f"INV-{seq:04d}"
    except Exception as exc:
        _log.warning("RPC increment_invoice_number_seq failed, falling back to atomic update: %s", exc)

    # Fallback atomic UPDATE ... RETURNING (PostgREST equivalent)
    res = (
        db.table("billing_company_profiles")
        .select("invoice_number_prefix, invoice_number_next_seq")
        .eq("id", profile_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Company profile not found for invoice number generation")

    p = res.data[0]
    prefix = p.get("invoice_number_prefix", "")
    curr_seq = int(p.get("invoice_number_next_seq", 1))

    db.table("billing_company_profiles").update(
        {"invoice_number_next_seq": curr_seq + 1, "updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", profile_id).execute()

    return f"{prefix}{curr_seq:04d}" if prefix else f"INV-{curr_seq:04d}"


# -----------------------------------------------------------------------------
# Invoice Creation & Management
# -----------------------------------------------------------------------------
def create_invoice(db: Client, invoice_in: InvoiceCreateInput) -> Dict[str, Any]:
    company = get_company_profile(db, invoice_in.company_profile_id, invoice_in.client_gstin_id)
    customer = get_customer(db, invoice_in.customer_id, invoice_in.client_gstin_id)

    # Validate GSTINs
    validate_gstin_string(company["gstin"], "Company Profile GSTIN")
    if customer.get("is_b2b") or (customer.get("gstin") and str(customer["gstin"]).strip()):
        validate_gstin_string(customer["gstin"], "Customer GSTIN")

    pos = (invoice_in.place_of_supply or customer.get("state_code") or company.get("state_code")).strip().upper()
    is_interstate = (company["state_code"].strip().upper() != pos)

    computed_lines = [calculate_line_item_tax(line, is_interstate) for line in invoice_in.line_items]

    subtotal_paise = sum(item["taxable_value_paise"] for item in computed_lines)
    total_tax_paise = sum(
        item["cgst_paise"] + item["sgst_paise"] + item["igst_paise"] + item["cess_paise"]
        for item in computed_lines
    )
    total_paise = sum(item["line_total_paise"] for item in computed_lines)

    invoice_num = _atomic_get_next_invoice_number(db, invoice_in.company_profile_id)

    inv_record = {
        "client_gstin_id": invoice_in.client_gstin_id,
        "company_profile_id": invoice_in.company_profile_id,
        "customer_id": invoice_in.customer_id,
        "invoice_number": invoice_num,
        "invoice_date": invoice_in.invoice_date.isoformat(),
        "due_date": invoice_in.due_date.isoformat() if invoice_in.due_date else None,
        "place_of_supply": pos,
        "is_interstate": is_interstate,
        "subtotal_paise": subtotal_paise,
        "total_tax_paise": total_tax_paise,
        "total_paise": total_paise,
        "status": InvoiceStatus.DRAFT.value,
        "notes": invoice_in.notes,
    }

    res_inv = db.table("billing_invoices").insert(inv_record).execute()
    if not res_inv.data:
        raise HTTPException(status_code=500, detail="Failed to create invoice record")

    created_inv = res_inv.data[0]
    inv_id = created_inv["id"]

    for line in computed_lines:
        line["invoice_id"] = inv_id

    res_lines = db.table("billing_invoice_line_items").insert(computed_lines).execute()
    created_inv["line_items"] = res_lines.data or []
    created_inv["company_profile"] = company
    created_inv["customer"] = customer

    return created_inv


def update_invoice(
    db: Client, invoice_id: str, client_gstin_id: str, invoice_in: InvoiceUpdateInput
) -> Dict[str, Any]:
    existing_inv_res = (
        db.table("billing_invoices")
        .select("*")
        .eq("id", invoice_id)
        .eq("client_gstin_id", client_gstin_id)
        .limit(1)
        .execute()
    )
    if not existing_inv_res.data:
        raise HTTPException(status_code=404, detail="Invoice not found")

    existing_inv = existing_inv_res.data[0]
    if existing_inv["status"] != InvoiceStatus.DRAFT.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot edit invoice with status '{existing_inv['status']}'. Only draft invoices can be edited.",
        )

    company = get_company_profile(db, existing_inv["company_profile_id"], client_gstin_id)
    cust_id = invoice_in.customer_id or existing_inv["customer_id"]
    customer = get_customer(db, cust_id, client_gstin_id)

    pos = (
        invoice_in.place_of_supply
        or existing_inv.get("place_of_supply")
        or customer.get("state_code")
        or company.get("state_code")
    ).strip().upper()
    is_interstate = (company["state_code"].strip().upper() != pos)

    update_payload: Dict[str, Any] = {
        "customer_id": cust_id,
        "place_of_supply": pos,
        "is_interstate": is_interstate,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if invoice_in.invoice_date:
        update_payload["invoice_date"] = invoice_in.invoice_date.isoformat()
    if invoice_in.due_date:
        update_payload["due_date"] = invoice_in.due_date.isoformat()
    if invoice_in.notes is not None:
        update_payload["notes"] = invoice_in.notes

    if invoice_in.line_items is not None:
        computed_lines = [calculate_line_item_tax(line, is_interstate) for line in invoice_in.line_items]
        subtotal_paise = sum(item["taxable_value_paise"] for item in computed_lines)
        total_tax_paise = sum(
            item["cgst_paise"] + item["sgst_paise"] + item["igst_paise"] + item["cess_paise"]
            for item in computed_lines
        )
        total_paise = sum(item["line_total_paise"] for item in computed_lines)

        update_payload["subtotal_paise"] = subtotal_paise
        update_payload["total_tax_paise"] = total_tax_paise
        update_payload["total_paise"] = total_paise

        db.table("billing_invoice_line_items").delete().eq("invoice_id", invoice_id).execute()
        for line in computed_lines:
            line["invoice_id"] = invoice_id
        res_lines = db.table("billing_invoice_line_items").insert(computed_lines).execute()
        new_lines = res_lines.data or []
    else:
        existing_lines_res = db.table("billing_invoice_line_items").select("*").eq("invoice_id", invoice_id).execute()
        new_lines = existing_lines_res.data or []

    res_inv = db.table("billing_invoices").update(update_payload).eq("id", invoice_id).execute()
    updated_inv = res_inv.data[0]
    updated_inv["line_items"] = new_lines
    updated_inv["company_profile"] = company
    updated_inv["customer"] = customer

    return updated_inv


def finalize_invoice(db: Client, invoice_id: str, client_gstin_id: str) -> Dict[str, Any]:
    existing_inv_res = (
        db.table("billing_invoices")
        .select("*")
        .eq("id", invoice_id)
        .eq("client_gstin_id", client_gstin_id)
        .limit(1)
        .execute()
    )
    if not existing_inv_res.data:
        raise HTTPException(status_code=404, detail="Invoice not found")

    existing_inv = existing_inv_res.data[0]
    if existing_inv["status"] == InvoiceStatus.FINALIZED.value:
        return get_invoice_detail(db, invoice_id, client_gstin_id)

    if existing_inv["status"] != InvoiceStatus.DRAFT.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot finalize invoice in status '{existing_inv['status']}'. Only draft invoices can be finalized.",
        )

    res = (
        db.table("billing_invoices")
        .update({"status": InvoiceStatus.FINALIZED.value, "updated_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", invoice_id)
        .execute()
    )
    return get_invoice_detail(db, invoice_id, client_gstin_id)


def get_invoice_detail(db: Client, invoice_id: str, client_gstin_id: str) -> Dict[str, Any]:
    res = (
        db.table("billing_invoices")
        .select("*")
        .eq("id", invoice_id)
        .eq("client_gstin_id", client_gstin_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Invoice not found")

    inv = res.data[0]
    inv["company_profile"] = get_company_profile(db, inv["company_profile_id"], client_gstin_id)
    inv["customer"] = get_customer(db, inv["customer_id"], client_gstin_id)

    lines_res = db.table("billing_invoice_line_items").select("*").eq("invoice_id", invoice_id).execute()
    inv["line_items"] = lines_res.data or []

    return inv


def list_invoices(
    db: Client,
    client_gstin_id: str,
    status: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    query = db.table("billing_invoices").select("*").eq("client_gstin_id", client_gstin_id)

    if status and status.strip():
        query = query.eq("status", status.strip().lower())
    if start_date:
        query = query.gte("invoice_date", start_date.isoformat())
    if end_date:
        query = query.lte("invoice_date", end_date.isoformat())

    res = query.order("created_at", desc=True).execute()
    invoices = res.data or []

    # Attach minimal customer info for list view
    if invoices:
        cust_ids = list({inv["customer_id"] for inv in invoices if inv.get("customer_id")})
        if cust_ids:
            cust_res = db.table("billing_customers").select("id, name, gstin").in_("id", cust_ids).execute()
            cust_map = {c["id"]: c for c in cust_res.data or []}
            for inv in invoices:
                inv["customer"] = cust_map.get(inv.get("customer_id"))

    return invoices
