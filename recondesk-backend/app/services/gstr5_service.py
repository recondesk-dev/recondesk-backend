"""Form GSTR-5 Service (Non-Resident Taxable Persons Compliance).

Manages:
- GSTR-5 Batches, NRTP registration validity period (Section 27).
- Table 3 Import of goods from overseas (Bill of Entry ITC).
- Table 5 Outward supplies to registered persons (B2B).
- Table 6 Outward supplies to unregistered persons (B2C).
- Table 7 Amendments to outward supplies.
- Advance tax deposit and cash ledger sufficiency checks (Section 27(2)).
- Cryptographic figures digest binding.
- GSTN offline JSON generation.
"""

from __future__ import annotations

import copy
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

from app.rules.gstr5_rules import (
    compute_nrtp_tax_summary,
    evaluate_nrtp_registration_and_due_date,
    extract_state_code,
)
from app.services.pre_filing_validator import compute_figures_digest

_log = logging.getLogger(__name__)


class Gstr5Error(Exception):
    pass


class Gstr5ValidationError(Gstr5Error):
    pass


class Gstr5DuplicateError(Gstr5Error):
    pass


@dataclass
class Gstr5BatchData:
    id: str
    firm_id: str
    client_gstin_id: str
    gstin: str
    period: str
    status: str
    figures_digest: str
    registration_start_date: str = ""
    registration_expiry_date: str = ""
    statutory_due_date: str = ""
    total_outward_taxable: float = 0.0
    total_outward_liability: float = 0.0
    total_import_itc: float = 0.0
    net_tax_payable: float = 0.0
    advance_tax_deposited: float = 0.0
    gstn_reference_id: Optional[str] = None
    gstn_status: Optional[str] = None
    arn: Optional[str] = None
    filing_run_id: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Gstr5ImportRecordData:
    id: str
    batch_id: str
    firm_id: str
    client_gstin_id: str
    boe_number: str
    boe_date: str
    port_code: str
    taxable_value: float
    igst_paid: float
    cess_paid: float
    status: str = "ACTIVE"
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Gstr5OutwardRecordData:
    id: str
    batch_id: str
    firm_id: str
    client_gstin_id: str
    supply_type: str  # "B2B" or "B2C"
    record_type: str  # "ORIGINAL" or "AMENDMENT"
    recipient_gstin: Optional[str]
    pos: str
    invoice_number: str
    invoice_date: str
    taxable_value: float
    rate_pct: float
    igst: float
    cgst: float
    sgst: float
    cess: float
    original_period: Optional[str] = None
    original_invoice_number: Optional[str] = None
    status: str = "ACTIVE"
    created_at: str = ""
    updated_at: str = ""


class _Gstr5Store:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._batches: dict[str, Gstr5BatchData] = {}
        self._imports: dict[str, Gstr5ImportRecordData] = {}
        self._outwards: dict[str, Gstr5OutwardRecordData] = {}

    def get_batch(self, batch_id: str) -> Optional[Gstr5BatchData]:
        with self._lock:
            return self._batches.get(batch_id)

    def find_batch(self, firm_id: str, client_gstin_id: str, period: str) -> Optional[Gstr5BatchData]:
        with self._lock:
            for b in self._batches.values():
                if b.firm_id == firm_id and b.client_gstin_id == client_gstin_id and b.period == period:
                    return b
            return None

    def put_batch(self, batch: Gstr5BatchData) -> None:
        with self._lock:
            self._batches[batch.id] = batch

    def put_import(self, rec: Gstr5ImportRecordData) -> None:
        with self._lock:
            self._imports[rec.id] = rec

    def list_imports(self, batch_id: str) -> list[Gstr5ImportRecordData]:
        with self._lock:
            return [r for r in self._imports.values() if r.batch_id == batch_id and r.status == "ACTIVE"]

    def put_outward(self, rec: Gstr5OutwardRecordData) -> None:
        with self._lock:
            self._outwards[rec.id] = rec

    def list_outwards(self, batch_id: str) -> list[Gstr5OutwardRecordData]:
        with self._lock:
            return [r for r in self._outwards.values() if r.batch_id == batch_id and r.status == "ACTIVE"]

    def delete_import(self, import_id: str) -> None:
        with self._lock:
            if import_id in self._imports:
                self._imports[import_id].status = "DELETED"

    def delete_outward(self, outward_id: str) -> None:
        with self._lock:
            if outward_id in self._outwards:
                self._outwards[outward_id].status = "DELETED"

    def clear(self) -> None:
        with self._lock:
            self._batches.clear()
            self._imports.clear()
            self._outwards.clear()


_gstr5_store = _Gstr5Store()


def reset_gstr5_store_for_testing() -> None:
    _gstr5_store.clear()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_or_create_batch_sync(
    sb: Any,
    *,
    firm_id: str,
    client_gstin_id: str,
    gstin: str,
    period: str,
    registration_start_date: Optional[str] = None,
    registration_expiry_date: Optional[str] = None,
    advance_tax_deposited: float = 0.0,
    user_id: Optional[str] = None,
) -> Gstr5BatchData:
    existing = _gstr5_store.find_batch(firm_id, client_gstin_id, period)
    if existing:
        return existing

    r_start = registration_start_date or "2026-06-01"
    r_exp = registration_expiry_date or "2026-08-30"
    reg_eval = evaluate_nrtp_registration_and_due_date(
        period=period,
        registration_start=r_start,
        registration_expiry=r_exp,
    )

    batch = Gstr5BatchData(
        id=str(uuid4()),
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin=gstin.strip().upper(),
        period=period.strip(),
        status="DRAFT",
        figures_digest="",
        registration_start_date=r_start,
        registration_expiry_date=r_exp,
        statutory_due_date=reg_eval.statutory_due_date.isoformat(),
        advance_tax_deposited=advance_tax_deposited,
        created_by=user_id,
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    _gstr5_store.put_batch(batch)
    return batch


def add_or_update_import_record_sync(
    sb: Any,
    *,
    batch_id: str,
    record_data: dict[str, Any],
    user_id: Optional[str] = None,
) -> Gstr5ImportRecordData:
    batch = _gstr5_store.get_batch(batch_id)
    if not batch:
        raise Gstr5Error(f"Batch '{batch_id}' not found.")

    boe_num = str(record_data.get("boe_number") or "").strip().upper()
    existing = _gstr5_store.list_imports(batch_id)
    rec_id = record_data.get("id")

    for r in existing:
        if r.boe_number == boe_num and r.id != rec_id:
            raise Gstr5DuplicateError(f"Duplicate Bill of Entry '{boe_num}' in batch.")

    now = _now_iso()
    rec = Gstr5ImportRecordData(
        id=str(rec_id or uuid4()),
        batch_id=batch_id,
        firm_id=batch.firm_id,
        client_gstin_id=batch.client_gstin_id,
        boe_number=boe_num,
        boe_date=str(record_data.get("boe_date") or ""),
        port_code=str(record_data.get("port_code") or "").strip().upper(),
        taxable_value=float(record_data.get("taxable_value") or 0.0),
        igst_paid=float(record_data.get("igst_paid") or 0.0),
        cess_paid=float(record_data.get("cess_paid") or 0.0),
        created_at=now,
        updated_at=now,
    )
    _gstr5_store.put_import(rec)
    recompute_batch_sync(sb, batch_id=batch_id)
    return rec


def add_or_update_outward_record_sync(
    sb: Any,
    *,
    batch_id: str,
    record_data: dict[str, Any],
    user_id: Optional[str] = None,
) -> Gstr5OutwardRecordData:
    batch = _gstr5_store.get_batch(batch_id)
    if not batch:
        raise Gstr5Error(f"Batch '{batch_id}' not found.")

    inv_num = str(record_data.get("invoice_number") or "").strip().upper()
    existing = _gstr5_store.list_outwards(batch_id)
    rec_id = record_data.get("id")

    for r in existing:
        if r.invoice_number == inv_num and r.id != rec_id:
            raise Gstr5DuplicateError(f"Duplicate outward invoice '{inv_num}' in batch.")

    rec_gstin = str(record_data.get("recipient_gstin") or "").strip().upper() or None
    supply_type = "B2B" if rec_gstin else "B2C"
    record_type = str(record_data.get("record_type") or "ORIGINAL").upper()

    now = _now_iso()
    rec = Gstr5OutwardRecordData(
        id=str(rec_id or uuid4()),
        batch_id=batch_id,
        firm_id=batch.firm_id,
        client_gstin_id=batch.client_gstin_id,
        supply_type=supply_type,
        record_type=record_type,
        recipient_gstin=rec_gstin,
        pos=str(record_data.get("pos") or "").strip(),
        invoice_number=inv_num,
        invoice_date=str(record_data.get("invoice_date") or ""),
        taxable_value=float(record_data.get("taxable_value") or 0.0),
        rate_pct=float(record_data.get("rate_pct") or 18.0),
        igst=float(record_data.get("igst") or 0.0),
        cgst=float(record_data.get("cgst") or 0.0),
        sgst=float(record_data.get("sgst") or 0.0),
        cess=float(record_data.get("cess") or 0.0),
        original_period=record_data.get("original_period"),
        original_invoice_number=record_data.get("original_invoice_number"),
        created_at=now,
        updated_at=now,
    )
    _gstr5_store.put_outward(rec)
    recompute_batch_sync(sb, batch_id=batch_id)
    return rec


def delete_import_record_sync(sb: Any, *, batch_id: str, import_id: str) -> None:
    _gstr5_store.delete_import(import_id)
    recompute_batch_sync(sb, batch_id=batch_id)


def delete_outward_record_sync(sb: Any, *, batch_id: str, outward_id: str) -> None:
    _gstr5_store.delete_outward(outward_id)
    recompute_batch_sync(sb, batch_id=batch_id)


def recompute_batch_sync(sb: Any, *, batch_id: str) -> Gstr5BatchData:
    batch = _gstr5_store.get_batch(batch_id)
    if not batch:
        raise Gstr5Error(f"Batch '{batch_id}' not found.")

    imports = _gstr5_store.list_imports(batch_id)
    outwards = _gstr5_store.list_outwards(batch_id)

    summary = compute_nrtp_tax_summary(
        outward_records=[r.__dict__ for r in outwards],
        import_records=[r.__dict__ for r in imports],
        advance_tax_deposited=batch.advance_tax_deposited,
    )

    batch.total_outward_taxable = float(summary.total_outward_taxable)
    batch.total_outward_liability = float(summary.total_outward_liability)
    batch.total_import_itc = float(summary.total_eligible_import_itc)
    batch.net_tax_payable = float(summary.net_tax_payable)

    payload_for_digest = {
        "gstin": batch.gstin,
        "period": batch.period,
        "outward_count": len(outwards),
        "import_count": len(imports),
        "total_outward_liability": batch.total_outward_liability,
        "total_import_itc": batch.total_import_itc,
        "net_tax_payable": batch.net_tax_payable,
        "advance_tax_deposited": batch.advance_tax_deposited,
    }
    batch.figures_digest = compute_figures_digest(payload_for_digest)
    batch.updated_at = _now_iso()
    _gstr5_store.put_batch(batch)
    return batch


def get_batch_summary_sync(sb: Any, *, batch_id: str) -> dict[str, Any]:
    batch = recompute_batch_sync(sb, batch_id=batch_id)
    imports = _gstr5_store.list_imports(batch_id)
    outwards = _gstr5_store.list_outwards(batch_id)

    b2b_orig = [r for r in outwards if r.supply_type == "B2B" and r.record_type == "ORIGINAL"]
    b2c_orig = [r for r in outwards if r.supply_type == "B2C" and r.record_type == "ORIGINAL"]
    amendments = [r for r in outwards if r.record_type == "AMENDMENT"]

    reg_eval = evaluate_nrtp_registration_and_due_date(
        period=batch.period,
        registration_start=batch.registration_start_date,
        registration_expiry=batch.registration_expiry_date,
    )

    summary = compute_nrtp_tax_summary(
        outward_records=[r.__dict__ for r in outwards],
        import_records=[r.__dict__ for r in imports],
        advance_tax_deposited=batch.advance_tax_deposited,
    )

    cash_payable = float(summary.shortfall_amount) if not summary.is_advance_sufficient else 0.0
    refund_eligible = float(summary.cash_ledger_balance) if summary.is_advance_sufficient else 0.0

    tax_summary_dict = copy.deepcopy(summary.__dict__)
    tax_summary_dict["gross_tax_liability"] = float(summary.total_outward_liability)
    tax_summary_dict["eligible_import_itc"] = float(summary.total_eligible_import_itc)
    tax_summary_dict["net_tax_payable"] = float(summary.net_tax_payable)
    tax_summary_dict["cash_payable"] = cash_payable
    tax_summary_dict["refund_eligible"] = refund_eligible

    return {
        "batch": copy.deepcopy(batch.__dict__),
        "registration_status": copy.deepcopy(reg_eval.__dict__),
        "tax_summary": tax_summary_dict,
        "table3_imports": [copy.deepcopy(r.__dict__) for r in imports],
        "table5_b2b": [copy.deepcopy(r.__dict__) for r in b2b_orig],
        "table6_b2c": [copy.deepcopy(r.__dict__) for r in b2c_orig],
        "table7_amendments": [copy.deepcopy(r.__dict__) for r in amendments],
        "statutory_restrictions": {
            "inward_domestic_itc_permitted": False,
            "rule_reference": "Section 17(5) of CGST Act, 2017 - NRTP restricted to Bill of Entry import ITC only",
        },
    }


def build_gstr5_offline_json(sb: Any, *, batch_id: str) -> dict[str, Any]:
    """Generate internal audit and ASP data interchange JSON for Form GSTR-5.

    Operational Note:
    The official GST Portal (gst.gov.in) does NOT support an offline JSON upload tool
    or 'Prepare Offline' utility for Form GSTR-5 (Non-Resident Taxable Persons).
    Official filing on the GST Portal is conducted directly online via 'Prepare Online'
    or programmatically via authorized GSP/ASP APIs. This generated JSON serves as
    an internal record, CA workpaper, and ASP API interchange payload.
    """
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]

    parts = batch["period"].split("-")
    fp = f"{parts[1]}{parts[0]}" if len(parts) == 2 else batch["period"]

    imp_g = []
    for r in summary["table3_imports"]:
        imp_g.append({
            "boe_num": r["boe_number"],
            "boe_dt": r["boe_date"],
            "port_code": r["port_code"],
            "txval": float(r["taxable_value"]),
            "iamt": float(r["igst_paid"]),
            "csamt": float(r["cess_paid"]),
        })

    b2b = []
    for r in summary["table5_b2b"]:
        b2b.append({
            "ctin": r["recipient_gstin"],
            "pos": r["pos"],
            "inum": r["invoice_number"],
            "idt": r["invoice_date"],
            "txval": float(r["taxable_value"]),
            "rt": float(r["rate_pct"]),
            "iamt": float(r["igst"]),
            "camt": float(r["cgst"]),
            "samt": float(r["sgst"]),
            "csamt": float(r["cess"]),
        })

    b2c = []
    for r in summary["table6_b2c"]:
        b2c.append({
            "pos": r["pos"],
            "inum": r["invoice_number"],
            "idt": r["invoice_date"],
            "txval": float(r["taxable_value"]),
            "rt": float(r["rate_pct"]),
            "iamt": float(r["igst"]),
            "camt": float(r["cgst"]),
            "samt": float(r["sgst"]),
            "csamt": float(r["cess"]),
        })

    payload: dict[str, Any] = {
        "gstin": batch["gstin"],
        "fp": fp,
        "imp_g": imp_g,
        "b2b": b2b,
        "b2c": b2c,
    }
    return payload
