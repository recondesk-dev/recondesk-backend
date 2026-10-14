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
import sqlalchemy as sa

from app.rules.gstr8_rules import (
    TcsCalculationResult,
    calculate_gstr8_tcs,
    get_applicable_tcs_rates,
    normalize_transaction_date,
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
    transaction_date: Optional[str] = None
    rate_basis: Optional[str] = None
    needs_review: bool = False
    review_reason: Optional[str] = None
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


def _assert_no_in_memory_fallback() -> None:
    """Fails closed if running in production or staging.

    Prevents silent fallback to process-local in-memory storage in production/staging,
    which causes silent data loss across container and worker boundaries.
    """
    try:
        from app.config import get_settings
        from app.aurora import AuroraConnectionError
        s = get_settings()
        app_env = str(getattr(s, "APP_ENV", "") or "").lower()
        if app_env in ("production", "staging"):
            raise AuroraConnectionError(
                "Production/Staging safeguard violation: Aurora database connection is unavailable or unconfigured. "
                "Process-local in-memory storage fallback is strictly blocked to prevent silent data loss."
            )
    except ImportError:
        pass


def _has_db(sb: Any) -> bool:
    if sb is None or not hasattr(sb, "table"):
        _assert_no_in_memory_fallback()
        return False
    try:
        from app.aurora_client import AuroraClient
        if isinstance(sb, AuroraClient):
            from app.aurora import get_aurora_database_url
            has_url = bool(get_aurora_database_url())
            if not has_url:
                _assert_no_in_memory_fallback()
            return has_url
    except Exception:
        pass
    return True


def _calculate_batch_totals_from_dicts(batch: Mapping[str, Any], records: list[Mapping[str, Any]]) -> dict[str, Any]:
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
        if str(r.get("status") or "").upper() != "ACTIVE":
            continue
        rtype = str(r.get("record_type") or "ORIGINAL").upper()
        stype = str(r.get("supply_type") or "B2B").upper()
        if rtype == "AMENDMENT":
            amend_cnt += 1
        elif stype == "B2B":
            b2b_cnt += 1
        else:
            b2c_cnt += 1

        gross_tot += Decimal(str(r.get("gross_supplies") or 0))
        ret_tot += Decimal(str(r.get("returned_supplies") or 0))
        net_tot += Decimal(str(r.get("net_supplies") or 0))
        tot_igst += Decimal(str(r.get("tcs_igst") or 0))
        tot_cgst += Decimal(str(r.get("tcs_cgst") or 0))
        tot_sgst += Decimal(str(r.get("tcs_sgst") or 0))
        tot_dep += Decimal(str(r.get("tax_deposited") or 0))

    updates = {
        "total_b2b_records": b2b_cnt,
        "total_b2c_records": b2c_cnt,
        "total_amendments": amend_cnt,
        "gross_supplies_value": float(gross_tot.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "returned_supplies_value": float(ret_tot.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "net_taxable_value": float(net_tot.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_tcs_igst": float(tot_igst.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_tcs_cgst": float(tot_cgst.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_tcs_sgst": float(tot_sgst.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_tcs_deposited": float(tot_dep.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    merged_batch = {**dict(batch), **updates}
    digest = compute_gstr8_figures_digest(merged_batch, records)
    updates["figures_digest"] = digest
    return updates


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

    if _has_db(sb):
        res = (
            sb.table(GSTR8_BATCHES_TABLE)
            .select("*")
            .eq("firm_id", firm_id)
            .eq("client_gstin_id", client_gstin_id)
            .eq("period", clean_period)
            .limit(1)
            .execute()
        )
        if res.data:
            return dict(res.data[0])

        new_id = str(uuid4())
        initial_digest = compute_gstr8_figures_digest({"gstin": clean_gstin, "period": clean_period}, [])
        now_iso = datetime.now(timezone.utc).isoformat()
        new_batch = {
            "id": new_id,
            "firm_id": firm_id,
            "client_gstin_id": client_gstin_id,
            "gstin": clean_gstin,
            "period": clean_period,
            "status": "DRAFT",
            "figures_digest": initial_digest,
            "total_b2b_records": 0,
            "total_b2c_records": 0,
            "total_amendments": 0,
            "gross_supplies_value": 0.0,
            "returned_supplies_value": 0.0,
            "net_taxable_value": 0.0,
            "total_tcs_igst": 0.0,
            "total_tcs_cgst": 0.0,
            "total_tcs_sgst": 0.0,
            "total_tcs_deposited": 0.0,
            "created_by": user_id,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        ins_res = sb.table(GSTR8_BATCHES_TABLE).insert(new_batch).execute()
        return dict(ins_res.data[0] if ins_res.data else new_batch)

    _assert_no_in_memory_fallback()
    with _mem_store_8._lock:
        for b in _mem_store_8.batches.values():
            if (
                b.firm_id == firm_id
                and b.client_gstin_id == client_gstin_id
                and b.period == clean_period
            ):
                return copy.deepcopy(b.__dict__)

        new_batch_obj = Gstr8BatchData(
            id=str(uuid4()),
            firm_id=firm_id,
            client_gstin_id=client_gstin_id,
            gstin=clean_gstin,
            period=clean_period,
            status="DRAFT",
            created_by=user_id,
        )
        _recalculate_batch_totals_8(new_batch_obj, [])
        _mem_store_8.batches[new_batch_obj.id] = new_batch_obj
        return copy.deepcopy(new_batch_obj.__dict__)


def add_or_update_gstr8_record_sync(
    sb: Any,
    *,
    batch_id: str,
    record_data: Mapping[str, Any],
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Add or update a TCS supply record in GSTR-8."""
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
    tx_date_raw = record_data.get("transaction_date") or record_data.get("supply_date") or record_data.get("invoice_date")
    try:
        tx_date = normalize_transaction_date(tx_date_raw, strict=True)
    except ValueError as exc:
        raise Gstr8ValidationError(f"Invalid transaction date: {exc}") from exc

    rate_basis = record_data.get("rate_basis")
    record_id = str(record_data.get("id") or "").strip() or str(uuid4())

    if _has_db(sb):
        engine = None
        try:
            from app.aurora_client import AuroraClient
            if isinstance(sb, AuroraClient):
                from app.aurora import get_aurora_engine, get_aurora_database_url
                if get_aurora_database_url():
                    engine = get_aurora_engine()
        except Exception:
            engine = None

        if engine is not None:
            with engine.begin() as conn:
                b_row = conn.execute(
                    sa.text("SELECT * FROM public.gstr8_batches WHERE id = :id FOR UPDATE"),
                    {"id": batch_id}
                ).mappings().first()
                if not b_row:
                    raise Gstr8Error(f"GSTR-8 Batch {batch_id} not found")
                batch = dict(b_row)

                if str(batch.get("status") or "").upper() in ("SAVED", "FILED"):
                    raise Gstr8ValidationError(f"Cannot modify batch in status {batch['status']}")

                eco_state = extract_state_code(batch.get("gstin") or "")
                supp_state = extract_state_code(supplier_gstin) if supplier_gstin else None

                try:
                    calc = calculate_gstr8_tcs(
                        period=str(batch.get("period") or ""),
                        gross_supplies=gross_val,
                        returned_supplies=ret_val,
                        eco_state=eco_state,
                        pos=pos,
                        supplier_state=supp_state,
                        transaction_date=tx_date,
                        rate_basis=rate_basis,
                    )
                except ValueError as exc:
                    raise Gstr8ValidationError(str(exc)) from exc

                dup_rows = conn.execute(
                    sa.text("""
                        SELECT id, supply_type, record_type, supplier_gstin, pos, transaction_date
                        FROM public.gstr8_records
                        WHERE batch_id = :batch_id
                          AND status = 'ACTIVE'
                          AND supply_type = :supply_type
                          AND record_type = :rec_type
                    """),
                    {"batch_id": batch_id, "supply_type": supply_type, "rec_type": rec_type}
                ).mappings().fetchall()

                for r in dup_rows:
                    if str(r.get("id")) != str(record_id):
                        if supply_type == "B2B" and str(r.get("supplier_gstin") or "").upper() == supplier_gstin:
                            r_date = str(r.get("transaction_date") or "")
                            if not (r_date and tx_date and r_date != str(tx_date)):
                                raise Gstr8DuplicateError(f"Duplicate B2B record for supplier {supplier_gstin} in {rec_type} table")
                        if supply_type == "B2C" and str(r.get("pos") or "") == pos:
                            r_date = str(r.get("transaction_date") or "")
                            if not (r_date and tx_date and r_date != str(tx_date)):
                                raise Gstr8DuplicateError(f"Duplicate B2C record for Place of Supply {pos} in {rec_type} table")

                tcs_igst = float(record_data.get("tcs_igst") if "tcs_igst" in record_data else calc.tcs_igst)
                tcs_cgst = float(record_data.get("tcs_cgst") if "tcs_cgst" in record_data else calc.tcs_cgst)
                tcs_sgst = float(record_data.get("tcs_sgst") if "tcs_sgst" in record_data else calc.tcs_sgst)

                now_iso = datetime.now(timezone.utc).isoformat()
                now_dt = datetime.now(timezone.utc)
                rec_row = {
                    "id": record_id,
                    "batch_id": batch_id,
                    "firm_id": str(batch.get("firm_id")),
                    "client_gstin_id": str(batch.get("client_gstin_id")),
                    "period": str(batch.get("period")),
                    "supply_type": supply_type,
                    "record_type": rec_type,
                    "pos": pos,
                    "supplier_gstin": supplier_gstin,
                    "gross_supplies": gross_val,
                    "returned_supplies": ret_val,
                    "net_supplies": float(calc.net_supplies),
                    "tcs_rate": float(calc.rate_structure.total_rate_pct),
                    "tcs_igst": tcs_igst,
                    "tcs_cgst": tcs_cgst,
                    "tcs_sgst": tcs_sgst,
                    "original_period": record_data.get("original_period"),
                    "original_supplier_gstin": record_data.get("original_supplier_gstin"),
                    "original_pos": record_data.get("original_pos"),
                    "tax_deposited": float(record_data.get("tax_deposited") or 0.0),
                    "transaction_date": tx_date,
                    "rate_basis": str(rate_basis) if rate_basis else None,
                    "needs_review": calc.requires_review,
                    "review_reason": calc.review_reason,
                    "status": "ACTIVE",
                    "updated_at": now_dt,
                }

                ex_id = conn.execute(
                    sa.text("SELECT id FROM public.gstr8_records WHERE id = :id"),
                    {"id": record_id}
                ).scalar()

                if ex_id:
                    update_cols = [k for k in rec_row.keys() if k != "id"]
                    set_clause = ", ".join(f'"{k}" = :{k}' for k in update_cols)
                    conn.execute(sa.text(f'UPDATE public.gstr8_records SET {set_clause} WHERE id = :id'), rec_row)
                else:
                    rec_row["created_at"] = now_dt
                    cols = list(rec_row.keys())
                    col_str = ", ".join(f'"{k}"' for k in cols)
                    val_str = ", ".join(f":{k}" for k in cols)
                    conn.execute(sa.text(f'INSERT INTO public.gstr8_records ({col_str}) VALUES ({val_str})'), rec_row)

                active_rows = conn.execute(
                    sa.text("SELECT * FROM public.gstr8_records WHERE batch_id = :batch_id AND status = 'ACTIVE'"),
                    {"batch_id": batch_id}
                ).mappings().fetchall()
                active_recs = [dict(r) for r in active_rows]

                b_updates = _calculate_batch_totals_from_dicts(batch, active_recs)
                if str(batch.get("status") or "").upper() in ("APPROVED", "UNDER_REVIEW"):
                    b_updates["status"] = "PREPARED"

                b_update_cols = list(b_updates.keys())
                b_set_clause = ", ".join(f'"{k}" = :{k}' for k in b_update_cols)
                b_params = {**b_updates, "id": batch_id}
                conn.execute(sa.text(f'UPDATE public.gstr8_batches SET {b_set_clause} WHERE id = :id'), b_params)

                conn.execute(
                    sa.text("""
                        INSERT INTO public.gstr8_audit_trail (batch_id, firm_id, action, actor_id, details, created_at)
                        VALUES (:batch_id, :firm_id, :action, :actor_id, :details, :created_at)
                    """),
                    {
                        "batch_id": batch_id,
                        "firm_id": str(batch.get("firm_id")),
                        "action": "UPSERT_RECORD",
                        "actor_id": user_id,
                        "details": json.dumps({"record_id": record_id, "supplier_gstin": supplier_gstin, "pos": pos}),
                        "created_at": now_dt,
                    }
                )

                rec_return = dict(rec_row)
                rec_return["created_at"] = now_iso
                rec_return["updated_at"] = now_iso
                return copy.deepcopy(rec_return)

        b_res = sb.table(GSTR8_BATCHES_TABLE).select("*").eq("id", batch_id).limit(1).execute()
        if not b_res.data:
            raise Gstr8Error(f"GSTR-8 Batch {batch_id} not found")
        batch = dict(b_res.data[0])

        if str(batch.get("status") or "").upper() in ("SAVED", "FILED"):
            raise Gstr8ValidationError(f"Cannot modify batch in status {batch['status']}")

        eco_state = extract_state_code(batch.get("gstin") or "")
        supp_state = extract_state_code(supplier_gstin) if supplier_gstin else None

        try:
            calc = calculate_gstr8_tcs(
                period=str(batch.get("period") or ""),
                gross_supplies=gross_val,
                returned_supplies=ret_val,
                eco_state=eco_state,
                pos=pos,
                supplier_state=supp_state,
                transaction_date=tx_date,
                rate_basis=rate_basis,
            )
        except ValueError as exc:
            raise Gstr8ValidationError(str(exc)) from exc

        # Check duplicates in DB
        dup_res = (
            sb.table(GSTR8_RECORDS_TABLE)
            .select("id, supply_type, record_type, supplier_gstin, pos, transaction_date")
            .eq("batch_id", batch_id)
            .eq("status", "ACTIVE")
            .eq("supply_type", supply_type)
            .eq("record_type", rec_type)
            .execute()
        )
        for r in (dup_res.data or []):
            if str(r.get("id")) != str(record_id):
                if supply_type == "B2B" and str(r.get("supplier_gstin") or "").upper() == supplier_gstin:
                    r_date = str(r.get("transaction_date") or "")
                    if not (r_date and tx_date and r_date != str(tx_date)):
                        raise Gstr8DuplicateError(f"Duplicate B2B record for supplier {supplier_gstin} in {rec_type} table")
                if supply_type == "B2C" and str(r.get("pos") or "") == pos:
                    r_date = str(r.get("transaction_date") or "")
                    if not (r_date and tx_date and r_date != str(tx_date)):
                        raise Gstr8DuplicateError(f"Duplicate B2C record for Place of Supply {pos} in {rec_type} table")

        tcs_igst = float(record_data.get("tcs_igst") if "tcs_igst" in record_data else calc.tcs_igst)
        tcs_cgst = float(record_data.get("tcs_cgst") if "tcs_cgst" in record_data else calc.tcs_cgst)
        tcs_sgst = float(record_data.get("tcs_sgst") if "tcs_sgst" in record_data else calc.tcs_sgst)

        now_iso = datetime.now(timezone.utc).isoformat()
        rec_row = {
            "id": record_id,
            "batch_id": batch_id,
            "firm_id": batch.get("firm_id"),
            "client_gstin_id": batch.get("client_gstin_id"),
            "period": batch.get("period"),
            "supply_type": supply_type,
            "record_type": rec_type,
            "pos": pos,
            "supplier_gstin": supplier_gstin,
            "gross_supplies": gross_val,
            "returned_supplies": ret_val,
            "net_supplies": float(calc.net_supplies),
            "tcs_rate": float(calc.rate_structure.total_rate_pct),
            "tcs_igst": tcs_igst,
            "tcs_cgst": tcs_cgst,
            "tcs_sgst": tcs_sgst,
            "original_period": record_data.get("original_period"),
            "original_supplier_gstin": record_data.get("original_supplier_gstin"),
            "original_pos": record_data.get("original_pos"),
            "tax_deposited": float(record_data.get("tax_deposited") or 0.0),
            "transaction_date": tx_date,
            "rate_basis": str(rate_basis) if rate_basis else None,
            "needs_review": calc.requires_review,
            "review_reason": calc.review_reason,
            "status": "ACTIVE",
            "updated_at": now_iso,
        }

        ex_res = sb.table(GSTR8_RECORDS_TABLE).select("id").eq("id", record_id).limit(1).execute()
        if ex_res.data:
            sb.table(GSTR8_RECORDS_TABLE).update(rec_row).eq("id", record_id).execute()
        else:
            rec_row["created_at"] = now_iso
            sb.table(GSTR8_RECORDS_TABLE).insert(rec_row).execute()

        active_recs = [dict(r) for r in (sb.table(GSTR8_RECORDS_TABLE).select("*").eq("batch_id", batch_id).eq("status", "ACTIVE").execute().data or [])]
        b_updates = _calculate_batch_totals_from_dicts(batch, active_recs)
        if str(batch.get("status") or "").upper() in ("APPROVED", "UNDER_REVIEW"):
            b_updates["status"] = "PREPARED"
        sb.table(GSTR8_BATCHES_TABLE).update(b_updates).eq("id", batch_id).execute()

        sb.table(GSTR8_AUDIT_TABLE).insert({
            "batch_id": batch_id,
            "firm_id": batch.get("firm_id"),
            "action": "UPSERT_RECORD",
            "actor_id": user_id,
            "details": {"record_id": record_id, "supplier_gstin": supplier_gstin, "pos": pos},
            "created_at": now_iso,
        }).execute()

        return copy.deepcopy(rec_row)

    _assert_no_in_memory_fallback()
    with _mem_store_8._lock:
        batch_mem = _mem_store_8.batches.get(batch_id)
        if not batch_mem:
            raise Gstr8Error(f"GSTR-8 Batch {batch_id} not found")

        if batch_mem.status in ("SAVED", "FILED"):
            raise Gstr8ValidationError(f"Cannot modify batch in status {batch_mem.status}")

        eco_state = extract_state_code(batch_mem.gstin)
        supp_state = extract_state_code(supplier_gstin) if supplier_gstin else None

        # Compute statutory TCS calculation with transaction date and rate basis awareness
        try:
            calc = calculate_gstr8_tcs(
                period=batch_mem.period,
                gross_supplies=gross_val,
                returned_supplies=ret_val,
                eco_state=eco_state,
                pos=pos,
                supplier_state=supp_state,
                transaction_date=tx_date,
                rate_basis=rate_basis,
            )
        except ValueError as exc:
            raise Gstr8ValidationError(str(exc)) from exc

        # Check for duplicates: allow multiple records for same supplier/POS only if transaction dates differ
        for r in _mem_store_8.records.values():
            if (
                r.batch_id == batch_id
                and r.status == "ACTIVE"
                and r.id != record_id
                and r.supply_type == supply_type
                and r.record_type == rec_type
            ):
                if supply_type == "B2B" and r.supplier_gstin == supplier_gstin:
                    if not (r.transaction_date and tx_date and r.transaction_date != tx_date):
                        raise Gstr8DuplicateError(
                            f"Duplicate B2B record for supplier {supplier_gstin} in {rec_type} table"
                        )
                if supply_type == "B2C" and r.pos == pos:
                    if not (r.transaction_date and tx_date and r.transaction_date != tx_date):
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
            firm_id=batch_mem.firm_id,
            client_gstin_id=batch_mem.client_gstin_id,
            period=batch_mem.period,
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
            transaction_date=tx_date,
            rate_basis=str(rate_basis) if rate_basis else None,
            needs_review=calc.requires_review,
            review_reason=calc.review_reason,
            status="ACTIVE",
        )

        _mem_store_8.records[record_id] = rec

        batch_records = [r for r in _mem_store_8.records.values() if r.batch_id == batch_id and r.status == "ACTIVE"]
        _recalculate_batch_totals_8(batch_mem, batch_records)

        if batch_mem.status in ("APPROVED", "UNDER_REVIEW"):
            batch_mem.status = "PREPARED"

        return copy.deepcopy(rec.__dict__)


def delete_gstr8_record_sync(
    sb: Any,
    *,
    batch_id: str,
    record_id: str,
    user_id: Optional[str] = None,
) -> bool:
    """Soft delete a GSTR-8 TCS record."""
    if _has_db(sb):
        engine = None
        try:
            from app.aurora_client import AuroraClient
            if isinstance(sb, AuroraClient):
                from app.aurora import get_aurora_engine, get_aurora_database_url
                if get_aurora_database_url():
                    engine = get_aurora_engine()
        except Exception:
            engine = None

        if engine is not None:
            with engine.begin() as conn:
                b_row = conn.execute(
                    sa.text("SELECT * FROM public.gstr8_batches WHERE id = :id FOR UPDATE"),
                    {"id": batch_id}
                ).mappings().first()
                if not b_row:
                    raise Gstr8Error(f"Batch {batch_id} not found")
                batch = dict(b_row)

                if str(batch.get("status") or "").upper() in ("SAVED", "FILED"):
                    raise Gstr8ValidationError(f"Cannot modify batch in status {batch['status']}")

                r_id = conn.execute(
                    sa.text("SELECT id FROM public.gstr8_records WHERE id = :id AND batch_id = :batch_id AND status = 'ACTIVE'"),
                    {"id": record_id, "batch_id": batch_id}
                ).scalar()
                if not r_id:
                    return False

                now_dt = datetime.now(timezone.utc)
                conn.execute(
                    sa.text("UPDATE public.gstr8_records SET status = 'DELETED', updated_at = :now WHERE id = :id"),
                    {"id": record_id, "now": now_dt}
                )

                active_rows = conn.execute(
                    sa.text("SELECT * FROM public.gstr8_records WHERE batch_id = :batch_id AND status = 'ACTIVE'"),
                    {"batch_id": batch_id}
                ).mappings().fetchall()
                active_recs = [dict(r) for r in active_rows]

                b_updates = _calculate_batch_totals_from_dicts(batch, active_recs)
                if str(batch.get("status") or "").upper() in ("APPROVED", "UNDER_REVIEW"):
                    b_updates["status"] = "PREPARED"

                b_update_cols = list(b_updates.keys())
                b_set_clause = ", ".join(f'"{k}" = :{k}' for k in b_update_cols)
                b_params = {**b_updates, "id": batch_id}
                conn.execute(sa.text(f'UPDATE public.gstr8_batches SET {b_set_clause} WHERE id = :id'), b_params)

                conn.execute(
                    sa.text("""
                        INSERT INTO public.gstr8_audit_trail (batch_id, firm_id, action, actor_id, details, created_at)
                        VALUES (:batch_id, :firm_id, :action, :actor_id, :details, :created_at)
                    """),
                    {
                        "batch_id": batch_id,
                        "firm_id": str(batch.get("firm_id")),
                        "action": "DELETE_RECORD",
                        "actor_id": user_id,
                        "details": json.dumps({"record_id": record_id}),
                        "created_at": now_dt,
                    }
                )

                return True

        b_res = sb.table(GSTR8_BATCHES_TABLE).select("*").eq("id", batch_id).limit(1).execute()
        if not b_res.data:
            raise Gstr8Error(f"Batch {batch_id} not found")
        batch = dict(b_res.data[0])

        if str(batch.get("status") or "").upper() in ("SAVED", "FILED"):
            raise Gstr8ValidationError(f"Cannot modify batch in status {batch['status']}")

        r_res = sb.table(GSTR8_RECORDS_TABLE).select("id").eq("id", record_id).eq("batch_id", batch_id).limit(1).execute()
        if not r_res.data:
            return False

        now_iso = datetime.now(timezone.utc).isoformat()
        sb.table(GSTR8_RECORDS_TABLE).update({
            "status": "DELETED",
            "updated_at": now_iso,
        }).eq("id", record_id).execute()

        active_recs = [dict(r) for r in (sb.table(GSTR8_RECORDS_TABLE).select("*").eq("batch_id", batch_id).eq("status", "ACTIVE").execute().data or [])]
        b_updates = _calculate_batch_totals_from_dicts(batch, active_recs)
        if str(batch.get("status") or "").upper() in ("APPROVED", "UNDER_REVIEW"):
            b_updates["status"] = "PREPARED"
        sb.table(GSTR8_BATCHES_TABLE).update(b_updates).eq("id", batch_id).execute()

        sb.table(GSTR8_AUDIT_TABLE).insert({
            "batch_id": batch_id,
            "firm_id": batch.get("firm_id"),
            "action": "DELETE_RECORD",
            "actor_id": user_id,
            "details": {"record_id": record_id},
            "created_at": now_iso,
        }).execute()

        return True

    _assert_no_in_memory_fallback()
    with _mem_store_8._lock:
        batch_mem = _mem_store_8.batches.get(batch_id)
        if not batch_mem:
            raise Gstr8Error(f"Batch {batch_id} not found")

        if batch_mem.status in ("SAVED", "FILED"):
            raise Gstr8ValidationError(f"Cannot modify batch in status {batch_mem.status}")

        rec = _mem_store_8.records.get(record_id)
        if not rec or rec.batch_id != batch_id:
            return False

        rec.status = "DELETED"
        rec.updated_at = datetime.now(timezone.utc).isoformat()

        batch_records = [r for r in _mem_store_8.records.values() if r.batch_id == batch_id and r.status == "ACTIVE"]
        _recalculate_batch_totals_8(batch_mem, batch_records)

        if batch_mem.status in ("APPROVED", "UNDER_REVIEW"):
            batch_mem.status = "PREPARED"

        return True


def get_batch_summary_sync(
    sb: Any,
    *,
    batch_id: str,
) -> dict[str, Any]:
    """Retrieve complete GSTR-8 batch summary with tables, calculations, and exceptions."""
    if _has_db(sb):
        b_res = sb.table(GSTR8_BATCHES_TABLE).select("*").eq("id", batch_id).limit(1).execute()
        if not b_res.data:
            raise Gstr8Error(f"Batch {batch_id} not found")
        batch_dict = dict(b_res.data[0])

        r_res = sb.table(GSTR8_RECORDS_TABLE).select("*").eq("batch_id", batch_id).eq("status", "ACTIVE").execute()
        records_db = [dict(r) for r in (r_res.data or [])]

        table3_b2b = [r for r in records_db if str(r.get("record_type") or "").upper() == "ORIGINAL" and str(r.get("supply_type") or "").upper() == "B2B"]
        table3_b2c = [r for r in records_db if str(r.get("record_type") or "").upper() == "ORIGINAL" and str(r.get("supply_type") or "").upper() == "B2C"]
        table4_b2b = [r for r in records_db if str(r.get("record_type") or "").upper() == "AMENDMENT" and str(r.get("supply_type") or "").upper() == "B2B"]
        table4_b2c = [r for r in records_db if str(r.get("record_type") or "").upper() == "AMENDMENT" and str(r.get("supply_type") or "").upper() == "B2C"]

        exceptions_db: list[dict[str, Any]] = []
        for r in records_db:
            if float(r.get("net_supplies") or 0.0) < 0:
                exceptions_db.append({
                    "record_id": r.get("id"),
                    "supplier_gstin": r.get("supplier_gstin"),
                    "pos": r.get("pos"),
                    "category": "NEGATIVE_NET_SUPPLIES",
                    "reason": f"Returned supplies (₹{float(r.get('returned_supplies') or 0.0):,.2f}) exceed gross supplies (₹{float(r.get('gross_supplies') or 0.0):,.2f}).",
                })
            if bool(r.get("needs_review")):
                exceptions_db.append({
                    "record_id": r.get("id"),
                    "supplier_gstin": r.get("supplier_gstin"),
                    "pos": r.get("pos"),
                    "category": "MISSING_RATE_BASIS_JULY_2024",
                    "reason": r.get("review_reason") or "July 2024 transition record requires transaction_date or verifiable rate basis (1.0% vs 0.5%).",
                })

        total_tcs_db = float(batch_dict.get("total_tcs_igst") or 0.0) + float(batch_dict.get("total_tcs_cgst") or 0.0) + float(batch_dict.get("total_tcs_sgst") or 0.0)
        deposited_db = float(batch_dict.get("total_tcs_deposited") or 0.0)
        deposit_var_db = round(total_tcs_db - deposited_db, 2)
        if abs(deposit_var_db) > 0.01:
            exceptions_db.append({
                "category": "DEPOSIT_DISCREPANCY",
                "reason": (
                    f"Total TCS calculated (₹{total_tcs_db:,.2f}) differs from tax deposited "
                    f"(₹{deposited_db:,.2f}) by ₹{deposit_var_db:,.2f}."
                ),
            })

        rates_db = get_applicable_tcs_rates(str(batch_dict.get("period") or ""))

        return {
            "batch": copy.deepcopy(batch_dict),
            "table3_b2b": table3_b2b,
            "table3_b2c": table3_b2c,
            "table4_b2b": table4_b2b,
            "table4_b2c": table4_b2c,
            "applicable_rates": {
                "total_pct": float(rates_db.total_rate_pct),
                "cgst_pct": float(rates_db.cgst_rate * 100),
                "sgst_pct": float(rates_db.sgst_rate * 100),
                "igst_pct": float(rates_db.igst_rate * 100),
                "reference": rates_db.notification_reference,
            },
            "total_tcs_liability": total_tcs_db,
            "deposit_variance": deposit_var_db,
            "exceptions": exceptions_db,
        }

    _assert_no_in_memory_fallback()
    with _mem_store_8._lock:
        batch_mem = _mem_store_8.batches.get(batch_id)
        if not batch_mem:
            raise Gstr8Error(f"Batch {batch_id} not found")

        records_mem = [
            copy.deepcopy(r.__dict__)
            for r in _mem_store_8.records.values()
            if r.batch_id == batch_id and r.status == "ACTIVE"
        ]

        table3_b2b_mem = [r for r in records_mem if r["record_type"] == "ORIGINAL" and r["supply_type"] == "B2B"]
        table3_b2c_mem = [r for r in records_mem if r["record_type"] == "ORIGINAL" and r["supply_type"] == "B2C"]
        table4_b2b_mem = [r for r in records_mem if r["record_type"] == "AMENDMENT" and r["supply_type"] == "B2B"]
        table4_b2c_mem = [r for r in records_mem if r["record_type"] == "AMENDMENT" and r["supply_type"] == "B2C"]

        exceptions_mem: list[dict[str, Any]] = []
        for r in records_mem:
            if r["net_supplies"] < 0:
                exceptions_mem.append({
                    "record_id": r["id"],
                    "supplier_gstin": r.get("supplier_gstin"),
                    "pos": r["pos"],
                    "category": "NEGATIVE_NET_SUPPLIES",
                    "reason": f"Returned supplies (₹{r['returned_supplies']:,.2f}) exceed gross supplies (₹{r['gross_supplies']:,.2f}).",
                })
            if r.get("needs_review"):
                exceptions_mem.append({
                    "record_id": r["id"],
                    "supplier_gstin": r.get("supplier_gstin"),
                    "pos": r["pos"],
                    "category": "MISSING_RATE_BASIS_JULY_2024",
                    "reason": r.get("review_reason") or "July 2024 transition record requires transaction_date or verifiable rate basis (1.0% vs 0.5%).",
                })

        total_tcs_mem = batch_mem.total_tcs_igst + batch_mem.total_tcs_cgst + batch_mem.total_tcs_sgst
        deposit_var_mem = round(total_tcs_mem - batch_mem.total_tcs_deposited, 2)
        if abs(deposit_var_mem) > 0.01:
            exceptions_mem.append({
                "category": "DEPOSIT_DISCREPANCY",
                "reason": (
                    f"Total TCS calculated (₹{total_tcs_mem:,.2f}) differs from tax deposited "
                    f"(₹{batch_mem.total_tcs_deposited:,.2f}) by ₹{deposit_var_mem:,.2f}."
                ),
            })

        rates_mem = get_applicable_tcs_rates(batch_mem.period)

        return {
            "batch": copy.deepcopy(batch_mem.__dict__),
            "table3_b2b": table3_b2b_mem,
            "table3_b2c": table3_b2c_mem,
            "table4_b2b": table4_b2b_mem,
            "table4_b2c": table4_b2c_mem,
            "applicable_rates": {
                "total_pct": float(rates_mem.total_rate_pct),
                "cgst_pct": float(rates_mem.cgst_rate * 100),
                "sgst_pct": float(rates_mem.sgst_rate * 100),
                "igst_pct": float(rates_mem.igst_rate * 100),
                "reference": rates_mem.notification_reference,
            },
            "total_tcs_liability": total_tcs_mem,
            "deposit_variance": deposit_var_mem,
            "exceptions": exceptions_mem,
        }



def build_gstr8_offline_json(
    sb: Any,
    *,
    batch_id: str,
) -> dict[str, Any]:
    """Generate official GSTN-compliant Form GSTR-8 offline JSON."""
    summary = get_batch_summary_sync(sb, batch_id=batch_id)
    batch = summary["batch"]

    # Block offline JSON generation if any records are unresolved for July 2024 rate basis
    all_recs = (
        summary["table3_b2b"]
        + summary["table3_b2c"]
        + summary["table4_b2b"]
        + summary["table4_b2c"]
    )
    for r in all_recs:
        if r.get("needs_review"):
            raise Gstr8ValidationError(
                f"Cannot export offline JSON: Record {r.get('id')} ({r.get('supplier_gstin') or r.get('pos')}) "
                f"requires review for July 2024 rate determination: {r.get('review_reason')}"
            )

    parts = batch["period"].split("-")
    fp = f"{parts[1]}{parts[0]}" if len(parts) == 2 else batch["period"]

    tcs_dict: dict[str, dict[str, Any]] = {}
    for r in summary["table3_b2b"]:
        supp = r["supplier_gstin"]
        if supp not in tcs_dict:
            tcs_dict[supp] = {
                "gstin_supp": supp,
                "gross_val": 0.0,
                "ret_val": 0.0,
                "net_val": 0.0,
                "iamt": 0.0,
                "camt": 0.0,
                "samt": 0.0,
            }
        tcs_dict[supp]["gross_val"] = round(tcs_dict[supp]["gross_val"] + float(r["gross_supplies"]), 2)
        tcs_dict[supp]["ret_val"] = round(tcs_dict[supp]["ret_val"] + float(r["returned_supplies"]), 2)
        tcs_dict[supp]["net_val"] = round(tcs_dict[supp]["net_val"] + float(r["net_supplies"]), 2)
        tcs_dict[supp]["iamt"] = round(tcs_dict[supp]["iamt"] + float(r["tcs_igst"]), 2)
        tcs_dict[supp]["camt"] = round(tcs_dict[supp]["camt"] + float(r["tcs_cgst"]), 2)
        tcs_dict[supp]["samt"] = round(tcs_dict[supp]["samt"] + float(r["tcs_sgst"]), 2)
    tcs_list = list(tcs_dict.values())

    tcs_b2c_dict: dict[str, dict[str, Any]] = {}
    for r in summary["table3_b2c"]:
        pos_key = r["pos"]
        if pos_key not in tcs_b2c_dict:
            tcs_b2c_dict[pos_key] = {
                "pos": pos_key,
                "gross_val": 0.0,
                "ret_val": 0.0,
                "net_val": 0.0,
                "iamt": 0.0,
                "camt": 0.0,
                "samt": 0.0,
            }
        tcs_b2c_dict[pos_key]["gross_val"] = round(tcs_b2c_dict[pos_key]["gross_val"] + float(r["gross_supplies"]), 2)
        tcs_b2c_dict[pos_key]["ret_val"] = round(tcs_b2c_dict[pos_key]["ret_val"] + float(r["returned_supplies"]), 2)
        tcs_b2c_dict[pos_key]["net_val"] = round(tcs_b2c_dict[pos_key]["net_val"] + float(r["net_supplies"]), 2)
        tcs_b2c_dict[pos_key]["iamt"] = round(tcs_b2c_dict[pos_key]["iamt"] + float(r["tcs_igst"]), 2)
        tcs_b2c_dict[pos_key]["camt"] = round(tcs_b2c_dict[pos_key]["camt"] + float(r["tcs_cgst"]), 2)
        tcs_b2c_dict[pos_key]["samt"] = round(tcs_b2c_dict[pos_key]["samt"] + float(r["tcs_sgst"]), 2)
    tcs_b2c_list = list(tcs_b2c_dict.values())

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
