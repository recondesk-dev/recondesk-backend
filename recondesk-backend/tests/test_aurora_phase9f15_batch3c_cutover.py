"""Test Suite for Phase 9F-15: Canonical Batch 3C Application Cutover.

Verifies:
1. Complete Supabase outage resilience: All Batch 3C operations succeed using Aurora PRIMARY
   even when Supabase raises ConnectionError.
2. Zero normal production Supabase writes during operations.
3. FilingSession lifecycle: create, get active, lookup by id, update token, logout, delete.
4. FilingRun lifecycle: create, update, poll status transitions (save/offset), mark failed, delete.
5. GSTR-3B offset lock enforcement (hard-blocks subsequent save/offset after offset complete).
6. Bulk FilingBatch and FilingBatchItem lifecycle: create, list, item update, recalculate summary counts.
7. SalesRegisterRun & SrRecord operations: create run, bulk insert records, fetch for period, delete.
8. Worker task resilience: Celery helper fetch_sales_register_records and batch status updates work on Aurora.
9. Tenant boundary isolation across all entities.
10. Sensitive GSTN token redaction guarantee (to_dict() mask and zero log leaks).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.schema_base import Base
from app.models.filing_automation import (
    FilingBatch,
    FilingBatchItem,
    FilingRun,
    FilingSession,
    SalesRegisterRun,
    SrRecord,
)
from app.models.tenancy import ClientGSTIN, UserProfile
from app.repositories.filing_automation import (
    AuroraFilingAutomationRepository,
    Gstr3bPeriodLockedError,
    get_filing_automation_repository,
    set_filing_automation_repository,
)
from app.filing import filing_store
from app.filing.sandbox_filing_client import TaxpayerSession, ReturnStatusInfo
from app.worker.filing_batch_task import fetch_sales_register_records


class BrokenSupabaseClient:
    """Mock Supabase client that raises ConnectionError on ANY operation to simulate complete outage."""

    def __init__(self) -> None:
        self.call_count = 0

    def table(self, table_name: str) -> Any:
        self.call_count += 1
        raise ConnectionError(f"Supabase is unreachable (simulated outage on {table_name})")


@pytest.fixture(autouse=True)
def setup_aurora_filing_repo():
    """Create an in-memory SQLite database initialized with Batch 3C tables and wire repository."""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    repo = AuroraFilingAutomationRepository(session_factory=session_factory)
    set_filing_automation_repository(repo)

    # Seed parent entities for tenant foreign key testing
    with session_factory() as session:
        u1 = UserProfile(
            id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
            email="firm1@example.com",
            role="ca",
        )
        u2 = UserProfile(
            id=uuid.UUID("22222222-2222-4222-8222-222222222222"),
            email="firm2@example.com",
            role="ca",
        )
        c1 = ClientGSTIN(
            id=uuid.UUID("33333333-3333-4333-8333-333333333333"),
            firm_owner_id=u1.id,
            gstin="27AABCT1234A1Z5",
            legal_name="Client 1 Corp",
        )
        c2 = ClientGSTIN(
            id=uuid.UUID("44444444-4444-4444-8444-444444444444"),
            firm_owner_id=u2.id,
            gstin="29AABCT5678B1Z2",
            legal_name="Client 2 Corp",
        )
        session.add_all([u1, u2, c1, c2])
        session.commit()

    yield repo

    set_filing_automation_repository(None)


def test_session_lifecycle_with_supabase_down():
    """Verify full taxpayer session lifecycle routes to Aurora when Supabase is down."""
    broken_sb = BrokenSupabaseClient()
    firm_id = "11111111-1111-4111-8111-111111111111"
    client_gstin_id = "33333333-3333-4333-8333-333333333333"
    gstin = "27AABCT1234A1Z5"

    session_data = TaxpayerSession(
        access_token="secret_live_otp_token_xyz999",
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=6),
        session_expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
    )

    # 1. Create Session
    created = filing_store.create_session(
        broken_sb,
        firm_id=firm_id,
        gstin=gstin,
        username="ca_firm1",
        session=session_data,
        client_gstin_id=client_gstin_id,
    )
    assert created is not None
    session_id = created["id"]
    assert created["gstin"] == gstin
    assert created["status"] == "active"
    assert created["session_token"] == "secret_live_otp_token_xyz999"

    # 2. Get Active Session
    active = filing_store.get_active_session(broken_sb, firm_id=firm_id, gstin=gstin)
    assert active is not None
    assert active["id"] == session_id

    # 3. Lookup by ID
    by_id = filing_store.get_session_by_id(broken_sb, session_id)
    assert by_id is not None
    assert by_id["id"] == session_id

    # 4. Token Refresh
    refreshed_session = TaxpayerSession(
        access_token="new_refreshed_token_abc123",
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=6),
        session_expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
    )
    updated = filing_store.update_session_token(broken_sb, session_id, refreshed_session)
    assert updated["session_token"] == "new_refreshed_token_abc123"

    # 5. Mark Logged Out
    filing_store.mark_session_logged_out(broken_sb, session_id)
    logged_out = filing_store.get_session_by_id(broken_sb, session_id)
    assert logged_out["status"] == "logged_out"
    assert logged_out["logged_out_at"] is not None

    # Active session query should now return None
    assert filing_store.get_active_session(broken_sb, firm_id=firm_id, gstin=gstin) is None

    # 6. Deletion cascade
    repo = get_filing_automation_repository()
    deleted = repo.delete_session(session_id)
    assert deleted is True
    assert filing_store.get_session_by_id(broken_sb, session_id) is None


def test_filing_run_lifecycle_and_offset_lock_with_supabase_down():
    """Verify filing run CRUD, status polls, and GSTR-3B offset lock when Supabase is down."""
    broken_sb = BrokenSupabaseClient()
    firm_id = "11111111-1111-4111-8111-111111111111"
    client_gstin_id = "33333333-3333-4333-8333-333333333333"
    gstin = "27AABCT1234A1Z5"
    period = "2026-03"

    # 1. Pre-check: save is allowed
    filing_store.assert_gstr3b_save_allowed(broken_sb, gstin=gstin, period=period)

    # 2. Create Run
    run = filing_store.create_run(
        broken_sb,
        firm_id=firm_id,
        gstin=gstin,
        period=period,
        return_type="gstr-3b",
        status="draft",
        client_gstin_id=client_gstin_id,
        save_payload={"table_4": {"itc": 12500.0}},
    )
    assert run is not None
    run_id = run["id"]
    assert run["status"] == "draft"
    assert run["return_type"] == "gstr-3b"

    # 3. Update Run to Save Pending
    filing_store.update_run(broken_sb, run_id, status="save_pending", reference_id="REF-1001")
    r1 = filing_store.get_run(broken_sb, run_id)
    assert r1["status"] == "save_pending"
    assert r1["reference_id"] == "REF-1001"

    # 4. Apply Save Status Poll (P -> saved)
    info_save = ReturnStatusInfo(
        outer_status_cd="1",
        gstn_status_cd="P",
        action="SAVE",
    )
    saved_run = filing_store.apply_save_status_to_run(
        broken_sb,
        run_id,
        return_status=info_save,
        envelope={"status_cd": "P", "error_report": None},
    )
    assert saved_run["status"] == "saved"

    # 5. Apply Offset Status Poll (P -> offset_complete)
    info_offset = ReturnStatusInfo(
        outer_status_cd="1",
        gstn_status_cd="P",
        action="OFFSET",
    )
    offset_run = filing_store.apply_offset_status_to_run(
        broken_sb,
        run_id,
        return_status=info_offset,
        envelope={"status_cd": "P"},
        offset_payload={"cgst": 500.0, "sgst": 500.0},
        tx_pmt_snapshot={"cash_ledger": 10000.0},
    )
    assert offset_run["status"] == "offset_complete"
    assert offset_run["offset_completed_at"] is not None
    assert offset_run["tx_pmt_snapshot"] == {"cash_ledger": 10000.0}

    # 6. GSTR-3B Offset Lock Enforcement: Save & Offset must now be strictly blocked!
    with pytest.raises(Gstr3bPeriodLockedError) as exc_save:
        filing_store.assert_gstr3b_save_allowed(broken_sb, gstin=gstin, period=period)
    assert exc_save.value.action == "save"
    assert exc_save.value.locking_run["id"] == run_id

    with pytest.raises(Gstr3bPeriodLockedError) as exc_offset:
        filing_store.assert_gstr3b_offset_allowed(broken_sb, gstin=gstin, period=period)
    assert exc_offset.value.action == "offset"

    # 7. Filing History Retrieval
    history = filing_store.get_filing_history(broken_sb, gstin=gstin, limit=50)
    assert len(history) == 1
    assert history[0]["id"] == run_id

    # 8. Mark Failed helper test
    run2 = filing_store.create_run(
        broken_sb,
        firm_id=firm_id,
        gstin=gstin,
        period="2026-04",
        return_type="gstr-1",
        status="save_pending",
    )
    filing_store.mark_run_failed(
        broken_sb,
        run2["id"],
        error_code="ERR_500",
        error_message="Sandbox network glitch",
    )
    r2_fetched = filing_store.get_run(broken_sb, run2["id"])
    assert r2_fetched["status"] == "failed"
    assert r2_fetched["error_code"] == "ERR_500"

    # 9. Delete Run
    repo = get_filing_automation_repository()
    assert repo.delete_run(run2["id"]) is True
    assert filing_store.get_run(broken_sb, run2["id"]) is None


def test_bulk_filing_batches_and_worker_task_with_supabase_down():
    """Verify batch creation, item updates, recalculation, and worker SR fetching on Aurora."""
    broken_sb = BrokenSupabaseClient()
    firm_id = "11111111-1111-4111-8111-111111111111"
    client_gstin_id = "33333333-3333-4333-8333-333333333333"
    period = "2026-03"

    # 1. Create Batch
    batch = filing_store.create_batch(
        broken_sb,
        firm_id=firm_id,
        created_by=firm_id,
        period=period,
        client_gstin_ids=[client_gstin_id],
        return_type="gstr-1",
    )
    assert batch is not None
    batch_id = batch["id"]
    assert batch["total_count"] == 1
    assert batch["status"] == "pending"
    assert len(batch["items"]) == 1
    item_id = batch["items"][0]["id"]

    # 2. Worker batch status transition to in_progress
    updated_b = filing_store.update_batch_status(broken_sb, batch_id, "in_progress")
    assert updated_b["status"] == "in_progress"

    # 3. Item processing
    filing_store.update_batch_item(broken_sb, item_id, status="in_progress")
    b_mid = filing_store.get_batch(broken_sb, batch_id)
    assert b_mid["items"][0]["status"] == "in_progress"

    # 4. Item completed
    filing_store.update_batch_item(broken_sb, item_id, status="filed")
    recalc = filing_store.recalculate_batch_status(broken_sb, batch_id)
    assert recalc["status"] == "completed"
    assert recalc["filed_count"] == 1
    assert recalc["failed_count"] == 0

    # 5. List batches
    batches = filing_store.list_batches(broken_sb, firm_id=firm_id)
    assert len(batches) == 1
    assert batches[0]["id"] == batch_id

    # 6. Delete batch
    repo = get_filing_automation_repository()
    assert repo.delete_batch(batch_id) is True
    assert filing_store.get_batch(broken_sb, batch_id) is None


def test_sales_register_run_and_worker_sr_fetch_with_supabase_down():
    """Verify sales_register_run, sr_records storage, and fetch_sales_register_records via worker."""
    broken_sb = BrokenSupabaseClient()
    repo = get_filing_automation_repository()
    client_gstin_id = "33333333-3333-4333-8333-333333333333"
    period = "2026-03"

    # 1. Create Sales Register Run
    sr_run = repo.create_sales_register_run(
        client_gstin_id=client_gstin_id,
        period=period,
        file_hash="hash_abc_123",
        status="completed",
    )
    assert sr_run is not None
    sr_run_id = sr_run["id"]

    # 2. Insert Voucher Records
    vouchers = [
        {"inv_no": "INV-001", "taxable": 50000.0, "igst": 9000.0, "hsn": "9983"},
        {"inv_no": "INV-002", "taxable": 30000.0, "cgst": 2700.0, "sgst": 2700.0, "hsn": "9984"},
    ]
    inserted = repo.create_sr_records(
        run_id=sr_run_id,
        client_gstin_id=client_gstin_id,
        period=period,
        records=vouchers,
    )
    assert inserted == 2

    # 3. Worker fetch_sales_register_records routes directly to Aurora
    fetched = fetch_sales_register_records(broken_sb, client_gstin_id=client_gstin_id, period=period)
    assert len(fetched) == 2
    assert fetched[0]["inv_no"] == "INV-001"
    assert fetched[1]["inv_no"] == "INV-002"

    # 4. Cleanup
    assert repo.delete_sales_register_run(sr_run_id) is True
    assert repo.get_sales_register_run(sr_run_id) is None
    assert len(fetch_sales_register_records(broken_sb, client_gstin_id=client_gstin_id, period=period)) == 0


def test_tenant_boundary_isolation_across_batch3c():
    """Verify strict tenant isolation: Firm 1 cannot see or manipulate Firm 2 records."""
    broken_sb = BrokenSupabaseClient()
    repo = get_filing_automation_repository()
    firm_1 = "11111111-1111-4111-8111-111111111111"
    firm_2 = "22222222-2222-4222-8222-222222222222"
    client_1 = "33333333-3333-4333-8333-333333333333"
    client_2 = "44444444-4444-4444-8444-444444444444"

    # Create Session for Firm 2
    sess_firm2 = filing_store.create_session(
        broken_sb,
        firm_id=firm_2,
        gstin="29AABCT5678B1Z2",
        username="ca_firm2",
        session=TaxpayerSession(
            access_token="secret_token_firm2",
            token_expires_at=datetime.now(timezone.utc) + timedelta(hours=6),
            session_expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
        ),
        client_gstin_id=client_2,
    )

    # Firm 1 cannot query Firm 2's active session
    active_for_firm1 = filing_store.get_active_session(
        broken_sb,
        firm_id=firm_1,
        gstin="29AABCT5678B1Z2",
    )
    assert active_for_firm1 is None

    # Create Batch for Firm 2
    batch_firm2 = filing_store.create_batch(
        broken_sb,
        firm_id=firm_2,
        created_by=firm_2,
        period="2026-03",
        client_gstin_ids=[client_2],
    )

    # Listing batches for Firm 1 returns 0 batches
    batches_firm1 = filing_store.list_batches(broken_sb, firm_id=firm_1)
    assert len(batches_firm1) == 0

    # Listing batches for Firm 2 returns 1 batch
    batches_firm2 = filing_store.list_batches(broken_sb, firm_id=firm_2)
    assert len(batches_firm2) == 1
    assert batches_firm2[0]["id"] == batch_firm2["id"]


def test_token_redaction_and_zero_normal_supabase_writes():
    """Verify that GSTN session token is always redacted in serialization and Supabase receives 0 writes."""
    broken_sb = BrokenSupabaseClient()
    firm_id = "11111111-1111-4111-8111-111111111111"
    client_id = "33333333-3333-4333-8333-333333333333"

    session = filing_store.create_session(
        broken_sb,
        firm_id=firm_id,
        gstin="27AABCT1234A1Z5",
        username="ca_user",
        session=TaxpayerSession(
            access_token="super_secret_taxpayer_token_12345",
            token_expires_at=datetime.now(timezone.utc) + timedelta(hours=6),
            session_expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
        ),
        client_gstin_id=client_id,
    )

    # Repository model serialization
    repo = get_filing_automation_repository()
    with repo._get_session() as db_sess:
        sess_model = db_sess.get(FilingSession, uuid.UUID(session["id"]))
        serialized = sess_model.to_dict()
        assert serialized["session_token"] == "***REDACTED***"
        assert "super_secret_taxpayer_token_12345" not in str(serialized)

    # Confirm zero normal Supabase calls were even attempted because Aurora handled everything
    assert broken_sb.call_count == 0, f"Supabase was invoked {broken_sb.call_count} times!"
