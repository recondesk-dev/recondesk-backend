"""Phase 4.2: Form GSTR-8 (TCS under Section 52) Compliance Engine.

Implements:
- E-Commerce Operator (ECO) & merchant supplier GSTIN management
- Table 3 Supplies: B2B (registered suppliers) and B2C (unregistered by POS)
- Table 4 Amendments: Table 4A (B2B amendments) and Table 4B (B2C amendments)
- Gross, returned, and net taxable supply calculation (net = gross - returns)
- Statutory TCS rates: 0.5% (0.25% + 0.25%) effective 10-Jul-2024 (Notification 15/2024-CT),
  1.0% (0.5% + 0.5%) for prior periods
- Tax-head allocation: Intra-state (CGST+SGST) vs Inter-state (IGST)
- Duplicate supplier / POS line detection
- Collected vs deposited tax reconciliation
- Figures digest computation & approval binding
- GSTN offline JSON generation
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Optional
from uuid import uuid4

from app.rules.gstr8_rules import (
    TcsCalculationResult,
    calculate_gstr8_tcs,
    get_applicable_tcs_rates,
)
from app.rules.gstr7_rules import extract_state_code, validate_gstin_format

_log = logging.getLogger(__name__)

GSTR8_BATCHES_TABLE = "gstr8_batches"
GSTR8_RECORDS_TABLE = "gstr8_records"
GSTR8_AUDIT_TABLE = "gstr8_audit_trail"


class Gstr8Error(Exception):
    """Base exception for GSTR-8 operations."""


class Gstr8ValidationError(Gstr8Error):
    """Validation or constraint violation."""


class Gstr8DuplicateError(Gstr8Error):
    """Duplicate TCS record error."""


@dataclass
class Gstr8RecordData:
    id: str
    batch_id: str
    firm_id: str
    client_gstin_id: str
    period: str
    supply_type: str  # "B2B" or "B2C"
    record_type: str  # "ORIGINAL" or "AMENDMENT"
    pos: str
    supplier_gstin: Optional[str] = None
    gross_supplies: float = 0.0
    returned_supplies: float = 0.0
    net_supplies: float = 0.0
    tcs_rate: float = 0.5
    tcs_igst: float = 0.0
    tcs_cgst: float = 0.0
    tcs_sgst: float = 0.0
    original_period: Optional[str] = None
    original_supplier_gstin: Optional[str] = None
    original_pos: Optional[str] = None
    tax_deposited: float = 0.0
    status: str = "ACTIVE"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Gstr8BatchData:
    id: str
    firm_id: str
    client_gstin_id: str
    gstin: str
    period: str
    status: str = "DRAFT"  # DRAFT, PREPARED, UNDER_REVIEW, APPROVED, REJECTED, SAVED, FILED
    figures_digest: str = ""
    total_b2b_records: int = 0
    total_b2c_records: int = 0
    total_amendments: int = 0
    gross_supplies_value: float = 0.0
    returned_supplies_value: float = 0.0
    net_taxable_value: float = 0.0
    total_tcs_igst: float = 0.0
    total_tcs_cgst: float = 0.0
    total_tcs_sgst: float = 0.0
    total_tcs_deposited: float = 0.0
    gstn_reference_id: Optional[str] = None
    gstn_status: Optional[str] = None
    arn: Optional[str] = None
    filing_run_id: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class _Gstr8MemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.batches: dict[str, Gstr8BatchData] = {}
        self.records: dict[str, Gstr8RecordData] = {}
        self.audits: list[dict[str, Any]] = []

    def reset(self) -> None:
        with self._lock:
            self.batches.clear()
            self.records.clear()
            self.audits.clear()


_mem_store_8 = _Gstr8MemoryStore()


def reset_gstr8_memory_store_for_testing() -> None:
    _mem_store_8.reset()


def compute_gstr8_figures_digest(batch: Mapping[str, Any], records: list[Mapping[str, Any]]) -> str:
    """Deterministic SHA-256 digest binding GSTR-8 batch to exact supply values."""
    sorted_recs = sorted(
        records,
        key=lambda r: (
            str(r.get("supply_type") or ""),
            str(r.get("record_type") or ""),
            str(r.get("supplier_gstin") or ""),
            str(r.get("pos") or ""),
            str(r.get("id") or ""),
        ),
    )
    payload = {
        "gstin": str(batch.get("gstin") or "").strip().upper(),
        "period": str(batch.get("period") or "").strip(),
        "gross_supplies_value": f"{float(batch.get('gross_supplies_value') or 0):.2f}",
        "returned_supplies_value": f"{float(batch.get('returned_supplies_value') or 0):.2f}",
        "net_taxable_value": f"{float(batch.get('net_taxable_value') or 0):.2f}",
        "total_tcs_igst": f"{float(batch.get('total_tcs_igst') or 0):.2f}",
        "total_tcs_cgst": f"{float(batch.get('total_tcs_cgst') or 0):.2f}",
        "total_tcs_sgst": f"{float(batch.get('total_tcs_sgst') or 0):.2f}",
        "records": [
            {
                "id": str(r.get("id") or ""),
                "supply_type": str(r.get("supply_type") or "B2B"),
                "record_type": str(r.get("record_type") or "ORIGINAL"),
                "supplier_gstin": str(r.get("supplier_gstin") or "").strip().upper(),
                "pos": str(r.get("pos") or "").strip(),
                "gross_supplies": f"{float(r.get('gross_supplies') or 0):.2f}",
                "returned_supplies": f"{float(r.get('returned_supplies') or 0):.2f}",
                "net_supplies": f"{float(r.get('net_supplies') or 0):.2f}",
                "tcs_igst": f"{float(r.get('tcs_igst') or 0):.2f}",
                "tcs_cgst": f"{float(r.get('tcs_cgst') or 0):.2f}",
                "tcs_sgst": f"{float(r.get('tcs_sgst') or 0):.2f}",
            }
            for r in sorted_recs
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _recalculate_batch_totals_8(batch: Gstr8BatchData, records: list[Gstr8RecordData]) -> None:
    gross_tot = Decimal("0.00")
    ret_tot = Decimal("0.00")
    net_tot = Decimal("0.00")
    tot_igst = Decimal("0.00")
    tot_cgst = Decimal("0.00")
    tot_sgst = Decimal("0.00")
    tot_dep = Decimal("0.00")
    b2b_cnt = 0
    b2c_cnt = 0
    amend_cnt = 0

    for r in records:
        if r.status != "ACTIVE":
            continue
        if r.record_type == "AMENDMENT":
            amend_cnt += 1
        elif r.supply_type == "B2B":
            b2b_cnt += 1
        else:
            b2c_cnt += 1

        gross_tot += Decimal(str(r.gross_supplies or 0))
        ret_tot += Decimal(str(r.returned_supplies or 0))
        net_tot += Decimal(str(r.net_supplies or 0))
        tot_igst += Decimal(str(r.tcs_igst or 0))
        tot_cgst += Decimal(str(r.tcs_cgst or 0))
        tot_sgst += Decimal(str(r.tcs_sgst or 0))
        tot_dep += Decimal(str(r.tax_deposited or 0))

    batch.total_b2b_records = b2b_cnt
    batch.total_b2c_records = b2c_cnt
    batch.total_amendments = amend_cnt
    batch.gross_supplies_value = float(gross_tot.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    batch.returned_supplies_value = float(ret_tot.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    batch.net_taxable_value = float(net_tot.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    batch.total_tcs_igst = float(tot_igst.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    batch.total_tcs_cgst = float(tot_cgst.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    batch.total_tcs_sgst = float(tot_sgst.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    batch.total_tcs_deposited = float(tot_dep.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    batch.updated_at = datetime.now(timezone.utc).isoformat()

    rec_dicts = [r.__dict__ for r in records if r.status == "ACTIVE"]
    batch.figures_digest = compute_gstr8_figures_digest(batch.__dict__, rec_dicts)


def get_or_create_batch_sync(
    sb: Any,
    *,
    firm_id: str,
    client_gstin_id: str,
    gstin: str,
    period: str,
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Retrieve existing GSTR-8 batch or create a new DRAFT batch."""
    clean_gstin = gstin.strip().upper()
    clean_period = period.strip()

    with _mem_store_8._lock:
        for b in _mem_store_8.batches.values():
            if (
                b.firm_id == firm_id
                and b.client_gstin_id == client_gstin_id
                and b.period == clean_period
            ):
                return copy.deepcopy(b.__dict__)

        new_batch = Gstr8BatchData(
            id=str(uuid4()),
            firm_id=firm_id,
            client_gstin_id=client_gstin_id,
            gstin=clean_gstin,
            period=clean_period,
            status="DRAFT",
            created_by=user_id,
        )
        _recalculate_batch_totals_8(new_batch, [])
        _mem_store_8.batches[new_batch.id] = new_batch
        return copy.deepcopy(new_batch.__dict__)


def add_or_update_gstr8_record_sync(
    sb: Any,
    *,
    batch_id: str,
    record_data: Mapping[str, Any],
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Add or update a TCS supply record in GSTR-8."""
    with _mem_store_8._lock:
        batch = _mem_store_8.batches.get(batch_id)
        if not batch:
            raise Gstr8Error(f"GSTR-8 Batch {batch_id} not found")

        if batch.status in ("SAVED", "FILED"):
            raise Gstr8ValidationError(f"Cannot modify batch in status {batch.status}")

        supply_type = str(record_data.get("supply_type") or "B2B").upper()
        rec_type = str(record_data.get("record_type") or "ORIGINAL").upper()
        supplier_gstin = str(record_data.get("supplier_gstin") or "").strip().upper() or None
        pos = str(record_data.get("pos") or "").strip()

        if supply_type == "B2B":
            if not supplier_gstin or not validate_gstin_format(supplier_gstin):
                raise Gstr8ValidationError(f"B2B supply requires a valid supplier GSTIN: '{supplier_gstin}'")
            if not pos:
                pos = extract_state_code(supplier_gstin)
        else:
            # B2C supply requires valid 2-digit POS
            if not pos or len(pos) != 2 or not pos.isdigit():
                raise Gstr8ValidationError(f"B2C supply requires a valid 2-digit Place of Supply (POS): '{pos}'")

        gross_val = float(record_data.get("gross_supplies") or 0.0)
        ret_val = float(record_data.get("returned_supplies") or 0.0)
        eco_state = extract_state_code(batch.gstin)
        supp_state = extract_state_code(supplier_gstin) if supplier_gstin else None

        # Compute statutory TCS calculation
        calc = calculate_gstr8_tcs(
            period=batch.period,
            gross_supplies=gross_val,
            returned_supplies=ret_val,
            eco_state=eco_state,
            pos=pos,
            supplier_state=supp_state,
        )

        record_id = str(record_data.get("id") or "").strip() or str(uuid4())

        # Check for duplicates
        for r in _mem_store_8.records.values():
            if (
                r.batch_id == batch_id
                and r.status == "ACTIVE"
                and r.id != record_id
                and r.supply_type == supply_type
                and r.record_type == rec_type
            ):
                if supply_type == "B2B" and r.supplier_gstin == supplier_gstin:
                    raise Gstr8DuplicateError(
                        f"Duplicate B2B record for supplier {supplier_gstin} in {rec_type} table"
                    )
                if supply_type == "B2C" and r.pos == pos:
                    raise Gstr8DuplicateError(
                        f"Duplicate B2C record for Place of Supply {pos} in {rec_type} table"
                    )

        # Allow user overrides for tax amounts if explicitly provided
        tcs_igst = float(record_data.get("tcs_igst") if "tcs_igst" in record_data else calc.tcs_igst)
        tcs_cgst = float(record_data.get("tcs_cgst") if "tcs_cgst" in record_data else calc.tcs_cgst)
        tcs_sgst = float(record_data.get("tcs_sgst") if "tcs_sgst" in record_data else calc.tcs_sgst)

        rec = Gstr8RecordData(
            id=record_id,
            batch_id=batch_id,
            firm_id=batch.firm_id,
            client_gstin_id=batch.client_gstin_id,
            period=batch.period,
            supply_type=supply_type,
            record_type=rec_type,
            pos=pos,
            supplier_gstin=supplier_gstin,
            gross_supplies=gross_val,
            returned_supplies=ret_val,
            net_supplies=float(calc.net_supplies),
            tcs_rate=float(calc.rate_structure.total_rate_pct),
            tcs_igst=tcs_igst,
            tcs_cgst=tcs_cgst,
            tcs_sgst=tcs_sgst,
            original_period=record_data.get("original_period"),
            original_supplier_gstin=record_data.get("original_supplier_gstin"),
            original_pos=record_data.get("original_pos"),
            tax_deposited=float(record_data.get("tax_deposited") or 0.0),
            status="ACTIVE",
        )

        _mem_store_8.records[record_id] = rec

        batch_records = [r for r in _mem_store_8.records.values() if r.batch_id == batch_id and r.status == "ACTIVE"]
        _recalculate_batch_totals_8(batch, batch_records)

        if batch.status in ("APPROVED", "UNDER_REVIEW"):
            batch.status = "PREPARED"

        return copy.deepcopy(rec.__dict__)


def delete_gstr8_record_sync(
    sb: Any,
    *,
    batch_id: str,
    record_id: str,
    user_id: Optional[str] = None,
) -> bool:
    """Soft delete a GSTR-8 TCS record."""
    with _mem_store_8._lock:
        batch = _mem_store_8.batches.get(batch_id)
        if not batch:
            raise Gstr8Error(f"Batch {batch_id} not found")

        if batch.status in ("SAVED", "FILED"):
            raise Gstr8ValidationError(f"Cannot modify batch in status {batch.status}")

        rec = _mem_store_8.records.get(record_id)
        if not rec or rec.batch_id != batch_id:
            return False

        rec.status = "DELETED"
        rec.updated_at = datetime.now(timezone.utc).isoformat()

        batch_records = [r for r in _mem_store_8.records.values() if r.batch_id == batch_id and r.status == "ACTIVE"]
        _recalculate_batch_totals_8(batch, batch_records)

        if batch.status in ("APPROVED", "UNDER_REVIEW"):
            batch.status = "PREPARED"

        return True


def get_batch_summary_sync(
    sb: Any,
    *,
    batch_id: str,
) -> dict[str, Any]:
    """Retrieve complete GSTR-8 batch summary with tables, calculations, and exceptions."""
    with _mem_store_8._lock:
        batch = _mem_store_8.batches.get(batch_id)
        if not batch:
            raise Gstr8Error(f"Batch {batch_id} not found")

        records = [
            copy.deepcopy(r.__dict__)
            for r in _mem_store_8.records.values()
            if r.batch_id == batch_id and r.status == "ACTIVE"
        ]

        table3_b2b = [r for r in records if r["record_type"] == "ORIGINAL" and r["supply_type"] == "B2B"]
        table3_b2c = [r for r in records if r["record_type"] == "ORIGINAL" and r["supply_type"] == "B2C"]
        table4_b2b = [r for r in records if r["record_type"] == "AMENDMENT" and r["supply_type"] == "B2B"]
        table4_b2c = [r for r in records if r["record_type"] == "AMENDMENT" and r["supply_type"] == "B2C"]

        exceptions: list[dict[str, Any]] = []
        for r in records:
            if r["net_supplies"] < 0:
                exceptions.append({
                    "record_id": r["id"],
                    "supplier_gstin": r.get("supplier_gstin"),
                    "pos": r["pos"],
                    "category": "NEGATIVE_NET_SUPPLIES",
                    "reason": f"Returned supplies (₹{r['returned_supplies']:,.2f}) exceed gross supplies (₹{r['gross_supplies']:,.2f}).",
                })

        total_tcs = batch.total_tcs_igst + batch.total_tcs_cgst + batch.total_tcs_sgst
        deposit_variance = round(total_tcs - batch.total_tcs_deposited, 2)
        if abs(deposit_variance) > 0.01:
            exceptions.append({
                "category": "DEPOSIT_DISCREPANCY",
                "reason": (
                    f"Total TCS calculated (₹{total_tcs:,.2f}) differs from tax deposited "
                    f"(₹{batch.total_tcs_deposited:,.2f}) by ₹{deposit_variance:,.2f}."
                ),
            })

        rates = get_applicable_tcs_rates(batch.period)

        return {
            "batch": copy.deepcopy(batch.__dict__),
            "table3_b2b": table3_b2b,
            "table3_b2c": table3_b2c,
            "table4_b2b": table4_b2b,
            "table4_b2c": table4_b2c,
            "applicable_rates": {
                "total_pct": float(rates.total_rate_pct),
                "cgst_pct": float(rates.cgst_rate * 100),
                "sgst_pct": float(rates.sgst_rate * 100),
                "igst_pct": float(rates.igst_rate * 100),
                "reference": rates.notification_reference,
            },
            "total_tcs_liability": total_tcs,
            "deposit_variance": deposit_variance,
            "exceptions": exceptions,
        }


def build_gstr8_offline_json(
    sb: Any,
    *,
    batch_id: str,
) -> dict[str, Any]:
    """Generate official GSTN-compliant Form GSTR-8 offline JSON."""
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]

    parts = batch["period"].split("-")
    fp = f"{parts[1]}{parts[0]}" if len(parts) == 2 else batch["period"]

    tcs_list = []
    for r in summary["table3_b2b"]:
        tcs_list.append({
            "gstin_supp": r["supplier_gstin"],
            "gross_val": float(r["gross_supplies"]),
            "ret_val": float(r["returned_supplies"]),
            "net_val": float(r["net_supplies"]),
            "iamt": float(r["tcs_igst"]),
            "camt": float(r["tcs_cgst"]),
            "samt": float(r["tcs_sgst"]),
        })

    tcs_b2c_list = []
    for r in summary["table3_b2c"]:
        tcs_b2c_list.append({
            "pos": r["pos"],
            "gross_val": float(r["gross_supplies"]),
            "ret_val": float(r["returned_supplies"]),
            "net_val": float(r["net_supplies"]),
            "iamt": float(r["tcs_igst"]),
            "camt": float(r["tcs_cgst"]),
            "samt": float(r["tcs_sgst"]),
        })

    tcsa_list = []
    for r in summary["table4_b2b"]:
        orig_fp = r.get("original_period") or batch["period"]
        omth = f"{orig_fp.split('-')[1]}{orig_fp.split('-')[0]}" if "-" in orig_fp else orig_fp
        tcsa_list.append({
            "ogstin": r.get("original_supplier_gstin") or r["supplier_gstin"],
            "omth": omth,
            "gstin_supp": r["supplier_gstin"],
            "gross_val": float(r["gross_supplies"]),
            "ret_val": float(r["returned_supplies"]),
            "net_val": float(r["net_supplies"]),
            "iamt": float(r["tcs_igst"]),
            "camt": float(r["tcs_cgst"]),
            "samt": float(r["tcs_sgst"]),
        })

    tcsa_b2c_list = []
    for r in summary["table4_b2c"]:
        orig_fp = r.get("original_period") or batch["period"]
        omth = f"{orig_fp.split('-')[1]}{orig_fp.split('-')[0]}" if "-" in orig_fp else orig_fp
        tcsa_b2c_list.append({
            "opos": r.get("original_pos") or r["pos"],
            "omth": omth,
            "pos": r["pos"],
            "gross_val": float(r["gross_supplies"]),
            "ret_val": float(r["returned_supplies"]),
            "net_val": float(r["net_supplies"]),
            "iamt": float(r["tcs_igst"]),
            "camt": float(r["tcs_cgst"]),
            "samt": float(r["tcs_sgst"]),
        })

    payload: dict[str, Any] = {
        "gstin": batch["gstin"],
        "fp": fp,
        "tcs": tcs_list,
    }
    if tcs_b2c_list:
        payload["tcs_b2c"] = tcs_b2c_list
    if tcsa_list:
        payload["tcsa"] = tcsa_list
    if tcsa_b2c_list:
        payload["tcsa_b2c"] = tcsa_b2c_list

    return payload
