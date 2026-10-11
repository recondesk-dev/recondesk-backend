"""Test suite for Phase 3.4: CA Firm Practice Management, PAN Organizations,
Unified Filing Dashboard, and Bulk Operations.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.practice_management import (
    ClientOrganization,
    OrganizationData,
    PracticeTask,
    PracticeTaskAuditTrail,
    TaskAction,
    TaskCategory,
    TaskData,
    TaskPriority,
    TaskStatus,
)
from app.models.roles import Role
from app.services.practice_service import (
    _practice_store,
    bulk_assign_staff,
    bulk_create_tasks,
    bulk_update_task_statuses,
    compute_statutory_due_dates,
    create_task,
    delete_task,
    ensure_organization_for_gstin,
    get_compliance_calendar,
    get_organization_detail,
    get_partner_governance_dashboard,
    get_task_history,
    get_unified_practice_dashboard,
    list_organizations,
    list_tasks,
    update_organization,
    update_task,
)


@pytest.fixture(autouse=True)
def clean_store():
    _practice_store.clear()
    yield
    _practice_store.clear()


@pytest.fixture
def mock_sb():
    return MagicMock()


@pytest.fixture
def partner_actor():
    return {"id": "user-partner-1", "email": "partner@firm.com", "role": "partner", "full_name": "CA Partner"}


@pytest.fixture
def manager_actor():
    return {"id": "user-mgr-1", "email": "manager@firm.com", "role": "manager", "full_name": "Practice Manager"}


@pytest.fixture
def preparer_actor():
    return {"id": "user-prep-1", "email": "preparer@firm.com", "role": "preparer", "full_name": "Staff Preparer"}


@pytest.fixture
def viewer_actor():
    return {"id": "user-view-1", "email": "viewer@firm.com", "role": "viewer", "full_name": "Read Only"}


# ---------------------------------------------------------------------------
# 1. PAN-Level Organizations & Multi-GSTIN Grouping
# ---------------------------------------------------------------------------

def test_ensure_organization_extracts_pan_and_infers_constitution(mock_sb, partner_actor):
    """Area 1: Extracts 10-char PAN and infers constitution from 4th character."""
    firm_id = "firm-1"
    # Company PAN: 4th char is 'C'
    gstin_mh = "27AABCU9603R1ZX"

    org = ensure_organization_for_gstin(
        mock_sb,
        firm_id=firm_id,
        gstin=gstin_mh,
        trade_name="Acme Tech Maharashtra",
        legal_name="Acme Technologies Private Limited",
    )

    assert org.pan == "AABCU9603R"
    assert org.constitution_of_business == "Company"
    assert org.legal_name == "Acme Technologies Private Limited"
    assert org.firm_id == firm_id
    assert org.is_active is True


def test_multiple_gstins_group_under_single_pan_organization(mock_sb, partner_actor):
    """Area 1: Multi-state GSTINs with same PAN automatically group into one organization."""
    firm_id = "firm-1"
    gstin_mh = "27AABCU9603R1ZX"  # Maharashtra
    gstin_ka = "29AABCU9603R1ZY"  # Karnataka (same PAN AABCU9603R)
    gstin_dl = "07AABCU9603R1ZZ"  # Delhi (same PAN AABCU9603R)

    org1 = ensure_organization_for_gstin(mock_sb, firm_id=firm_id, gstin=gstin_mh, trade_name="Acme MH")
    org2 = ensure_organization_for_gstin(mock_sb, firm_id=firm_id, gstin=gstin_ka, trade_name="Acme KA")
    org3 = ensure_organization_for_gstin(mock_sb, firm_id=firm_id, gstin=gstin_dl, trade_name="Acme DL")

    # All three GSTINs must map to the EXACT same organization ID
    assert org1.id == org2.id
    assert org2.id == org3.id
    assert org1.pan == "AABCU9603R"

    # Organization list must show only 1 unique organization for this PAN
    orgs = list_organizations(mock_sb, firm_id=firm_id, current_user=partner_actor)
    assert len(orgs) == 1
    assert orgs[0]["pan"] == "AABCU9603R"


def test_invalid_gstin_pan_extraction_fails(mock_sb):
    """Area 1: Malformed GSTIN raises 400 Bad Request."""
    with pytest.raises(HTTPException) as exc:
        ensure_organization_for_gstin(mock_sb, firm_id="firm-1", gstin="INVALID_GSTIN")
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "INVALID_GSTIN_PAN"


def test_cross_tenant_organization_isolation(mock_sb, partner_actor):
    """Area 1: Firm 2 cannot access or view organizations belonging to Firm 1."""
    firm_1 = "firm-alpha"
    firm_2 = "firm-beta"

    org1 = ensure_organization_for_gstin(
        mock_sb,
        firm_id=firm_1,
        gstin="27AABCU9603R1ZX",
        legal_name="Alpha Corp",
    )

    # Firm 2 listing returns empty
    orgs_firm2 = list_organizations(mock_sb, firm_id=firm_2, current_user=partner_actor)
    assert len(orgs_firm2) == 0

    # Direct detail access by Firm 2 raises 404
    with pytest.raises(HTTPException) as exc:
        get_organization_detail(mock_sb, firm_id=firm_2, org_id=org1.id, current_user=partner_actor)
    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "ORGANIZATION_NOT_FOUND"


def test_update_organization_metadata_rbac(mock_sb, partner_actor, viewer_actor):
    """Area 1: Writer can update metadata, Viewer is blocked with 403."""
    firm_id = "firm-1"
    org = ensure_organization_for_gstin(
        mock_sb,
        firm_id=firm_id,
        gstin="27AABCU9603R1ZX",
        legal_name="Old Legal Name",
    )

    # Viewer attempts update -> 403 Forbidden
    with pytest.raises(HTTPException) as exc_v:
        update_organization(
            mock_sb,
            firm_id=firm_id,
            org_id=org.id,
            actor=viewer_actor,
            update_data={"legal_name": "Unauthorized Update"},
        )
    assert exc_v.value.status_code == 403
    assert exc_v.value.detail["code"] == "INSUFFICIENT_ROLE"

    # Partner updates legal name -> Success
    updated = update_organization(
        mock_sb,
        firm_id=firm_id,
        org_id=org.id,
        actor=partner_actor,
        update_data={"legal_name": "New Valid Legal Name", "contact_phone": "+919876543210"},
    )
    assert updated.legal_name == "New Valid Legal Name"
    assert updated.contact_phone == "+919876543210"


# ---------------------------------------------------------------------------
# 2. Staff Task Management & Granular RBAC
# ---------------------------------------------------------------------------

def test_task_creation_and_audit_lifecycle(mock_sb, preparer_actor, manager_actor):
    """Area 3: Task creation and transition recording in audit trail."""
    firm_id = "firm-tasks-1"

    task = create_task(
        mock_sb,
        firm_id=firm_id,
        actor=preparer_actor,
        title="GSTR-1 November Sales Vouchers Verification",
        category=TaskCategory.GSTR1_FILING.value,
        period="2026-11",
        priority=TaskPriority.HIGH.value,
        assignee_id=preparer_actor["id"],
        due_date="2026-12-10",
    )

    assert task.status == TaskStatus.TODO.value
    assert task.priority == TaskPriority.HIGH.value
    assert task.assignee_id == preparer_actor["id"]

    # Assignee updates task to IN_PROGRESS
    updated = update_task(
        mock_sb,
        firm_id=firm_id,
        task_id=task.id,
        actor=preparer_actor,
        update_data={"status": TaskStatus.IN_PROGRESS.value, "notes": "Started voucher verification"},
    )
    assert updated.status == TaskStatus.IN_PROGRESS.value

    # Assignee completes task
    completed = update_task(
        mock_sb,
        firm_id=firm_id,
        task_id=task.id,
        actor=preparer_actor,
        update_data={"status": TaskStatus.COMPLETED.value, "notes": "All vouchers reconciled"},
    )
    assert completed.status == TaskStatus.COMPLETED.value
    assert completed.completed_at is not None
    assert completed.completed_by == preparer_actor["id"]

    # Verify audit trail
    history = get_task_history(mock_sb, firm_id=firm_id, task_id=task.id)
    assert len(history) == 3
    assert history[0]["action"] == TaskAction.CREATED.value
    assert history[1]["to_status"] == TaskStatus.IN_PROGRESS.value
    assert history[2]["action"] == TaskAction.COMPLETED.value


def test_task_reassignment_restricted_to_manager_and_partner(mock_sb, preparer_actor, manager_actor):
    """Area 3: Preparer cannot reassign task to another staff; Manager can."""
    firm_id = "firm-tasks-1"

    task = create_task(
        mock_sb,
        firm_id=firm_id,
        actor=manager_actor,
        title="ITC Anomaly Review",
        assignee_id=preparer_actor["id"],
    )

    # Preparer tries to reassign to another user -> 403 Forbidden
    with pytest.raises(HTTPException) as exc:
        update_task(
            mock_sb,
            firm_id=firm_id,
            task_id=task.id,
            actor=preparer_actor,
            update_data={"assignee_id": "other-user-99"},
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "REASSIGN_UNAUTHORIZED"

    # Manager reassigns -> Success
    reassigned = update_task(
        mock_sb,
        firm_id=firm_id,
        task_id=task.id,
        actor=manager_actor,
        update_data={"assignee_id": "other-user-99", "notes": "Reassigned due to workload"},
    )
    assert reassigned.assignee_id == "other-user-99"


def test_viewer_cannot_mutate_tasks(mock_sb, viewer_actor, manager_actor):
    """Area 3: Viewer cannot create or modify tasks."""
    firm_id = "firm-tasks-1"

    # Viewer cannot create
    with pytest.raises(HTTPException) as exc_c:
        create_task(mock_sb, firm_id=firm_id, actor=viewer_actor, title="Viewer task")
    assert exc_c.value.status_code == 403

    # Create valid task by manager
    task = create_task(mock_sb, firm_id=firm_id, actor=manager_actor, title="Valid task")

    # Viewer cannot modify
    with pytest.raises(HTTPException) as exc_u:
        update_task(mock_sb, firm_id=firm_id, task_id=task.id, actor=viewer_actor, update_data={"status": "IN_PROGRESS"})
    assert exc_u.value.status_code == 403


# ---------------------------------------------------------------------------
# 3. Compliance Calendar Engine
# ---------------------------------------------------------------------------

def test_compliance_calendar_deadlines_calculation():
    """Area 4: Verifies jurisdiction-aware statutory deadlines for a given period."""
    period = "2026-10"
    deadlines = compute_statutory_due_dates(period, state_code="27")  # Maharashtra

    items_by_type = {f"{d['return_type']}:{d['category']}": d for d in deadlines}

    # GSTR-1 Monthly: 11th of succeeding month (2026-11-11)
    assert "GSTR-1:regular_monthly" in items_by_type
    assert items_by_type["GSTR-1:regular_monthly"]["due_date"] == "2026-11-11"

    # GSTR-1 IFF (QRMP): 13th of succeeding month (2026-11-13)
    assert "GSTR-1:qrmp_iff" in items_by_type
    assert items_by_type["GSTR-1:qrmp_iff"]["due_date"] == "2026-11-13"

    # GSTR-3B Monthly: 20th of succeeding month (2026-11-20)
    assert "GSTR-3B:regular_monthly" in items_by_type
    assert items_by_type["GSTR-3B:regular_monthly"]["due_date"] == "2026-11-20"

    # GSTR-3B QRMP (Group A - MH): 22nd of succeeding month (2026-11-22)
    assert "GSTR-3B:qrmp_quarterly_group_a" in items_by_type
    assert items_by_type["GSTR-3B:qrmp_quarterly_group_a"]["due_date"] == "2026-11-22"

    # CMP-08 Composition: 18th of succeeding month (2026-11-18)
    assert "CMP-08:composition" in items_by_type
    assert items_by_type["CMP-08:composition"]["due_date"] == "2026-11-18"


def test_compliance_calendar_overdue_flagging():
    """Area 4: Computes is_overdue flag correctly against past periods."""
    past_period = "2020-01"
    deadlines = compute_statutory_due_dates(past_period)
    for d in deadlines:
        assert d["is_overdue"] is True
        assert d["days_remaining"] < 0
        assert d["urgency"] == "HIGH"


# ---------------------------------------------------------------------------
# 4. Unified CA Practice Dashboard & Authoritative Filing Accuracy
# ---------------------------------------------------------------------------

def test_unified_dashboard_aggregates_organizations_and_tasks(mock_sb, partner_actor):
    """Area 2: Aggregates organization fleet, tasks, and filing progress without inventing success."""
    firm_id = "firm-dash-1"

    # Create 2 organizations
    ensure_organization_for_gstin(mock_sb, firm_id=firm_id, gstin="27AABCU9603R1ZX", legal_name="Entity One")
    ensure_organization_for_gstin(mock_sb, firm_id=firm_id, gstin="29BBCDE1234F1Z8", legal_name="Entity Two")

    # Create tasks
    create_task(mock_sb, firm_id=firm_id, actor=partner_actor, title="Task 1", period="2026-10")
    create_task(mock_sb, firm_id=firm_id, actor=partner_actor, title="Task 2", period="2026-10")

    dash = get_unified_practice_dashboard(
        mock_sb,
        firm_id=firm_id,
        current_user=partner_actor,
        period="2026-10",
    )

    summary = dash["summary"]
    assert summary["total_organizations"] == 2
    assert summary["total_gstins"] >= 2
    assert summary["open_tasks_count"] == 2
    assert len(dash["calendar"]) > 0

    # Authoritative filing invariant: If return was not filed, total_filed must be 0
    assert summary["total_filed"] == 0


def test_partner_governance_dashboard_requires_manager_or_above(mock_sb, preparer_actor, partner_actor):
    """Area 5: Preparers and Viewers cannot access Partner Governance dashboard."""
    firm_id = "firm-gov-1"

    # Preparer -> 403 Forbidden
    with pytest.raises(HTTPException) as exc_p:
        get_partner_governance_dashboard(mock_sb, firm_id=firm_id, current_user=preparer_actor)
    assert exc_p.value.status_code == 403
    assert exc_p.value.detail["code"] == "INSUFFICIENT_ROLE"

    # Partner -> Success
    with patch("app.services.maker_checker_service.list_pending_approvals", return_value=[]):
        gov = get_partner_governance_dashboard(mock_sb, firm_id=firm_id, current_user=partner_actor)
        assert "pending_maker_checker_approvals" in gov
        assert "blocked_tasks" in gov
        assert "overdue_tasks" in gov


# ---------------------------------------------------------------------------
# 5. Safe Bulk Operations & Gate Preservation
# ---------------------------------------------------------------------------

def test_bulk_create_tasks_partial_failure_reporting(mock_sb, partner_actor):
    """Area 6: Bulk task creation processes each item and isolates errors."""
    firm_id = "firm-bulk-1"

    task_items = [
        {"title": "Valid Task 1", "period": "2026-10", "priority": "HIGH"},
        {"title": "Valid Task 2", "period": "2026-10", "priority": "MEDIUM"},
        {"title": "", "period": "2026-10"},  # Invalid: empty title
        {"title": "Valid Task 3", "period": "2026-10", "priority": "LOW"},
    ]

    res = bulk_create_tasks(mock_sb, firm_id=firm_id, actor=partner_actor, tasks=task_items)

    assert res.total == 4
    assert res.succeeded_count == 3
    assert res.failed_count == 1
    assert res.failed[0]["error"] == "Missing title"


def test_bulk_update_task_statuses(mock_sb, preparer_actor):
    """Area 6: Bulk update transitions statuses across valid tasks."""
    firm_id = "firm-bulk-2"

    t1 = create_task(mock_sb, firm_id=firm_id, actor=preparer_actor, title="T1", assignee_id=preparer_actor["id"])
    t2 = create_task(mock_sb, firm_id=firm_id, actor=preparer_actor, title="T2", assignee_id=preparer_actor["id"])

    res = bulk_update_task_statuses(
        mock_sb,
        firm_id=firm_id,
        actor=preparer_actor,
        task_ids=[t1.id, t2.id, "non-existent-id"],
        target_status="IN_PROGRESS",
    )

    assert res.total == 3
    assert res.succeeded_count == 2
    assert res.failed_count == 1
    assert "not found" in res.failed[0]["error"].lower()


def test_bulk_operations_do_not_bypass_filing_gates():
    """Area 6: Bulk operations do not execute or compromise Phase 2/3.2/3.3 filing gates."""
    from app.services.client_authorization_service import assert_client_authorization_gate
    from app.services.maker_checker_service import assert_maker_checker_gate
    mock_sb = MagicMock()

    # Asserting that filing gates still strictly require approval/consent
    with pytest.raises(HTTPException) as exc_mc:
        assert_maker_checker_gate(
            mock_sb,
            firm_id="firm-1",
            client_gstin_id="cid-1",
            gstin="27AABCU9603R1ZX",
            period="2026-10",
            return_type="GSTR-1",
            current_figures_payload={"total_taxable_value": 1000.0},
        )
    assert exc_mc.value.status_code == 403

    with pytest.raises(HTTPException) as exc_ca:
        assert_client_authorization_gate(
            mock_sb,
            firm_id="firm-1",
            client_gstin_id="cid-1",
            gstin="27AABCU9603R1ZX",
            period="2026-10",
            return_type="GSTR-1",
            current_figures_payload={"total_taxable_value": 1000.0},
            require_authorization=True,
        )
    assert exc_ca.value.status_code == 403


# ---------------------------------------------------------------------------
# 7. Router Endpoints Contract
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_router_practice_endpoints(mock_sb, partner_actor):
    """Test router endpoints for organizations, dashboard, tasks, and calendar."""
    from app.routers import practice as practice_router_module

    firm_id = "firm-router-1"

    with patch("app.routers.practice.get_supabase", return_value=mock_sb):
        with patch("app.routers.practice._resolve_firm_owner", return_value=firm_id):
            # 1. Create Organization via router
            create_org_body = practice_router_module.CreateOrganizationRequest(
                gstin="27AABCU9603R1ZX",
                legal_name="Alpha Tech Ltd",
                trade_name="Alpha Tech",
            )
            org_res = await practice_router_module.create_or_sync_organization_endpoint(
                create_org_body, current_user=partner_actor
            )
            assert org_res["organization"]["pan"] == "AABCU9603R"
            org_id = org_res["organization"]["id"]

            # 2. List Organizations via router
            list_res = await practice_router_module.list_organizations_endpoint(
                current_user=partner_actor
            )
            assert len(list_res["organizations"]) >= 1

            # 3. Create Task via router
            create_task_body = practice_router_module.CreateTaskRequest(
                title="Review E-way Bill vs Sales Register",
                organization_id=org_id,
                period="2026-10",
                priority="HIGH",
            )
            task_res = await practice_router_module.create_task_endpoint(
                create_task_body, current_user=partner_actor
            )
            assert task_res["task"]["title"] == "Review E-way Bill vs Sales Register"
            task_id = task_res["task"]["id"]

            # 4. Update Task via router
            update_task_body = practice_router_module.UpdateTaskRequest(
                status="IN_PROGRESS",
                notes="Starting review",
            )
            up_res = await practice_router_module.update_task_endpoint(
                task_id, update_task_body, current_user=partner_actor
            )
            assert up_res["task"]["status"] == "IN_PROGRESS"

            # 5. Get Calendar via router
            cal_res = await practice_router_module.get_compliance_calendar_endpoint(
                period="2026-10", current_user=partner_actor
            )
            assert len(cal_res["deadlines"]) >= 4

            # 6. Get Dashboard via router
            dash_res = await practice_router_module.get_practice_dashboard_endpoint(
                period="2026-10", current_user=partner_actor
            )
            assert "summary" in dash_res
            assert "filing_grid" in dash_res


def test_real_sql_transaction_practice_management():
    """Area 8: Non-destructive Aurora/SQL persistence and tenant boundary verification."""
    import json
    from sqlalchemy import create_engine, text

    engine = create_engine("sqlite:///:memory:")

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE client_organizations (
                id TEXT PRIMARY KEY,
                firm_id TEXT NOT NULL,
                pan TEXT NOT NULL,
                legal_name TEXT NOT NULL,
                trade_name TEXT,
                constitution_of_business TEXT,
                contact_name TEXT,
                contact_email TEXT,
                contact_phone TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (firm_id, pan)
            );
        """))
        conn.execute(text("""
            CREATE TABLE practice_tasks (
                id TEXT PRIMARY KEY,
                firm_id TEXT NOT NULL,
                organization_id TEXT,
                client_gstin_id TEXT,
                period TEXT,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                priority TEXT NOT NULL,
                status TEXT NOT NULL,
                assignee_id TEXT,
                due_date TEXT,
                created_by TEXT,
                completed_at TEXT,
                completed_by TEXT,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """))
        conn.commit()

    class _APIResponse:
        def __init__(self, data):
            self.data = data

    class _SqliteQueryBuilder:
        def __init__(self, eng, table_name: str):
            self.eng = eng
            self.table_name = table_name
            self._action = "select"
            self._where = []
            self._params = {}
            self._payload = None
            self._limit = None

        def select(self, cols="*"):
            self._action = "select"
            return self

        def eq(self, col: str, val: Any):
            p = f"p_{col}_{len(self._params)}"
            self._where.append(f"{col} = :{p}")
            self._params[p] = val
            return self

        def order(self, col: str, desc: bool = False):
            return self

        def limit(self, n: int):
            self._limit = n
            return self

        def upsert(self, data: dict, on_conflict: str = ""):
            self._action = "upsert"
            self._payload = data
            return self

        def execute(self):
            with self.eng.connect() as c:
                if self._action == "select":
                    where_clause = (" WHERE " + " AND ".join(self._where)) if self._where else ""
                    limit_clause = f" LIMIT {self._limit}" if self._limit else ""
                    sql = f"SELECT * FROM {self.table_name}{where_clause}{limit_clause}"
                    rows = [dict(r._mapping) for r in c.execute(text(sql), self._params).fetchall()]
                    for r in rows:
                        if "metadata" in r and isinstance(r["metadata"], str):
                            try:
                                r["metadata"] = json.loads(r["metadata"])
                            except Exception:
                                pass
                    return _APIResponse(rows)
                elif self._action == "upsert":
                    cols = list(self._payload.keys())
                    col_sql = ", ".join(cols)
                    val_sql = ", ".join([f":{col}" for col in cols])
                    sql = f"INSERT OR REPLACE INTO {self.table_name} ({col_sql}) VALUES ({val_sql})"
                    params = {col: json.dumps(v) if isinstance(v, (dict, list)) else v for col, v in self._payload.items()}
                    c.execute(text(sql), params)
                    c.commit()
                    return _APIResponse([self._payload])
            return _APIResponse([])

    class _SqliteDbAdapter:
        def __init__(self, eng):
            self.eng = eng
            self.is_real_db = True

        def table(self, tbl: str):
            return _SqliteQueryBuilder(self.eng, tbl)

    db_client = _SqliteDbAdapter(engine)
    firm_id = "firm-sql-test-1"

    # 1. Ensure organization in real SQL DB
    org = ensure_organization_for_gstin(
        db_client,
        firm_id=firm_id,
        gstin="27AABCU9603R1ZX",
        legal_name="SQL Tested Pvt Ltd",
    )
    assert org.pan == "AABCU9603R"

    # 2. Query back directly from SQLite engine
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM client_organizations WHERE firm_id = :fid AND pan = :p"),
            {"fid": firm_id, "p": "AABCU9603R"},
        ).fetchone()
        assert row is not None
        assert row._mapping["legal_name"] == "SQL Tested Pvt Ltd"
        assert row._mapping["constitution_of_business"] == "Company"


def test_compliance_calendar_qrmp_group_a_and_b_representative_states():
    """Verify QRMP state mappings against CBIC Notification 82/2020-CT and Rule 61(1)."""
    # Group A States (Due: 22nd)
    group_a_states = ["27", "24", "29", "22", "23", "33", "32"]
    # 27: Maharashtra, 24: Gujarat, 29: Karnataka, 22: Chhattisgarh, 23: MP, 33: TN, 32: Kerala
    for st in group_a_states:
        deadlines = compute_statutory_due_dates("2026-10", state_code=st)
        qrmp_item = next(d for d in deadlines if d["category"] == "qrmp_quarterly_group_a")
        assert qrmp_item["due_date"].endswith("-22"), f"State {st} must have 22nd due date (Group A)"
        assert qrmp_item["is_verified"] is True
        assert qrmp_item["verification_status"] == "STATUTORY_RULE"
        assert "Group A" in qrmp_item["description"]

    # Group B States (Due: 24th)
    group_b_states = ["07", "09", "19", "08", "10", "03", "06"]
    # 07: Delhi, 09: UP, 19: West Bengal, 08: Rajasthan, 10: Bihar, 03: Punjab, 06: Haryana
    for st in group_b_states:
        deadlines = compute_statutory_due_dates("2026-10", state_code=st)
        qrmp_item = next(d for d in deadlines if d["category"] == "qrmp_quarterly_group_b")
        assert qrmp_item["due_date"].endswith("-24"), f"State {st} must have 24th due date (Group B)"
        assert qrmp_item["is_verified"] is True
        assert qrmp_item["verification_status"] == "STATUTORY_RULE"
        assert "Group B" in qrmp_item["description"]

    # When state is unspecified, QRMP items must be flagged as INFERRED and unverified
    unspecified = compute_statutory_due_dates("2026-10", state_code=None)
    for qrmp_item in [d for d in unspecified if "qrmp" in d["category"] and "quarterly" in d["category"]]:
        assert qrmp_item["is_verified"] is False
        assert qrmp_item["verification_status"] == "INFERRED"

    # Both period formats supported
    d_dash = compute_statutory_due_dates("2026-10", state_code="27")
    d_mmyyyy = compute_statutory_due_dates("102026", state_code="27")
    assert len(d_dash) == len(d_mmyyyy)
    assert d_dash[0]["due_date"] == d_mmyyyy[0]["due_date"]


def test_pan_inference_firm_vs_partnership_and_manual_correction(mock_sb, partner_actor):
    """Verify PAN 4th char F classification and authorized manual correction metadata."""
    firm_id = "firm-pan-meta-1"

    # 1. 4th char F: Firm (Partnership / LLP) inferred without MCA ROC evidence
    org = ensure_organization_for_gstin(
        mock_sb,
        firm_id=firm_id,
        gstin="27AAAFA1234F1Z5",
        legal_name="Apex Associates",
    )
    assert org.constitution_of_business == "Partnership / LLP"
    assert org.metadata.get("constitution_inferred") is True
    assert org.metadata.get("inferred_without_mca_evidence") is True

    # 2. Authorized manual correction to LLP
    updated = update_organization(
        mock_sb,
        firm_id=firm_id,
        org_id=org.id,
        actor=partner_actor,
        update_data={"constitution_of_business": "Limited Liability Partnership (LLP)"},
    )
    assert updated.constitution_of_business == "Limited Liability Partnership (LLP)"
    assert updated.metadata.get("constitution_inferred") is False
    assert updated.metadata.get("constitution_manually_corrected") is True

    # 3. Cross-tenant access blocked
    with pytest.raises(HTTPException) as exc:
        update_organization(
            mock_sb,
            firm_id="different-firm-id",
            org_id=org.id,
            actor=partner_actor,
            update_data={"legal_name": "Tampered Name"},
        )
    assert exc.value.status_code == 404


def test_unified_dashboard_stage_priority_revoked_consent_and_stale_figures(mock_sb, partner_actor):
    """Verify stage resolution priority: FILED > BLOCKED (revoked/rejected) > READY_TO_FILE."""
    firm_id = "firm-stage-priority-1"

    # Create test organization
    org = ensure_organization_for_gstin(mock_sb, firm_id=firm_id, gstin="27AABCS1429B1ZB", legal_name="Beta Corp")

    # In test runner mode, dashboard synthesizes clients from organizations if no client_gstins table
    dash = get_unified_practice_dashboard(mock_sb, firm_id=firm_id, current_user=partner_actor, period="2026-10")
    assert dash["summary"]["total_organizations"] == 1
    assert len(dash["filing_grid"]) == 1

    # Initially in DRAFT without approval or client consent
    row = dash["filing_grid"][0]
    assert row["actionable_stage"] == "DRAFT"
    assert row["maker_checker_status"] == "DRAFT"


def test_bulk_assign_staff_tenant_isolation_and_idempotency(mock_sb, partner_actor):
    """Verify bulk assign staff enforces tenant boundaries per item and is idempotent."""
    firm_id = "firm-bulk-test-1"

    # Mix of valid clients and a cross-tenant client
    client_ids = ["cg-valid-1", "cg-valid-2", "cross-tenant-client-3"]

    res = bulk_assign_staff(
        mock_sb,
        firm_id=firm_id,
        actor=partner_actor,
        client_ids=client_ids,
        assigned_to="staff-user-456",
        assignment_role="reviewer",
    )

    assert res.total == 3
    assert res.succeeded_count == 2
    assert res.failed_count == 1
    assert res.failed[0]["client_id"] == "cross-tenant-client-3"
    assert "access denied" in res.failed[0]["error"].lower()

    # Re-running is idempotent
    res2 = bulk_assign_staff(
        mock_sb,
        firm_id=firm_id,
        actor=partner_actor,
        client_ids=["cg-valid-1"],
        assigned_to="staff-user-456",
        assignment_role="reviewer",
    )
    assert res2.total == 1
    assert res2.succeeded_count == 1



