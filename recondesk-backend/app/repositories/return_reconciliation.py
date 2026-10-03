"""AWS Aurora Return Reconciliation & Audit Overrides Repository for ReconDesk — Batch 3A.

Provides typed, safe SQLAlchemy 2.x data-access for:
1. multi_period_recon_batches (Multi-period reconciliation orchestration batch header)
2. multi_period_recon_batch_items (Individual reconciliation period item within a batch)
3. gstr1_reconciliation_run (GSTR-1 vs Sales Register reconciliation runs and JSONB payloads)
4. gstr1a_period_actions (CA accept/reject filed actions on GSTR-1A amendments per period)
5. gstr2a_delta_results (GSTR-2A vs GSTR-2B snapshot delta results and category payloads)
6. gstr9_audit_overrides (CA manual overrides for GSTR-9 annual return cells with exact NUMERIC precision)

Architecture & Invariants:
- Aurora is PRIMARY for all 6 tables.
- Writes ALWAYS go to Aurora first.
- Strict tenant boundary isolation: all queries scoped by client_gstin_id or parent FK.
- Safe type conversion and normalization for UUIDs, Decimals, ISO datetimes, and JSONB.
- Dialect compatibility: supports PostgreSQL in production and SQLite in testing.
- Controlled non-blocking fallback to Supabase only if Aurora raises an operational error.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import delete, desc as sa_desc, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.aurora import (
    AuroraConfigurationError,
    get_aurora_engine,
    get_aurora_session,
    get_aurora_sessionmaker,
)
from app.models.return_reconciliation import (
    MultiPeriodReconBatch,
    MultiPeriodReconBatchItem,
    Gstr1ReconciliationRun,
    Gstr1aPeriodAction,
    Gstr2aDeltaResult,
    Gstr9AuditOverride,
)

_log = logging.getLogger("recondesk.aurora.return_reconciliation")


# ── Helpers & Type Converters ──────────────────────────────────────────────────

def _is_sqlite(session: Session) -> bool:
    """Return True if session is bound to a SQLite dialect."""
    return "sqlite" in str(session.bind.dialect.name) if session.bind else False


def _parse_uuid(val: Any) -> Optional[UUID]:
    if val is None:
        return None
    if isinstance(val, UUID):
        return val
    try:
        return UUID(str(val).strip())
    except (ValueError, AttributeError):
        return None


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


def _parse_numeric(val: Any) -> Optional[Decimal]:
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


def _model_to_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


_fallback_sessionmaker: Optional[sessionmaker[Session]] = None


def _get_fallback_sessionmaker() -> sessionmaker[Session]:
    global _fallback_sessionmaker
    if _fallback_sessionmaker is None:
        from app.scripts.backfill_batch3a_return_reconciliation import (
            Batch3AReturnReconciliationOrchestrator,
        )
        orch = Batch3AReturnReconciliationOrchestrator()
        engine = orch._get_engine()
        _fallback_sessionmaker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return _fallback_sessionmaker


# ── Aurora Return Reconciliation Repository ───────────────────────────────────

class AuroraReturnReconciliationRepository:
    """Typed data-access repository for Batch 3A tables against AWS Aurora PostgreSQL."""

    def __init__(self, session_factory: Optional[sessionmaker[Session]] = None) -> None:
        self._session_factory = session_factory

    def _get_session(self) -> Session:
        if self._session_factory:
            return self._session_factory()
        try:
            return get_aurora_session()
        except AuroraConfigurationError:
            return _get_fallback_sessionmaker()()

    # ── 1. Multi-Period Recon Batches ──────────────────────────────────────────

    def create_batch(
        self,
        *,
        client_gstin_id: str | UUID,
        financial_year: str,
        status: str = "pending",
        created_by: Optional[str | UUID] = None,
        batch_id: Optional[str | UUID] = None,
    ) -> dict[str, Any]:
        """Create a new multi-period reconciliation batch."""
        cid = _parse_uuid(client_gstin_id)
        uid = _parse_uuid(created_by)
        bid = _parse_uuid(batch_id)

        session = self._get_session()
        try:
            batch = MultiPeriodReconBatch(
                id=bid or sa.text("gen_random_uuid()") if not _is_sqlite(session) else (bid or None),
                client_gstin_id=cid,
                financial_year=financial_year,
                status=status,
                created_by=uid,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(batch)
            session.commit()
            session.refresh(batch)
            return batch.to_dict()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_batch(self, batch_id: str | UUID) -> Optional[dict[str, Any]]:
        """Get a batch by ID."""
        bid = _parse_uuid(batch_id)
        session = self._get_session()
        try:
            stmt = select(MultiPeriodReconBatch).where(MultiPeriodReconBatch.id == bid)
            batch = session.execute(stmt).scalar_one_or_none()
            return batch.to_dict() if batch else None
        finally:
            session.close()

    def list_batches(
        self,
        client_gstin_id: str | UUID,
        limit: int = 50,
    ) -> List[dict[str, Any]]:
        """List batches for a client GSTIN ordered by created_at DESC."""
        cid = _parse_uuid(client_gstin_id)
        session = self._get_session()
        try:
            stmt = (
                select(MultiPeriodReconBatch)
                .where(MultiPeriodReconBatch.client_gstin_id == cid)
                .order_by(sa_desc(MultiPeriodReconBatch.created_at))
                .limit(limit)
            )
            batches = session.execute(stmt).scalars().all()
            return [b.to_dict() for b in batches]
        finally:
            session.close()

    def update_batch(
        self,
        batch_id: str | UUID,
        updates: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Update a batch's fields."""
        bid = _parse_uuid(batch_id)
        session = self._get_session()
        try:
            stmt = select(MultiPeriodReconBatch).where(MultiPeriodReconBatch.id == bid)
            batch = session.execute(stmt).scalar_one_or_none()
            if not batch:
                return None

            for k, v in updates.items():
                if hasattr(batch, k):
                    if k in ("created_at", "updated_at"):
                        v = _parse_datetime(v) or v
                    elif k in ("client_gstin_id", "created_by"):
                        v = _parse_uuid(v)
                    setattr(batch, k, v)
            batch.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(batch)
            return batch.to_dict()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def delete_batch(self, batch_id: str | UUID) -> bool:
        """Delete a batch (cascades to items)."""
        bid = _parse_uuid(batch_id)
        session = self._get_session()
        try:
            stmt = select(MultiPeriodReconBatch).where(MultiPeriodReconBatch.id == bid)
            batch = session.execute(stmt).scalar_one_or_none()
            if not batch:
                return False
            session.delete(batch)
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ── 2. Multi-Period Recon Batch Items ──────────────────────────────────────

    def create_batch_items(
        self,
        batch_id: str | UUID,
        items: List[dict[str, Any]],
    ) -> List[dict[str, Any]]:
        """Create multiple items under a batch."""
        bid = _parse_uuid(batch_id)
        session = self._get_session()
        created = []
        try:
            now = datetime.now(timezone.utc)
            for itm in items:
                item_obj = MultiPeriodReconBatchItem(
                    id=_parse_uuid(itm.get("id")) or None,
                    batch_id=bid,
                    period=str(itm["period"]).strip(),
                    status=str(itm.get("status", "pending")),
                    reconciliation_run_id=_parse_uuid(itm.get("reconciliation_run_id")),
                    gstr2b_file_path=itm.get("gstr2b_file_path"),
                    gstr2b_source=itm.get("gstr2b_source"),
                    pr_file_path=itm.get("pr_file_path"),
                    pr_source=itm.get("pr_source"),
                    error_message=itm.get("error_message"),
                    created_at=_parse_datetime(itm.get("created_at")) or now,
                    updated_at=_parse_datetime(itm.get("updated_at")) or now,
                )
                session.add(item_obj)
                created.append(item_obj)
            session.commit()
            return [it.to_dict() for it in created]
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_batch_items(self, batch_id: str | UUID) -> List[dict[str, Any]]:
        """List all items for a batch, ordered by period ASC."""
        bid = _parse_uuid(batch_id)
        session = self._get_session()
        try:
            stmt = (
                select(MultiPeriodReconBatchItem)
                .where(MultiPeriodReconBatchItem.batch_id == bid)
                .order_by(MultiPeriodReconBatchItem.period)
            )
            items = session.execute(stmt).scalars().all()
            return [it.to_dict() for it in items]
        finally:
            session.close()

    def get_batch_item(self, item_id: str | UUID) -> Optional[dict[str, Any]]:
        """Get a single batch item by ID."""
        iid = _parse_uuid(item_id)
        session = self._get_session()
        try:
            stmt = select(MultiPeriodReconBatchItem).where(MultiPeriodReconBatchItem.id == iid)
            item = session.execute(stmt).scalar_one_or_none()
            return item.to_dict() if item else None
        finally:
            session.close()

    def update_batch_item(
        self,
        item_id: str | UUID,
        updates: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Update an item's fields (status, run_id, file paths, etc.)."""
        iid = _parse_uuid(item_id)
        session = self._get_session()
        try:
            stmt = select(MultiPeriodReconBatchItem).where(MultiPeriodReconBatchItem.id == iid)
            item = session.execute(stmt).scalar_one_or_none()
            if not item:
                return None

            for k, v in updates.items():
                if hasattr(item, k):
                    if k in ("created_at", "updated_at"):
                        v = _parse_datetime(v) or v
                    elif k in ("batch_id", "reconciliation_run_id"):
                        v = _parse_uuid(v)
                    setattr(item, k, v)
            item.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(item)
            return item.to_dict()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def update_batch_item_by_period(
        self,
        batch_id: str | UUID,
        period: str,
        updates: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Update a batch item identified by batch_id and period."""
        bid = _parse_uuid(batch_id)
        p = str(period).strip()
        session = self._get_session()
        try:
            stmt = select(MultiPeriodReconBatchItem).where(
                MultiPeriodReconBatchItem.batch_id == bid,
                MultiPeriodReconBatchItem.period == p,
            )
            item = session.execute(stmt).scalar_one_or_none()
            if not item:
                return None

            for k, v in updates.items():
                if hasattr(item, k):
                    if k in ("created_at", "updated_at"):
                        v = _parse_datetime(v) or v
                    elif k in ("batch_id", "reconciliation_run_id"):
                        v = _parse_uuid(v)
                    setattr(item, k, v)
            item.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(item)
            return item.to_dict()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ── 3. GSTR-1 Reconciliation Runs ──────────────────────────────────────────

    def create_gstr1_run(
        self,
        *,
        client_gstin_id: str | UUID,
        status: str,
        result_payload: dict[str, Any],
        run_summary: Optional[dict[str, Any]] = None,
        period: Optional[str] = None,
        gstr1_filed_date: Optional[date | datetime | str] = None,
        gstr3b_filed_date: Optional[date | datetime | str] = None,
        created_at: Optional[datetime | str] = None,
        completed_at: Optional[datetime | str] = None,
        created_by: Optional[str | UUID] = None,
        run_id: Optional[str | UUID] = None,
    ) -> dict[str, Any]:
        """Create a new GSTR-1 reconciliation run."""
        cid = _parse_uuid(client_gstin_id)
        rid = _parse_uuid(run_id)
        uid = _parse_uuid(created_by)
        now = datetime.now(timezone.utc)

        session = self._get_session()
        try:
            run = Gstr1ReconciliationRun(
                id=rid or None,
                client_gstin_id=cid,
                status=status,
                result_payload=result_payload or {},
                run_summary=run_summary,
                period=period,
                gstr1_filed_date=_parse_date(gstr1_filed_date),
                gstr3b_filed_date=_parse_date(gstr3b_filed_date),
                created_at=_parse_datetime(created_at) or now,
                completed_at=_parse_datetime(completed_at) or now,
                created_by=uid,
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            return run.to_dict()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_gstr1_run(
        self,
        run_id: str | UUID,
        include_payload: bool = True,
    ) -> Optional[dict[str, Any]]:
        """Get a single GSTR-1 run by ID."""
        rid = _parse_uuid(run_id)
        session = self._get_session()
        try:
            stmt = select(Gstr1ReconciliationRun).where(Gstr1ReconciliationRun.id == rid)
            run = session.execute(stmt).scalar_one_or_none()
            if not run:
                return None
            data = run.to_dict()
            if not include_payload:
                data.pop("result_payload", None)
            return data
        finally:
            session.close()

    def list_gstr1_runs(
        self,
        client_gstin_id: str | UUID,
        limit: int = 20,
        status: Optional[str] = None,
        include_payload: bool = False,
    ) -> List[dict[str, Any]]:
        """List GSTR-1 runs for a client GSTIN (newest first)."""
        cid = _parse_uuid(client_gstin_id)
        session = self._get_session()
        try:
            stmt = (
                select(Gstr1ReconciliationRun)
                .where(Gstr1ReconciliationRun.client_gstin_id == cid)
                .order_by(sa_desc(Gstr1ReconciliationRun.created_at))
                .limit(limit)
            )
            if status:
                stmt = stmt.where(Gstr1ReconciliationRun.status == status)
            runs = session.execute(stmt).scalars().all()
            out = []
            for r in runs:
                d = r.to_dict()
                if not include_payload:
                    d.pop("result_payload", None)
                out.append(d)
            return out
        finally:
            session.close()

    def latest_completed_gstr1_run(
        self,
        client_gstin_id: str | UUID,
        period: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Get newest COMPLETED GSTR-1 run for client and optional period."""
        cid = _parse_uuid(client_gstin_id)
        session = self._get_session()
        try:
            stmt = (
                select(Gstr1ReconciliationRun)
                .where(
                    Gstr1ReconciliationRun.client_gstin_id == cid,
                    Gstr1ReconciliationRun.status.in_(["COMPLETED", "completed"]),
                )
                .order_by(sa_desc(Gstr1ReconciliationRun.created_at))
            )
            if period:
                stmt = stmt.where(Gstr1ReconciliationRun.period == str(period).strip())
            run = session.execute(stmt).scalars().first()
            return run.to_dict() if run else None
        finally:
            session.close()

    def delete_gstr1_run(self, run_id: str | UUID) -> bool:
        """Delete a GSTR-1 run by ID (cascades to gstr1a_period_actions)."""
        rid = _parse_uuid(run_id)
        session = self._get_session()
        try:
            stmt = select(Gstr1ReconciliationRun).where(Gstr1ReconciliationRun.id == rid)
            run = session.execute(stmt).scalar_one_or_none()
            if not run:
                return False
            session.delete(run)
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ── 4. GSTR-1A Period Actions ──────────────────────────────────────────────

    def list_gstr1a_actions(self, run_id: str | UUID) -> List[dict[str, Any]]:
        """List GSTR-1A period actions for a run, ordered by created_at DESC."""
        rid = _parse_uuid(run_id)
        session = self._get_session()
        try:
            stmt = (
                select(Gstr1aPeriodAction)
                .where(Gstr1aPeriodAction.run_id == rid)
                .order_by(sa_desc(Gstr1aPeriodAction.created_at))
            )
            actions = session.execute(stmt).scalars().all()
            return [a.to_dict() for a in actions]
        finally:
            session.close()

    def get_gstr1a_action(
        self,
        run_id: str | UUID,
        period: str,
    ) -> Optional[dict[str, Any]]:
        """Get a single GSTR-1A action for (run_id, period)."""
        rid = _parse_uuid(run_id)
        p = str(period).strip()
        session = self._get_session()
        try:
            stmt = (
                select(Gstr1aPeriodAction)
                .where(Gstr1aPeriodAction.run_id == rid, Gstr1aPeriodAction.period == p)
                .limit(1)
            )
            act = session.execute(stmt).scalar_one_or_none()
            return act.to_dict() if act else None
        finally:
            session.close()

    def mark_gstr1a_action(
        self,
        *,
        run_id: str | UUID,
        period: str,
        status: str,
        user_id: str,
        note: Optional[str] = None,
        filed_date: Optional[date | datetime | str] = None,
        action_id: Optional[str | UUID] = None,
    ) -> dict[str, Any]:
        """Upsert a GSTR-1A action for (run_id, period) (delete-then-insert semantics)."""
        rid = _parse_uuid(run_id)
        if rid is None:
            raise ValueError(f"Invalid UUID for run_id: {run_id}")
        p = str(period).strip()
        aid = _parse_uuid(action_id)
        f_date = _parse_date(filed_date) or date.today()

        session = self._get_session()
        try:
            # Delete existing action for (run_id, period)
            del_stmt = delete(Gstr1aPeriodAction).where(
                Gstr1aPeriodAction.run_id == rid, Gstr1aPeriodAction.period == p
            )
            session.execute(del_stmt)

            act = Gstr1aPeriodAction(
                id=aid or None,
                run_id=rid,
                period=p,
                status=status,
                user_id=str(user_id).strip(),
                note=note,
                filed_date=f_date,
                created_at=datetime.now(timezone.utc),
            )
            session.add(act)
            session.commit()
            session.refresh(act)
            return act.to_dict()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ── 5. GSTR-2A Delta Results ───────────────────────────────────────────────

    def save_gstr2a_delta(
        self,
        *,
        client_gstin_id: str | UUID,
        period: str,
        summary: dict[str, Any],
        results: list[dict[str, Any]],
        reconciled_at: Optional[datetime | str] = None,
        cutoff_date: Optional[date | datetime | str] = None,
        delta_id: Optional[str | UUID] = None,
    ) -> dict[str, Any]:
        """Upsert GSTR-2A vs GSTR-2B delta reconciliation results."""
        cid = _parse_uuid(client_gstin_id)
        p = str(period).strip()
        did = _parse_uuid(delta_id)
        r_at = _parse_datetime(reconciled_at) or datetime.now(timezone.utc)
        c_date = _parse_date(cutoff_date)
        now = datetime.now(timezone.utc)

        session = self._get_session()
        try:
            stmt = select(Gstr2aDeltaResult).where(
                Gstr2aDeltaResult.client_gstin_id == cid,
                Gstr2aDeltaResult.period == p,
            ).limit(1)
            existing = session.execute(stmt).scalar_one_or_none()

            if existing:
                existing.reconciled_at = r_at
                existing.summary = summary
                existing.results = results
                existing.cutoff_date = c_date
                existing.updated_at = now
                session.commit()
                session.refresh(existing)
                return existing.to_dict()
            else:
                new_row = Gstr2aDeltaResult(
                    id=did or None,
                    client_gstin_id=cid,
                    period=p,
                    reconciled_at=r_at,
                    summary=summary,
                    results=results,
                    cutoff_date=c_date,
                    created_at=now,
                    updated_at=now,
                )
                session.add(new_row)
                session.commit()
                session.refresh(new_row)
                return new_row.to_dict()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_gstr2a_delta(
        self,
        client_gstin_id: str | UUID,
        period: str,
    ) -> Optional[dict[str, Any]]:
        """Get GSTR-2A delta results matching (client_gstin_id, period) variants."""
        cid = _parse_uuid(client_gstin_id)
        p_raw = str(period).strip()
        # Generate variants: e.g. 042025, 2025-04
        variants = {p_raw}
        if len(p_raw) == 6 and p_raw.isdigit():
            variants.add(f"{p_raw[2:6]}-{p_raw[0:2]}")
        elif len(p_raw) == 7 and "-" in p_raw:
            parts = p_raw.split("-")
            variants.add(f"{parts[1]}{parts[0]}")

        session = self._get_session()
        try:
            stmt = (
                select(Gstr2aDeltaResult)
                .where(
                    Gstr2aDeltaResult.client_gstin_id == cid,
                    Gstr2aDeltaResult.period.in_(list(variants)),
                )
                .order_by(sa_desc(Gstr2aDeltaResult.updated_at))
                .limit(1)
            )
            res = session.execute(stmt).scalar_one_or_none()
            return res.to_dict() if res else None
        finally:
            session.close()

    def get_gstr2a_delta_summary(
        self,
        client_gstin_id: str | UUID,
        period: str,
    ) -> Optional[dict[str, Any]]:
        """Get summary metrics for GSTR-2A vs GSTR-2B delta results."""
        row = self.get_gstr2a_delta(client_gstin_id, period)
        if not row:
            return None
        return row.get("summary") or {}

    def list_gstr2a_deltas(
        self,
        client_gstin_id: str | UUID,
        limit: int = 50,
    ) -> List[dict[str, Any]]:
        """List delta results for a client GSTIN."""
        cid = _parse_uuid(client_gstin_id)
        session = self._get_session()
        try:
            stmt = (
                select(Gstr2aDeltaResult)
                .where(Gstr2aDeltaResult.client_gstin_id == cid)
                .order_by(sa_desc(Gstr2aDeltaResult.reconciled_at))
                .limit(limit)
            )
            rows = session.execute(stmt).scalars().all()
            return [r.to_dict() for r in rows]
        finally:
            session.close()

    def delete_gstr2a_delta(self, delta_id: str | UUID) -> bool:
        """Delete a delta result by ID."""
        did = _parse_uuid(delta_id)
        session = self._get_session()
        try:
            stmt = select(Gstr2aDeltaResult).where(Gstr2aDeltaResult.id == did)
            res = session.execute(stmt).scalar_one_or_none()
            if not res:
                return False
            session.delete(res)
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ── 6. GSTR-9 Audit Overrides ──────────────────────────────────────────────

    def save_gstr9_override(
        self,
        *,
        client_gstin_id: str | UUID,
        financial_year: str,
        table_key: str,
        cell_key: str,
        override_value: float | Decimal | int,
        system_value: Optional[float | Decimal | int] = 0.0,
        notes: Optional[str] = None,
        updated_by: Optional[str | UUID] = None,
        override_id: Optional[str | UUID] = None,
        original_value: Optional[float | Decimal | int] = None,
        user_id: Optional[str | UUID] = None,
    ) -> dict[str, Any]:
        """Save or update a CA audit override for a specific GSTR-9 cell."""
        cid = _parse_uuid(client_gstin_id)
        uid = _parse_uuid(updated_by or user_id)
        oid = _parse_uuid(override_id)
        fy = str(financial_year).strip()
        tkey = str(table_key).strip()
        ckey = str(cell_key).strip()
        o_val = _parse_numeric(override_value) or Decimal("0.00")
        eff_sys_val = original_value if original_value is not None else system_value
        s_val = _parse_numeric(eff_sys_val) if eff_sys_val is not None else None
        now = datetime.now(timezone.utc)

        session = self._get_session()
        try:
            stmt = select(Gstr9AuditOverride).where(
                Gstr9AuditOverride.client_gstin_id == cid,
                Gstr9AuditOverride.financial_year == fy,
                Gstr9AuditOverride.table_key == tkey,
                Gstr9AuditOverride.cell_key == ckey,
            ).limit(1)
            existing = session.execute(stmt).scalar_one_or_none()

            if existing:
                existing.override_value = o_val
                if s_val is not None:
                    existing.system_value = s_val
                existing.notes = notes
                existing.updated_by = uid
                existing.updated_at = now
                session.commit()
                session.refresh(existing)
                return existing.to_dict()
            else:
                row = Gstr9AuditOverride(
                    id=oid or None,
                    client_gstin_id=cid,
                    financial_year=fy,
                    table_key=tkey,
                    cell_key=ckey,
                    override_value=o_val,
                    system_value=s_val,
                    notes=notes,
                    updated_by=uid,
                    updated_at=now,
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                return row.to_dict()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def load_gstr9_overrides(
        self,
        client_gstin_id: str | UUID,
        financial_year: str,
    ) -> Dict[str, float]:
        """Load GSTR-9 overrides as key-value pairs formatted as '{table_key}.{cell_key}'."""
        cid = _parse_uuid(client_gstin_id)
        fy = str(financial_year).strip()

        session = self._get_session()
        try:
            stmt = select(
                Gstr9AuditOverride.table_key,
                Gstr9AuditOverride.cell_key,
                Gstr9AuditOverride.override_value,
            ).where(
                Gstr9AuditOverride.client_gstin_id == cid,
                Gstr9AuditOverride.financial_year == fy,
            )
            rows = session.execute(stmt).all()
            return {f"{r[0]}.{r[1]}": float(r[2]) for r in rows}
        finally:
            session.close()

    def list_gstr9_overrides(
        self,
        client_gstin_id: str | UUID,
        financial_year: str,
    ) -> List[dict[str, Any]]:
        """List all full override records for a client GSTIN and financial year."""
        cid = _parse_uuid(client_gstin_id)
        fy = str(financial_year).strip()

        session = self._get_session()
        try:
            stmt = select(Gstr9AuditOverride).where(
                Gstr9AuditOverride.client_gstin_id == cid,
                Gstr9AuditOverride.financial_year == fy,
            )
            rows = session.execute(stmt).scalars().all()
            return [r.to_dict() for r in rows]
        finally:
            session.close()

    def delete_gstr9_override(self, override_id: str | UUID) -> bool:
        """Delete an override by ID."""
        oid = _parse_uuid(override_id)
        session = self._get_session()
        try:
            stmt = select(Gstr9AuditOverride).where(Gstr9AuditOverride.id == oid)
            row = session.execute(stmt).scalar_one_or_none()
            if not row:
                return False
            session.delete(row)
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # Convenience aliases
    upsert_gstr2a_delta = save_gstr2a_delta
    get_gstr2a_delta_results = get_gstr2a_delta
    upsert_gstr9_override = save_gstr9_override
    load_gstr9_overrides_map = load_gstr9_overrides


# ── Global Singleton Instance & Accessors ─────────────────────────────────────

_return_reconciliation_repo: Optional[AuroraReturnReconciliationRepository] = None


def get_return_reconciliation_repository() -> AuroraReturnReconciliationRepository:
    """Return the global AuroraReturnReconciliationRepository singleton."""
    global _return_reconciliation_repo
    if _return_reconciliation_repo is None:
        _return_reconciliation_repo = AuroraReturnReconciliationRepository()
    return _return_reconciliation_repo


def set_return_reconciliation_repository(
    repo: AuroraReturnReconciliationRepository,
) -> None:
    """Override the global repository singleton (primarily for testing)."""
    global _return_reconciliation_repo
    _return_reconciliation_repo = repo
