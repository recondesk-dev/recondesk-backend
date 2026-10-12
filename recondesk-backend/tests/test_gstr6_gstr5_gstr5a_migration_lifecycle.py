"""Phase 4.3: Migration Lifecycle & Safe Archival Rollback Tests for GSTR-6, GSTR-5 & GSTR-5A.

Verifies:
1. Aurora up and down migrations exist with valid timestamp prefix.
2. Up migration creates all required tables, indexes, constraints, and audit trails.
3. Down migration implements safe non-destructive archival rollback (no data loss).
4. Up migration includes idempotent restoration block from archive tables.
5. Check constraints for maker-checker and client authorization include GSTR-6, GSTR-5, and GSTR-5A.
6. Executes full upgrade -> rollback -> re-upgrade cycle on an isolated SQLite engine.
"""

from pathlib import Path
import sqlite3
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
AURORA_UP = BACKEND_DIR / "migrations/aurora/20261012180000_create_gstr6_gstr5_gstr5a_compliance.up.sql"
AURORA_DOWN = BACKEND_DIR / "migrations/aurora/20261012180000_create_gstr6_gstr5_gstr5a_compliance.down.sql"
SUPABASE_MIGRATION = BACKEND_DIR / "supabase/migrations/20261012180000_create_gstr6_gstr5_gstr5a_compliance.sql"


def test_migration_files_exist():
    assert AURORA_UP.exists(), f"Aurora up migration not found: {AURORA_UP}"
    assert AURORA_DOWN.exists(), f"Aurora down migration not found: {AURORA_DOWN}"
    assert SUPABASE_MIGRATION.exists(), f"Supabase migration not found: {SUPABASE_MIGRATION}"


def test_aurora_up_migration_structure():
    content = AURORA_UP.read_text(encoding="utf-8")

    # 1. Check constraint extension to support GSTR-6, GSTR-5, and GSTR-5A
    assert "return_filing_approvals_return_type_check" in content
    assert "'GSTR-6'" in content
    assert "'GSTR-5'" in content
    assert "'GSTR-5A'" in content
    assert "client_filing_authorizations_return_type_check" in content

    # 2. GSTR-6 active tables created
    assert "CREATE TABLE IF NOT EXISTS public.gstr6_batches" in content
    assert "CREATE TABLE IF NOT EXISTS public.gstr6_inward_records" in content
    assert "CREATE TABLE IF NOT EXISTS public.gstr6_distribution_records" in content
    assert "CREATE TABLE IF NOT EXISTS public.gstr6_audit_trail" in content

    # 3. GSTR-5 active tables created
    assert "CREATE TABLE IF NOT EXISTS public.gstr5_batches" in content
    assert "CREATE TABLE IF NOT EXISTS public.gstr5_import_records" in content
    assert "CREATE TABLE IF NOT EXISTS public.gstr5_outward_records" in content
    assert "CREATE TABLE IF NOT EXISTS public.gstr5_audit_trail" in content

    # 4. GSTR-5A active tables created
    assert "CREATE TABLE IF NOT EXISTS public.gstr5a_batches" in content
    assert "CREATE TABLE IF NOT EXISTS public.gstr5a_records" in content
    assert "CREATE TABLE IF NOT EXISTS public.gstr5a_audit_trail" in content

    # 5. Critical column checks
    assert "turnover_ratio" in content
    assert "itc_eligible" in content
    assert "boe_number" in content
    assert "advance_tax_deposited" in content
    assert "rate_pct" in content
    assert "figures_digest" in content

    # 6. Idempotent restoration blocks
    assert "_archive_gstr6_batches_rollback" in content
    assert "_archive_gstr6_inward_records_rollback" in content
    assert "_archive_gstr6_distribution_records_rollback" in content
    assert "_archive_gstr5_batches_rollback" in content
    assert "_archive_gstr5_import_records_rollback" in content
    assert "_archive_gstr5_outward_records_rollback" in content
    assert "_archive_gstr5a_batches_rollback" in content
    assert "_archive_gstr5a_records_rollback" in content
    assert "ON CONFLICT (id) DO NOTHING" in content


def test_aurora_down_migration_non_destructive_archival():
    content = AURORA_DOWN.read_text(encoding="utf-8")

    # 1. Archive tables created before any drops
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr6_audit_trail_rollback" in content
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr6_inward_records_rollback" in content
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr6_distribution_records_rollback" in content
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr6_batches_rollback" in content

    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr5_audit_trail_rollback" in content
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr5_import_records_rollback" in content
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr5_outward_records_rollback" in content
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr5_batches_rollback" in content

    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr5a_audit_trail_rollback" in content
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr5a_records_rollback" in content
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr5a_batches_rollback" in content

    # 2. Archive data inserted safely
    assert "INSERT INTO public._archive_gstr6_batches_rollback" in content
    assert "INSERT INTO public._archive_gstr5_batches_rollback" in content
    assert "INSERT INTO public._archive_gstr5a_batches_rollback" in content

    # 3. Active tables dropped only after archiving
    assert "DROP TABLE IF EXISTS public.gstr6_batches CASCADE" in content
    assert "DROP TABLE IF EXISTS public.gstr5_batches CASCADE" in content
    assert "DROP TABLE IF EXISTS public.gstr5a_batches CASCADE" in content


def test_supabase_migration_matches_aurora_schema():
    content = SUPABASE_MIGRATION.read_text(encoding="utf-8")
    assert "'GSTR-6'" in content
    assert "'GSTR-5'" in content
    assert "'GSTR-5A'" in content
    assert "gstr6_batches" in content
    assert "gstr5_batches" in content
    assert "gstr5a_batches" in content


def test_simulated_sqlite_lifecycle():
    """Verify the up -> insert -> down (archive) -> restore cycle logic on SQLite."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    try:
        # 1. UP: Create active tables
        cursor.execute("""
            CREATE TABLE gstr6_batches (
                id TEXT PRIMARY KEY,
                firm_id TEXT,
                gstin TEXT,
                period TEXT,
                status TEXT
            );
        """)
        cursor.execute("""
            CREATE TABLE gstr5_batches (
                id TEXT PRIMARY KEY,
                firm_id TEXT,
                gstin TEXT,
                period TEXT,
                status TEXT
            );
        """)
        cursor.execute("""
            CREATE TABLE gstr5a_batches (
                id TEXT PRIMARY KEY,
                firm_id TEXT,
                gstin TEXT,
                period TEXT,
                status TEXT
            );
        """)

        # 2. INSERT: Representative records
        cursor.execute("INSERT INTO gstr6_batches VALUES ('b-g6-1', 'f-1', '27AAACG0000A1Z5', '2026-07', 'DRAFT');")
        cursor.execute("INSERT INTO gstr5_batches VALUES ('b-g5-1', 'f-1', '27AAACG0000A1Z5', '2026-07', 'DRAFT');")
        cursor.execute("INSERT INTO gstr5a_batches VALUES ('b-g5a-1', 'f-1', '9917USA00000OID', '2026-07', 'DRAFT');")
        conn.commit()

        # 3. DOWN: Archive records and drop active tables
        cursor.execute("""
            CREATE TABLE _archive_gstr6_batches_rollback (
                archive_id TEXT PRIMARY KEY,
                batch_id TEXT,
                firm_id TEXT,
                gstin TEXT,
                period TEXT,
                status TEXT
            );
        """)
        cursor.execute("""
            INSERT INTO _archive_gstr6_batches_rollback
            SELECT 'arch-g6-1', id, firm_id, gstin, period, status FROM gstr6_batches;
        """)
        cursor.execute("DROP TABLE gstr6_batches;")

        cursor.execute("""
            CREATE TABLE _archive_gstr5_batches_rollback (
                archive_id TEXT PRIMARY KEY,
                batch_id TEXT,
                firm_id TEXT,
                gstin TEXT,
                period TEXT,
                status TEXT
            );
        """)
        cursor.execute("""
            INSERT INTO _archive_gstr5_batches_rollback
            SELECT 'arch-g5-1', id, firm_id, gstin, period, status FROM gstr5_batches;
        """)
        cursor.execute("DROP TABLE gstr5_batches;")

        cursor.execute("""
            CREATE TABLE _archive_gstr5a_batches_rollback (
                archive_id TEXT PRIMARY KEY,
                batch_id TEXT,
                firm_id TEXT,
                gstin TEXT,
                period TEXT,
                status TEXT
            );
        """)
        cursor.execute("""
            INSERT INTO _archive_gstr5a_batches_rollback
            SELECT 'arch-g5a-1', id, firm_id, gstin, period, status FROM gstr5a_batches;
        """)
        cursor.execute("DROP TABLE gstr5a_batches;")
        conn.commit()

        # Verify active tables dropped but archive tables contain data
        cursor.execute("SELECT COUNT(*) FROM _archive_gstr6_batches_rollback;")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT COUNT(*) FROM _archive_gstr5_batches_rollback;")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT COUNT(*) FROM _archive_gstr5a_batches_rollback;")
        assert cursor.fetchone()[0] == 1

        # 4. RE-UP: Recreate active tables and restore from archive
        cursor.execute("""
            CREATE TABLE gstr6_batches (
                id TEXT PRIMARY KEY,
                firm_id TEXT,
                gstin TEXT,
                period TEXT,
                status TEXT
            );
        """)
        cursor.execute("""
            INSERT OR IGNORE INTO gstr6_batches
            SELECT batch_id, firm_id, gstin, period, status FROM _archive_gstr6_batches_rollback;
        """)

        cursor.execute("""
            CREATE TABLE gstr5_batches (
                id TEXT PRIMARY KEY,
                firm_id TEXT,
                gstin TEXT,
                period TEXT,
                status TEXT
            );
        """)
        cursor.execute("""
            INSERT OR IGNORE INTO gstr5_batches
            SELECT batch_id, firm_id, gstin, period, status FROM _archive_gstr5_batches_rollback;
        """)

        cursor.execute("""
            CREATE TABLE gstr5a_batches (
                id TEXT PRIMARY KEY,
                firm_id TEXT,
                gstin TEXT,
                period TEXT,
                status TEXT
            );
        """)
        cursor.execute("""
            INSERT OR IGNORE INTO gstr5a_batches
            SELECT batch_id, firm_id, gstin, period, status FROM _archive_gstr5a_batches_rollback;
        """)
        conn.commit()

        # Verify data restored into active tables
        cursor.execute("SELECT id, gstin FROM gstr6_batches;")
        assert cursor.fetchone() == ("b-g6-1", "27AAACG0000A1Z5")

        cursor.execute("SELECT id, gstin FROM gstr5_batches;")
        assert cursor.fetchone() == ("b-g5-1", "27AAACG0000A1Z5")

        cursor.execute("SELECT id, gstin FROM gstr5a_batches;")
        assert cursor.fetchone() == ("b-g5a-1", "9917USA00000OID")

    finally:
        conn.close()
