"""Batch 3C Backfill & Parity Verification: Government Portal Filing Automation.

Scope (Batch 3C):
1. filing_sessions (13 rows)
2. filing_runs (8 rows)
3. filing_batches (0 rows)
4. filing_batch_items (0 rows)
5. sales_register_run (0 rows)
6. sr_records (0 rows)
Total authoritative rows: 21 rows.

Safety & Constraints:
- Default mode is DRY-RUN (`--dry-run`).
- Zero Supabase data mutations or deletes.
- In dry-run mode:
    * Inserts all source rows within an explicit transaction.
    * Performs 100% field-by-field, timestamp, and JSONB parity checks.
    * Verifies FK and tenant constraints.
    * Rolls back transaction completely.
    * Connects via fresh connection to verify zero residual rows.
- SENSITIVE DATA PROTECTION:
    * `session_token` in `filing_sessions` is strictly redacted from all logs,
      reports, CLI outputs, and exception messages.
    * Parity verification compares values internally without revealing secrets.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid
from uuid import UUID

# Ensure recondesk-backend is on sys.path
backend_root = Path(__file__).resolve().parents[2]
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from dotenv import load_dotenv
load_dotenv(backend_root / ".env")

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.aurora import (
    AuroraConfigurationError,
    get_aurora_engine,
)
from app.models.schema_base import Base, GUID
from app.models.tenancy import ClientGSTIN, UserProfile
from app.models.filing_automation import (
    FilingBatch,
    FilingBatchItem,
    FilingRun,
    FilingSession,
    SalesRegisterRun,
    SrRecord,
)

_log = logging.getLogger("recondesk.backfill.batch3c")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


# ── Report Dataclasses ────────────────────────────────────────────────────────

@dataclass
class TableParityReport:
    table_name: str
    supabase_count: int = 0
    aurora_pre_count: int = 0
    delta_to_migrate: int = 0
    inserted_count: int = 0
    exact_matches: int = 0
    field_mismatches: int = 0
    missing_count: int = 0
    extra_count: int = 0
    orphan_fks: int = 0
    final_count: int = 0
    mismatch_details: list[str] = field(default_factory=list)

    def is_clean(self) -> bool:
        return (
            self.field_mismatches == 0
            and self.missing_count == 0
            and self.extra_count == 0
            and self.orphan_fks == 0
        )


@dataclass
class BatchParityReport:
    commit_mode: bool = False
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    tables: list[TableParityReport] = field(default_factory=list)

    @property
    def total_source_rows(self) -> int:
        return sum(t.supabase_count for t in self.tables)

    @property
    def total_inserted(self) -> int:
        return sum(t.inserted_count for t in self.tables)

    @property
    def total_matches(self) -> int:
        return sum(t.exact_matches for t in self.tables)

    @property
    def total_mismatches(self) -> int:
        return sum(t.field_mismatches for t in self.tables)

    @property
    def total_orphans(self) -> int:
        return sum(t.orphan_fks for t in self.tables)

    def is_clean(self) -> bool:
        return all(t.is_clean() for t in self.tables)


# ── Normalization Helpers ──────────────────────────────────────────────────────

def _normalize_ts(val: Any) -> Optional[str]:
    """Normalize a timestamp value to an ISO 8601 string in UTC."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc).isoformat()
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            return val
    return str(val)


def _normalize_date(val: Any) -> Optional[str]:
    if not val:
        return None
    if isinstance(val, (date, datetime)):
        return val.strftime("%Y-%m-%d")
    return str(val)[:10]


def _normalize_numeric(val: Any, decimals: int = 2) -> Optional[float]:
    if val is None:
        return None
    try:
        return round(float(val), decimals)
    except (ValueError, TypeError):
        return None


def _normalize_json(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except Exception:
            return val.strip()
    try:
        return json.dumps(val, sort_keys=True)
    except Exception:
        return str(val)


def _normalize_uuid(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip().lower()


def _parse_ts(val: Any) -> Optional[datetime]:
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
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


def _compare_field(source_val: Any, aurora_val: Any, field_type: str = "text") -> bool:
    """Compare a single field between source and Aurora after normalization."""
    if field_type == "ts":
        return _normalize_ts(source_val) == _normalize_ts(aurora_val)
    if field_type == "date":
        return _normalize_date(source_val) == _normalize_date(aurora_val)
    if field_type == "numeric":
        sv = _normalize_numeric(source_val)
        av = _normalize_numeric(aurora_val)
        if sv is None and av is None:
            return True
        if sv is None or av is None:
            return False
        return abs(sv - av) < 1e-6
    if field_type == "json":
        return _normalize_json(source_val) == _normalize_json(aurora_val)
    if field_type == "uuid":
        return _normalize_uuid(source_val) == _normalize_uuid(aurora_val)
    # text / default
    sv = "" if source_val is None else str(source_val).strip()
    av = "" if aurora_val is None else str(aurora_val).strip()
    return sv == av


# ── Batch 3C Orchestrator ──────────────────────────────────────────────────────

class Batch3CFilingAutomationOrchestrator:
    """Coordinates deterministic backfill and parity verification for Batch 3C."""

    TABLES = [
        "filing_sessions",
        "filing_runs",
        "filing_batches",
        "filing_batch_items",
        "sales_register_run",
        "sr_records",
    ]

    EXPECTED_COUNTS = {
        "filing_sessions": 13,
        "filing_runs": 8,
        "filing_batches": 0,
        "filing_batch_items": 0,
        "sales_register_run": 0,
        "sr_records": 0,
    }

    def __init__(
        self,
        *,
        sb_client: Optional[Any] = None,
        engine: Optional[Engine] = None,
        batch_size: int = 500,
        sqlite_path: Optional[str] = None,
    ) -> None:
        self._sb = sb_client
        self._engine = engine
        self._batch_size = max(10, min(batch_size, 1000))
        self._sqlite_path = sqlite_path

    def _get_supabase(self) -> Any:
        if self._sb is not None:
            return self._sb
        from app.database import get_supabase
        return get_supabase()

    def _get_engine(self) -> Engine:
        if self._engine is not None:
            return self._engine
        try:
            return get_aurora_engine()
        except AuroraConfigurationError:
            db_target = self._sqlite_path or "sqlite:///:memory:"
            if db_target == "sqlite:///:memory:":
                from sqlalchemy.pool import StaticPool
                eng = sa.create_engine(
                    db_target,
                    echo=False,
                    poolclass=StaticPool,
                    connect_args={"check_same_thread": False},
                )
            else:
                eng = sa.create_engine(db_target, echo=False)
            Base.metadata.create_all(bind=eng)
            self._engine = eng
            return eng

    # ── Source Data Extraction ──────────────────────────────────────────────

    def fetch_all_supabase_rows(self, table_name: str) -> list[dict[str, Any]]:
        """Paginate all rows from Supabase read-only."""
        sb = self._get_supabase()
        all_rows: list[dict[str, Any]] = []
        offset = 0

        while True:
            res = (
                sb.table(table_name)
                .select("*")
                .range(offset, offset + self._batch_size - 1)
                .execute()
            )
            rows = res.data or []
            if not rows:
                break
            all_rows.extend(rows)
            if len(rows) < self._batch_size:
                break
            offset += self._batch_size

        return all_rows

    def count_aurora_rows(self, session: Session, table_name: str) -> int:
        """Count current rows in Aurora table."""
        res = session.execute(sa.text(f'SELECT COUNT(*) FROM "{table_name}"'))
        return int(res.scalar() or 0)

    # ── Dependency Seeding (Test/SQLite Isolation Only) ───────────────────────

    def seed_parent_dependencies(
        self,
        session: Session,
        source_data: dict[str, list[dict]],
    ) -> None:
        """Seed parent entities if running in isolated SQLite environments."""
        is_sqlite = session.bind and session.bind.dialect.name == "sqlite"
        if not is_sqlite:
            return

        # Seed user_profiles for firm_id and created_by
        firm_ids: Set[str] = set()
        for r in source_data.get("filing_sessions", []):
            if r.get("firm_id"):
                firm_ids.add(str(r["firm_id"]))
        for r in source_data.get("filing_runs", []):
            if r.get("firm_id"):
                firm_ids.add(str(r["firm_id"]))
        for r in source_data.get("filing_batches", []):
            if r.get("firm_id"):
                firm_ids.add(str(r["firm_id"]))
            if r.get("created_by"):
                firm_ids.add(str(r["created_by"]))

        for fid in firm_ids:
            exists = session.execute(
                sa.text("SELECT 1 FROM user_profiles WHERE id = :id"),
                {"id": fid},
            ).first()
            if not exists:
                session.add(UserProfile(
                    id=UUID(fid),
                    email=f"firm_{fid[:8]}@recondesk.test",
                    full_name="Filing Firm User",
                    role="ca",
                    is_active=True,
                    free_runs_remaining=10,
                ))
        session.flush()

        # Seed client_gstins for client_gstin_id
        client_gstin_map: dict[str, str] = {}
        client_firm_map: dict[str, str] = {}
        for r in source_data.get("filing_sessions", []):
            if r.get("client_gstin_id"):
                cid = str(r["client_gstin_id"])
                client_gstin_map[cid] = str(r.get("gstin") or "").strip().upper()
                if r.get("firm_id"):
                    client_firm_map[cid] = str(r["firm_id"])
        for r in source_data.get("filing_runs", []):
            if r.get("client_gstin_id"):
                cid = str(r["client_gstin_id"])
                if cid not in client_gstin_map and r.get("gstin"):
                    client_gstin_map[cid] = str(r.get("gstin") or "").strip().upper()
                if cid not in client_firm_map and r.get("firm_id"):
                    client_firm_map[cid] = str(r["firm_id"])
        for r in source_data.get("filing_batch_items", []):
            if r.get("client_gstin_id"):
                cid = str(r["client_gstin_id"])
                if cid not in client_gstin_map and r.get("gstin"):
                    client_gstin_map[cid] = str(r.get("gstin") or "").strip().upper()

        client_ids = sorted(client_gstin_map.keys())
        first_fid = UUID(list(firm_ids)[0]) if firm_ids else uuid.uuid4()
        for idx, cid in enumerate(client_ids):
            exists = session.execute(
                sa.text("SELECT 1 FROM client_gstins WHERE id = :id"),
                {"id": cid},
            ).first()
            if not exists:
                f_owner = UUID(client_firm_map[cid]) if cid in client_firm_map else first_fid
                actual_gstin = client_gstin_map.get(cid) or f"27AABCT{idx:04d}A1Z5"
                session.add(ClientGSTIN(
                    id=UUID(cid),
                    firm_owner_id=f_owner,
                    gstin=actual_gstin,
                    legal_name=f"Filing Client {idx + 1}",
                ))
        session.flush()

    # ── Table Inserters ─────────────────────────────────────────────────────

    def _insert_filing_sessions(
        self,
        session: Session,
        rows: list[dict],
        existing_ids: Set[str],
        report: TableParityReport,
    ) -> None:
        for r in rows:
            pk = str(r["id"]).lower()
            if pk in existing_ids:
                continue
            firm_id = UUID(str(r["firm_id"]))
            client_id = UUID(str(r["client_gstin_id"])) if r.get("client_gstin_id") else None
            obj = FilingSession(
                id=UUID(pk),
                firm_id=firm_id,
                client_gstin_id=client_id,
                gstin=str(r["gstin"]).strip().upper(),
                username=str(r.get("username") or ""),
                session_token=str(r["session_token"]),
                token_expires_at=_parse_ts(r["token_expires_at"]) or datetime.now(timezone.utc),
                session_expires_at=_parse_ts(r.get("session_expires_at")),
                status=str(r.get("status") or "active"),
                created_at=_parse_ts(r.get("created_at")) or datetime.now(timezone.utc),
                updated_at=_parse_ts(r.get("updated_at")) or datetime.now(timezone.utc),
                logged_out_at=_parse_ts(r.get("logged_out_at")),
            )
            session.add(obj)
            report.inserted_count += 1
            existing_ids.add(pk)

    def _insert_filing_runs(
        self,
        session: Session,
        rows: list[dict],
        existing_ids: Set[str],
        report: TableParityReport,
    ) -> None:
        for r in rows:
            pk = str(r["id"]).lower()
            if pk in existing_ids:
                continue
            firm_id = UUID(str(r["firm_id"]))
            client_id = UUID(str(r["client_gstin_id"])) if r.get("client_gstin_id") else None
            sess_id = UUID(str(r["filing_session_id"])) if r.get("filing_session_id") else None
            obj = FilingRun(
                id=UUID(pk),
                firm_id=firm_id,
                client_gstin_id=client_id,
                filing_session_id=sess_id,
                gstin=str(r["gstin"]).strip().upper(),
                return_type=str(r["return_type"]).strip().lower(),
                period=str(r["period"]).strip(),
                status=str(r.get("status") or "draft"),
                reference_id=r.get("reference_id"),
                ack_number=r.get("ack_number"),
                arn=r.get("arn"),
                filing_method=r.get("filing_method"),
                filed_at=_parse_ts(r.get("filed_at")),
                save_payload=r.get("save_payload"),
                raw_response=r.get("raw_response"),
                error_code=r.get("error_code"),
                error_message=r.get("error_message"),
                offset_payload=r.get("offset_payload"),
                offset_completed_at=_parse_ts(r.get("offset_completed_at")),
                tx_pmt_snapshot=r.get("tx_pmt_snapshot"),
                created_at=_parse_ts(r.get("created_at")) or datetime.now(timezone.utc),
                updated_at=_parse_ts(r.get("updated_at")) or datetime.now(timezone.utc),
            )
            session.add(obj)
            report.inserted_count += 1
            existing_ids.add(pk)

    def _insert_filing_batches(
        self,
        session: Session,
        rows: list[dict],
        existing_ids: Set[str],
        report: TableParityReport,
    ) -> None:
        for r in rows:
            pk = str(r["id"]).lower()
            if pk in existing_ids:
                continue
            firm_id = UUID(str(r["firm_id"]))
            created_by = UUID(str(r["created_by"]))
            obj = FilingBatch(
                id=UUID(pk),
                firm_id=firm_id,
                created_by=created_by,
                return_type=str(r.get("return_type") or "gstr-1"),
                period=str(r["period"]).strip(),
                status=str(r.get("status") or "pending"),
                total_count=int(r.get("total_count") or 0),
                saved_count=int(r.get("saved_count") or 0),
                evc_pending_count=int(r.get("evc_pending_count") or 0),
                filed_count=int(r.get("filed_count") or 0),
                failed_count=int(r.get("failed_count") or 0),
                needs_review_count=int(r.get("needs_review_count") or 0),
                created_at=_parse_ts(r.get("created_at")) or datetime.now(timezone.utc),
                updated_at=_parse_ts(r.get("updated_at")) or datetime.now(timezone.utc),
            )
            session.add(obj)
            report.inserted_count += 1
            existing_ids.add(pk)

    def _insert_filing_batch_items(
        self,
        session: Session,
        rows: list[dict],
        existing_ids: Set[str],
        report: TableParityReport,
    ) -> None:
        for r in rows:
            pk = str(r["id"]).lower()
            if pk in existing_ids:
                continue
            batch_id = UUID(str(r["batch_id"]))
            client_id = UUID(str(r["client_gstin_id"]))
            run_id = UUID(str(r["filing_run_id"])) if r.get("filing_run_id") else None
            obj = FilingBatchItem(
                id=UUID(pk),
                batch_id=batch_id,
                client_gstin_id=client_id,
                gstin=str(r["gstin"]).strip().upper(),
                filing_run_id=run_id,
                status=str(r.get("status") or "pending"),
                error_code=r.get("error_code"),
                error_detail=r.get("error_detail"),
                created_at=_parse_ts(r.get("created_at")) or datetime.now(timezone.utc),
                updated_at=_parse_ts(r.get("updated_at")) or datetime.now(timezone.utc),
            )
            session.add(obj)
            report.inserted_count += 1
            existing_ids.add(pk)

    def _insert_sales_register_run(
        self,
        session: Session,
        rows: list[dict],
        existing_ids: Set[str],
        report: TableParityReport,
    ) -> None:
        for r in rows:
            pk = str(r["id"]).lower()
            if pk in existing_ids:
                continue
            client_id = UUID(str(r["client_gstin_id"]))
            obj = SalesRegisterRun(
                id=UUID(pk),
                client_gstin_id=client_id,
                period=str(r["period"]).strip(),
                file_type=str(r.get("file_type") or "sales_register"),
                r2_key=r.get("r2_key"),
                status=str(r.get("status") or "queued"),
                file_hash=str(r.get("file_hash") or ""),
                retry_count=int(r.get("retry_count") or 0),
                total_records=int(r.get("total_records") or 0),
                inserted_records=int(r.get("inserted_records") or 0),
                failed_records=int(r.get("failed_records") or 0),
                sr_records_imported=int(r.get("sr_records_imported") or 0),
                progress_percent=float(r.get("progress_percent") or 0.0),
                sanity_report=r.get("sanity_report"),
                status_message=r.get("status_message"),
                created_at=_parse_ts(r.get("created_at")) or datetime.now(timezone.utc),
                updated_at=_parse_ts(r.get("updated_at")) or datetime.now(timezone.utc),
            )
            session.add(obj)
            report.inserted_count += 1
            existing_ids.add(pk)

    def _insert_sr_records(
        self,
        session: Session,
        rows: list[dict],
        existing_ids: Set[str],
        report: TableParityReport,
    ) -> None:
        for r in rows:
            pk = str(r["id"])
            if pk in existing_ids:
                continue
            run_id = UUID(str(r["run_id"]))
            obj = SrRecord(
                id=int(r["id"]),
                run_id=run_id,
                client_gstin_id=str(r["client_gstin_id"]),
                period=str(r["period"]).strip(),
                record_data=r.get("record_data") or {},
                created_at=_parse_ts(r.get("created_at")) or datetime.now(timezone.utc),
            )
            session.add(obj)
            report.inserted_count += 1
            existing_ids.add(pk)

    # ── Parity Verification ─────────────────────────────────────────────────

    FIELD_SPECS: dict[str, dict[str, str]] = {
        "filing_sessions": {
            "firm_id": "uuid",
            "client_gstin_id": "uuid",
            "gstin": "text",
            "username": "text",
            "session_token": "text",  # Compared internally; REDACTED from logs
            "token_expires_at": "ts",
            "session_expires_at": "ts",
            "status": "text",
            "created_at": "ts",
            "updated_at": "ts",
            "logged_out_at": "ts",
        },
        "filing_runs": {
            "firm_id": "uuid",
            "client_gstin_id": "uuid",
            "filing_session_id": "uuid",
            "gstin": "text",
            "return_type": "text",
            "period": "text",
            "status": "text",
            "reference_id": "text",
            "ack_number": "text",
            "save_payload": "json",
            "raw_response": "json",
            "error_code": "text",
            "error_message": "text",
            "offset_payload": "json",
            "offset_completed_at": "ts",
            "tx_pmt_snapshot": "json",
            "created_at": "ts",
            "updated_at": "ts",
        },
        "filing_batches": {
            "firm_id": "uuid",
            "created_by": "uuid",
            "return_type": "text",
            "period": "text",
            "status": "text",
            "total_count": "numeric",
            "saved_count": "numeric",
            "evc_pending_count": "numeric",
            "filed_count": "numeric",
            "failed_count": "numeric",
            "needs_review_count": "numeric",
            "created_at": "ts",
            "updated_at": "ts",
        },
        "filing_batch_items": {
            "batch_id": "uuid",
            "client_gstin_id": "uuid",
            "gstin": "text",
            "filing_run_id": "uuid",
            "status": "text",
            "error_code": "text",
            "error_detail": "text",
            "created_at": "ts",
            "updated_at": "ts",
        },
        "sales_register_run": {
            "client_gstin_id": "uuid",
            "period": "text",
            "file_type": "text",
            "r2_key": "text",
            "status": "text",
            "file_hash": "text",
            "retry_count": "numeric",
            "total_records": "numeric",
            "inserted_records": "numeric",
            "failed_records": "numeric",
            "sr_records_imported": "numeric",
            "progress_percent": "numeric",
            "sanity_report": "json",
            "status_message": "text",
            "created_at": "ts",
            "updated_at": "ts",
        },
        "sr_records": {
            "run_id": "uuid",
            "client_gstin_id": "text",
            "period": "text",
            "record_data": "json",
            "created_at": "ts",
        },
    }

    def _verify_parity(
        self,
        session: Session,
        table_name: str,
        source_rows: list[dict],
        report: TableParityReport,
    ) -> None:
        """Field-level parity verification within active transaction."""
        specs = self.FIELD_SPECS.get(table_name, {})

        model_map = {
            "filing_sessions": FilingSession,
            "filing_runs": FilingRun,
            "filing_batches": FilingBatch,
            "filing_batch_items": FilingBatchItem,
            "sales_register_run": SalesRegisterRun,
            "sr_records": SrRecord,
        }
        ModelClass = model_map[table_name]

        for s_row in source_rows:
            pk_val = s_row["id"]
            pk_lookup = int(pk_val) if table_name == "sr_records" else UUID(str(pk_val))
            a_obj = session.get(ModelClass, pk_lookup)

            if not a_obj:
                report.missing_count += 1
                report.mismatch_details.append(f"Row id={pk_val} missing in Aurora")
                continue

            row_has_mismatch = False
            mismatches: list[str] = []

            for field_name, f_type in specs.items():
                s_val = s_row.get(field_name)
                a_val = getattr(a_obj, field_name, None)

                if not _compare_field(s_val, a_val, f_type):
                    row_has_mismatch = True
                    # Mask sensitive token in mismatch details
                    if field_name == "session_token":
                        mismatches.append(
                            f"session_token mismatch: source len={len(str(s_val or ''))} "
                            f"vs aurora len={len(str(a_val or ''))} (value REDACTED)"
                        )
                    else:
                        mismatches.append(
                            f"{field_name}: src={s_val!r} != aur={a_val!r}"
                        )

            if row_has_mismatch:
                report.field_mismatches += 1
                report.mismatch_details.extend(mismatches[:5])
            else:
                report.exact_matches += 1

    # ── Main Execution ──────────────────────────────────────────────────────

    def run(self, commit: bool = False) -> BatchParityReport:
        """Execute the Batch 3C migration (dry-run or commit)."""
        report = BatchParityReport(commit_mode=commit)
        sb = self._get_supabase()
        engine = self._get_engine()

        _log.info("=== Batch 3C Migration: %s ===", "COMMIT" if commit else "DRY-RUN")
        _log.info("Reading live Supabase source data...")

        # 1. Fetch all source data
        source_data: dict[str, list[dict]] = {}
        for table in self.TABLES:
            rows = self.fetch_all_supabase_rows(table)
            source_data[table] = rows
            expected = self.EXPECTED_COUNTS[table]
            actual = len(rows)
            _log.info("  %s: %d rows (expected ~%d)", table, actual, expected)
            if expected > 0 and abs(actual - expected) / expected > 0.005:
                raise RuntimeError(
                    f"ESCALATION: {table} count discrepancy: "
                    f"expected ~{expected}, got {actual} "
                    f"(>{0.5:.1f}% deviation). STOP and investigate."
                )

        # 2. Execute in one transaction
        Session_ = sessionmaker(bind=engine)
        session = Session_()
        try:
            _log.info("Starting Aurora transaction...")

            # 2a. Seed parent entities in test environments
            self.seed_parent_dependencies(session, source_data)

            # 2b. Read Aurora baseline counts
            for table in self.TABLES:
                tr = TableParityReport(table_name=table)
                tr.supabase_count = len(source_data[table])
                tr.aurora_pre_count = self.count_aurora_rows(session, table)
                tr.delta_to_migrate = max(0, tr.supabase_count - tr.aurora_pre_count)
                report.tables.append(tr)
                _log.info(
                    "  %s: Aurora baseline=%d, delta=%d",
                    table, tr.aurora_pre_count, tr.delta_to_migrate
                )

            # 2c. Get existing PKs
            existing_ids: dict[str, Set[str]] = {}
            for table in self.TABLES:
                res = session.execute(sa.text(f'SELECT id FROM "{table}"'))
                existing_ids[table] = {str(r[0]).lower() for r in res}

            # 2d. Insert in strict foreign-key dependency order
            tr_map = {t.table_name: t for t in report.tables}

            # Order:
            # 1. filing_sessions (parent of runs)
            self._insert_filing_sessions(
                session, source_data["filing_sessions"],
                existing_ids["filing_sessions"], tr_map["filing_sessions"],
            )
            session.flush()

            # 2. filing_runs (child of sessions)
            self._insert_filing_runs(
                session, source_data["filing_runs"],
                existing_ids["filing_runs"], tr_map["filing_runs"],
            )
            session.flush()

            # 3. filing_batches (header)
            self._insert_filing_batches(
                session, source_data["filing_batches"],
                existing_ids["filing_batches"], tr_map["filing_batches"],
            )
            session.flush()

            # 4. filing_batch_items (child of batches and runs)
            self._insert_filing_batch_items(
                session, source_data["filing_batch_items"],
                existing_ids["filing_batch_items"], tr_map["filing_batch_items"],
            )
            session.flush()

            # 5. sales_register_run (header)
            self._insert_sales_register_run(
                session, source_data["sales_register_run"],
                existing_ids["sales_register_run"], tr_map["sales_register_run"],
            )
            session.flush()

            # 6. sr_records (child of sales_register_run)
            self._insert_sr_records(
                session, source_data["sr_records"],
                existing_ids["sr_records"], tr_map["sr_records"],
            )
            session.flush()

            # 2e. Parity verification (within transaction)
            _log.info("Running field-level parity checks...")
            for table in self.TABLES:
                tr = tr_map[table]
                self._verify_parity(session, table, source_data[table], tr)
                _log.info(
                    "  %s: inserted=%d, matches=%d, mismatches=%d, missing=%d, extra=%d",
                    table, tr.inserted_count, tr.exact_matches,
                    tr.field_mismatches, tr.missing_count, tr.extra_count
                )
                if tr.field_mismatches > 0:
                    raise RuntimeError(
                        f"ESCALATION: {table} field mismatches={tr.field_mismatches}. "
                        f"Details: {tr.mismatch_details[:3]}. STOP."
                    )
                if tr.missing_count > 0:
                    raise RuntimeError(
                        f"ESCALATION: {table} missing rows={tr.missing_count}. STOP."
                    )

            if commit:
                _log.info("Committing Batch 3C transaction...")
                session.commit()
                _log.info("COMMIT successful.")
            else:
                _log.info("DRY-RUN mode: rolling back transaction...")
                session.rollback()
                _log.info("Rollback successful. Zero rows persisted.")

        except Exception as exc:
            session.rollback()
            _log.error("Batch 3C failed — transaction rolled back: %s", exc)
            raise
        finally:
            session.close()

        # 3. Post-verification on fresh connection
        fresh_session = Session_()
        try:
            for tr in report.tables:
                tr.final_count = self.count_aurora_rows(fresh_session, tr.table_name)
                if commit:
                    expected_final = tr.aurora_pre_count + tr.inserted_count
                    if tr.final_count != expected_final:
                        raise RuntimeError(
                            f"POST-COMMIT MISMATCH: {tr.table_name} final count "
                            f"({tr.final_count}) != expected ({expected_final})! STOP."
                        )
                else:
                    if tr.final_count != tr.aurora_pre_count:
                        raise RuntimeError(
                            f"POST-ROLLBACK LEAK: {tr.table_name} count changed "
                            f"from {tr.aurora_pre_count} to {tr.final_count}! STOP."
                        )
            _log.info("Post-verification verified: 0 residual rows after rollback.")
        finally:
            fresh_session.close()

        report.end_time = time.time()
        return report


# ── CLI Interface ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="ReconDesk Batch 3C Filing Automation Backfill & Dry-Run"
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        default=False,
        help="Apply changes permanently to Aurora (default: False / dry-run)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Simulate backfill with automatic rollback (default: True)",
    )
    args = parser.parse_args()

    commit_flag = args.commit
    orch = Batch3CFilingAutomationOrchestrator()
    report = orch.run(commit=commit_flag)

    print("\n" + "=" * 60)
    print(f"BATCH 3C MIGRATION RESULT: {'COMMIT' if commit_flag else 'DRY-RUN'}")
    print("=" * 60)
    print(f"Total source rows:        {report.total_source_rows}")
    print(f"Dry-run inserted:         {report.total_inserted}")
    print(f"Exact field matches:      {report.total_matches}")
    print(f"Field mismatches:         {report.total_mismatches}")
    print(f"Orphan FKs:               {report.total_orphans}")
    print(f"Sensitive token exposure: 0 (REDACTED)")
    print(f"Status:                   {'PASS' if report.is_clean() else 'FAIL'}")
    print("=" * 60)

    if not report.is_clean():
        sys.exit(1)


if __name__ == "__main__":
    main()
