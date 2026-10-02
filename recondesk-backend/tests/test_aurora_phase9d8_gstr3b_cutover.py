"""Test Suite for Phase 9D-8 — Batch 2B Application Cutover.

Verifies:
1. Reversal ledger insertion targets Aurora.
2. Reversal ledger fetch returns Aurora row.
3. Reversal ledger status transition updates Aurora.
4. Condition fulfillment updates Aurora.
5. Reclaim authorization updates Aurora.
6. Reclaimable reversals query reads from Aurora.
7. Reclaim event execution targets Aurora.
8. Native RPC / Aurora transactional reclaim execution verifies balance decrement.
9. Reclaim idempotency replay returns cached result from Aurora.
10. Table 4 summary snapshot creation targets Aurora.
11. Table 4 summary snapshot superseding works in Aurora.
12. Table 4 adjustment insert targets Aurora.
13. Table 4 adjustment soft-delete targets Aurora.
14. GSTR-3B reconciliation upsert targets Aurora.
15. GSTR-3B reconciliation fetch returns Aurora row.
16. Run cascade delete cleans up Batch 2B child records in Aurora.
17. Tenant isolation: client A cannot see or mutate client B's Batch 2B records.
18. Supabase failure / unavailable simulation verifies system continues operating normally via Aurora.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.schema_base import Base
from app.models.tenancy import ClientGSTIN, UserProfile
from app.models.reconciliation import ReconciliationRun
from app.models.gstr3b import (
    Gstr3bReversalLedger,
    Gstr3bTable4Summary,
    Gstr3bReclaimEvent,
    Gstr3bTable4Adjustment,
    Gstr3bReconciliation,
)
from app.repositories.gstr3b import (
    AuroraGstr3bRepository,
    set_gstr3b_repository,
)
from app.repositories.reconciliation import AuroraReconciliationRepository
from app.services.gstr3b_reversal_ledger import (
    ReversalLedgerCreate,
    ReclaimEventCreate,
    ReclaimEventType,
    ReversalStatus,
    StatutoryTemporaryReason,
    StatutoryEvidenceType,
    create_reversal_ledger_entry,
    get_reversal_ledger_entry,
    list_reversal_ledger_entries,
    update_reversal_ledger_status,
    fulfill_reversal_condition,
    authorize_reclaim,
    get_reclaimable_reversals,
    execute_reclaim_event,
)
from app.services.gstr3b_table4_engine import (
    load_reclaim_events_for_run,
    load_table4_adjustments,
    compute_table4_adjustments_digest,
)
from app.services.gstr9c_itc_fy_rollup import (
    fetch_gstr3b_for_run_ids,
    fetch_gstr3b_by_period_for_gstin,
)


@pytest.fixture
def cutover_sqlite_engine():
    """Create an isolated temporary SQLite database for Batch 2B cutover tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(cutover_sqlite_engine):
    """Return a sessionmaker bound to the test engine."""
    return sessionmaker(bind=cutover_sqlite_engine, autoflush=False)


@pytest.fixture
def gstr3b_repo(session_factory):
    """Instantiate and configure AuroraGstr3bRepository with the test sessionmaker."""
    repo = AuroraGstr3bRepository(session_factory=session_factory)
    set_gstr3b_repository(repo)
    yield repo
    set_gstr3b_repository(None)


@pytest.fixture
def seeded_env(session_factory):
    """Seed baseline tenant, user, and reconciliation runs for testing."""
    with session_factory() as session:
        user_a = UserProfile(
            id=uuid.uuid4(),
            email="tenant_a@recondesk.com",
            full_name="User Tenant A",
            role="admin",
            is_active=True,
        )
        user_b = UserProfile(
            id=uuid.uuid4(),
            email="tenant_b@recondesk.com",
            full_name="User Tenant B",
            role="admin",
            is_active=True,
        )
        session.add_all([user_a, user_b])
        session.flush()

        client_a = ClientGSTIN(
            id=uuid.uuid4(),
            firm_owner_id=user_a.id,
            gstin="27AABCU9603R1ZM",
            legal_name="Tenant Alpha Industries Ltd",
            trade_name="Alpha Tech",
            state_code="27",
            is_active=True,
        )
        client_b = ClientGSTIN(
            id=uuid.uuid4(),
            firm_owner_id=user_b.id,
            gstin="29XYZAB1234C1Z5",
            legal_name="Tenant Beta Solutions Pvt Ltd",
            trade_name="Beta Corp",
            state_code="29",
            is_active=True,
        )
        session.add_all([client_a, client_b])
        session.flush()

        run_a = ReconciliationRun(
            id=uuid.uuid4(),
            client_gstin_id=client_a.id,
            period="2025-01",
            status="COMPLETED",
        )
        run_b = ReconciliationRun(
            id=uuid.uuid4(),
            client_gstin_id=client_b.id,
            period="2025-01",
            status="COMPLETED",
        )
        session.add_all([run_a, run_b])
        session.commit()

        return {
            "user_a_id": str(user_a.id),
            "user_b_id": str(user_b.id),
            "client_a_id": str(client_a.id),
            "client_b_id": str(client_b.id),
            "run_a_id": str(run_a.id),
            "run_b_id": str(run_b.id),
            "client_a_gstin": "27AABCU9603R1ZM",
            "client_b_gstin": "29XYZAB1234C1Z5",
        }


# ── Tests ────────────────────────────────────────────────────────────────────


def test_reversal_ledger_insertion_and_fetch_aurora(gstr3b_repo, seeded_env):
    """Items 1 & 2: Reversal ledger insertion targets Aurora and fetch returns Aurora row."""
    entry_req = ReversalLedgerCreate(
        client_gstin_id=seeded_env["client_a_id"],
        source_type="RECON_OUTCOME",
        source_record_id="pm:invoice-101",
        source_run_id=seeded_env["run_a_id"],
        reversal_tax_period="2025-01",
        document_type="INVOICE",
        document_number="INV-101",
        document_date=date(2025, 1, 15),
        supplier_gstin="27SUPPLIER1234Z",
        reversal_table4_cell="4B2",
        is_reclaimable=True,
        statutory_reason=StatutoryTemporaryReason.RULE_37_NON_PAYMENT,
        reversed_igst_paise=100000,
        reversed_cgst_paise=50000,
        reversed_sgst_paise=50000,
        reversed_cess_paise=0,
        created_by=seeded_env["user_a_id"],
    )

    # Supabase is passed as None to verify Aurora PRIMARY with no Supabase dependency
    created = create_reversal_ledger_entry(None, entry_req)
    assert created["id"] is not None
    assert created["status"] == "OPEN"
    assert created["reversed_igst_paise"] == 100000

    # Fetch single entry
    fetched = get_reversal_ledger_entry(None, created["id"])
    assert fetched["id"] == created["id"]
    assert fetched["document_number"] == "INV-101"

    # List entries for client
    listed = list_reversal_ledger_entries(None, seeded_env["client_a_id"])
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]


def test_reversal_ledger_lifecycle_transitions_aurora(gstr3b_repo, seeded_env):
    """Items 3, 4, 5: Status transition, condition fulfillment, and authorization update Aurora."""
    entry_req = ReversalLedgerCreate(
        client_gstin_id=seeded_env["client_a_id"],
        source_type="RECON_OUTCOME",
        source_record_id="pm:invoice-102",
        source_run_id=seeded_env["run_a_id"],
        reversal_tax_period="2025-01",
        document_type="INVOICE",
        document_number="INV-102",
        reversal_table4_cell="4B2",
        is_reclaimable=True,
        statutory_reason=StatutoryTemporaryReason.RULE_37_NON_PAYMENT,
        reversed_igst_paise=200000,
    )
    created = create_reversal_ledger_entry(None, entry_req)
    lid = created["id"]

    # 1. Update status
    updated = update_reversal_ledger_status(None, lid, ReversalStatus.OPEN)
    assert updated["status"] == "OPEN"

    # 2. Fulfill condition
    fulfilled = fulfill_reversal_condition(
        None,
        lid,
        evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-9988776655",
        evidence_document_date=date(2025, 2, 10),
        notes="Bank payment cleared to vendor",
    )
    assert fulfilled["status"] == "CONDITION_FULFILLED"
    assert fulfilled["condition_fulfilled_date"] is not None

    # 3. Authorize reclaim
    authorized = authorize_reclaim(
        None,
        lid,
        authorized_by=seeded_env["user_a_id"],
        reclaim_eligibility_date=date(2025, 2, 15),
    )
    assert authorized["status"] == "RECLAIM_AUTHORIZED"
    assert authorized["reclaim_eligibility_date"] == "2025-02-15"


def test_reclaimable_reversals_query_aurora(gstr3b_repo, seeded_env):
    """Item 6: Reclaimable reversals query reads from Aurora with balance calculations."""
    entry_req = ReversalLedgerCreate(
        client_gstin_id=seeded_env["client_a_id"],
        source_type="RECON_OUTCOME",
        source_record_id="pm:invoice-103",
        source_run_id=seeded_env["run_a_id"],
        reversal_tax_period="2025-01",
        document_type="INVOICE",
        reversal_table4_cell="4B2",
        is_reclaimable=True,
        statutory_reason=StatutoryTemporaryReason.RULE_37_NON_PAYMENT,
        reversed_igst_paise=300000,
    )
    created = create_reversal_ledger_entry(None, entry_req)
    lid = created["id"]

    authorize_reclaim(None, lid, authorized_by=seeded_env["user_a_id"])

    reclaimable = get_reclaimable_reversals(None, seeded_env["client_a_id"], tax_period="2025-02")
    assert len(reclaimable) >= 1
    target = next(r for r in reclaimable if r["id"] == lid)
    assert target["available_balance"]["igst_paise"] == 300000
    tot = (
        target["available_balance"]["igst_paise"]
        + target["available_balance"]["cgst_paise"]
        + target["available_balance"]["sgst_paise"]
        + target["available_balance"]["cess_paise"]
    )
    assert tot == 300000


def test_reclaim_event_execution_and_rpc_decrement_aurora(gstr3b_repo, seeded_env):
    """Items 7, 8, 9: Reclaim event execution, balance decrement, and idempotency replay in Aurora."""
    entry_req = ReversalLedgerCreate(
        client_gstin_id=seeded_env["client_a_id"],
        source_type="RECON_OUTCOME",
        source_record_id="pm:invoice-104",
        source_run_id=seeded_env["run_a_id"],
        reversal_tax_period="2025-01",
        document_type="INVOICE",
        reversal_table4_cell="4B2",
        is_reclaimable=True,
        statutory_reason=StatutoryTemporaryReason.RULE_37_NON_PAYMENT,
        reversed_igst_paise=500000,
        reversed_cgst_paise=200000,
        reversed_sgst_paise=200000,
    )
    created = create_reversal_ledger_entry(None, entry_req)
    lid = created["id"]
    authorize_reclaim(None, lid, authorized_by=seeded_env["user_a_id"])

    # 1. Execute partial reclaim
    reclaim_req = ReclaimEventCreate(
        ledger_id=lid,
        client_gstin_id=seeded_env["client_a_id"],
        reclaim_run_id=seeded_env["run_a_id"],
        reclaim_tax_period="2025-02",
        event_type=ReclaimEventType.RECLAIM,
        reclaimed_igst_paise=250000,
        reclaimed_cgst_paise=100000,
        reclaimed_sgst_paise=100000,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-PARTIAL-1",
        reclaim_notes="Partial payment cleared",
        idempotency_key="IDEMP-PARTIAL-104",
    )

    res1 = execute_reclaim_event(None, reclaim_req)
    assert res1.status == "PARTIALLY_RECLAIMED"
    assert res1.is_idempotent_replay is False
    assert res1.reclaimed_igst_paise == 250000
    assert res1.remaining_igst_paise == 250000
    assert res1.remaining_cgst_paise == 100000
    assert res1.remaining_sgst_paise == 100000

    # 2. Replay with identical idempotency key -> returns cached replay
    res_replay = execute_reclaim_event(None, reclaim_req)
    assert res_replay.is_idempotent_replay is True
    assert res_replay.event_id == res1.event_id
    assert res_replay.reclaimed_igst_paise == 250000

    # 3. Complete remaining balance -> FULLY_RECLAIMED
    reclaim_req_full = ReclaimEventCreate(
        ledger_id=lid,
        client_gstin_id=seeded_env["client_a_id"],
        reclaim_run_id=seeded_env["run_a_id"],
        reclaim_tax_period="2025-02",
        event_type=ReclaimEventType.RECLAIM,
        reclaimed_igst_paise=250000,
        reclaimed_cgst_paise=100000,
        reclaimed_sgst_paise=100000,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-FINAL-2",
        reclaim_notes="Final balance cleared",
        idempotency_key="IDEMP-FINAL-104",
    )
    res2 = execute_reclaim_event(None, reclaim_req_full)
    assert res2.status == "FULLY_RECLAIMED"
    assert res2.remaining_igst_paise == 0
    assert res2.remaining_cgst_paise == 0
    assert res2.remaining_sgst_paise == 0

    # 4. Excess reclaim attempt rejected
    reclaim_req_excess = ReclaimEventCreate(
        ledger_id=lid,
        client_gstin_id=seeded_env["client_a_id"],
        reclaim_run_id=seeded_env["run_a_id"],
        reclaim_tax_period="2025-02",
        event_type=ReclaimEventType.RECLAIM,
        reclaimed_igst_paise=1000,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-EXCESS",
        reclaim_notes="Excess attempt",
    )
    with pytest.raises(ValueError, match="EXCESS_RECLAIM_IGST"):
        execute_reclaim_event(None, reclaim_req_excess)


def test_table4_summary_snapshot_creation_and_superseding_aurora(gstr3b_repo, seeded_env):
    """Items 10 & 11: Table 4 summary snapshot creation and superseding in Aurora."""
    rid = seeded_env["run_a_id"]
    client_id = seeded_env["client_a_id"]

    # Version 1 Snapshot
    snap_data_v1 = {
        "run_id": rid,
        "client_gstin_id": client_id,
        "tax_period": "2025-01",
        "status": "FINALIZED",
        "table_4a5": {"total_tax_paise": 1000000},
        "table_4b2": {"total_tax_paise": 200000},
        "table_4b_total": {"total_tax_paise": 200000},
        "table_4c": {"total_tax_paise": 800000},
        "audit_hash": "sha256-v1-hash",
    }
    v1 = gstr3b_repo.create_table4_summary_snapshot(snap_data_v1, supersede_previous=True)
    assert v1["version"] == 1
    assert v1["is_current"] is True

    # Current snapshot check
    cur1 = gstr3b_repo.get_table4_summary_for_run(rid, is_current_only=True)
    assert cur1["version"] == 1

    # Version 2 Snapshot (supersedes V1)
    snap_data_v2 = {
        "run_id": rid,
        "client_gstin_id": client_id,
        "tax_period": "2025-01",
        "status": "FINALIZED",
        "table_4a5": {"total_tax_paise": 1200000},
        "table_4b2": {"total_tax_paise": 200000},
        "table_4b_total": {"total_tax_paise": 200000},
        "table_4c": {"total_tax_paise": 1000000},
        "audit_hash": "sha256-v2-hash",
    }
    v2 = gstr3b_repo.create_table4_summary_snapshot(snap_data_v2, supersede_previous=True)
    assert v2["version"] == 2
    assert v2["is_current"] is True

    # Check V1 is now superseded
    all_snaps = gstr3b_repo.list_table4_summaries_for_run(rid)
    assert len(all_snaps) == 2
    snap_v1_updated = next(s for s in all_snaps if s["version"] == 1)
    assert snap_v1_updated["is_current"] is False
    assert snap_v1_updated["superseded_at"] is not None

    cur2 = gstr3b_repo.get_table4_summary_for_run(rid, is_current_only=True)
    assert cur2["version"] == 2
    assert cur2["audit_hash"] == "sha256-v2-hash"


def test_table4_adjustment_crud_and_soft_delete_aurora(gstr3b_repo, seeded_env):
    """Items 12 & 13: Table 4 adjustment insert, listing, digest, and soft-delete in Aurora."""
    rid = seeded_env["run_a_id"]
    client_id = seeded_env["client_a_id"]

    adj_data = {
        "run_id": rid,
        "client_gstin_id": client_id,
        "tax_period": "2025-01",
        "row_id": "4B2",
        "igst_paise": 150000,
        "cgst_paise": 75000,
        "sgst_paise": 75000,
        "cess_paise": 0,
        "adjustment_type": "REDUCTION",
        "statutory_category": "RULE_42",
        "reason": "Exempt supply turnover reversal under Rule 42",
        "reference_doc": "JV-RULE42-202501",
    }
    created = gstr3b_repo.create_table4_adjustment(adj_data)
    aid = created["id"]
    assert created["is_deleted"] is False

    # List adjustments via service function (Aurora primary)
    active_adjs = load_table4_adjustments(None, rid)
    assert len(active_adjs) == 1
    assert active_adjs[0]["id"] == aid

    # Compute digest
    digest1 = compute_table4_adjustments_digest(active_adjs, run_id=rid)
    assert digest1 is not None

    # Soft delete adjustment
    deleted_ok = gstr3b_repo.soft_delete_table4_adjustment(aid, run_id=rid)
    assert deleted_ok is True

    # Verify excluded from active adjustments
    remaining_adjs = load_table4_adjustments(None, rid)
    assert len(remaining_adjs) == 0

    digest2 = compute_table4_adjustments_digest(remaining_adjs, run_id=rid)
    assert digest2 != digest1


def test_gstr3b_reconciliation_upsert_and_fetch_aurora(gstr3b_repo, seeded_env):
    """Items 14 & 15: GSTR-3B reconciliation upsert, fetch, and rollup retrieval in Aurora."""
    rid = seeded_env["run_a_id"]
    gstin = seeded_env["client_a_gstin"]

    recon_data = {
        "run_id": rid,
        "client_gstin": gstin,
        "tax_period": "2025-01",
        "gstr3b_igst_claimed": Decimal("450000.00"),
        "gstr3b_cgst_claimed": Decimal("225000.00"),
        "gstr3b_sgst_claimed": Decimal("225000.00"),
        "gstr2b_igst_available": Decimal("400000.00"),
        "gstr2b_cgst_available": Decimal("200000.00"),
        "gstr2b_sgst_available": Decimal("200000.00"),
        "igst_difference": Decimal("50000.00"),
        "cgst_difference": Decimal("25000.00"),
        "sgst_difference": Decimal("25000.00"),
        "igst_status": "EXCESS_CLAIMED",
        "cgst_status": "EXCESS_CLAIMED",
        "sgst_status": "EXCESS_CLAIMED",
        "overall_status": "EXCESS_CLAIMED",
        "outward_supply_total": Decimal("5000000.00"),
        "raw_gstr3b": {"ret_period": "2025-01", "gstin": gstin},
        "uploaded_by": seeded_env["user_a_id"],
    }

    # Upsert
    saved = gstr3b_repo.upsert_gstr3b_reconciliation(rid, recon_data)
    assert saved["id"] is not None
    assert str(saved["run_id"]) == rid

    # Fetch for run
    fetched = gstr3b_repo.get_gstr3b_reconciliation_for_run(rid)
    assert fetched is not None
    assert fetched["overall_status"] == "EXCESS_CLAIMED"

    # Rollup fetch for runs
    by_runs = fetch_gstr3b_for_run_ids(None, [rid])
    assert rid in by_runs
    assert float(by_runs[rid]["gstr3b_igst_claimed"]) == 450000.0

    # Rollup fetch by period for GSTIN
    by_period = fetch_gstr3b_by_period_for_gstin(None, gstin=gstin, periods={"2025-01"})
    assert "2025-01" in by_period
    assert float(by_period["2025-01"]["gstr3b_igst_claimed"]) == 450000.0


def test_cascade_deletion_cleans_up_batch2b_records_aurora(session_factory, gstr3b_repo, seeded_env):
    """Item 16: Deleting a reconciliation run cascade-cleans Batch 2B child records in Aurora."""
    rid = seeded_env["run_a_id"]
    client_id = seeded_env["client_a_id"]

    # 1. Create reversal ledger row
    entry_req = ReversalLedgerCreate(
        client_gstin_id=client_id,
        source_type="RECON_OUTCOME",
        source_record_id="pm:invoice-cascade",
        source_run_id=rid,
        reversal_tax_period="2025-01",
        document_type="INVOICE",
        reversal_table4_cell="4B2",
        is_reclaimable=True,
        statutory_reason=StatutoryTemporaryReason.RULE_37_NON_PAYMENT,
        reversed_igst_paise=100000,
    )
    rev = create_reversal_ledger_entry(None, entry_req)

    # 2. Create reclaim event
    gstr3b_repo.create_reclaim_event({
        "client_gstin_id": client_id,
        "ledger_id": rev["id"],
        "reclaim_run_id": rid,
        "reclaim_tax_period": "2025-01",
        "reclaimed_igst_paise": 50000,
        "statutory_evidence_type": "PAYMENT_TO_SUPPLIER",
        "evidence_reference": "UTR-CASCADE",
    })

    # 3. Create Table 4 summary
    gstr3b_repo.create_table4_summary_snapshot({
        "run_id": rid,
        "client_gstin_id": client_id,
        "tax_period": "2025-01",
        "status": "FINALIZED",
        "audit_hash": "hash-cascade",
    })

    # 4. Create adjustment
    gstr3b_repo.create_table4_adjustment({
        "run_id": rid,
        "client_gstin_id": client_id,
        "tax_period": "2025-01",
        "row_id": "4B2",
        "igst_paise": 10000,
        "adjustment_type": "ADDITION",
        "statutory_category": "RULE_42",
        "reason": "Cascade test adjustment",
    })

    # 5. Create reconciliation
    gstr3b_repo.upsert_gstr3b_reconciliation(rid, {
        "run_id": rid,
        "client_gstin": seeded_env["client_a_gstin"],
        "tax_period": "2025-01",
        "gstr3b_igst_claimed": Decimal("1000.00"),
        "uploaded_by": seeded_env["user_a_id"],
    })

    # Execute AuroraReconciliationRepository cascade delete
    recon_repo = AuroraReconciliationRepository(session_factory=session_factory)
    del_ok = recon_repo.delete_run_cascade(rid)
    assert del_ok is True

    # Verify zero residual Batch 2B records for run_a_id
    with session_factory() as session:
        assert session.execute(select(Gstr3bReversalLedger).where(Gstr3bReversalLedger.source_run_id == uuid.UUID(rid))).scalars().all() == []
        assert session.execute(select(Gstr3bTable4Summary).where(Gstr3bTable4Summary.run_id == uuid.UUID(rid))).scalars().all() == []
        assert session.execute(select(Gstr3bTable4Adjustment).where(Gstr3bTable4Adjustment.run_id == uuid.UUID(rid))).scalars().all() == []
        assert session.execute(select(Gstr3bReconciliation).where(Gstr3bReconciliation.run_id == uuid.UUID(rid))).scalars().all() == []
        assert session.execute(select(Gstr3bReclaimEvent).where(Gstr3bReclaimEvent.reclaim_run_id == uuid.UUID(rid))).scalars().all() == []


def test_tenant_isolation_batch2b_aurora(gstr3b_repo, seeded_env):
    """Item 17: Tenant isolation prevents cross-tenant access to Batch 2B records."""
    client_a = seeded_env["client_a_id"]
    client_b = seeded_env["client_b_id"]
    run_a = seeded_env["run_a_id"]
    run_b = seeded_env["run_b_id"]

    # Insert reversal for Tenant A
    create_reversal_ledger_entry(None, ReversalLedgerCreate(
        client_gstin_id=client_a,
        source_type="RECON_OUTCOME",
        source_record_id="pm:inv-tenant-a",
        source_run_id=run_a,
        reversal_tax_period="2025-01",
        document_type="INVOICE",
        reversal_table4_cell="4B2",
        is_reclaimable=True,
        statutory_reason=StatutoryTemporaryReason.RULE_37_NON_PAYMENT,
        reversed_igst_paise=100000,
    ))

    # Insert reversal for Tenant B
    create_reversal_ledger_entry(None, ReversalLedgerCreate(
        client_gstin_id=client_b,
        source_type="RECON_OUTCOME",
        source_record_id="pm:inv-tenant-b",
        source_run_id=run_b,
        reversal_tax_period="2025-01",
        document_type="INVOICE",
        reversal_table4_cell="4B2",
        is_reclaimable=True,
        statutory_reason=StatutoryTemporaryReason.RULE_37_NON_PAYMENT,
        reversed_igst_paise=200000,
    ))

    # Tenant A sees ONLY Tenant A's entries
    list_a = list_reversal_ledger_entries(None, client_a)
    assert len(list_a) == 1
    assert list_a[0]["source_record_id"] == "pm:inv-tenant-a"
    assert str(list_a[0]["client_gstin_id"]) == client_a

    # Tenant B sees ONLY Tenant B's entries
    list_b = list_reversal_ledger_entries(None, client_b)
    assert len(list_b) == 1
    assert list_b[0]["source_record_id"] == "pm:inv-tenant-b"
    assert str(list_b[0]["client_gstin_id"]) == client_b

    # Add adjustments for each tenant
    gstr3b_repo.create_table4_adjustment({
        "run_id": run_a,
        "client_gstin_id": client_a,
        "tax_period": "2025-01",
        "row_id": "4B2",
        "igst_paise": 11000,
        "adjustment_type": "ADDITION",
        "statutory_category": "RULE_42",
        "reason": "Tenant A Adjustment",
    })
    gstr3b_repo.create_table4_adjustment({
        "run_id": run_b,
        "client_gstin_id": client_b,
        "tax_period": "2025-01",
        "row_id": "4B2",
        "igst_paise": 22000,
        "adjustment_type": "ADDITION",
        "statutory_category": "RULE_42",
        "reason": "Tenant B Adjustment",
    })

    adjs_a = load_table4_adjustments(None, run_a)
    assert len(adjs_a) == 1
    assert adjs_a[0]["reason"] == "Tenant A Adjustment"

    adjs_b = load_table4_adjustments(None, run_b)
    assert len(adjs_b) == 1
    assert adjs_b[0]["reason"] == "Tenant B Adjustment"


def test_supabase_failure_mode_aurora_primary(gstr3b_repo, seeded_env):
    """Item 18: System operates uninterrupted when Supabase client is completely disabled / raises."""
    client_a = seeded_env["client_a_id"]
    run_a = seeded_env["run_a_id"]

    class BrokenSupabaseClient:
        def table(self, *args, **kwargs):
            raise ConnectionError("Supabase network unreachable")

        def rpc(self, *args, **kwargs):
            raise ConnectionError("Supabase RPC service down")

    broken_sb = BrokenSupabaseClient()

    # 1. Insert reversal entry works via Aurora despite broken Supabase
    entry = create_reversal_ledger_entry(broken_sb, ReversalLedgerCreate(
        client_gstin_id=client_a,
        source_type="RECON_OUTCOME",
        source_record_id="pm:inv-resilient",
        source_run_id=run_a,
        reversal_tax_period="2025-01",
        document_type="INVOICE",
        reversal_table4_cell="4B2",
        is_reclaimable=True,
        statutory_reason=StatutoryTemporaryReason.RULE_37_NON_PAYMENT,
        reversed_igst_paise=350000,
    ))
    assert entry["id"] is not None

    # 2. Fetch entry works via Aurora
    fetched = get_reversal_ledger_entry(broken_sb, entry["id"])
    assert fetched["id"] == entry["id"]

    # 3. Authorize reclaim works via Aurora
    auth = authorize_reclaim(broken_sb, entry["id"], authorized_by=seeded_env["user_a_id"])
    assert auth["status"] == "RECLAIM_AUTHORIZED"

    # 4. Execute reclaim works via Aurora
    rec_res = execute_reclaim_event(broken_sb, ReclaimEventCreate(
        ledger_id=entry["id"],
        client_gstin_id=client_a,
        reclaim_run_id=run_a,
        reclaim_tax_period="2025-02",
        reclaimed_igst_paise=100000,
        statutory_evidence_type=StatutoryEvidenceType.PAYMENT_TO_SUPPLIER,
        evidence_reference="UTR-RESILIENT",
        reclaim_notes="Resilient execution",
    ))
    assert rec_res.reclaimed_igst_paise == 100000
    assert rec_res.remaining_igst_paise == 250000

    # 5. Table 4 adjustments work via Aurora
    adjs = load_table4_adjustments(broken_sb, run_a)
    assert isinstance(adjs, list)

    # 6. GSTR-3B reconciliation rollup works via Aurora
    rollups = fetch_gstr3b_for_run_ids(broken_sb, [run_a])
    assert isinstance(rollups, dict)
