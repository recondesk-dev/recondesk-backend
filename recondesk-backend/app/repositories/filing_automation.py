"""AWS Aurora Filing Automation & Bulk Return Processing Repository — Batch 3C.

Provides safe, typed SQLAlchemy 2.x data access for:
1. filing_sessions (GSTN taxpayer OTP sessions and access tokens)
2. filing_runs (GSTR return Save, Offset, File lifecycle attempts)
3. filing_batches (Bulk multi-GSTIN return processing headers)
4. filing_batch_items (Individual client item statuses within batches)
5. sales_register_run (Tally Bridge Sales Register auto-sync headers)
6. sr_records (Individual parsed voucher records for sales side)

Architecture & Invariants:
- Designed as future PRIMARY for all Batch 3C operations.
- Full tenant boundary isolation (firm_id on sessions, runs, and batches).
- Zero session token exposure in logs, exception traces, or string outputs.
- Dialect compatibility: AWS Aurora PostgreSQL in production, SQLite in test suites.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import delete, desc as sa_desc, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.aurora import (
    AuroraConfigurationError,
    get_aurora_engine,
    get_aurora_session,
)
from app.models.filing_automation import (
    FilingBatch,
    FilingBatchItem,
    FilingRun,
    FilingSession,
    SalesRegisterRun,
    SrRecord,
)
from app.filing.filing_store import Gstr3bPeriodLockedError

_log = logging.getLogger("recondesk.aurora.filing_automation")

GSTR3B_OFFSET_LOCKED_STATUSES: frozenset[str] = frozenset({
    "offset_complete",
    "evc_pending",
    "filed",
})
RETURN_TYPE_GSTR3B = "gstr-3b"


_fallback_sessionmaker: Optional[sessionmaker[Session]] = None


def _get_fallback_sessionmaker() -> sessionmaker[Session]:
    global _fallback_sessionmaker
    if _fallback_sessionmaker is None:
        from app.scripts.backfill_batch3c_filing_automation import (
            Batch3CFilingAutomationOrchestrator,
        )
        orch = Batch3CFilingAutomationOrchestrator()
        engine = orch._get_engine()
        _fallback_sessionmaker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return _fallback_sessionmaker


def _parse_uuid(val: Any) -> Optional[UUID]:
    if val is None:
        return None
    if isinstance(val, UUID):
        return val
    try:
        return UUID(str(val).strip())
    except (ValueError, AttributeError):
        return None


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _parse_datetime(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


class AuroraFilingAutomationRepository:
    """Production repository for Batch 3C Filing Automation operations."""

    def __init__(self, session_factory: Optional[sessionmaker[Session]] = None) -> None:
        self._session_factory = session_factory

    def _get_session(self) -> Session:
        if self._session_factory:
            return self._session_factory()
        try:
            return get_aurora_session()
        except AuroraConfigurationError:
            return _get_fallback_sessionmaker()()

    # =========================================================================
    # 1. Filing Sessions
    # =========================================================================

    def create_session(
        self,
        *,
        firm_id: str,
        gstin: str,
        username: str,
        session_token: Optional[str] = None,
        token_expires_at: Optional[datetime | str] = None,
        session_expires_at: Optional[datetime | str] = None,
        session: Optional[Any] = None,
        client_gstin_id: Optional[str] = None,
        status: str = "active",
    ) -> dict[str, Any]:
        """Create and persist a new taxpayer OTP session."""
        f_uuid = _parse_uuid(firm_id)
        if not f_uuid:
            raise ValueError(f"Invalid firm_id: {firm_id}")

        if session is not None:
            session_token = getattr(session, "access_token", session_token)
            token_expires_at = getattr(session, "token_expires_at", token_expires_at)
            session_expires_at = getattr(session, "session_expires_at", session_expires_at)

        if not session_token:
            raise ValueError("session_token or session object with access_token required")

        c_uuid = _parse_uuid(client_gstin_id) if client_gstin_id else None
        t_exp = _parse_datetime(token_expires_at)
        if not t_exp:
            raise ValueError("token_expires_at must be a valid datetime")
        s_exp = _parse_datetime(session_expires_at) if session_expires_at else None

        with self._get_session() as session_ctx:
            row = FilingSession(
                firm_id=f_uuid,
                client_gstin_id=c_uuid,
                gstin=gstin.strip().upper(),
                username=username.strip(),
                session_token=session_token.strip(),
                token_expires_at=t_exp,
                session_expires_at=s_exp,
                status=status,
            )
            session_ctx.add(row)
            session_ctx.commit()
            session_ctx.refresh(row)
            _log.info(
                "Created filing_sessions id=%s for gstin=%s (firm=%s)",
                row.id, row.gstin, row.firm_id,
            )
            return row.to_dict(redact_token=False)

    def update_session_token(
        self,
        session_id: str,
        *,
        session_token: Optional[str] = None,
        token_expires_at: Optional[datetime | str] = None,
        session_expires_at: Optional[datetime | str] = None,
        session: Optional[Any] = None,
        status: str = "active",
    ) -> Optional[dict[str, Any]]:
        s_uuid = _parse_uuid(session_id)
        if not s_uuid:
            return None

        if session is not None:
            session_token = getattr(session, "access_token", session_token)
            token_expires_at = getattr(session, "token_expires_at", token_expires_at)
            session_expires_at = getattr(session, "session_expires_at", session_expires_at)

        if not session_token:
            raise ValueError("session_token or session object with access_token required")

        t_exp = _parse_datetime(token_expires_at)
        s_exp = _parse_datetime(session_expires_at) if session_expires_at else None

        with self._get_session() as session_ctx:
            stmt = (
                update(FilingSession)
                .where(FilingSession.id == s_uuid)
                .values(
                    session_token=session_token.strip(),
                    token_expires_at=t_exp,
                    session_expires_at=s_exp,
                    status=status,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            session_ctx.execute(stmt)
            session_ctx.commit()
            row = session_ctx.get(FilingSession, s_uuid)
            return row.to_dict(redact_token=False) if row else None

    def mark_session_logged_out(self, session_id: str) -> None:
        s_uuid = _parse_uuid(session_id)
        if not s_uuid:
            return
        now = datetime.now(timezone.utc)
        with self._get_session() as session:
            stmt = (
                update(FilingSession)
                .where(FilingSession.id == s_uuid)
                .values(
                    status="logged_out",
                    logged_out_at=now,
                    updated_at=now,
                )
            )
            session.execute(stmt)
            session.commit()
            _log.info("Marked filing_sessions id=%s logged_out", session_id)

    def get_active_session(
        self,
        *,
        firm_id: str,
        gstin: str,
        redact_token: bool = False,
    ) -> Optional[dict[str, Any]]:
        f_uuid = _parse_uuid(firm_id)
        if not f_uuid:
            return None
        now = datetime.now(timezone.utc)
        with self._get_session() as session:
            stmt = (
                select(FilingSession)
                .where(
                    FilingSession.firm_id == f_uuid,
                    FilingSession.gstin == gstin.strip().upper(),
                    FilingSession.status == "active",
                    FilingSession.token_expires_at > now,
                )
                .order_by(sa_desc(FilingSession.token_expires_at))
                .limit(1)
            )
            row = session.scalars(stmt).first()
            return row.to_dict(redact_token=redact_token) if row else None

    def get_session_by_id(
        self, session_id: str, redact_token: bool = False
    ) -> Optional[dict[str, Any]]:
        s_uuid = _parse_uuid(session_id)
        if not s_uuid:
            return None
        with self._get_session() as session:
            row = session.get(FilingSession, s_uuid)
            return row.to_dict(redact_token=redact_token) if row else None

    # =========================================================================
    # 2. Filing Runs & GSTR-3B Lock Protection
    # =========================================================================

    def find_gstr3b_offset_lock(
        self, *, gstin: str, period: str
    ) -> Optional[dict[str, Any]]:
        g = (gstin or "").strip().upper()
        p = (period or "").strip()
        if not g or not p:
            return None
        with self._get_session() as session:
            stmt = (
                select(FilingRun)
                .where(
                    FilingRun.return_type == RETURN_TYPE_GSTR3B,
                    FilingRun.gstin == g,
                    FilingRun.period == p,
                    FilingRun.status.in_(sorted(GSTR3B_OFFSET_LOCKED_STATUSES)),
                )
                .order_by(sa_desc(FilingRun.offset_completed_at))
                .limit(1)
            )
            row = session.scalars(stmt).first()
            return row.to_dict() if row else None

    def assert_gstr3b_period_unlocked(
        self, *, gstin: str, period: str, action: str
    ) -> None:
        action_key = (action or "").strip().lower()
        if action_key not in ("save", "offset"):
            raise ValueError(f"action must be 'save' or 'offset'; got {action!r}")

        locking = self.find_gstr3b_offset_lock(gstin=gstin, period=period)
        if locking is None:
            return

        g = (gstin or "").strip().upper()
        p = (period or "").strip()
        lock_id = locking.get("id")
        lock_status = locking.get("status")
        completed_at = locking.get("offset_completed_at")
        has_tx_pmt = locking.get("tx_pmt_snapshot") is not None

        if action_key == "save":
            detail = (
                f"GSTR-3B Save is blocked for {g} period {p}: Offset Liability "
                f"already completed (run_id={lock_id}, status={lock_status!r}"
                f"{f', offset_completed_at={completed_at}' if completed_at else ''}). "
                "The return for this period is locked after Offset. Correct any "
                "figures in a future period's GSTR-3B — do not Save again here."
            )
        else:
            detail = (
                f"GSTR-3B Offset Liability is blocked for {g} period {p}: Offset "
                f"already completed (run_id={lock_id}, status={lock_status!r}"
                f"{f', offset_completed_at={completed_at}' if completed_at else ''}). "
                "A second Offset must not be attempted. Proof: post-Offset Get Details tx_pmt "
                f"{'is stored on that run' if has_tx_pmt else 'should be re-fetched from GSTN for that run'}. "
                "Handle corrections in a future period's return."
            )
        raise Gstr3bPeriodLockedError(
            detail,
            action=action_key,
            gstin=g,
            period=p,
            locking_run=locking,
        )

    def assert_gstr3b_save_allowed(self, *, gstin: str, period: str) -> None:
        self.assert_gstr3b_period_unlocked(gstin=gstin, period=period, action="save")

    def assert_gstr3b_offset_allowed(self, *, gstin: str, period: str) -> None:
        self.assert_gstr3b_period_unlocked(gstin=gstin, period=period, action="offset")

    def create_run(
        self,
        *,
        firm_id: str,
        gstin: str,
        period: str,
        return_type: str = "gstr-1",
        status: str = "draft",
        filing_session_id: Optional[str] = None,
        client_gstin_id: Optional[str] = None,
        save_payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        f_uuid = _parse_uuid(firm_id)
        if not f_uuid:
            raise ValueError(f"Invalid firm_id: {firm_id}")

        c_uuid = _parse_uuid(client_gstin_id) if client_gstin_id else None
        s_uuid = _parse_uuid(filing_session_id) if filing_session_id else None

        with self._get_session() as session:
            run = FilingRun(
                firm_id=f_uuid,
                client_gstin_id=c_uuid,
                filing_session_id=s_uuid,
                gstin=gstin.strip().upper(),
                return_type=return_type.strip().lower(),
                period=period.strip(),
                status=status,
                save_payload=save_payload,
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            _log.info(
                "Created filing_runs id=%s return_type=%s period=%s",
                run.id, run.return_type, run.period,
            )
            return run.to_dict()

    def update_run(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        reference_id: Optional[str] = None,
        ack_number: Optional[str] = None,
        arn: Optional[str] = None,
        filing_method: Optional[str] = None,
        filed_at: Optional[datetime | str] = None,
        save_payload: Optional[dict[str, Any]] = None,
        raw_response: Any = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        clear_error: bool = False,
        offset_payload: Optional[dict[str, Any]] = None,
        offset_completed_at: Optional[datetime | str] = None,
        tx_pmt_snapshot: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        r_uuid = _parse_uuid(run_id)
        if not r_uuid:
            return None

        vals: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
        if status is not None:
            vals["status"] = status
        if reference_id is not None:
            vals["reference_id"] = reference_id
        if ack_number is not None:
            vals["ack_number"] = ack_number
        if arn is not None:
            vals["arn"] = arn
        if filing_method is not None:
            vals["filing_method"] = filing_method
        if filed_at is not None:
            vals["filed_at"] = _parse_datetime(filed_at)
        if save_payload is not None:
            vals["save_payload"] = save_payload
        if raw_response is not None:
            vals["raw_response"] = raw_response
        if clear_error:
            vals["error_code"] = None
            vals["error_message"] = None
        if error_code is not None:
            vals["error_code"] = error_code
        if error_message is not None:
            vals["error_message"] = error_message
        if offset_payload is not None:
            vals["offset_payload"] = offset_payload
        if offset_completed_at is not None:
            vals["offset_completed_at"] = _parse_datetime(offset_completed_at)
        if tx_pmt_snapshot is not None:
            vals["tx_pmt_snapshot"] = tx_pmt_snapshot

        with self._get_session() as session:
            stmt = update(FilingRun).where(FilingRun.id == r_uuid).values(**vals)
            session.execute(stmt)
            session.commit()
            run = session.get(FilingRun, r_uuid)
            return run.to_dict() if run else None

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        r_uuid = _parse_uuid(run_id)
        if not r_uuid:
            return None
        with self._get_session() as session:
            run = session.get(FilingRun, r_uuid)
            return run.to_dict() if run else None

    def mark_run_failed(
        self,
        run_id: str,
        *,
        error_code: Optional[str],
        error_message: str,
        raw_response: Any = None,
    ) -> None:
        self.update_run(
            run_id,
            status="failed",
            error_code=error_code,
            error_message=error_message[:2000],
            raw_response=raw_response,
        )

    def apply_save_status_to_run(
        self,
        run_id: str,
        *,
        return_status: Any,
        envelope: Any = None,
    ) -> Optional[dict[str, Any]]:
        if isinstance(return_status, str):
            if return_status in ("P", "saved"):
                status, err_cd, err_msg = "saved", None, None
            elif return_status in ("ER", "PE", "save_failed"):
                status, err_cd, err_msg = "save_failed", "ERR", "GSTN save failed"
            else:
                status, err_cd, err_msg = "save_pending", None, None
        else:
            from app.filing.sandbox_filing_client import filing_run_status_after_save_poll
            status, err_cd, err_msg = filing_run_status_after_save_poll(return_status)

        if status == "saved":
            return self.update_run(
                run_id,
                status="saved",
                raw_response=envelope,
                clear_error=True,
            )
        if status == "save_failed":
            return self.update_run(
                run_id,
                status="save_failed",
                error_code=err_cd,
                error_message=(err_msg or "GSTN save failed")[:2000],
                raw_response=envelope,
            )
        return self.update_run(
            run_id,
            status="save_pending",
            raw_response=envelope,
        )

    def apply_offset_status_to_run(
        self,
        run_id: str,
        *,
        return_status: Any,
        envelope: Any = None,
        offset_payload: Optional[dict[str, Any]] = None,
        tx_pmt_snapshot: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        if isinstance(return_status, str):
            if return_status in ("P", "offset_complete"):
                status, err_cd, err_msg = "offset_complete", None, None
            elif return_status in ("ER", "PE", "offset_failed"):
                status, err_cd, err_msg = "offset_failed", "ERR", "GSTN offset failed"
            else:
                status, err_cd, err_msg = "offset_pending", None, None
        else:
            from app.filing.sandbox_filing_client import filing_run_status_after_offset_poll
            status, err_cd, err_msg = filing_run_status_after_offset_poll(return_status)

        now = datetime.now(timezone.utc)
        if status == "offset_complete":
            return self.update_run(
                run_id,
                status="offset_complete",
                raw_response=envelope,
                clear_error=True,
                offset_payload=offset_payload,
                offset_completed_at=now,
                tx_pmt_snapshot=tx_pmt_snapshot,
            )
        if status == "offset_failed":
            return self.update_run(
                run_id,
                status="offset_failed",
                error_code=err_cd,
                error_message=(err_msg or "GSTN offset failed")[:2000],
                raw_response=envelope,
            )
        return self.update_run(
            run_id,
            status="offset_pending",
            raw_response=envelope,
        )

    def get_filing_history(
        self,
        *,
        gstin: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        g = (gstin or "").strip().upper()
        if not g:
            return []
        with self._get_session() as session:
            stmt = (
                select(FilingRun)
                .where(FilingRun.gstin == g)
                .order_by(sa_desc(FilingRun.created_at))
                .limit(limit)
            )
            rows = session.scalars(stmt).all()
            return [r.to_dict() for r in rows]

    # =========================================================================
    # 3. Bulk Filing Batches & Items
    # =========================================================================

    def create_batch(
        self,
        *,
        firm_id: str,
        created_by: str,
        period: str,
        client_gstin_ids: list[str],
        return_type: str = "gstr-1",
        client_gstin_map: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        f_uuid = _parse_uuid(firm_id)
        u_uuid = _parse_uuid(created_by)
        if not f_uuid or not u_uuid:
            raise ValueError("firm_id and created_by must be valid UUIDs")

        with self._get_session() as session:
            batch = FilingBatch(
                firm_id=f_uuid,
                created_by=u_uuid,
                return_type=return_type,
                period=period.strip(),
                status="pending",
                total_count=len(client_gstin_ids),
            )
            session.add(batch)
            session.flush()

            gstin_map = client_gstin_map or {}
            for cid in client_gstin_ids:
                c_uuid = _parse_uuid(cid)
                if not c_uuid:
                    continue
                gstin_val = gstin_map.get(cid, "")
                item = FilingBatchItem(
                    batch_id=batch.id,
                    client_gstin_id=c_uuid,
                    gstin=gstin_val,
                    status="pending",
                )
                session.add(item)

            session.commit()
            return self.get_batch(str(batch.id)) or batch.to_dict()

    def get_batch(self, batch_id: str) -> Optional[dict[str, Any]]:
        b_uuid = _parse_uuid(batch_id)
        if not b_uuid:
            return None
        with self._get_session() as session:
            batch = session.get(FilingBatch, b_uuid)
            if not batch:
                return None
            res = batch.to_dict()
            items_stmt = (
                select(FilingBatchItem)
                .where(FilingBatchItem.batch_id == b_uuid)
                .order_by(FilingBatchItem.created_at)
            )
            items = session.scalars(items_stmt).all()
            res["items"] = [i.to_dict() for i in items]
            return res

    def list_batches(self, firm_id: str, limit: int = 50) -> list[dict[str, Any]]:
        f_uuid = _parse_uuid(firm_id)
        if not f_uuid:
            return []
        with self._get_session() as session:
            stmt = (
                select(FilingBatch)
                .where(FilingBatch.firm_id == f_uuid)
                .order_by(sa_desc(FilingBatch.created_at))
                .limit(limit)
            )
            batches = session.scalars(stmt).all()
            return [b.to_dict() for b in batches]

    def update_batch_item(
        self,
        item_id: str,
        *,
        status: Optional[str] = None,
        filing_run_id: Optional[str] = None,
        error_code: Optional[str] = None,
        error_detail: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        i_uuid = _parse_uuid(item_id)
        if not i_uuid:
            return None

        vals: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
        if status is not None:
            vals["status"] = status
        if filing_run_id is not None:
            vals["filing_run_id"] = _parse_uuid(filing_run_id)
        if error_code is not None:
            vals["error_code"] = error_code
        if error_detail is not None:
            vals["error_detail"] = error_detail[:2000]

        with self._get_session() as session:
            stmt = update(FilingBatchItem).where(FilingBatchItem.id == i_uuid).values(**vals)
            session.execute(stmt)
            session.commit()
            item = session.get(FilingBatchItem, i_uuid)
            return item.to_dict() if item else None

    def recalculate_batch_status(self, batch_id: str) -> Optional[dict[str, Any]]:
        b_uuid = _parse_uuid(batch_id)
        if not b_uuid:
            return None

        with self._get_session() as session:
            stmt = select(FilingBatchItem.status).where(FilingBatchItem.batch_id == b_uuid)
            statuses = session.scalars(stmt).all()
            total = len(statuses)

            saved_c = sum(1 for s in statuses if s == "saved")
            evc_pending_c = sum(1 for s in statuses if s == "evc_pending")
            filed_c = sum(1 for s in statuses if s == "filed")
            failed_c = sum(1 for s in statuses if s == "failed")
            needs_review_c = sum(1 for s in statuses if s == "needs_review")
            in_prog_c = sum(1 for s in statuses if s in ("in_progress", "pending"))

            if in_prog_c > 0:
                overall_status = "in_progress"
            elif filed_c == total and total > 0:
                overall_status = "completed"
            elif failed_c == total and total > 0:
                overall_status = "failed"
            else:
                overall_status = "partially_completed"

            update_stmt = (
                update(FilingBatch)
                .where(FilingBatch.id == b_uuid)
                .values(
                    status=overall_status,
                    saved_count=saved_c,
                    evc_pending_count=evc_pending_c,
                    filed_count=filed_c,
                    failed_count=failed_c,
                    needs_review_count=needs_review_c,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            session.execute(update_stmt)
            session.commit()
            batch = session.get(FilingBatch, b_uuid)
            return batch.to_dict() if batch else None

    # =========================================================================
    # 4. Sales Register Run & sr_records Access
    # =========================================================================

    def fetch_sales_register_records(
        self, client_gstin_id: str, period: str
    ) -> list[dict[str, Any]]:
        cid = str(client_gstin_id).strip()
        p = period.strip()
        with self._get_session() as session:
            stmt = (
                select(SrRecord.record_data)
                .where(
                    SrRecord.client_gstin_id == cid,
                    SrRecord.period == p,
                )
            )
            rows = session.scalars(stmt).all()
            return [r for r in rows if isinstance(r, dict)]

    def create_sales_register_run(
        self,
        *,
        client_gstin_id: str,
        period: str,
        file_type: str = "sales_register",
        r2_key: Optional[str] = None,
        status: str = "queued",
        file_hash: str = "",
    ) -> dict[str, Any]:
        c_uuid = _parse_uuid(client_gstin_id)
        if not c_uuid:
            raise ValueError(f"Invalid client_gstin_id: {client_gstin_id}")

        with self._get_session() as session:
            srr = SalesRegisterRun(
                client_gstin_id=c_uuid,
                period=period.strip(),
                file_type=file_type,
                r2_key=r2_key,
                status=status,
                file_hash=file_hash,
            )
            session.add(srr)
            session.commit()
            session.refresh(srr)
            return srr.to_dict()

    def get_sales_register_run(self, run_id: str) -> Optional[dict[str, Any]]:
        r_uuid = _parse_uuid(run_id)
        if not r_uuid:
            return None
        with self._get_session() as session:
            row = session.get(SalesRegisterRun, r_uuid)
            return row.to_dict() if row else None

    def create_sr_records(
        self,
        *,
        run_id: str,
        client_gstin_id: str,
        period: str,
        records: list[dict[str, Any]],
    ) -> int:
        r_uuid = _parse_uuid(run_id)
        if not r_uuid:
            raise ValueError("Invalid run_id")
        cid = str(client_gstin_id).strip()
        p = period.strip()

        with self._get_session() as session:
            inserted = 0
            for r in records:
                row = SrRecord(
                    run_id=r_uuid,
                    client_gstin_id=cid,
                    period=p,
                    record_data=r,
                )
                session.add(row)
                inserted += 1
            session.commit()
            return inserted

    def update_batch_status(self, batch_id: str, status: str) -> Optional[dict[str, Any]]:
        """Update overall status of a filing batch."""
        b_uuid = _parse_uuid(batch_id)
        if not b_uuid:
            return None
        with self._get_session() as session:
            stmt = (
                update(FilingBatch)
                .where(FilingBatch.id == b_uuid)
                .values(
                    status=status,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            session.execute(stmt)
            session.commit()
            batch = session.get(FilingBatch, b_uuid)
            return batch.to_dict() if batch else None

    def delete_session(self, session_id: str) -> bool:
        """Delete a filing session by id (cascading to dependent runs if configured)."""
        s_uuid = _parse_uuid(session_id)
        if not s_uuid:
            return False
        with self._get_session() as session:
            row = session.get(FilingSession, s_uuid)
            if not row:
                return False
            session.delete(row)
            session.commit()
            return True

    def delete_run(self, run_id: str) -> bool:
        """Delete a filing run by id."""
        r_uuid = _parse_uuid(run_id)
        if not r_uuid:
            return False
        with self._get_session() as session:
            row = session.get(FilingRun, r_uuid)
            if not row:
                return False
            session.delete(row)
            session.commit()
            return True

    def delete_batch(self, batch_id: str) -> bool:
        """Delete a filing batch and its child batch items."""
        b_uuid = _parse_uuid(batch_id)
        if not b_uuid:
            return False
        with self._get_session() as session:
            row = session.get(FilingBatch, b_uuid)
            if not row:
                return False
            session.delete(row)
            session.commit()
            return True

    def get_sr_records(
        self,
        *,
        client_gstin_id: str,
        period: str,
    ) -> list[dict[str, Any]]:
        """Fetch parsed sales register records by client_gstin_id and period."""
        return self.fetch_sales_register_records(client_gstin_id, period)

    def delete_sales_register_run(self, run_id: str) -> bool:
        """Delete a sales register run by id (cascading to sr_records)."""
        r_uuid = _parse_uuid(run_id)
        if not r_uuid:
            return False
        with self._get_session() as session:
            row = session.get(SalesRegisterRun, r_uuid)
            if not row:
                return False
            # Explicit delete of child records for engines without FK cascade (like SQLite in tests)
            session.execute(delete(SrRecord).where(SrRecord.run_id == r_uuid))
            session.delete(row)
            session.commit()
            return True

    def delete_sr_records(self, run_id: str) -> int:
        """Delete all sr_records associated with a run_id."""
        r_uuid = _parse_uuid(run_id)
        if not r_uuid:
            return 0
        with self._get_session() as session:
            stmt = delete(SrRecord).where(SrRecord.run_id == r_uuid)
            res = session.execute(stmt)
            session.commit()
            return res.rowcount or 0


_global_filing_repo: Optional[AuroraFilingAutomationRepository] = None


def get_filing_automation_repository() -> AuroraFilingAutomationRepository:
    """Return the global Aurora filing automation repository singleton."""
    global _global_filing_repo
    if _global_filing_repo is None:
        _global_filing_repo = AuroraFilingAutomationRepository()
    return _global_filing_repo


def set_filing_automation_repository(
    repo: Optional[AuroraFilingAutomationRepository],
) -> None:
    """Inject or reset filing automation repository instance (used in tests)."""
    global _global_filing_repo
    _global_filing_repo = repo
