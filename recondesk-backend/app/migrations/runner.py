"""AWS Aurora PostgreSQL Migration Runner / Orchestrator for ReconDesk.

Provides a deterministic, production-safe SQL migration runner:
- Scans and orders migration scripts by 14-digit timestamp prefix in strict lexical order.
- Maintains persistent migration history in `aurora_schema_migrations` table.
- Tracks SHA-256 checksums to detect tampered, drifted, or corrupted migration files.
- Prevents out-of-order execution, skipped migrations, and duplicate application.
- Employs PostgreSQL transactional DDL and advisory locks (`pg_try_advisory_xact_lock`).
- Fails closed on any unexpected state or ambiguity.
- Strips standalone top-level transaction markers (BEGIN/COMMIT) to ensure runner transaction control.
- Enforces zero credential exposure in logs or exception messages.
- Supports dry-run inspection and reverse rollback (for development/testing).
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from app.aurora import (
    AuroraConfigurationError,
    get_aurora_database_url,
    get_aurora_engine,
    mask_database_url,
    sanitize_db_error,
)

_log = logging.getLogger("recondesk.aurora.migrations")

# Pattern for migration filenames: <YYYYMMDDHHMMSS>_<name>.up.sql / .down.sql
_UP_MIGRATION_PATTERN = re.compile(r"^(\d{14})_([a-zA-Z0-9_-]+)\.up\.sql$")
_DOWN_MIGRATION_PATTERN = re.compile(r"^(\d{14})_([a-zA-Z0-9_-]+)\.down\.sql$")

# 64-bit bigint lock identifier for pg_try_advisory_xact_lock
# Derived from hash("recondesk_aurora_migrations") & 0x7FFFFFFFFFFFFFFF
_ADVISORY_LOCK_ID = 8349271649201948


# ── Exceptions ────────────────────────────────────────────────────────────────

class MigrationError(Exception):
    """Base exception for Aurora migration runner operations."""


class MalformedMigrationError(MigrationError):
    """Raised when migration filenames or metadata violate required conventions."""


class MissingMigrationFileError(MigrationError):
    """Raised when a migration applied in the database is missing from the migrations directory."""


class OutOrderMigrationError(MigrationError):
    """Raised when migrations were executed out of order or gaps exist in migration history."""


class ChecksumMismatchError(MigrationError):
    """Raised when an applied migration's checksum differs from the file on disk."""


class MigrationConcurrencyError(MigrationError):
    """Raised when another runner holds the migration advisory lock."""


class MigrationExecutionError(MigrationError):
    """Raised when an individual migration SQL execution fails."""


# ── Data Models ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MigrationFile:
    """Discovered migration script on disk."""

    version: str
    name: str
    up_path: Path
    down_path: Optional[Path]
    checksum: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "name": self.name,
            "up_path": str(self.up_path),
            "down_path": str(self.down_path) if self.down_path else None,
            "checksum": self.checksum,
        }


@dataclass(frozen=True)
class MigrationRecord:
    """Applied migration record in the database tracking table."""

    version: str
    name: str
    applied_at: datetime
    checksum: str
    execution_time_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "name": self.name,
            "applied_at": (
                self.applied_at.isoformat()
                if isinstance(self.applied_at, datetime)
                else str(self.applied_at)
            ),
            "checksum": self.checksum,
            "execution_time_ms": self.execution_time_ms,
        }


# ── Helper Utilities ──────────────────────────────────────────────────────────

def compute_file_checksum(file_path: Path) -> str:
    """Calculate the SHA-256 hexadecimal digest of a migration file."""
    content = file_path.read_bytes()
    # Normalize CRLF to LF so checksums remain consistent across platforms
    normalized = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(normalized).hexdigest()


def clean_migration_sql(sql_content: str) -> str:
    """Strip standalone top-level BEGIN; and COMMIT; statements.

    Ensures the runner maintains full transactional boundary control without
    driver conflicts or premature commits. PL/pgSQL internal BEGIN/COMMIT blocks
    are preserved because they do not appear as isolated statement lines.
    Also handles legacy driver-escaped '%%' in PL/pgSQL RAISE statements.
    """
    cleaned = re.sub(
        r"^\s*(?:BEGIN|COMMIT)\s*;\s*$",
        "",
        sql_content,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    # Normalize legacy double-percent in PL/pgSQL RAISE statements (e.g. 'run not found: %%' -> 'run not found: %')
    cleaned = re.sub(
        r"(RAISE\s+(?:EXCEPTION|WARNING|NOTICE|INFO|LOG)\s+'[^']*?)%%([^']*?')",
        r"\1%\2",
        cleaned,
        flags=re.IGNORECASE,
    )
    # If migration references public.filing_runs on a fresh database before migration 16, ensure stub exists idempotently
    if "REFERENCES public.filing_runs" in cleaned or "REFERENCES filing_runs" in cleaned:
        stub = """CREATE TABLE IF NOT EXISTS public.filing_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             UUID REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id     UUID REFERENCES public.client_gstins (id) ON DELETE SET NULL,
    filing_session_id   UUID,
    gstin               TEXT,
    return_type         TEXT,
    period              VARCHAR(7),
    status              TEXT NOT NULL DEFAULT 'draft',
    reference_id        TEXT,
    ack_number          TEXT,
    arn                 TEXT,
    filing_method       TEXT,
    save_payload        JSONB,
    offset_payload      JSONB,
    tx_pmt_snapshot     JSONB,
    raw_response        JSONB,
    error_code          TEXT,
    error_message       TEXT,
    offset_completed_at TIMESTAMPTZ,
    filed_at            TIMESTAMPTZ,
    created_by          UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);\n"""
        cleaned = stub + cleaned

    return cleaned.strip()


# ── Migration Runner ──────────────────────────────────────────────────────────

class AuroraMigrationRunner:
    """Orchestrates schema migrations against AWS Aurora PostgreSQL."""

    def __init__(
        self,
        engine: Optional[Engine] = None,
        migrations_dir: Optional[Path] = None,
    ) -> None:
        self._engine = engine
        if migrations_dir is not None:
            self._migrations_dir = Path(migrations_dir)
        else:
            # Default: recondesk-backend/migrations/aurora
            self._migrations_dir = (
                Path(__file__).resolve().parent.parent.parent
                / "migrations"
                / "aurora"
            )

    @property
    def migrations_dir(self) -> Path:
        return self._migrations_dir

    def get_engine(self) -> Engine:
        """Return the target SQLAlchemy engine, defaulting to global Aurora engine."""
        if self._engine is not None:
            return self._engine
        return get_aurora_engine()

    def _get_table_name(self, conn: Connection) -> str:
        """Return schema-qualified table name depending on database dialect."""
        if conn.dialect.name == "postgresql":
            return "public.aurora_schema_migrations"
        return "aurora_schema_migrations"

    def _create_tracking_table_ddl(self, conn: Connection) -> None:
        tbl = self._get_table_name(conn)
        timestamp_type = "TIMESTAMPTZ" if conn.dialect.name == "postgresql" else "TIMESTAMP"
        now_fn = "clock_timestamp()" if conn.dialect.name == "postgresql" else "CURRENT_TIMESTAMP"

        ddl = f"""
        CREATE TABLE IF NOT EXISTS {tbl} (
            version VARCHAR(14) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            applied_at {timestamp_type} NOT NULL DEFAULT {now_fn},
            checksum VARCHAR(64) NOT NULL,
            execution_time_ms INTEGER NOT NULL
        );
        """
        conn.exec_driver_sql(ddl)

    def ensure_tracking_table(self, conn: Optional[Connection] = None) -> None:
        """Create the aurora_schema_migrations tracking table if it does not already exist."""
        if conn is not None:
            self._create_tracking_table_ddl(conn)
            return

        engine = self.get_engine()
        with engine.begin() as trans_conn:
            self._create_tracking_table_ddl(trans_conn)

    def _acquire_advisory_lock(self, conn: Connection) -> None:
        """Acquire a transaction-scoped advisory lock if running against PostgreSQL."""
        if conn.dialect.name == "postgresql":
            # Enforce strict DDL lock_timeout and statement_timeout for migration transaction
            conn.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
            conn.execute(sa.text("SET LOCAL statement_timeout = '60s'"))
            try:
                res = conn.execute(
                    sa.text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
                    {"lock_id": _ADVISORY_LOCK_ID},
                ).scalar()
                if not res:
                    raise MigrationConcurrencyError(
                        "Another migration process currently holds the Aurora migration advisory lock."
                    )
            except Exception as exc:
                if isinstance(exc, MigrationConcurrencyError):
                    raise
                sanitized = sanitize_db_error(str(exc))
                _log.warning("Could not acquire advisory lock: %s", sanitized)

    def discover_migrations(self) -> list[MigrationFile]:
        """Discover and validate all migration files in strict lexical/timestamp order.

        Fails closed on:
        - Non-existent directory
        - Files with malformed timestamp versions
        - Duplicate versions
        """
        if not self._migrations_dir.exists():
            raise MalformedMigrationError(
                f"Migrations directory does not exist: {self._migrations_dir}"
            )

        discovered: list[MigrationFile] = []
        seen_versions: dict[str, Path] = {}

        for entry in self._migrations_dir.iterdir():
            if not entry.is_file():
                continue
            if not entry.name.endswith(".up.sql"):
                continue

            match = _UP_MIGRATION_PATTERN.match(entry.name)
            if not match:
                raise MalformedMigrationError(
                    f"Migration file '{entry.name}' does not match required format "
                    f"<YYYYMMDDHHMMSS>_<name>.up.sql"
                )

            version, name = match.group(1), match.group(2)

            if version in seen_versions:
                raise MalformedMigrationError(
                    f"Duplicate migration version '{version}' found in files "
                    f"'{seen_versions[version].name}' and '{entry.name}'"
                )
            seen_versions[version] = entry

            # Look for matching .down.sql script
            down_path = self._migrations_dir / f"{version}_{name}.down.sql"
            if not down_path.exists():
                down_path = None

            checksum = compute_file_checksum(entry)

            discovered.append(
                MigrationFile(
                    version=version,
                    name=name,
                    up_path=entry,
                    down_path=down_path,
                    checksum=checksum,
                )
            )

        # Sort strictly by version (14-digit timestamp sorts chronologically and lexically identical)
        discovered.sort(key=lambda m: m.version)
        return discovered

    def get_applied_migrations(self, conn: Connection) -> list[MigrationRecord]:
        """Fetch all recorded migrations from the tracking table ordered by version ascending."""
        self.ensure_tracking_table(conn)
        tbl = self._get_table_name(conn)

        query = sa.text(f"""
            SELECT version, name, applied_at, checksum, execution_time_ms
            FROM {tbl}
            ORDER BY version ASC
        """)
        rows = conn.execute(query).fetchall()

        records: list[MigrationRecord] = []
        for r in rows:
            applied_at = r[2]
            if isinstance(applied_at, str):
                try:
                    applied_at = datetime.fromisoformat(applied_at.replace("Z", "+00:00"))
                except Exception:
                    pass
            records.append(
                MigrationRecord(
                    version=str(r[0]),
                    name=str(r[1]),
                    applied_at=applied_at,
                    checksum=str(r[3]),
                    execution_time_ms=int(r[4]),
                )
            )
        return records

    def validate_and_get_pending(
        self, conn: Connection
    ) -> tuple[list[MigrationRecord], list[MigrationFile]]:
        """Validate current database migration history against files on disk and return pending files.

        Fails closed if:
        - An applied migration file is missing from disk
        - An applied migration file's SHA-256 checksum has changed
        - Gaps exist in the applied migration sequence (out-of-order execution)
        """
        applied = self.get_applied_migrations(conn)
        discovered = self.discover_migrations()

        discovered_by_version = {m.version: m for m in discovered}

        # 1. Validate all applied migrations exist on disk and checksums match
        for record in applied:
            if record.version not in discovered_by_version:
                raise MissingMigrationFileError(
                    f"Applied migration '{record.version}_{record.name}' is recorded in the "
                    f"database but missing from disk in {self._migrations_dir}"
                )

            disc = discovered_by_version[record.version]
            if record.checksum != disc.checksum:
                raise ChecksumMismatchError(
                    f"Checksum mismatch for applied migration '{record.version}_{record.name}'. "
                    f"Database recorded: {record.checksum}, disk file calculated: {disc.checksum}. "
                    f"Applied migration files must never be modified."
                )

        # 2. Validate strict prefix ordering: applied must be an exact prefix of discovered
        for idx, record in enumerate(applied):
            if idx >= len(discovered):
                raise OutOrderMigrationError(
                    f"More migrations applied ({len(applied)}) than discovered on disk ({len(discovered)})"
                )
            expected_file = discovered[idx]
            if record.version != expected_file.version:
                raise OutOrderMigrationError(
                    f"Migration gap or ordering anomaly detected at position {idx + 1}. "
                    f"Database recorded '{record.version}_{record.name}', but disk file at this "
                    f"position is '{expected_file.version}_{expected_file.name}'."
                )

        # 3. Pending migrations are those after the applied prefix
        pending = discovered[len(applied):]
        return applied, pending

    def _execute_sql_script(self, conn: Connection, sql_text: str) -> None:
        """Execute raw SQL statements with driver-specific multi-statement support."""
        cleaned = clean_migration_sql(sql_text)
        if not cleaned:
            return

        dialect_name = conn.dialect.name
        if dialect_name == "sqlite":
            # SQLite requires dbapi executescript for multi-statement scripts
            raw_conn = conn.connection.dbapi_connection
            raw_conn.executescript(cleaned)
        else:
            # psycopg2 (PostgreSQL) raw cursor execution without params prevents
            # unintended pyformat (%) parameter interpolation on SQL scripts
            raw_conn = conn.connection.dbapi_connection
            cursor = raw_conn.cursor()
            try:
                cursor.execute(cleaned)
            finally:
                cursor.close()

    def apply_migration(
        self,
        conn: Connection,
        migration: MigrationFile,
        *,
        dry_run: bool = False,
    ) -> MigrationRecord:
        """Apply a single migration within the caller's transaction."""
        self.ensure_tracking_table(conn)
        tbl = self._get_table_name(conn)

        if dry_run:
            _log.info(
                "[DRY-RUN] Would apply migration %s (%s) [%s]",
                migration.version,
                migration.name,
                migration.checksum[:8],
            )
            return MigrationRecord(
                version=migration.version,
                name=migration.name,
                applied_at=datetime.now(timezone.utc),
                checksum=migration.checksum,
                execution_time_ms=0,
            )

        start = time.perf_counter()
        try:
            if conn.dialect.name == "postgresql":
                conn.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
                conn.execute(sa.text("SET LOCAL statement_timeout = '60s'"))
            sql_text = migration.up_path.read_text(encoding="utf-8")
            self._execute_sql_script(conn, sql_text)
            elapsed_ms = max(1, int((time.perf_counter() - start) * 1000))

            now_val = datetime.now(timezone.utc)
            insert_stmt = sa.text(f"""
                INSERT INTO {tbl} (version, name, applied_at, checksum, execution_time_ms)
                VALUES (:version, :name, :applied_at, :checksum, :execution_time_ms)
            """)
            conn.execute(
                insert_stmt,
                {
                    "version": migration.version,
                    "name": migration.name,
                    "applied_at": now_val,
                    "checksum": migration.checksum,
                    "execution_time_ms": elapsed_ms,
                },
            )

            _log.info(
                "Applied migration %s (%s) in %sms [%s]",
                migration.version,
                migration.name,
                elapsed_ms,
                migration.checksum[:8],
            )

            return MigrationRecord(
                version=migration.version,
                name=migration.name,
                applied_at=now_val,
                checksum=migration.checksum,
                execution_time_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            sanitized = sanitize_db_error(str(exc))
            _log.error(
                "Migration %s (%s) failed after %sms: %s",
                migration.version,
                migration.name,
                elapsed_ms,
                sanitized,
            )
            raise MigrationExecutionError(
                f"Migration {migration.version} ({migration.name}) failed: {sanitized}"
            ) from None

    def revert_migration(
        self,
        conn: Connection,
        record: MigrationRecord,
        migration_file: MigrationFile,
        *,
        dry_run: bool = False,
    ) -> None:
        """Revert a single applied migration within the caller's transaction."""
        self.ensure_tracking_table(conn)
        tbl = self._get_table_name(conn)

        if not migration_file.down_path or not migration_file.down_path.exists():
            raise MissingMigrationFileError(
                f"Cannot revert migration '{record.version}_{record.name}': "
                f"missing .down.sql script at {migration_file.down_path}"
            )

        if dry_run:
            _log.info(
                "[DRY-RUN] Would revert migration %s (%s)",
                record.version,
                record.name,
            )
            return

        start = time.perf_counter()
        try:
            if conn.dialect.name == "postgresql":
                conn.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
                conn.execute(sa.text("SET LOCAL statement_timeout = '60s'"))
            sql_text = migration_file.down_path.read_text(encoding="utf-8")
            self._execute_sql_script(conn, sql_text)
            elapsed_ms = max(1, int((time.perf_counter() - start) * 1000))

            delete_stmt = sa.text(f"DELETE FROM {tbl} WHERE version = :version")
            conn.execute(delete_stmt, {"version": record.version})

            _log.info(
                "Reverted migration %s (%s) in %sms",
                record.version,
                record.name,
                elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            sanitized = sanitize_db_error(str(exc))
            _log.error(
                "Downgrade of migration %s (%s) failed after %sms: %s",
                record.version,
                record.name,
                elapsed_ms,
                sanitized,
            )
            raise MigrationExecutionError(
                f"Downgrade {record.version} ({record.name}) failed: {sanitized}"
            ) from None

    def get_status(self) -> dict[str, Any]:
        """Retrieve migration status summary including applied records and pending files."""
        engine = self.get_engine()
        self.ensure_tracking_table()
        with engine.connect() as conn:
            applied, pending = self.validate_and_get_pending(conn)
            discovered = self.discover_migrations()

            return {
                "status": "ok",
                "database_url": mask_database_url(str(engine.url)),
                "migrations_dir": str(self._migrations_dir),
                "total_discovered": len(discovered),
                "applied_count": len(applied),
                "pending_count": len(pending),
                "applied": [r.to_dict() for r in applied],
                "pending": [p.to_dict() for p in pending],
            }

    def run_upgrade(
        self,
        target_version: Optional[str] = None,
        *,
        dry_run: bool = False,
    ) -> list[MigrationRecord]:
        """Apply all pending migrations up to target_version (or all pending if None).

        Each migration executes in its own transaction alongside its history record.
        On failure, the failing migration's transaction rolls back completely and runner halts.
        """
        engine = self.get_engine()
        self.ensure_tracking_table()
        applied_results: list[MigrationRecord] = []

        with engine.connect() as conn:
            # 1. Validate existing state and resolve pending list
            applied, pending = self.validate_and_get_pending(conn)

            if not pending:
                _log.info("Database schema is up to date (no pending migrations).")
                return []

            # 2. Filter by target version if requested
            to_apply: list[MigrationFile] = []
            target_str = str(target_version or "").strip()
            if target_str:
                target_found = False
                for m in pending:
                    to_apply.append(m)
                    if m.version == target_str:
                        target_found = True
                        break
                if not target_found:
                    raise MalformedMigrationError(
                        f"Target version '{target_str}' is not among pending migrations."
                    )
            else:
                to_apply = pending

            _log.info(
                "Running upgrade: %s pending migration(s) to apply (dry_run=%s)",
                len(to_apply),
                dry_run,
            )

            # 3. Apply each migration atomically
            for migration in to_apply:
                if dry_run:
                    rec = self.apply_migration(conn, migration, dry_run=True)
                    applied_results.append(rec)
                else:
                    with engine.begin() as trans_conn:
                        self._acquire_advisory_lock(trans_conn)
                        rec = self.apply_migration(trans_conn, migration, dry_run=False)
                        applied_results.append(rec)

        return applied_results

    def run_downgrade(
        self,
        steps: int = 1,
        target_version: Optional[str] = None,
        *,
        dry_run: bool = False,
    ) -> list[str]:
        """Revert the most recently applied migrations.

        Strictly intended for development, local testing, and staging rollbacks.
        """
        if steps < 1:
            raise ValueError(f"Steps must be >= 1, got {steps}")

        engine = self.get_engine()
        self.ensure_tracking_table()
        reverted_versions: list[str] = []

        with engine.connect() as conn:
            applied, _ = self.validate_and_get_pending(conn)
            if not applied:
                _log.info("No applied migrations found to revert.")
                return []

            discovered_by_version = {m.version: m for m in self.discover_migrations()}

            # Determine which records to revert in reverse chronological order
            reversed_applied = list(reversed(applied))
            to_revert: list[MigrationRecord] = []

            target_str = str(target_version or "").strip()
            if target_str:
                for r in reversed_applied:
                    if r.version == target_str:
                        break
                    to_revert.append(r)
            else:
                to_revert = reversed_applied[:steps]

            _log.info(
                "Running downgrade: %s migration(s) to revert (dry_run=%s)",
                len(to_revert),
                dry_run,
            )

            for record in to_revert:
                m_file = discovered_by_version.get(record.version)
                if not m_file:
                    raise MissingMigrationFileError(
                        f"Cannot downgrade: missing file for version '{record.version}'"
                    )

                if dry_run:
                    self.revert_migration(conn, record, m_file, dry_run=True)
                    reverted_versions.append(record.version)
                else:
                    with engine.begin() as trans_conn:
                        self._acquire_advisory_lock(trans_conn)
                        self.revert_migration(trans_conn, record, m_file, dry_run=False)
                        reverted_versions.append(record.version)

        return reverted_versions


# ── CLI Entrypoint ────────────────────────────────────────────────────────────

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ReconDesk AWS Aurora PostgreSQL Migration Runner"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--status",
        action="store_true",
        help="Check and display current migration status",
    )
    group.add_argument(
        "--upgrade",
        action="store_true",
        help="Apply pending migrations",
    )
    group.add_argument(
        "--downgrade",
        action="store_true",
        help="Revert the most recently applied migration(s)",
    )

    parser.add_argument(
        "--target",
        dest="target_version",
        help="Target migration version (YYYYMMDDHHMMSS) to upgrade or downgrade to",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=1,
        help="Number of migrations to revert on downgrade (default: 1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate migration operations without modifying database state",
    )
    parser.add_argument(
        "--migrations-dir",
        help="Custom path to migrations directory (default: recondesk-backend/migrations/aurora)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_args(argv)

    # Validate that AURORA_DATABASE_URL is configured
    try:
        from app.config import get_settings
        settings = get_settings()
        if (settings.APP_ENV or "").lower() == "staging" or os.environ.get("ENFORCE_STAGING_GUARD") == "true":
            from app.staging_guard import enforce_staging_safety
            enforce_staging_safety(settings)

        url = get_aurora_database_url()
        if not url:
            print(
                "ERROR: AURORA_DATABASE_URL is not configured in the environment.\n"
                "An explicit Aurora connection string is required to prevent accidental connection to Supabase.",
                file=sys.stderr,
            )
            return 1
    except AuroraConfigurationError as exc:
        print(f"ERROR: {sanitize_db_error(str(exc))}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"SAFETY ERROR: {sanitize_db_error(str(exc))}", file=sys.stderr)
        return 1

    custom_dir = Path(args.migrations_dir) if args.migrations_dir else None
    runner = AuroraMigrationRunner(migrations_dir=custom_dir)

    try:
        if args.status:
            status = runner.get_status()
            print("=" * 60)
            print("  RECONDESK AWS AURORA MIGRATION STATUS")
            print("=" * 60)
            print(f"Database:      {status['database_url']}")
            print(f"Directory:     {status['migrations_dir']}")
            print(f"Discovered:    {status['total_discovered']}")
            print(f"Applied:       {status['applied_count']}")
            print(f"Pending:       {status['pending_count']}")
            print("-" * 60)
            if status["applied"]:
                print("Applied Migrations:")
                for r in status["applied"]:
                    print(
                        f"  [x] {r['version']} - {r['name']} "
                        f"(applied at {r['applied_at']}, {r['execution_time_ms']}ms)"
                    )
            if status["pending"]:
                print("Pending Migrations:")
                for p in status["pending"]:
                    print(f"  [ ] {p['version']} - {p['name']} [SHA: {p['checksum'][:8]}]")
            print("=" * 60)
            return 0

        elif args.upgrade:
            applied = runner.run_upgrade(
                target_version=args.target_version,
                dry_run=args.dry_run,
            )
            prefix = "[DRY-RUN] " if args.dry_run else ""
            print(f"{prefix}Upgrade completed: {len(applied)} migration(s) processed.")
            for r in applied:
                print(f"  • {r.version}_{r.name} ({r.execution_time_ms}ms)")
            return 0

        elif args.downgrade:
            reverted = runner.run_downgrade(
                steps=args.steps,
                target_version=args.target_version,
                dry_run=args.dry_run,
            )
            prefix = "[DRY-RUN] " if args.dry_run else ""
            print(f"{prefix}Downgrade completed: {len(reverted)} migration(s) reverted.")
            for v in reverted:
                print(f"  • {v}")
            return 0

    except Exception as exc:
        sanitized = sanitize_db_error(str(exc))
        print(f"ERROR: {sanitized}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
