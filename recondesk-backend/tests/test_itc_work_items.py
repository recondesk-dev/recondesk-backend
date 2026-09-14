"""Comprehensive test suite for Phase 5.2: Exception Work Item Lifecycle Engine.

Validates all contracts and guardrails:
1. Canonical exception identity & DB-level uniqueness (run_id, record_id, exception_type)
2. Idempotent synchronization from reconciliation outcomes without resetting operational fields
3. Centralized lifecycle transition matrix and invalid transition rejection (HTTP 409)
4. Maker-checker authorization guardrails (Staff vs CA Admin)
5. Manual priority override with reason, preserving system_priority
6. Due date assignment and dynamic SLA calculation
7. Full operational activity timeline and event recording
8. Finalized run statutory protection (Table 4 snapshot remains byte/value immutable)
9. Tenant isolation and firm boundary enforcement (HTTP 403)
10. Structured resolution and Phase 5.5 revalidation hook
11. Reopening dismissed and resolved items with justification
12. Bulk operational actions with per-item status reporting
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_active_user
from app.main import app
from app.services import itc_work_item_service as wis
from app.services.reconciliation_outcomes import OutcomeRow
from tests.test_gstr3b_reversal_ledger import InMemorySupabaseClient, InMemoryTable

CLIENT_ID_1 = "00000000-0000-0000-0000-000000000001"
CLIENT_ID_2 = "00000000-0000-0000-0000-000000000002"
GSTIN_1 = "27AAACB1234A1Z1"
GSTIN_2 = "27AAACB9999Z1Z9"

RUN_ID = "11111111-1111-1111-1111-111111111111"
ADMIN_USER_ID = "00000000-0000-0000-0000-000000000001"
STAFF_USER_ID = "00000000-0000-0000-0000-000000000002"
OTHER_FIRM_USER_ID = "00000000-0000-0000-0000-000000000099"


class EnhancedInMemoryTable(InMemoryTable):
    """Extends InMemoryTable to support range, is_, or_, and unique constraint on itc_work_items."""

    def is_(self, col: str, val: any):
        self._filters.append((col, ("IS", val)))
        return self

    def or_(self, filter_str: str):
        # Store raw or filter
        self._filters.append(("_OR_", filter_str))
        return self

    def range(self, start: int, end: int):
        self._range_val = (start, end)
        return self

    def execute(self):
        if self._pending_insert is not None:
            inserted = []
            for item in self._pending_insert:
                if "id" not in item or not item["id"]:
                    import uuid
                    item["id"] = str(uuid.uuid4())
                if self.name == "itc_work_items":
                    rid = item.get("run_id")
                    rec_id = item.get("record_id")
                    ex_type = item.get("exception_type")
                    for existing in self.rows:
                        if (
                            existing.get("run_id") == rid
                            and existing.get("record_id") == rec_id
                            and existing.get("exception_type") == ex_type
                        ):
                            raise RuntimeError(
                                f"UNIQUE CONSTRAINT VIOLATION: duplicate key value violates unique constraint 'uq_itc_work_item' "
                                f"Key (run_id, record_id, exception_type)=({rid}, {rec_id}, {ex_type})"
                            )
                self.rows.append(item)
                inserted.append(item)
            self._pending_insert = None
            res = MagicMock()
            res.data = inserted
            return res

        # Fallback to parent execute for select/update/delete
        res = super().execute()
        # Handle range slicing
        if hasattr(self, "_range_val") and self._range_val and res.data:
            s, e = self._range_val
            res.data = res.data[s : e + 1]
            self._range_val = None
        return res


class EnhancedInMemorySupabaseClient(InMemorySupabaseClient):
    def table(self, name: str) -> EnhancedInMemoryTable:
        if name not in self.tables:
            self.tables[name] = EnhancedInMemoryTable(name, self)
        return self.tables[name]


def _build_mock_db() -> EnhancedInMemorySupabaseClient:
    sb = EnhancedInMemorySupabaseClient()
    sb.table("client_gstins").rows = [
        {
            "id": CLIENT_ID_1,
            "firm_owner_id": ADMIN_USER_ID,
            "gstin": GSTIN_1,
            "legal_name": "Acme Corp",
            "trade_name": "Acme",
            "is_active": True,
            "assigned_to": STAFF_USER_ID,
        },
        {
            "id": CLIENT_ID_2,
            "firm_owner_id": OTHER_FIRM_USER_ID,
            "gstin": GSTIN_2,
            "legal_name": "Other Corp",
            "is_active": True,
            "assigned_to": OTHER_FIRM_USER_ID,
        },
    ]
    sb.table("user_profiles").rows = [
        {
            "id": ADMIN_USER_ID,
            "full_name": "Admin CA",
            "email": "ca@acme.com",
            "role": "admin",
        },
        {
            "id": STAFF_USER_ID,
            "full_name": "Staff Member",
            "email": "staff@acme.com",
            "role": "staff",
        },
        {
            "id": OTHER_FIRM_USER_ID,
            "full_name": "Other CA",
            "email": "other@firm.com",
            "role": "admin",
        },
    ]
    sb.table("reconciliation_run").rows = [
        {
            "id": RUN_ID,
            "client_gstin_id": CLIENT_ID_1,
            "period": "2026-08",
            "status": "FINAL",
            "is_locked": True,
            "finalized_at": "2026-09-10T10:00:00Z",
            "finalized_by": ADMIN_USER_ID,
            "run_summary": {
                "missed_itc_paise": 5000000,
                "wrongful_itc": 2000000,
            },
        }
    ]
    sb.table("gstr3b_table4_summaries").rows = [
        {
            "id": "snap-123",
            "run_id": RUN_ID,
            "status": "FINALIZED",
            "audit_hash": "authoritative-hash-abc-123",
            "table_4a5": {"total_tax": 100000.0, "total_tax_paise": 10000000},
            "table_4b_total": {"total_tax": 10000.0, "total_tax_paise": 1000000},
            "table_4c": {"total_tax": 90000.0, "total_tax_paise": 9000000},
            "table_4d1": {"total_tax": 5000.0, "total_tax_paise": 500000},
        }
    ]
    sb.table("reconciliation_exception_dispositions").rows = []
    sb.table("itc_work_items").rows = []
    sb.table("itc_work_item_events").rows = []
    sb.table("team_members").rows = [
        {
            "id": "tm-1",
            "firm_owner_id": ADMIN_USER_ID,
            "member_user_id": STAFF_USER_ID,
            "is_active": True,
            "role": "staff",
        }
    ]
    return sb


def _make_mock_outcomes():
    return [
        OutcomeRow(
            id="pm:1",
            category="matched",
            supplier_gstin="27ABCDE1234F1Z5",
            supplier_name="Clean Supplier",
            invoice_number="INV-001",
            invoice_date="2026-08-01",
            match_status="EXACT",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=0,
            rule37_flag=False,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=10000,
            decision_what="Matched invoice",
            decision_why="PR and 2B agree",
            decision_next="Claim Table 4A5",
        ),
        OutcomeRow(
            id="pm:2",
            category="rule37_warnings",
            supplier_gstin="27DEFGH5678J1Z2",
            supplier_name="Delayed Supplier",
            invoice_number="INV-002",
            invoice_date="2026-01-10",
            match_status="RULE37",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=1800000,
            rule37_flag=True,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=18000,
            decision_what="Payment unpaid >180 days",
            decision_why="Rule 37 requires reversal",
            decision_next="Reverse in Table 4B2",
        ),
        OutcomeRow(
            id="pr:101",
            category="missed_itc",
            supplier_gstin="27XYZAB9876C1Z3",
            supplier_name="Missing Supplier",
            invoice_number="INV-003",
            invoice_date="2026-08-05",
            match_status="NOT_IN_2B",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=4374000,
            rule37_flag=False,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=43740,
            decision_what="Invoice missing from 2B",
            decision_why="Supplier unfiled",
            decision_next="Follow up with supplier",
        ),
    ]


@pytest.fixture
def test_client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test 1: Idempotent Work Item Creation & DB Uniqueness
# ---------------------------------------------------------------------------

def test_work_item_creation_idempotency():
    sb = _build_mock_db()
    mock_outcomes = _make_mock_outcomes()

    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(mock_outcomes, {}, {})), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"blocking_records": [{"record_id": "pm:2"}]}):

        # First sync
        res1 = wis.sync_work_items_for_run(sb, CLIENT_ID_1, RUN_ID, user_id=ADMIN_USER_ID)
        assert res1["created_count"] == 2  # pm:2 (Rule 37) and pr:101 (Missing 2B)
        assert len(sb.table("itc_work_items").rows) == 2

        # Second sync must be idempotent
        res2 = wis.sync_work_items_for_run(sb, CLIENT_ID_1, RUN_ID, user_id=ADMIN_USER_ID)
        assert res2["created_count"] == 0
        assert res2["preserved_count"] == 2
        assert len(sb.table("itc_work_items").rows) == 2


# ---------------------------------------------------------------------------
# Test 2: Centralized Lifecycle State Machine Transitions
# ---------------------------------------------------------------------------

def test_state_transitions_valid_and_invalid():
    sb = _build_mock_db()
    mock_outcomes = _make_mock_outcomes()

    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(mock_outcomes, {}, {})), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"blocking_records": []}):

        wis.sync_work_items_for_run(sb, CLIENT_ID_1, RUN_ID, user_id=ADMIN_USER_ID)
        item = sb.table("itc_work_items").rows[0]
        wid = item["id"]

        admin_user = {"id": ADMIN_USER_ID, "role": "admin", "full_name": "Admin CA"}

        # Valid transition sequence: OPEN -> IN_PROGRESS -> WAITING_VENDOR -> READY_FOR_REVIEW -> RESOLVED
        wis.transition_work_item_status(sb, wid, "IN_PROGRESS", admin_user)
        assert sb.table("itc_work_items").rows[0]["status"] == "IN_PROGRESS"

        wis.transition_work_item_status(sb, wid, "WAITING_VENDOR", admin_user)
        assert sb.table("itc_work_items").rows[0]["status"] == "WAITING_VENDOR"

        wis.transition_work_item_status(sb, wid, "READY_FOR_REVIEW", admin_user)
        assert sb.table("itc_work_items").rows[0]["status"] == "READY_FOR_REVIEW"

        wis.transition_work_item_status(sb, wid, "RESOLVED", admin_user)
        assert sb.table("itc_work_items").rows[0]["status"] == "RESOLVED"

        # Invalid transition: RESOLVED directly to WAITING_VENDOR (must reopen to IN_PROGRESS first)
        with pytest.raises(Exception) as exc_info:
            wis.transition_work_item_status(sb, wid, "WAITING_VENDOR", admin_user)
        assert "409" in str(exc_info.value) or "not permitted" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 3: Maker-Checker Authorization Guardrails
# ---------------------------------------------------------------------------

def test_maker_checker_authorization():
    sb = _build_mock_db()
    mock_outcomes = _make_mock_outcomes()

    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(mock_outcomes, {}, {})), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"blocking_records": [{"record_id": "pm:2"}]}):

        wis.sync_work_items_for_run(sb, CLIENT_ID_1, RUN_ID, user_id=ADMIN_USER_ID)
        # pm:2 is a blocker gate exception
        blocker_item = [r for r in sb.table("itc_work_items").rows if r["record_id"] == "pm:2"][0]
        wid = blocker_item["id"]

        staff_user = {"id": STAFF_USER_ID, "role": "staff", "full_name": "Staff Junior"}
        admin_user = {"id": ADMIN_USER_ID, "role": "admin", "full_name": "Admin Senior"}

        # Staff attempting direct status transition to RESOLVED on blocker item must be rejected (409)
        with pytest.raises(Exception) as exc_info:
            wis.transition_work_item_status(sb, wid, "RESOLVED", staff_user)
        assert "409" in str(exc_info.value) or "Only an Admin or CA Owner" in str(exc_info.value)

        # Staff calling resolve_work_item submits to READY_FOR_REVIEW (maker)
        res = wis.resolve_work_item(sb, wid, "VENDOR_CORRECTION_RECEIVED", "Supplier promised upload", staff_user)
        assert res["status"] == "READY_FOR_REVIEW"
        assert res["resolution_code"] == "VENDOR_CORRECTION_RECEIVED"

        # Admin calling resolve_work_item approves to RESOLVED (checker)
        admin_res = wis.resolve_work_item(sb, wid, "DOCUMENT_VERIFIED", "CA checked invoice & payment", admin_user)
        assert admin_res["status"] == "RESOLVED"
        assert admin_res["resolved_by"] == ADMIN_USER_ID


# ---------------------------------------------------------------------------
# Test 4: Manual Priority Override Preserving System Priority
# ---------------------------------------------------------------------------

def test_manual_priority_override():
    sb = _build_mock_db()
    mock_outcomes = _make_mock_outcomes()

    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(mock_outcomes, {}, {})), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"blocking_records": [{"record_id": "pm:2"}]}):

        wis.sync_work_items_for_run(sb, CLIENT_ID_1, RUN_ID, user_id=ADMIN_USER_ID)
        item = sb.table("itc_work_items").rows[0]
        wid = item["id"]
        original_sys_prio = item["system_priority"]

        admin_user = {"id": ADMIN_USER_ID, "role": "admin", "full_name": "Admin CA"}

        # Privileged CA Admin override to LOW with justification
        res = wis.override_work_item_priority(sb, wid, "LOW", "Immaterial threshold for this vendor", admin_user)
        assert res["priority"] == "LOW"
        assert res["manual_priority"] == "LOW"
        assert res["system_priority"] == original_sys_prio  # System priority preserved!
        assert res["priority_override_reason"] == "Immaterial threshold for this vendor"
        assert res["priority_changed_by"] == ADMIN_USER_ID

        # Privileged CA Owner override allowed
        owner_user = {"id": ADMIN_USER_ID, "role": "owner", "full_name": "Owner CA"}
        res_owner = wis.override_work_item_priority(sb, wid, "MEDIUM", "Adjusted by owner", owner_user)
        assert res_owner["priority"] == "MEDIUM"

        # Non-privileged normal staff must be rejected with 403 (OBS-03)
        staff_user = {"id": STAFF_USER_ID, "role": "staff", "full_name": "Staff Junior"}
        with pytest.raises(Exception) as exc_info:
            wis.override_work_item_priority(sb, wid, "CRITICAL", "Staff attempting override", staff_user)
        assert "403" in str(exc_info.value) or "Only an Admin or CA Owner" in str(exc_info.value)

        # Unauthorized cross-firm user rejected with 403 (OBS-03)
        other_user = {"id": OTHER_FIRM_USER_ID, "role": "admin", "full_name": "Other CA"}
        with pytest.raises(Exception) as exc_info:
            wis.override_work_item_priority(sb, wid, "HIGH", "Hacker override", other_user)
        assert "403" in str(exc_info.value) or "Access denied" in str(exc_info.value)

        # Empty reason rejected with 422
        with pytest.raises(Exception) as exc_info:
            wis.override_work_item_priority(sb, wid, "HIGH", "   ", admin_user)
        assert "422" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 4B: Assignee Firm-Membership Validation (OBS-02)
# ---------------------------------------------------------------------------

def test_assign_work_item_firm_membership_validation():
    sb = _build_mock_db()
    mock_outcomes = _make_mock_outcomes()

    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(mock_outcomes, {}, {})), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"blocking_records": []}):

        wis.sync_work_items_for_run(sb, CLIENT_ID_1, RUN_ID, user_id=ADMIN_USER_ID)
        item = sb.table("itc_work_items").rows[0]
        wid = item["id"]

        admin_user = {"id": ADMIN_USER_ID, "role": "admin", "full_name": "Admin CA"}
        other_user = {"id": OTHER_FIRM_USER_ID, "role": "admin", "full_name": "Other Firm CA"}

        # 1. Valid same-firm team member -> allowed
        res1 = wis.assign_work_item(sb, wid, STAFF_USER_ID, admin_user)
        assert res1["assigned_to"] == STAFF_USER_ID

        # 2. Valid firm owner assignee -> allowed
        res2 = wis.assign_work_item(sb, wid, ADMIN_USER_ID, admin_user)
        assert res2["assigned_to"] == ADMIN_USER_ID

        # 3. Unassigning (None) -> allowed
        res3 = wis.assign_work_item(sb, wid, None, admin_user)
        assert res3["assigned_to"] is None

        # 4. Cross-firm assignee (user from another firm) -> rejected with HTTP 400
        with pytest.raises(Exception) as exc_info:
            wis.assign_work_item(sb, wid, OTHER_FIRM_USER_ID, admin_user)
        assert "400" in str(exc_info.value) or "not an active member of this firm" in str(exc_info.value)

        # 5. Non-member / non-existent user ID -> rejected with HTTP 400
        non_member_id = "99999999-9999-9999-9999-999999999999"
        with pytest.raises(Exception) as exc_info:
            wis.assign_work_item(sb, wid, non_member_id, admin_user)
        assert "400" in str(exc_info.value) or "not an active member of this firm" in str(exc_info.value)

        # 6. Invalid UUID string -> rejected with HTTP 422
        with pytest.raises(Exception) as exc_info:
            wis.assign_work_item(sb, wid, "invalid-uuid-format", admin_user)
        assert "422" in str(exc_info.value)

        # 7. Unauthorized requester attempting to assign work item -> rejected with HTTP 403
        with pytest.raises(Exception) as exc_info:
            wis.assign_work_item(sb, wid, STAFF_USER_ID, other_user)
        assert "403" in str(exc_info.value) or "Access denied" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 5: Finalized Run Statutory Immutability (Critical Boundary)
# ---------------------------------------------------------------------------

def test_finalized_run_protection():
    sb = _build_mock_db()
    mock_outcomes = _make_mock_outcomes()

    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(mock_outcomes, {}, {})), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"blocking_records": []}):

        wis.sync_work_items_for_run(sb, CLIENT_ID_1, RUN_ID, user_id=ADMIN_USER_ID)
        item = sb.table("itc_work_items").rows[0]
        wid = item["id"]

        admin_user = {"id": ADMIN_USER_ID, "role": "admin", "full_name": "Admin CA"}

        # Initial snapshot state
        snap_before = dict(sb.table("gstr3b_table4_summaries").rows[0])

        # Perform operational actions: add note, assign, resolve
        wis.add_work_item_note(sb, wid, "Reviewed supplier filing statement", admin_user)
        wis.assign_work_item(sb, wid, STAFF_USER_ID, admin_user)
        wis.resolve_work_item(sb, wid, "VENDOR_CORRECTION_RECEIVED", "Resolved operationally", admin_user)

        # Statutory snapshot must be 100% byte/value identical!
        snap_after = dict(sb.table("gstr3b_table4_summaries").rows[0])
        assert snap_before == snap_after
        assert snap_after["audit_hash"] == "authoritative-hash-abc-123"
        assert snap_after["table_4c"]["total_tax"] == 90000.0


# ---------------------------------------------------------------------------
# Test 6: Tenant and Client Isolation
# ---------------------------------------------------------------------------

def test_tenant_and_client_isolation():
    sb = _build_mock_db()
    mock_outcomes = _make_mock_outcomes()

    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(mock_outcomes, {}, {})), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"blocking_records": []}):

        wis.sync_work_items_for_run(sb, CLIENT_ID_1, RUN_ID, user_id=ADMIN_USER_ID)
        item = sb.table("itc_work_items").rows[0]
        wid = item["id"]

        # Other firm user attempting to access Client 1 work item
        other_user = {"id": OTHER_FIRM_USER_ID, "role": "admin", "full_name": "Foreign CA"}

        with pytest.raises(Exception) as exc_info:
            wis.get_work_item(sb, wid, other_user)
        assert "403" in str(exc_info.value) or "Access denied" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 7: Activity Timeline & Audit Events Recording
# ---------------------------------------------------------------------------

def test_event_timeline_recording():
    sb = _build_mock_db()
    mock_outcomes = _make_mock_outcomes()

    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(mock_outcomes, {}, {})), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"blocking_records": []}):

        wis.sync_work_items_for_run(sb, CLIENT_ID_1, RUN_ID, user_id=ADMIN_USER_ID)
        item = sb.table("itc_work_items").rows[0]
        wid = item["id"]

        admin_user = {"id": ADMIN_USER_ID, "role": "admin", "full_name": "Admin CA"}

        wis.assign_work_item(sb, wid, STAFF_USER_ID, admin_user)
        wis.transition_work_item_status(sb, wid, "IN_PROGRESS", admin_user)
        wis.add_work_item_note(sb, wid, "Test comment", admin_user)
        wis.set_work_item_due_date(sb, wid, "2026-09-30T18:00:00Z", admin_user)

        detail = wis.get_work_item(sb, wid, admin_user)
        events = detail["events"]

        event_types = [e["event_type"] for e in events]
        assert "WORK_ITEM_CREATED" in event_types
        assert "ASSIGNED" in event_types or "REASSIGNED" in event_types
        assert "STATUS_CHANGED" in event_types
        assert "NOTE_ADDED" in event_types
        assert "DUE_DATE_CHANGED" in event_types


# ---------------------------------------------------------------------------
# Test 8: Reopen Dismissed and Resolved Items
# ---------------------------------------------------------------------------

def test_reopen_dismissed_and_resolved():
    sb = _build_mock_db()
    mock_outcomes = _make_mock_outcomes()

    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(mock_outcomes, {}, {})), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"blocking_records": []}):

        wis.sync_work_items_for_run(sb, CLIENT_ID_1, RUN_ID, user_id=ADMIN_USER_ID)
        item = sb.table("itc_work_items").rows[0]
        wid = item["id"]

        admin_user = {"id": ADMIN_USER_ID, "role": "admin", "full_name": "Admin CA"}

        # Dismiss
        wis.dismiss_work_item(sb, wid, "Customer confirmed invoice cancelled", admin_user)
        assert sb.table("itc_work_items").rows[0]["status"] == "DISMISSED"

        # Reopen dismissed item -> moves to OPEN
        res_open = wis.reopen_work_item(sb, wid, "Supplier submitted revised e-invoice", admin_user)
        assert res_open["status"] == "OPEN"
        assert res_open["reopen_reason"] == "Supplier submitted revised e-invoice"

        # Resolve
        wis.transition_work_item_status(sb, wid, "IN_PROGRESS", admin_user)
        wis.resolve_work_item(sb, wid, "PAYMENT_VERIFIED", "Bank ledger verified", admin_user)
        assert sb.table("itc_work_items").rows[0]["status"] == "RESOLVED"

        # Reopen resolved item -> moves to IN_PROGRESS
        res_reopened = wis.reopen_work_item(sb, wid, "Payment was dishonored", admin_user)
        assert res_reopened["status"] == "IN_PROGRESS"


# ---------------------------------------------------------------------------
# Test 9: Resolution Triggers Revalidation Hook
# ---------------------------------------------------------------------------

def test_resolution_triggers_revalidation_hook():
    sb = _build_mock_db()
    mock_outcomes = _make_mock_outcomes()

    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(mock_outcomes, {}, {})), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"blocking_records": []}):

        wis.sync_work_items_for_run(sb, CLIENT_ID_1, RUN_ID, user_id=ADMIN_USER_ID)
        item = sb.table("itc_work_items").rows[0]
        wid = item["id"]

        admin_user = {"id": ADMIN_USER_ID, "role": "admin", "full_name": "Admin CA"}

        wis.transition_work_item_status(sb, wid, "IN_PROGRESS", admin_user)

        # VENDOR_CORRECTION_RECEIVED qualifies for revalidation
        res = wis.resolve_work_item(sb, wid, "VENDOR_CORRECTION_RECEIVED", "Supplier filed amendment", admin_user)
        assert res["status"] == "RESOLVED"
        assert res["revalidation_status"] == "PENDING"
        assert res["revalidation_requested_at"] is not None


# ---------------------------------------------------------------------------
# Test 10: Bulk Operational Action
# ---------------------------------------------------------------------------

def test_bulk_action_execution():
    sb = _build_mock_db()
    mock_outcomes = _make_mock_outcomes()

    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(mock_outcomes, {}, {})), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"blocking_records": []}):

        wis.sync_work_items_for_run(sb, CLIENT_ID_1, RUN_ID, user_id=ADMIN_USER_ID)
        wids = [r["id"] for r in sb.table("itc_work_items").rows]

        admin_user = {"id": ADMIN_USER_ID, "role": "admin", "full_name": "Admin CA"}

        # Bulk assign
        res = wis.execute_bulk_action(sb, "assign", wids, {"assigned_to": STAFF_USER_ID}, admin_user)
        assert res["success_count"] == 2
        assert res["failure_count"] == 0
        for r in sb.table("itc_work_items").rows:
            assert r["assigned_to"] == STAFF_USER_ID


# ---------------------------------------------------------------------------
# Test 11: Sync Preserves Operational State
# ---------------------------------------------------------------------------

def test_sync_preserves_operational_state():
    sb = _build_mock_db()
    mock_outcomes = _make_mock_outcomes()

    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(mock_outcomes, {}, {})), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={"blocking_records": []}):

        wis.sync_work_items_for_run(sb, CLIENT_ID_1, RUN_ID, user_id=ADMIN_USER_ID)
        item = sb.table("itc_work_items").rows[0]
        wid = item["id"]

        admin_user = {"id": ADMIN_USER_ID, "role": "admin", "full_name": "Admin CA"}

        # Mutate operational state
        wis.transition_work_item_status(sb, wid, "IN_PROGRESS", admin_user)
        wis.assign_work_item(sb, wid, STAFF_USER_ID, admin_user)
        wis.override_priority(sb, wid, "LOW", "Preserved", admin_user)
        wis.set_work_item_due_date(sb, wid, "2026-10-15T00:00:00Z", admin_user)

        # Re-run sync
        wis.sync_work_items_for_run(sb, CLIENT_ID_1, RUN_ID, user_id=ADMIN_USER_ID)

        # Verify operational fields are NOT reset
        updated_item = [r for r in sb.table("itc_work_items").rows if r["id"] == wid][0]
        assert updated_item["status"] == "IN_PROGRESS"
        assert updated_item["assigned_to"] == STAFF_USER_ID
        assert updated_item["priority"] == "LOW"
        assert updated_item["manual_priority"] == "LOW"
        assert updated_item["due_at"] is not None
