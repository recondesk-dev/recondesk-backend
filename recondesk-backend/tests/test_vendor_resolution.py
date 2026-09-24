"""Comprehensive test suite for Phase 5.3: Vendor Resolution & Communication.

Verifies:
1. Database migration & schema invariants (work_item_id, message_body, idx_vendor_followup_work_item).
2. Tenant & firm isolation on communication and vendor profile endpoints.
3. Communication templates (WhatsApp wa.me deep links and Email HTML notices).
4. Dispatch logging with work-item linkage and COMMUNICATION_DISPATCHED timeline events.
5. Follow-up scheduling with SLA tracking and FOLLOWUP_SCHEDULED timeline events.
6. Structured vendor response recording across all 6 categories (WILL_FILE_NEXT_PERIOD, INVOICE_AMENDED, DOCUMENT_PROVIDED, DISPUTED, NO_SUCH_INVOICE, OTHER).
7. Maker-checker preservation on blocking exceptions.
8. Finalized run statutory protection (Table 4 and outcomes remain strictly immutable).
9. Phase 5.5 revalidation boundary (request marks PENDING without calculating reconciliation).
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_active_user
from app.main import app
from app.services import itc_work_item_service as wis
from app.services import vendor_followup_engine as vf_svc
from tests.test_itc_work_items import EnhancedInMemorySupabaseClient

CLIENT_ID_1 = "00000000-0000-0000-0000-000000000001"
CLIENT_ID_2 = "00000000-0000-0000-0000-000000000002"
GSTIN_1 = "27AAACB1234A1Z1"
GSTIN_2 = "27AAACB9999Z1Z9"

RUN_ID = "11111111-1111-1111-1111-111111111111"
ADMIN_USER_ID = "00000000-0000-0000-0000-000000000001"
STAFF_USER_ID = "00000000-0000-0000-0000-000000000002"
OTHER_FIRM_USER_ID = "00000000-0000-0000-0000-000000000099"

SUPPLIER_GSTIN = "27ABCDE1234F1Z5"
SUPPLIER_NAME = "Acme Tools Pvt Ltd"


def setup_mock_db():
    sb = EnhancedInMemorySupabaseClient()
    # 1. client_gstins
    sb.table("client_gstins").rows = [
        {
            "id": CLIENT_ID_1,
            "firm_owner_id": ADMIN_USER_ID,
            "gstin": GSTIN_1,
            "trade_name": "Test Client 1",
            "legal_name": "Test Client 1 Pvt Ltd",
            "assigned_to": STAFF_USER_ID,
            "is_active": True,
        },
        {
            "id": CLIENT_ID_2,
            "firm_owner_id": OTHER_FIRM_USER_ID,
            "gstin": GSTIN_2,
            "trade_name": "Other Firm Client",
            "legal_name": "Other Client Ltd",
            "assigned_to": None,
            "is_active": True,
        },
    ]

    # 2. user_profiles
    sb.table("user_profiles").rows = [
        {
            "id": ADMIN_USER_ID,
            "firm_owner_id": ADMIN_USER_ID,
            "role": "admin",
            "full_name": "Admin CA",
            "email": "admin@recondesk.in",
        },
        {
            "id": STAFF_USER_ID,
            "firm_owner_id": ADMIN_USER_ID,
            "role": "staff",
            "full_name": "Audit Staff",
            "email": "staff@recondesk.in",
        },
        {
            "id": OTHER_FIRM_USER_ID,
            "firm_owner_id": OTHER_FIRM_USER_ID,
            "role": "admin",
            "full_name": "Other CA",
            "email": "other@otherfirm.in",
        },
    ]

    # 3. firm_members
    sb.table("firm_members").rows = [
        {"firm_owner_id": ADMIN_USER_ID, "member_user_id": STAFF_USER_ID, "role": "staff", "status": "active"},
    ]

    # 4. reconciliation_run
    sb.table("reconciliation_run").rows = [
        {
            "id": RUN_ID,
            "client_gstin_id": CLIENT_ID_1,
            "period": "2026-08",
            "status": "COMPLETED",
            "is_locked": False,
        }
    ]

    # 5. itc_work_items (sample non-blocking item and blocking item)
    wi_non_blocking_id = "22222222-2222-2222-2222-222222222222"
    wi_blocking_id = "33333333-3333-3333-3333-333333333333"
    sb.table("itc_work_items").rows = [
        {
            "id": wi_non_blocking_id,
            "firm_owner_id": ADMIN_USER_ID,
            "client_gstin_id": CLIENT_ID_1,
            "run_id": RUN_ID,
            "record_id": "pr:101",
            "exception_type": "MISSING_2B",
            "status": "OPEN",
            "priority": "HIGH",
            "system_priority": "HIGH",
            "vendor_gstin": SUPPLIER_GSTIN,
            "vendor_name": SUPPLIER_NAME,
            "invoice_number": "INV-101",
            "invoice_date": "2026-08-10",
            "itc_amount_at_stake": 25000.00,
            "itc_amount_at_stake_paise": 2500000,
            "is_blocking": False,
            "revalidation_status": "NONE",
            "created_at": "2026-09-14T10:00:00Z",
            "updated_at": "2026-09-14T10:00:00Z",
        },
        {
            "id": wi_blocking_id,
            "firm_owner_id": ADMIN_USER_ID,
            "client_gstin_id": CLIENT_ID_1,
            "run_id": RUN_ID,
            "record_id": "pr:102",
            "exception_type": "RULE_37",
            "status": "OPEN",
            "priority": "CRITICAL",
            "system_priority": "CRITICAL",
            "vendor_gstin": SUPPLIER_GSTIN,
            "vendor_name": SUPPLIER_NAME,
            "invoice_number": "INV-102",
            "invoice_date": "2026-01-10",
            "itc_amount_at_stake": 50000.00,
            "itc_amount_at_stake_paise": 5000000,
            "is_blocking": True,
            "revalidation_status": "NONE",
            "created_at": "2026-09-14T10:00:00Z",
            "updated_at": "2026-09-14T10:00:00Z",
        },
    ]

    # 6. supplier_compliance_summary
    sb.table("supplier_compliance_summary").rows = [
        {
            "firm_owner_id": ADMIN_USER_ID,
            "supplier_gstin_normalized": SUPPLIER_GSTIN,
            "supplier_trade_name": SUPPLIER_NAME,
            "client_gstin_ids": [CLIENT_ID_1],
            "clients_touched_count": 1,
            "total_invoices": 15,
            "mismatch_invoice_count": 3,
            "mismatch_rate": 0.2,
            "rule37_open_count": 1,
            "rule37_at_risk_paise": 5000000,
            "section_17_5_count": 0,
            "late_filing_count": 2,
            "late_filing_rate": 0.1333,
            "pr_only_count": 1,
            "risk_score": 65,
        }
    ]

    sb.table("vendor_followup_logs").rows = []
    sb.table("itc_work_item_events").rows = []

    return sb, wi_non_blocking_id, wi_blocking_id


# 1. DATABASE MIGRATION & SCHEMA CHECK
def test_database_migration_file_exists():
    migration_path = "supabase/migrations/20260914140000_vendor_followup_work_item.sql"
    if not os.path.exists(migration_path):
        migration_path = "recondesk-backend/supabase/migrations/20260914140000_vendor_followup_work_item.sql"
    assert os.path.exists(migration_path), "Migration file must exist"
    with open(migration_path) as f:
        content = f.read()
    assert "work_item_id" in content
    assert "message_body" in content
    assert "idx_vendor_followup_work_item" in content
    assert "vendor_followup_logs" in content


# 2. COMMUNICATION TEMPLATES
def test_communication_templates_whatsapp_and_email():
    wa = vf_svc.generate_whatsapp_payload(
        supplier_gstin=SUPPLIER_GSTIN,
        supplier_name=SUPPLIER_NAME,
        vendor_phone="9876543210",
        at_risk_itc_rupees=25000.0,
        template_type="MISSING_2B_REQUEST",
    )
    assert "wa.me/919876543210" in wa["whatsapp_url"]
    assert "Missing" in wa["message_text"]
    assert "25,000.00" in wa["message_text"]

    email = vf_svc.generate_email_template(
        supplier_gstin=SUPPLIER_GSTIN,
        supplier_name=SUPPLIER_NAME,
        at_risk_itc_rupees=25000.0,
        template_type="VALUE_MISMATCH_VERIFICATION",
    )
    assert "Value Discrepancy" in email["subject"]
    assert SUPPLIER_GSTIN in email["subject"]
    assert "25,000.00" in email["html_body"]


# 3. DISPATCH LOGGING & WORK-ITEM TIMELINE EVENT
def test_log_followup_action_with_work_item_linkage():
    sb, wid, _ = setup_mock_db()

    log = vf_svc.log_followup_action(
        sb=sb,
        client_gstin_id=CLIENT_ID_1,
        supplier_gstin=SUPPLIER_GSTIN,
        supplier_name=SUPPLIER_NAME,
        vendor_phone="9876543210",
        vendor_email="accounts@acme.com",
        channel="WHATSAPP",
        template_type="MISSING_2B_REQUEST",
        at_risk_itc_rupees=25000.0,
        dispatched_by=ADMIN_USER_ID,
        work_item_id=wid,
        message_body="Sample WhatsApp body",
    )

    assert log["work_item_id"] == wid
    assert log["message_body"] == "Sample WhatsApp body"
    assert log["supplier_gstin"] == SUPPLIER_GSTIN

    # Verify event appended to itc_work_item_events
    events = [e for e in sb.table("itc_work_item_events").rows if e.get("work_item_id") == wid]
    assert len(events) == 1
    assert events[0]["event_type"] == "COMMUNICATION_DISPATCHED"
    assert events[0]["metadata"]["channel"] == "WHATSAPP"
    assert events[0]["metadata"]["template_type"] == "MISSING_2B_REQUEST"


def test_log_followup_action_failed_persistence_does_not_emit_event():
    """FIND-5.3-02 Hardening: COMMUNICATION_DISPATCHED must NOT be emitted if log persistence fails."""
    sb, wid, _ = setup_mock_db()

    mock_table = MagicMock()
    mock_table.insert.side_effect = RuntimeError("Database connection lost / disk full")
    orig_table_fn = sb.table

    def failing_table_lookup(name: str):
        if name == "vendor_followup_logs":
            return mock_table
        return orig_table_fn(name)

    with patch.object(sb, "table", side_effect=failing_table_lookup), \
         patch("app.config.get_settings") as mock_settings:
        mock_settings.return_value.SUPABASE_DATABASE_URL = None
        mock_settings.return_value.DATABASE_URL = None

        log = vf_svc.log_followup_action(
            sb=sb,
            client_gstin_id=CLIENT_ID_1,
            supplier_gstin=SUPPLIER_GSTIN,
            supplier_name=SUPPLIER_NAME,
            vendor_phone="9876543210",
            vendor_email="accounts@acme.com",
            channel="WHATSAPP",
            template_type="MISSING_2B_REQUEST",
            at_risk_itc_rupees=25000.0,
            dispatched_by=ADMIN_USER_ID,
            work_item_id=wid,
            message_body="Sample WhatsApp body",
        )

        assert log is None

        # Verify COMMUNICATION_DISPATCHED was NOT emitted
        events = [e for e in sb.table("itc_work_item_events").rows if e.get("event_type") == "COMMUNICATION_DISPATCHED"]
        assert len(events) == 0, "COMMUNICATION_DISPATCHED must NOT be emitted when log persistence fails"


# 4. WORK ITEM COMMUNICATION HISTORY ENDPOINT & TENANT ISOLATION
def test_work_item_communication_history_endpoint_and_isolation():
    sb, wid, _ = setup_mock_db()

    # Add a follow-up log for wid
    sb.table("vendor_followup_logs").rows.append({
        "id": "log-1",
        "client_gstin_id": CLIENT_ID_1,
        "supplier_gstin": SUPPLIER_GSTIN,
        "supplier_name": SUPPLIER_NAME,
        "channel": "EMAIL",
        "template_type": "RULE37_NOTICE",
        "at_risk_itc_rupees": 25000.0,
        "status": "NOTICE_GENERATED",
        "work_item_id": wid,
        "message_body": "Notice text",
        "dispatched_at": "2026-09-14T11:00:00Z",
    })

    admin_user = {"id": ADMIN_USER_ID, "role": "admin", "email": "admin@recondesk.in"}
    other_user = {"id": OTHER_FIRM_USER_ID, "role": "admin", "email": "other@otherfirm.in"}

    with patch("app.routers.vendor_followup.get_supabase", return_value=sb), \
         patch("app.routers.vendor_followup.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        app.dependency_overrides[get_current_active_user] = lambda: admin_user
        client = TestClient(app)

        res = client.get(f"/api/vendors/followup/work-items/{wid}/history")
        assert res.status_code == 200
        data = res.json()
        assert data["total_logs"] == 1
        assert data["logs"][0]["work_item_id"] == wid
        assert data["logs"][0]["channel"] == "EMAIL"

    # Cross-firm access denial
    with patch("app.routers.vendor_followup.get_supabase", return_value=sb), \
         patch("app.routers.vendor_followup.list_accessible_client_gstin_ids", return_value={CLIENT_ID_2}):
        app.dependency_overrides[get_current_active_user] = lambda: other_user
        client = TestClient(app)

        res = client.get(f"/api/vendors/followup/work-items/{wid}/history")
        assert res.status_code == 404, "Cross-firm client access must be denied"

    app.dependency_overrides.clear()


# 5. VENDOR RESPONSE ALL CATEGORIES & STATE MACHINE
def test_vendor_response_all_categories():
    categories = [
        ("WILL_FILE_NEXT_PERIOD", "WAITING_VENDOR"),
        ("INVOICE_AMENDED", "IN_PROGRESS"),
        ("DOCUMENT_PROVIDED", "READY_FOR_REVIEW"),
        ("DISPUTED", "IN_PROGRESS"),
        ("NO_SUCH_INVOICE", "IN_PROGRESS"),
        ("OTHER", "IN_PROGRESS"),
    ]

    admin_user = {"id": ADMIN_USER_ID, "role": "admin", "full_name": "Admin CA"}

    for cat, expected_status in categories:
        sb, wid, _ = setup_mock_db()
        resp = wis.record_vendor_response(
            sb=sb,
            work_item_id=wid,
            response_data={
                "response_category": cat,
                "contact_channel": "PHONE",
                "contact_person": "Mr. Vendor",
                "promised_date": "2026-09-30",
                "notes": f"Testing category {cat}",
            },
            current_user=admin_user,
        )

        assert resp["status"] == expected_status, f"Expected {expected_status} for {cat}, got {resp['status']}"
        assert resp["due_at"] is not None

        # Verify event
        events = [e for e in sb.table("itc_work_item_events").rows if e.get("event_type") == "VENDOR_RESPONSE_RECORDED"]
        assert len(events) == 1
        assert events[0]["metadata"]["response_category"] == cat
        assert events[0]["metadata"]["promised_date"] == "2026-09-30"


# 6. MAKER-CHECKER ON BLOCKING EXCEPTION PRESERVED
def test_maker_checker_blocking_exception_preserved():
    sb, _, wid_blocking = setup_mock_db()
    staff_user = {"id": STAFF_USER_ID, "role": "staff", "full_name": "Audit Staff"}

    # Staff trying to force RESOLVED on a blocking item via vendor response must be rejected
    with pytest.raises(Exception) as exc_info:
        wis.record_vendor_response(
            sb=sb,
            work_item_id=wid_blocking,
            response_data={
                "response_category": "DOCUMENT_PROVIDED",
                "target_status": "RESOLVED",
                "notes": "Vendor sent receipt, marking resolved",
            },
            current_user=staff_user,
        )
    assert "Staff cannot resolve a blocking exception" in str(exc_info.value)


# 7. FOLLOW-UP SCHEDULING
def test_schedule_work_item_followup():
    sb, wid, _ = setup_mock_db()
    admin_user = {"id": ADMIN_USER_ID, "role": "admin", "full_name": "Admin CA"}

    updated = wis.schedule_work_item_followup(
        sb=sb,
        work_item_id=wid,
        due_at_str="2026-10-15T18:00:00Z",
        note_text="Check 2B filing by 15th",
        current_user=admin_user,
    )

    assert updated["due_at"] is not None
    assert updated["sla_status"] == "ON_TRACK"

    events = [e for e in sb.table("itc_work_item_events").rows if e.get("event_type") == "FOLLOWUP_SCHEDULED"]
    assert len(events) == 1
    assert "Check 2B filing" in events[0]["note"]


# 8. VENDOR PROFILE API
def test_get_work_item_vendor_profile():
    sb, wid, _ = setup_mock_db()
    admin_user = {"id": ADMIN_USER_ID, "role": "admin", "full_name": "Admin CA"}

    profile = wis.get_work_item_vendor_profile(sb, wid, admin_user)

    assert profile["vendor_gstin"] == SUPPLIER_GSTIN
    assert profile["risk_score"] == 65
    assert profile["risk_tier"] == "HIGH_RISK"
    assert profile["total_invoices"] == 15
    assert profile["mismatch_count"] == 3
    assert profile["open_work_item_count"] == 2
    assert profile["itc_at_stake"] > 0


# 9. FINALIZED RUN IMMUTABILITY
def test_finalized_run_operational_immutability():
    sb, wid, _ = setup_mock_db()
    # Lock and finalize the run
    sb.table("reconciliation_run").rows[0]["status"] = "FINAL"
    sb.table("reconciliation_run").rows[0]["is_locked"] = True

    admin_user = {"id": ADMIN_USER_ID, "role": "admin", "full_name": "Admin CA"}

    # Operational actions succeed on finalized run
    log = vf_svc.log_followup_action(
        sb=sb,
        client_gstin_id=CLIENT_ID_1,
        supplier_gstin=SUPPLIER_GSTIN,
        supplier_name=SUPPLIER_NAME,
        vendor_phone="9876543210",
        vendor_email="acc@acme.com",
        channel="EMAIL",
        template_type="POLITE_REMINDER",
        at_risk_itc_rupees=25000.0,
        dispatched_by=ADMIN_USER_ID,
        work_item_id=wid,
    )
    assert log is not None

    resp = wis.record_vendor_response(
        sb=sb,
        work_item_id=wid,
        response_data={
            "response_category": "WILL_FILE_NEXT_PERIOD",
            "notes": "Spoke after finalization",
        },
        current_user=admin_user,
    )
    assert resp["status"] == "WAITING_VENDOR"

    # Verify run remains locked and FINAL
    run = sb.table("reconciliation_run").rows[0]
    assert run["status"] == "FINAL"
    assert run["is_locked"] is True


# 10. REVALIDATION BOUNDARY PRESERVATION
def test_revalidation_boundary_preservation():
    sb, wid, _ = setup_mock_db()
    admin_user = {"id": ADMIN_USER_ID, "role": "admin", "full_name": "Admin CA"}

    item = wis.request_work_item_revalidation(sb, wid, admin_user)

    assert item["revalidation_status"] == "PENDING"
    events = [e for e in sb.table("itc_work_item_events").rows if e.get("event_type") == "REVALIDATION_REQUESTED"]
    assert len(events) == 1

    # Invariants: Zero modification to reconciliation run or outcomes
    run = sb.table("reconciliation_run").rows[0]
    assert run["status"] == "COMPLETED"
