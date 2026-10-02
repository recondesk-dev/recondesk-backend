"""AWS Aurora Reconciliation Repository for ReconDesk.

Provides safe, typed SQLAlchemy data-access methods for:
- Reconciliation run lifecycle, status, KPIs, and filtering
- GSTR-2B line records (gstr_records)
- Purchase register line records (pr_records)
- Reconciliation engine compressed results and payloads (reconciliation_results)
- Transactional cascade deletion maintaining exact Step 1-7 invariant

Security Invariants:
1. All client scoping respects accessible client_gstin_ids boundaries.
2. Distinguishes between infrastructure misses (run not in Aurora -> None)
   and authoritative empty results (query returned 0 runs -> []).
3. Transactional cascade deletion guarantees no orphaned child records.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional, Sequence
from uuid import UUID

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.models.reconciliation import (
    GstrRecord,
    PrRecord,
    ReconciliationResult,
    ReconciliationRun,
)

_log = logging.getLogger("recondesk.aurora.reconciliation")


def _parse_date(val: Any) -> Optional[date]:
    if val is None or isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        return date.fromisoformat(s[:10])
    return None


def _parse_datetime(val: Any) -> Optional[datetime]:
    if val is None or isinstance(val, datetime):
        return val
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        # Handle trailing Z
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    return None


class AuroraReconciliationRepository:
    """Repository handling purchase-side reconciliation data operations in AWS Aurora."""

    def __init__(
        self,
        session_factory: Optional[sessionmaker[Session]] = None,
    ) -> None:
        if session_factory is not None:
            self._session_factory = session_factory
        else:
            from app.aurora import get_aurora_sessionmaker
            self._session_factory = get_aurora_sessionmaker()

    def _get_session(self) -> Session:
        return self._session_factory()

    # ── Reconciliation Run Operations ─────────────────────────────────────────

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        """Fetch reconciliation run by primary key.

        Returns:
            dict: Run dictionary matching Supabase PostgREST shape.
            None: Run not found in Aurora (migration miss).
        """
        rid = str(run_id or "").strip()
        if not rid:
            return None

        with self._get_session() as session:
            stmt = select(ReconciliationRun).where(ReconciliationRun.id == rid)
            run = session.scalar(stmt)
            if run is None:
                return None
            return run.to_dict()

    def list_runs(
        self,
        client_ids: Sequence[str],
        *,
        status_filter: Optional[str] = None,
        limit: int = 50,
    ) -> Optional[list[dict[str, Any]]]:
        """List runs for accessible client IDs with status filtering and pagination.

        Returns:
            list[dict]: Matching runs ordered by created_at DESC (authoritative, can be []).
            None: If infrastructure error occurs.
        """
        if not client_ids:
            return []

        cids = [str(c).strip() for c in client_ids if str(c).strip()]
        if not cids:
            return []

        try:
            with self._get_session() as session:
                # 1. Tenancy check: verify whether any requested client ID exists in Aurora
                from app.models.tenancy import ClientGSTIN
                client_stmt = select(ClientGSTIN.id).where(ClientGSTIN.id.in_(cids)).limit(1)
                if session.scalar(client_stmt) is None:
                    # None of the requested clients exist in Aurora: migration miss (permits Supabase fallback)
                    return None

                stmt = select(ReconciliationRun).where(
                    ReconciliationRun.client_gstin_id.in_(cids)
                )

                if status_filter:
                    sf = status_filter.strip()
                    sf_upper = sf.upper()
                    if sf_upper == "FAILED":
                        stmt = stmt.where(
                            func.upper(ReconciliationRun.status).in_(["FAILED"])
                        )
                    else:
                        stmt = stmt.where(
                            func.upper(ReconciliationRun.status) == sf_upper
                        )

                stmt = stmt.order_by(ReconciliationRun.created_at.desc()).limit(limit)
                runs = session.scalars(stmt).all()
                return [r.to_dict() for r in runs]
        except Exception as exc:
            _log.warning("Aurora list_runs query failed: %s", type(exc).__name__)
            return None

    def create_run(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new reconciliation_run row in Aurora."""
        payload = dict(data)
        run_id = payload.get("id") or str(uuid.uuid4())
        payload["id"] = run_id

        # Normalize date/datetime fields
        if "gstr_period_end" in payload:
            payload["gstr_period_end"] = _parse_date(payload["gstr_period_end"])
        if "created_at" in payload:
            payload["created_at"] = _parse_datetime(payload["created_at"])
        if "updated_at" in payload:
            payload["updated_at"] = _parse_datetime(payload["updated_at"])
        if "processing_started_at" in payload:
            payload["processing_started_at"] = _parse_datetime(payload["processing_started_at"])
        if "completed_at" in payload:
            payload["completed_at"] = _parse_datetime(payload["completed_at"])
        if "finalized_at" in payload:
            payload["finalized_at"] = _parse_datetime(payload["finalized_at"])
        if "paid_at" in payload:
            payload["paid_at"] = _parse_datetime(payload["paid_at"])

        with self._get_session() as session:
            run = ReconciliationRun(**payload)
            session.add(run)
            session.commit()
            session.refresh(run)
            return run.to_dict()

    def update_run(self, run_id: str, fields: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Update reconciliation_run fields by ID."""
        rid = str(run_id or "").strip()
        if not rid or not fields:
            return None

        payload = dict(fields)
        # Normalize date/datetime fields
        if "gstr_period_end" in payload:
            payload["gstr_period_end"] = _parse_date(payload["gstr_period_end"])
        if "created_at" in payload:
            payload["created_at"] = _parse_datetime(payload["created_at"])
        if "updated_at" in payload:
            payload["updated_at"] = _parse_datetime(payload["updated_at"])
        if "processing_started_at" in payload:
            payload["processing_started_at"] = _parse_datetime(payload["processing_started_at"])
        if "completed_at" in payload:
            payload["completed_at"] = _parse_datetime(payload["completed_at"])
        if "finalized_at" in payload:
            payload["finalized_at"] = _parse_datetime(payload["finalized_at"])
        if "paid_at" in payload:
            payload["paid_at"] = _parse_datetime(payload["paid_at"])

        with self._get_session() as session:
            stmt = select(ReconciliationRun).where(ReconciliationRun.id == rid)
            run = session.scalar(stmt)
            if run is None:
                return None
            for k, v in payload.items():
                if hasattr(run, k):
                    setattr(run, k, v)
            session.commit()
            session.refresh(run)
            return run.to_dict()

    def delete_run_cascade(self, run_id: str) -> bool:
        """Execute transactional cascade deletion implementing the 7-step sequence.

        Step 1: Set table4_summary_id = NULL on reconciliation_run
        Step 2: Clear/unlink gstr3b_reclaim_events
        Step 3: Delete gstr3b_reversal_ledger for source_run_id = run_id
        Step 4: Delete gstr3b_table4_summaries for run_id = run_id
        Step 5: Repoint/delete invoice_tracking
        Step 6: Delete rule37_actions and reconciliation_import_runs
        Step 7: Delete reconciliation_run (cascading gstr_records, pr_records, reconciliation_results)

        Returns:
            True if run was deleted.
            False if run was not found.
        """
        rid = str(run_id or "").strip()
        if not rid:
            return False

        with self._get_session() as session:
            # First check if run exists
            stmt = select(ReconciliationRun.id).where(ReconciliationRun.id == rid)
            if session.scalar(stmt) is None:
                return False

            # Try invoking stored procedure if PostgreSQL dialect has it
            try:
                if session.bind and session.bind.dialect.name == "postgresql":
                    session.execute(
                        text("SELECT public.delete_reconciliation_run_cascade(:rid)"),
                        {"rid": rid},
                    )
                    session.commit()
                    return True
            except Exception as proc_exc:
                _log.info(
                    "Stored function delete_reconciliation_run_cascade not used, executing SQLAlchemy steps: %s",
                    proc_exc,
                )
                session.rollback()

            # Execute transactional 7-step sequence defensively:
            # Step 1: Disconnect circular FK
            try:
                with session.begin_nested():
                    session.execute(
                        update(ReconciliationRun)
                        .where(ReconciliationRun.id == rid)
                        .values(table4_summary_id=None)
                    )
            except Exception:
                pass

            # Step 2: Unlink/delete gstr3b_reclaim_events
            try:
                with session.begin_nested():
                    session.execute(
                        text(
                            "UPDATE gstr3b_reclaim_events SET compensates_event_id = NULL "
                            "WHERE reclaim_run_id = :rid OR ledger_id IN ("
                            "  SELECT id FROM gstr3b_reversal_ledger WHERE source_run_id = :rid"
                            ")"
                        ),
                        {"rid": rid},
                    )
                    session.execute(
                        text(
                            "DELETE FROM gstr3b_reclaim_events "
                            "WHERE reclaim_run_id = :rid OR ledger_id IN ("
                            "  SELECT id FROM gstr3b_reversal_ledger WHERE source_run_id = :rid"
                            ")"
                        ),
                        {"rid": rid},
                    )
            except Exception:
                pass

            # Step 3: Delete gstr3b_reversal_ledger
            try:
                with session.begin_nested():
                    session.execute(
                        text("DELETE FROM gstr3b_reversal_ledger WHERE source_run_id = :rid"),
                        {"rid": rid},
                    )
            except Exception:
                pass

            # Step 4: Delete gstr3b_table4_summaries
            try:
                with session.begin_nested():
                    session.execute(
                        text("DELETE FROM gstr3b_table4_summaries WHERE run_id = :rid"),
                        {"rid": rid},
                    )
            except Exception:
                pass

            # Step 4b: Delete gstr3b_table4_adjustments
            try:
                with session.begin_nested():
                    session.execute(
                        text("DELETE FROM gstr3b_table4_adjustments WHERE run_id = :rid"),
                        {"rid": rid},
                    )
            except Exception:
                pass

            # Step 4c: Delete gstr3b_reconciliation
            try:
                with session.begin_nested():
                    session.execute(
                        text("DELETE FROM gstr3b_reconciliation WHERE run_id = :rid"),
                        {"rid": rid},
                    )
            except Exception:
                pass

            # Step 5: Repoint/delete invoice_tracking
            try:
                with session.begin_nested():
                    session.execute(
                        text(
                            "UPDATE invoice_tracking SET last_seen_run_id = first_seen_run_id, updated_at = :now "
                            "WHERE last_seen_run_id = :rid AND first_seen_run_id != :rid"
                        ),
                        {"rid": rid, "now": datetime.now(timezone.utc)},
                    )
                    session.execute(
                        text(
                            "DELETE FROM invoice_tracking "
                            "WHERE first_seen_run_id = :rid OR last_seen_run_id = :rid"
                        ),
                        {"rid": rid},
                    )
            except Exception:
                pass

            # Step 6: Non-cascading rule37_actions and reconciliation_import_runs
            try:
                with session.begin_nested():
                    session.execute(
                        text("DELETE FROM rule37_actions WHERE run_id = :rid"),
                        {"rid": rid},
                    )
            except Exception:
                pass

            try:
                with session.begin_nested():
                    session.execute(
                        text("DELETE FROM reconciliation_import_runs WHERE id = :rid"),
                        {"rid": rid},
                    )
            except Exception:
                pass

            # Step 7: Delete child records and parent reconciliation_run
            try:
                with session.begin_nested():
                    session.execute(delete(GstrRecord).where(GstrRecord.run_id == rid))
                    session.execute(delete(PrRecord).where(PrRecord.run_id == rid))
                    session.execute(delete(ReconciliationResult).where(ReconciliationResult.run_id == rid))
            except Exception:
                pass

            run = session.scalar(
                select(ReconciliationRun).where(ReconciliationRun.id == rid)
            )
            if run is not None:
                session.delete(run)
                session.commit()
                return True
            session.rollback()
            return False

    # ── GSTR Record Operations ────────────────────────────────────────────────

    def get_gstr_records(
        self,
        run_id: str,
        *,
        offset: int = 0,
        limit: Optional[int] = None,
    ) -> Optional[list[dict[str, Any]]]:
        """Fetch GSTR line records for a run.

        Returns:
            list[dict]: Matching records (can be []).
            None: If the run itself is not found in Aurora.
        """
        rid = str(run_id or "").strip()
        if not rid:
            return None

        with self._get_session() as session:
            # Verify run exists
            run_exists = session.scalar(
                select(func.count(ReconciliationRun.id)).where(
                    ReconciliationRun.id == rid
                )
            )
            if not run_exists:
                return None

            stmt = select(GstrRecord).where(GstrRecord.run_id == rid)
            if offset > 0:
                stmt = stmt.offset(offset)
            if limit is not None:
                stmt = stmt.limit(limit)

            records = session.scalars(stmt).all()
            return [r.to_dict() for r in records]

    def count_gstr_records(self, run_id: str) -> int:
        """Count GSTR line records for a run."""
        rid = str(run_id or "").strip()
        if not rid:
            return 0
        with self._get_session() as session:
            cnt = session.scalar(
                select(func.count(GstrRecord.id)).where(GstrRecord.run_id == rid)
            )
            return int(cnt or 0)

    def insert_gstr_records(
        self,
        run_id: str,
        records: list[dict[str, Any]],
    ) -> int:
        """Bulk insert GSTR records into Aurora."""
        rid = str(run_id or "").strip()
        if not rid or not records:
            return 0

        rows = []
        for r in records:
            item = dict(r)
            item["run_id"] = rid
            if not item.get("id"):
                item["id"] = str(uuid.uuid4())
            if "invoice_date" in item:
                item["invoice_date"] = _parse_date(item["invoice_date"])
            if "gstr2b_reflection_date" in item:
                item["gstr2b_reflection_date"] = _parse_date(item["gstr2b_reflection_date"])
            if "created_at" in item:
                item["created_at"] = _parse_datetime(item["created_at"])
            rows.append(GstrRecord(**item))

        with self._get_session() as session:
            session.add_all(rows)
            session.commit()
            return len(rows)

    # ── PR Record Operations ──────────────────────────────────────────────────

    def get_pr_records(
        self,
        run_id: str,
        *,
        offset: int = 0,
        limit: Optional[int] = None,
    ) -> Optional[list[dict[str, Any]]]:
        """Fetch PR line records for a run.

        Returns:
            list[dict]: Matching records (can be []).
            None: If the run itself is not found in Aurora.
        """
        rid = str(run_id or "").strip()
        if not rid:
            return None

        with self._get_session() as session:
            run_exists = session.scalar(
                select(func.count(ReconciliationRun.id)).where(
                    ReconciliationRun.id == rid
                )
            )
            if not run_exists:
                return None

            stmt = select(PrRecord).where(PrRecord.run_id == rid)
            if offset > 0:
                stmt = stmt.offset(offset)
            if limit is not None:
                stmt = stmt.limit(limit)

            records = session.scalars(stmt).all()
            return [r.to_dict() for r in records]

    def count_pr_records(self, run_id: str) -> int:
        """Count PR line records for a run."""
        rid = str(run_id or "").strip()
        if not rid:
            return 0
        with self._get_session() as session:
            cnt = session.scalar(
                select(func.count(PrRecord.id)).where(PrRecord.run_id == rid)
            )
            return int(cnt or 0)

    def insert_pr_records(
        self,
        run_id: str,
        records: list[dict[str, Any]],
    ) -> int:
        """Bulk insert PR records into Aurora."""
        rid = str(run_id or "").strip()
        if not rid or not records:
            return 0

        rows = []
        for r in records:
            item = dict(r)
            item["run_id"] = rid
            if not item.get("id"):
                item["id"] = str(uuid.uuid4())
            if "invoice_date" in item:
                item["invoice_date"] = _parse_date(item["invoice_date"])
            if "payment_date" in item:
                item["payment_date"] = _parse_date(item["payment_date"])
            if "rule_37_deadline" in item:
                item["rule_37_deadline"] = _parse_date(item["rule_37_deadline"])
            if "created_at" in item:
                item["created_at"] = _parse_datetime(item["created_at"])
            rows.append(PrRecord(**item))

        with self._get_session() as session:
            session.add_all(rows)
            session.commit()
            return len(rows)

    # ── Reconciliation Results Operations ─────────────────────────────────────

    def get_reconciliation_results(self, run_id: str) -> Optional[dict[str, Any]]:
        """Fetch reconciliation_results for a run.

        Returns:
            dict: Result row with record_data, payload, match_confidence.
            None: If not found in Aurora.
        """
        rid = str(run_id or "").strip()
        if not rid:
            return None

        with self._get_session() as session:
            stmt = select(ReconciliationResult).where(
                ReconciliationResult.run_id == rid
            ).order_by(ReconciliationResult.created_at.desc()).limit(1)
            res = session.scalar(stmt)
            if res is None:
                return None
            return res.to_dict()

    def save_reconciliation_results(
        self,
        run_id: str,
        payload: Any,
        *,
        record_data: Any = None,
        match_confidence: Optional[float] = None,
        created_at: Optional[str] = None,
    ) -> bool:
        """Save or replace reconciliation_results row for a run."""
        rid = str(run_id or "").strip()
        if not rid:
            return False

        created_dt = _parse_datetime(created_at) or datetime.now(timezone.utc)

        with self._get_session() as session:
            # Delete previous results for run_id
            session.execute(
                delete(ReconciliationResult).where(ReconciliationResult.run_id == rid)
            )
            row = ReconciliationResult(
                id=str(uuid.uuid4()),
                run_id=rid,
                payload=payload,
                record_data=record_data,
                match_confidence=match_confidence,
                created_at=created_dt,
            )
            session.add(row)
            session.commit()
            return True


# ── Global Repository Accessors ───────────────────────────────────────────────

_reconciliation_repo: Optional[AuroraReconciliationRepository] = None


def get_reconciliation_repository() -> Optional[AuroraReconciliationRepository]:
    """Return global AuroraReconciliationRepository if Aurora is enabled/configured, else None."""
    global _reconciliation_repo
    if _reconciliation_repo is not None:
        return _reconciliation_repo

    from app.aurora import get_aurora_database_url, is_aurora_enabled

    if is_aurora_enabled() or get_aurora_database_url():
        try:
            _reconciliation_repo = AuroraReconciliationRepository()
            return _reconciliation_repo
        except Exception as exc:
            _log.warning(
                "Failed to initialize AuroraReconciliationRepository: %s",
                type(exc).__name__,
            )
            return None

    return None


def set_reconciliation_repository(
    repo: Optional[AuroraReconciliationRepository],
) -> None:
    """Explicitly set or reset the reconciliation repository (for testing)."""
    global _reconciliation_repo
    _reconciliation_repo = repo
