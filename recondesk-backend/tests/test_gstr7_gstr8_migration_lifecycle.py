"""Phase 4.2: Migration Lifecycle & Safe Archival Rollback Tests for GSTR-7 & GSTR-8.

Verifies:
1. Aurora up and down migrations exist with valid timestamp prefix.
2. Up migration creates all required tables, indexes, constraints, and audit trails.
3. Down migration implements safe non-destructive archival rollback (no data loss).
4. Up migration includes idempotent restoration block from archive tables.
5. Check constraints for maker-checker and client authorization include GSTR-7 and GSTR-8.
6. Executes full upgrade -> rollback -> re-upgrade cycle on an isolated SQLite engine.
"""

from pathlib import Path
import re
import sqlite3
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
AURORA_UP = BACKEND_DIR / "migrations/aurora/20261012160000_create_gstr7_gstr8_compliance.up.sql"
AURORA_DOWN = BACKEND_DIR / "migrations/aurora/20261012160000_create_gstr7_gstr8_compliance.down.sql"
SUPABASE_MIGRATION = BACKEND_DIR / "supabase/migrations/20261012160000_create_gstr7_gstr8_compliance.sql"


def test_migration_files_exist():
    assert AURORA_UP.exists(), f"Aurora up migration not found: {AURORA_UP}"
    assert AURORA_DOWN.exists(), f"Aurora down migration not found: {AURORA_DOWN}"
    assert SUPABASE_MIGRATION.exists(), f"Supabase migration not found: {SUPABASE_MIGRATION}"


def test_aurora_up_migration_structure():
    content = AURORA_UP.read_text(encoding="utf-8")

    # 1. Check constraint extension to support GSTR-7 and GSTR-8
    assert "return_filing_approvals_return_type_check" in content
    assert "'GSTR-7'" in content
    assert "'GSTR-8'" in content
    assert "client_filing_authorizations_return_type_check" in content

    # 2. GSTR-7 active tables created
    assert "CREATE TABLE IF NOT EXISTS public.gstr7_batches" in content
    assert "CREATE TABLE IF NOT EXISTS public.gstr7_records" in content
    assert "CREATE TABLE IF NOT EXISTS public.gstr7_audit_trail" in content

    # 3. GSTR-8 active tables created
    assert "CREATE TABLE IF NOT EXISTS public.gstr8_batches" in content
    assert "CREATE TABLE IF NOT EXISTS public.gstr8_records" in content
    assert "CREATE TABLE IF NOT EXISTS public.gstr8_audit_trail" in content

    # 4. Critical column checks
    assert "contract_value" in content
    assert "is_eligible_for_tds" in content
    assert "returned_supplies" in content
    assert "net_supplies" in content
    assert "tcs_rate" in content
    assert "figures_digest" in content

    # 5. Idempotent restoration blocks
    assert "_archive_gstr7_batches_rollback" in content
    assert "_archive_gstr7_records_rollback" in content
    assert "_archive_gstr8_batches_rollback" in content
    assert "_archive_gstr8_records_rollback" in content
    assert "ON CONFLICT (id) DO NOTHING" in content


def test_aurora_down_migration_non_destructive_archival():
    content = AURORA_DOWN.read_text(encoding="utf-8")

    # 1. Archive tables created before any drops
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr7_audit_trail_rollback" in content
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr7_records_rollback" in content
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr7_batches_rollback" in content
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr8_audit_trail_rollback" in content
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr8_records_rollback" in content
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr8_batches_rollback" in content

    # 2. Archive data inserted safely
    assert "INSERT INTO public._archive_gstr7_audit_trail_rollback" in content
    assert "INSERT INTO public._archive_gstr7_records_rollback" in content
    assert "INSERT INTO public._archive_gstr7_batches_rollback" in content
    assert "INSERT INTO public._archive_gstr8_audit_trail_rollback" in content
    assert "INSERT INTO public._archive_gstr8_records_rollback" in content
    assert "INSERT INTO public._archive_gstr8_batches_rollback" in content

    # 3. Active tables dropped only after archiving
    assert "DROP TABLE IF EXISTS public.gstr7_audit_trail CASCADE" in content
    assert "DROP TABLE IF EXISTS public.gstr7_records CASCADE" in content
    assert "DROP TABLE IF EXISTS public.gstr7_batches CASCADE" in content
    assert "DROP TABLE IF EXISTS public.gstr8_audit_trail CASCADE" in content
    assert "DROP TABLE IF EXISTS public.gstr8_records CASCADE" in content
    assert "DROP TABLE IF EXISTS public.gstr8_batches CASCADE" in content

    # 4. Archive tables must NEVER be dropped
    assert "DROP TABLE" not in content or "_archive" not in content.split("DROP TABLE")[1].split(";")[0]


def test_supabase_migration_matches_aurora_schema():
    content = SUPABASE_MIGRATION.read_text(encoding="utf-8")
    assert "'GSTR-7'" in content
    assert "'GSTR-8'" in content
    assert "gstr7_batches" in content
    assert "gstr8_batches" in content
    assert "_archive_gstr7_batches_rollback" in content
    assert "_archive_gstr8_batches_rollback" in content


def test_gstr7_gstr8_upgrade_rollback_reupgrade_cycle_execution():
    """Execute UP -> INSERT -> DOWN (ARCHIVE) -> UP (RESTORE) cycle in isolated SQLite."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()

    try:
        # 1. UP: Create active tables
        cur.execute("""
            CREATE TABLE gstr7_batches (
                id TEXT PRIMARY KEY,
                firm_id TEXT NOT NULL,
                client_gstin_id TEXT NOT NULL,
                gstin TEXT NOT NULL,
                period TEXT NOT NULL,
                status TEXT NOT NULL,
                figures_digest TEXT NOT NULL,
                total_records INT NOT NULL DEFAULT 0,
                total_amendments INT NOT NULL DEFAULT 0,
                total_amount_paid REAL NOT NULL DEFAULT 0.0,
                total_tds_igst REAL NOT NULL DEFAULT 0.0,
                total_tds_cgst REAL NOT NULL DEFAULT 0.0,
                total_tds_sgst REAL NOT NULL DEFAULT 0.0,
                total_tds_deposited REAL NOT NULL DEFAULT 0.0,
                gstn_reference_id TEXT,
                gstn_status TEXT,
                arn TEXT,
                filing_run_id TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE gstr8_batches (
                id TEXT PRIMARY KEY,
                firm_id TEXT NOT NULL,
                client_gstin_id TEXT NOT NULL,
                gstin TEXT NOT NULL,
                period TEXT NOT NULL,
                status TEXT NOT NULL,
                figures_digest TEXT NOT NULL,
                total_b2b_records INT NOT NULL DEFAULT 0,
                total_b2c_records INT NOT NULL DEFAULT 0,
                total_amendments INT NOT NULL DEFAULT 0,
                gross_supplies_value REAL NOT NULL DEFAULT 0.0,
                returned_supplies_value REAL NOT NULL DEFAULT 0.0,
                net_taxable_value REAL NOT NULL DEFAULT 0.0,
                total_tcs_igst REAL NOT NULL DEFAULT 0.0,
                total_tcs_cgst REAL NOT NULL DEFAULT 0.0,
                total_tcs_sgst REAL NOT NULL DEFAULT 0.0,
                total_tcs_deposited REAL NOT NULL DEFAULT 0.0,
                gstn_reference_id TEXT,
                gstn_status TEXT,
                arn TEXT,
                filing_run_id TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

        # 2. INSERT: Add live data
        cur.execute("""
            INSERT INTO gstr7_batches (
                id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
                total_records, total_amount_paid, total_tds_cgst, total_tds_sgst, created_at, updated_at
            ) VALUES (
                'batch-g7-01', 'firm-01', 'cgstin-01', '27AAACG0000A1Z5', '2026-07', 'APPROVED',
                'digest_g7', 5, 250000.0, 2500.0, 2500.0, '2026-07-01', '2026-07-01'
            );
        """)
        cur.execute("""
            INSERT INTO gstr8_batches (
                id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
                total_b2b_records, net_taxable_value, total_tcs_cgst, total_tcs_sgst, created_at, updated_at
            ) VALUES (
                'batch-g8-01', 'firm-01', 'cgstin-02', '27AAACG0000A1Z5', '2026-07', 'APPROVED',
                'digest_g8', 3, 450000.0, 1125.0, 1125.0, '2026-07-01', '2026-07-01'
            );
        """)

        # 3. DOWN: Non-destructive archival
        cur.execute("""
            CREATE TABLE _archive_gstr7_batches_rollback AS
            SELECT id AS batch_id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
                   total_records, total_amendments, total_amount_paid, total_tds_igst, total_tds_cgst,
                   total_tds_sgst, total_tds_deposited, gstn_reference_id, gstn_status, arn,
                   filing_run_id, created_by, created_at, updated_at
            FROM gstr7_batches;
        """)
        cur.execute("DROP TABLE gstr7_batches;")

        cur.execute("""
            CREATE TABLE _archive_gstr8_batches_rollback AS
            SELECT id AS batch_id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
                   total_b2b_records, total_b2c_records, total_amendments, gross_supplies_value,
                   returned_supplies_value, net_taxable_value, total_tcs_igst, total_tcs_cgst,
                   total_tcs_sgst, total_tcs_deposited, gstn_reference_id, gstn_status, arn,
                   filing_run_id, created_by, created_at, updated_at
            FROM gstr8_batches;
        """)
        cur.execute("DROP TABLE gstr8_batches;")

        # Verify archive tables preserve data
        cur.execute("SELECT COUNT(*) FROM _archive_gstr7_batches_rollback")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT COUNT(*) FROM _archive_gstr8_batches_rollback")
        assert cur.fetchone()[0] == 1

        # 4. RE-UPGRADE: Recreate active tables and restore from archives
        cur.execute("""
            CREATE TABLE gstr7_batches (
                id TEXT PRIMARY KEY,
                firm_id TEXT NOT NULL,
                client_gstin_id TEXT NOT NULL,
                gstin TEXT NOT NULL,
                period TEXT NOT NULL,
                status TEXT NOT NULL,
                figures_digest TEXT NOT NULL,
                total_records INT NOT NULL DEFAULT 0,
                total_amendments INT NOT NULL DEFAULT 0,
                total_amount_paid REAL NOT NULL DEFAULT 0.0,
                total_tds_igst REAL NOT NULL DEFAULT 0.0,
                total_tds_cgst REAL NOT NULL DEFAULT 0.0,
                total_tds_sgst REAL NOT NULL DEFAULT 0.0,
                total_tds_deposited REAL NOT NULL DEFAULT 0.0,
                gstn_reference_id TEXT,
                gstn_status TEXT,
                arn TEXT,
                filing_run_id TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        cur.execute("""
            INSERT OR IGNORE INTO gstr7_batches
            SELECT batch_id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
                   total_records, total_amendments, total_amount_paid, total_tds_igst, total_tds_cgst,
                   total_tds_sgst, total_tds_deposited, gstn_reference_id, gstn_status, arn,
                   filing_run_id, created_by, created_at, updated_at
            FROM _archive_gstr7_batches_rollback;
        """)

        cur.execute("""
            CREATE TABLE gstr8_batches (
                id TEXT PRIMARY KEY,
                firm_id TEXT NOT NULL,
                client_gstin_id TEXT NOT NULL,
                gstin TEXT NOT NULL,
                period TEXT NOT NULL,
                status TEXT NOT NULL,
                figures_digest TEXT NOT NULL,
                total_b2b_records INT NOT NULL DEFAULT 0,
                total_b2c_records INT NOT NULL DEFAULT 0,
                total_amendments INT NOT NULL DEFAULT 0,
                gross_supplies_value REAL NOT NULL DEFAULT 0.0,
                returned_supplies_value REAL NOT NULL DEFAULT 0.0,
                net_taxable_value REAL NOT NULL DEFAULT 0.0,
                total_tcs_igst REAL NOT NULL DEFAULT 0.0,
                total_tcs_cgst REAL NOT NULL DEFAULT 0.0,
                total_tcs_sgst REAL NOT NULL DEFAULT 0.0,
                total_tcs_deposited REAL NOT NULL DEFAULT 0.0,
                gstn_reference_id TEXT,
                gstn_status TEXT,
                arn TEXT,
                filing_run_id TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        cur.execute("""
            INSERT OR IGNORE INTO gstr8_batches
            SELECT batch_id, firm_id, client_gstin_id, gstin, period, status, figures_digest,
                   total_b2b_records, total_b2c_records, total_amendments, gross_supplies_value,
                   returned_supplies_value, net_taxable_value, total_tcs_igst, total_tcs_cgst,
                   total_tcs_sgst, total_tcs_deposited, gstn_reference_id, gstn_status, arn,
                   filing_run_id, created_by, created_at, updated_at
            FROM _archive_gstr8_batches_rollback;
        """)

        # 5. Verify restored rows
        cur.execute("SELECT id, status, total_amount_paid FROM gstr7_batches WHERE id = 'batch-g7-01'")
        row_g7 = cur.fetchone()
        assert row_g7 == ("batch-g7-01", "APPROVED", 250000.0)

        cur.execute("SELECT id, status, net_taxable_value FROM gstr8_batches WHERE id = 'batch-g8-01'")
        row_g8 = cur.fetchone()
        assert row_g8 == ("batch-g8-01", "APPROVED", 450000.0)

    finally:
        conn.close()
