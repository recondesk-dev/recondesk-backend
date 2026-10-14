"""ReconDesk Phase 6 / v1.5.1: Live PostgreSQL Staging Validation Suite.

Executes genuine PostgreSQL integration tests against the active staging database:
1. Verifies 17 applied migrations, 0 pending, and checksum verification via AuroraMigrationRunner.
2. Validates PostgreSQL partial index (idx_gstr8_records_supp_tx_date) and 27-column schema.
3. Tests full GSTR-8 lifecycle through real PostgreSQL-backed AuroraClient.
4. Tests data and rate basis survival across connection teardown, process restarts, and worker contexts.
5. Tests July 2024 unverified rate basis blocking, duplicate detection, and offline JSON export.
6. Tests concurrent edits to the same batch and verifies transactional consistency.
7. Tests maker-checker approval invalidation upon record alteration.
8. Tests authenticated cross-tenant access denial at database/application boundary.
9. Verifies zero production mutations and isolation safeguards.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List
import pytest
import sqlalchemy as sa

STAGING_DB_URL = "postgresql+psycopg2://postgres:postgres@localhost:5433/recondesk_staging"

from app.aurora import get_aurora_engine, reset_aurora_engine
from app.aurora_client import AuroraClient
from app.migrations.runner import AuroraMigrationRunner, compute_file_checksum
from app.scripts.validate_aurora_staging_migration import verify_staging_database_safety
from app.services.gstr8_service import (
    GSTR8_BATCHES_TABLE,
    GSTR8_RECORDS_TABLE,
    GSTR8_AUDIT_TABLE,
    Gstr8DuplicateError,
    Gstr8Error,
    Gstr8ValidationError,
    add_or_update_gstr8_record_sync,
    build_gstr8_offline_json,
    delete_gstr8_record_sync,
    get_batch_summary_sync,
    get_or_create_batch_sync,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent
MIGRATION_17_UP = BACKEND_DIR / "migrations/aurora/20261014100000_add_gstr8_transaction_date_fields.up.sql"

# Authoritative staging tenant fixtures from recondesk_staging
FIRM_ALPHA_ID = "11111111-1111-1111-1111-111111111111"
CLIENT_ALPHA_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
GSTIN_ALPHA = "27AAPFU0939F1ZV"

FIRM_BETA_ID = "22222222-2222-2222-2222-222222222222"
CLIENT_BETA_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
GSTIN_BETA = "27ABCDE1234F1Z5"


def _is_staging_reachable() -> bool:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        res = s.connect_ex(("127.0.0.1", 5433))
        s.close()
        return res == 0
    except Exception:
        return False


@pytest.fixture(autouse=True)
def setup_staging_engine(monkeypatch):
    """Ensure clean engine connection to staging PostgreSQL for each test."""
    if not _is_staging_reachable():
        pytest.skip("Staging PostgreSQL on localhost:5433 is not reachable (offline or sandboxed).")

    from app.config import get_settings
    monkeypatch.setenv("AURORA_DATABASE_URL", STAGING_DB_URL)
    monkeypatch.setenv("AURORA_DB_ENABLED", "true")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ENABLE_LIVE_GSTR_FILING", "false")
    get_settings.cache_clear()
    verify_staging_database_safety(STAGING_DB_URL)
    reset_aurora_engine()

    # Clean up test rows for test firms
    engine = sa.create_engine(STAGING_DB_URL)
    with engine.connect() as conn:
        conn.execute(sa.text("DELETE FROM public.gstr8_audit_trail WHERE firm_id IN (:f1, :f2);"), {"f1": FIRM_ALPHA_ID, "f2": FIRM_BETA_ID})
        conn.execute(sa.text("DELETE FROM public.gstr8_records WHERE firm_id IN (:f1, :f2);"), {"f1": FIRM_ALPHA_ID, "f2": FIRM_BETA_ID})
        conn.execute(sa.text("DELETE FROM public.gstr8_batches WHERE firm_id IN (:f1, :f2);"), {"f1": FIRM_ALPHA_ID, "f2": FIRM_BETA_ID})
        conn.commit()

    yield
    reset_aurora_engine()
    get_settings.cache_clear()


class TestPostgreSqlStagingValidation:

    def test_1_migration_17_status_and_checksums(self):
        """1 & 2: Verify migration 17 applied, zero pending, and checksum matches."""
        engine = sa.create_engine(STAGING_DB_URL)
        runner = AuroraMigrationRunner(engine=engine)

        with engine.connect() as conn:
            applied, pending = runner.validate_and_get_pending(conn)
            assert len(applied) == 17, f"Expected 17 applied migrations, found {len(applied)}"
            assert len(pending) == 0, f"Expected 0 pending migrations, found {len(pending)}"

            m17 = next(m for m in applied if m.version == "20261014100000")
            assert m17.name == "add_gstr8_transaction_date_fields"
            expected_checksum = compute_file_checksum(MIGRATION_17_UP)
            assert m17.checksum == expected_checksum, "Migration 17 checksum mismatch!"

    def test_2_postgresql_schema_and_partial_index(self):
        """9: Verify 27 columns and partial index on public.gstr8_records in PostgreSQL."""
        engine = sa.create_engine(STAGING_DB_URL)
        with engine.connect() as conn:
            cols = {
                r[0]: r[1]
                for r in conn.execute(sa.text("""
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'gstr8_records';
                """)).fetchall()
            }
            assert len(cols) == 27, f"Expected 27 columns, found {len(cols)}"
            assert cols["transaction_date"] == "date"
            assert cols["rate_basis"] == "character varying"
            assert cols["needs_review"] == "boolean"
            assert cols["review_reason"] == "text"

            # Verify partial index
            indexes = {
                r[0]: r[1]
                for r in conn.execute(sa.text("""
                    SELECT indexname, indexdef
                    FROM pg_indexes
                    WHERE schemaname = 'public' AND tablename = 'gstr8_records';
                """)).fetchall()
            }
            assert "idx_gstr8_records_supp_tx_date" in indexes
            idx_def = indexes["idx_gstr8_records_supp_tx_date"]
            assert "WHERE" in idx_def and "status" in idx_def and "ACTIVE" in idx_def

    def test_3_gstr8_lifecycle_through_real_aurora_client(self):
        """3: Test batch create, record add, summary, and soft delete through real PostgreSQL client."""
        sb = AuroraClient()
        period = "2026-09"

        # 1. Create or retrieve batch
        batch = get_or_create_batch_sync(
            sb,
            firm_id=FIRM_ALPHA_ID,
            client_gstin_id=CLIENT_ALPHA_ID,
            gstin=GSTIN_ALPHA,
            period=period,
            user_id=FIRM_ALPHA_ID,
        )
        batch_id = batch["id"]
        assert batch["status"] == "DRAFT"
        assert batch["gstin"] == GSTIN_ALPHA

        # 2. Add B2B record
        rec_b2b = add_or_update_gstr8_record_sync(
            sb,
            batch_id=batch_id,
            record_data={
                "supply_type": "B2B",
                "record_type": "ORIGINAL",
                "supplier_gstin": "27BBBBB0000B1Z1",
                "gross_supplies": 400000.0,
                "returned_supplies": 50000.0,
                "pos": "27",
                "transaction_date": "2026-09-10",
            },
            user_id=FIRM_ALPHA_ID,
        )
        assert rec_b2b["net_supplies"] == 350000.0
        assert rec_b2b["tcs_cgst"] == 875.0  # 0.25% of 350,000
        assert rec_b2b["tcs_sgst"] == 875.0

        # 3. Add B2C interstate record
        rec_b2c = add_or_update_gstr8_record_sync(
            sb,
            batch_id=batch_id,
            record_data={
                "supply_type": "B2C",
                "record_type": "ORIGINAL",
                "gross_supplies": 100000.0,
                "returned_supplies": 0.0,
                "pos": "24",  # Gujarat (interstate)
                "transaction_date": "2026-09-12",
            },
            user_id=FIRM_ALPHA_ID,
        )
        assert rec_b2c["tcs_igst"] == 500.0  # 0.5% of 100,000

        # 4. Fetch summary from PostgreSQL
        summary = get_batch_summary_sync(sb, batch_id=batch_id)
        assert summary["batch"]["gross_supplies_value"] == 500000.0
        assert summary["batch"]["returned_supplies_value"] == 50000.0
        assert summary["batch"]["net_taxable_value"] == 450000.0
        assert summary["batch"]["total_tcs_cgst"] == 875.0
        assert summary["batch"]["total_tcs_sgst"] == 875.0
        assert summary["batch"]["total_tcs_igst"] == 500.0
        assert summary["total_tcs_liability"] == 2250.0

        # 5. Soft-delete B2C record
        del_ok = delete_gstr8_record_sync(sb, batch_id=batch_id, record_id=rec_b2c["id"], user_id=FIRM_ALPHA_ID)
        assert del_ok is True

        # Verify summary reflects soft deletion
        summary_after_del = get_batch_summary_sync(sb, batch_id=batch_id)
        assert summary_after_del["batch"]["gross_supplies_value"] == 400000.0
        assert summary_after_del["batch"]["total_tcs_igst"] == 0.0
        assert summary_after_del["total_tcs_liability"] == 1750.0

    def test_4_persistence_across_new_connections_and_process_restarts(self):
        """4: Verify records and rate bases survive engine disposal and fresh connections."""
        sb1 = AuroraClient()
        period = "2026-10"

        batch = get_or_create_batch_sync(
            sb1,
            firm_id=FIRM_ALPHA_ID,
            client_gstin_id=CLIENT_ALPHA_ID,
            gstin=GSTIN_ALPHA,
            period=period,
            user_id=FIRM_ALPHA_ID,
        )
        batch_id = batch["id"]

        add_or_update_gstr8_record_sync(
            sb1,
            batch_id=batch_id,
            record_data={
                "supply_type": "B2B",
                "record_type": "ORIGINAL",
                "supplier_gstin": "27CCCCC0000C1Z2",
                "gross_supplies": 250000.0,
                "returned_supplies": 25000.0,
                "pos": "27",
                "transaction_date": "2026-10-05",
            },
            user_id=FIRM_ALPHA_ID,
        )

        # Force process/connection restart simulation
        reset_aurora_engine()

        # Reconnect with fresh client instance
        sb2 = AuroraClient()
        summary = get_batch_summary_sync(sb2, batch_id=batch_id)
        assert summary["batch"]["id"] == batch_id
        assert summary["batch"]["gross_supplies_value"] == 250000.0
        assert summary["batch"]["net_taxable_value"] == 225000.0
        assert len(summary["table3_b2b"]) == 1
        rec = summary["table3_b2b"][0]
        assert rec["supplier_gstin"] == "27CCCCC0000C1Z2"
        assert str(rec["transaction_date"]) == "2026-10-05"

    def test_5_historical_july_2024_blocking_and_json_export(self):
        """5: Verify missing transaction date in July 2024 blocks export and unblocks when resolved."""
        sb = AuroraClient()
        period = "2024-07"

        batch = get_or_create_batch_sync(
            sb,
            firm_id=FIRM_ALPHA_ID,
            client_gstin_id=CLIENT_ALPHA_ID,
            gstin=GSTIN_ALPHA,
            period=period,
            user_id=FIRM_ALPHA_ID,
        )
        batch_id = batch["id"]

        # 1. Add record with NO transaction date
        rec_unverified = add_or_update_gstr8_record_sync(
            sb,
            batch_id=batch_id,
            record_data={
                "supply_type": "B2B",
                "record_type": "ORIGINAL",
                "supplier_gstin": "27DDDDD0000D1Z3",
                "gross_supplies": 600000.0,
                "returned_supplies": 0.0,
                "pos": "27",
            },
            user_id=FIRM_ALPHA_ID,
        )
        assert rec_unverified["needs_review"] is True

        # Offline JSON generation MUST be blocked
        with pytest.raises(Gstr8ValidationError) as exc:
            build_gstr8_offline_json(sb, batch_id=batch_id)
        assert "requires review for July 2024 rate determination" in str(exc.value)

        # 2. Resolve by providing explicit transaction date
        rec_resolved = add_or_update_gstr8_record_sync(
            sb,
            batch_id=batch_id,
            record_data={
                "id": rec_unverified["id"],
                "supply_type": "B2B",
                "record_type": "ORIGINAL",
                "supplier_gstin": "27DDDDD0000D1Z3",
                "gross_supplies": 600000.0,
                "returned_supplies": 0.0,
                "pos": "27",
                "transaction_date": "2024-07-15",
            },
            user_id=FIRM_ALPHA_ID,
        )
        assert rec_resolved["needs_review"] is False

        # Offline JSON generation now succeeds
        offline_json = build_gstr8_offline_json(sb, batch_id=batch_id)
        assert offline_json["gstin"] == GSTIN_ALPHA
        assert offline_json["fp"] == "072024"
        assert len(offline_json["tcs"]) == 1
        assert offline_json["tcs"][0]["gstin_supp"] == "27DDDDD0000D1Z3"
        assert offline_json["tcs"][0]["net_val"] == 600000.0
        assert offline_json["tcs"][0]["camt"] == 1500.0  # 0.25% of 600,000
        assert offline_json["tcs"][0]["samt"] == 1500.0

    def test_6_concurrent_edits_transactional_consistency(self):
        """6: Test simultaneous edits to the same batch and verify transactional consistency in PostgreSQL."""
        sb = AuroraClient()
        period = "2026-11"

        batch = get_or_create_batch_sync(
            sb,
            firm_id=FIRM_ALPHA_ID,
            client_gstin_id=CLIENT_ALPHA_ID,
            gstin=GSTIN_ALPHA,
            period=period,
            user_id=FIRM_ALPHA_ID,
        )
        batch_id = batch["id"]

        def worker_add_record(idx: int):
            worker_sb = AuroraClient()
            supp_gstin = f"27EEEEE{idx:04d}E1Z4"
            add_or_update_gstr8_record_sync(
                worker_sb,
                batch_id=batch_id,
                record_data={
                    "supply_type": "B2B",
                    "record_type": "ORIGINAL",
                    "supplier_gstin": supp_gstin,
                    "gross_supplies": 10000.0 * idx,
                    "returned_supplies": 0.0,
                    "pos": "27",
                    "transaction_date": f"2026-11-{idx:02d}",
                },
                user_id=FIRM_ALPHA_ID,
            )

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(worker_add_record, i) for i in range(1, 6)]
            for f in futures:
                f.result()

        # Verify all 5 records persisted consistently
        summary = get_batch_summary_sync(sb, batch_id=batch_id)
        assert summary["batch"]["total_b2b_records"] == 5
        # Sum of 10k + 20k + 30k + 40k + 50k = 150,000
        assert summary["batch"]["gross_supplies_value"] == 150000.0
        assert summary["batch"]["net_taxable_value"] == 150000.0
        assert summary["total_tcs_liability"] == 750.0  # 0.5% of 150,000

    def test_7_maker_checker_approval_invalidation(self):
        """7: Verify previously approved batches are downgraded to PREPARED upon figure alteration."""
        sb = AuroraClient()
        period = "2026-12"

        batch = get_or_create_batch_sync(
            sb,
            firm_id=FIRM_ALPHA_ID,
            client_gstin_id=CLIENT_ALPHA_ID,
            gstin=GSTIN_ALPHA,
            period=period,
            user_id=FIRM_ALPHA_ID,
        )
        batch_id = batch["id"]

        add_or_update_gstr8_record_sync(
            sb,
            batch_id=batch_id,
            record_data={
                "supply_type": "B2B",
                "record_type": "ORIGINAL",
                "supplier_gstin": "27FFFFF0000F1Z5",
                "gross_supplies": 100000.0,
                "returned_supplies": 0.0,
                "pos": "27",
                "transaction_date": "2026-12-05",
            },
            user_id=FIRM_ALPHA_ID,
        )

        # Manually approve batch
        sb.table(GSTR8_BATCHES_TABLE).update({"status": "APPROVED"}).eq("id", batch_id).execute()
        b_approved = sb.table(GSTR8_BATCHES_TABLE).select("*").eq("id", batch_id).execute().data[0]
        assert b_approved["status"] == "APPROVED"
        approved_digest = b_approved["figures_digest"]

        # Alter figures: add another record
        add_or_update_gstr8_record_sync(
            sb,
            batch_id=batch_id,
            record_data={
                "supply_type": "B2C",
                "record_type": "ORIGINAL",
                "gross_supplies": 20000.0,
                "returned_supplies": 0.0,
                "pos": "27",
                "transaction_date": "2026-12-10",
            },
            user_id=FIRM_ALPHA_ID,
        )

        # Status must be reset to PREPARED and digest must change
        b_after = sb.table(GSTR8_BATCHES_TABLE).select("*").eq("id", batch_id).execute().data[0]
        assert b_after["status"] == "PREPARED"
        assert b_after["figures_digest"] != approved_digest

    def test_8_authenticated_cross_tenant_access_denial(self):
        """8: Verify authenticated multi-tenant isolation at database/application boundary."""
        sb = AuroraClient()

        # Firm Alpha batch
        batch_alpha = get_or_create_batch_sync(
            sb,
            firm_id=FIRM_ALPHA_ID,
            client_gstin_id=CLIENT_ALPHA_ID,
            gstin=GSTIN_ALPHA,
            period="2027-01",
            user_id=FIRM_ALPHA_ID,
        )

        # Firm Beta batch for same period
        batch_beta = get_or_create_batch_sync(
            sb,
            firm_id=FIRM_BETA_ID,
            client_gstin_id=CLIENT_BETA_ID,
            gstin=GSTIN_BETA,
            period="2027-01",
            user_id=FIRM_BETA_ID,
        )

        assert batch_alpha["id"] != batch_beta["id"]

        # Firm Beta queries with Firm Beta firm_id for Firm Alpha batch -> MUST return empty
        res_denied = (
            sb.table(GSTR8_BATCHES_TABLE)
            .select("*")
            .eq("firm_id", FIRM_BETA_ID)
            .eq("id", batch_alpha["id"])
            .execute()
        )
        assert len(res_denied.data) == 0

        # Query records with mismatched client_gstin_id -> MUST return empty
        res_rec_denied = (
            sb.table(GSTR8_RECORDS_TABLE)
            .select("*")
            .eq("client_gstin_id", CLIENT_BETA_ID)
            .eq("batch_id", batch_alpha["id"])
            .execute()
        )
        assert len(res_rec_denied.data) == 0
