"""E-Way Bill Service (NIC Schema V1.03/V1.04).

Implements:
1. Validity calculation under statutory Rule 138(10) (200km/day for regular, 20km/day for ODC).
2. Standalone E-Way Bill generation (Part A & Part B).
3. 1-Click E-Way Bill generation directly from finalized invoices.
4. Part B Vehicle Update with historical tracking.
5. 24-Hour statutory cancellation under Rule 138(9).
6. Official Government NIC Bulk JSON exporter for direct upload to ewaybillgst.gov.in.
7. Self-healing DDL for public.eway_bills table.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import logging
import math
import random
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from supabase import Client

from app.models.ewaybill import (
    CancelEwayBillInput,
    DocumentType,
    EwayBillCreateInput,
    EwayBillStatus,
    EwbFromInvoiceInput,
    SubSupplyType,
    SupplyType,
    TransportMode,
    UpdateVehicleInput,
    VehicleType,
)

logger = logging.getLogger(__name__)


def calculate_validity_period(distance_km: int, vehicle_type: VehicleType, start_dt: datetime) -> datetime:
    """Calculate E-Way Bill validity under statutory CGST Rule 138(10).

    - Regular Cargo (R): 1 day for every 200 km (or part thereof).
    - Over Dimensional Cargo (O): 1 day for every 20 km (or part thereof).
    Valid till midnight of the terminal day.
    """
    km = max(1, int(distance_km))
    if vehicle_type == VehicleType.OVER_DIMENSIONAL_CARGO:
        days = math.ceil(km / 20.0)
    else:
        days = math.ceil(km / 200.0)
    days = max(1, days)
    end_date = start_dt + timedelta(days=days)
    # Set to end of day 23:59:59 UTC
    return end_date.replace(hour=23, minute=59, second=59, microsecond=0)


def generate_ewb_number(state_code: str) -> str:
    """Generate a standard 12-digit Indian E-Way Bill Number (State prefix + 10 random digits)."""
    st = str(state_code).zfill(2)[:2]
    if not st.isdigit():
        st = "27"
    rest = "".join([str(random.randint(0, 9)) for _ in range(10)])
    return f"{st}{rest}"


def ensure_ewaybill_table_exists(sb: Client) -> None:
    """Self-healing DDL to guarantee public.eway_bills exists in database."""
    try:
        sb.table("eway_bills").select("id").limit(1).execute()
    except Exception as exc:
        logger.warning("Table eway_bills not queryable via PostgREST, running self-healing DDL: %s", exc)
        from app.config import get_settings
        import sqlalchemy as sa
        s = get_settings()
        from app.aurora import normalize_database_url
        db_url = normalize_database_url(s.AURORA_DATABASE_URL or s.DATABASE_URL or s.SUPABASE_DATABASE_URL)
        if db_url:
            eng = sa.create_engine(db_url)
            with eng.connect() as conn:
                conn.execute(
                    sa.text(
                        """
                        CREATE TABLE IF NOT EXISTS public.eway_bills (
                            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                            client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
                            invoice_id UUID REFERENCES public.invoices(id) ON DELETE SET NULL,
                            ewb_number TEXT NOT NULL UNIQUE,
                            ewb_date TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
                            valid_until TIMESTAMPTZ,
                            status TEXT NOT NULL DEFAULT 'ACTIVE',
                            doc_type TEXT NOT NULL DEFAULT 'INV',
                            doc_number TEXT NOT NULL,
                            doc_date DATE NOT NULL,
                            supply_type TEXT NOT NULL DEFAULT 'O',
                            sub_supply_type TEXT NOT NULL DEFAULT '1',
                            sub_supply_desc TEXT,
                            from_gstin TEXT NOT NULL,
                            from_trade_name TEXT NOT NULL,
                            from_addr1 TEXT NOT NULL,
                            from_addr2 TEXT,
                            from_place TEXT NOT NULL,
                            from_pincode INT NOT NULL,
                            from_state_code TEXT NOT NULL,
                            to_gstin TEXT NOT NULL,
                            to_trade_name TEXT NOT NULL,
                            to_addr1 TEXT NOT NULL,
                            to_addr2 TEXT,
                            to_place TEXT NOT NULL,
                            to_pincode INT NOT NULL,
                            to_state_code TEXT NOT NULL,
                            total_taxable_value NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
                            cgst_amount NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
                            sgst_amount NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
                            igst_amount NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
                            cess_amount NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
                            total_invoice_value NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
                            transporter_id TEXT,
                            transporter_name TEXT,
                            trans_mode TEXT NOT NULL DEFAULT '1',
                            distance_km INT NOT NULL DEFAULT 10,
                            trans_doc_no TEXT,
                            trans_doc_date DATE,
                            vehicle_no TEXT,
                            vehicle_type TEXT NOT NULL DEFAULT 'R',
                            vehicle_history JSONB NOT NULL DEFAULT '[]'::jsonb,
                            items JSONB NOT NULL DEFAULT '[]'::jsonb,
                            nic_payload JSONB,
                            qr_code TEXT,
                            cancel_reason TEXT,
                            cancel_remarks TEXT,
                            cancelled_at TIMESTAMPTZ,
                            created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
                        );
                        CREATE INDEX IF NOT EXISTS idx_eway_bills_client_gstin ON public.eway_bills(client_gstin_id);
                        CREATE INDEX IF NOT EXISTS idx_eway_bills_doc_no ON public.eway_bills(doc_number);
                        CREATE INDEX IF NOT EXISTS idx_eway_bills_ewb_no ON public.eway_bills(ewb_number);
                        """
                    )
                )
                conn.execute(sa.text("NOTIFY pgrst, 'reload schema';"))
                conn.commit()
            eng.dispose()


def create_standalone_ewaybill(
    sb: Client,
    data: EwayBillCreateInput,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a complete standalone E-Way Bill."""
    ensure_ewaybill_table_exists(sb)

    now_dt = datetime.now(timezone.utc)
    valid_until = calculate_validity_period(data.distance_km, data.vehicle_type, now_dt)
    ewb_no = generate_ewb_number(data.from_state_code)

    status_str = EwayBillStatus.ACTIVE.value if (data.vehicle_no or data.trans_doc_no) else EwayBillStatus.PART_A_ONLY.value

    items_json = [item.model_dump() for item in data.items]

    record = {
        "client_gstin_id": data.client_gstin_id,
        "invoice_id": data.invoice_id,
        "ewb_number": ewb_no,
        "ewb_date": now_dt.isoformat(),
        "valid_until": valid_until.isoformat(),
        "status": status_str,
        "doc_type": data.doc_type.value,
        "doc_number": data.doc_number.strip(),
        "doc_date": data.doc_date.isoformat(),
        "supply_type": data.supply_type.value,
        "sub_supply_type": data.sub_supply_type.value,
        "sub_supply_desc": data.sub_supply_desc,
        "from_gstin": data.from_gstin.upper().strip(),
        "from_trade_name": data.from_trade_name.strip(),
        "from_addr1": data.from_addr1.strip(),
        "from_addr2": data.from_addr2.strip() if data.from_addr2 else None,
        "from_place": data.from_place.strip(),
        "from_pincode": data.from_pincode,
        "from_state_code": data.from_state_code.strip(),
        "to_gstin": data.to_gstin.upper().strip(),
        "to_trade_name": data.to_trade_name.strip(),
        "to_addr1": data.to_addr1.strip(),
        "to_addr2": data.to_addr2.strip() if data.to_addr2 else None,
        "to_place": data.to_place.strip(),
        "to_pincode": data.to_pincode,
        "to_state_code": data.to_state_code.strip(),
        "total_taxable_value": data.total_taxable_value,
        "cgst_amount": data.cgst_amount,
        "sgst_amount": data.sgst_amount,
        "igst_amount": data.igst_amount,
        "cess_amount": data.cess_amount,
        "total_invoice_value": data.total_invoice_value,
        "transporter_id": data.transporter_id.upper().strip() if data.transporter_id else None,
        "transporter_name": data.transporter_name.strip() if data.transporter_name else None,
        "trans_mode": data.trans_mode.value,
        "distance_km": data.distance_km,
        "trans_doc_no": data.trans_doc_no.strip() if data.trans_doc_no else None,
        "trans_doc_date": data.trans_doc_date.isoformat() if data.trans_doc_date else None,
        "vehicle_no": data.vehicle_no.upper().strip() if data.vehicle_no else None,
        "vehicle_type": data.vehicle_type.value,
        "items": items_json,
        "vehicle_history": [
            {
                "vehicle_no": data.vehicle_no.upper().strip() if data.vehicle_no else None,
                "from_place": data.from_place,
                "updated_at": now_dt.isoformat(),
                "reason": "Initial generation",
            }
        ] if data.vehicle_no else [],
        "created_by": user_id if (user_id and len(user_id) == 36) else None,
    }

    res = sb.table("eway_bills").insert(record).execute()
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create E-Way Bill record")
    return res.data[0]


def generate_ewaybill_from_invoice(
    sb: Client,
    input_data: EwbFromInvoiceInput,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """1-Click Generation of E-Way Bill directly from an existing finalized Invoice."""
    ensure_ewaybill_table_exists(sb)

    # 1. Fetch invoice, company profile, customer, and items
    inv_res = sb.table("invoices").select("*").eq("id", input_data.invoice_id).execute()
    if not inv_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Invoice '{input_data.invoice_id}' not found")
    invoice = inv_res.data[0]

    comp_res = sb.table("company_profiles").select("*").eq("id", invoice["company_profile_id"]).execute()
    company = comp_res.data[0] if comp_res.data else {}

    cust_res = sb.table("customers").select("*").eq("id", invoice["customer_id"]).execute()
    customer = cust_res.data[0] if cust_res.data else {}

    items_res = sb.table("invoice_line_items").select("*").eq("invoice_id", input_data.invoice_id).execute()
    line_items = items_res.data or []

    # Map to EwayBillCreateInput
    eway_items = []
    tot_cgst = 0.0
    tot_sgst = 0.0
    tot_igst = 0.0
    tot_cess = 0.0
    tot_taxable = 0.0

    for item in line_items:
        taxable_val = round((item.get("taxable_value_paise") or 0) / 100.0, 2)
        cgst_amt = round((item.get("cgst_paise") or 0) / 100.0, 2)
        sgst_amt = round((item.get("sgst_paise") or 0) / 100.0, 2)
        igst_amt = round((item.get("igst_paise") or 0) / 100.0, 2)
        cess_amt = round((item.get("cess_paise") or 0) / 100.0, 2)

        tot_taxable += taxable_val
        tot_cgst += cgst_amt
        tot_sgst += sgst_amt
        tot_igst += igst_amt
        tot_cess += cess_amt

        eway_items.append(
            {
                "item_name": item.get("description") or "Item",
                "hsn_code": str(item.get("hsn_or_sac_code") or "9999").strip(),
                "quantity": float(item.get("quantity") or 1.0),
                "unit": str(item.get("unit") or "NOS").strip(),
                "taxable_value": taxable_val,
                "cgst_rate": float(item.get("cgst_rate_percent") or 0.0),
                "cgst_amount": cgst_amt,
                "sgst_rate": float(item.get("sgst_rate_percent") or 0.0),
                "sgst_amount": sgst_amt,
                "igst_rate": float(item.get("igst_rate_percent") or 0.0),
                "igst_amount": igst_amt,
                "cess_amount": cess_amt,
            }
        )

    seller_pin = int(company.get("pincode") or 400001) if str(company.get("pincode") or "").isdigit() else 400001
    buyer_pin = int(customer.get("pincode") or 400001) if str(customer.get("pincode") or "").isdigit() else 400001

    tot_inv_val = round((invoice.get("total_paise") or 0) / 100.0, 2)

    parsed_doc_date = date.today()
    if invoice.get("invoice_date"):
        try:
            parsed_doc_date = date.fromisoformat(str(invoice["invoice_date"])[:10])
        except Exception:
            pass

    create_data = EwayBillCreateInput(
        client_gstin_id=input_data.client_gstin_id,
        invoice_id=input_data.invoice_id,
        supply_type=SupplyType.OUTWARD,
        sub_supply_type=SubSupplyType.SUPPLY,
        doc_type=DocumentType.TAX_INVOICE,
        doc_number=invoice.get("invoice_number") or "INV-1",
        doc_date=parsed_doc_date,
        from_gstin=company.get("gstin") or "27AABCR1234F1Z5",
        from_trade_name=company.get("trade_name") or company.get("legal_name") or "Business",
        from_addr1=company.get("address_line1") or "Address Line 1",
        from_addr2=company.get("address_line2"),
        from_place=company.get("city") or "Mumbai",
        from_pincode=seller_pin,
        from_state_code=company.get("state_code") or "27",
        to_gstin=customer.get("gstin") or "URP",
        to_trade_name=customer.get("name") or "Customer",
        to_addr1=customer.get("address_line1") or "Customer Address",
        to_addr2=customer.get("address_line2"),
        to_place=customer.get("city") or "Pune",
        to_pincode=buyer_pin,
        to_state_code=customer.get("state_code") or company.get("state_code") or "27",
        total_taxable_value=tot_taxable,
        cgst_amount=tot_cgst,
        sgst_amount=tot_sgst,
        igst_amount=tot_igst,
        cess_amount=tot_cess,
        total_invoice_value=tot_inv_val,
        items=eway_items,
        transporter_id=input_data.transporter_id,
        transporter_name=input_data.transporter_name,
        trans_mode=input_data.trans_mode,
        distance_km=input_data.distance_km,
        trans_doc_no=input_data.trans_doc_no,
        trans_doc_date=input_data.trans_doc_date,
        vehicle_no=input_data.vehicle_no,
        vehicle_type=input_data.vehicle_type,
    )

    return create_standalone_ewaybill(sb, create_data, user_id=user_id)


def update_vehicle_details(
    sb: Client,
    ewb_id: str,
    update: UpdateVehicleInput,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Update Part B vehicle number with audit trail."""
    ensure_ewaybill_table_exists(sb)

    cur = sb.table("eway_bills").select("*").eq("id", ewb_id).execute()
    if not cur.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "E-Way Bill not found")
    record = cur.data[0]

    if record.get("status") == EwayBillStatus.CANCELLED.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot update vehicle for a CANCELLED E-Way Bill")

    history = record.get("vehicle_history") or []
    new_entry = {
        "vehicle_no": update.vehicle_no.upper().strip(),
        "from_place": update.from_place.strip(),
        "from_state_code": update.from_state_code,
        "reason_code": update.reason_code,
        "reason_remark": update.reason_remark,
        "trans_doc_no": update.trans_doc_no,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": user_id,
    }
    history.append(new_entry)

    upd_payload = {
        "vehicle_no": update.vehicle_no.upper().strip(),
        "trans_mode": update.trans_mode.value,
        "trans_doc_no": update.trans_doc_no,
        "status": EwayBillStatus.ACTIVE.value,
        "vehicle_history": history,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    res = sb.table("eway_bills").update(upd_payload).eq("id", ewb_id).execute()
    return res.data[0]


def cancel_ewaybill(
    sb: Client,
    ewb_id: str,
    cancel: CancelEwayBillInput,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Cancel E-Way Bill within the statutory 24-hour window under Rule 138(9)."""
    ensure_ewaybill_table_exists(sb)

    cur = sb.table("eway_bills").select("*").eq("id", ewb_id).execute()
    if not cur.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "E-Way Bill not found")
    record = cur.data[0]

    if record.get("status") == EwayBillStatus.CANCELLED.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "E-Way Bill is already cancelled")

    ewb_dt_str = record.get("ewb_date") or ""
    try:
        ewb_dt = datetime.fromisoformat(ewb_dt_str.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - ewb_dt > timedelta(hours=24):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "E-Way Bill cannot be cancelled after 24 hours from generation under statutory Rule 138(9).",
            )
    except (ValueError, TypeError):
        pass

    upd = {
        "status": EwayBillStatus.CANCELLED.value,
        "cancel_reason": cancel.cancel_reason_code,
        "cancel_remarks": cancel.cancel_remarks.strip(),
        "cancelled_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    res = sb.table("eway_bills").update(upd).eq("id", ewb_id).execute()
    return res.data[0]


def list_ewaybills(
    sb: Client,
    client_gstin_id: str,
    status_filter: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List E-Way Bills for client GSTIN."""
    ensure_ewaybill_table_exists(sb)
    q = sb.table("eway_bills").select("*").eq("client_gstin_id", client_gstin_id)
    if status_filter:
        q = q.eq("status", status_filter.upper())
    res = q.order("created_at", desc=True).limit(limit).execute()
    return res.data or []


def build_nic_bulk_json(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate official Government NIC Bulk JSON export for direct portal upload on ewaybillgst.gov.in."""
    bill_lists = []

    for rec in records:
        doc_dt = rec.get("doc_date") or date.today().isoformat()
        try:
            d_obj = datetime.strptime(str(doc_dt)[:10], "%Y-%m-%d")
            formatted_doc_dt = d_obj.strftime("%d/%m/%Y")
        except Exception:
            formatted_doc_dt = str(doc_dt)

        items_list = []
        raw_items = rec.get("items") or []
        for itm in raw_items:
            items_list.append(
                {
                    "productName": itm.get("item_name") or "Goods",
                    "productDesc": itm.get("description") or itm.get("item_name") or "Goods",
                    "hsnCode": int(str(itm.get("hsn_code") or "9999").strip()),
                    "quantity": float(itm.get("quantity") or 1.0),
                    "qtyUnit": str(itm.get("unit") or "NOS").strip(),
                    "taxableAmount": float(itm.get("taxable_value") or 0.0),
                    "cgstRate": float(itm.get("cgst_rate") or 0.0),
                    "sgstRate": float(itm.get("sgst_rate") or 0.0),
                    "igstRate": float(itm.get("igst_rate") or 0.0),
                    "cessRate": float(itm.get("cess_rate") or 0.0),
                }
            )

        bill = {
            "userGstin": rec.get("from_gstin"),
            "supplyType": rec.get("supply_type") or "O",
            "subSupplyType": rec.get("sub_supply_type") or "1",
            "subSupplyDesc": rec.get("sub_supply_desc") or "",
            "docType": rec.get("doc_type") or "INV",
            "docNo": rec.get("doc_number"),
            "docDate": formatted_doc_dt,
            "fromGstin": rec.get("from_gstin"),
            "fromTrdName": rec.get("from_trade_name"),
            "fromAddr1": rec.get("from_addr1"),
            "fromAddr2": rec.get("from_addr2") or "",
            "fromPlace": rec.get("from_place"),
            "fromPincode": int(rec.get("from_pincode") or 400001),
            "fromStateCode": int(str(rec.get("from_state_code") or "27")),
            "actualFromStateCode": int(str(rec.get("from_state_code") or "27")),
            "toGstin": rec.get("to_gstin"),
            "toTrdName": rec.get("to_trade_name"),
            "toAddr1": rec.get("to_addr1"),
            "toAddr2": rec.get("to_addr2") or "",
            "toPlace": rec.get("to_place"),
            "toPincode": int(rec.get("to_pincode") or 400001),
            "toStateCode": int(str(rec.get("to_state_code") or "27")),
            "actualToStateCode": int(str(rec.get("to_state_code") or "27")),
            "totalValue": float(rec.get("total_taxable_value") or 0.0),
            "cgstValue": float(rec.get("cgst_amount") or 0.0),
            "sgstValue": float(rec.get("sgst_amount") or 0.0),
            "igstValue": float(rec.get("igst_amount") or 0.0),
            "cessValue": float(rec.get("cess_amount") or 0.0),
            "totInvValue": float(rec.get("total_invoice_value") or 0.0),
            "transDistance": str(rec.get("distance_km") or 10),
            "transporterId": rec.get("transporter_id") or "",
            "transporterName": rec.get("transporter_name") or "",
            "transDocNo": rec.get("trans_doc_no") or "",
            "transDocDate": "",
            "vehicleNo": rec.get("vehicle_no") or "",
            "vehicleType": rec.get("vehicle_type") or "R",
            "itemList": items_list,
        }
        bill_lists.append(bill)

    return {
        "version": "1.0.1124",
        "billLists": bill_lists,
    }
