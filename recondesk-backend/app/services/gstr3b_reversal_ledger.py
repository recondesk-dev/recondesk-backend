"""GSTR-3B General Table 4(B)(2) Reversal & Reclaim Ledger Service.

Phase 3A.1.1 Hardening:
- Authoritative cross-period tracking of all temporary reversals (Table 4B2)
  and verified reclaims (Table 4A5 + Table 4D1).
- Strict Reclaimability Boundary: is_reclaimable=False guarantees:
  * no reclaim_events
  * cannot transition to CONDITION_FULFILLED, RECLAIM_AUTHORIZED, PARTIALLY_RECLAIMED, or FULLY_RECLAIMED
  * cannot contribute to 4(D)(1)
- Complete Rule 37A provenance:
  * financial year of ITC
  * supplier's outward-supply statement period & GSTR-1 filing date
  * corresponding supplier GSTR-3B tax period & filing status
  * 30 September test date & filed_by_september_30 flag
  * 30 November reversal deadline & actual reversal date
  * subsequent supplier filing date & filing ARN
  * condition fulfilled date & reclaim eligibility date
- Statutory Section 16(2)(b):
  * Formal statutory category SECTION_16_2_B_NOT_RECEIVED requiring CA disposition & evidence.
  * Internal transit flags do NOT automatically assign this statutory classification.
- Frozen state sealing & digest for reproducible audit snapshots.
- Immutable event history as authoritative source of truth.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator
from supabase import Client

_log = logging.getLogger(__name__)
_python_fallback_reclaim_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ReversalProvenanceType(str, Enum):
    RECON_OUTCOME = "RECON_OUTCOME"
    EXCEPTION_DISPOSITION = "EXCEPTION_DISPOSITION"
    STATUTORY_ADJUSTMENT = "STATUTORY_ADJUSTMENT"
    OPENING_BALANCE = "OPENING_BALANCE"


class StatutoryTemporaryReason(str, Enum):
    RULE_37_NON_PAYMENT = "RULE_37_NON_PAYMENT"
    RULE_37A_SUPPLIER_NON_FILING = "RULE_37A_SUPPLIER_NON_FILING"
    SECTION_16_2_B_NOT_RECEIVED = "SECTION_16_2_B_NOT_RECEIVED"
    SECTION_16_2_C_SUPPLIER_TAX_CONDITION = "SECTION_16_2_C_SUPPLIER_TAX_CONDITION"
    OTHER_TEMPORARY = "OTHER_TEMPORARY"
    OPENING_BALANCE = "OPENING_BALANCE"


class ReversalStatus(str, Enum):
    OPEN = "OPEN"
    CONDITION_FULFILLED = "CONDITION_FULFILLED"
    RECLAIM_AUTHORIZED = "RECLAIM_AUTHORIZED"
    PARTIALLY_RECLAIMED = "PARTIALLY_RECLAIMED"
    FULLY_RECLAIMED = "FULLY_RECLAIMED"
    NON_RECLAIMABLE = "NON_RECLAIMABLE"


class ReclaimEventType(str, Enum):
    RECLAIM = "RECLAIM"
    COMPENSATING_REVERSAL = "COMPENSATING_REVERSAL"


class StatutoryEvidenceType(str, Enum):
    PAYMENT_TO_SUPPLIER = "PAYMENT_TO_SUPPLIER"
    SUPPLIER_GSTR3B_FILED = "SUPPLIER_GSTR3B_FILED"
    GOODS_RECEIVED_GRN = "GOODS_RECEIVED_GRN"
    TAX_DISCHARGE_CONFIRMED = "TAX_DISCHARGE_CONFIRMED"
    OPENING_BALANCE_VERIFIED = "OPENING_BALANCE_VERIFIED"
    COMPENSATING_ADJUSTMENT = "COMPENSATING_ADJUSTMENT"
    OTHER_STATUTORY_PROOF = "OTHER_STATUTORY_PROOF"


# ---------------------------------------------------------------------------
# State Sealing Helpers
# ---------------------------------------------------------------------------

def compute_state_digest(payload: Any) -> str:
    """Compute a deterministic SHA-256 digest of a canonical dictionary/list."""
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class AvailableBalancePaise(BaseModel):
    igst_paise: int
    cgst_paise: int
    sgst_paise: int
    cess_paise: int

    @property
    def total_paise(self) -> int:
        return self.igst_paise + self.cgst_paise + self.sgst_paise + self.cess_paise


class ReversalLedgerCreate(BaseModel):
    client_gstin_id: str
    source_type: ReversalProvenanceType
    source_record_id: str
    source_run_id: Optional[str] = None
    reversal_tax_period: str = Field(..., pattern=r"^\d{4}-\d{2}$")

    # Relaxed document identity for adjustments & opening balances
    document_type: str = "INVOICE"
    document_number: Optional[str] = None
    document_date: Optional[date] = None
    supplier_gstin: Optional[str] = None
    reference_doc: Optional[str] = None

    reversal_table4_cell: str = "4B2"
    is_reclaimable: bool = True
    statutory_reason: StatutoryTemporaryReason

    # Explicit Rule 37A Lifecycle & Provenance fields
    itc_financial_year: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}$")
    supplier_outward_statement_period: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}$")
    supplier_gstr1_filing_date: Optional[date] = None
    supplier_gstr3b_tax_period: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}$")
    supplier_gstr3b_filing_status: Optional[str] = "UNKNOWN"
    filed_by_september_30: bool = False
    september_test_date: Optional[date] = None
    november_reversal_deadline: Optional[date] = None
    actual_reversal_date: Optional[date] = None
    subsequent_supplier_filing_date: Optional[date] = None
    subsequent_filing_arn: Optional[str] = None
    condition_fulfilled_date: Optional[date] = None
    reclaim_eligibility_date: Optional[date] = None

    # Source State Sealing
    source_payload: dict[str, Any] = Field(default_factory=dict)
    source_state_hash: Optional[str] = None

    reversed_igst_paise: int = 0
    reversed_cgst_paise: int = 0
    reversed_sgst_paise: int = 0
    reversed_cess_paise: int = 0
    created_by: Optional[str] = None

    @field_validator("reversal_table4_cell")
    @classmethod
    def validate_reversal_table4_cell(cls, v: str) -> str:
        clean = v.strip().upper()
        if clean != "4B2":
            raise ValueError(
                f"Invalid reversal cell '{clean}'. Only Table 4(B)(2) reversals "
                f"are tracked in this ledger. Permanent 4(B)(1) reversals are strictly forbidden."
            )
        return clean

    @model_validator(mode="after")
    def validate_amounts_and_digest(self) -> ReversalLedgerCreate:
        if (
            self.reversed_igst_paise < 0
            or self.reversed_cgst_paise < 0
            or self.reversed_sgst_paise < 0
            or self.reversed_cess_paise < 0
        ):
            raise ValueError("Reversed tax amounts must be non-negative integer paise.")

        tot = (
            self.reversed_igst_paise
            + self.reversed_cgst_paise
            + self.reversed_sgst_paise
            + self.reversed_cess_paise
        )
        if tot <= 0:
            raise ValueError("Total reversed tax across all heads must be greater than zero.")

        if not self.source_state_hash:
            self.source_state_hash = compute_state_digest(self.source_payload or {
                "source_record_id": self.source_record_id,
                "reversal_tax_period": self.reversal_tax_period,
                "statutory_reason": self.statutory_reason.value,
                "reversed_tot_paise": tot,
            })

        return self


class ReversalLedgerEntry(BaseModel):
    id: str
    client_gstin_id: str
    source_type: str
    source_record_id: str
    source_run_id: Optional[str] = None
    reversal_tax_period: str
    document_type: str
    document_number: Optional[str] = None
    document_date: Optional[str] = None
    supplier_gstin: Optional[str] = None
    reference_doc: Optional[str] = None
    reversal_table4_cell: str
    is_reclaimable: bool
    statutory_reason: str

    itc_financial_year: Optional[str] = None
    supplier_outward_statement_period: Optional[str] = None
    supplier_gstr1_filing_date: Optional[str] = None
    supplier_gstr3b_tax_period: Optional[str] = None
    supplier_gstr3b_filing_status: Optional[str] = None
    filed_by_september_30: bool = False
    september_test_date: Optional[str] = None
    november_reversal_deadline: Optional[str] = None
    actual_reversal_date: Optional[str] = None
    subsequent_supplier_filing_date: Optional[str] = None
    subsequent_filing_arn: Optional[str] = None
    condition_fulfilled_date: Optional[str] = None
    reclaim_eligibility_date: Optional[str] = None

    source_state_hash: str
    source_payload: dict[str, Any]

    reversed_igst_paise: int
    reversed_cgst_paise: int
    reversed_sgst_paise: int
    reversed_cess_paise: int

    cached_reclaimed_igst_paise: int = 0
    cached_reclaimed_cgst_paise: int = 0
    cached_reclaimed_sgst_paise: int = 0
    cached_reclaimed_cess_paise: int = 0

    status: str
    created_at: str
    updated_at: str
    created_by: Optional[str] = None


class ReclaimEventCreate(BaseModel):
    ledger_id: str
    client_gstin_id: Optional[str] = None
    reclaim_run_id: str
    reclaim_tax_period: str = Field(..., pattern=r"^\d{4}-\d{2}$")
    event_type: ReclaimEventType = ReclaimEventType.RECLAIM
    compensates_event_id: Optional[str] = None

    reclaimed_igst_paise: int = 0
    reclaimed_cgst_paise: int = 0
    reclaimed_sgst_paise: int = 0
    reclaimed_cess_paise: int = 0

    statutory_evidence_type: StatutoryEvidenceType
    evidence_reference: str = Field(..., min_length=1)
    evidence_document_date: Optional[date] = None
    authorized_by: Optional[str] = None
    reclaim_notes: str = Field(..., min_length=3)
    idempotency_key: Optional[str] = None

    @model_validator(mode="after")
    def validate_reclaim_amounts(self) -> ReclaimEventCreate:
        if (
            self.reclaimed_igst_paise < 0
            or self.reclaimed_cgst_paise < 0
            or self.reclaimed_sgst_paise < 0
            or self.reclaimed_cess_paise < 0
        ):
            raise ValueError("Reclaimed amounts must be non-negative integer paise.")

        tot = (
            self.reclaimed_igst_paise
            + self.reclaimed_cgst_paise
            + self.reclaimed_sgst_paise
            + self.reclaimed_cess_paise
        )
        if tot <= 0:
            raise ValueError("Total reclaimed amount across all tax heads must be greater than zero.")

        return self


class ReclaimExecutionResult(BaseModel):
    event_id: str
    ledger_id: str
    status: str
    is_idempotent_replay: bool = False
    event_type: str
    reclaimed_igst_paise: int
    reclaimed_cgst_paise: int
    reclaimed_sgst_paise: int
    reclaimed_cess_paise: int
    remaining_igst_paise: int
    remaining_cgst_paise: int
    remaining_sgst_paise: int
    remaining_cess_paise: int



# ---------------------------------------------------------------------------
# Repository & Data Access Functions
# ---------------------------------------------------------------------------

def create_reversal_ledger_entry(sb: Client, entry: ReversalLedgerCreate) -> dict[str, Any]:
    """Insert a new temporary reversal into public.gstr3b_reversal_ledger."""
    if entry.reversal_table4_cell != "4B2":
        raise ValueError("Only Table 4(B)(2) temporary reversals are eligible for this ledger.")

    init_status = ReversalStatus.OPEN.value if entry.is_reclaimable else ReversalStatus.NON_RECLAIMABLE.value

    payload = {
        "client_gstin_id": entry.client_gstin_id,
        "source_type": entry.source_type.value,
        "source_record_id": entry.source_record_id,
        "source_run_id": entry.source_run_id,
        "reversal_tax_period": entry.reversal_tax_period,
        "source_state_hash": entry.source_state_hash,
        "source_payload": entry.source_payload,
        "document_type": entry.document_type,
        "document_number": entry.document_number,
        "document_date": str(entry.document_date) if entry.document_date else None,
        "supplier_gstin": entry.supplier_gstin,
        "reference_doc": entry.reference_doc,
        "reversal_table4_cell": "4B2",
        "is_reclaimable": entry.is_reclaimable,
        "statutory_reason": entry.statutory_reason.value,
        "itc_financial_year": entry.itc_financial_year,
        "supplier_outward_statement_period": entry.supplier_outward_statement_period,
        "supplier_gstr1_filing_date": str(entry.supplier_gstr1_filing_date) if entry.supplier_gstr1_filing_date else None,
        "supplier_gstr3b_tax_period": entry.supplier_gstr3b_tax_period,
        "supplier_gstr3b_filing_status": entry.supplier_gstr3b_filing_status,
        "filed_by_september_30": entry.filed_by_september_30,
        "september_test_date": str(entry.september_test_date) if entry.september_test_date else None,
        "november_reversal_deadline": str(entry.november_reversal_deadline) if entry.november_reversal_deadline else None,
        "actual_reversal_date": str(entry.actual_reversal_date) if entry.actual_reversal_date else None,
        "subsequent_supplier_filing_date": str(entry.subsequent_supplier_filing_date) if entry.subsequent_supplier_filing_date else None,
        "subsequent_filing_arn": entry.subsequent_filing_arn,
        "condition_fulfilled_date": str(entry.condition_fulfilled_date) if entry.condition_fulfilled_date else None,
        "reclaim_eligibility_date": str(entry.reclaim_eligibility_date) if entry.reclaim_eligibility_date else None,
        "reversed_igst_paise": entry.reversed_igst_paise,
        "reversed_cgst_paise": entry.reversed_cgst_paise,
        "reversed_sgst_paise": entry.reversed_sgst_paise,
        "reversed_cess_paise": entry.reversed_cess_paise,
        "cached_reclaimed_igst_paise": 0,
        "cached_reclaimed_cgst_paise": 0,
        "cached_reclaimed_sgst_paise": 0,
        "cached_reclaimed_cess_paise": 0,
        "status": init_status,
        "created_by": entry.created_by,
    }

    res = sb.table("gstr3b_reversal_ledger").insert(payload).execute()
    if not res.data:
        raise RuntimeError("Failed to insert reversal ledger row.")
    return res.data[0]


def update_reversal_ledger_status(
    sb: Client,
    ledger_id: str,
    new_status: ReversalStatus,
    *,
    condition_fulfilled_date: Optional[date] = None,
    reclaim_eligibility_date: Optional[date] = None,
) -> dict[str, Any]:
    """Transition lifecycle status with strict reclaimability boundary enforcement."""
    ledger = get_reversal_ledger_entry(sb, ledger_id)
    if not ledger.get("is_reclaimable"):
        raise ValueError(
            f"REVERSAL_BOUNDARY_VIOLATION: Entry {ledger_id} has is_reclaimable=False "
            f"and cannot transition to status '{new_status.value}'."
        )

    updates: dict[str, Any] = {
        "status": new_status.value,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if condition_fulfilled_date:
        updates["condition_fulfilled_date"] = str(condition_fulfilled_date)
    if reclaim_eligibility_date:
        updates["reclaim_eligibility_date"] = str(reclaim_eligibility_date)

    res = sb.table("gstr3b_reversal_ledger").update(updates).eq("id", ledger_id).execute()
    return res.data[0]


def get_reversal_ledger_entry(sb: Client, ledger_id: str) -> dict[str, Any]:
    """Fetch single reversal ledger entry by UUID."""
    res = sb.table("gstr3b_reversal_ledger").select("*").eq("id", ledger_id).limit(1).execute()
    if not res.data:
        raise ValueError(f"Reversal ledger entry not found: {ledger_id}")
    return res.data[0]


def list_reversal_ledger_entries(
    sb: Client,
    client_gstin_id: str,
    *,
    status: Optional[str] = None,
    tax_period: Optional[str] = None,
    is_reclaimable: Optional[bool] = None,
) -> list[dict[str, Any]]:
    """List reversal ledger entries with filtering."""
    q = sb.table("gstr3b_reversal_ledger").select("*").eq("client_gstin_id", client_gstin_id)
    if status:
        q = q.eq("status", status)
    if tax_period:
        q = q.eq("reversal_tax_period", tax_period)
    if is_reclaimable is not None:
        q = q.eq("is_reclaimable", is_reclaimable)
    res = q.order("created_at", desc=True).execute()
    return res.data or []


def get_authoritative_reclaim_history(sb: Client, ledger_id: str) -> list[dict[str, Any]]:
    """Fetch immutable reclaim events for a reversal ledger row (authoritative source of truth)."""
    res = (
        sb.table("gstr3b_reclaim_events")
        .select("*")
        .eq("ledger_id", ledger_id)
        .order("created_at", desc=False)
        .execute()
    )
    return res.data or []


def calculate_available_balance(sb: Client, ledger_id: str) -> AvailableBalancePaise:
    """Calculate current available balance per tax head strictly from immutable reclaim events."""
    ledger = get_reversal_ledger_entry(sb, ledger_id)
    if not ledger.get("is_reclaimable"):
        return AvailableBalancePaise(igst_paise=0, cgst_paise=0, sgst_paise=0, cess_paise=0)

    events = get_authoritative_reclaim_history(sb, ledger_id)

    tot_reclaimed_igst = 0
    tot_reclaimed_cgst = 0
    tot_reclaimed_sgst = 0
    tot_reclaimed_cess = 0

    for e in events:
        mult = 1 if e.get("event_type", "RECLAIM") == "RECLAIM" else -1
        tot_reclaimed_igst += mult * int(e.get("reclaimed_igst_paise") or 0)
        tot_reclaimed_cgst += mult * int(e.get("reclaimed_cgst_paise") or 0)
        tot_reclaimed_sgst += mult * int(e.get("reclaimed_sgst_paise") or 0)
        tot_reclaimed_cess += mult * int(e.get("reclaimed_cess_paise") or 0)

    avail_igst = int(ledger.get("reversed_igst_paise") or 0) - tot_reclaimed_igst
    avail_cgst = int(ledger.get("reversed_cgst_paise") or 0) - tot_reclaimed_cgst
    avail_sgst = int(ledger.get("reversed_sgst_paise") or 0) - tot_reclaimed_sgst
    avail_cess = int(ledger.get("reversed_cess_paise") or 0) - tot_reclaimed_cess

    return AvailableBalancePaise(
        igst_paise=max(0, avail_igst),
        cgst_paise=max(0, avail_cgst),
        sgst_paise=max(0, avail_sgst),
        cess_paise=max(0, avail_cess),
    )


def execute_reclaim_event(sb: Client, req: ReclaimEventCreate) -> ReclaimExecutionResult:
    """Execute an atomic reclaim event against an eligible 4(B)(2) reversal ledger row."""
    # Try RPC stored procedure first
    try:
        rpc_params = {
            "p_ledger_id": req.ledger_id,
            "p_reclaim_run_id": req.reclaim_run_id,
            "p_reclaim_tax_period": req.reclaim_tax_period,
            "p_reclaimed_igst_paise": req.reclaimed_igst_paise,
            "p_reclaimed_cgst_paise": req.reclaimed_cgst_paise,
            "p_reclaimed_sgst_paise": req.reclaimed_sgst_paise,
            "p_reclaimed_cess_paise": req.reclaimed_cess_paise,
            "p_statutory_evidence_type": req.statutory_evidence_type.value,
            "p_evidence_reference": req.evidence_reference,
            "p_evidence_document_date": str(req.evidence_document_date) if req.evidence_document_date else None,
            "p_authorized_by": req.authorized_by,
            "p_reclaim_notes": req.reclaim_notes,
            "p_event_type": req.event_type.value,
            "p_compensates_event_id": req.compensates_event_id,
            "p_idempotency_key": req.idempotency_key.strip() if req.idempotency_key else None,
        }
        rpc_res = sb.rpc("fn_execute_reclaim_event", rpc_params).execute()
        if rpc_res.data and isinstance(rpc_res.data, dict):
            d = rpc_res.data
            return ReclaimExecutionResult(
                event_id=str(d.get("event_id")),
                ledger_id=str(d.get("ledger_id")),
                status=str(d.get("status")),
                is_idempotent_replay=bool(d.get("is_idempotent_replay", False)),
                event_type=req.event_type.value,
                reclaimed_igst_paise=int(d.get("reclaimed_igst_paise") or 0),
                reclaimed_cgst_paise=int(d.get("reclaimed_cgst_paise") or 0),
                reclaimed_sgst_paise=int(d.get("reclaimed_sgst_paise") or 0),
                reclaimed_cess_paise=int(d.get("reclaimed_cess_paise") or 0),
                remaining_igst_paise=int(d.get("remaining_igst_paise") or 0),
                remaining_cgst_paise=int(d.get("remaining_cgst_paise") or 0),
                remaining_sgst_paise=int(d.get("remaining_sgst_paise") or 0),
                remaining_cess_paise=int(d.get("remaining_cess_paise") or 0),
            )
    except Exception as e:
        err_msg = str(e)
        if any(k in err_msg for k in ("EXCESS_RECLAIM", "NEGATIVE_RECLAIM", "ZERO_RECLAIM", "REVERSAL_ENTRY_IS_NOT_RECLAIMABLE", "REVERSAL_LEDGER_ENTRY_NOT_FOUND")):
            raise ValueError(err_msg) from e
        _log.info("RPC not available, running python validation: %s", err_msg)

    # Python-level atomic execution (for mock/unit test suites)
    with _python_fallback_reclaim_lock:
        ledger = get_reversal_ledger_entry(sb, req.ledger_id)
        if not ledger.get("is_reclaimable") or ledger.get("status") == "NON_RECLAIMABLE":
            raise ValueError(f"REVERSAL_ENTRY_IS_NOT_RECLAIMABLE: Entry {req.ledger_id} has is_reclaimable=False.")

        cid = req.client_gstin_id or ledger.get("client_gstin_id")

        # Database-level dedicated idempotency check
        if req.idempotency_key and req.idempotency_key.strip():
            clean_key = req.idempotency_key.strip()
            ev_match = (
                sb.table("gstr3b_reclaim_events")
                .select("*")
                .eq("client_gstin_id", cid)
                .eq("idempotency_key", clean_key)
                .limit(1)
                .execute()
            )
            if ev_match.data:
                ev = ev_match.data[0]
                bal = calculate_available_balance(sb, req.ledger_id)
                return ReclaimExecutionResult(
                    event_id=str(ev.get("id")),
                    ledger_id=req.ledger_id,
                    status=str(ledger.get("status")),
                    is_idempotent_replay=True,
                    event_type=str(ev.get("event_type", "RECLAIM")),
                    reclaimed_igst_paise=int(ev.get("reclaimed_igst_paise") or 0),
                    reclaimed_cgst_paise=int(ev.get("reclaimed_cgst_paise") or 0),
                    reclaimed_sgst_paise=int(ev.get("reclaimed_sgst_paise") or 0),
                    reclaimed_cess_paise=int(ev.get("reclaimed_cess_paise") or 0),
                    remaining_igst_paise=bal.igst_paise,
                    remaining_cgst_paise=bal.cgst_paise,
                    remaining_sgst_paise=bal.sgst_paise,
                    remaining_cess_paise=bal.cess_paise,
                )

        events = get_authoritative_reclaim_history(sb, req.ledger_id)

        cur_igst = 0
        cur_cgst = 0
        cur_sgst = 0
        cur_cess = 0
        for e in events:
            mult = 1 if e.get("event_type", "RECLAIM") == "RECLAIM" else -1
            cur_igst += mult * int(e.get("reclaimed_igst_paise") or 0)
            cur_cgst += mult * int(e.get("reclaimed_cgst_paise") or 0)
            cur_sgst += mult * int(e.get("reclaimed_sgst_paise") or 0)
            cur_cess += mult * int(e.get("reclaimed_cess_paise") or 0)

        rev_igst = int(ledger.get("reversed_igst_paise") or 0)
        rev_cgst = int(ledger.get("reversed_cgst_paise") or 0)
        rev_sgst = int(ledger.get("reversed_sgst_paise") or 0)
        rev_cess = int(ledger.get("reversed_cess_paise") or 0)

        # Tax-head safe validation
        delta = 1 if req.event_type == ReclaimEventType.RECLAIM else -1
        if delta == 1:
            if (cur_igst + req.reclaimed_igst_paise) > rev_igst:
                raise ValueError(f"EXCESS_RECLAIM_IGST: Requested {req.reclaimed_igst_paise} exceeds available {rev_igst - cur_igst}")
            if (cur_cgst + req.reclaimed_cgst_paise) > rev_cgst:
                raise ValueError(f"EXCESS_RECLAIM_CGST: Requested {req.reclaimed_cgst_paise} exceeds available {rev_cgst - cur_cgst}")
            if (cur_sgst + req.reclaimed_sgst_paise) > rev_sgst:
                raise ValueError(f"EXCESS_RECLAIM_SGST: Requested {req.reclaimed_sgst_paise} exceeds available {rev_sgst - cur_sgst}")
            if (cur_cess + req.reclaimed_cess_paise) > rev_cess:
                raise ValueError(f"EXCESS_RECLAIM_CESS: Requested {req.reclaimed_cess_paise} exceeds available {rev_cess - cur_cess}")

        # Insert immutable reclaim event
        event_payload = {
            "client_gstin_id": cid,
            "ledger_id": req.ledger_id,
            "reclaim_run_id": req.reclaim_run_id,
            "reclaim_tax_period": req.reclaim_tax_period,
            "event_type": req.event_type.value,
            "compensates_event_id": req.compensates_event_id,
            "reclaimed_igst_paise": req.reclaimed_igst_paise,
            "reclaimed_cgst_paise": req.reclaimed_cgst_paise,
            "reclaimed_sgst_paise": req.reclaimed_sgst_paise,
            "reclaimed_cess_paise": req.reclaimed_cess_paise,
            "statutory_evidence_type": req.statutory_evidence_type.value,
            "evidence_reference": req.evidence_reference,
            "evidence_document_date": str(req.evidence_document_date) if req.evidence_document_date else None,
            "authorized_by": req.authorized_by,
            "reclaim_notes": req.reclaim_notes,
            "idempotency_key": req.idempotency_key.strip() if req.idempotency_key else None,
        }
        ins_res = sb.table("gstr3b_reclaim_events").insert(event_payload).execute()
        event_id = ins_res.data[0].get("id") if ins_res.data else "mock-event-id"

        # Compute new cached derived balances
        new_igst = cur_igst + (delta * req.reclaimed_igst_paise)
        new_cgst = cur_cgst + (delta * req.reclaimed_cgst_paise)
        new_sgst = cur_sgst + (delta * req.reclaimed_sgst_paise)
        new_cess = cur_cess + (delta * req.reclaimed_cess_paise)

        is_full = (
            new_igst == rev_igst
            and new_cgst == rev_cgst
            and new_sgst == rev_sgst
            and new_cess == rev_cess
        )
        if is_full:
            new_status = ReversalStatus.FULLY_RECLAIMED.value
        elif (new_igst + new_cgst + new_sgst + new_cess) > 0:
            new_status = ReversalStatus.PARTIALLY_RECLAIMED.value
        else:
            new_status = ReversalStatus.OPEN.value

        sb.table("gstr3b_reversal_ledger").update({
            "cached_reclaimed_igst_paise": new_igst,
            "cached_reclaimed_cgst_paise": new_cgst,
            "cached_reclaimed_sgst_paise": new_sgst,
            "cached_reclaimed_cess_paise": new_cess,
            "status": new_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", req.ledger_id).execute()

        return ReclaimExecutionResult(
            event_id=event_id,
            ledger_id=req.ledger_id,
            status=new_status,
            event_type=req.event_type.value,
            reclaimed_igst_paise=req.reclaimed_igst_paise,
            reclaimed_cgst_paise=req.reclaimed_cgst_paise,
            reclaimed_sgst_paise=req.reclaimed_sgst_paise,
            reclaimed_cess_paise=req.reclaimed_cess_paise,
            remaining_igst_paise=rev_igst - new_igst,
            remaining_cgst_paise=rev_cgst - new_cgst,
            remaining_sgst_paise=rev_sgst - new_sgst,
            remaining_cess_paise=rev_cess - new_cess,
        )


# ---------------------------------------------------------------------------
# Phase 3C: Lifecycle Transitions & Validation
# ---------------------------------------------------------------------------

def fulfill_reversal_condition(
    sb: Client,
    ledger_id: str,
    evidence_type: StatutoryEvidenceType,
    evidence_reference: str,
    *,
    evidence_document_date: Optional[date] = None,
    condition_fulfilled_date: Optional[date] = None,
    notes: Optional[str] = None,
) -> dict[str, Any]:
    """Transition an open reversal to CONDITION_FULFILLED with required statutory evidence."""
    ledger = get_reversal_ledger_entry(sb, ledger_id)
    if not ledger.get("is_reclaimable") or ledger.get("status") == ReversalStatus.NON_RECLAIMABLE.value:
        raise ValueError(
            f"REVERSAL_BOUNDARY_VIOLATION: Entry {ledger_id} is non-reclaimable and cannot fulfill conditions."
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    c_date = condition_fulfilled_date or date.today()

    updates: dict[str, Any] = {
        "status": ReversalStatus.CONDITION_FULFILLED.value,
        "condition_fulfilled_date": str(c_date),
        "updated_at": now_iso,
    }
    sp = ledger.get("source_payload") or {}
    sp["evidence_fulfilled"] = {
        "type": evidence_type.value,
        "reference": evidence_reference,
        "document_date": str(evidence_document_date) if evidence_document_date else None,
        "fulfilled_date": str(c_date),
        "notes": notes,
    }
    updates["source_payload"] = sp

    res = sb.table("gstr3b_reversal_ledger").update(updates).eq("id", ledger_id).execute()
    return res.data[0] if res.data else {}


def authorize_reclaim(
    sb: Client,
    ledger_id: str,
    authorized_by: str,
    *,
    reclaim_eligibility_date: Optional[date] = None,
) -> dict[str, Any]:
    """Authorize an entry whose condition has been fulfilled (or open) for reclaim in GSTR-3B."""
    ledger = get_reversal_ledger_entry(sb, ledger_id)
    if not ledger.get("is_reclaimable") or ledger.get("status") == ReversalStatus.NON_RECLAIMABLE.value:
        raise ValueError(
            f"REVERSAL_BOUNDARY_VIOLATION: Entry {ledger_id} is non-reclaimable and cannot be authorized for reclaim."
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    r_date = reclaim_eligibility_date or date.today()

    updates = {
        "status": ReversalStatus.RECLAIM_AUTHORIZED.value,
        "reclaim_eligibility_date": str(r_date),
        "updated_at": now_iso,
    }
    res = sb.table("gstr3b_reversal_ledger").update(updates).eq("id", ledger_id).execute()
    return res.data[0] if res.data else {}


def validate_reclaim_request(sb: Client, req: ReclaimEventCreate) -> tuple[bool, Optional[str]]:
    """Validate whether a requested reclaim event is legally and mathematically permissible."""
    try:
        ledger = get_reversal_ledger_entry(sb, req.ledger_id)
    except Exception:
        return False, f"REVERSAL_LEDGER_ENTRY_NOT_FOUND: {req.ledger_id}"

    if not ledger.get("is_reclaimable") or ledger.get("status") == ReversalStatus.NON_RECLAIMABLE.value:
        return False, f"REVERSAL_ENTRY_IS_NOT_RECLAIMABLE: Entry {req.ledger_id} is non-reclaimable."

    cur_status = ledger.get("status")
    allowed_statuses = (
        ReversalStatus.OPEN.value,
        ReversalStatus.CONDITION_FULFILLED.value,
        ReversalStatus.RECLAIM_AUTHORIZED.value,
        ReversalStatus.PARTIALLY_RECLAIMED.value,
    )
    if cur_status not in allowed_statuses:
        return False, f"INVALID_STATUS_FOR_RECLAIM: Current status '{cur_status}' is not eligible for reclaim."

    bal = calculate_available_balance(sb, req.ledger_id)
    if req.event_type == ReclaimEventType.RECLAIM:
        if req.reclaimed_igst_paise > bal.igst_paise:
            return False, f"EXCESS_RECLAIM_IGST: Requested {req.reclaimed_igst_paise} exceeds available {bal.igst_paise} paise."
        if req.reclaimed_cgst_paise > bal.cgst_paise:
            return False, f"EXCESS_RECLAIM_CGST: Requested {req.reclaimed_cgst_paise} exceeds available {bal.cgst_paise} paise."
        if req.reclaimed_sgst_paise > bal.sgst_paise:
            return False, f"EXCESS_RECLAIM_SGST: Requested {req.reclaimed_sgst_paise} exceeds available {bal.sgst_paise} paise."
        if req.reclaimed_cess_paise > bal.cess_paise:
            return False, f"EXCESS_RECLAIM_CESS: Requested {req.reclaimed_cess_paise} exceeds available {bal.cess_paise} paise."

    return True, None


def get_reclaimable_reversals(
    sb: Client,
    client_gstin_id: str,
    *,
    tax_period: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Retrieve all open/authorized reversal ledger entries that possess available reclaim balances."""
    q = (
        sb.table("gstr3b_reversal_ledger")
        .select("*")
        .eq("client_gstin_id", client_gstin_id)
        .eq("is_reclaimable", True)
        .in_("status", [
            ReversalStatus.OPEN.value,
            ReversalStatus.CONDITION_FULFILLED.value,
            ReversalStatus.RECLAIM_AUTHORIZED.value,
            ReversalStatus.PARTIALLY_RECLAIMED.value,
        ])
    )
    if tax_period:
        q = q.lte("reversal_tax_period", tax_period)

    res = q.order("reversal_tax_period", desc=False).execute()
    rows = res.data or []

    result = []
    for r in rows:
        bal = calculate_available_balance(sb, r["id"])
        if bal.total_paise > 0:
            entry_copy = dict(r)
            entry_copy["available_balance"] = bal.model_dump()
            result.append(entry_copy)
    return result


# ---------------------------------------------------------------------------
# Phase 3C: Automatic 4(B)(2) Reversal Registration from Table 4 Snapshot
# ---------------------------------------------------------------------------

def register_table4_reversals_to_ledger(
    sb: Client,
    run_id: str,
    user_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Inspect Table 4 compilation for run_id and register all 4(B)(2) temporary reversals into ledger.

    Strict Invariants:
    1. Only 4(B)(2) records are registered (Table 4(B)(1) and Table 4(D)(2) are strictly excluded).
    2. Idempotent: Does not insert duplicate rows for the same source_type and source_record_id within this run.
    3. Proper classification: Rule 37 -> RULE_37_NON_PAYMENT, Rule 37A -> RULE_37A_SUPPLIER_NON_FILING,
       Section 16(2)(b) -> SECTION_16_2_B_NOT_RECEIVED.
    4. Sealed source state digest and payload persisted.
    """
    from app.services import reconciliation_outcomes as ro
    from app.services.gstr3b_table4_engine import (
        extract_tax_heads_paise,
        is_credit_note,
        is_section_16_4_or_pos_restricted,
        load_exception_dispositions,
        load_table4_adjustments,
        RULE37_CONCERNS,
    )

    r_row = sb.table("reconciliation_run").select("id, client_gstin_id, period").eq("id", run_id).limit(1).execute()
    if not r_row.data:
        raise ValueError(f"Reconciliation run not found: {run_id}")
    client_gstin_id = r_row.data[0]["client_gstin_id"]
    tax_period = r_row.data[0]["period"]

    p = ro.load_payload(sb, run_id) or {}
    all_outcomes = ro.build_outcome_rows(sb, run_id, p)[0]
    gstr_db = ro.load_gstr_map(sb, run_id)
    pr_db = ro.load_pr_map(sb, run_id)
    dispositions = load_exception_dispositions(sb, run_id)
    adjustments = load_table4_adjustments(sb, run_id)

    registered: list[dict[str, Any]] = []

    # Fetch already registered entries for this run to maintain idempotency
    existing_ledger = sb.table("gstr3b_reversal_ledger").select("source_record_id, source_type").eq("source_run_id", run_id).execute()
    existing_keys = {(x["source_type"], x["source_record_id"]) for x in (existing_ledger.data or [])}

    for r in all_outcomes:
        rec_id = r.id
        if rec_id.startswith("de:") or r.category == "duplicate_entry":
            continue

        pid = r.matched_pr_id or ""
        gid = rec_id.removeprefix("pm:").removeprefix("gstr:") if (rec_id.startswith("pm:") or rec_id.startswith("gstr:")) else ""

        g_entry = gstr_db.get(gid) or {}
        g_rd = g_entry.get("record_data") if isinstance(g_entry.get("record_data"), dict) else {}
        p_entry = pr_db.get(pid) or {}
        p_rd = p_entry.get("record_data") if isinstance(p_entry.get("record_data"), dict) else {}

        # Exclude 4D2 restricted records
        disp_4d2 = dispositions.get(f"{rec_id}:TIME_BARRED_16_4") or dispositions.get(f"{rec_id}:POS_RESTRICTED") or dispositions.get(rec_id)
        is_4d2, _ = is_section_16_4_or_pos_restricted(r, g_rd, p_rd, disp_4d2)
        if is_4d2:
            continue

        igst_p, cgst_p, sgst_p, cess_p = extract_tax_heads_paise(g_rd or p_rd)
        cn = is_credit_note(g_rd or p_rd, r)
        sign = -1 if cn else 1
        sig_igst = sign * igst_p
        sig_cgst = sign * cgst_p
        sig_sgst = sign * sgst_p
        sig_cess = sign * cess_p

        disp_r37 = dispositions.get(f"{rec_id}:RULE_37") or dispositions.get(rec_id)
        disp_r37a = dispositions.get(f"{rec_id}:RULE_37A") or dispositions.get(rec_id)
        disp_2b = dispositions.get(f"{rec_id}:TWO_B_ONLY") or dispositions.get(rec_id)
        disp_162b = (
            dispositions.get(f"{rec_id}:SECTION_16_2_B")
            or dispositions.get(f"{rec_id}:GOODS_NOT_RECEIVED")
            or dispositions.get(rec_id)
        )

        is_r37 = (
            r.category == "rule37_warnings" or bool(r.rule37_flag) or str(r.match_status).upper() in RULE37_CONCERNS
        ) and not (r.match_status == "RULE37A" or r.rule37a_flag)
        is_disp_r37_reversed = bool(
            disp_r37
            and str(disp_r37.get("disposition", "")).upper() in ("REVERSED", "REVERSAL_CONFIRMED")
            and (
                str(disp_r37.get("table4_effect", "")).upper() == "4B2"
                or str(disp_r37.get("exception_type", "")).upper() == "RULE_37"
            )
        )
        is_r37_reversed = is_disp_r37_reversed or (
            is_r37 and bool(disp_r37 and str(disp_r37.get("disposition", "")).upper() in ("REVERSED", "REVERSAL_CONFIRMED"))
        )

        is_r37a = (r.match_status == "RULE37A" or r.rule37a_flag)
        is_r37a_reversed = is_r37a and bool(disp_r37a and str(disp_r37a.get("disposition", "")).upper() in ("REVERSED", "REVERSAL_CONFIRMED", "RULE_37A_VERIFIED", "CONFIRMED_NON_FILER"))

        is_162b_reversed = bool(
            disp_162b
            and str(disp_162b.get("disposition", "")).upper() in (
                "REVERSED", "SECTION_16_2_B_REVERSED", "CONFIRMED_NOT_RECEIVED"
            )
        )

        is_2b_only_162b = (
            (rec_id.startswith("gstr:") or (not pid and not rec_id.startswith("pm:")))
            and bool(disp_2b and str(disp_2b.get("disposition", "")).upper() == "SECTION_16_2_B_REVERSED")
        )

        # Determine if this outcome created a 4B2 temporary reversal
        stat_reason = None
        if is_r37_reversed:
            stat_reason = StatutoryTemporaryReason.RULE_37_NON_PAYMENT
        elif is_r37a_reversed:
            stat_reason = StatutoryTemporaryReason.RULE_37A_SUPPLIER_NON_FILING
        elif is_162b_reversed or is_2b_only_162b:
            stat_reason = StatutoryTemporaryReason.SECTION_16_2_B_NOT_RECEIVED

        if not stat_reason:
            continue

        tot_p = sig_igst + sig_cgst + sig_sgst + sig_cess
        if tot_p <= 0:
            continue

        key = (ReversalProvenanceType.RECON_OUTCOME.value, rec_id)
        if key in existing_keys:
            continue

        # Extract Rule 37A provenance metadata if applicable
        r37a_dict = disp_r37a if (disp_r37a and is_r37a_reversed) else {}

        # Parse document date safely
        doc_date = None
        raw_date = str(r.invoice_date or "")[:10]
        if raw_date and len(raw_date) == 10:
            try:
                doc_date = date.fromisoformat(raw_date)
            except Exception:
                pass

        entry_model = ReversalLedgerCreate(
            client_gstin_id=client_gstin_id,
            source_type=ReversalProvenanceType.RECON_OUTCOME,
            source_record_id=rec_id,
            source_run_id=run_id,
            reversal_tax_period=tax_period,
            document_type="CREDIT_NOTE" if cn else "INVOICE",
            document_number=r.invoice_number,
            document_date=doc_date,
            supplier_gstin=r.supplier_gstin,
            reversal_table4_cell="4B2",
            is_reclaimable=True,
            statutory_reason=stat_reason,
            itc_financial_year=r37a_dict.get("itc_financial_year"),
            supplier_outward_statement_period=r37a_dict.get("supplier_outward_statement_period"),
            supplier_gstr3b_tax_period=r37a_dict.get("supplier_gstr3b_tax_period"),
            supplier_gstr3b_filing_status=r37a_dict.get("supplier_gstr3b_filing_status", "UNFILED"),
            filed_by_september_30=bool(r37a_dict.get("filed_by_september_30", False)),
            reversed_igst_paise=max(0, sig_igst),
            reversed_cgst_paise=max(0, sig_cgst),
            reversed_sgst_paise=max(0, sig_sgst),
            reversed_cess_paise=max(0, sig_cess),
            created_by=user_id,
            source_payload={
                "outcome_id": rec_id,
                "invoice_number": r.invoice_number,
                "supplier_gstin": r.supplier_gstin,
                "statutory_reason": stat_reason.value,
                "reversal_tax_period": tax_period,
            },
        )
        saved = create_reversal_ledger_entry(sb, entry_model)
        registered.append(saved)
        existing_keys.add(key)

    # Also register external 4B2 adjustments
    for adj in adjustments:
        if str(adj.get("row_id") or "").upper() != "4B2":
            continue
        adj_id = str(adj.get("id"))
        key = (ReversalProvenanceType.STATUTORY_ADJUSTMENT.value, adj_id)
        if key in existing_keys:
            continue

        igst_a = int(adj.get("igst_paise") or 0)
        cgst_a = int(adj.get("cgst_paise") or 0)
        sgst_a = int(adj.get("sgst_paise") or 0)
        cess_a = int(adj.get("cess_paise") or 0)
        if (igst_a + cgst_a + sgst_a + cess_a) <= 0:
            continue

        is_rec = adj.get("is_reclaimable", True)
        raw_reason = str(adj.get("statutory_reason") or adj.get("reason") or "OTHER_TEMPORARY").upper()
        if "37A" in raw_reason:
            stat_cat = StatutoryTemporaryReason.RULE_37A_SUPPLIER_NON_FILING
        elif "37" in raw_reason:
            stat_cat = StatutoryTemporaryReason.RULE_37_NON_PAYMENT
        elif "16(2)(B)" in raw_reason or "16_2_B" in raw_reason:
            stat_cat = StatutoryTemporaryReason.SECTION_16_2_B_NOT_RECEIVED
        elif "16(2)(C)" in raw_reason or "16_2_C" in raw_reason:
            stat_cat = StatutoryTemporaryReason.SECTION_16_2_C_SUPPLIER_TAX_CONDITION
        else:
            stat_cat = StatutoryTemporaryReason.OTHER_TEMPORARY

        adj_model = ReversalLedgerCreate(
            client_gstin_id=client_gstin_id,
            source_type=ReversalProvenanceType.STATUTORY_ADJUSTMENT,
            source_record_id=adj_id,
            source_run_id=run_id,
            reversal_tax_period=tax_period,
            document_type="ADJUSTMENT",
            reference_doc=str(adj.get("reference_doc") or f"ADJ-{adj_id[:8]}"),
            reversal_table4_cell="4B2",
            is_reclaimable=is_rec,
            statutory_reason=stat_cat,
            reversed_igst_paise=igst_a,
            reversed_cgst_paise=cgst_a,
            reversed_sgst_paise=sgst_a,
            reversed_cess_paise=cess_a,
            created_by=user_id,
            source_payload=adj,
        )
        saved = create_reversal_ledger_entry(sb, adj_model)
        registered.append(saved)
        existing_keys.add(key)

    return registered
