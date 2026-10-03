"""Test Suite for Phase 9D-13 — Batch 2C Application Cutover.

Verifies:
1. supplier_compliance_summary operations target Aurora as PRIMARY datastore.
2. supplier_compliance_by_client operations target Aurora as PRIMARY datastore.
3. supplier_followup_audit operations target Aurora as PRIMARY datastore.
4. itc_work_items operations target Aurora as PRIMARY datastore.
5. itc_work_item_events operations target Aurora as PRIMARY datastore.
6. vendor_followup_logs operations target Aurora as PRIMARY datastore.
7. Supplier compliance scorecard service functions (_replace_client_contributions, _rollup_suppliers) operate via Aurora.
8. ITC work item service functions (list, get, transition, priority override, assign, due date, resolve, dismiss, reopen, vendor response) operate via Aurora.
9. Vendor followup engine functions (log, token, portal fetch, portal response, contact update, history) operate via Aurora.
10. ITC revalidation engine (request, execute) operates via Aurora.
11. Resolution intelligence engine operates via Aurora.
12. Multi-tenant isolation: firm A / client A cannot view or mutate firm B / client B data across all six tables.
13. Cascade cleanup on run deletion removes audit rows, work items, and child events for that run in Aurora.
14. Complete Supabase outage / failure resilience (BrokenSupabaseClient) leaves all operations functioning seamlessly via Aurora.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.schema_base import Base
from app.models.tenancy import ClientGSTIN, UserProfile
from app.models.reconciliation import ReconciliationRun
from app.models.vendor_compliance import (
    SupplierComplianceSummary,
    SupplierComplianceByClient,
    SupplierFollowupAudit,
    ITCWorkItem,
    ITCWorkItemEvent,
    VendorFollowupLog,
)
from app.repositories.vendor_compliance import (
    AuroraVendorComplianceRepository,
    get_vendor_compliance_repository,
    set_vendor_compliance_repository,
)
from app.repositories.tenancy import (
    AuroraTenancyRepository,
    set_tenancy_repository,
)
from app.repositories.reconciliation import (
    AuroraReconciliationRepository,
    set_reconciliation_repository,
)
from app.services.supplier_compliance_scorecard import (
    SupplierClientCounters,
    _replace_client_contributions,
    _rollup_suppliers,
)
import app.services.itc_work_item_service as wis
import app.services.vendor_followup_engine as vfe
import app.services.itc_revalidation_engine as ire
import app.services.resolution_intelligence_engine as rie


# ── Broken Supabase Simulation ───────────────────────────────────────────────

class BrokenSupabaseClient:
    """Simulates a complete Supabase outage / network failure."""

    def table(self, *args, **kwargs):
        raise ConnectionError("Supabase datastore is completely offline")

    def rpc(self, *args, **kwargs):
        raise ConnectionError("Supabase RPC service is completely offline")


# ── Test Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def cutover_sqlite_engine():
    """Create an isolated temporary SQLite database with all schema tables."""
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


@pytest.fixture(autouse=True)
def configured_repos(session_factory):
    """Configure Aurora repositories with test engine sessionmaker."""
    vc_repo = AuroraVendorComplianceRepository(session_factory=session_factory)
    t_repo = AuroraTenancyRepository(session_factory=session_factory)
    r_repo = AuroraReconciliationRepository(session_factory=session_factory)

    set_vendor_compliance_repository(vc_repo)
    set_tenancy_repository(t_repo)
    set_reconciliation_repository(r_repo)

    yield vc_repo

    set_vendor_compliance_repository(None)
    set_tenancy_repository(None)
    set_reconciliation_repository(None)


@pytest.fixture
def seeded_env(session_factory):
    """Seed baseline tenants, users, and reconciliation runs."""
    with session_factory() as session:
        user_a = UserProfile(
            id=uuid.uuid4(),
            email="tenant_a@recondesk.com",
            full_name="CA Tenant Alpha",
            role="admin",
            is_active=True,
        )
        user_b = UserProfile(
            id=uuid.uuid4(),
            email="tenant_b@recondesk.com",
            full_name="CA Tenant Beta",
            role="admin",
            is_active=True,
        )
        session.add_all([user_a, user_b])
        session.flush()

        client_a = ClientGSTIN(
            id=uuid.uuid4(),
            firm_owner_id=user_a.id,
            gstin="27AABCU9603R1ZM",
            legal_name="Alpha Tech Corp",
            trade_name="Alpha Tech",
            state_code="27",
            is_active=True,
        )
        client_b = ClientGSTIN(
            id=uuid.uuid4(),
            firm_owner_id=user_b.id,
            gstin="29XYZAB1234C1Z5",
            legal_name="Beta Logistics Pvt Ltd",
            trade_name="Beta Logistics",
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
            "user_a_dict": {
                "id": str(user_a.id),
                "email": user_a.email,
                "full_name": user_a.full_name,
                "role": user_a.role,
                "firm_owner_id": str(user_a.id),
            },
            "user_b_dict": {
                "id": str(user_b.id),
                "email": user_b.email,
                "full_name": user_b.full_name,
                "role": user_b.role,
                "firm_owner_id": str(user_b.id),
            },
        }


# ── Repository Tests ─────────────────────────────────────────────────────────

def test_supplier_compliance_summary_ops(configured_repos, seeded_env):
    """Verify Aurora repository operations for supplier_compliance_summary."""
    vendor_compliance_repo = configured_repos
    fa = seeded_env["user_a_id"]
    gstin = "27ABCDE1234F1Z5"

    row = {
        "firm_owner_id": fa,
        "supplier_gstin_normalized": gstin,
        "supplier_trade_name": "ABC Supplies Ltd",
        "client_gstin_ids": [seeded_env["client_a_id"]],
        "clients_touched_count": 1,
        "total_invoices": 10,
        "mismatch_invoice_count": 2,
        "mismatch_rate": 0.20,
        "rule37_open_count": 1,
        "rule37_at_risk_paise": 50000,
        "section_17_5_count": 0,
        "late_filing_count": 1,
        "late_filing_rate": 0.10,
        "pr_only_count": 1,
        "quarterly_filer_flag": False,
        "risk_score": 45,
    }

    # 1. Upsert
    res = vendor_compliance_repo.upsert_supplier_compliance_summary(row)
    assert res["supplier_gstin_normalized"] == gstin
    assert res["firm_owner_id"] == fa
    assert res["total_invoices"] == 10

    # 2. Get by (firm_owner_id, supplier_gstin_normalized)
    fetched = vendor_compliance_repo.get_supplier_compliance_summary(fa, gstin)
    assert fetched is not None
    assert fetched["supplier_trade_name"] == "ABC Supplies Ltd"
    assert fetched["risk_score"] == 45

    # 3. List for firm
    listed, total = vendor_compliance_repo.list_supplier_compliance_summary(fa, search="ABC")
    assert total == 1
    assert len(listed) == 1
    assert listed[0]["supplier_gstin_normalized"] == gstin

    # 4. Update by GSTIN
    updated_cnt = vendor_compliance_repo.update_supplier_compliance_summary_by_gstin(
        gstin, {"supplier_trade_name": "ABC Updated Supplies Ltd"}
    )
    assert updated_cnt == 1
    fetched_after = vendor_compliance_repo.get_supplier_compliance_summary(fa, gstin)
    assert fetched_after["supplier_trade_name"] == "ABC Updated Supplies Ltd"

    # 5. List all summaries
    all_summaries = vendor_compliance_repo.list_all_supplier_compliance_summaries()
    assert len(all_summaries) >= 1

    # 6. Delete
    deleted = vendor_compliance_repo.delete_supplier_compliance_summary(fa, gstin)
    assert deleted is True
    assert vendor_compliance_repo.get_supplier_compliance_summary(fa, gstin) is None


def test_supplier_compliance_by_client_ops(configured_repos, seeded_env):
    """Verify Aurora repository operations for supplier_compliance_by_client."""
    vendor_compliance_repo = configured_repos
    fa = seeded_env["user_a_id"]
    ca = seeded_env["client_a_id"]
    s1 = "27ABCDE1234F1Z5"
    s2 = "27XYZAB9876K1Z9"

    rows = [
        {
            "firm_owner_id": fa,
            "client_gstin_id": ca,
            "supplier_gstin_normalized": s1,
            "supplier_trade_name": "Supplier One",
            "total_invoices": 5,
            "mismatch_invoice_count": 1,
            "rule37_open_count": 0,
            "rule37_at_risk_paise": 0,
            "section_17_5_count": 0,
            "late_filing_count": 0,
            "pr_only_count": 1,
            "quarterly_filer_flag": False,
        },
        {
            "firm_owner_id": fa,
            "client_gstin_id": ca,
            "supplier_gstin_normalized": s2,
            "supplier_trade_name": "Supplier Two",
            "total_invoices": 8,
            "mismatch_invoice_count": 2,
            "rule37_open_count": 1,
            "rule37_at_risk_paise": 25000,
            "section_17_5_count": 0,
            "late_filing_count": 1,
            "pr_only_count": 0,
            "quarterly_filer_flag": True,
        },
    ]

    # 1. Replace client contributions
    affected = vendor_compliance_repo.replace_client_contributions(fa, ca, rows)
    assert affected == {s1, s2}

    # 2. Get by client rows for supplier
    rows_s1 = vendor_compliance_repo.get_by_client_rows_for_supplier(fa, s1)
    assert len(rows_s1) == 1
    assert rows_s1[0]["supplier_trade_name"] == "Supplier One"
    assert rows_s1[0]["total_invoices"] == 5

    # 3. Get prior supplier GSTINs for client
    priors = vendor_compliance_repo.get_prior_supplier_gstins_for_client(fa, ca)
    assert priors == {s1, s2}

    # 4. Replace with only s1 (s2 gets removed)
    affected2 = vendor_compliance_repo.replace_client_contributions(fa, ca, [rows[0]])
    assert s1 in affected2
    assert s2 in affected2  # s2 is affected because it was removed
    priors2 = vendor_compliance_repo.get_prior_supplier_gstins_for_client(fa, ca)
    assert priors2 == {s1}


def test_supplier_followup_audit_ops(configured_repos, seeded_env):
    """Verify Aurora repository operations for supplier_followup_audit."""
    vendor_compliance_repo = configured_repos
    ra = seeded_env["run_a_id"]
    ca = seeded_env["client_a_id"]
    ua = seeded_env["user_a_id"]

    audit_rows = [
        {
            "run_id": ra,
            "client_gstin_id": ca,
            "supplier_gstin": "27SUPPLIER0001Z",
            "supplier_name": "Supplier 0001 Ltd",
            "invoice_numbers": ["INV-001", "INV-002"],
            "invoice_count": 2,
            "total_tax_paise": 180000,
            "rule37_tax_paise": 0,
            "rule37a_tax_paise": 0,
            "mismatch_reasons": ["MISSING_IN_2B"],
            "status": "generated",
            "created_by": ua,
        },
        {
            "run_id": ra,
            "client_gstin_id": ca,
            "supplier_gstin": "27SUPPLIER0002Z",
            "supplier_name": "Supplier 0002 Ltd",
            "invoice_numbers": ["INV-003"],
            "invoice_count": 1,
            "total_tax_paise": 90000,
            "rule37_tax_paise": 90000,
            "rule37a_tax_paise": 0,
            "mismatch_reasons": ["RULE_37_OVERDUE"],
            "status": "downloaded",
            "created_by": ua,
        },
    ]

    # 1. Insert audit rows
    res = vendor_compliance_repo.insert_supplier_followup_audit(audit_rows)
    assert isinstance(res, list)
    assert len(res) == 2

    # 2. List for run
    listed = vendor_compliance_repo.list_supplier_followup_audit_for_run(ra)
    assert len(listed) == 2
    gstins = {x["supplier_gstin"] for x in listed}
    assert gstins == {"27SUPPLIER0001Z", "27SUPPLIER0002Z"}

    # 3. List for multiple runs
    multi = vendor_compliance_repo.list_supplier_followup_audit_for_runs([ra])
    assert len(multi) == 2

    # 4. Delete for run
    del_cnt = vendor_compliance_repo.delete_supplier_followup_audit_for_run(ra)
    assert del_cnt == 2
    assert len(vendor_compliance_repo.list_supplier_followup_audit_for_run(ra)) == 0


def test_itc_work_items_and_events_ops(configured_repos, seeded_env):
    """Verify Aurora repository operations for itc_work_items and itc_work_item_events."""
    vendor_compliance_repo = configured_repos
    fa = seeded_env["user_a_id"]
    ca = seeded_env["client_a_id"]
    ra = seeded_env["run_a_id"]

    wi_row = {
        "firm_owner_id": fa,
        "client_gstin_id": ca,
        "run_id": ra,
        "record_id": "rec-101",
        "exception_type": "MISSED_ITC",
        "status": "OPEN",
        "priority": "HIGH",
        "category": "INVOICE_MISSING",
        "title": "Missing Invoice INV-101",
        "what": "Invoice missing in GSTR-2B",
        "why": "Supplier delayed filing GSTR-1",
        "next_action": "Contact supplier",
        "vendor_gstin": "27SUPPLIER0101Z",
        "vendor_name": "Supplier 101 Corp",
        "invoice_number": "INV-101",
        "invoice_date": "2025-01-10",
        "taxable_value": 100000.0,
        "total_tax": 18000.0,
        "itc_amount_at_stake": 18000.0,
        "itc_amount_at_stake_paise": 1800000,
        "is_blocking": True,
    }

    # 1. Insert work item
    inserted = vendor_compliance_repo.insert_work_item(wi_row)
    wi_id = inserted["id"]
    assert wi_id is not None
    assert inserted["status"] == "OPEN"
    assert inserted["priority"] == "HIGH"
    assert inserted["is_blocking"] is True

    # 2. Get work item
    fetched = vendor_compliance_repo.get_work_item(wi_id, client_gstin_id=ca)
    assert fetched is not None
    assert fetched["record_id"] == "rec-101"

    # 3. Insert work item event
    ev1 = vendor_compliance_repo.insert_work_item_event({
        "work_item_id": wi_id,
        "event_type": "CREATED",
        "to_status": "OPEN",
        "note": "Work item generated by reconciliation run",
    })
    assert ev1["work_item_id"] == wi_id

    # 4. Update work item
    updated = vendor_compliance_repo.update_work_item(
        wi_id,
        {
            "status": "TRIAGED",
            "priority": "CRITICAL",
            "assigned_to": fa,
        },
    )
    assert updated is not None
    assert updated["status"] == "TRIAGED"
    assert updated["priority"] == "CRITICAL"
    assert updated["assigned_to"] == fa

    # 5. Insert transition event
    ev2 = vendor_compliance_repo.insert_work_item_event({
        "work_item_id": wi_id,
        "event_type": "STATUS_CHANGED",
        "from_status": "OPEN",
        "to_status": "TRIAGED",
        "actor_id": fa,
        "note": "Work item triaged by CA",
    })

    # 6. List events
    events = vendor_compliance_repo.list_work_item_events(wi_id)
    assert len(events) == 2
    assert events[0]["event_type"] == "CREATED"
    assert events[1]["event_type"] == "STATUS_CHANGED"

    # 7. List work items with filters
    items, total = vendor_compliance_repo.list_work_items(
        client_gstin_id=ca,
        status="TRIAGED",
        priority="CRITICAL",
        vendor_gstin="27SUPPLIER0101Z",
    )
    assert total == 1
    assert len(items) == 1
    assert items[0]["id"] == wi_id

    # 8. Existing map for run
    ex_map = vendor_compliance_repo.get_existing_work_items_map_for_run(ra)
    assert ("rec-101", "MISSED_ITC") in ex_map

    # 9. Delete work items for run
    del_cnt = vendor_compliance_repo.delete_work_items_for_run(ra)
    assert del_cnt == 1
    assert vendor_compliance_repo.get_work_item(wi_id) is None
    # Events should be cascade deleted
    assert len(vendor_compliance_repo.list_work_item_events(wi_id)) == 0


def test_vendor_followup_logs_ops(configured_repos, seeded_env):
    """Verify Aurora repository operations for vendor_followup_logs."""
    vendor_compliance_repo = configured_repos
    ca = seeded_env["client_a_id"]
    token = "test-portal-token-9d13"

    log_row = {
        "client_gstin_id": ca,
        "supplier_gstin": "27SUPPLIER0888Z",
        "supplier_name": "Supplier 888 Pvt Ltd",
        "vendor_phone": "9998887776",
        "vendor_email": "supplier888@test.com",
        "channel": "WHATSAPP",
        "template_type": "POLITE_REMINDER",
        "invoices_count": 2,
        "at_risk_itc_rupees": 25000.0,
        "status": "SENT",
        "token": token,
        "invoices_snapshot": [
            {"invoice_number": "INV-888-A", "taxable_value": 100000.0, "tax_amount": 18000.0},
            {"invoice_number": "INV-888-B", "taxable_value": 50000.0, "tax_amount": 7000.0},
        ],
    }

    # 1. Insert log
    inserted = vendor_compliance_repo.insert_vendor_followup_log(log_row)
    log_id = inserted["id"]
    assert log_id is not None
    assert inserted["token"] == token
    assert inserted["status"] == "SENT"

    # 2. Get by token
    fetched_tok = vendor_compliance_repo.get_vendor_followup_log_by_token(token)
    assert fetched_tok is not None
    assert fetched_tok["id"] == log_id
    assert fetched_tok["supplier_gstin"] == "27SUPPLIER0888Z"
    assert len(fetched_tok["invoices_snapshot"]) == 2

    # 3. Get by ID
    fetched_id = vendor_compliance_repo.get_vendor_followup_log_by_id(log_id)
    assert fetched_id is not None
    assert fetched_id["token"] == token

    # 4. Update log (e.g. portal view and response)
    now_iso = datetime.now(timezone.utc).isoformat()
    updated = vendor_compliance_repo.update_vendor_followup_log(
        log_id,
        {
            "status": "FILING_CONFIRMED",
            "viewed_at": now_iso,
            "response_action": "ALREADY_FILED",
            "arn_number": "AA27082600123456",
            "responded_at": now_iso,
        },
    )
    assert updated is not None
    assert updated["status"] == "FILING_CONFIRMED"
    assert updated["response_action"] == "ALREADY_FILED"
    assert updated["arn_number"] == "AA27082600123456"

    # 5. Update logs by supplier
    up_cnt = vendor_compliance_repo.update_vendor_followup_logs_by_supplier(
        ca, "27SUPPLIER0888Z", {"vendor_phone": "9112233445"}
    )
    assert up_cnt >= 1
    log_check = vendor_compliance_repo.get_vendor_followup_log_by_id(log_id)
    assert log_check["vendor_phone"] == "9112233445"

    # 6. List logs for client
    client_logs = vendor_compliance_repo.list_vendor_followup_logs_for_client(ca)
    assert len(client_logs) >= 1
    assert client_logs[0]["id"] == log_id

    # 7. List logs for work item
    wi_logs = vendor_compliance_repo.list_vendor_followup_logs_for_work_item(uuid.uuid4())
    assert len(wi_logs) == 0


# ── Service Layer Tests ──────────────────────────────────────────────────────

def test_scorecard_service_cutover(configured_repos, seeded_env):
    """Verify supplier_compliance_scorecard service operates with Aurora as primary."""
    vendor_compliance_repo = configured_repos
    fa = seeded_env["user_a_id"]
    ca = seeded_env["client_a_id"]
    s_gstin = "27ABCDE1234F1Z5"

    counters = {
        s_gstin: SupplierClientCounters(
            supplier_gstin=s_gstin,
            trade_name="Alpha Tech Vendors",
            invoice_keys={"inv-1", "inv-2"},
            mismatch_keys={"inv-2"},
            rule37_open_count=1,
            rule37_at_risk_paise=15000,
            section_17_5_count=0,
            late_filing_count=0,
            pr_only_count=1,
            quarterly_filer_flag=False,
        )
    }

    broken_sb = BrokenSupabaseClient()

    # 1. Test _replace_client_contributions with broken Supabase client -> targets Aurora
    affected = _replace_client_contributions(
        broken_sb,
        firm_owner_id=fa,
        client_gstin_id=ca,
        counters=counters,
    )
    assert s_gstin in affected

    # 2. Test _rollup_suppliers with broken Supabase client -> targets Aurora
    _rollup_suppliers(broken_sb, firm_owner_id=fa, supplier_gstins=affected)

    # 3. Verify rolled-up record exists in Aurora
    summary = vendor_compliance_repo.get_supplier_compliance_summary(fa, s_gstin)
    assert summary is not None
    assert summary["supplier_gstin_normalized"] == s_gstin
    assert summary["total_invoices"] == 2
    assert summary["mismatch_invoice_count"] == 1
    assert summary["rule37_open_count"] == 1
    assert summary["rule37_at_risk_paise"] == 15000
    assert summary["clients_touched_count"] == 1


def test_itc_work_item_service_cutover(configured_repos, seeded_env):
    """Verify itc_work_item_service operations write to and read from Aurora."""
    vendor_compliance_repo = configured_repos
    fa = seeded_env["user_a_id"]
    ca = seeded_env["client_a_id"]
    ra = seeded_env["run_a_id"]
    user_a = seeded_env["user_a_dict"]

    broken_sb = BrokenSupabaseClient()

    # 1. Seed work item directly in Aurora
    wi = vendor_compliance_repo.insert_work_item({
        "firm_owner_id": fa,
        "client_gstin_id": ca,
        "run_id": ra,
        "record_id": "item-001",
        "exception_type": "MISSED_ITC",
        "status": "OPEN",
        "priority": "HIGH",
        "category": "INVOICE_MISSING",
        "title": "Missing Invoice INV-A1",
        "what": "Invoice missing in GSTR-2B",
        "why": "Section 16(2)(aa) bars ITC",
        "next_action": "Contact vendor",
        "vendor_gstin": "27SUPPA0000001Z",
        "vendor_name": "Supplier A1",
        "invoice_number": "INV-A1",
        "invoice_date": "2025-01-05",
        "taxable_value": 50000.0,
        "total_tax": 9000.0,
        "itc_amount_at_stake": 9000.0,
        "itc_amount_at_stake_paise": 900000,
        "is_blocking": True,
    })
    wi_id = wi["id"]

    # Record initial event
    vendor_compliance_repo.insert_work_item_event({
        "work_item_id": wi_id,
        "event_type": "CREATED",
        "to_status": "OPEN",
        "actor_id": fa,
        "note": "Work item initialized",
    })

    # 2. List work items
    listed = wis.list_work_items(broken_sb, ca, current_user=user_a)
    assert listed["total_count"] == 1
    assert listed["work_items"][0]["id"] == wi_id

    # 3. Get single work item
    fetched = wis.get_work_item(broken_sb, wi_id, user_a)
    assert fetched["id"] == wi_id
    assert len(fetched["events"]) >= 1

    # 4. Status transition: OPEN -> TRIAGED -> IN_PROGRESS
    trans = wis.transition_work_item_status(
        broken_sb,
        wi_id,
        "TRIAGED",
        user_a,
        note="Triaged for investigation",
    )
    assert trans["status"] == "TRIAGED"

    trans2 = wis.transition_work_item_status(
        broken_sb,
        wi_id,
        "IN_PROGRESS",
        user_a,
        note="Actively investigating invoice documentation",
    )
    assert trans2["status"] == "IN_PROGRESS"

    # 5. Priority override
    pri = wis.override_work_item_priority(
        broken_sb,
        wi_id,
        "CRITICAL",
        "High value ITC risk at quarter end",
        user_a,
    )
    assert pri["priority"] == "CRITICAL"
    assert pri["manual_priority"] == "CRITICAL"

    # 6. Assign work item
    assigned = wis.assign_work_item(broken_sb, wi_id, fa, user_a)
    assert assigned["assigned_to"] == fa

    # 7. Set due date
    due_str = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    due_res = wis.set_work_item_due_date(broken_sb, wi_id, due_str, user_a)
    assert due_res["due_at"] is not None

    # 8. Resolve work item
    resolved = wis.resolve_work_item(
        broken_sb,
        wi_id,
        "VENDOR_CORRECTION_RECEIVED",
        "Supplier uploaded invoice to GSTR-1 portal",
        user_a,
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution_code"] == "VENDOR_CORRECTION_RECEIVED"

    # 9. Reopen work item
    reopened = wis.reopen_work_item(
        broken_sb,
        wi_id,
        "Portal filing ARN was rejected by GSTN",
        user_a,
    )
    assert reopened["status"] == "IN_PROGRESS"
    assert reopened["reopen_reason"] == "Portal filing ARN was rejected by GSTN"

    # 10. Dismiss work item
    dismissed = wis.dismiss_work_item(
        broken_sb,
        wi_id,
        "Duplicate invoice entry in books",
        user_a,
    )
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["dismissal_reason"] == "Duplicate invoice entry in books"

    # 11. Verify all event timeline entries exist in Aurora
    aurora_events = vendor_compliance_repo.list_work_item_events(wi_id)
    assert len(aurora_events) >= 6
    types = [e["event_type"] for e in aurora_events]
    assert "CREATED" in types
    assert "STATUS_CHANGED" in types
    assert "PRIORITY_CHANGED" in types
    assert "RESOLUTION_APPROVED" in types
    assert "REOPENED" in types
    assert "DISMISSED" in types


def test_vendor_followup_engine_cutover(configured_repos, seeded_env):
    """Verify vendor_followup_engine operations write to and read from Aurora."""
    vendor_compliance_repo = configured_repos
    ca = seeded_env["client_a_id"]
    ua = seeded_env["user_a_id"]
    broken_sb = BrokenSupabaseClient()

    # 1. Log followup action
    res_log = vfe.log_followup_action(
        sb=broken_sb,
        client_gstin_id=ca,
        supplier_gstin="27VENDOR001234Z",
        supplier_name="Vendor 1234 Services",
        channel="WHATSAPP",
        template_type="POLITE_REMINDER",
        at_risk_itc_rupees=45000.0,
        vendor_phone="9876543210",
        vendor_email="vendor@services.com",
        message_body="Please file your GSTR-1 for 3 overdue invoices.",
        dispatched_by=ua,
    )
    assert res_log is not None
    assert res_log.get("id") is not None
    log_id = res_log["id"]

    # 2. Create or get followup token
    token_dict = vfe.create_or_get_followup_token(
        sb=broken_sb,
        client_gstin_id=ca,
        supplier_gstin="27VENDOR001234Z",
        supplier_name="Vendor 1234 Services",
        at_risk_itc_rupees=45000.0,
        work_item_id=None,
    )
    token = token_dict["token"]
    assert token is not None

    # 3. Get vendor portal data via token
    portal_data = vfe.get_vendor_portal_data(broken_sb, token)
    assert portal_data["supplier_gstin"] == "27VENDOR001234Z"
    assert portal_data["status"] == "VIEWED"

    # 4. Submit vendor portal response
    resp_result = vfe.submit_vendor_portal_response(
        sb=broken_sb,
        token=token,
        action="ALREADY_FILED",
        arn_number="AA2708260012345678",
    )
    assert resp_result["success"] is True
    assert resp_result["status"] == "FILING_CONFIRMED"
    assert resp_result["arn_number"] == "AA2708260012345678"

    # Verify updated record in Aurora
    aurora_log = vendor_compliance_repo.get_vendor_followup_log_by_token(token)
    assert aurora_log["status"] == "FILING_CONFIRMED"
    assert aurora_log["response_action"] == "ALREADY_FILED"
    assert aurora_log["arn_number"] == "AA2708260012345678"

    # 5. Update vendor contact info
    contact_up = vfe.update_vendor_contact_info(
        sb=broken_sb,
        client_gstin_id=ca,
        supplier_gstin="27VENDOR001234Z",
        vendor_phone="9988776655",
        vendor_email="new_email@vendor.com",
    )
    assert contact_up["vendor_phone"] == "9988776655"
    assert contact_up["vendor_email"] == "new_email@vendor.com"
    check_contact = vendor_compliance_repo.get_vendor_followup_log_by_token(token)
    assert check_contact["vendor_phone"] == "9988776655"
    assert check_contact["vendor_email"] == "new_email@vendor.com"

    # 6. Get followup history for client
    hist = vfe.get_followup_history(broken_sb, ca)
    assert len(hist) >= 1


def test_itc_revalidation_engine_cutover(configured_repos, seeded_env):
    """Verify itc_revalidation_engine operations write to and read from Aurora."""
    vendor_compliance_repo = configured_repos
    fa = seeded_env["user_a_id"]
    ca = seeded_env["client_a_id"]
    ra = seeded_env["run_a_id"]
    user_a = seeded_env["user_a_dict"]

    # 1. Seed work item in Aurora
    wi = vendor_compliance_repo.insert_work_item({
        "firm_owner_id": fa,
        "client_gstin_id": ca,
        "run_id": ra,
        "record_id": "reval-rec-1",
        "exception_type": "MISSING_IN_2B",
        "status": "OPEN",
        "priority": "HIGH",
        "category": "INVOICE_MISSING",
        "title": "Missing Invoice REVAL-1",
        "vendor_gstin": "27SUPPLIER0999Z",
        "invoice_number": "INV-REVAL-1",
        "invoice_date": "2025-01-15",
        "total_tax": 18000.0,
        "revalidation_status": "NONE",
    })
    wi_id = wi["id"]

    broken_sb = BrokenSupabaseClient()

    # 2. Request revalidation
    req_res = ire.request_revalidation(broken_sb, wi_id, user_a)
    assert req_res["revalidation_status"] == "PENDING"

    # Verify Aurora state
    aurora_wi = vendor_compliance_repo.get_work_item(wi_id)
    assert aurora_wi["revalidation_status"] == "PENDING"
    assert aurora_wi["revalidation_requested_at"] is not None

    # 3. Execute revalidation against Aurora
    exec_res = ire.execute_revalidation(broken_sb, wi_id, user_a)
    assert exec_res["revalidation_status"] in ("REVALIDATED", "RESOLVED")

    # Verify timeline events recorded in Aurora
    events = vendor_compliance_repo.list_work_item_events(wi_id)
    assert len(events) >= 2


def test_resolution_intelligence_cutover(configured_repos, seeded_env):
    """Verify resolution_intelligence_engine loads work item and metrics from Aurora."""
    vendor_compliance_repo = configured_repos
    fa = seeded_env["user_a_id"]
    ca = seeded_env["client_a_id"]
    ra = seeded_env["run_a_id"]
    user_a = seeded_env["user_a_dict"]

    # 1. Seed work item in Aurora
    wi = vendor_compliance_repo.insert_work_item({
        "firm_owner_id": fa,
        "client_gstin_id": ca,
        "run_id": ra,
        "record_id": "res-intel-rec-1",
        "exception_type": "RULE37_OVERDUE",
        "status": "OPEN",
        "priority": "HIGH",
        "category": "PAYMENT_OVERDUE",
        "title": "Rule 37 Overdue Tax Risk",
        "vendor_gstin": "27SUPPLIER0777Z",
        "invoice_number": "INV-INTEL-1",
        "invoice_date": "2024-06-01",
        "total_tax": 25000.0,
        "itc_amount_at_stake_paise": 2500000,
    })

    # 2. Seed supplier compliance summary (15 char GSTIN)
    vendor_compliance_repo.upsert_supplier_compliance_summary({
        "firm_owner_id": fa,
        "supplier_gstin_normalized": "27SUPPLIER0777Z",
        "supplier_trade_name": "Supplier 777 Works",
        "client_gstin_ids": [ca],
        "clients_touched_count": 1,
        "total_invoices": 15,
        "mismatch_invoice_count": 3,
        "rule37_open_count": 1,
        "risk_score": 60,
    })

    broken_sb = BrokenSupabaseClient()

    # 3. Call resolution intelligence with broken Supabase client -> reads Aurora
    intel = rie.get_work_item_resolution_intelligence(broken_sb, wi, user_a)
    assert intel["work_item_id"] == wi["id"]
    assert intel["exception_type"] == "RULE37_OVERDUE"
    assert "root_cause_explanation" in intel
    assert "next_best_action" in intel
    assert len(intel["evidence"]) > 0


# ── Multi-Tenant Isolation Tests ─────────────────────────────────────────────

def test_multitenant_isolation_batch2c(configured_repos, seeded_env):
    """Verify strict tenant isolation between Tenant A and Tenant B across all 6 tables."""
    vendor_compliance_repo = configured_repos
    fa = seeded_env["user_a_id"]
    fb = seeded_env["user_b_id"]
    ca = seeded_env["client_a_id"]
    cb = seeded_env["client_b_id"]
    ra = seeded_env["run_a_id"]
    rb = seeded_env["run_b_id"]
    user_a = seeded_env["user_a_dict"]
    user_b = seeded_env["user_b_dict"]

    # 1. Seed summaries with valid 15-char GSTINs
    vendor_compliance_repo.upsert_supplier_compliance_summary({
        "firm_owner_id": fa,
        "supplier_gstin_normalized": "27SUPPA0000001Z",
        "supplier_trade_name": "Vendor A",
        "client_gstin_ids": [ca],
        "total_invoices": 10,
    })
    vendor_compliance_repo.upsert_supplier_compliance_summary({
        "firm_owner_id": fb,
        "supplier_gstin_normalized": "27SUPPB0000001Z",
        "supplier_trade_name": "Vendor B",
        "client_gstin_ids": [cb],
        "total_invoices": 20,
    })

    # Assert summaries isolation
    sum_a, _ = vendor_compliance_repo.list_supplier_compliance_summary(fa)
    assert len(sum_a) == 1
    assert sum_a[0]["supplier_gstin_normalized"] == "27SUPPA0000001Z"

    sum_b, _ = vendor_compliance_repo.list_supplier_compliance_summary(fb)
    assert len(sum_b) == 1
    assert sum_b[0]["supplier_gstin_normalized"] == "27SUPPB0000001Z"

    # 2. Seed by_client contributions
    vendor_compliance_repo.replace_client_contributions(fa, ca, [{
        "firm_owner_id": fa,
        "client_gstin_id": ca,
        "supplier_gstin_normalized": "27SUPPA0000001Z",
        "total_invoices": 10,
    }])
    vendor_compliance_repo.replace_client_contributions(fb, cb, [{
        "firm_owner_id": fb,
        "client_gstin_id": cb,
        "supplier_gstin_normalized": "27SUPPB0000001Z",
        "total_invoices": 20,
    }])

    assert len(vendor_compliance_repo.get_by_client_rows_for_supplier(fa, "27SUPPB0000001Z")) == 0
    assert len(vendor_compliance_repo.get_by_client_rows_for_supplier(fb, "27SUPPA0000001Z")) == 0

    # 3. Seed follow-up audit
    vendor_compliance_repo.insert_supplier_followup_audit([
        {
            "run_id": ra,
            "client_gstin_id": ca,
            "supplier_gstin": "27SUPPA0000001Z",
            "invoice_count": 1,
            "total_tax_paise": 10000,
            "generated_by": fa,
        }
    ])
    vendor_compliance_repo.insert_supplier_followup_audit([
        {
            "run_id": rb,
            "client_gstin_id": cb,
            "supplier_gstin": "27SUPPB0000001Z",
            "invoice_count": 2,
            "total_tax_paise": 20000,
            "generated_by": fb,
        }
    ])

    audits_a = vendor_compliance_repo.list_supplier_followup_audit_for_run(ra)
    assert len(audits_a) == 1
    assert audits_a[0]["supplier_gstin"] == "27SUPPA0000001Z"

    audits_b = vendor_compliance_repo.list_supplier_followup_audit_for_run(rb)
    assert len(audits_b) == 1
    assert audits_b[0]["supplier_gstin"] == "27SUPPB0000001Z"

    # 4. Seed work items & events
    wi_a = vendor_compliance_repo.insert_work_item({
        "firm_owner_id": fa,
        "client_gstin_id": ca,
        "run_id": ra,
        "record_id": "iso-rec-a",
        "exception_type": "MISSED_ITC",
        "status": "OPEN",
        "vendor_gstin": "27SUPPA0000001Z",
    })
    wi_b = vendor_compliance_repo.insert_work_item({
        "firm_owner_id": fb,
        "client_gstin_id": cb,
        "run_id": rb,
        "record_id": "iso-rec-b",
        "exception_type": "MISSED_ITC",
        "status": "OPEN",
        "vendor_gstin": "27SUPPB0000001Z",
    })

    # Scoped get_work_item
    assert vendor_compliance_repo.get_work_item(wi_a["id"], client_gstin_id=cb) is None
    assert vendor_compliance_repo.get_work_item(wi_b["id"], client_gstin_id=ca) is None

    # Service-level cross-tenant authorization check
    broken_sb = BrokenSupabaseClient()
    with pytest.raises(Exception) as exc:
        wis.get_work_item(broken_sb, wi_a["id"], user_b)
    assert "403" in str(exc.value) or "404" in str(exc.value) or "denied" in str(exc.value).lower()

    # 5. Seed followup logs
    vendor_compliance_repo.insert_vendor_followup_log({
        "client_gstin_id": ca,
        "supplier_gstin": "27SUPPA0000001Z",
        "token": "token-iso-a",
        "status": "SENT",
    })
    vendor_compliance_repo.insert_vendor_followup_log({
        "client_gstin_id": cb,
        "supplier_gstin": "27SUPPB0000001Z",
        "token": "token-iso-b",
        "status": "SENT",
    })

    logs_a = vendor_compliance_repo.list_vendor_followup_logs_for_client(ca)
    assert len(logs_a) == 1
    assert logs_a[0]["token"] == "token-iso-a"

    logs_b = vendor_compliance_repo.list_vendor_followup_logs_for_client(cb)
    assert len(logs_b) == 1
    assert logs_b[0]["token"] == "token-iso-b"


# ── Run Cascade Cleanup Tests ────────────────────────────────────────────────

def test_run_cascade_cleanup_batch2c(configured_repos, seeded_env):
    """Verify run deletion cleans up audit rows, work items, and child events in Aurora."""
    vendor_compliance_repo = configured_repos
    fa = seeded_env["user_a_id"]
    ca = seeded_env["client_a_id"]
    ra = seeded_env["run_a_id"]
    rb = seeded_env["run_b_id"]

    # 1. Seed audit logs for run A and run B
    vendor_compliance_repo.insert_supplier_followup_audit([
        {
            "run_id": ra,
            "client_gstin_id": ca,
            "supplier_gstin": "27CLEANUP00001Z",
            "invoice_count": 1,
            "total_tax_paise": 10000,
            "generated_by": fa,
        },
        {
            "run_id": rb,
            "client_gstin_id": seeded_env["client_b_id"],
            "supplier_gstin": "27CLEANUP00002Z",
            "invoice_count": 1,
            "total_tax_paise": 20000,
            "generated_by": seeded_env["user_b_id"],
        },
    ])

    # 2. Seed work item & events for run A and run B
    wi_a = vendor_compliance_repo.insert_work_item({
        "firm_owner_id": fa,
        "client_gstin_id": ca,
        "run_id": ra,
        "record_id": "clean-rec-a",
        "exception_type": "MISSED_ITC",
        "status": "OPEN",
    })
    wi_b = vendor_compliance_repo.insert_work_item({
        "firm_owner_id": seeded_env["user_b_id"],
        "client_gstin_id": seeded_env["client_b_id"],
        "run_id": rb,
        "record_id": "clean-rec-b",
        "exception_type": "MISSED_ITC",
        "status": "OPEN",
    })

    vendor_compliance_repo.insert_work_item_event({
        "work_item_id": wi_a["id"],
        "event_type": "CREATED",
        "to_status": "OPEN",
    })
    vendor_compliance_repo.insert_work_item_event({
        "work_item_id": wi_b["id"],
        "event_type": "CREATED",
        "to_status": "OPEN",
    })

    # 3. Simulate run A deletion cascade
    vendor_compliance_repo.delete_supplier_followup_audit_for_run(ra)
    vendor_compliance_repo.delete_work_items_for_run(ra)

    # 4. Verify Run A records are wiped
    assert len(vendor_compliance_repo.list_supplier_followup_audit_for_run(ra)) == 0
    assert vendor_compliance_repo.get_work_item(wi_a["id"]) is None
    assert len(vendor_compliance_repo.list_work_item_events(wi_a["id"])) == 0

    # 5. Verify Run B records remain intact
    assert len(vendor_compliance_repo.list_supplier_followup_audit_for_run(rb)) == 1
    assert vendor_compliance_repo.get_work_item(wi_b["id"]) is not None
    assert len(vendor_compliance_repo.list_work_item_events(wi_b["id"])) == 1


# ── Full Broken Supabase Client Outage Resilience ────────────────────────────

def test_broken_supabase_client_resilience_batch2c(configured_repos, seeded_env):
    """Verify entire Batch 2C operates flawlessly when Supabase raises network errors."""
    vendor_compliance_repo = configured_repos
    fa = seeded_env["user_a_id"]
    ca = seeded_env["client_a_id"]
    ra = seeded_env["run_a_id"]
    user_a = seeded_env["user_a_dict"]

    broken_sb = BrokenSupabaseClient()

    # 1. Insert work item directly via Aurora repo
    wi = vendor_compliance_repo.insert_work_item({
        "firm_owner_id": fa,
        "client_gstin_id": ca,
        "run_id": ra,
        "record_id": "outage-wi-1",
        "exception_type": "MISSING_IN_2B",
        "status": "OPEN",
        "priority": "HIGH",
        "category": "INVOICE_MISSING",
        "title": "Missing Invoice INV-OUTAGE-1",
        "vendor_gstin": "27OUTAGE000001Z",
        "vendor_name": "Outage Resilience Vendor",
        "invoice_number": "INV-OUTAGE-1",
        "invoice_date": "2025-01-20",
        "taxable_value": 80000.0,
        "total_tax": 14400.0,
        "itc_amount_at_stake_paise": 1440000,
    })
    wi_id = wi["id"]

    # 2. Get and update work item via Broken Supabase
    wi_fetched = wis.get_work_item(broken_sb, wi_id, user_a)
    assert wi_fetched["id"] == wi_id

    trans = wis.transition_work_item_status(broken_sb, wi_id, "TRIAGED", user_a)
    assert trans["status"] == "TRIAGED"

    # 3. Create followup token via Broken Supabase
    tok_dict = vfe.create_or_get_followup_token(
        broken_sb,
        client_gstin_id=ca,
        supplier_gstin="27OUTAGE000001Z",
        supplier_name="Outage Resilience Vendor",
        at_risk_itc_rupees=14400.0,
        work_item_id=wi_id,
    )
    token = tok_dict["token"]
    assert token is not None

    # 4. View portal data via Broken Supabase
    p_data = vfe.get_vendor_portal_data(broken_sb, token)
    assert p_data["token"] == token
    assert p_data["status"] == "VIEWED"

    # 5. Submit vendor portal response via Broken Supabase
    resp = vfe.submit_vendor_portal_response(
        broken_sb,
        token=token,
        action="PROMISED_NEXT_CYCLE",
        promised_period="February 2025",
    )
    assert resp["success"] is True
    assert resp["status"] == "PROMISED_NEXT_CYCLE"

    # 6. Verify Aurora datastore received and persisted everything
    persisted_log = vendor_compliance_repo.get_vendor_followup_log_by_token(token)
    assert persisted_log["status"] == "PROMISED_NEXT_CYCLE"
    assert persisted_log["promised_period"] == "February 2025"

    persisted_wi = vendor_compliance_repo.get_work_item(wi_id)
    assert persisted_wi["status"] == "TRIAGED"
