"""Form GSTR-5A Service (OIDAR Services Compliance).

Manages:
- GSTR-5A Batches, Overseas supplier profiles (Section 14 of IGST Act).
- Table 5 Taxable outward supplies to non-taxable online recipients in India.
- Table 5A Amendments to earlier tax periods.
- 18% IGST statutory calculation and zero ITC invariant.
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

from app.rules.gstr5a_rules import (
    OIDAR_DUE_DATE_DAY,
    compute_oidar_tax_for_supply,
    summarize_gstr5a_supplies,
)
from app.services.pre_filing_validator import compute_figures_digest

_log = logging.getLogger(__name__)


class Gstr5aError(Exception):
    pass


class Gstr5aValidationError(Gstr5aError):
    pass


class Gstr5aDuplicateError(Gstr5aError):
    pass


@dataclass
class Gstr5aBatchData:
    id: str
    firm_id: str
    client_gstin_id: str
    gstin: str
    period: str
    status: str
    figures_digest: str
    total_taxable_value: float = 0.0
    total_igst: float = 0.0
    total_cess: float = 0.0
    net_tax_payable: float = 0.0
    total_records: int = 0
    total_amendments: int = 0
    gstn_reference_id: Optional[str] = None
    gstn_status: Optional[str] = None
    arn: Optional[str] = None
    filing_run_id: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Gstr5aRecordData:
    id: str
    batch_id: str
    firm_id: str
    client_gstin_id: str
    record_type: str  # "ORIGINAL" or "AMENDMENT"
    pos: str
    taxable_value: float
    rate_pct: float
    igst: float
    cess: float
    original_period: Optional[str] = None
    original_pos: Optional[str] = None
    status: str = "ACTIVE"
    created_at: str = ""
    updated_at: str = ""


class _Gstr5aStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._batches: dict[str, Gstr5aBatchData] = {}
        self._records: dict[str, Gstr5aRecordData] = {}

    def get_batch(self, batch_id: str) -> Optional[Gstr5aBatchData]:
        with self._lock:
            return self._batches.get(batch_id)

    def find_batch(self, firm_id: str, client_gstin_id: str, period: str) -> Optional[Gstr5aBatchData]:
        with self._lock:
            for b in self._batches.values():
                if b.firm_id == firm_id and b.client_gstin_id == client_gstin_id and b.period == period:
                    return b
            return None

    def put_batch(self, batch: Gstr5aBatchData) -> None:
        with self._lock:
            self._batches[batch.id] = batch

    def put_record(self, rec: Gstr5aRecordData) -> None:
        with self._lock:
            self._records[rec.id] = rec

    def list_records(self, batch_id: str) -> list[Gstr5aRecordData]:
        with self._lock:
            return [r for r in self._records.values() if r.batch_id == batch_id and r.status == "ACTIVE"]

    def delete_record(self, rec_id: str) -> None:
        with self._lock:
            if rec_id in self._records:
                self._records[rec_id].status = "DELETED"

    def clear(self) -> None:
        with self._lock:
            self._batches.clear()
            self._records.clear()


_gstr5a_store = _Gstr5aStore()


def reset_gstr5a_store_for_testing() -> None:
    _gstr5a_store.clear()


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
) -> Gstr5aBatchData:
    existing = _gstr5a_store.find_batch(firm_id, client_gstin_id, period)
    if existing:
        return existing

    batch = Gstr5aBatchData(
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
    _gstr5a_store.put_batch(batch)
    return batch


def add_or_update_record_sync(
    sb: Any,
    *,
    batch_id: str,
    record_data: dict[str, Any],
    user_id: Optional[str] = None,
) -> Gstr5aRecordData:
    batch = _gstr5a_store.get_batch(batch_id)
    if not batch:
        raise Gstr5aError(f"Batch '{batch_id}' not found.")

    pos = str(record_data.get("pos") or "").strip()
    rec_type = str(record_data.get("record_type") or "ORIGINAL").upper()

    existing = _gstr5a_store.list_records(batch_id)
    rec_id = record_data.get("id")

    for r in existing:
        if r.pos == pos and r.record_type == rec_type and r.id != rec_id:
            if rec_type == "ORIGINAL":
                raise Gstr5aDuplicateError(f"Duplicate Table 5 entry for Place of Supply '{pos}'.")

    t_val = float(record_data.get("taxable_value") or 0.0)
    r_pct = float(record_data.get("rate_pct") or 18.0)
    cess_val = float(record_data.get("cess") or 0.0)

    igst_calc, cess_calc, _ = compute_oidar_tax_for_supply(
        taxable_value=t_val,
        rate_pct=r_pct,
        cess_amount=cess_val,
    )

    now = _now_iso()
    rec = Gstr5aRecordData(
        id=str(rec_id or uuid4()),
        batch_id=batch_id,
        firm_id=batch.firm_id,
        client_gstin_id=batch.client_gstin_id,
        record_type=rec_type,
        pos=pos,
        taxable_value=t_val,
        rate_pct=r_pct,
        igst=float(igst_calc),
        cess=float(cess_calc),
        original_period=record_data.get("original_period"),
        original_pos=record_data.get("original_pos"),
        created_at=now,
        updated_at=now,
    )
    _gstr5a_store.put_record(rec)
    recompute_batch_sync(sb, batch_id=batch_id)
    return rec


def delete_record_sync(sb: Any, *, batch_id: str, record_id: str) -> None:
    _gstr5a_store.delete_record(record_id)
    recompute_batch_sync(sb, batch_id=batch_id)


def recompute_batch_sync(sb: Any, *, batch_id: str) -> Gstr5aBatchData:
    batch = _gstr5a_store.get_batch(batch_id)
    if not batch:
        raise Gstr5aError(f"Batch '{batch_id}' not found.")

    records = _gstr5a_store.list_records(batch_id)
    table5 = [r.__dict__ for r in records if r.record_type == "ORIGINAL"]
    table5a = [r.__dict__ for r in records if r.record_type == "AMENDMENT"]

    summary = summarize_gstr5a_supplies(
        period=batch.period,
        table5_supplies=table5,
        table5a_amendments=table5a,
    )

    batch.total_taxable_value = float(summary.total_taxable_value)
    batch.total_igst = float(summary.total_igst)
    batch.total_cess = float(summary.total_cess)
    batch.net_tax_payable = float(summary.net_tax_payable)
    batch.total_records = len(table5)
    batch.total_amendments = len(table5a)

    payload_for_digest = {
        "gstin": batch.gstin,
        "period": batch.period,
        "total_taxable_value": batch.total_taxable_value,
        "total_igst": batch.total_igst,
        "total_cess": batch.total_cess,
        "net_tax_payable": batch.net_tax_payable,
        "supplies": sorted(
            [{"pos": r["pos"], "txval": r["taxable_value"], "igst": r["igst"]} for r in table5],
            key=lambda x: x["pos"],
        ),
    }
    batch.figures_digest = compute_figures_digest(payload_for_digest)
    batch.updated_at = _now_iso()
    _gstr5a_store.put_batch(batch)
    return batch


def get_batch_summary_sync(sb: Any, *, batch_id: str) -> dict[str, Any]:
    batch = recompute_batch_sync(sb, batch_id=batch_id)
    records = _gstr5a_store.list_records(batch_id)

    table5 = [copy.deepcopy(r.__dict__) for r in records if r.record_type == "ORIGINAL"]
    table5a = [copy.deepcopy(r.__dict__) for r in records if r.record_type == "AMENDMENT"]

    summary = summarize_gstr5a_supplies(
        period=batch.period,
        table5_supplies=table5,
        table5a_amendments=table5a,
    )

    return {
        "batch": copy.deepcopy(batch.__dict__),
        "tax_summary": copy.deepcopy(summary.__dict__),
        "table5_supplies": table5,
        "table5a_amendments": table5a,
        "statutory_checks": {
            "eligible_itc": 0.00,
            "applicable_tax_head": "IGST Only (Section 14 of IGST Act)",
            "due_date_day": OIDAR_DUE_DATE_DAY,
        },
    }


def build_gstr5a_offline_json(sb: Any, *, batch_id: str) -> dict[str, Any]:
    """Generate official GSTN Form GSTR-5A offline JSON."""
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]

    parts = batch["period"].split("-")
    fp = f"{parts[1]}{parts[0]}" if len(parts) == 2 else batch["period"]

    sec5 = []
    for r in summary["table5_supplies"]:
        sec5.append({
            "pos": r["pos"],
            "txval": float(r["taxable_value"]),
            "rt": float(r["rate_pct"]),
            "iamt": float(r["igst"]),
            "csamt": float(r["cess"]),
        })

    sec5a = []
    for r in summary["table5a_amendments"]:
        orig_fp = r.get("original_period") or batch["period"]
        omth = f"{orig_fp.split('-')[1]}{orig_fp.split('-')[0]}" if "-" in orig_fp else orig_fp
        sec5a.append({
            "opos": r.get("original_pos") or r["pos"],
            "omth": omth,
            "pos": r["pos"],
            "txval": float(r["taxable_value"]),
            "rt": float(r["rate_pct"]),
            "iamt": float(r["igst"]),
            "csamt": float(r["cess"]),
        })

    payload: dict[str, Any] = {
        "gstin": batch["gstin"],
        "fp": fp,
        "sec5": sec5,
    }
    if sec5a:
        payload["sec5a"] = sec5a

    return payload
