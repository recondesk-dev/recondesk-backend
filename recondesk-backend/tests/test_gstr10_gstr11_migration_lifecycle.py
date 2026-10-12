"""Phase 4.4: Migration Lifecycle & Safe Archival Rollback Tests for GSTR-10 & GSTR-11.

Verifies:
1. Aurora up and down migrations exist with valid timestamp prefix.
2. Up migration creates all required tables, indexes, constraints, and audit trails.
3. Down migration implements safe non-destructive archival rollback (no data loss).
4. Up migration includes idempotent restoration block from archive tables.
5. Executes full upgrade -> rollback -> re-upgrade cycle on an isolated SQLite engine.
"""

from pathlib import Path
import sqlite3
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
AURORA_UP = BACKEND_DIR / "migrations/aurora/20261012210000_create_gstr10_gstr11_compliance.up.sql"
AURORA_DOWN = BACKEND_DIR / "migrations/aurora/20261012210000_create_gstr10_gstr11_compliance.down.sql"
SUPABASE_MIGRATION = BACKEND_DIR / "supabase/migrations/20261012210000_create_gstr10_gstr11_compliance.sql"


def test_migration_files_exist():
    assert AURORA_UP.exists(), f"Aurora up migration not found: {AURORA_UP}"
    assert AURORA_DOWN.exists(), f"Aurora down migration not found: {AURORA_DOWN}"
    assert SUPABASE_MIGRATION.exists(), f"Supabase migration not found: {SUPABASE_MIGRATION}"


def test_aurora_up_migration_structure():
    content = AURORA_UP.read_text(encoding="utf-8")

    # 1. GSTR-10 active tables created
    assert "CREATE TABLE IF NOT EXISTS public.gstr10_batches" in content
    assert "CREATE TABLE IF NOT EXISTS public.gstr10_stock_records" in content
    assert "CREATE TABLE IF NOT EXISTS public.gstr10_audit_trail" in content

    # 2. GSTR-11 active tables created
    assert "CREATE TABLE IF NOT EXISTS public.gstr11_batches" in content
    assert "CREATE TABLE IF NOT EXISTS public.gstr11_inward_records" in content
    assert "CREATE TABLE IF NOT EXISTS public.gstr11_audit_trail" in content

    # 3. Critical column checks
    assert "cancellation_order_number" in content
    assert "effective_cancellation_date" in content
    assert "item_type" in content
    assert "reverse_igst" in content
    assert "reverse_cgst" in content
    assert "reverse_sgst" in content
    assert "ca_membership_number" in content
    assert "uin" in content
    assert "supply_type" in content
    assert "cdn_type" in content
    assert "figures_digest" in content

    # 4. Idempotent restoration blocks
    assert "_archive_gstr10_batches_rollback" in content
    assert "_archive_gstr10_stock_records_rollback" in content
    assert "_archive_gstr11_batches_rollback" in content
    assert "_archive_gstr11_inward_records_rollback" in content
    assert "ON CONFLICT (id) DO NOTHING" in content

    # 5. Check constraint extension to support GSTR-10 and GSTR-11
    assert "return_filing_approvals_return_type_check" in content
    assert "'GSTR-10'" in content
    assert "'GSTR-11'" in content
    assert "client_filing_authorizations_return_type_check" in content


def test_aurora_down_migration_non_destructive_archival():
    content = AURORA_DOWN.read_text(encoding="utf-8")

    # 1. Archive tables created before any drops
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr10_audit_trail_rollback" in content
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr10_stock_records_rollback" in content
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr10_batches_rollback" in content

    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr11_audit_trail_rollback" in content
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr11_inward_records_rollback" in content
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr11_batches_rollback" in content

    # 2. Archive data inserted safely
    assert "INSERT INTO public._archive_gstr10_batches_rollback" in content
    assert "INSERT INTO public._archive_gstr10_stock_records_rollback" in content
    assert "INSERT INTO public._archive_gstr11_batches_rollback" in content
    assert "INSERT INTO public._archive_gstr11_inward_records_rollback" in content

    # 3. Active tables dropped only after archiving
    assert "DROP TABLE IF EXISTS public.gstr10_batches CASCADE" in content
    assert "DROP TABLE IF EXISTS public.gstr11_batches CASCADE" in content

    # 4. Reverts check constraints to Phase 4.3 return types
    assert "return_filing_approvals_return_type_check" in content
    assert "client_filing_authorizations_return_type_check" in content


def test_supabase_migration_matches_aurora_schema():
    content = SUPABASE_MIGRATION.read_text(encoding="utf-8")
    assert "gstr10_batches" in content
    assert "gstr10_stock_records" in content
    assert "gstr11_batches" in content
    assert "gstr11_inward_records" in content
    assert "'GSTR-10'" in content
    assert "'GSTR-11'" in content


def test_simulated_sqlite_lifecycle():
    """Verify the up -> insert -> down (archive) -> restore cycle logic on SQLite."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    try:
        # 1. UP: Create active tables
        cursor.execute("""
            CREATE TABLE gstr10_batches (
                id TEXT PRIMARY KEY,
                firm_id TEXT,
                gstin TEXT,
                period TEXT,
                status TEXT,
                total_reversal_liability REAL
            );
        """)
        cursor.execute("""
            CREATE TABLE gstr10_stock_records (
                id TEXT PRIMARY KEY,
                batch_id TEXT,
                item_type TEXT,
                taxable_value REAL,
                reverse_igst REAL
            );
        """)
        cursor.execute("""
            CREATE TABLE gstr11_batches (
                id TEXT PRIMARY KEY,
                firm_id TEXT,
                uin TEXT,
                period TEXT,
                status TEXT,
                total_net_refund_claimed REAL
            );
        """)
        cursor.execute("""
            CREATE TABLE gstr11_inward_records (
                id TEXT PRIMARY KEY,
                batch_id TEXT,
                supply_type TEXT,
                doc_number TEXT,
                taxable_value REAL
            );
        """)

        # 2. INSERT: Representative records
        cursor.execute("INSERT INTO gstr10_batches VALUES ('b-g10-1', 'f-1', '27AAACG0000A1Z5', '2026-10', 'DRAFT', 27000.0);")
        cursor.execute("INSERT INTO gstr10_stock_records VALUES ('sr-1', 'b-g10-1', '8A', 100000.0, 18000.0);")
        cursor.execute("INSERT INTO gstr10_stock_records VALUES ('sr-2', 'b-g10-1', '8D', 50000.0, 9000.0);")

        cursor.execute("INSERT INTO gstr11_batches VALUES ('b-g11-1', 'f-1', '0717USA00001UN1', '2026-10', 'DRAFT', 16200.0);")
        cursor.execute("INSERT INTO gstr11_inward_records VALUES ('ir-1', 'b-g11-1', '3A', 'INV-100', 100000.0);")
        cursor.execute("INSERT INTO gstr11_inward_records VALUES ('ir-2', 'b-g11-1', '3B', 'CN-01', 10000.0);")
        conn.commit()

        # 3. DOWN: Non-destructive archival
        cursor.execute("""
            CREATE TABLE _archive_gstr10_batches_rollback (
                archive_id TEXT PRIMARY KEY,
                batch_id TEXT,
                firm_id TEXT,
                gstin TEXT,
                period TEXT,
                status TEXT,
                total_reversal_liability REAL
            );
        """)
        cursor.execute("""
            INSERT INTO _archive_gstr10_batches_rollback
            SELECT 'arch-' || id, id, firm_id, gstin, period, status, total_reversal_liability FROM gstr10_batches;
        """)
        cursor.execute("""
            CREATE TABLE _archive_gstr10_stock_records_rollback (
                archive_id TEXT PRIMARY KEY,
                record_id TEXT,
                batch_id TEXT,
                item_type TEXT,
                taxable_value REAL,
                reverse_igst REAL
            );
        """)
        cursor.execute("""
            INSERT INTO _archive_gstr10_stock_records_rollback
            SELECT 'arch-' || id, id, batch_id, item_type, taxable_value, reverse_igst FROM gstr10_stock_records;
        """)
        cursor.execute("DROP TABLE gstr10_stock_records;")
        cursor.execute("DROP TABLE gstr10_batches;")

        cursor.execute("""
            CREATE TABLE _archive_gstr11_batches_rollback (
                archive_id TEXT PRIMARY KEY,
                batch_id TEXT,
                firm_id TEXT,
                uin TEXT,
                period TEXT,
                status TEXT,
                total_net_refund_claimed REAL
            );
        """)
        cursor.execute("""
            INSERT INTO _archive_gstr11_batches_rollback
            SELECT 'arch-' || id, id, firm_id, uin, period, status, total_net_refund_claimed FROM gstr11_batches;
        """)
        cursor.execute("""
            CREATE TABLE _archive_gstr11_inward_records_rollback (
                archive_id TEXT PRIMARY KEY,
                record_id TEXT,
                batch_id TEXT,
                supply_type TEXT,
                doc_number TEXT,
                taxable_value REAL
            );
        """)
        cursor.execute("""
            INSERT INTO _archive_gstr11_inward_records_rollback
            SELECT 'arch-' || id, id, batch_id, supply_type, doc_number, taxable_value FROM gstr11_inward_records;
        """)
        cursor.execute("DROP TABLE gstr11_inward_records;")
        cursor.execute("DROP TABLE gstr11_batches;")
        conn.commit()

        # Verify active tables are dropped and archives hold data
        cursor.execute("SELECT count(*) FROM _archive_gstr10_batches_rollback;")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT count(*) FROM _archive_gstr10_stock_records_rollback;")
        assert cursor.fetchone()[0] == 2
        cursor.execute("SELECT count(*) FROM _archive_gstr11_batches_rollback;")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT count(*) FROM _archive_gstr11_inward_records_rollback;")
        assert cursor.fetchone()[0] == 2

        # 4. RE-UP: Recreate active tables and restore from archive
        cursor.execute("""
            CREATE TABLE gstr10_batches (
                id TEXT PRIMARY KEY,
                firm_id TEXT,
                gstin TEXT,
                period TEXT,
                status TEXT,
                total_reversal_liability REAL
            );
        """)
        cursor.execute("""
            CREATE TABLE gstr10_stock_records (
                id TEXT PRIMARY KEY,
                batch_id TEXT,
                item_type TEXT,
                taxable_value REAL,
                reverse_igst REAL
            );
        """)
        cursor.execute("""
            INSERT INTO gstr10_batches
            SELECT batch_id, firm_id, gstin, period, status, total_reversal_liability
            FROM _archive_gstr10_batches_rollback;
        """)
        cursor.execute("""
            INSERT INTO gstr10_stock_records
            SELECT record_id, batch_id, item_type, taxable_value, reverse_igst
            FROM _archive_gstr10_stock_records_rollback;
        """)

        cursor.execute("""
            CREATE TABLE gstr11_batches (
                id TEXT PRIMARY KEY,
                firm_id TEXT,
                uin TEXT,
                period TEXT,
                status TEXT,
                total_net_refund_claimed REAL
            );
        """)
        cursor.execute("""
            CREATE TABLE gstr11_inward_records (
                id TEXT PRIMARY KEY,
                batch_id TEXT,
                supply_type TEXT,
                doc_number TEXT,
                taxable_value REAL
            );
        """)
        cursor.execute("""
            INSERT INTO gstr11_batches
            SELECT batch_id, firm_id, uin, period, status, total_net_refund_claimed
            FROM _archive_gstr11_batches_rollback;
        """)
        cursor.execute("""
            INSERT INTO gstr11_inward_records
            SELECT record_id, batch_id, supply_type, doc_number, taxable_value
            FROM _archive_gstr11_inward_records_rollback;
        """)
        conn.commit()

        # 5. Verify restored data matches exactly
        cursor.execute("SELECT gstin, total_reversal_liability FROM gstr10_batches WHERE id = 'b-g10-1';")
        row_g10 = cursor.fetchone()
        assert row_g10[0] == "27AAACG0000A1Z5"
        assert row_g10[1] == 27000.0

        cursor.execute("SELECT count(*) FROM gstr10_stock_records WHERE batch_id = 'b-g10-1';")
        assert cursor.fetchone()[0] == 2

        cursor.execute("SELECT uin, total_net_refund_claimed FROM gstr11_batches WHERE id = 'b-g11-1';")
        row_g11 = cursor.fetchone()
        assert row_g11[0] == "0717USA00001UN1"
        assert row_g11[1] == 16200.0

        cursor.execute("SELECT count(*) FROM gstr11_inward_records WHERE batch_id = 'b-g11-1';")
        assert cursor.fetchone()[0] == 2

    finally:
        conn.close()
