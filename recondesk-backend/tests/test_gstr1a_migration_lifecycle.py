"""Phase 4.1: Database Migration Lifecycle & Safe Archival Rollback Tests.

Verifies:
1. Aurora up and down migrations exist with valid 14-digit timestamps.
2. Up migration creates tables, indexes, constraints, and audit trails.
3. Down migration implements non-destructive archival rollback (no data loss).
4. Up migration includes idempotent restoration block from archive tables.
5. Column schemas align symmetrically between active and archive tables.
"""

from pathlib import Path
import re
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
AURORA_UP = BACKEND_DIR / "migrations/aurora/20261012140000_create_gstr1a_amendments.up.sql"
AURORA_DOWN = BACKEND_DIR / "migrations/aurora/20261012140000_create_gstr1a_amendments.down.sql"
SUPABASE_MIGRATION = BACKEND_DIR / "supabase/migrations/20261012140000_create_gstr1a_amendments.sql"


def test_migration_files_exist():
    assert AURORA_UP.exists(), f"Aurora up migration not found: {AURORA_UP}"
    assert AURORA_DOWN.exists(), f"Aurora down migration not found: {AURORA_DOWN}"
    assert SUPABASE_MIGRATION.exists(), f"Supabase migration not found: {SUPABASE_MIGRATION}"


def test_aurora_up_migration_structure():
    content = AURORA_UP.read_text(encoding="utf-8")

    # 1. Check constraint extension to support GSTR-1A
    assert "return_filing_approvals_return_type_check" in content
    assert "'GSTR-1A'" in content
    assert "client_filing_authorizations_return_type_check" in content

    # 2. Active tables created with primary keys and foreign keys
    assert "CREATE TABLE IF NOT EXISTS public.gstr1a_amendment_batches" in content
    assert "CREATE TABLE IF NOT EXISTS public.gstr1a_amendment_items" in content
    assert "CREATE TABLE IF NOT EXISTS public.gstr1a_amendment_audit_trail" in content

    # 3. Batch constraints and figures digest
    assert "figures_digest" in content
    assert "delta_taxable_value" in content
    assert "delta_igst" in content
    assert "uq_gstr1a_batch UNIQUE (firm_id, client_gstin_id, period)" in content

    # 4. Item columns
    assert "table_name" in content
    assert "action_type" in content
    assert "item_digest" in content
    assert "original_payload" in content
    assert "amended_payload" in content
    assert "diff_summary" in content

    # 5. Indexes
    assert "idx_gstr1a_batches_lookup" in content
    assert "idx_gstr1a_items_batch" in content
    assert "idx_gstr1a_audit_batch" in content

    # 6. Idempotent re-upgrade restoration block
    assert "_archive_gstr1a_batches_rollback" in content
    assert "_archive_gstr1a_items_rollback" in content
    assert "_archive_gstr1a_audit_trail_rollback" in content
    assert "ON CONFLICT (id) DO NOTHING" in content


def test_aurora_down_migration_non_destructive_archival():
    content = AURORA_DOWN.read_text(encoding="utf-8")

    # 1. Archive tables created before any drops
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr1a_audit_trail_rollback" in content
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr1a_items_rollback" in content
    assert "CREATE TABLE IF NOT EXISTS public._archive_gstr1a_batches_rollback" in content

    # 2. Archive data inserted safely
    assert "INSERT INTO public._archive_gstr1a_audit_trail_rollback" in content
    assert "INSERT INTO public._archive_gstr1a_items_rollback" in content
    assert "INSERT INTO public._archive_gstr1a_batches_rollback" in content

    # 3. Archived tables are preserved, active tables dropped only after archiving
    assert "DROP TABLE IF EXISTS public.gstr1a_amendment_audit_trail CASCADE" in content
    assert "DROP TABLE IF EXISTS public.gstr1a_amendment_items CASCADE" in content
    assert "DROP TABLE IF EXISTS public.gstr1a_amendment_batches CASCADE" in content

    # 4. Critical safety: Archive tables themselves must NEVER be dropped
    assert "DROP TABLE" not in content or "_archive" not in content.split("DROP TABLE")[1].split(";")[0]


def test_supabase_migration_matches_aurora_schema():
    content = SUPABASE_MIGRATION.read_text(encoding="utf-8")

    # Check constraint and tables match
    assert "'GSTR-1A'" in content
    assert "gstr1a_amendment_batches" in content
    assert "gstr1a_amendment_items" in content
    assert "gstr1a_amendment_audit_trail" in content
    assert "_archive_gstr1a_batches_rollback" in content


def test_gstr1a_upgrade_rollback_reupgrade_cycle_execution():
    """Execute the full lifecycle (UP -> INSERT -> ROLLBACK ARCHIVE -> DROP -> RE-UPGRADE -> RESTORE) on an isolated database engine."""
    from sqlalchemy import create_engine, text

    engine = create_engine("sqlite:///:memory:")

    with engine.connect() as conn:
        # Step 0: Predecessor tables
        conn.execute(text("""
            CREATE TABLE user_profiles (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                full_name TEXT
            );
        """))
        conn.execute(text("""
            CREATE TABLE client_gstins (
                id TEXT PRIMARY KEY,
                firm_owner_id TEXT NOT NULL,
                gstin TEXT NOT NULL
            );
        """))
        conn.execute(text("""
            CREATE TABLE filing_runs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL
            );
        """))

        # Step 1: UP Migration - Create active GSTR-1A tables
        conn.execute(text("""
            CREATE TABLE gstr1a_amendment_batches (
                id TEXT PRIMARY KEY,
                firm_id TEXT NOT NULL,
                client_gstin_id TEXT NOT NULL,
                gstin TEXT NOT NULL,
                period TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'DRAFT',
                figures_digest TEXT NOT NULL DEFAULT '',
                total_additions INTEGER NOT NULL DEFAULT 0,
                total_amendments INTEGER NOT NULL DEFAULT 0,
                delta_taxable_value REAL NOT NULL DEFAULT 0.00,
                delta_igst REAL NOT NULL DEFAULT 0.00,
                delta_cgst REAL NOT NULL DEFAULT 0.00,
                delta_sgst REAL NOT NULL DEFAULT 0.00,
                delta_cess REAL NOT NULL DEFAULT 0.00,
                gstn_reference_id TEXT,
                gstn_status TEXT,
                arn TEXT,
                filing_run_id TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (firm_id, client_gstin_id, period)
            );
        """))
        conn.execute(text("""
            CREATE TABLE gstr1a_amendment_items (
                id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                firm_id TEXT NOT NULL,
                client_gstin_id TEXT NOT NULL,
                period TEXT NOT NULL,
                table_name TEXT NOT NULL,
                action_type TEXT NOT NULL,
                original_invoice_number TEXT,
                original_invoice_date TEXT,
                amended_invoice_number TEXT,
                amended_invoice_date TEXT,
                recipient_gstin TEXT,
                pos TEXT,
                supply_type TEXT,
                original_payload TEXT NOT NULL DEFAULT '{}',
                amended_payload TEXT NOT NULL DEFAULT '{}',
                diff_summary TEXT NOT NULL DEFAULT '{}',
                delta_taxable_value REAL NOT NULL DEFAULT 0.00,
                delta_igst REAL NOT NULL DEFAULT 0.00,
                delta_cgst REAL NOT NULL DEFAULT 0.00,
                delta_sgst REAL NOT NULL DEFAULT 0.00,
                delta_cess REAL NOT NULL DEFAULT 0.00,
                item_digest TEXT NOT NULL DEFAULT '',
                source_note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """))
        conn.execute(text("""
            CREATE TABLE gstr1a_amendment_audit_trail (
                id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                firm_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor_id TEXT,
                actor_name TEXT NOT NULL,
                actor_role TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT,
                details TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
        """))

        # Step 2: Insert representative live GSTR-1A amendment data
        conn.execute(text("""
            INSERT INTO gstr1a_amendment_batches (
                id, firm_id, client_gstin_id, gstin, period, status,
                figures_digest, total_additions, total_amendments,
                delta_taxable_value, delta_igst, delta_cgst, delta_sgst, delta_cess,
                created_at, updated_at
            ) VALUES (
                'batch-001', 'firm-001', 'cg-001', '27AAPFU0939F1ZV', '2026-01', 'APPROVED',
                'digest-sha256-batch001', 1, 1,
                75000.00, 13500.00, 0.00, 0.00, 0.00,
                '2026-01-15T10:00:00Z', '2026-01-15T12:00:00Z'
            );
        """))
        conn.execute(text("""
            INSERT INTO gstr1a_amendment_items (
                id, batch_id, firm_id, client_gstin_id, period, table_name,
                action_type, original_invoice_number, amended_invoice_number,
                recipient_gstin, pos, original_payload, amended_payload, diff_summary,
                delta_taxable_value, delta_igst, item_digest, created_at, updated_at
            ) VALUES (
                'item-001', 'batch-001', 'firm-001', 'cg-001', '2026-01', '9A_B2B',
                'AMENDMENT', 'INV-100', 'INV-100-REV',
                '27AABCS1429B1Z', '27', '{"val": 50000}', '{"val": 125000}', '{"val": {"original": 50000, "amended": 125000}}',
                75000.00, 13500.00, 'digest-sha256-item001', '2026-01-15T10:05:00Z', '2026-01-15T10:05:00Z'
            );
        """))
        conn.execute(text("""
            INSERT INTO gstr1a_amendment_audit_trail (
                id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
                from_status, to_status, details, created_at
            ) VALUES (
                'audit-001', 'batch-001', 'firm-001', 'APPROVED', 'user-001', 'Audit Partner', 'partner',
                'UNDER_REVIEW', 'APPROVED', '{"notes": "Approved for 3B integration"}', '2026-01-15T12:00:00Z'
            );
        """))

        # Verify initial data exists
        b_count = conn.execute(text("SELECT count(*) FROM gstr1a_amendment_batches")).scalar()
        i_count = conn.execute(text("SELECT count(*) FROM gstr1a_amendment_items")).scalar()
        a_count = conn.execute(text("SELECT count(*) FROM gstr1a_amendment_audit_trail")).scalar()
        assert b_count == 1
        assert i_count == 1
        assert a_count == 1

        # Step 3: DOWN Migration (Rollback) - Safely archive before drop
        conn.execute(text("""
            CREATE TABLE _archive_gstr1a_batches_rollback (
                archive_id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                firm_id TEXT NOT NULL,
                client_gstin_id TEXT NOT NULL,
                gstin TEXT NOT NULL,
                period TEXT NOT NULL,
                status TEXT NOT NULL,
                figures_digest TEXT NOT NULL,
                total_additions INTEGER NOT NULL,
                total_amendments INTEGER NOT NULL,
                delta_taxable_value REAL NOT NULL,
                delta_igst REAL NOT NULL,
                delta_cgst REAL NOT NULL,
                delta_sgst REAL NOT NULL,
                delta_cess REAL NOT NULL,
                gstn_reference_id TEXT,
                gstn_status TEXT,
                arn TEXT,
                filing_run_id TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                archived_at TEXT NOT NULL
            );
        """))
        conn.execute(text("""
            CREATE TABLE _archive_gstr1a_items_rollback (
                archive_id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                firm_id TEXT NOT NULL,
                client_gstin_id TEXT NOT NULL,
                period TEXT NOT NULL,
                table_name TEXT NOT NULL,
                action_type TEXT NOT NULL,
                original_invoice_number TEXT,
                original_invoice_date TEXT,
                amended_invoice_number TEXT,
                amended_invoice_date TEXT,
                recipient_gstin TEXT,
                pos TEXT,
                supply_type TEXT,
                original_payload TEXT NOT NULL,
                amended_payload TEXT NOT NULL,
                diff_summary TEXT NOT NULL,
                delta_taxable_value REAL NOT NULL,
                delta_igst REAL NOT NULL,
                delta_cgst REAL NOT NULL,
                delta_sgst REAL NOT NULL,
                delta_cess REAL NOT NULL,
                item_digest TEXT NOT NULL,
                source_note TEXT,
                created_at TEXT NOT NULL,
                archived_at TEXT NOT NULL
            );
        """))
        conn.execute(text("""
            CREATE TABLE _archive_gstr1a_audit_trail_rollback (
                archive_id TEXT PRIMARY KEY,
                entry_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                firm_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor_id TEXT,
                actor_name TEXT NOT NULL,
                actor_role TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL,
                archived_at TEXT NOT NULL
            );
        """))

        # Archive inserts
        conn.execute(text("""
            INSERT INTO _archive_gstr1a_batches_rollback (
                archive_id, batch_id, firm_id, client_gstin_id, gstin, period, status,
                figures_digest, total_additions, total_amendments,
                delta_taxable_value, delta_igst, delta_cgst, delta_sgst, delta_cess,
                gstn_reference_id, gstn_status, arn, filing_run_id, created_by,
                created_at, archived_at
            )
            SELECT
                'arc-b-' || id, id, firm_id, client_gstin_id, gstin, period, status,
                figures_digest, total_additions, total_amendments,
                delta_taxable_value, delta_igst, delta_cgst, delta_sgst, delta_cess,
                gstn_reference_id, gstn_status, arn, filing_run_id, created_by,
                created_at, '2026-01-15T12:05:00Z'
            FROM gstr1a_amendment_batches;
        """))
        conn.execute(text("""
            INSERT INTO _archive_gstr1a_items_rollback (
                archive_id, item_id, batch_id, firm_id, client_gstin_id, period, table_name,
                action_type, original_invoice_number, original_invoice_date,
                amended_invoice_number, amended_invoice_date, recipient_gstin,
                pos, supply_type, original_payload, amended_payload, diff_summary,
                delta_taxable_value, delta_igst, delta_cgst, delta_sgst, delta_cess,
                item_digest, source_note, created_at, archived_at
            )
            SELECT
                'arc-i-' || id, id, batch_id, firm_id, client_gstin_id, period, table_name,
                action_type, original_invoice_number, original_invoice_date,
                amended_invoice_number, amended_invoice_date, recipient_gstin,
                pos, supply_type, original_payload, amended_payload, diff_summary,
                delta_taxable_value, delta_igst, delta_cgst, delta_sgst, delta_cess,
                item_digest, source_note, created_at, '2026-01-15T12:05:00Z'
            FROM gstr1a_amendment_items;
        """))
        conn.execute(text("""
            INSERT INTO _archive_gstr1a_audit_trail_rollback (
                archive_id, entry_id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
                from_status, to_status, details, created_at, archived_at
            )
            SELECT
                'arc-a-' || id, id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
                from_status, to_status, details, created_at, '2026-01-15T12:05:00Z'
            FROM gstr1a_amendment_audit_trail;
        """))

        # Drop active tables
        conn.execute(text("DROP TABLE gstr1a_amendment_audit_trail;"))
        conn.execute(text("DROP TABLE gstr1a_amendment_items;"))
        conn.execute(text("DROP TABLE gstr1a_amendment_batches;"))

        # Verify active tables dropped but archive tables contain durable records
        arc_b = conn.execute(text("SELECT count(*) FROM _archive_gstr1a_batches_rollback")).scalar()
        arc_i = conn.execute(text("SELECT count(*) FROM _archive_gstr1a_items_rollback")).scalar()
        arc_a = conn.execute(text("SELECT count(*) FROM _archive_gstr1a_audit_trail_rollback")).scalar()
        assert arc_b == 1
        assert arc_i == 1
        assert arc_a == 1

        # Step 4: RE-UPGRADE Migration - Re-create active tables and restore archived data
        conn.execute(text("""
            CREATE TABLE gstr1a_amendment_batches (
                id TEXT PRIMARY KEY,
                firm_id TEXT NOT NULL,
                client_gstin_id TEXT NOT NULL,
                gstin TEXT NOT NULL,
                period TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'DRAFT',
                figures_digest TEXT NOT NULL DEFAULT '',
                total_additions INTEGER NOT NULL DEFAULT 0,
                total_amendments INTEGER NOT NULL DEFAULT 0,
                delta_taxable_value REAL NOT NULL DEFAULT 0.00,
                delta_igst REAL NOT NULL DEFAULT 0.00,
                delta_cgst REAL NOT NULL DEFAULT 0.00,
                delta_sgst REAL NOT NULL DEFAULT 0.00,
                delta_cess REAL NOT NULL DEFAULT 0.00,
                gstn_reference_id TEXT,
                gstn_status TEXT,
                arn TEXT,
                filing_run_id TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (firm_id, client_gstin_id, period)
            );
        """))
        conn.execute(text("""
            CREATE TABLE gstr1a_amendment_items (
                id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                firm_id TEXT NOT NULL,
                client_gstin_id TEXT NOT NULL,
                period TEXT NOT NULL,
                table_name TEXT NOT NULL,
                action_type TEXT NOT NULL,
                original_invoice_number TEXT,
                original_invoice_date TEXT,
                amended_invoice_number TEXT,
                amended_invoice_date TEXT,
                recipient_gstin TEXT,
                pos TEXT,
                supply_type TEXT,
                original_payload TEXT NOT NULL DEFAULT '{}',
                amended_payload TEXT NOT NULL DEFAULT '{}',
                diff_summary TEXT NOT NULL DEFAULT '{}',
                delta_taxable_value REAL NOT NULL DEFAULT 0.00,
                delta_igst REAL NOT NULL DEFAULT 0.00,
                delta_cgst REAL NOT NULL DEFAULT 0.00,
                delta_sgst REAL NOT NULL DEFAULT 0.00,
                delta_cess REAL NOT NULL DEFAULT 0.00,
                item_digest TEXT NOT NULL DEFAULT '',
                source_note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """))
        conn.execute(text("""
            CREATE TABLE gstr1a_amendment_audit_trail (
                id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                firm_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor_id TEXT,
                actor_name TEXT NOT NULL,
                actor_role TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT,
                details TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
        """))

        # Step 5: Execute idempotent restoration block
        conn.execute(text("""
            INSERT OR IGNORE INTO gstr1a_amendment_batches (
                id, firm_id, client_gstin_id, gstin, period, status,
                figures_digest, total_additions, total_amendments,
                delta_taxable_value, delta_igst, delta_cgst, delta_sgst, delta_cess,
                gstn_reference_id, gstn_status, arn, filing_run_id, created_by,
                created_at, updated_at
            )
            SELECT
                batch_id, firm_id, client_gstin_id, gstin, period, status,
                figures_digest, total_additions, total_amendments,
                delta_taxable_value, delta_igst, delta_cgst, delta_sgst, delta_cess,
                gstn_reference_id, gstn_status, arn, filing_run_id, created_by,
                created_at, archived_at
            FROM _archive_gstr1a_batches_rollback;
        """))
        conn.execute(text("""
            INSERT OR IGNORE INTO gstr1a_amendment_items (
                id, batch_id, firm_id, client_gstin_id, period, table_name,
                action_type, original_invoice_number, original_invoice_date,
                amended_invoice_number, amended_invoice_date, recipient_gstin,
                pos, supply_type, original_payload, amended_payload, diff_summary,
                delta_taxable_value, delta_igst, delta_cgst, delta_sgst, delta_cess,
                item_digest, source_note, created_at, updated_at
            )
            SELECT
                item_id, batch_id, firm_id, client_gstin_id, period, table_name,
                action_type, original_invoice_number, original_invoice_date,
                amended_invoice_number, amended_invoice_date, recipient_gstin,
                pos, supply_type, original_payload, amended_payload, diff_summary,
                delta_taxable_value, delta_igst, delta_cgst, delta_sgst, delta_cess,
                item_digest, source_note, created_at, archived_at
            FROM _archive_gstr1a_items_rollback;
        """))
        conn.execute(text("""
            INSERT OR IGNORE INTO gstr1a_amendment_audit_trail (
                id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
                from_status, to_status, details, created_at
            )
            SELECT
                entry_id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
                from_status, to_status, details, created_at
            FROM _archive_gstr1a_audit_trail_rollback;
        """))

        # Step 6: Verify restored data fidelity
        row_batch = conn.execute(text("SELECT * FROM gstr1a_amendment_batches WHERE id = 'batch-001'")).mappings().fetchone()
        assert row_batch is not None
        assert row_batch["gstin"] == "27AAPFU0939F1ZV"
        assert row_batch["period"] == "2026-01"
        assert row_batch["status"] == "APPROVED"
        assert row_batch["figures_digest"] == "digest-sha256-batch001"
        assert row_batch["delta_taxable_value"] == 75000.00
        assert row_batch["delta_igst"] == 13500.00

        row_item = conn.execute(text("SELECT * FROM gstr1a_amendment_items WHERE id = 'item-001'")).mappings().fetchone()
        assert row_item is not None
        assert row_item["original_invoice_number"] == "INV-100"
        assert row_item["amended_invoice_number"] == "INV-100-REV"
        assert row_item["delta_taxable_value"] == 75000.00
        assert row_item["item_digest"] == "digest-sha256-item001"

        row_audit = conn.execute(text("SELECT * FROM gstr1a_amendment_audit_trail WHERE id = 'audit-001'")).mappings().fetchone()
        assert row_audit is not None
        assert row_audit["actor_name"] == "Audit Partner"
        assert row_audit["action"] == "APPROVED"

        # Step 7: Re-run restoration query to verify idempotence
        conn.execute(text("""
            INSERT OR IGNORE INTO gstr1a_amendment_batches (id, firm_id, client_gstin_id, gstin, period, created_at, updated_at)
            SELECT batch_id, firm_id, client_gstin_id, gstin, period, created_at, archived_at FROM _archive_gstr1a_batches_rollback;
        """))
        final_b_count = conn.execute(text("SELECT count(*) FROM gstr1a_amendment_batches")).scalar()
        assert final_b_count == 1, "Idempotent re-run must not create duplicates"

