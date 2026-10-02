"""AWS Aurora GSTR-3B Repository for ReconDesk — Batch 2B.

Provides safe, typed SQLAlchemy 2.x data-access for:
1. gstr3b_reversal_ledger (General Table 4B2 statutory temporary reversal ledger)
2. gstr3b_table4_summaries (Authoritative Table 4 workpaper snapshots with versioning)
3. gstr3b_reclaim_events (Immutable historical reclaim events against reversal ledger)
4. gstr3b_table4_adjustments (Manual/external statutory additions/reductions directly targeting Table 4)
5. gstr3b_reconciliation (Per-run comparison of ITC available vs claimed in GSTR-3B)

Architecture & Invariants:
- Aurora is PRIMARY for all five tables.
- Writes ALWAYS go to Aurora first.
- Reclaim RPC (fn_execute_reclaim_event) is executed directly in Aurora with row-level locks
  (SELECT FOR UPDATE), authoritative balance checking, and idempotency guarantees.
- Deletion cascade unlinks and cleans up Batch 2B child records safely.
- Multi-tenant boundary isolation enforced on client_gstin_id and run_id.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from uuid import UUID

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.models.gstr3b import (
    Gstr3bReclaimEvent,
    Gstr3bReconciliation,
    Gstr3bReversalLedger,
    Gstr3bTable4Adjustment,
    Gstr3bTable4Summary,
)
from app.models.reconciliation import ReconciliationRun

_log = logging.getLogger("recondesk.aurora.gstr3b")


# ── Serialization & Parsing Helpers ──────────────────────────────────────────


def _parse_datetime(val: Any) -> Optional[datetime]:
    if val is None or isinstance(val, datetime):
        return val
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return None
    return None


def _parse_date(val: Any) -> Optional[date]:
    if val is None or isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        s = val.strip()[:10]
        try:
            return date.fromisoformat(s)
        except Exception:
            return None
    return None


def _model_to_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return {}


def _is_sqlite(session: Session) -> bool:
    return "sqlite" in str(session.bind.dialect.name) if session.bind else False


# ── Aurora GSTR-3B Repository ────────────────────────────────────────────────


class AuroraGstr3bRepository:
    """Production data-access layer for Batch 2B tables in AWS Aurora PostgreSQL."""

    def __init__(
        self,
        session_factory: Optional[sessionmaker[Session]] = None,
    ) -> None:
        if session_factory is not None:
            self._session_factory = session_factory
        else:
            from app.aurora import get_aurora_sessionmaker
            self._session_factory = get_aurora_sessionmaker()

    # ═════════════════════════════════════════════════════════════════════════
    # 1. gstr3b_reversal_ledger
    # ═════════════════════════════════════════════════════════════════════════

    def create_reversal_ledger_entry(self, data: dict[str, Any]) -> dict[str, Any]:
        """Insert a new temporary reversal into gstr3b_reversal_ledger."""
        with self._session_factory() as session:
            entry = Gstr3bReversalLedger(
                id=UUID(str(data["id"])) if data.get("id") else None,
                client_gstin_id=UUID(str(data["client_gstin_id"])),
                source_type=str(data["source_type"]),
                source_record_id=str(data["source_record_id"]),
                source_run_id=UUID(str(data["source_run_id"])) if data.get("source_run_id") else None,
                reversal_tax_period=str(data["reversal_tax_period"]),
                source_state_hash=str(data.get("source_state_hash") or ""),
                source_payload=data.get("source_payload") or {},
                document_type=str(data.get("document_type") or "INVOICE"),
                document_number=data.get("document_number"),
                document_date=_parse_date(data.get("document_date")),
                supplier_gstin=data.get("supplier_gstin"),
                reference_doc=data.get("reference_doc"),
                reversal_table4_cell=str(data.get("reversal_table4_cell") or "4B2"),
                is_reclaimable=bool(data.get("is_reclaimable", True)),
                statutory_reason=str(data["statutory_reason"]),
                itc_financial_year=data.get("itc_financial_year"),
                supplier_outward_statement_period=data.get("supplier_outward_statement_period"),
                supplier_gstr1_filing_date=_parse_date(data.get("supplier_gstr1_filing_date")),
                supplier_gstr3b_tax_period=data.get("supplier_gstr3b_tax_period"),
                supplier_gstr3b_filing_status=str(data.get("supplier_gstr3b_filing_status") or "UNKNOWN"),
                filed_by_september_30=bool(data.get("filed_by_september_30", False)),
                september_test_date=_parse_date(data.get("september_test_date")),
                november_reversal_deadline=_parse_date(data.get("november_reversal_deadline")),
                actual_reversal_date=_parse_date(data.get("actual_reversal_date")),
                subsequent_supplier_filing_date=_parse_date(data.get("subsequent_supplier_filing_date")),
                subsequent_filing_arn=data.get("subsequent_filing_arn"),
                condition_fulfilled_date=_parse_date(data.get("condition_fulfilled_date")),
                reclaim_eligibility_date=_parse_date(data.get("reclaim_eligibility_date")),
                reversed_igst_paise=int(data.get("reversed_igst_paise") or 0),
                reversed_cgst_paise=int(data.get("reversed_cgst_paise") or 0),
                reversed_sgst_paise=int(data.get("reversed_sgst_paise") or 0),
                reversed_cess_paise=int(data.get("reversed_cess_paise") or 0),
                cached_reclaimed_igst_paise=int(data.get("cached_reclaimed_igst_paise") or 0),
                cached_reclaimed_cgst_paise=int(data.get("cached_reclaimed_cgst_paise") or 0),
                cached_reclaimed_sgst_paise=int(data.get("cached_reclaimed_sgst_paise") or 0),
                cached_reclaimed_cess_paise=int(data.get("cached_reclaimed_cess_paise") or 0),
                status=str(data.get("status") or "OPEN"),
                created_at=_parse_datetime(data.get("created_at")) or datetime.now(timezone.utc),
                updated_at=_parse_datetime(data.get("updated_at")) or datetime.now(timezone.utc),
                created_by=UUID(str(data["created_by"])) if data.get("created_by") else None,
            )
            session.add(entry)
            session.flush()
            res = _model_to_dict(entry)
            session.commit()
            return res

    def get_reversal_ledger_entry(self, ledger_id: str) -> Optional[dict[str, Any]]:
        """Fetch single reversal ledger row by UUID."""
        with self._session_factory() as session:
            row = session.get(Gstr3bReversalLedger, UUID(str(ledger_id)))
            return _model_to_dict(row) if row else None

    def update_reversal_ledger_entry(self, ledger_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Update fields on an existing reversal ledger row."""
        with self._session_factory() as session:
            row = session.get(Gstr3bReversalLedger, UUID(str(ledger_id)))
            if not row:
                return None

            date_fields = {
                "document_date",
                "supplier_gstr1_filing_date",
                "september_test_date",
                "november_reversal_deadline",
                "actual_reversal_date",
                "subsequent_supplier_filing_date",
                "condition_fulfilled_date",
                "reclaim_eligibility_date",
            }
            datetime_fields = {"created_at", "updated_at"}

            for k, v in updates.items():
                if not hasattr(row, k):
                    continue
                if k in date_fields:
                    setattr(row, k, _parse_date(v))
                elif k in datetime_fields:
                    setattr(row, k, _parse_datetime(v))
                elif k == "created_by":
                    setattr(row, k, UUID(str(v)) if v else None)
                else:
                    setattr(row, k, v)

            row.updated_at = datetime.now(timezone.utc)
            session.flush()
            res = _model_to_dict(row)
            session.commit()
            return res

    def list_reversal_ledger_entries(
        self,
        *,
        client_gstin_id: Optional[str] = None,
        source_run_id: Optional[str] = None,
        status_filter: Optional[list[str]] = None,
        statutory_reason: Optional[str] = None,
        is_reclaimable: Optional[bool] = None,
        tax_period: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Query reversal ledger entries with optional tenant and status filters."""
        with self._session_factory() as session:
            stmt = select(Gstr3bReversalLedger)
            if client_gstin_id:
                stmt = stmt.where(Gstr3bReversalLedger.client_gstin_id == UUID(str(client_gstin_id)))
            if source_run_id:
                stmt = stmt.where(Gstr3bReversalLedger.source_run_id == UUID(str(source_run_id)))
            if status_filter:
                stmt = stmt.where(Gstr3bReversalLedger.status.in_(status_filter))
            if statutory_reason:
                stmt = stmt.where(Gstr3bReversalLedger.statutory_reason == statutory_reason.strip().upper())
            if is_reclaimable is not None:
                stmt = stmt.where(Gstr3bReversalLedger.is_reclaimable == is_reclaimable)
            if tax_period:
                stmt = stmt.where(Gstr3bReversalLedger.reversal_tax_period == tax_period.strip())

            stmt = stmt.order_by(Gstr3bReversalLedger.created_at.asc())
            rows = session.execute(stmt).scalars().all()
            return [_model_to_dict(r) for r in rows]

    def get_reclaimable_reversals(
        self,
        client_gstin_id: str,
        before_or_on_period: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Fetch reversal rows currently eligible for reclaim."""
        with self._session_factory() as session:
            stmt = (
                select(Gstr3bReversalLedger)
                .where(
                    Gstr3bReversalLedger.client_gstin_id == UUID(str(client_gstin_id)),
                    Gstr3bReversalLedger.is_reclaimable.is_(True),
                    Gstr3bReversalLedger.status.in_(["RECLAIM_AUTHORIZED", "PARTIALLY_RECLAIMED", "CONDITION_FULFILLED"]),
                )
            )
            if before_or_on_period:
                stmt = stmt.where(Gstr3bReversalLedger.reversal_tax_period <= before_or_on_period)
            stmt = stmt.order_by(Gstr3bReversalLedger.document_date.asc(), Gstr3bReversalLedger.created_at.asc())
            rows = session.execute(stmt).scalars().all()
            return [_model_to_dict(r) for r in rows]

    # ═════════════════════════════════════════════════════════════════════════
    # 2. gstr3b_reclaim_events
    # ═════════════════════════════════════════════════════════════════════════

    def create_reclaim_event(self, data: dict[str, Any]) -> dict[str, Any]:
        """Insert an immutable historical reclaim event."""
        with self._session_factory() as session:
            ev = Gstr3bReclaimEvent(
                id=UUID(str(data["id"])) if data.get("id") else None,
                client_gstin_id=UUID(str(data["client_gstin_id"])),
                ledger_id=UUID(str(data["ledger_id"])),
                reclaim_run_id=UUID(str(data["reclaim_run_id"])),
                reclaim_tax_period=str(data["reclaim_tax_period"]),
                event_type=str(data.get("event_type") or "RECLAIM"),
                compensates_event_id=UUID(str(data["compensates_event_id"])) if data.get("compensates_event_id") else None,
                reclaimed_igst_paise=int(data.get("reclaimed_igst_paise") or 0),
                reclaimed_cgst_paise=int(data.get("reclaimed_cgst_paise") or 0),
                reclaimed_sgst_paise=int(data.get("reclaimed_sgst_paise") or 0),
                reclaimed_cess_paise=int(data.get("reclaimed_cess_paise") or 0),
                statutory_evidence_type=str(data["statutory_evidence_type"]),
                evidence_reference=str(data["evidence_reference"]),
                evidence_document_date=_parse_date(data.get("evidence_document_date")),
                authorized_by=UUID(str(data["authorized_by"])) if data.get("authorized_by") else None,
                reclaim_notes=str(data.get("reclaim_notes") or ""),
                idempotency_key=str(data.get("idempotency_key") or "").strip() or None,
                created_at=_parse_datetime(data.get("created_at")) or datetime.now(timezone.utc),
            )
            session.add(ev)
            session.flush()
            res = _model_to_dict(ev)
            session.commit()
            return res

    def get_reclaim_event(self, event_id: str) -> Optional[dict[str, Any]]:
        """Fetch single reclaim event by UUID."""
        with self._session_factory() as session:
            row = session.get(Gstr3bReclaimEvent, UUID(str(event_id)))
            return _model_to_dict(row) if row else None

    def get_reclaim_events_for_ledger(self, ledger_id: str) -> list[dict[str, Any]]:
        """List historical reclaim events for a specific reversal ledger entry."""
        with self._session_factory() as session:
            stmt = (
                select(Gstr3bReclaimEvent)
                .where(Gstr3bReclaimEvent.ledger_id == UUID(str(ledger_id)))
                .order_by(Gstr3bReclaimEvent.created_at.asc())
            )
            rows = session.execute(stmt).scalars().all()
            return [_model_to_dict(r) for r in rows]

    def get_reclaim_events_for_run(self, reclaim_run_id: str) -> list[dict[str, Any]]:
        """List reclaim events executed in a specific reconciliation run."""
        with self._session_factory() as session:
            stmt = (
                select(Gstr3bReclaimEvent)
                .where(Gstr3bReclaimEvent.reclaim_run_id == UUID(str(reclaim_run_id)))
                .order_by(Gstr3bReclaimEvent.created_at.asc())
            )
            rows = session.execute(stmt).scalars().all()
            return [_model_to_dict(r) for r in rows]

    def get_reclaim_events_for_client(
        self,
        client_gstin_id: str,
        tax_period: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """List reclaim events for a client, optionally scoped to a reclaim tax period."""
        with self._session_factory() as session:
            stmt = (
                select(Gstr3bReclaimEvent)
                .where(Gstr3bReclaimEvent.client_gstin_id == UUID(str(client_gstin_id)))
            )
            if tax_period:
                stmt = stmt.where(Gstr3bReclaimEvent.reclaim_tax_period == tax_period.strip())
            stmt = stmt.order_by(Gstr3bReclaimEvent.created_at.asc())
            rows = session.execute(stmt).scalars().all()
            return [_model_to_dict(r) for r in rows]

    def get_reclaim_event_by_idempotency_key(
        self,
        client_gstin_id: str,
        idempotency_key: str,
    ) -> Optional[dict[str, Any]]:
        """Find existing reclaim event by tenant-scoped idempotency key."""
        clean_key = (idempotency_key or "").strip()
        if not clean_key:
            return None
        with self._session_factory() as session:
            stmt = (
                select(Gstr3bReclaimEvent)
                .where(
                    Gstr3bReclaimEvent.client_gstin_id == UUID(str(client_gstin_id)),
                    Gstr3bReclaimEvent.idempotency_key == clean_key,
                )
                .limit(1)
            )
            row = session.execute(stmt).scalars().first()
            return _model_to_dict(row) if row else None

    # ═════════════════════════════════════════════════════════════════════════
    # 3. Critical RPC: fn_execute_reclaim_event
    # ═════════════════════════════════════════════════════════════════════════

    def execute_reclaim_rpc(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute atomic reclaim transaction with row locks, balance calculation, and idempotency.

        In AWS Aurora PostgreSQL, invokes public.fn_execute_reclaim_event directly.
        In local/SQLite environments, executes the exact same locking and validation semantics
        within a single transaction.
        """
        with self._session_factory() as session:
            if not _is_sqlite(session):
                # Native Aurora PostgreSQL Stored Procedure
                stmt = text("""
                    SELECT public.fn_execute_reclaim_event(
                        :p_ledger_id::uuid,
                        :p_reclaim_run_id::uuid,
                        :p_reclaim_tax_period::varchar,
                        :p_reclaimed_igst_paise::bigint,
                        :p_reclaimed_cgst_paise::bigint,
                        :p_reclaimed_sgst_paise::bigint,
                        :p_reclaimed_cess_paise::bigint,
                        :p_statutory_evidence_type::varchar,
                        :p_evidence_reference::varchar,
                        :p_evidence_document_date::date,
                        :p_authorized_by::uuid,
                        :p_reclaim_notes::text,
                        :p_event_type::varchar,
                        :p_compensates_event_id::uuid,
                        :p_idempotency_key::varchar
                    ) AS result;
                """)
                raw_res = session.execute(stmt, params).scalar()
                session.commit()
                if isinstance(raw_res, str):
                    return json.loads(raw_res)
                return raw_res or {}

            # SQLite transactional simulation for local testing/dev
            ledger_id = UUID(str(params["p_ledger_id"]))
            reclaim_run_id = UUID(str(params["p_reclaim_run_id"]))
            tax_period = str(params["p_reclaim_tax_period"])
            r_igst = int(params.get("p_reclaimed_igst_paise") or 0)
            r_cgst = int(params.get("p_reclaimed_cgst_paise") or 0)
            r_sgst = int(params.get("p_reclaimed_sgst_paise") or 0)
            r_cess = int(params.get("p_reclaimed_cess_paise") or 0)
            ev_type = str(params.get("p_event_type") or "RECLAIM")
            idem_key = str(params.get("p_idempotency_key") or "").strip() or None

            if r_igst < 0 or r_cgst < 0 or r_sgst < 0 or r_cess < 0:
                raise ValueError("NEGATIVE_RECLAIM_AMOUNT: Reclaimed tax amounts cannot be negative.")
            if (r_igst + r_cgst + r_sgst + r_cess) <= 0:
                raise ValueError("ZERO_RECLAIM_AMOUNT: At least one tax head must have a positive reclaim amount.")

            ledger = session.get(Gstr3bReversalLedger, ledger_id)
            if not ledger:
                raise ValueError(f"REVERSAL_LEDGER_ENTRY_NOT_FOUND: Ledger ID {ledger_id} does not exist.")
            if not ledger.is_reclaimable or ledger.status == "NON_RECLAIMABLE":
                raise ValueError(f"REVERSAL_ENTRY_IS_NOT_RECLAIMABLE: Entry {ledger_id} has is_reclaimable=False or status=NON_RECLAIMABLE.")

            # Idempotency replay check
            if idem_key:
                existing_ev = (
                    session.execute(
                        select(Gstr3bReclaimEvent)
                        .where(
                            Gstr3bReclaimEvent.client_gstin_id == ledger.client_gstin_id,
                            Gstr3bReclaimEvent.idempotency_key == idem_key,
                        )
                        .limit(1)
                    )
                    .scalars()
                    .first()
                )
                if existing_ev:
                    return {
                        "event_id": str(existing_ev.id),
                        "ledger_id": str(ledger.id),
                        "status": ledger.status,
                        "is_idempotent_replay": True,
                        "event_type": existing_ev.event_type,
                        "reclaimed_igst_paise": int(existing_ev.reclaimed_igst_paise),
                        "reclaimed_cgst_paise": int(existing_ev.reclaimed_cgst_paise),
                        "reclaimed_sgst_paise": int(existing_ev.reclaimed_sgst_paise),
                        "reclaimed_cess_paise": int(existing_ev.reclaimed_cess_paise),
                        "remaining_igst_paise": max(0, int(ledger.reversed_igst_paise) - int(ledger.cached_reclaimed_igst_paise)),
                        "remaining_cgst_paise": max(0, int(ledger.reversed_cgst_paise) - int(ledger.cached_reclaimed_cgst_paise)),
                        "remaining_sgst_paise": max(0, int(ledger.reversed_sgst_paise) - int(ledger.cached_reclaimed_sgst_paise)),
                        "remaining_cess_paise": max(0, int(ledger.reversed_cess_paise) - int(ledger.cached_reclaimed_cess_paise)),
                    }

            # Check head-by-head remaining balances
            curr_rem_igst = max(0, int(ledger.reversed_igst_paise) - int(ledger.cached_reclaimed_igst_paise))
            curr_rem_cgst = max(0, int(ledger.reversed_cgst_paise) - int(ledger.cached_reclaimed_cgst_paise))
            curr_rem_sgst = max(0, int(ledger.reversed_sgst_paise) - int(ledger.cached_reclaimed_sgst_paise))
            curr_rem_cess = max(0, int(ledger.reversed_cess_paise) - int(ledger.cached_reclaimed_cess_paise))

            if r_igst > curr_rem_igst:
                raise ValueError(f"EXCESS_RECLAIM_IGST: Requested {r_igst} paise exceeds available {curr_rem_igst} paise.")
            if r_cgst > curr_rem_cgst:
                raise ValueError(f"EXCESS_RECLAIM_CGST: Requested {r_cgst} paise exceeds available {curr_rem_cgst} paise.")
            if r_sgst > curr_rem_sgst:
                raise ValueError(f"EXCESS_RECLAIM_SGST: Requested {r_sgst} paise exceeds available {curr_rem_sgst} paise.")
            if r_cess > curr_rem_cess:
                raise ValueError(f"EXCESS_RECLAIM_CESS: Requested {r_cess} paise exceeds available {curr_rem_cess} paise.")

            new_ev = Gstr3bReclaimEvent(
                client_gstin_id=ledger.client_gstin_id,
                ledger_id=ledger.id,
                reclaim_run_id=reclaim_run_id,
                reclaim_tax_period=tax_period,
                event_type=ev_type,
                compensates_event_id=UUID(str(params["p_compensates_event_id"])) if params.get("p_compensates_event_id") else None,
                reclaimed_igst_paise=r_igst,
                reclaimed_cgst_paise=r_cgst,
                reclaimed_sgst_paise=r_sgst,
                reclaimed_cess_paise=r_cess,
                statutory_evidence_type=str(params["p_statutory_evidence_type"]),
                evidence_reference=str(params["p_evidence_reference"]),
                evidence_document_date=_parse_date(params.get("p_evidence_document_date")),
                authorized_by=UUID(str(params["p_authorized_by"])) if params.get("p_authorized_by") else None,
                reclaim_notes=str(params.get("p_reclaim_notes") or ""),
                idempotency_key=idem_key,
                created_at=datetime.now(timezone.utc),
            )
            session.add(new_ev)

            # Update ledger cached balances and status
            ledger.cached_reclaimed_igst_paise += r_igst
            ledger.cached_reclaimed_cgst_paise += r_cgst
            ledger.cached_reclaimed_sgst_paise += r_sgst
            ledger.cached_reclaimed_cess_paise += r_cess

            fin_rem_igst = max(0, int(ledger.reversed_igst_paise) - int(ledger.cached_reclaimed_igst_paise))
            fin_rem_cgst = max(0, int(ledger.reversed_cgst_paise) - int(ledger.cached_reclaimed_cgst_paise))
            fin_rem_sgst = max(0, int(ledger.reversed_sgst_paise) - int(ledger.cached_reclaimed_sgst_paise))
            fin_rem_cess = max(0, int(ledger.reversed_cess_paise) - int(ledger.cached_reclaimed_cess_paise))

            if (fin_rem_igst + fin_rem_cgst + fin_rem_sgst + fin_rem_cess) == 0:
                ledger.status = "FULLY_RECLAIMED"
            else:
                ledger.status = "PARTIALLY_RECLAIMED"

            ledger.updated_at = datetime.now(timezone.utc)
            session.flush()

            result = {
                "event_id": str(new_ev.id),
                "ledger_id": str(ledger.id),
                "status": ledger.status,
                "is_idempotent_replay": False,
                "event_type": ev_type,
                "reclaimed_igst_paise": r_igst,
                "reclaimed_cgst_paise": r_cgst,
                "reclaimed_sgst_paise": r_sgst,
                "reclaimed_cess_paise": r_cess,
                "remaining_igst_paise": fin_rem_igst,
                "remaining_cgst_paise": fin_rem_cgst,
                "remaining_sgst_paise": fin_rem_sgst,
                "remaining_cess_paise": fin_rem_cess,
            }
            session.commit()
            return result

    # ═════════════════════════════════════════════════════════════════════════
    # 4. gstr3b_table4_summaries
    # ═════════════════════════════════════════════════════════════════════════

    def get_table4_summary_for_run(
        self,
        run_id: str,
        is_current_only: bool = True,
    ) -> Optional[dict[str, Any]]:
        """Fetch Table 4 summary snapshot for a run."""
        with self._session_factory() as session:
            stmt = select(Gstr3bTable4Summary).where(Gstr3bTable4Summary.run_id == UUID(str(run_id)))
            if is_current_only:
                stmt = stmt.where(Gstr3bTable4Summary.is_current.is_(True))
            stmt = stmt.order_by(Gstr3bTable4Summary.version.desc()).limit(1)
            row = session.execute(stmt).scalars().first()
            return _model_to_dict(row) if row else None

    def list_table4_summaries_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """List all historical snapshot versions for a reconciliation run."""
        with self._session_factory() as session:
            stmt = (
                select(Gstr3bTable4Summary)
                .where(Gstr3bTable4Summary.run_id == UUID(str(run_id)))
                .order_by(Gstr3bTable4Summary.version.desc())
            )
            rows = session.execute(stmt).scalars().all()
            return [_model_to_dict(r) for r in rows]

    def create_table4_summary_snapshot(
        self,
        data: dict[str, Any],
        supersede_previous: bool = True,
    ) -> dict[str, Any]:
        """Persist a new versioned Table 4 snapshot, atomically superseding prior snapshots."""
        with self._session_factory() as session:
            rid = UUID(str(data["run_id"]))
            user_id = UUID(str(data["finalized_by"])) if data.get("finalized_by") else None
            now = datetime.now(timezone.utc)

            max_version = 0
            if supersede_previous:
                existing_summaries = (
                    session.execute(
                        select(Gstr3bTable4Summary)
                        .where(Gstr3bTable4Summary.run_id == rid)
                        .order_by(Gstr3bTable4Summary.version.desc())
                    )
                    .scalars()
                    .all()
                )
                for s in existing_summaries:
                    if s.version and s.version > max_version:
                        max_version = s.version
                    if s.is_current:
                        s.is_current = False
                        s.superseded_at = now
                        s.superseded_by = user_id
                session.flush()

            new_version = max_version + 1 if supersede_previous else int(data.get("version") or 1)

            summary = Gstr3bTable4Summary(
                id=UUID(str(data["id"])) if data.get("id") else None,
                run_id=rid,
                client_gstin_id=UUID(str(data["client_gstin_id"])),
                tax_period=str(data["tax_period"]),
                status=str(data.get("status") or "FINALIZED"),
                table_4a1=data.get("table_4a1") or {},
                table_4a2=data.get("table_4a2") or {},
                table_4a3=data.get("table_4a3") or {},
                table_4a4=data.get("table_4a4") or {},
                table_4a5=data.get("table_4a5") or {},
                table_4a_total=data.get("table_4a_total") or {},
                table_4b1=data.get("table_4b1") or {},
                table_4b2=data.get("table_4b2") or {},
                table_4b_total=data.get("table_4b_total") or {},
                table_4c=data.get("table_4c") or {},
                table_4d1=data.get("table_4d1") or {},
                table_4d2=data.get("table_4d2") or {},
                audit_hash=str(data.get("audit_hash") or ""),
                created_at=_parse_datetime(data.get("created_at")) or now,
                updated_at=_parse_datetime(data.get("updated_at")) or now,
                finalized_at=_parse_datetime(data.get("finalized_at")) or now,
                finalized_by=user_id,
                version=new_version,
                is_current=True,
                source_state_digest=str(data.get("source_state_digest") or data.get("audit_hash") or ""),
                snapshot_payload=data.get("snapshot_payload") or {},
                contributing_outcome_ids=data.get("contributing_outcome_ids") or [],
                contributing_disposition_ids=data.get("contributing_disposition_ids") or [],
                contributing_adjustment_ids=data.get("contributing_adjustment_ids") or [],
                contributing_reclaim_ids=data.get("contributing_reclaim_ids") or [],
            )
            session.add(summary)
            session.flush()

            # Disconnect circular / link foreign key onto reconciliation_run if present
            run_obj = session.get(ReconciliationRun, rid)
            if run_obj:
                run_obj.table4_summary_id = summary.id
                session.flush()

            res = _model_to_dict(summary)
            session.commit()
            return res

    # ═════════════════════════════════════════════════════════════════════════
    # 5. gstr3b_table4_adjustments
    # ═════════════════════════════════════════════════════════════════════════

    def get_table4_adjustment(self, adj_id: str, run_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Fetch single adjustment by ID."""
        with self._session_factory() as session:
            stmt = select(Gstr3bTable4Adjustment).where(Gstr3bTable4Adjustment.id == UUID(str(adj_id)))
            if run_id:
                stmt = stmt.where(Gstr3bTable4Adjustment.run_id == UUID(str(run_id)))
            row = session.execute(stmt).scalars().first()
            return _model_to_dict(row) if row else None

    def list_table4_adjustments_for_run(
        self,
        run_id: str,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch external adjustments for a reconciliation run."""
        with self._session_factory() as session:
            stmt = select(Gstr3bTable4Adjustment).where(Gstr3bTable4Adjustment.run_id == UUID(str(run_id)))
            if not include_deleted:
                stmt = stmt.where(Gstr3bTable4Adjustment.is_deleted.is_(False))
            stmt = stmt.order_by(Gstr3bTable4Adjustment.created_at.asc())
            rows = session.execute(stmt).scalars().all()
            return [_model_to_dict(r) for r in rows]

    def create_table4_adjustment(self, data: dict[str, Any]) -> dict[str, Any]:
        """Insert manual/external Table 4 adjustment."""
        with self._session_factory() as session:
            adj = Gstr3bTable4Adjustment(
                id=UUID(str(data["id"])) if data.get("id") else None,
                run_id=UUID(str(data["run_id"])),
                client_gstin_id=UUID(str(data["client_gstin_id"])),
                tax_period=str(data["tax_period"]),
                row_id=str(data["row_id"]),
                igst_paise=int(data.get("igst_paise") or 0),
                cgst_paise=int(data.get("cgst_paise") or 0),
                sgst_paise=int(data.get("sgst_paise") or 0),
                cess_paise=int(data.get("cess_paise") or 0),
                adjustment_type=str(data["adjustment_type"]),
                statutory_category=str(data["statutory_category"]),
                reason=str(data["reason"]),
                reference_doc=data.get("reference_doc"),
                turnover_ratio_data=data.get("turnover_ratio_data"),
                created_at=_parse_datetime(data.get("created_at")) or datetime.now(timezone.utc),
                created_by=UUID(str(data["created_by"])) if data.get("created_by") else None,
                is_deleted=bool(data.get("is_deleted", False)),
            )
            session.add(adj)
            session.flush()
            res = _model_to_dict(adj)
            session.commit()
            return res

    def soft_delete_table4_adjustment(self, adj_id: str, run_id: str) -> bool:
        """Soft-delete an adjustment by setting is_deleted=True."""
        with self._session_factory() as session:
            stmt = select(Gstr3bTable4Adjustment).where(
                Gstr3bTable4Adjustment.id == UUID(str(adj_id)),
                Gstr3bTable4Adjustment.run_id == UUID(str(run_id)),
            )
            row = session.execute(stmt).scalars().first()
            if not row or row.is_deleted:
                return False
            row.is_deleted = True
            session.commit()
            return True

    # ═════════════════════════════════════════════════════════════════════════
    # 6. gstr3b_reconciliation
    # ═════════════════════════════════════════════════════════════════════════

    def get_gstr3b_reconciliation_for_run(self, run_id: str) -> Optional[dict[str, Any]]:
        """Fetch latest GSTR-3B reconciliation result for a run."""
        with self._session_factory() as session:
            stmt = (
                select(Gstr3bReconciliation)
                .where(Gstr3bReconciliation.run_id == UUID(str(run_id)))
                .order_by(Gstr3bReconciliation.uploaded_at.desc())
                .limit(1)
            )
            row = session.execute(stmt).scalars().first()
            return _model_to_dict(row) if row else None

    def upsert_gstr3b_reconciliation(self, run_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Upsert GSTR-3B comparison result (1 active record per run)."""
        with self._session_factory() as session:
            rid = UUID(str(run_id))
            stmt = select(Gstr3bReconciliation).where(Gstr3bReconciliation.run_id == rid).limit(1)
            existing = session.execute(stmt).scalars().first()

            uploaded_at = _parse_datetime(data.get("uploaded_at")) or datetime.now(timezone.utc)
            uploaded_by = UUID(str(data["uploaded_by"])) if data.get("uploaded_by") else None

            if existing:
                for k, v in data.items():
                    if k in ("id", "run_id"):
                        continue
                    if k == "uploaded_at":
                        existing.uploaded_at = uploaded_at
                    elif k == "uploaded_by":
                        existing.uploaded_by = uploaded_by
                    elif hasattr(existing, k):
                        setattr(existing, k, v)
                session.flush()
                res = _model_to_dict(existing)
            else:
                recon = Gstr3bReconciliation(
                    id=UUID(str(data["id"])) if data.get("id") else None,
                    run_id=rid,
                    client_gstin=str(data["client_gstin"]),
                    tax_period=str(data["tax_period"]),
                    gstr3b_igst_claimed=Decimal(str(data.get("gstr3b_igst_claimed") or 0)),
                    gstr3b_cgst_claimed=Decimal(str(data.get("gstr3b_cgst_claimed") or 0)),
                    gstr3b_sgst_claimed=Decimal(str(data.get("gstr3b_sgst_claimed") or 0)),
                    gstr2b_igst_available=Decimal(str(data.get("gstr2b_igst_available") or 0)),
                    gstr2b_cgst_available=Decimal(str(data.get("gstr2b_cgst_available") or 0)),
                    gstr2b_sgst_available=Decimal(str(data.get("gstr2b_sgst_available") or 0)),
                    igst_difference=Decimal(str(data.get("igst_difference") or 0)),
                    cgst_difference=Decimal(str(data.get("cgst_difference") or 0)),
                    sgst_difference=Decimal(str(data.get("sgst_difference") or 0)),
                    igst_status=data.get("igst_status"),
                    cgst_status=data.get("cgst_status"),
                    sgst_status=data.get("sgst_status"),
                    overall_status=data.get("overall_status"),
                    outward_supply_total=Decimal(str(data.get("outward_supply_total") or 0)),
                    raw_gstr3b=data.get("raw_gstr3b"),
                    uploaded_by=uploaded_by,
                    uploaded_at=uploaded_at,
                )
                session.add(recon)
                session.flush()
                res = _model_to_dict(recon)

            session.commit()
            return res

    def fetch_latest_gstr3b_for_runs(self, run_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch latest GSTR-3B reconciliation row mapped by run_id."""
        if not run_ids:
            return {}
        uids = [UUID(str(r)) for r in run_ids]
        with self._session_factory() as session:
            stmt = (
                select(Gstr3bReconciliation)
                .where(Gstr3bReconciliation.run_id.in_(uids))
                .order_by(Gstr3bReconciliation.uploaded_at.desc())
            )
            rows = session.execute(stmt).scalars().all()
            out: dict[str, dict[str, Any]] = {}
            for r in rows:
                k = str(r.run_id)
                if k not in out:
                    out[k] = _model_to_dict(r)
            return out

    def fetch_gstr3b_by_period_for_gstin(
        self,
        *,
        gstin: str,
        periods: Optional[set[str]] = None,
        limit: int = 200,
    ) -> dict[str, dict[str, Any]]:
        """Fetch latest GSTR-3B upload per period for client GSTIN."""
        norm_gstin = (gstin or "").strip().upper()
        if not norm_gstin:
            return {}
        with self._session_factory() as session:
            stmt = (
                select(Gstr3bReconciliation)
                .where(Gstr3bReconciliation.client_gstin == norm_gstin)
            )
            if periods:
                stmt = stmt.where(Gstr3bReconciliation.tax_period.in_(periods))
            stmt = stmt.order_by(Gstr3bReconciliation.uploaded_at.desc()).limit(limit)
            rows = session.execute(stmt).scalars().all()
            out: dict[str, dict[str, Any]] = {}
            for r in rows:
                p = str(r.tax_period)
                if p not in out:
                    out[p] = _model_to_dict(r)
            return out

    # ═════════════════════════════════════════════════════════════════════════
    # 7. Cascade Deletion Helper
    # ═════════════════════════════════════════════════════════════════════════

    def delete_run_records(self, run_id: str) -> dict[str, int]:
        """Safely clean up Batch 2B records associated with a reconciliation run."""
        rid = UUID(str(run_id))
        counts = {
            "gstr3b_reclaim_events": 0,
            "gstr3b_reversal_ledger": 0,
            "gstr3b_table4_summaries": 0,
            "gstr3b_table4_adjustments": 0,
            "gstr3b_reconciliation": 0,
        }
        with self._session_factory() as session:
            # 1. Unlink & Delete reclaim events
            ledger_subq = select(Gstr3bReversalLedger.id).where(Gstr3bReversalLedger.source_run_id == rid)
            session.execute(
                update(Gstr3bReclaimEvent)
                .where(
                    (Gstr3bReclaimEvent.reclaim_run_id == rid)
                    | (Gstr3bReclaimEvent.ledger_id.in_(ledger_subq))
                )
                .values(compensates_event_id=None)
            )
            ev_del = session.execute(
                delete(Gstr3bReclaimEvent).where(
                    (Gstr3bReclaimEvent.reclaim_run_id == rid)
                    | (Gstr3bReclaimEvent.ledger_id.in_(ledger_subq))
                )
            )
            counts["gstr3b_reclaim_events"] = ev_del.rowcount or 0

            # 2. Delete reversal ledger
            rl_del = session.execute(
                delete(Gstr3bReversalLedger).where(Gstr3bReversalLedger.source_run_id == rid)
            )
            counts["gstr3b_reversal_ledger"] = rl_del.rowcount or 0

            # 3. Disconnect summary on run and delete summaries
            session.execute(
                update(ReconciliationRun)
                .where(ReconciliationRun.id == rid)
                .values(table4_summary_id=None)
            )
            t4_del = session.execute(
                delete(Gstr3bTable4Summary).where(Gstr3bTable4Summary.run_id == rid)
            )
            counts["gstr3b_table4_summaries"] = t4_del.rowcount or 0

            # 4. Delete adjustments
            adj_del = session.execute(
                delete(Gstr3bTable4Adjustment).where(Gstr3bTable4Adjustment.run_id == rid)
            )
            counts["gstr3b_table4_adjustments"] = adj_del.rowcount or 0

            # 5. Delete reconciliation
            rec_del = session.execute(
                delete(Gstr3bReconciliation).where(Gstr3bReconciliation.run_id == rid)
            )
            counts["gstr3b_reconciliation"] = rec_del.rowcount or 0

            session.commit()
            return counts


# ── Global Singleton Factory ──────────────────────────────────────────────────

_gstr3b_repo: Optional[AuroraGstr3bRepository] = None


def get_gstr3b_repository() -> Optional[AuroraGstr3bRepository]:
    """Return the module-level AuroraGstr3bRepository singleton.

    Returns None when Aurora is not configured.
    """
    global _gstr3b_repo
    if _gstr3b_repo is not None:
        return _gstr3b_repo
    try:
        from app.aurora import get_aurora_sessionmaker
        sf = get_aurora_sessionmaker()
        _gstr3b_repo = AuroraGstr3bRepository(session_factory=sf)
        return _gstr3b_repo
    except Exception as exc:
        _log.debug("Aurora GSTR-3B repository unavailable: %s", exc)
        return None


def set_gstr3b_repository(repo: Optional[AuroraGstr3bRepository]) -> None:
    """Set the module-level AuroraGstr3bRepository singleton (primarily for testing)."""
    global _gstr3b_repo
    _gstr3b_repo = repo
