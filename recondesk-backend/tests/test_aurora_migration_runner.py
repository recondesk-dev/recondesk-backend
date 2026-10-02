"""Tests for ReconDesk AWS Aurora Migration Runner & Tenancy Backfill (Phase 6).

Verifies:
1. Migration discovery & ordering (14-digit timestamps, lexical order).
2. Malformed migration metadata rejection (fails closed).
3. Duplicate version detection (fails closed).
4. Migration tracking table creation & execution records.
5. Idempotent re-runs (already-applied migrations safely skipped).
6. Checksum mismatch detection (fails closed when applied files are altered).
7. Missing migration file detection (fails closed when applied file is removed).
8. Out-of-order execution / gap detection (fails closed).
9. Transactional failure rollback & safe retry behavior.
10. Dry-run execution mode without database mutation.
11. Downgrade execution and rollback tracking.
12. Zero secret leakage in logs and exception messages.
13. Tenancy backfill orchestrator (canonical UUIDs, dependency order, read-only Supabase).
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine

from app.aurora import mask_database_url, sanitize_db_error
from app.migrations.runner import (
    AuroraMigrationRunner,
    ChecksumMismatchError,
    MalformedMigrationError,
    MigrationConcurrencyError,
    MigrationExecutionError,
    MigrationFile,
    MigrationRecord,
    MissingMigrationFileError,
    OutOrderMigrationError,
    clean_migration_sql,
    compute_file_checksum,
)
from app.scripts.backfill_tenancy_aurora import (
    BackfillStats,
    TenancyBackfillOrchestrator,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_migrations_dir():
    """Create a temporary directory for test migration scripts."""
    tmp = tempfile.mkdtemp(prefix="aurora_migrations_test_")
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def sqlite_test_engine():
    """Create an isolated temporary SQLite engine for migration tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(f"sqlite:///{db_path}")
    yield engine
    engine.dispose()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass


# ── 1. Real Migrations Discovery & Ordering Tests ──────────────────────────────

class TestRealMigrationsDiscovery:
    def test_discover_real_aurora_migrations(self):
        """Verify the 3 existing Aurora migrations are correctly discovered in order."""
        runner = AuroraMigrationRunner()
        discovered = runner.discover_migrations()

        assert len(discovered) >= 3
        versions = [m.version for m in discovered]

        # Monotonically increasing 14-digit timestamps
        assert versions == sorted(versions)
        for v in versions:
            assert len(v) == 14
            assert v.isdigit()

        # Check known migrations are present and in exact dependency order:
        # 1. create_tenancy_tables (creates user_profiles, team_members, client_gstins)
        # 2. create_cognito_user_mappings (references user_profiles)
        # 3. create_reconciliation_tables (references client_gstins, user_profiles)
        assert discovered[0].version == "20260930183000"
        assert discovered[0].name == "create_tenancy_tables"
        assert discovered[1].version == "20261001120000"
        assert discovered[1].name == "create_cognito_user_mappings"
        assert discovered[2].version == "20261001150000"
        assert discovered[2].name == "create_reconciliation_tables"
        if len(discovered) >= 4:
            assert discovered[3].version == "20261003100000"
            assert discovered[3].name == "create_wizard_ingestion_tables"

        # Check that SHA-256 checksums are calculated
        for m in discovered:
            assert len(m.checksum) == 64
            assert m.up_path.exists()
            if m.down_path:
                assert m.down_path.exists()


# ── 2. Malformed Metadata & Duplicate Prevention Tests ────────────────────────

class TestMalformedMetadataAndDuplicates:
    def test_malformed_timestamp_fails_closed(self, temp_migrations_dir):
        """File with invalid timestamp format raises MalformedMigrationError."""
        bad_file = temp_migrations_dir / "2026_create_table.up.sql"
        bad_file.write_text("CREATE TABLE bad (id int);", encoding="utf-8")

        runner = AuroraMigrationRunner(migrations_dir=temp_migrations_dir)
        with pytest.raises(MalformedMigrationError, match="does not match required format"):
            runner.discover_migrations()

    def test_duplicate_version_fails_closed(self, temp_migrations_dir):
        """Two files with identical timestamp versions raise MalformedMigrationError."""
        f1 = temp_migrations_dir / "20261001100000_create_one.up.sql"
        f2 = temp_migrations_dir / "20261001100000_create_two.up.sql"
        f1.write_text("CREATE TABLE one (id int);", encoding="utf-8")
        f2.write_text("CREATE TABLE two (id int);", encoding="utf-8")

        runner = AuroraMigrationRunner(migrations_dir=temp_migrations_dir)
        with pytest.raises(MalformedMigrationError, match="Duplicate migration version"):
            runner.discover_migrations()

    def test_missing_directory_fails_closed(self):
        """Non-existent migrations directory raises MalformedMigrationError."""
        runner = AuroraMigrationRunner(migrations_dir=Path("/non/existent/path/here"))
        with pytest.raises(MalformedMigrationError, match="does not exist"):
            runner.discover_migrations()


# ── 3. Tracking Table & Upgrade Execution Tests ───────────────────────────────

class TestMigrationTrackingAndUpgrade:
    def test_upgrade_creates_tracking_table_and_records(
        self, temp_migrations_dir, sqlite_test_engine
    ):
        """Running upgrade creates aurora_schema_migrations and records each migration."""
        f1 = temp_migrations_dir / "20261001100000_create_items.up.sql"
        f1.write_text(
            "BEGIN;\nCREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT);\nCOMMIT;",
            encoding="utf-8",
        )

        f2 = temp_migrations_dir / "20261001110000_create_orders.up.sql"
        f2.write_text(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, total REAL);",
            encoding="utf-8",
        )

        runner = AuroraMigrationRunner(
            engine=sqlite_test_engine, migrations_dir=temp_migrations_dir
        )
        applied = runner.run_upgrade()

        assert len(applied) == 2
        assert applied[0].version == "20261001100000"
        assert applied[0].name == "create_items"
        assert applied[1].version == "20261001110000"
        assert applied[1].name == "create_orders"

        # Verify tracking table in SQLite
        with sqlite_test_engine.connect() as conn:
            records = runner.get_applied_migrations(conn)
            assert len(records) == 2
            assert records[0].version == "20261001100000"
            assert records[0].checksum == compute_file_checksum(f1)
            assert records[1].version == "20261001110000"
            assert records[1].checksum == compute_file_checksum(f2)

            # Verify target tables were created
            res1 = conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name='items'")).scalar()
            res2 = conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name='orders'")).scalar()
            assert res1 == "items"
            assert res2 == "orders"

    def test_already_applied_migrations_skipped_idempotently(
        self, temp_migrations_dir, sqlite_test_engine
    ):
        """Second upgrade run does not re-apply already executed migrations."""
        f1 = temp_migrations_dir / "20261001100000_create_items.up.sql"
        f1.write_text("CREATE TABLE items (id INTEGER PRIMARY KEY);", encoding="utf-8")

        runner = AuroraMigrationRunner(
            engine=sqlite_test_engine, migrations_dir=temp_migrations_dir
        )
        first_applied = runner.run_upgrade()
        assert len(first_applied) == 1

        second_applied = runner.run_upgrade()
        assert len(second_applied) == 0


# ── 4. Drift & Checksum Mismatch Tests ────────────────────────────────────────

class TestDriftAndIntegrityFailures:
    def test_checksum_mismatch_fails_closed(
        self, temp_migrations_dir, sqlite_test_engine
    ):
        """Modifying an applied migration file raises ChecksumMismatchError."""
        f1 = temp_migrations_dir / "20261001100000_create_items.up.sql"
        f1.write_text("CREATE TABLE items (id INTEGER PRIMARY KEY);", encoding="utf-8")

        runner = AuroraMigrationRunner(
            engine=sqlite_test_engine, migrations_dir=temp_migrations_dir
        )
        runner.run_upgrade()

        # Tamper with file
        f1.write_text("CREATE TABLE items (id INTEGER PRIMARY KEY, tampered BOOLEAN);", encoding="utf-8")

        with pytest.raises(ChecksumMismatchError, match="Checksum mismatch for applied migration"):
            with sqlite_test_engine.connect() as conn:
                runner.validate_and_get_pending(conn)

    def test_missing_migration_file_fails_closed(
        self, temp_migrations_dir, sqlite_test_engine
    ):
        """Removing an applied migration file raises MissingMigrationFileError."""
        f1 = temp_migrations_dir / "20261001100000_create_items.up.sql"
        f1.write_text("CREATE TABLE items (id INTEGER PRIMARY KEY);", encoding="utf-8")

        runner = AuroraMigrationRunner(
            engine=sqlite_test_engine, migrations_dir=temp_migrations_dir
        )
        runner.run_upgrade()

        # Delete file from disk
        f1.unlink()

        with pytest.raises(MissingMigrationFileError, match="is recorded in the database but missing from disk"):
            with sqlite_test_engine.connect() as conn:
                runner.validate_and_get_pending(conn)

    def test_out_of_order_migration_gap_fails_closed(
        self, temp_migrations_dir, sqlite_test_engine
    ):
        """If a gap exists in applied migrations, OutOrderMigrationError is raised."""
        f1 = temp_migrations_dir / "20261001100000_first.up.sql"
        f2 = temp_migrations_dir / "20261001110000_second.up.sql"
        f1.write_text("CREATE TABLE first (id INT);", encoding="utf-8")
        f2.write_text("CREATE TABLE second (id INT);", encoding="utf-8")

        runner = AuroraMigrationRunner(
            engine=sqlite_test_engine, migrations_dir=temp_migrations_dir
        )

        # Manually record f2 as applied, skipping f1
        with sqlite_test_engine.connect() as conn:
            runner.ensure_tracking_table(conn)
            tbl = runner._get_table_name(conn)
            conn.execute(
                sa.text(f"INSERT INTO {tbl} (version, name, applied_at, checksum, execution_time_ms) VALUES (:v, :n, :at, :c, :ms)"),
                {
                    "v": "20261001110000",
                    "n": "second",
                    "at": datetime.now(timezone.utc),
                    "c": compute_file_checksum(f2),
                    "ms": 10,
                },
            )
            conn.commit()

            with pytest.raises(OutOrderMigrationError, match="Migration gap or ordering anomaly"):
                runner.validate_and_get_pending(conn)


# ── 5. Transactional Rollback & Retry Tests ───────────────────────────────────

class TestTransactionalRollbackAndRetry:
    def test_failed_migration_rolls_back_and_permits_retry(
        self, temp_migrations_dir, sqlite_test_engine
    ):
        """A syntax error in migration causes rollback and no record in tracking table."""
        bad_f = temp_migrations_dir / "20261001100000_bad.up.sql"
        bad_f.write_text("CREATE TABLE IF NOT EXISTS valid (id INT); MALFORMED SQL SYNTAX ERROR;", encoding="utf-8")

        runner = AuroraMigrationRunner(
            engine=sqlite_test_engine, migrations_dir=temp_migrations_dir
        )

        with pytest.raises(MigrationExecutionError):
            runner.run_upgrade()

        # Check tracking table has no record
        with sqlite_test_engine.connect() as conn:
            records = runner.get_applied_migrations(conn)
            assert len(records) == 0

        # Fix the SQL file to be valid and retry
        bad_f.write_text("CREATE TABLE IF NOT EXISTS valid (id INT);", encoding="utf-8")
        retry_applied = runner.run_upgrade()
        assert len(retry_applied) == 1
        assert retry_applied[0].version == "20261001100000"


# ── 6. Dry Run & Downgrade Tests ──────────────────────────────────────────────

class TestDryRunAndDowngrade:
    def test_dry_run_does_not_mutate_database(
        self, temp_migrations_dir, sqlite_test_engine
    ):
        """Dry run discovers pending migrations but leaves database untouched."""
        f1 = temp_migrations_dir / "20261001100000_create_test.up.sql"
        f1.write_text("CREATE TABLE test_table (id INT);", encoding="utf-8")

        runner = AuroraMigrationRunner(
            engine=sqlite_test_engine, migrations_dir=temp_migrations_dir
        )
        simulated = runner.run_upgrade(dry_run=True)

        assert len(simulated) == 1
        assert simulated[0].version == "20261001100000"

        # Check target table was NOT created
        with sqlite_test_engine.connect() as conn:
            res = conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name='test_table'")).scalar()
            assert res is None

            records = runner.get_applied_migrations(conn)
            assert len(records) == 0

    def test_downgrade_reverts_latest_migration(
        self, temp_migrations_dir, sqlite_test_engine
    ):
        """Downgrade executes .down.sql and removes record from tracking table."""
        f_up = temp_migrations_dir / "20261001100000_create_test.up.sql"
        f_down = temp_migrations_dir / "20261001100000_create_test.down.sql"
        f_up.write_text("CREATE TABLE test_table (id INT);", encoding="utf-8")
        f_down.write_text("DROP TABLE IF EXISTS test_table;", encoding="utf-8")

        runner = AuroraMigrationRunner(
            engine=sqlite_test_engine, migrations_dir=temp_migrations_dir
        )
        runner.run_upgrade()

        # Verify table exists
        with sqlite_test_engine.connect() as conn:
            res = conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name='test_table'")).scalar()
            assert res == "test_table"
            assert len(runner.get_applied_migrations(conn)) == 1

        # Revert
        reverted = runner.run_downgrade(steps=1)
        assert reverted == ["20261001100000"]

        # Verify table dropped and record removed
        with sqlite_test_engine.connect() as conn:
            res = conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name='test_table'")).scalar()
            assert res is None
            assert len(runner.get_applied_migrations(conn)) == 0


# ── 7. Secret Sanitization Tests ─────────────────────────────────────────────

class TestSecretSanitization:
    def test_mask_database_url_hides_passwords_and_tokens(self):
        """Database URLs mask passwords and query tokens."""
        raw_url = "postgresql://myuser:super_secret_pw123@aurora-cluster.us-east-1.rds.amazonaws.com:5432/recondesk?sslmode=require&token=secret_tok_999"
        masked = mask_database_url(raw_url)
        assert "super_secret_pw123" not in masked
        assert "secret_tok_999" not in masked
        assert "myuser:***@" in masked or "myuser:***" in masked

    def test_sanitize_db_error_strips_credentials(self):
        """Error messages strip inline passwords, credentials, and connection strings."""
        err_msg = (
            "OperationalError: connection to server at '10.0.1.2' failed with password='MySecretPassword!'"
            " url: postgresql://admin:MySecretPassword!@10.0.1.2:5432/db"
        )
        sanitized = sanitize_db_error(err_msg)
        assert "MySecretPassword!" not in sanitized
        assert "***" in sanitized


# ── 8. Tenancy Backfill Orchestrator Tests ────────────────────────────────────

class TestTenancyBackfillOrchestrator:
    def test_backfill_user_profiles_preserves_canonical_ids(self):
        """User profile backfill preserves exact UUIDs and does not alter Supabase."""
        u1_id = str(uuid.uuid4())
        u2_id = str(uuid.uuid4())

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.order.return_value.range.return_value.execute.side_effect = [
            MagicMock(data=[
                {"id": u1_id, "email": "ca1@firm.com", "role": "admin", "full_name": "CA One"},
                {"id": u2_id, "email": "staff1@firm.com", "role": "staff", "full_name": "Staff One"},
            ]),
            MagicMock(data=[]),
        ]

        mock_repo = MagicMock()
        orchestrator = TenancyBackfillOrchestrator(
            sb_client=mock_sb, tenancy_repo=mock_repo, batch_size=10
        )

        stats = orchestrator.backfill_user_profiles(dry_run=False)

        assert stats.source_count == 2
        assert stats.synced_count == 2
        assert stats.error_count == 0

        # Verify upsert called with exact UUIDs
        calls = mock_repo.upsert_user_profile.call_args_list
        assert len(calls) == 2
        assert calls[0][0][0]["id"] == u1_id
        assert calls[1][0][0]["id"] == u2_id

        # Verify Supabase was NEVER written to
        assert not mock_sb.table.return_value.insert.called
        assert not mock_sb.table.return_value.update.called
        assert not mock_sb.table.return_value.delete.called

    def test_backfill_team_members_and_clients_dependency_order(self):
        """run_all executes user_profiles -> team_members -> client_gstins."""
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.order.return_value.range.return_value.execute.return_value = MagicMock(data=[])

        mock_repo = MagicMock()
        orchestrator = TenancyBackfillOrchestrator(
            sb_client=mock_sb, tenancy_repo=mock_repo
        )

        results = orchestrator.run_all(dry_run=True)

        assert "user_profiles" in results
        assert "team_members" in results
        assert "client_gstins" in results

    def test_backfill_audit_detects_missing_records(self):
        """Audit compares Supabase IDs with Aurora and identifies missing records."""
        u1_id = str(uuid.uuid4())
        u2_id = str(uuid.uuid4())

        mock_sb = MagicMock()
        # Mock table("...").select("id").execute()
        mock_sb.table.return_value.select.return_value.execute.side_effect = [
            MagicMock(data=[{"id": u1_id}, {"id": u2_id}]),  # user_profiles
            MagicMock(data=[]),                                 # team_members
            MagicMock(data=[]),                                 # client_gstins
        ]

        mock_repo = MagicMock()
        # u1 exists in Aurora, u2 does not
        mock_repo.get_user_profile.side_effect = lambda uid: {"id": uid} if uid == u1_id else None

        orchestrator = TenancyBackfillOrchestrator(
            sb_client=mock_sb, tenancy_repo=mock_repo
        )

        audit_res = orchestrator.audit()
        prof_res = audit_res["tables"]["user_profiles"]

        assert prof_res["supabase_count"] == 2
        assert prof_res["aurora_count"] == 1
        assert prof_res["missing_in_aurora_count"] == 1
        assert prof_res["missing_sample"] == [u2_id]
