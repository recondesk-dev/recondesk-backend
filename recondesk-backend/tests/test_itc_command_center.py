"""Comprehensive tests for Phase 5.1: ITC Command Center."""

from __future__ import annotations

from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from app.services.itc_command_center_service import get_itc_command_center_data
from app.services.reconciliation_outcomes import OutcomeRow
from app.auth import get_current_active_user
from tests.test_gstr3b_reversal_ledger import InMemorySupabaseClient

CLIENT_ID = "00000000-0000-0000-0000-000000000001"
GSTIN = "27AAACB1234A1Z1"
RUN_ID = "11111111-1111-1111-1111-111111111111"
USER_ID = "user-123"


def _make_mock_client():
    sb = InMemorySupabaseClient()
    sb.table("client_gstins").rows = [
        {
            "id": CLIENT_ID,
            "gstin": GSTIN,
            "trade_name": "Acme Industries",
            "legal_name": "Acme Industries Pvt Ltd",
            "is_active": True,
            "firm_owner_id": USER_ID,
            "assigned_to": USER_ID,
        }
    ]
    sb.table("reconciliation_run").rows = [
        {
            "id": RUN_ID,
            "client_gstin_id": CLIENT_ID,
            "period": "2026-08",
            "status": "FINAL",
            "is_locked": True,
            "finalized_at": "2026-09-10T10:00:00Z",
            "finalized_by": USER_ID,
            "run_summary": {
                "missed_itc_paise": 5000000,   # ₹50,000
                "wrongful_itc": 2000000,       # ₹20,000
            },
        }
    ]
    sb.table("gstr3b_table4_summaries").rows = [
        {
            "id": "snap-1",
            "run_id": RUN_ID,
            "status": "FINALIZED",
            "audit_hash": "mock-hash-123",
            "table_4a5": {"total_tax": 100000.0, "total_tax_paise": 10000000},
            "table_4b_total": {"total_tax": 10000.0, "total_tax_paise": 1000000},
            "table_4c": {"total_tax": 90000.0, "total_tax_paise": 9000000},
            "table_4d1": {"total_tax": 5000.0, "total_tax_paise": 500000},
        }
    ]
    sb.table("reconciliation_exception_dispositions").rows = []
    sb.table("gstr3b_table4_adjustments").rows = []
    return sb


def _make_mock_outcomes():
    # 1 clean match, 1 Rule 37 blocker, 1 Sec 17(5) blocker, 1 missing in 2B
    r_clean = OutcomeRow(
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
        decision_what="Matched invoice",
        decision_why="Exact match in PR and 2B",
        decision_next="Claim in Table 4A5",
        rule37_flag=False,
        blocked_credit_flag=False,
        late_filing_flag=False,
        is_credit_note=False,
        amount=1000000,
    )
    r_r37 = OutcomeRow(
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
        total_tax_diff_paise=0,
        decision_what="Unpaid beyond 180 days under Rule 37",
        decision_why="Payment pending for 210 days",
        decision_next="Reverse in Table 4(B)(2)",
        rule37_flag=True,
        blocked_credit_flag=False,
        late_filing_flag=False,
        is_credit_note=False,
        amount=8500000,  # ₹85,000
    )
    r_175 = OutcomeRow(
        id="pm:3",
        category="blocked_credit",
        supplier_gstin="27IJKLM9999K1Z3",
        supplier_name="Luxury Motors",
        invoice_number="INV-003",
        invoice_date="2026-08-05",
        match_status="BLOCKED_17_5",
        taxable_value_diff=0,
        igst_diff=0,
        cgst_diff=0,
        sgst_diff=0,
        total_tax_diff_paise=0,
        decision_what="Passenger vehicle motor repair blocked under Sec 17(5)(a)",
        decision_why="Motor vehicle credit restricted for non-transport business",
        decision_next="Report in 4A5 and reverse in 4B1",
        rule37_flag=False,
        blocked_credit_flag=True,
        late_filing_flag=False,
        is_credit_note=False,
        amount=4000000,  # ₹40,000
    )
    r_missed = OutcomeRow(
        id="pr:4",
        category="missed_itc",
        supplier_gstin="27NOPQR1111L1Z4",
        supplier_name="Missing Supplier",
        invoice_number="INV-004",
        invoice_date="2026-08-12",
        match_status="MISSING_2B",
        taxable_value_diff=0,
        igst_diff=0,
        cgst_diff=0,
        sgst_diff=0,
        total_tax_diff_paise=0,
        decision_what="Purchase register invoice not in GSTR-2B",
        decision_why="Supplier has not uploaded invoice in GSTR-1",
        decision_next="Follow up with supplier to file in GSTR-1",
        rule37_flag=False,
        blocked_credit_flag=False,
        late_filing_flag=False,
        is_credit_note=False,
        amount=15000000,  # ₹1,50,000
    )
    return [r_clean, r_r37, r_175, r_missed]


def test_command_center_service_aggregation():
    sb = _make_mock_client()
    mock_rows = _make_mock_outcomes()

    with patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
         patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(mock_rows, {}, {})), \
         patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={
             "can_finalize": False,
             "unresolved_blocking_exceptions": 2,
             "blocking_records": [{"record_id": "pm:2"}, {"record_id": "pm:3"}],
         }):
        res = get_itc_command_center_data(sb, CLIENT_ID, period="2026-08")

    assert res["client"]["gstin"] == GSTIN
    assert res["client"]["pan"] == "AAACB1234A"
    assert res["selected_period"] == "2026-08"
    assert res["is_locked"] is True
    assert res["audit_hash"] == "mock-hash-123"

    # KPIs
    kpis = res["kpis"]
    assert kpis["eligible_itc"] == 100000.0
    assert kpis["reversed_itc"] == 10000.0
    assert kpis["net_itc"] == 90000.0
    assert kpis["reclaimed_itc"] == 5000.0
    assert kpis["missed_itc"] == 50000.0
    assert kpis["at_risk_itc"] == 20000.0

    # Work items: 3 exceptions (clean match excluded)
    items = res["work_items"]
    assert len(items) == 3

    # Check priorities
    types = [item["exception_type"] for item in items]
    assert "RULE_37" in types
    assert "SEC_17_5" in types
    assert "MISSING_2B" in types

    # Rule 37 & Sec 17(5) are blocking records -> CRITICAL
    r37_item = next(i for i in items if i["exception_type"] == "RULE_37")
    assert r37_item["is_blocking"] is True
    assert r37_item["priority"] == "CRITICAL"
    assert "Rule 37" in r37_item["what"]
    assert r37_item["status"] in ("ACTION_REQUIRED", "OPEN")

    # Missing 2B is ₹1.5L -> HIGH (per spec Section 6)
    missed_item = next(i for i in items if i["exception_type"] == "MISSING_2B")
    assert missed_item["priority"] == "HIGH"
    assert missed_item["status"] in ("AWAITING_VENDOR", "OPEN")
    assert "purchase register" in missed_item["what"].lower()

    # Summary counts
    sc = res["summary_counts"]
    assert sc["total_items"] == 3
    assert sc["blocking_count"] == 2


def test_command_center_endpoint_integration():
    from app.main import app

    sb = _make_mock_client()
    mock_rows = _make_mock_outcomes()

    app.dependency_overrides[get_current_active_user] = lambda: {
        "id": USER_ID,
        "email": "ca@recondesk.in",
        "role": "admin",
    }

    try:
        with patch("app.routers.clients.get_supabase", return_value=sb), \
             patch("app.routers.clients.list_accessible_client_gstin_ids", return_value={CLIENT_ID}), \
             patch("app.services.reconciliation_outcomes.load_payload", return_value={}), \
             patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=(mock_rows, {}, {})), \
             patch("app.services.gstr3b_table4_engine.check_finalization_blocking_exceptions", return_value={
                 "can_finalize": False,
                 "unresolved_blocking_exceptions": 2,
                 "blocking_records": [{"record_id": "pm:2"}, {"record_id": "pm:3"}],
             }):

            client = TestClient(app)
            response = client.get(
                f"/api/clients/{CLIENT_ID}/command-center?period=2026-08",
            )
            assert response.status_code == 200
            data = response.json()
            assert data["client"]["gstin"] == GSTIN
            assert data["kpis"]["net_itc"] == 90000.0
            assert len(data["work_items"]) == 3
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
