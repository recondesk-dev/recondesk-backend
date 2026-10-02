"""AWS Aurora Compliance Repository for ReconDesk — Batch 2A.

Provides safe, typed SQLAlchemy data-access for:
- mismatch_notes
- reconciliation_exception_dispositions
- invoice_tracking
- rule37_actions
- rule37_resolutions
- rule37_alert_dedup

Architecture:
- Aurora is PRIMARY for all six tables.
- Supabase is a READ-ONLY fallback (never the write target) used only when
  Aurora is unavailable, to maintain read availability during the migration
  window.
- Writes ALWAYS go to Aurora first.  Supabase fallback is never written to
  from this module.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from app.models.compliance import (
    InvoiceTracking,
    MismatchNote,
    ReconciliationExceptionDisposition,
    Rule37Action,
    Rule37AlertDedup,
    Rule37Resolution,
)

_log = logging.getLogger("recondesk.aurora.compliance")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _str(val: Any) -> str:
    return str(val) if val is not None else ""


def _model_to_dict(obj: Any) -> dict[str, Any]:
    """Convert SQLAlchemy model to dict via its to_dict() method."""
    if obj is None:
        return {}
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return {}


def _is_sqlite(session: Session) -> bool:
    """Return True if the underlying DB is SQLite (test/dev fallback)."""
    return "sqlite" in str(session.bind.dialect.name) if session.bind else False


def _upsert_stmt(session: Session, model_cls: Any, values: dict, conflict_cols: list[str]) -> Any:
    """Return a dialect-appropriate upsert statement."""
    if _is_sqlite(session):
        stmt = sqlite_insert(model_cls.__table__).values(**values)
        update_cols = {c: values[c] for c in values if c not in conflict_cols}
        return stmt.on_conflict_do_update(index_elements=conflict_cols, set_=update_cols)
    else:
        stmt = pg_insert(model_cls.__table__).values(**values)
        update_cols = {c: values[c] for c in values if c not in conflict_cols}
        return stmt.on_conflict_do_update(index_elements=conflict_cols, set_=update_cols)


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


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class AuroraComplianceRepository:
    """Repository for Batch 2A compliance tables in AWS Aurora."""

    def __init__(
        self,
        session_factory: Optional[sessionmaker[Session]] = None,
    ) -> None:
        if session_factory is not None:
            self._session_factory = session_factory
        else:
            from app.aurora import get_aurora_sessionmaker
            self._session_factory = get_aurora_sessionmaker()

    # -----------------------------------------------------------------------
    # mismatch_notes
    # -----------------------------------------------------------------------

    def insert_mismatch_note(self, row: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Insert a new mismatch_note. Returns the inserted row dict."""
        try:
            with self._session_factory() as session:
                created = _parse_datetime(row.get("created_at")) or datetime.now(timezone.utc)
                note = MismatchNote(
                    record_id=str(row["record_id"]) if row.get("record_id") else None,
                    run_id=str(row["run_id"]),
                    user_id=str(row["user_id"]) if row.get("user_id") else None,
                    note=row.get("note", ""),
                    record_type=row.get("record_type", "pr"),
                    status=row.get("status") or row.get("note_type") or "pending",
                    created_at=created,
                )
                session.add(note)
                session.flush()
                result = _model_to_dict(note)
                session.commit()
                return result
        except Exception as exc:
            _log.warning("Aurora insert_mismatch_note failed: %s", exc)
            return None


    def get_mismatch_notes_by_record_id(
        self, record_id: str, *, include_decision_status: bool = True
    ) -> list[dict[str, Any]]:
        """Fetch all mismatch_notes for a given record_id."""
        try:
            with self._session_factory() as session:
                stmt = (
                    select(MismatchNote)
                    .where(MismatchNote.record_id == str(record_id))
                    .order_by(MismatchNote.created_at.desc())
                )
                rows = session.execute(stmt).scalars().all()
                out = [_model_to_dict(r) for r in rows]
                if not include_decision_status:
                    out = [
                        r for r in out
                        if str(r.get("status") or "").strip().lower() != "decision_status"
                    ]
                return out
        except Exception as exc:
            _log.warning("Aurora get_mismatch_notes_by_record_id failed: %s", exc)
            return []

    def get_mismatch_notes_by_run_id(
        self, run_id: str, *, note_type: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Fetch mismatch_notes for a run, optionally filtered by note_type (mapped to status)."""
        try:
            with self._session_factory() as session:
                stmt = (
                    select(MismatchNote)
                    .where(MismatchNote.run_id == str(run_id))
                )
                if note_type is not None:
                    stmt = stmt.where(MismatchNote.status == note_type)
                rows = session.execute(stmt).scalars().all()
                return [_model_to_dict(r) for r in rows]
        except Exception as exc:
            _log.warning("Aurora get_mismatch_notes_by_run_id failed: %s", exc)
            return []


    def get_mismatch_note_by_id(self, note_id: str) -> Optional[dict[str, Any]]:
        """Fetch a single mismatch_note by primary key."""
        try:
            with self._session_factory() as session:
                obj = session.get(MismatchNote, str(note_id))
                return _model_to_dict(obj) if obj else None
        except Exception as exc:
            _log.warning("Aurora get_mismatch_note_by_id failed: %s", exc)
            return None

    def update_mismatch_note(self, note_id: str, *, note: str) -> bool:
        """Update note text on an existing mismatch_note. Returns True on success."""
        try:
            with self._session_factory() as session:
                stmt = (
                    update(MismatchNote)
                    .where(MismatchNote.id == str(note_id))
                    .values(note=note)
                )
                session.execute(stmt)
                session.commit()
                return True
        except Exception as exc:
            _log.warning("Aurora update_mismatch_note failed: %s", exc)
            return False

    def delete_mismatch_note(self, note_id: str) -> bool:
        """Delete a single mismatch_note by primary key. Returns True on success."""
        try:
            with self._session_factory() as session:
                stmt = delete(MismatchNote).where(MismatchNote.id == str(note_id))
                session.execute(stmt)
                session.commit()
                return True
        except Exception as exc:
            _log.warning("Aurora delete_mismatch_note failed: %s", exc)
            return False

    def delete_mismatch_notes_by_run_and_record(
        self, run_id: str, record_id: str
    ) -> bool:
        """Delete all mismatch_notes matching (run_id, record_id). Used for decision-status upsert."""
        try:
            with self._session_factory() as session:
                stmt = (
                    delete(MismatchNote)
                    .where(MismatchNote.run_id == str(run_id))
                    .where(MismatchNote.record_id == str(record_id))
                )
                session.execute(stmt)
                session.commit()
                return True
        except Exception as exc:
            _log.warning("Aurora delete_mismatch_notes_by_run_and_record failed: %s", exc)
            return False

    # -----------------------------------------------------------------------
    # reconciliation_exception_dispositions
    # -----------------------------------------------------------------------

    def upsert_exception_disposition(self, row: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Upsert an exception disposition on (run_id, record_id, exception_type)."""
        try:
            with self._session_factory() as session:
                created = _parse_datetime(row.get("created_at")) or datetime.now(timezone.utc)
                values = {
                    "run_id": str(row["run_id"]),
                    "record_id": str(row["record_id"]),
                    "exception_type": str(row["exception_type"]),
                    "disposition": str(row["disposition"]),
                    "eligibility_effect": row.get("eligibility_effect"),
                    "table4_effect": row.get("table4_effect"),
                    "reason": row.get("reason", ""),
                    "reference_doc": row.get("reference_doc"),
                    "statutory_reference": row.get("statutory_reference"),
                    "created_by": str(row["created_by"]) if row.get("created_by") else None,
                    "created_at": created,
                }
                stmt = _upsert_stmt(
                    session,
                    ReconciliationExceptionDisposition,
                    values,
                    ["run_id", "record_id", "exception_type"],
                )
                result = session.execute(stmt)
                session.commit()
                # Re-fetch to return full row
                obj = session.execute(
                    select(ReconciliationExceptionDisposition)
                    .where(ReconciliationExceptionDisposition.run_id == values["run_id"])
                    .where(ReconciliationExceptionDisposition.record_id == values["record_id"])
                    .where(ReconciliationExceptionDisposition.exception_type == values["exception_type"])
                ).scalars().first()
                return _model_to_dict(obj) if obj else values
        except Exception as exc:
            _log.warning("Aurora upsert_exception_disposition failed: %s", exc)
            return None

    def get_exception_dispositions_for_run(
        self, run_id: str
    ) -> dict[str, dict[str, Any]]:
        """Load all dispositions for run_id, keyed by '{record_id}:{exception_type}' and 'record_id'."""
        try:
            with self._session_factory() as session:
                stmt = (
                    select(ReconciliationExceptionDisposition)
                    .where(ReconciliationExceptionDisposition.run_id == str(run_id))
                )
                rows = session.execute(stmt).scalars().all()
                out: dict[str, dict[str, Any]] = {}
                for r in rows:
                    d = _model_to_dict(r)
                    rec_id = str(d.get("record_id") or "")
                    ex_type = str(d.get("exception_type") or "")
                    out[f"{rec_id}:{ex_type}"] = d
                    out[rec_id] = d
                return out
        except Exception as exc:
            _log.warning("Aurora get_exception_dispositions_for_run failed: %s", exc)
            return {}

    # -----------------------------------------------------------------------
    # invoice_tracking
    # -----------------------------------------------------------------------

    def bulk_fetch_invoice_tracking(
        self, client_gstin_id: UUID, *, page_size: int = 1000
    ) -> dict[tuple[str, str], dict[str, Any]]:
        """Fetch ALL invoice_tracking rows for a client, keyed by (invoice_number, supplier_gstin)."""
        index: dict[tuple[str, str], dict[str, Any]] = {}
        try:
            with self._session_factory() as session:
                offset = 0
                while True:
                    stmt = (
                        select(InvoiceTracking)
                        .where(InvoiceTracking.client_gstin_id == str(client_gstin_id))
                        .order_by(InvoiceTracking.id)
                        .offset(offset)
                        .limit(page_size)
                    )
                    rows = session.execute(stmt).scalars().all()
                    for row in rows:
                        key = (str(row.invoice_number), str(row.supplier_gstin))
                        index[key] = _model_to_dict(row)
                    if len(rows) < page_size:
                        break
                    offset += len(rows)
        except Exception as exc:
            _log.warning("Aurora bulk_fetch_invoice_tracking failed: %s", exc)
        return index

    def batch_upsert_invoice_tracking(
        self,
        rows: list[dict[str, Any]],
        *,
        conflict_col: str = "id",
    ) -> int:
        """Batch upsert invoice_tracking rows. Returns count of rows processed."""
        if not rows:
            return 0
        inserted = 0
        try:
            with self._session_factory() as session:
                for row in rows:
                    values = {k: v for k, v in row.items() if v is not None or k == "id"}
                    if "id" in values:
                        # Full upsert: update by primary key
                        obj = session.get(InvoiceTracking, str(values["id"]))
                        if obj:
                            for k, v in values.items():
                                setattr(obj, k, v)
                        else:
                            session.add(InvoiceTracking(**values))
                    else:
                        session.add(InvoiceTracking(**values))
                    inserted += 1
                session.commit()
        except Exception as exc:
            _log.warning("Aurora batch_upsert_invoice_tracking failed: %s", exc)
        return inserted

    def get_chronic_risks(
        self, client_gstin_id: UUID, *, threshold: int = 3
    ) -> list[dict[str, Any]]:
        """Return unresolved invoices with consecutive_unmatched_runs >= threshold."""
        try:
            with self._session_factory() as session:
                stmt = (
                    select(InvoiceTracking)
                    .where(InvoiceTracking.client_gstin_id == str(client_gstin_id))
                    .where(InvoiceTracking.is_resolved == False)  # noqa: E712
                    .where(InvoiceTracking.consecutive_unmatched_runs >= threshold)
                    .order_by(InvoiceTracking.consecutive_unmatched_runs.desc())
                )
                rows = session.execute(stmt).scalars().all()
                return [_model_to_dict(r) for r in rows]
        except Exception as exc:
            _log.warning("Aurora get_chronic_risks failed: %s", exc)
            return []

    def get_invoice_tracking_by_run(
        self, *, column: str, run_id: str
    ) -> list[dict[str, Any]]:
        """Fetch invoice_tracking rows where first_seen_run_id or last_seen_run_id = run_id."""
        try:
            with self._session_factory() as session:
                col_attr = getattr(InvoiceTracking, column)
                stmt = (
                    select(InvoiceTracking)
                    .where(col_attr == str(run_id))
                )
                rows = session.execute(stmt).scalars().all()
                return [_model_to_dict(r) for r in rows]
        except Exception as exc:
            _log.warning("Aurora get_invoice_tracking_by_run (col=%s) failed: %s", column, exc)
            return []

    def delete_invoice_tracking_by_id(self, tracking_id: str) -> bool:
        """Delete a single invoice_tracking row by primary key."""
        try:
            with self._session_factory() as session:
                stmt = delete(InvoiceTracking).where(InvoiceTracking.id == str(tracking_id))
                session.execute(stmt)
                session.commit()
                return True
        except Exception as exc:
            _log.warning("Aurora delete_invoice_tracking_by_id failed: %s", exc)
            return False

    def update_invoice_tracking_last_seen(self, tracking_id: str, last_seen_run_id: str) -> bool:
        """Re-point last_seen_run_id for an invoice_tracking row."""
        try:
            with self._session_factory() as session:
                stmt = (
                    update(InvoiceTracking)
                    .where(InvoiceTracking.id == str(tracking_id))
                    .values(last_seen_run_id=str(last_seen_run_id))
                )
                session.execute(stmt)
                session.commit()
                return True
        except Exception as exc:
            _log.warning("Aurora update_invoice_tracking_last_seen failed: %s", exc)
            return False

    def delete_invoice_tracking_by_run_col(self, column: str, run_id: str) -> int:
        """Delete all invoice_tracking rows where column = run_id."""
        try:
            with self._session_factory() as session:
                col_attr = getattr(InvoiceTracking, column)
                stmt = delete(InvoiceTracking).where(col_attr == str(run_id))
                result = session.execute(stmt)
                session.commit()
                return result.rowcount or 0
        except Exception as exc:
            _log.warning(
                "Aurora delete_invoice_tracking_by_run_col (col=%s) failed: %s", column, exc
            )
            return 0

    # -----------------------------------------------------------------------
    # rule37_actions
    # -----------------------------------------------------------------------

    def get_rule37_actions_for_run(
        self, run_id: str
    ) -> list[dict[str, Any]]:
        """Return all rule37_actions for a given run_id."""
        try:
            with self._session_factory() as session:
                stmt = (
                    select(Rule37Action)
                    .where(Rule37Action.run_id == str(run_id))
                )
                rows = session.execute(stmt).scalars().all()
                return [_model_to_dict(r) for r in rows]
        except Exception as exc:
            _log.warning("Aurora get_rule37_actions_for_run failed: %s", exc)
            return []

    def get_rule37_actions_for_client(
        self, client_gstin_id: str, *, columns: Optional[list[str]] = None
    ) -> list[dict[str, Any]]:
        """Return all rule37_actions for a client_gstin_id."""
        try:
            with self._session_factory() as session:
                stmt = (
                    select(Rule37Action)
                    .where(Rule37Action.client_gstin_id == str(client_gstin_id))
                )
                rows = session.execute(stmt).scalars().all()
                if columns:
                    return [{c: _model_to_dict(r).get(c) for c in columns} for r in rows]
                return [_model_to_dict(r) for r in rows]
        except Exception as exc:
            _log.warning("Aurora get_rule37_actions_for_client failed: %s", exc)
            return []

    def get_rule37_action_by_hash(
        self, run_id: str, record_hash: str
    ) -> Optional[dict[str, Any]]:
        """Fetch a single rule37_action by (run_id, record_hash)."""
        try:
            with self._session_factory() as session:
                stmt = (
                    select(Rule37Action)
                    .where(Rule37Action.run_id == str(run_id))
                    .where(Rule37Action.record_hash == str(record_hash))
                )
                obj = session.execute(stmt).scalars().first()
                return _model_to_dict(obj) if obj else None
        except Exception as exc:
            _log.warning("Aurora get_rule37_action_by_hash failed: %s", exc)
            return None

    def upsert_rule37_action(self, payload: dict[str, Any]) -> bool:
        """Delete-then-insert rule37_actions row (idempotent per run_id + record_hash)."""
        run_id = str(payload.get("run_id", ""))
        record_hash = str(payload.get("record_hash", ""))
        try:
            with self._session_factory() as session:
                # Delete existing
                session.execute(
                    delete(Rule37Action)
                    .where(Rule37Action.run_id == run_id)
                    .where(Rule37Action.record_hash == record_hash)
                )
                # Handle review_metadata JSON serialization for SQLite
                clean_payload = dict(payload)
                if isinstance(clean_payload.get("review_metadata"), dict):
                    dialect = session.bind.dialect.name if session.bind else "postgresql"
                    if "sqlite" in dialect:
                        clean_payload["review_metadata"] = json.dumps(
                            clean_payload["review_metadata"]
                        )
                # Insert fresh
                obj = Rule37Action(**clean_payload)
                session.add(obj)
                session.commit()
                return True
        except Exception as exc:
            _log.warning(
                "Aurora upsert_rule37_action failed run_id=%s hash=%s: %s",
                run_id, record_hash, exc,
            )
            return False

    def delete_rule37_actions_for_run(self, run_id: str) -> int:
        """Delete all rule37_actions for a run_id. Returns deleted count."""
        try:
            with self._session_factory() as session:
                result = session.execute(
                    delete(Rule37Action).where(Rule37Action.run_id == str(run_id))
                )
                session.commit()
                return result.rowcount or 0
        except Exception as exc:
            _log.warning("Aurora delete_rule37_actions_for_run failed: %s", exc)
            return 0

    # -----------------------------------------------------------------------
    # rule37_resolutions
    # -----------------------------------------------------------------------

    def count_rule37_resolutions_for_run(self, run_id: str) -> int:
        """Return count of rule37_resolutions for a run_id."""
        try:
            with self._session_factory() as session:
                from sqlalchemy import func
                stmt = (
                    select(func.count())
                    .select_from(Rule37Resolution)
                    .where(Rule37Resolution.run_id == str(run_id))
                )
                result = session.execute(stmt).scalar_one_or_none()
                return int(result or 0)
        except Exception as exc:
            _log.warning("Aurora count_rule37_resolutions_for_run failed: %s", exc)
            return 0

    def get_rule37_resolutions_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Return all rule37_resolutions for a run_id."""
        try:
            with self._session_factory() as session:
                stmt = (
                    select(Rule37Resolution)
                    .where(Rule37Resolution.run_id == str(run_id))
                )
                rows = session.execute(stmt).scalars().all()
                return [_model_to_dict(r) for r in rows]
        except Exception as exc:
            _log.warning("Aurora get_rule37_resolutions_for_run failed: %s", exc)
            return []

    # -----------------------------------------------------------------------
    # rule37_alert_dedup
    # -----------------------------------------------------------------------

    def load_rule37_dedup_map(
        self, client_gstin_id: str
    ) -> dict[str, dict[str, Any]]:
        """Return {invoice_key: row} for a client_gstin_id."""
        try:
            with self._session_factory() as session:
                stmt = (
                    select(Rule37AlertDedup)
                    .where(Rule37AlertDedup.client_gstin_id == str(client_gstin_id))
                )
                rows = session.execute(stmt).scalars().all()
                out: dict[str, dict[str, Any]] = {}
                for r in rows:
                    d = _model_to_dict(r)
                    key = str(d.get("invoice_key") or "")
                    if key:
                        out[key] = d
                return out
        except Exception as exc:
            _log.warning("Aurora load_rule37_dedup_map failed: %s", exc)
            return {}

    def upsert_rule37_dedup(
        self,
        *,
        firm_owner_id: str,
        client_gstin_id: str,
        invoice_key: str,
        tier: str,
        now: datetime,
    ) -> bool:
        """Upsert a rule37_alert_dedup row on (client_gstin_id, invoice_key)."""
        try:
            with self._session_factory() as session:
                sent_at = _parse_datetime(now) or datetime.now(timezone.utc)
                values = {
                    "firm_owner_id": str(firm_owner_id),
                    "client_gstin_id": str(client_gstin_id),
                    "invoice_key": str(invoice_key),
                    "last_alert_tier": str(tier),
                    "last_sent_at": sent_at,
                }
                stmt = _upsert_stmt(
                    session,
                    Rule37AlertDedup,
                    values,
                    ["client_gstin_id", "invoice_key"],
                )
                session.execute(stmt)
                session.commit()
                return True
        except Exception as exc:
            _log.warning("Aurora upsert_rule37_dedup failed key=%s: %s", invoice_key, exc)
            return False


# ---------------------------------------------------------------------------
# Module-level singleton factory (mirrors wizard.py pattern)
# ---------------------------------------------------------------------------

_compliance_repo: Optional[AuroraComplianceRepository] = None


def get_compliance_repository() -> Optional[AuroraComplianceRepository]:
    """Return the module-level AuroraComplianceRepository singleton.

    Returns None when Aurora is not configured (dev / test without Aurora URL).
    """
    global _compliance_repo
    if _compliance_repo is not None:
        return _compliance_repo
    try:
        from app.aurora import get_aurora_sessionmaker
        sf = get_aurora_sessionmaker()
        _compliance_repo = AuroraComplianceRepository(session_factory=sf)
        return _compliance_repo
    except Exception as exc:
        _log.debug("Aurora compliance repository unavailable: %s", exc)
        return None
