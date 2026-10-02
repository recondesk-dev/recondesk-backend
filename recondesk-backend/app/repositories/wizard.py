"""AWS Aurora Wizard & Ingestion Repository for ReconDesk.

Provides safe, typed SQLAlchemy data-access methods for:
- Import wizard runs (reconciliation_import_runs)
- Import wizard audit logs (reconciliation_import_run_audit_log)
- Client PR column mappings (client_import_mappings)

Security & Data Invariants:
1. Multi-tenant scoping: all queries respect client_id / client_gstin_id boundaries.
2. Exact parity with Supabase PostgREST serialized shapes (.to_dict()).
3. Transactional atomic operations for mapping saves and run transitions.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional, Sequence
from uuid import UUID

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.models.wizard import (
    ClientImportMapping,
    ReconciliationImportRun,
    ReconciliationImportRunAuditLog,
)

_log = logging.getLogger("recondesk.aurora.wizard")

ACTIVE_STATUSES = [
    "draft",
    "gstr_uploaded",
    "pr_uploaded",
    "pending",
    "processing",
]


def _parse_date(val: Any) -> Optional[date]:
    if val is None or isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        if len(s) == 7 and s[4] == "-":
            s = f"{s}-01"
        return date.fromisoformat(s[:10])
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
        return datetime.fromisoformat(s)
    return None


class AuroraWizardRepository:
    """Repository handling import wizard, audit trail, and column mapping operations in AWS Aurora."""

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

    # ── Reconciliation Import Run Operations ───────────────────────────────────

    def get_run(self, run_id: str | UUID) -> Optional[dict[str, Any]]:
        """Fetch import wizard run by primary key."""
        rid = str(run_id or "").strip()
        if not rid:
            return None

        with self._get_session() as session:
            stmt = select(ReconciliationImportRun).where(
                ReconciliationImportRun.id == rid
            )
            run = session.scalar(stmt)
            if run is None:
                return None
            return run.to_dict()

    def get_runs_by_ids(
        self, run_ids: Sequence[str | UUID]
    ) -> list[dict[str, Any]]:
        """Fetch import wizard runs by a collection of IDs."""
        if not run_ids:
            return []
        rids = [str(r).strip() for r in run_ids if str(r).strip()]
        if not rids:
            return []

        with self._get_session() as session:
            stmt = select(ReconciliationImportRun).where(
                ReconciliationImportRun.id.in_(rids)
            )
            runs = session.scalars(stmt).all()
            return [r.to_dict() for r in runs]

    def list_runs_for_clients(
        self,
        client_ids: Sequence[str | UUID],
        *,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """List import wizard runs for accessible clients ordered by created_at desc."""
        if not client_ids:
            return []
        cids = [str(c).strip() for c in client_ids if str(c).strip()]
        if not cids:
            return []

        with self._get_session() as session:
            stmt = (
                select(ReconciliationImportRun)
                .where(ReconciliationImportRun.client_id.in_(cids))
                .order_by(ReconciliationImportRun.created_at.desc())
                .limit(limit)
            )
            runs = session.scalars(stmt).all()
            return [r.to_dict() for r in runs]

    def find_active_run_for_client_and_period(
        self,
        client_id: str | UUID,
        period: str | date,
        active_statuses: Optional[Sequence[str]] = None,
    ) -> Optional[dict[str, Any]]:
        """Find the most recently updated active run for a client and period."""
        cid = str(client_id or "").strip()
        p = _parse_date(period)
        if not cid or not p:
            return None

        statuses = list(active_statuses or ACTIVE_STATUSES)

        with self._get_session() as session:
            stmt = (
                select(ReconciliationImportRun)
                .where(
                    ReconciliationImportRun.client_id == cid,
                    ReconciliationImportRun.period == p,
                    ReconciliationImportRun.status.in_(statuses),
                )
                .order_by(ReconciliationImportRun.updated_at.desc())
                .limit(1)
            )
            run = session.scalar(stmt)
            if run is None:
                return None
            return run.to_dict()

    def find_active_run_for_client(
        self,
        client_id: str | UUID,
        active_statuses: Optional[Sequence[str]] = None,
    ) -> Optional[dict[str, Any]]:
        """Find the most recently updated active run for a client."""
        cid = str(client_id or "").strip()
        if not cid:
            return None

        statuses = list(active_statuses or ACTIVE_STATUSES)

        with self._get_session() as session:
            stmt = (
                select(ReconciliationImportRun)
                .where(
                    ReconciliationImportRun.client_id == cid,
                    ReconciliationImportRun.status.in_(statuses),
                )
                .order_by(ReconciliationImportRun.updated_at.desc())
                .limit(1)
            )
            run = session.scalar(stmt)
            if run is None:
                return None
            return run.to_dict()

    def find_completed_run_for_period(
        self,
        client_id: str | UUID,
        period: str | date,
    ) -> Optional[dict[str, Any]]:
        """Find if a completed run exists for a client and period."""
        cid = str(client_id or "").strip()
        p = _parse_date(period)
        if not cid or not p:
            return None

        with self._get_session() as session:
            stmt = (
                select(ReconciliationImportRun)
                .where(
                    ReconciliationImportRun.client_id == cid,
                    ReconciliationImportRun.period == p,
                    ReconciliationImportRun.status == "complete",
                )
                .limit(1)
            )
            run = session.scalar(stmt)
            if run is None:
                return None
            return run.to_dict()

    def another_processing_run(
        self,
        client_id: str | UUID,
        period: str | date,
        exclude_run_id: str | UUID,
    ) -> bool:
        """Check if another run is in processing status for this client and period."""
        cid = str(client_id or "").strip()
        p = _parse_date(period)
        ex_id = str(exclude_run_id or "").strip()
        if not cid or not p:
            return False

        with self._get_session() as session:
            stmt = (
                select(ReconciliationImportRun.id)
                .where(
                    ReconciliationImportRun.client_id == cid,
                    ReconciliationImportRun.period == p,
                    ReconciliationImportRun.status == "processing",
                    ReconciliationImportRun.id != ex_id,
                )
                .limit(1)
            )
            return session.scalar(stmt) is not None

    def create_run(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new reconciliation import run."""
        d = dict(data)
        run_id = d.get("id") or str(uuid.uuid4())
        period = _parse_date(d.get("period"))
        if period is None:
            raise ValueError("period is required and must be valid date")

        now = datetime.now(timezone.utc)
        created_at = _parse_datetime(d.get("created_at")) or now
        updated_at = _parse_datetime(d.get("updated_at")) or now

        row = ReconciliationImportRun(
            id=str(run_id),
            client_id=str(d["client_id"]),
            firm_owner_id=str(d["firm_owner_id"]) if d.get("firm_owner_id") else None,
            period=period,
            status=d.get("status", "draft"),
            current_step=int(d.get("current_step", 1)),
            gstr2b_r2_key=d.get("gstr2b_r2_key"),
            gstr2b_file_name=d.get("gstr2b_file_name"),
            gstr2b_file_size=d.get("gstr2b_file_size"),
            gstr2b_file_hash=d.get("gstr2b_file_hash"),
            gstr2b_uploaded_at=_parse_datetime(d.get("gstr2b_uploaded_at")),
            gstr2b_record_count=int(d.get("gstr2b_record_count") or 0),
            sanity_check_results=d.get("sanity_check_results"),
            pr_r2_key=d.get("pr_r2_key"),
            pr_file_name=d.get("pr_file_name"),
            pr_file_size=d.get("pr_file_size"),
            pr_file_hash=d.get("pr_file_hash"),
            pr_uploaded_at=_parse_datetime(d.get("pr_uploaded_at")),
            pr_record_count=int(d.get("pr_record_count") or 0),
            column_mapping=d.get("column_mapping"),
            created_by=str(d["created_by"]),
            created_at=created_at,
            updated_at=updated_at,
            progress_pct=int(d.get("progress_pct") or 0),
            status_message=d.get("status_message"),
            error_detail=d.get("error_detail"),
            pr_column_headers=d.get("pr_column_headers"),
            gstr2b_deleted_at=_parse_datetime(d.get("gstr2b_deleted_at")),
            pr_deleted_at=_parse_datetime(d.get("pr_deleted_at")),
            itc_claimed_period=_parse_date(d.get("itc_claimed_period")),
            run_summary=d.get("run_summary"),
        )

        with self._get_session() as session:
            session.add(row)
            session.commit()
            session.refresh(row)
            return row.to_dict()

    def update_run(
        self,
        run_id: str | UUID,
        patch: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Update reconciliation import run fields by primary key."""
        rid = str(run_id or "").strip()
        if not rid or not patch:
            return self.get_run(run_id)

        clean_patch: dict[str, Any] = {}
        for k, v in patch.items():
            if k in ("created_at", "updated_at", "gstr2b_uploaded_at", "pr_uploaded_at", "gstr2b_deleted_at", "pr_deleted_at"):
                clean_patch[k] = _parse_datetime(v) if v is not None else None
            elif k in ("period", "itc_claimed_period"):
                clean_patch[k] = _parse_date(v) if v is not None else None
            elif k in ("progress_pct", "current_step", "gstr2b_file_size", "pr_file_size", "gstr2b_record_count", "pr_record_count"):
                clean_patch[k] = int(v) if v is not None else None
            else:
                clean_patch[k] = v

        if "updated_at" not in clean_patch:
            clean_patch["updated_at"] = datetime.now(timezone.utc)

        with self._get_session() as session:
            stmt = (
                update(ReconciliationImportRun)
                .where(ReconciliationImportRun.id == rid)
                .values(**clean_patch)
            )
            res = session.execute(stmt)
            session.commit()
            if res.rowcount == 0:
                return None

            # Fetch fresh row
            get_stmt = select(ReconciliationImportRun).where(
                ReconciliationImportRun.id == rid
            )
            run = session.scalar(get_stmt)
            return run.to_dict() if run else None

    def delete_run(self, run_id: str | UUID) -> bool:
        """Delete reconciliation import run by primary key (cascades audit logs)."""
        rid = str(run_id or "").strip()
        if not rid:
            return False

        with self._get_session() as session:
            del_audit = delete(ReconciliationImportRunAuditLog).where(
                ReconciliationImportRunAuditLog.run_id == rid
            )
            session.execute(del_audit)
            stmt = delete(ReconciliationImportRun).where(
                ReconciliationImportRun.id == rid
            )
            res = session.execute(stmt)
            session.commit()
            return res.rowcount > 0

    # ── Audit Log Operations ──────────────────────────────────────────────────

    def create_audit_log(
        self,
        run_id: str | UUID,
        user_id: str | UUID,
        event: str,
        detail: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Record an import wizard audit log entry."""
        rid = str(run_id or "").strip()
        uid = str(user_id or "").strip()
        log_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        row = ReconciliationImportRunAuditLog(
            id=log_id,
            run_id=rid,
            user_id=uid,
            event=event,
            detail=detail or {},
            created_at=now,
        )

        with self._get_session() as session:
            session.add(row)
            session.commit()
            session.refresh(row)
            return row.to_dict()

    def list_audit_logs(
        self, run_id: str | UUID
    ) -> list[dict[str, Any]]:
        """List all audit logs for a run ordered by created_at asc."""
        rid = str(run_id or "").strip()
        if not rid:
            return []

        with self._get_session() as session:
            stmt = (
                select(ReconciliationImportRunAuditLog)
                .where(ReconciliationImportRunAuditLog.run_id == rid)
                .order_by(ReconciliationImportRunAuditLog.created_at.asc())
            )
            logs = session.scalars(stmt).all()
            return [lg.to_dict() for lg in logs]

    # ── Client Import Mappings Operations ──────────────────────────────────────

    def get_client_mappings(
        self, client_gstin_id: str | UUID
    ) -> list[dict[str, Any]]:
        """Fetch saved column mappings for client GSTIN ordered by target_field."""
        cid = str(client_gstin_id or "").strip()
        if not cid:
            return []

        with self._get_session() as session:
            stmt = (
                select(ClientImportMapping)
                .where(ClientImportMapping.client_gstin_id == cid)
                .order_by(ClientImportMapping.target_field.asc())
            )
            mappings = session.scalars(stmt).all()
            return [m.to_dict() for m in mappings]

    def save_client_mappings(
        self,
        client_gstin_id: str | UUID,
        items: Sequence[Any],
    ) -> list[dict[str, Any]]:
        """Atomically replace column mappings for a client GSTIN."""
        cid = str(client_gstin_id or "").strip()
        if not cid:
            raise ValueError("client_gstin_id is required")

        now = datetime.now(timezone.utc)
        new_rows: list[ClientImportMapping] = []
        for it in items:
            src = str(
                it.get("source_column_name")
                if isinstance(it, dict)
                else getattr(it, "source_column_name", "")
            ).strip()
            tf = str(
                it.get("target_field")
                if isinstance(it, dict)
                else getattr(getattr(it, "target_field", None), "value", getattr(it, "target_field", ""))
            ).strip()
            if not src or not tf:
                continue

            new_rows.append(
                ClientImportMapping(
                    id=str(uuid.uuid4()),
                    client_gstin_id=cid,
                    source_column_name=src,
                    target_field=tf,
                    created_at=now,
                    updated_at=now,
                )
            )

        with self._get_session() as session:
            # Atomic delete existing + insert new
            del_stmt = delete(ClientImportMapping).where(
                ClientImportMapping.client_gstin_id == cid
            )
            session.execute(del_stmt)

            if new_rows:
                session.add_all(new_rows)

            session.commit()

            # Query back
            stmt = (
                select(ClientImportMapping)
                .where(ClientImportMapping.client_gstin_id == cid)
                .order_by(ClientImportMapping.target_field.asc())
            )
            mappings = session.scalars(stmt).all()
            return [m.to_dict() for m in mappings]

    def delete_client_mappings(self, client_gstin_id: str | UUID) -> bool:
        """Delete all saved column mappings for a client GSTIN."""
        cid = str(client_gstin_id or "").strip()
        if not cid:
            return False

        with self._get_session() as session:
            stmt = delete(ClientImportMapping).where(
                ClientImportMapping.client_gstin_id == cid
            )
            res = session.execute(stmt)
            session.commit()
            return res.rowcount > 0


# ── Global Repository Accessors ───────────────────────────────────────────────

_wizard_repo: Optional[AuroraWizardRepository] = None


def get_wizard_repository() -> Optional[AuroraWizardRepository]:
    """Return global AuroraWizardRepository if Aurora is enabled/configured, else None."""
    global _wizard_repo
    if _wizard_repo is not None:
        return _wizard_repo

    from app.aurora import get_aurora_database_url, is_aurora_enabled

    if is_aurora_enabled() or get_aurora_database_url():
        try:
            _wizard_repo = AuroraWizardRepository()
            return _wizard_repo
        except Exception as exc:
            _log.warning(
                "Failed to initialize AuroraWizardRepository: %s",
                type(exc).__name__,
            )
            return None

    return None


def set_wizard_repository(repo: Optional[AuroraWizardRepository]) -> None:
    """Explicitly set or reset the wizard repository (for testing)."""
    global _wizard_repo
    _wizard_repo = repo
