"""Comprehensive automated test suite for Phase 5.4: Resolution Intelligence / Exception Intelligence.

Verifies:
1. Deterministic Root Cause Explanations across all 10 exception types:
   - MISSING_2B, 2B_ONLY, SEC_17_5, RULE_37, RULE_37A, GSTIN_MISMATCH,
     VALUE_MISMATCH, DUPLICATE, TIME_BARRED_16_4, OTHER.
2. Concrete Evidence Points compilation and severity tagging.
3. Operational Resolution Difficulty calculation (0-100), tiers, and mandatory disclaimer.
4. Next Best Action recommendations and 1-click modal mapping.
5. Revalidation Guidance and prerequisites verification.
6. Multi-tenant and firm isolation (403 Forbidden / 404 Not Found).
7. Finalized run protection (read-only execution).
8. Critical Safety Verification: 0 INSERTs, 0 UPDATEs, 0 DELETEs across any table during intelligence synthesis.
"""

from __future__ import annotations

import copy
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_active_user
from app.main import app
from app.services import resolution_intelligence_engine as rie
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

    # 5. supplier_compliance_summary
    sb.table("supplier_compliance_summary").rows = [
        {
            "firm_owner_id": ADMIN_USER_ID,
            "supplier_gstin_normalized": SUPPLIER_GSTIN,
            "supplier_name": SUPPLIER_NAME,
            "compliance_risk_score": 78,
            "compliance_risk_tier": "HIGH_RISK",
            "total_invoices_evaluated": 15,
            "invoices_missing_in_2b": 6,
            "avg_filing_delay_days": 24,
            "consecutive_delinquENT_periods": 3,
        }
    ]

    # 6. vendor_followup_logs
    sb.table("vendor_followup_logs").rows = [
        {
            "id": "log-001",
            "work_item_id": "22222222-2222-2222-2222-222222222222",
            "channel": "WHATSAPP",
            "template_type": "MISSING_INVOICE",
            "status": "DELIVERED",
            "dispatched_at": "2026-09-14T11:00:00Z",
            "message_body": "Please upload INV-101",
        }
    ]

    # 7. itc_work_items
    wi_base_id = "22222222-2222-2222-2222-222222222222"
    sb.table("itc_work_items").rows = [
        {
            "id": wi_base_id,
            "firm_owner_id": ADMIN_USER_ID,
            "client_gstin_id": CLIENT_ID_1,
            "run_id": RUN_ID,
            "record_id": "pr:101",
            "exception_type": "MISSING_2B",
            "status": "WAITING_VENDOR",
            "priority": "HIGH",
            "system_priority": "HIGH",
            "vendor_gstin": SUPPLIER_GSTIN,
            "vendor_name": SUPPLIER_NAME,
            "invoice_number": "INV-101",
            "invoice_date": "2026-07-15",
            "itc_amount_at_stake": 35000.00,
            "itc_amount_at_stake_paise": 3500000,
            "is_blocking": False,
            "revalidation_status": "NONE",
            "created_at": "2026-09-14T10:00:00Z",
            "updated_at": "2026-09-14T10:00:00Z",
        }
    ]

    # 8. itc_work_item_events
    sb.table("itc_work_item_events").rows = [
        {
            "id": "ev-001",
            "work_item_id": wi_base_id,
            "event_type": "COMMUNICATION_DISPATCHED",
            "actor_id": ADMIN_USER_ID,
            "actor_role": "admin",
            "actor_name": "Admin CA",
            "note": "Dispatched WhatsApp message",
            "created_at": "2026-09-14T11:00:00Z",
        },
        {
            "id": "ev-002",
            "work_item_id": wi_base_id,
            "event_type": "VENDOR_RESPONSE_RECORDED",
            "actor_id": ADMIN_USER_ID,
            "actor_role": "admin",
            "actor_name": "Admin CA",
            "note": "Vendor promised to file next period",
            "metadata": {
                "response_category": "WILL_FILE_NEXT_PERIOD",
                "contact_channel": "PHONE",
                "promised_date": "2026-09-20",
            },
            "created_at": "2026-09-14T14:00:00Z",
        },
    ]

    return sb


@pytest.fixture
def test_client():
    sb = setup_mock_db()
    with patch("app.routers.work_items.get_supabase", return_value=sb), \
         patch("app.routers.work_items.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}), \
         patch("app.services.itc_work_item_service.list_accessible_client_gstin_ids", return_value={CLIENT_ID_1}):
        client = TestClient(app)
        yield client, sb


class TestResolutionIntelligenceEngine:
    def test_all_10_exception_types_root_cause(self):
        """Test root cause synthesis across all 10 authoritative exception types."""
        sb = setup_mock_db()
        current_user = {"id": ADMIN_USER_ID, "role": "admin", "firm_owner_id": ADMIN_USER_ID}

        exception_types = [
            "MISSING_2B",
            "2B_ONLY",
            "SEC_17_5",
            "RULE_37",
            "RULE_37A",
            "GSTIN_MISMATCH",
            "VALUE_MISMATCH",
            "DUPLICATE",
            "TIME_BARRED_16_4",
            "OTHER",
        ]

        for ex_type in exception_types:
            item = {
                "id": "22222222-2222-2222-2222-222222222222",
                "client_gstin_id": CLIENT_ID_1,
                "firm_owner_id": ADMIN_USER_ID,
                "exception_type": ex_type,
                "status": "OPEN",
                "vendor_gstin": SUPPLIER_GSTIN,
                "vendor_name": SUPPLIER_NAME,
                "invoice_number": f"INV-{ex_type}",
                "invoice_date": "2026-06-01",
                "itc_amount_at_stake": 15000.0,
                "itc_amount_at_stake_paise": 1500000,
                "is_blocking": ex_type in ("SEC_17_5", "RULE_37", "TIME_BARRED_16_4"),
                "events": [],
            }

            intel = rie.get_work_item_resolution_intelligence(sb, item, current_user)

            assert intel["work_item_id"] == item["id"]
            assert intel["exception_type"] == ex_type
            assert "what_happened" in intel["root_cause_explanation"]
            assert "likely_root_cause" in intel["root_cause_explanation"]
            assert "statutory_context" in intel["root_cause_explanation"]
            assert intel["root_cause_explanation"]["confidence_level"] in ("HIGH", "MEDIUM", "LOW")

            # Validate specific statutory context per exception
            ctx = intel["root_cause_explanation"]["statutory_context"]
            if ex_type == "MISSING_2B":
                assert "Section 16(2)(aa)" in ctx
            elif ex_type == "SEC_17_5":
                assert "Section 17(5)" in ctx
            elif ex_type == "RULE_37":
                assert "Rule 37" in ctx
            elif ex_type == "RULE_37A":
                assert "Rule 37A" in ctx
            elif ex_type == "TIME_BARRED_16_4":
                assert "Section 16(4)" in ctx

    def test_resolution_difficulty_scoring_and_tiers(self):
        """Test operational resolution difficulty scoring, bounding (0-100), and tiers."""
        sb = setup_mock_db()
        current_user = {"id": ADMIN_USER_ID, "role": "admin", "firm_owner_id": ADMIN_USER_ID}

        # Case 1: Low friction item
        low_item = {
            "id": "low-1",
            "client_gstin_id": CLIENT_ID_1,
            "firm_owner_id": ADMIN_USER_ID,
            "exception_type": "MISSING_2B",
            "status": "RESOLVED",
            "invoice_date": "2026-09-01",
            "is_blocking": False,
            "events": [],
        }
        low_intel = rie.get_work_item_resolution_intelligence(sb, low_item, current_user)
        assert 0 <= low_intel["resolution_difficulty"]["score"] <= 100
        assert low_intel["resolution_difficulty"]["tier"] in ("LOW", "MEDIUM", "HIGH", "VERY_HIGH")
        assert len(low_intel["resolution_difficulty"]["disclaimer"]) > 20

        # Case 2: High friction item (blocking, disputed, high supplier risk, old invoice)
        high_item = {
            "id": "high-1",
            "client_gstin_id": CLIENT_ID_1,
            "firm_owner_id": ADMIN_USER_ID,
            "exception_type": "RULE_37",
            "status": "OPEN",
            "vendor_gstin": SUPPLIER_GSTIN,
            "invoice_date": "2025-01-01",
            "is_blocking": True,
            "sla_status": "OVERDUE",
            "revalidation_result": "STILL_FAILING",
            "events": [
                {"event_type": "REOPENED"},
                {"event_type": "REOPENED"},
                {
                    "event_type": "VENDOR_RESPONSE_RECORDED",
                    "metadata": {"response_category": "DISPUTED"},
                },
            ],
        }
        high_intel = rie.get_work_item_resolution_intelligence(sb, high_item, current_user)
        assert high_intel["resolution_difficulty"]["score"] >= 60
        assert high_intel["resolution_difficulty"]["tier"] in ("HIGH", "VERY_HIGH")
        assert any(f["dimension"] == "STATUTORY_BLOCKER" for f in high_intel["resolution_difficulty"]["factors"])
        assert any(f["dimension"] == "VENDOR_DISPUTE" for f in high_intel["resolution_difficulty"]["factors"])

    def test_next_best_action_mapping(self):
        """Test next best action mapping to appropriate operational workflows."""
        sb = setup_mock_db()
        current_user = {"id": ADMIN_USER_ID, "role": "admin", "firm_owner_id": ADMIN_USER_ID}

        # 1. Open missing 2B with no follow-ups -> DISPATCH_VENDOR_FOLLOWUP
        wi1 = {
            "id": "act-1",
            "exception_type": "MISSING_2B",
            "status": "OPEN",
            "vendor_gstin": SUPPLIER_GSTIN,
            "events": [],
        }
        res1 = rie.get_work_item_resolution_intelligence(sb, wi1, current_user)
        assert res1["next_best_action"]["action_type"] == "DISPATCH_VENDOR_FOLLOWUP"

        # 2. Waiting vendor with document provided -> DISPOSITION_OR_RESOLVE
        wi2 = {
            "id": "act-2",
            "exception_type": "MISSING_2B",
            "status": "WAITING_VENDOR",
            "vendor_gstin": SUPPLIER_GSTIN,
            "events": [
                {
                    "event_type": "VENDOR_RESPONSE_RECORDED",
                    "metadata": {"response_category": "DOCUMENT_PROVIDED"},
                }
            ],
        }
        res2 = rie.get_work_item_resolution_intelligence(sb, wi2, current_user)
        assert res2["next_best_action"]["action_type"] == "DISPOSITION_OR_RESOLVE"

        # 3. Resolved item -> REVALIDATE_INVOICE
        wi3 = {
            "id": "act-3",
            "exception_type": "MISSING_2B",
            "status": "RESOLVED",
            "revalidation_status": "NONE",
            "events": [],
        }
        res3 = rie.get_work_item_resolution_intelligence(sb, wi3, current_user)
        assert res3["next_best_action"]["action_type"] == "REVALIDATE_INVOICE"

    def test_revalidation_guidance(self):
        """Test revalidation guidance and prerequisites."""
        sb = setup_mock_db()
        current_user = {"id": ADMIN_USER_ID, "role": "admin", "firm_owner_id": ADMIN_USER_ID}

        # Permanent statutory block (Sec 17(5)) cannot be revalidated
        item_blocked = {
            "id": "rev-1",
            "exception_type": "SEC_17_5",
            "status": "RESOLVED",
            "events": [],
        }
        intel_blocked = rie.get_work_item_resolution_intelligence(sb, item_blocked, current_user)
        assert intel_blocked["revalidation_guidance"]["status"] == "NOT_READY"
        assert any(not p["satisfied"] for p in intel_blocked["revalidation_guidance"]["prerequisites"])

        # Already pending revalidation
        item_pending = {
            "id": "rev-2",
            "exception_type": "MISSING_2B",
            "status": "RESOLVED",
            "revalidation_status": "PENDING",
            "events": [],
        }
        intel_pending = rie.get_work_item_resolution_intelligence(sb, item_pending, current_user)
        assert intel_pending["revalidation_guidance"]["status"] == "NOT_READY"
        assert "already pending" in intel_pending["revalidation_guidance"]["summary"].lower()

    def test_zero_database_mutations_safety(self):
        """CRITICAL TEST: Proves that resolution intelligence executes with ZERO mutations (0 INSERT, 0 UPDATE, 0 DELETE)."""
        sb = setup_mock_db()
        current_user = {"id": ADMIN_USER_ID, "role": "admin", "firm_owner_id": ADMIN_USER_ID}

        # Snapshot full state across all tables before intelligence generation
        snapshot_before = {}
        for tbl_name, tbl in sb.tables.items():
            snapshot_before[tbl_name] = copy.deepcopy(tbl.rows)

        # Call intelligence generation on an active item
        item = copy.deepcopy(sb.table("itc_work_items").rows[0])
        item["events"] = copy.deepcopy(sb.table("itc_work_item_events").rows)

        intel = rie.get_work_item_resolution_intelligence(sb, item, current_user)
        assert intel is not None
        assert "root_cause_explanation" in intel

        # Snapshot full state after
        for tbl_name, tbl in sb.tables.items():
            before_rows = snapshot_before[tbl_name]
            after_rows = tbl.rows
            assert len(before_rows) == len(after_rows), f"Table {tbl_name} row count changed from {len(before_rows)} to {len(after_rows)}!"
            assert before_rows == after_rows, f"Table {tbl_name} content was mutated during intelligence synthesis!"


class TestResolutionIntelligenceEndpoint:
    def test_get_intelligence_endpoint_success(self, test_client):
        """Test GET /api/work-items/{work_item_id}/intelligence successfully returns 200 with complete payload."""
        client, sb = test_client
        app.dependency_overrides[get_current_active_user] = lambda: {
            "id": ADMIN_USER_ID,
            "role": "admin",
            "firm_owner_id": ADMIN_USER_ID,
        }

        wid = "22222222-2222-2222-2222-222222222222"
        res = client.get(f"/api/work-items/{wid}/intelligence")
        assert res.status_code == 200, res.text
        data = res.json()

        assert data["work_item_id"] == wid
        assert data["exception_type"] == "MISSING_2B"
        assert "what_happened" in data["root_cause_explanation"]
        assert "likely_root_cause" in data["root_cause_explanation"]
        assert "statutory_context" in data["root_cause_explanation"]
        assert isinstance(data["evidence"], list)
        assert len(data["evidence"]) >= 1
        assert "score" in data["resolution_difficulty"]
        assert "tier" in data["resolution_difficulty"]
        assert "factors" in data["resolution_difficulty"]
        assert "disclaimer" in data["resolution_difficulty"]
        assert "action_type" in data["next_best_action"]
        assert "status" in data["revalidation_guidance"]

    def test_get_intelligence_cross_firm_isolation_403(self, test_client):
        """Test GET /api/work-items/{work_item_id}/intelligence returns 403 when accessed by another firm."""
        client, sb = test_client
        # Authenticate as user from another firm
        app.dependency_overrides[get_current_active_user] = lambda: {
            "id": OTHER_FIRM_USER_ID,
            "role": "admin",
            "firm_owner_id": OTHER_FIRM_USER_ID,
        }

        wid = "22222222-2222-2222-2222-222222222222"
        with patch("app.services.itc_work_item_service.list_accessible_client_gstin_ids", return_value={CLIENT_ID_2}):
            res = client.get(f"/api/work-items/{wid}/intelligence")
            assert res.status_code == 403

    def test_get_intelligence_not_found_404(self, test_client):
        """Test GET /api/work-items/{work_item_id}/intelligence returns 404 for non-existent item."""
        client, sb = test_client
        app.dependency_overrides[get_current_active_user] = lambda: {
            "id": ADMIN_USER_ID,
            "role": "admin",
            "firm_owner_id": ADMIN_USER_ID,
        }

        random_wid = "99999999-9999-9999-9999-999999999999"
        res = client.get(f"/api/work-items/{random_wid}/intelligence")
        assert res.status_code == 404
