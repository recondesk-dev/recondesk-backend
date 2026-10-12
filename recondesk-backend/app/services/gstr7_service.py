"""Phase 4.2: Form GSTR-7 (TDS under Section 51) Compliance Engine.

Implements:
- Deductor & deductee GSTIN management
- Contract/payment-based TDS reconciliation
- Threshold validation (> ₹2,50,000 contract value)
- Section 51(1) Proviso exemption verification
- Intra-state (CGST+SGST) vs Inter-state (IGST) tax allocation
- Original (Table 3) and Amendment (Table 4) TDS records
- Duplicate deduction detection
- Deducted vs deposited tax reconciliation
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

from app.rules.gstr7_rules import (
    GSTR7_CONTRACT_THRESHOLD,
    TdsCalculationResult,
    calculate_gstr7_tds,
    evaluate_section_51_proviso,
    extract_state_code,
    validate_gstin_format,
)

_log = logging.getLogger(__name__)

GSTR7_BATCHES_TABLE = "gstr7_batches"
GSTR7_RECORDS_TABLE = "gstr7_records"
GSTR7_AUDIT_TABLE = "gstr7_audit_trail"


class Gstr7Error(Exception):
    """Base exception for GSTR-7 operations."""


class Gstr7ValidationError(Gstr7Error):
    """Validation or threshold constraint violation."""


class Gstr7DuplicateError(Gstr7Error):
    """Duplicate TDS record error."""


@dataclass
class Gstr7RecordData:
    id: str
    batch_id: str
    firm_id: str
    client_gstin_id: str
    period: str
    record_type: str  # "ORIGINAL" or "AMENDMENT"
    deductee_gstin: str
    contract_number: str = ""
    contract_value: float = 0.0
    payment_reference: str = ""
    payment_date: Optional[str] = None
    amount_paid: float = 0.0
    supplier_state: str = ""
    pos: str = ""
    tds_rate: float = 2.0
    tds_igst: float = 0.0
    tds_cgst: float = 0.0
    tds_sgst: float = 0.0
    original_period: Optional[str] = None
    original_deductee_gstin: Optional[str] = None
    tax_deposited: float = 0.0
    is_eligible_for_tds: bool = True
    ineligibility_reason: Optional[str] = None
    status: str = "ACTIVE"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Gstr7BatchData:
    id: str
    firm_id: str
    client_gstin_id: str
    gstin: str
    period: str
    status: str = "DRAFT"  # DRAFT, PREPARED, UNDER_REVIEW, APPROVED, REJECTED, SAVED, FILED
    figures_digest: str = ""
    total_records: int = 0
    total_amendments: int = 0
    total_amount_paid: float = 0.0
    total_tds_igst: float = 0.0
    total_tds_cgst: float = 0.0
    total_tds_sgst: float = 0.0
    total_tds_deposited: float = 0.0
    gstn_reference_id: Optional[str] = None
    gstn_status: Optional[str] = None
    arn: Optional[str] = None
    filing_run_id: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class _Gstr7MemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.batches: dict[str, Gstr7BatchData] = {}
        self.records: dict[str, Gstr7RecordData] = {}
        self.audits: list[dict[str, Any]] = []

    def reset(self) -> None:
        with self._lock:
            self.batches.clear()
            self.records.clear()
            self.audits.clear()


_mem_store = _Gstr7MemoryStore()


def reset_gstr7_memory_store_for_testing() -> None:
    _mem_store.reset()


def compute_gstr7_figures_digest(batch: Mapping[str, Any], records: list[Mapping[str, Any]]) -> str:
    """Deterministic SHA-256 digest binding GSTR-7 batch to exact record values."""
    sorted_recs = sorted(
        records,
        key=lambda r: (
            str(r.get("record_type") or ""),
            str(r.get("deductee_gstin") or ""),
            str(r.get("payment_reference") or ""),
            str(r.get("id") or ""),
        ),
    )
    payload = {
        "gstin": str(batch.get("gstin") or "").strip().upper(),
        "period": str(batch.get("period") or "").strip(),
        "total_amount_paid": f"{float(batch.get('total_amount_paid') or 0):.2f}",
        "total_tds_igst": f"{float(batch.get('total_tds_igst') or 0):.2f}",
        "total_tds_cgst": f"{float(batch.get('total_tds_cgst') or 0):.2f}",
        "total_tds_sgst": f"{float(batch.get('total_tds_sgst') or 0):.2f}",
        "records": [
            {
                "id": str(r.get("id") or ""),
                "record_type": str(r.get("record_type") or "ORIGINAL"),
                "deductee_gstin": str(r.get("deductee_gstin") or "").strip().upper(),
                "amount_paid": f"{float(r.get('amount_paid') or 0):.2f}",
                "tds_igst": f"{float(r.get('tds_igst') or 0):.2f}",
                "tds_cgst": f"{float(r.get('tds_cgst') or 0):.2f}",
                "tds_sgst": f"{float(r.get('tds_sgst') or 0):.2f}",
            }
            for r in sorted_recs
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _recalculate_batch_totals(batch: Gstr7BatchData, records: list[Gstr7RecordData]) -> None:
    tot_amt = Decimal("0.00")
    tot_igst = Decimal("0.00")
    tot_cgst = Decimal("0.00")
    tot_sgst = Decimal("0.00")
    tot_dep = Decimal("0.00")
    orig_cnt = 0
    amend_cnt = 0

    for r in records:
        if r.status != "ACTIVE":
            continue
        if r.record_type == "AMENDMENT":
            amend_cnt += 1
        else:
            orig_cnt += 1

        tot_amt += Decimal(str(r.amount_paid or 0))
        tot_igst += Decimal(str(r.tds_igst or 0))
        tot_cgst += Decimal(str(r.tds_cgst or 0))
        tot_sgst += Decimal(str(r.tds_sgst or 0))
        tot_dep += Decimal(str(r.tax_deposited or 0))

    batch.total_records = orig_cnt
    batch.total_amendments = amend_cnt
    batch.total_amount_paid = float(tot_amt.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    batch.total_tds_igst = float(tot_igst.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    batch.total_tds_cgst = float(tot_cgst.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    batch.total_tds_sgst = float(tot_sgst.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    batch.total_tds_deposited = float(tot_dep.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    batch.updated_at = datetime.now(timezone.utc).isoformat()

    # Refresh figures digest
    rec_dicts = [r.__dict__ for r in records if r.status == "ACTIVE"]
    batch.figures_digest = compute_gstr7_figures_digest(batch.__dict__, rec_dicts)


def get_or_create_batch_sync(
    sb: Any,
    *,
    firm_id: str,
    client_gstin_id: str,
    gstin: str,
    period: str,
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Retrieve existing GSTR-7 batch or create a new DRAFT batch."""
    clean_gstin = gstin.strip().upper()
    clean_period = period.strip()

    with _mem_store._lock:
        for b in _mem_store.batches.values():
            if (
                b.firm_id == firm_id
                and b.client_gstin_id == client_gstin_id
                and b.period == clean_period
            ):
                return copy.deepcopy(b.__dict__)

        new_batch = Gstr7BatchData(
            id=str(uuid4()),
            firm_id=firm_id,
            client_gstin_id=client_gstin_id,
            gstin=clean_gstin,
            period=clean_period,
            status="DRAFT",
            created_by=user_id,
        )
        _recalculate_batch_totals(new_batch, [])
        _mem_store.batches[new_batch.id] = new_batch
        return copy.deepcopy(new_batch.__dict__)


def add_or_update_gstr7_record_sync(
    sb: Any,
    *,
    batch_id: str,
    record_data: Mapping[str, Any],
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Add or update a TDS record in GSTR-7 (Table 3 or Table 4).

    Applies statutory Section 51 validation, duplicate detection, and recalculates totals.
    """
    with _mem_store._lock:
        batch = _mem_store.batches.get(batch_id)
        if not batch:
            raise Gstr7Error(f"GSTR-7 Batch {batch_id} not found")

        if batch.status in ("SAVED", "FILED"):
            raise Gstr7ValidationError(f"Cannot modify batch in status {batch.status}")

        deductee_gstin = str(record_data.get("deductee_gstin") or "").strip().upper()
        if not validate_gstin_format(deductee_gstin):
            raise Gstr7ValidationError(f"Invalid deductee GSTIN format: '{deductee_gstin}'")

        deductor_state = extract_state_code(batch.gstin)
        supplier_state = extract_state_code(deductee_gstin)
        pos = str(record_data.get("pos") or supplier_state).strip()

        contract_val = float(record_data.get("contract_value") or 0.0)
        amount_paid = float(record_data.get("amount_paid") or 0.0)
        rec_type = str(record_data.get("record_type") or "ORIGINAL").upper()
        payment_ref = str(record_data.get("payment_reference") or "").strip()

        # Run statutory calculation
        calc = calculate_gstr7_tds(
            contract_value=contract_val,
            amount_paid=amount_paid,
            deductor_state=deductor_state,
            supplier_state=supplier_state,
            pos=pos,
        )

        record_id = str(record_data.get("id") or "").strip() or str(uuid4())

        # Check for duplicates: Same deductee + payment_reference within batch
        for r in _mem_store.records.values():
            if (
                r.batch_id == batch_id
                and r.status == "ACTIVE"
                and r.id != record_id
                and r.record_type == rec_type
                and r.deductee_gstin == deductee_gstin
                and payment_ref
                and r.payment_reference.upper() == payment_ref.upper()
            ):
                raise Gstr7DuplicateError(
                    f"Duplicate TDS record for deductee {deductee_gstin} with payment reference '{payment_ref}'"
                )

        # Allow user overrides for tax amounts if provided and eligible, else use calculated
        tds_igst = float(record_data.get("tds_igst") if "tds_igst" in record_data else calc.tds_igst)
        tds_cgst = float(record_data.get("tds_cgst") if "tds_cgst" in record_data else calc.tds_cgst)
        tds_sgst = float(record_data.get("tds_sgst") if "tds_sgst" in record_data else calc.tds_sgst)

        rec = Gstr7RecordData(
            id=record_id,
            batch_id=batch_id,
            firm_id=batch.firm_id,
            client_gstin_id=batch.client_gstin_id,
            period=batch.period,
            record_type=rec_type,
            deductee_gstin=deductee_gstin,
            contract_number=str(record_data.get("contract_number") or ""),
            contract_value=contract_val,
            payment_reference=payment_ref,
            payment_date=record_data.get("payment_date"),
            amount_paid=amount_paid,
            supplier_state=supplier_state,
            pos=pos,
            tds_rate=float(record_data.get("tds_rate") or 2.0),
            tds_igst=tds_igst,
            tds_cgst=tds_cgst,
            tds_sgst=tds_sgst,
            original_period=record_data.get("original_period"),
            original_deductee_gstin=record_data.get("original_deductee_gstin"),
            tax_deposited=float(record_data.get("tax_deposited") or 0.0),
            is_eligible_for_tds=calc.is_eligible,
            ineligibility_reason=calc.ineligibility_reason,
            status="ACTIVE",
        )

        _mem_store.records[record_id] = rec

        # Recompute totals and digest
        batch_records = [r for r in _mem_store.records.values() if r.batch_id == batch_id and r.status == "ACTIVE"]
        _recalculate_batch_totals(batch, batch_records)

        # If batch was APPROVED or UNDER_REVIEW, revert to PREPARED due to modification
        if batch.status in ("APPROVED", "UNDER_REVIEW"):
            batch.status = "PREPARED"

        return copy.deepcopy(rec.__dict__)


def delete_gstr7_record_sync(
    sb: Any,
    *,
    batch_id: str,
    record_id: str,
    user_id: Optional[str] = None,
) -> bool:
    """Soft delete a GSTR-7 TDS record."""
    with _mem_store._lock:
        batch = _mem_store.batches.get(batch_id)
        if not batch:
            raise Gstr7Error(f"Batch {batch_id} not found")

        if batch.status in ("SAVED", "FILED"):
            raise Gstr7ValidationError(f"Cannot modify batch in status {batch.status}")

        rec = _mem_store.records.get(record_id)
        if not rec or rec.batch_id != batch_id:
            return False

        rec.status = "DELETED"
        rec.updated_at = datetime.now(timezone.utc).isoformat()

        batch_records = [r for r in _mem_store.records.values() if r.batch_id == batch_id and r.status == "ACTIVE"]
        _recalculate_batch_totals(batch, batch_records)

        if batch.status in ("APPROVED", "UNDER_REVIEW"):
            batch.status = "PREPARED"

        return True


def get_batch_summary_sync(
    sb: Any,
    *,
    batch_id: str,
) -> dict[str, Any]:
    """Retrieve complete GSTR-7 batch summary with records and statutory checks."""
    with _mem_store._lock:
        batch = _mem_store.batches.get(batch_id)
        if not batch:
            raise Gstr7Error(f"Batch {batch_id} not found")

        records = [
            copy.deepcopy(r.__dict__)
            for r in _mem_store.records.values()
            if r.batch_id == batch_id and r.status == "ACTIVE"
        ]

        # Categorize Table 3 vs Table 4
        table3_recs = [r for r in records if r["record_type"] == "ORIGINAL"]
        table4_recs = [r for r in records if r["record_type"] == "AMENDMENT"]

        # Exceptions & Discrepancies
        exceptions: list[dict[str, Any]] = []
        for r in records:
            if not r["is_eligible_for_tds"] and r["ineligibility_reason"]:
                exceptions.append({
                    "record_id": r["id"],
                    "deductee_gstin": r["deductee_gstin"],
                    "category": "STATUTORY_INELIGIBLE",
                    "reason": r["ineligibility_reason"],
                })

        total_tds = batch.total_tds_igst + batch.total_tds_cgst + batch.total_tds_sgst
        deposit_variance = round(total_tds - batch.total_tds_deposited, 2)
        if abs(deposit_variance) > 0.01:
            exceptions.append({
                "category": "DEPOSIT_DISCREPANCY",
                "reason": (
                    f"Total TDS calculated (₹{total_tds:,.2f}) differs from tax deposited "
                    f"(₹{batch.total_tds_deposited:,.2f}) by ₹{deposit_variance:,.2f}."
                ),
            })

        return {
            "batch": copy.deepcopy(batch.__dict__),
            "table3_original": table3_recs,
            "table4_amendments": table4_recs,
            "total_tds_liability": total_tds,
            "deposit_variance": deposit_variance,
            "exceptions": exceptions,
        }


def build_gstr7_offline_json(
    sb: Any,
    *,
    batch_id: str,
) -> dict[str, Any]:
    """Generate official GSTN-compliant Form GSTR-7 offline JSON.

    Conforms to GST offline tool structure:
    {
      "gstin": "...",
      "fp": "MMYYYY",
      "tds": [ ... ],
      "tdsa": [ ... ]
    }
    """
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]

    # Convert YYYY-MM to MMYYYY
    parts = batch["period"].split("-")
    fp = f"{parts[1]}{parts[0]}" if len(parts) == 2 else batch["period"]

    tds_list = []
    for r in summary["table3_original"]:
        tds_list.append({
            "gstin_ded": r["deductee_gstin"],
            "amt_paid": float(r["amount_paid"]),
            "iamt": float(r["tds_igst"]),
            "camt": float(r["tds_cgst"]),
            "samt": float(r["tds_sgst"]),
        })

    tdsa_list = []
    for r in summary["table4_amendments"]:
        orig_fp = r.get("original_period") or batch["period"]
        if "-" in orig_fp:
            oparts = orig_fp.split("-")
            omth = f"{oparts[1]}{oparts[0]}"
        else:
            omth = orig_fp

        tdsa_list.append({
            "ogstin": r.get("original_deductee_gstin") or r["deductee_gstin"],
            "omth": omth,
            "gstin_ded": r["deductee_gstin"],
            "amt_paid": float(r["amount_paid"]),
            "iamt": float(r["tds_igst"]),
            "camt": float(r["tds_cgst"]),
            "samt": float(r["tds_sgst"]),
        })

    payload: dict[str, Any] = {
        "gstin": batch["gstin"],
        "fp": fp,
        "tds": tds_list,
    }
    if tdsa_list:
        payload["tdsa"] = tdsa_list

    return payload
