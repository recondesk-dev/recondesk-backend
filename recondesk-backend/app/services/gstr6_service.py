"""Form GSTR-6 Service (Input Service Distributor Compliance).

Manages:
- GSTR-6 Batches, Table 3 Inward invoices & credit/debit notes.
- Table 4 Eligible vs Ineligible ITC segregation (Section 17(5)).
- Table 5 ISD Credit Distribution to recipient distinct persons (Rule 39).
- Table 6B Amendments to distributed credit.
- Over-distribution and duplicate prevention.
- Cryptographic figures digest binding.
- GSTN offline JSON generation.
"""

from __future__ import annotations

import copy
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

from app.rules.gstr6_rules import (
    distribute_isd_credit,
    extract_state_code,
    validate_distinct_persons,
)
from app.services.pre_filing_validator import compute_figures_digest

_log = logging.getLogger(__name__)


class Gstr6Error(Exception):
    pass


class Gstr6ValidationError(Gstr6Error):
    pass


class Gstr6DuplicateError(Gstr6Error):
    pass


class Gstr6OverDistributionError(Gstr6Error):
    pass


@dataclass
class Gstr6BatchData:
    id: str
    firm_id: str
    client_gstin_id: str
    gstin: str
    period: str
    status: str
    figures_digest: str
    total_inward_records: int = 0
    total_distribution_records: int = 0
    total_eligible_itc: float = 0.0
    total_ineligible_itc: float = 0.0
    total_distributed_itc: float = 0.0
    gstn_reference_id: Optional[str] = None
    gstn_status: Optional[str] = None
    arn: Optional[str] = None
    filing_run_id: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Gstr6InwardRecordData:
    id: str
    batch_id: str
    firm_id: str
    client_gstin_id: str
    supplier_gstin: str
    invoice_number: str
    invoice_date: str
    invoice_value: float
    taxable_value: float
    igst: float
    cgst: float
    sgst: float
    cess: float
    is_eligible: bool
    ineligibility_reason: Optional[str] = None
    status: str = "ACTIVE"
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Gstr6DistributionRecordData:
    id: str
    batch_id: str
    firm_id: str
    client_gstin_id: str
    recipient_gstin: str
    recipient_state: str
    is_eligible: bool
    record_type: str  # "ORIGINAL" or "AMENDMENT"
    distributed_igst: float
    distributed_cgst: float
    distributed_sgst: float
    total_distributed: float
    original_cgst_converted_to_igst: float = 0.0
    original_sgst_converted_to_igst: float = 0.0
    original_period: Optional[str] = None
    original_recipient_gstin: Optional[str] = None
    turnover: float = 0.0
    status: str = "ACTIVE"
    created_at: str = ""
    updated_at: str = ""


class _Gstr6Store:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._batches: dict[str, Gstr6BatchData] = {}
        self._inward: dict[str, Gstr6InwardRecordData] = {}
        self._distributions: dict[str, Gstr6DistributionRecordData] = {}

    def _batch_key(self, firm_id: str, client_gstin_id: str, period: str) -> str:
        return f"{firm_id}:{client_gstin_id}:{period}"

    def get_batch(self, batch_id: str) -> Optional[Gstr6BatchData]:
        with self._lock:
            return self._batches.get(batch_id)

    def find_batch(self, firm_id: str, client_gstin_id: str, period: str) -> Optional[Gstr6BatchData]:
        with self._lock:
            for b in self._batches.values():
                if b.firm_id == firm_id and b.client_gstin_id == client_gstin_id and b.period == period:
                    return b
            return None

    def put_batch(self, batch: Gstr6BatchData) -> None:
        with self._lock:
            self._batches[batch.id] = batch

    def put_inward(self, rec: Gstr6InwardRecordData) -> None:
        with self._lock:
            self._inward[rec.id] = rec

    def list_inward(self, batch_id: str) -> list[Gstr6InwardRecordData]:
        with self._lock:
            return [r for r in self._inward.values() if r.batch_id == batch_id and r.status == "ACTIVE"]

    def put_distribution(self, rec: Gstr6DistributionRecordData) -> None:
        with self._lock:
            self._distributions[rec.id] = rec

    def list_distributions(self, batch_id: str) -> list[Gstr6DistributionRecordData]:
        with self._lock:
            return [r for r in self._distributions.values() if r.batch_id == batch_id and r.status == "ACTIVE"]

    def delete_distribution(self, dist_id: str) -> None:
        with self._lock:
            if dist_id in self._distributions:
                self._distributions[dist_id].status = "DELETED"

    def delete_inward(self, inward_id: str) -> None:
        with self._lock:
            if inward_id in self._inward:
                self._inward[inward_id].status = "DELETED"

    def clear(self) -> None:
        with self._lock:
            self._batches.clear()
            self._inward.clear()
            self._distributions.clear()


_gstr6_store = _Gstr6Store()


def reset_gstr6_store_for_testing() -> None:
    _gstr6_store.clear()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_or_create_batch_sync(
    sb: Any,
    *,
    firm_id: str,
    client_gstin_id: str,
    gstin: str,
    period: str,
    user_id: Optional[str] = None,
) -> Gstr6BatchData:
    existing = _gstr6_store.find_batch(firm_id, client_gstin_id, period)
    if existing:
        return existing

    batch = Gstr6BatchData(
        id=str(uuid4()),
        firm_id=firm_id,
        client_gstin_id=client_gstin_id,
        gstin=gstin.strip().upper(),
        period=period.strip(),
        status="DRAFT",
        figures_digest="",
        created_by=user_id,
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    _gstr6_store.put_batch(batch)
    return batch


def add_or_update_inward_invoice_sync(
    sb: Any,
    *,
    batch_id: str,
    record_data: dict[str, Any],
    user_id: Optional[str] = None,
) -> Gstr6InwardRecordData:
    batch = _gstr6_store.get_batch(batch_id)
    if not batch:
        raise Gstr6Error(f"Batch '{batch_id}' not found.")

    supp_gstin = str(record_data.get("supplier_gstin") or "").strip().upper()
    inv_num = str(record_data.get("invoice_number") or "").strip().upper()

    existing = _gstr6_store.list_inward(batch_id)
    rec_id = record_data.get("id")

    for r in existing:
        if r.supplier_gstin == supp_gstin and r.invoice_number == inv_num and r.id != rec_id:
            raise Gstr6DuplicateError(f"Duplicate inward invoice '{inv_num}' for supplier '{supp_gstin}'.")

    now = _now_iso()
    rec = Gstr6InwardRecordData(
        id=str(rec_id or uuid4()),
        batch_id=batch_id,
        firm_id=batch.firm_id,
        client_gstin_id=batch.client_gstin_id,
        supplier_gstin=supp_gstin,
        invoice_number=inv_num,
        invoice_date=str(record_data.get("invoice_date") or ""),
        invoice_value=float(record_data.get("invoice_value") or 0.0),
        taxable_value=float(record_data.get("taxable_value") or 0.0),
        igst=float(record_data.get("igst") or 0.0),
        cgst=float(record_data.get("cgst") or 0.0),
        sgst=float(record_data.get("sgst") or 0.0),
        cess=float(record_data.get("cess") or 0.0),
        is_eligible=bool(record_data.get("is_eligible", True)),
        ineligibility_reason=record_data.get("ineligibility_reason"),
        created_at=now,
        updated_at=now,
    )
    _gstr6_store.put_inward(rec)
    recompute_batch_sync(sb, batch_id=batch_id)
    return rec


def delete_inward_invoice_sync(sb: Any, *, batch_id: str, invoice_id: str) -> None:
    _gstr6_store.delete_inward(invoice_id)
    recompute_batch_sync(sb, batch_id=batch_id)


def execute_isd_distribution_sync(
    sb: Any,
    *,
    batch_id: str,
    recipient_turnovers: list[dict[str, Any]],
    user_id: Optional[str] = None,
) -> list[Gstr6DistributionRecordData]:
    """Execute statutory Rule 39 credit distribution across recipient distinct persons."""
    batch = _gstr6_store.get_batch(batch_id)
    if not batch:
        raise Gstr6Error(f"Batch '{batch_id}' not found.")

    inwards = _gstr6_store.list_inward(batch_id)

    # Calculate available pools
    el_igst = sum(r.igst for r in inwards if r.is_eligible)
    el_cgst = sum(r.cgst for r in inwards if r.is_eligible)
    el_sgst = sum(r.sgst for r in inwards if r.is_eligible)

    inel_igst = sum(r.igst for r in inwards if not r.is_eligible)
    inel_cgst = sum(r.cgst for r in inwards if not r.is_eligible)
    inel_sgst = sum(r.sgst for r in inwards if not r.is_eligible)

    created_records: list[Gstr6DistributionRecordData] = []
    now = _now_iso()

    # Clear existing distributions for this batch to re-distribute
    with _gstr6_store._lock:
        for d in list(_gstr6_store._distributions.values()):
            if d.batch_id == batch_id:
                d.status = "DELETED"

    # Distribute Eligible ITC
    if (el_igst + el_cgst + el_sgst) > 0:
        res_el = distribute_isd_credit(
            isd_gstin=batch.gstin,
            pool_igst=el_igst,
            pool_cgst=el_cgst,
            pool_sgst=el_sgst,
            is_eligible=True,
            recipient_turnovers=recipient_turnovers,
        )
        if res_el.is_over_distributed:
            raise Gstr6OverDistributionError(res_el.error_message)

        for d in res_el.distributions:
            rec = Gstr6DistributionRecordData(
                id=str(uuid4()),
                batch_id=batch_id,
                firm_id=batch.firm_id,
                client_gstin_id=batch.client_gstin_id,
                recipient_gstin=d.recipient_gstin,
                recipient_state=d.recipient_state,
                is_eligible=True,
                record_type="ORIGINAL",
                distributed_igst=float(d.distributed_igst),
                distributed_cgst=float(d.distributed_cgst),
                distributed_sgst=float(d.distributed_sgst),
                total_distributed=float(d.total_distributed),
                original_cgst_converted_to_igst=float(d.original_cgst_converted_to_igst),
                original_sgst_converted_to_igst=float(d.original_sgst_converted_to_igst),
                created_at=now,
                updated_at=now,
            )
            _gstr6_store.put_distribution(rec)
            created_records.append(rec)

    # Distribute Ineligible ITC (Section 17(5))
    if (inel_igst + inel_cgst + inel_sgst) > 0:
        res_inel = distribute_isd_credit(
            isd_gstin=batch.gstin,
            pool_igst=inel_igst,
            pool_cgst=inel_cgst,
            pool_sgst=inel_sgst,
            is_eligible=False,
            recipient_turnovers=recipient_turnovers,
        )
        if res_inel.is_over_distributed:
            raise Gstr6OverDistributionError(res_inel.error_message)

        for d in res_inel.distributions:
            rec = Gstr6DistributionRecordData(
                id=str(uuid4()),
                batch_id=batch_id,
                firm_id=batch.firm_id,
                client_gstin_id=batch.client_gstin_id,
                recipient_gstin=d.recipient_gstin,
                recipient_state=d.recipient_state,
                is_eligible=False,
                record_type="ORIGINAL",
                distributed_igst=float(d.distributed_igst),
                distributed_cgst=float(d.distributed_cgst),
                distributed_sgst=float(d.distributed_sgst),
                total_distributed=float(d.total_distributed),
                original_cgst_converted_to_igst=float(d.original_cgst_converted_to_igst),
                original_sgst_converted_to_igst=float(d.original_sgst_converted_to_igst),
                created_at=now,
                updated_at=now,
            )
            _gstr6_store.put_distribution(rec)
            created_records.append(rec)

    recompute_batch_sync(sb, batch_id=batch_id)
    return created_records


def add_distribution_amendment_sync(
    sb: Any,
    *,
    batch_id: str,
    record_data: dict[str, Any],
    user_id: Optional[str] = None,
) -> Gstr6DistributionRecordData:
    batch = _gstr6_store.get_batch(batch_id)
    if not batch:
        raise Gstr6Error(f"Batch '{batch_id}' not found.")

    rec_gstin = str(record_data.get("recipient_gstin") or "").strip().upper()
    orig_gstin = str(record_data.get("original_recipient_gstin") or rec_gstin).strip().upper()
    orig_period = str(record_data.get("original_period") or "").strip()

    now = _now_iso()
    rec = Gstr6DistributionRecordData(
        id=str(record_data.get("id") or uuid4()),
        batch_id=batch_id,
        firm_id=batch.firm_id,
        client_gstin_id=batch.client_gstin_id,
        recipient_gstin=rec_gstin,
        recipient_state=extract_state_code(rec_gstin),
        is_eligible=bool(record_data.get("is_eligible", True)),
        record_type="AMENDMENT",
        distributed_igst=float(record_data.get("distributed_igst") or 0.0),
        distributed_cgst=float(record_data.get("distributed_cgst") or 0.0),
        distributed_sgst=float(record_data.get("distributed_sgst") or 0.0),
        total_distributed=float(record_data.get("total_distributed") or 0.0),
        original_period=orig_period,
        original_recipient_gstin=orig_gstin,
        created_at=now,
        updated_at=now,
    )
    _gstr6_store.put_distribution(rec)
    recompute_batch_sync(sb, batch_id=batch_id)
    return rec


def recompute_batch_sync(sb: Any, *, batch_id: str) -> Gstr6BatchData:
    batch = _gstr6_store.get_batch(batch_id)
    if not batch:
        raise Gstr6Error(f"Batch '{batch_id}' not found.")

    inwards = _gstr6_store.list_inward(batch_id)
    distributions = _gstr6_store.list_distributions(batch_id)

    tot_el = sum(r.igst + r.cgst + r.sgst for r in inwards if r.is_eligible)
    tot_inel = sum(r.igst + r.cgst + r.sgst for r in inwards if not r.is_eligible)
    tot_dist = sum(d.total_distributed for d in distributions)

    payload_for_digest = {
        "gstin": batch.gstin,
        "period": batch.period,
        "inward_count": len(inwards),
        "total_eligible_itc": round(tot_el, 2),
        "total_ineligible_itc": round(tot_inel, 2),
        "total_distributed": round(tot_dist, 2),
        "distributions": [
            {
                "rec_gstin": d.recipient_gstin,
                "el": d.is_eligible,
                "igst": d.distributed_igst,
                "cgst": d.distributed_cgst,
                "sgst": d.distributed_sgst,
            }
            for d in sorted(distributions, key=lambda x: (x.recipient_gstin, x.is_eligible))
        ],
    }

    batch.total_inward_records = len(inwards)
    batch.total_distribution_records = len(distributions)
    batch.total_eligible_itc = round(tot_el, 2)
    batch.total_ineligible_itc = round(tot_inel, 2)
    batch.total_distributed_itc = round(tot_dist, 2)
    batch.figures_digest = compute_figures_digest(payload_for_digest)
    batch.updated_at = _now_iso()
    _gstr6_store.put_batch(batch)
    return batch


def get_batch_summary_sync(sb: Any, *, batch_id: str) -> dict[str, Any]:
    batch = recompute_batch_sync(sb, batch_id=batch_id)
    inwards = _gstr6_store.list_inward(batch_id)
    distributions = _gstr6_store.list_distributions(batch_id)

    orig_dist = [d for d in distributions if d.record_type == "ORIGINAL"]
    amend_dist = [d for d in distributions if d.record_type == "AMENDMENT"]

    available_pool = batch.total_eligible_itc + batch.total_ineligible_itc
    variance = round(batch.total_distributed_itc - available_pool, 2)

    tot_pool_cgst = sum(r.cgst for r in inwards)
    tot_pool_sgst = sum(r.sgst for r in inwards)
    tot_pool_igst = sum(r.igst for r in inwards)
    tot_dist_cgst = sum(d.distributed_cgst for d in distributions)
    tot_dist_sgst = sum(d.distributed_sgst for d in distributions)
    tot_dist_igst = sum(d.distributed_igst for d in distributions)

    return {
        "batch": copy.deepcopy(batch.__dict__),
        "table3_inward": [copy.deepcopy(r.__dict__) for r in inwards],
        "table4_itc_pool": {
            "eligible_itc": batch.total_eligible_itc,
            "ineligible_itc": batch.total_ineligible_itc,
            "total_available": available_pool,
        },
        "pool_summary": {
            "total_pool_cgst": tot_pool_cgst,
            "total_pool_sgst": tot_pool_sgst,
            "total_pool_igst": tot_pool_igst,
            "total_eligible_pool": batch.total_eligible_itc,
            "total_ineligible_pool": batch.total_ineligible_itc,
        },
        "distribution_summary": {
            "total_distributed_igst": tot_dist_igst,
            "total_eligible_distributed_igst": sum(d.distributed_igst for d in distributions if d.is_eligible),
            "total_ineligible_distributed_igst": sum(d.distributed_igst for d in distributions if not d.is_eligible),
            "total_distributed_cgst": tot_dist_cgst,
            "total_distributed_sgst": tot_dist_sgst,
            "total_distributed": batch.total_distributed_itc,
        },
        "table5_distribution": [copy.deepcopy(d.__dict__) for d in orig_dist],
        "table6b_amendments": [copy.deepcopy(d.__dict__) for d in amend_dist],
        "variance_distributed_vs_available": variance,
        "is_over_distributed": variance > 0.0,
        "downstream_guarantee": {
            "destination_ledger": "GSTR-2B Table 4(A)(4) of recipient branches",
            "isd_head_office_liability": 0.00,
            "status": "GSTN_CONFIRMED" if batch.status == "FILED" and getattr(batch, "filing_acknowledgement", None) else "PENDING_GSTR6_FILING_CONFIRMATION",
            "is_confirmed_gstr2b_itc": bool(batch.status == "FILED" and getattr(batch, "filing_acknowledgement", None)),
            "premature_recognition_guarantee": "Distributed credit is provisional/allocated until Form GSTR-6 filing acknowledgement is verified from GSTN.",
        },
        "downstream_destination": "GSTR-2B Table 4(A)(4) of Recipient Distinct Persons",
    }


def build_gstr6_offline_json(sb: Any, *, batch_id: str) -> dict[str, Any]:
    """Generate official GSTN Form GSTR-6 offline JSON.
    
    Structure:
    {
      "gstin": "...",
      "fp": "MMYYYY",
      "isd": [ ... ],
      "isda": [ ... ]
    }
    """
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]

    parts = batch["period"].split("-")
    fp = f"{parts[1]}{parts[0]}" if len(parts) == 2 else batch["period"]

    isd_list = []
    for d in summary["table5_distribution"]:
        isd_list.append({
            "cpt_gstin": d["recipient_gstin"],
            "state_cd": d["recipient_state"],
            "elg": "E" if d["is_eligible"] else "NE",
            "iamt": float(d["distributed_igst"]),
            "camt": float(d["distributed_cgst"]),
            "samt": float(d["distributed_sgst"]),
        })

    isda_list = []
    for d in summary["table6b_amendments"]:
        orig_fp = d.get("original_period") or batch["period"]
        omth = f"{orig_fp.split('-')[1]}{orig_fp.split('-')[0]}" if "-" in orig_fp else orig_fp
        isda_list.append({
            "ocpt_gstin": d.get("original_recipient_gstin") or d["recipient_gstin"],
            "omth": omth,
            "cpt_gstin": d["recipient_gstin"],
            "elg": "E" if d["is_eligible"] else "NE",
            "iamt": float(d["distributed_igst"]),
            "camt": float(d["distributed_cgst"]),
            "samt": float(d["distributed_sgst"]),
        })

    payload: dict[str, Any] = {
        "gstin": batch["gstin"],
        "fp": fp,
        "isd": isd_list,
    }
    if isda_list:
        payload["isda"] = isda_list

    return payload
