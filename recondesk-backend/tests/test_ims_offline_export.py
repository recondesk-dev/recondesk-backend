"""Unit tests for GSTN IMS Offline Export & Batch File Generator."""

from __future__ import annotations

import io
import json
import pytest
from unittest.mock import MagicMock, patch
from openpyxl import load_workbook

from app.ims.ims_offline_export import (
    build_ims_offline_json,
    build_ims_workpaper_excel,
    ca_action_to_gstn_act,
    format_gstn_date,
    format_gstn_period,
    normalize_export_item,
)
from app.ims.ims_recommendation import InvoiceRecommendation


def test_format_gstn_date_and_period():
    assert format_gstn_date("2024-10-15") == "15-10-2024"
    assert format_gstn_date("2024-10-15T10:30:00Z") == "15-10-2024"
    assert format_gstn_date("15/10/2024") == "15-10-2024"
    assert format_gstn_date("15-10-2024") == "15-10-2024"
    assert format_gstn_date(None) == ""

    assert format_gstn_period("2024-10") == "102024"
    assert format_gstn_period("10-2024") == "102024"
    assert format_gstn_period("102024") == "102024"


def test_ca_action_to_gstn_act():
    assert ca_action_to_gstn_act("accept") == ("Accept", "A")
    assert ca_action_to_gstn_act("reject") == ("Reject", "R")
    assert ca_action_to_gstn_act("hold") == ("Pending", "P")
    assert ca_action_to_gstn_act("pending") == ("Pending", "P")
    assert ca_action_to_gstn_act("unknown") == ("Pending", "P")


def test_normalize_export_item():
    rec = InvoiceRecommendation(
        invoice_id="inv-101",
        supplier_gstin="27AABCU9603R1ZM",
        invoice_number="INV-001",
        invoice_date="2024-10-01",
        supplier_name="Acme Supplies Ltd",
        category="matched",
        ims_status="no_action_taken",
        recommended_action="accept",
        confidence_score=0.98,
        confidence_source="matcher_fuzzy",
        reason_codes=("MATCHED_IN_BOOKS",),
        human_readable_why="Clean match in purchase register.",
        amount_paise=1180000,
        section="b2b",
        writeback_payload={
            "txval": 10000.0,
            "iamt": 0.0,
            "camt": 900.0,
            "samt": 900.0,
            "cess": 0.0,
            "val": 11800.0,
            "pos": "27",
            "rchrg": "N",
        },
    )

    norm = normalize_export_item(rec)
    assert norm["invoice_id"] == "inv-101"
    assert norm["supplier_gstin"] == "27AABCU9603R1ZM"
    assert norm["supplier_name"] == "Acme Supplies Ltd"
    assert norm["invoice_number"] == "INV-001"
    assert norm["invoice_date"] == "01-10-2024"
    assert norm["recommended_action"] == "accept"
    assert norm["chosen_action"] == "accept"
    assert norm["act_code"] == "A"
    assert norm["action_label"] == "Accept"
    assert not norm["is_override"]
    assert norm["txval"] == 10000.0
    assert norm["val"] == 11800.0
    assert norm["total_tax"] == 1800.0


def test_build_ims_offline_json():
    items = [
        {
            "invoice_id": "inv-1",
            "supplier_gstin": "27AABCU9603R1ZM",
            "supplier_name": "Supplier A",
            "invoice_number": "INV-001",
            "invoice_date": "2024-10-01",
            "recommended_action": "accept",
            "chosen_action": "accept",
            "section": "b2b",
            "writeback_payload": {
                "txval": 10000.0,
                "camt": 900.0,
                "samt": 900.0,
                "iamt": 0.0,
                "cess": 0.0,
                "val": 11800.0,
                "pos": "27",
                "rchrg": "N",
                "inv_typ": "R",
            },
        },
        {
            "invoice_id": "inv-2",
            "supplier_gstin": "27AABCU9603R1ZM",
            "supplier_name": "Supplier A",
            "invoice_number": "INV-002",
            "invoice_date": "2024-10-05",
            "recommended_action": "hold",
            "chosen_action": "reject",  # Override
            "section": "b2b",
            "writeback_payload": {
                "txval": 5000.0,
                "camt": 450.0,
                "samt": 450.0,
                "val": 5900.0,
                "pos": "27",
                "rchrg": "N",
            },
        },
        {
            "invoice_id": "cn-1",
            "supplier_gstin": "27XYZPA1234F1ZQ",
            "supplier_name": "Supplier B",
            "invoice_number": "CN-999",
            "invoice_date": "2024-10-20",
            "recommended_action": "hold",
            "chosen_action": "hold",
            "section": "cdnr",
            "note_type": "C",
            "original_invoice_number": "INV-ORIG-01",
            "original_invoice_date": "2024-09-15",
            "writeback_payload": {
                "txval": 2000.0,
                "iamt": 360.0,
                "val": 2360.0,
                "pos": "27",
            },
        },
    ]

    buyer_gstin = "27AAPFU0939F1ZV"
    period = "2024-10"

    offline_data = build_ims_offline_json(buyer_gstin, period, items)

    assert offline_data["gstin"] == buyer_gstin
    assert offline_data["fp"] == "102024"
    assert offline_data["version"] == "1.0"

    # B2B checks
    assert len(offline_data["b2b"]) == 1
    supp_a_group = offline_data["b2b"][0]
    assert supp_a_group["ctin"] == "27AABCU9603R1ZM"
    assert supp_a_group["cpty"] == "Supplier A"
    assert len(supp_a_group["inv"]) == 2

    inv1 = supp_a_group["inv"][0]
    assert inv1["inum"] == "INV-001"
    assert inv1["idt"] == "01-10-2024"
    assert inv1["act"] == "A"
    assert inv1["action"] == "Accept"
    assert inv1["val"] == 11800.0
    assert inv1["itms"][0]["txval"] == 10000.0
    assert inv1["itms"][0]["camt"] == 900.0

    inv2 = supp_a_group["inv"][1]
    assert inv2["inum"] == "INV-002"
    assert inv2["act"] == "R"
    assert inv2["action"] == "Reject"

    # CDNR checks
    assert len(offline_data["cdnr"]) == 1
    supp_b_group = offline_data["cdnr"][0]
    assert supp_b_group["ctin"] == "27XYZPA1234F1ZQ"
    assert len(supp_b_group["nt"]) == 1
    nt1 = supp_b_group["nt"][0]
    assert nt1["nt_num"] == "CN-999"
    assert nt1["nt_dt"] == "20-10-2024"
    assert nt1["ntty"] == "C"
    assert nt1["inum"] == "INV-ORIG-01"
    assert nt1["act"] == "P"
    assert nt1["action"] == "Pending"


def test_build_ims_workpaper_excel():
    items = [
        {
            "invoice_id": "inv-1",
            "supplier_gstin": "27AABCU9603R1ZM",
            "supplier_name": "Alpha Traders",
            "invoice_number": "INV-100",
            "invoice_date": "2024-10-01",
            "category": "matched",
            "recommended_action": "accept",
            "chosen_action": "accept",
            "section": "b2b",
            "reason_codes": ["MATCHED_IN_BOOKS"],
            "why": "Books and GSTR-2B match clean.",
            "writeback_payload": {
                "txval": 100000.0,
                "camt": 9000.0,
                "samt": 9000.0,
                "iamt": 0.0,
                "val": 118000.0,
                "pos": "27",
                "rchrg": "N",
            },
        },
        {
            "invoice_id": "inv-2",
            "supplier_gstin": "27AABCU9603R1ZM",
            "supplier_name": "Alpha Traders",
            "invoice_number": "INV-101",
            "invoice_date": "2024-10-02",
            "category": "review_required",
            "recommended_action": "hold",
            "chosen_action": "hold",
            "section": "b2b",
            "reason_codes": ["RCM_FLAG_CONFLICT"],
            "why": "Reverse charge treatment conflict: GSTR-2B reverse-charge indicator contradicts PR.",
            "writeback_payload": {
                "txval": 25000.0,
                "iamt": 4500.0,
                "val": 29500.0,
                "pos": "27",
                "rchrg": "Y",
            },
        },
        {
            "invoice_id": "inv-3",
            "supplier_gstin": "06BBBBA1111B1ZZ",
            "supplier_name": "Beta Services",
            "invoice_number": "INV-201",
            "invoice_date": "2024-10-03",
            "category": "review_required",
            "recommended_action": "hold",
            "chosen_action": "hold",
            "section": "b2b",
            "reason_codes": ["TAX_HEAD_MISMATCH"],
            "why": "Tax head allocation mismatch: GSTR-2B has IGST but PR booked CGST+SGST.",
            "writeback_payload": {
                "txval": 50000.0,
                "iamt": 9000.0,
                "val": 59000.0,
                "pos": "06",
                "rchrg": "N",
            },
        },
        {
            "invoice_id": "cn-1",
            "supplier_gstin": "27AABCU9603R1ZM",
            "supplier_name": "Alpha Traders",
            "invoice_number": "CN-001",
            "invoice_date": "2024-10-15",
            "category": "missed_itc",
            "recommended_action": "hold",
            "chosen_action": "hold",
            "section": "cdnr",
            "note_type": "C",
            "original_invoice_number": "INV-100",
            "original_invoice_date": "2024-10-01",
            "reason_codes": ["UNLINKED_CREDIT_NOTE"],
            "why": "Credit Note unlinked in purchase register.",
            "writeback_payload": {
                "txval": 10000.0,
                "camt": 900.0,
                "samt": 900.0,
                "val": 11800.0,
                "pos": "27",
            },
        },
    ]

    xlsx_bytes, filename = build_ims_workpaper_excel(
        buyer_gstin="27AAPFU0939F1ZV",
        period="2024-10",
        items=items,
        client_name="Test Client Enterprises",
        firm_name="Kadam & Co. Chartered Accountants",
        generated_by="Omkar Kadam, CA",
    )

    assert isinstance(xlsx_bytes, bytes)
    assert len(xlsx_bytes) > 2000
    assert filename.startswith("IMS_Action_Workpaper_27AAPFU0939F1ZV_")
    assert filename.endswith(".xlsx")

    # Inspect Excel content via openpyxl
    wb = load_workbook(io.BytesIO(xlsx_bytes))
    sheet_names = wb.sheetnames
    assert "IMS Summary" in sheet_names
    assert "B2B Actions" in sheet_names
    assert "CDNR Actions" in sheet_names

    ws_summary = wb["IMS Summary"]
    # Check title
    assert "ReconDesk — GSTN IMS Action Audit Workpaper" in str(ws_summary["A1"].value)
    # Check client header
    assert "Test Client Enterprises" in str(ws_summary["A2"].value)

    # Check that high-priority rules are listed
    summary_text = " ".join(str(cell.value or "") for row in ws_summary.iter_rows() for cell in row)
    assert "RCM Flag Conflict" in summary_text
    assert "Tax-Head Mismatch" in summary_text
    assert "Rule 37 180-Day Payment Clock" in summary_text
    assert "Section 17(5) Blocked Credit" in summary_text

    # Check B2B sheet has rows
    ws_b2b = wb["B2B Actions"]
    assert ws_b2b.max_row == 4  # Header + 3 B2B invoices

    # Check CDNR sheet has row
    ws_cdnr = wb["CDNR Actions"]
    assert ws_cdnr.max_row == 2  # Header + 1 CDNR note


@pytest.mark.asyncio
async def test_ims_export_json_endpoint():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth import get_current_active_user
    from app.ims.ims_recommendation import RecommendationBatch, InvoiceRecommendation

    client = TestClient(app)
    app.dependency_overrides[get_current_active_user] = lambda: {"id": "user-test-123"}

    mock_rec = InvoiceRecommendation(
        invoice_id="inv-endpoint-1",
        supplier_gstin="27AABCU9603R1ZM",
        invoice_number="INV-EP-101",
        invoice_date="2024-10-01",
        supplier_name="Test Supplier",
        category="matched",
        ims_status="no_action_taken",
        recommended_action="accept",
        confidence_score=0.95,
        confidence_source="matcher_fuzzy",
        reason_codes=("MATCHED_IN_BOOKS",),
        human_readable_why="Matched clean in books.",
        amount_paise=118000,
        section="b2b",
        writeback_payload={
            "txval": 1000.0,
            "iamt": 0.0,
            "camt": 90.0,
            "samt": 90.0,
            "val": 1180.0,
            "pos": "27",
            "rchrg": "N",
        },
    )

    batch = RecommendationBatch(
        available=True,
        reason=None,
        invoices=[mock_rec],
        high_confidence_accept_count=1,
    )

    with patch("app.routers.ims_actions.get_supabase") as mock_get_sb, \
         patch("app.routers.ims_actions.assert_run_accessible") as mock_assert, \
         patch("app.routers.ims_actions._client_row_for_run") as mock_client_row, \
         patch("app.routers.ims_actions.build_recommendations_for_run") as mock_build_rec, \
         patch("app.routers.ims_actions.log_audit") as mock_log_audit, \
         patch("app.routers.ims_actions.get_user_profile") as mock_user_prof:

        mock_get_sb.return_value = MagicMock()

        mock_assert.return_value = {"id": "run-test-1", "period": "2024-10", "client_gstin_id": "cg-1"}
        mock_client_row.return_value = {"gstin": "27AAPFU0939F1ZV", "trade_name": "Test Client"}
        mock_build_rec.return_value = batch
        mock_user_prof.return_value = {"firm_name": "Kadam & Co.", "full_name": "Omkar Kadam"}

        # 1. GET export JSON
        res_get = client.get("/api/reconcile/runs/run-test-1/ims/export/json")
        assert res_get.status_code == 200
        assert res_get.headers["content-type"] == "application/json"
        assert "attachment; filename=" in res_get.headers["content-disposition"]
        json_body = res_get.json()
        assert json_body["gstin"] == "27AAPFU0939F1ZV"
        assert json_body["fp"] == "102024"
        assert len(json_body["b2b"]) == 1
        assert json_body["b2b"][0]["inv"][0]["inum"] == "INV-EP-101"
        assert json_body["b2b"][0]["inv"][0]["act"] == "A"

        # 2. POST export JSON with override
        body = {
            "invoices": [
                {
                    "invoice_id": "inv-endpoint-1",
                    "chosen_action": "reject",
                    "section": "b2b",
                }
            ]
        }
        res_post = client.post("/api/reconcile/runs/run-test-1/ims/export/json", json=body)
        assert res_post.status_code == 200
        json_post_body = res_post.json()
        assert json_post_body["b2b"][0]["inv"][0]["act"] == "R"
        assert json_post_body["b2b"][0]["inv"][0]["action"] == "Reject"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ims_export_excel_endpoint():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth import get_current_active_user
    from app.ims.ims_recommendation import RecommendationBatch, InvoiceRecommendation

    client = TestClient(app)
    app.dependency_overrides[get_current_active_user] = lambda: {"id": "user-test-123"}

    mock_rec = InvoiceRecommendation(
        invoice_id="inv-excel-1",
        supplier_gstin="27AABCU9603R1ZM",
        invoice_number="INV-EX-202",
        invoice_date="2024-10-01",
        supplier_name="Excel Supplier Ltd",
        category="matched",
        ims_status="no_action_taken",
        recommended_action="accept",
        confidence_score=0.99,
        confidence_source="matcher_fuzzy",
        reason_codes=("MATCHED_IN_BOOKS",),
        human_readable_why="Matched clean in books.",
        amount_paise=236000,
        section="b2b",
        writeback_payload={
            "txval": 2000.0,
            "iamt": 0.0,
            "camt": 180.0,
            "samt": 180.0,
            "val": 2360.0,
            "pos": "27",
            "rchrg": "N",
        },
    )

    batch = RecommendationBatch(
        available=True,
        reason=None,
        invoices=[mock_rec],
        high_confidence_accept_count=1,
    )

    with patch("app.routers.ims_actions.get_supabase") as mock_get_sb, \
         patch("app.routers.ims_actions.assert_run_accessible") as mock_assert, \
         patch("app.routers.ims_actions._client_row_for_run") as mock_client_row, \
         patch("app.routers.ims_actions.build_recommendations_for_run") as mock_build_rec, \
         patch("app.routers.ims_actions.log_audit") as mock_log_audit, \
         patch("app.routers.ims_actions.get_user_profile") as mock_user_prof:

        mock_get_sb.return_value = MagicMock()
        mock_assert.return_value = {"id": "run-test-2", "period": "2024-10", "client_gstin_id": "cg-1"}
        mock_client_row.return_value = {"gstin": "27AAPFU0939F1ZV", "trade_name": "Excel Client"}
        mock_build_rec.return_value = batch
        mock_user_prof.return_value = {"firm_name": "Kadam & Co.", "full_name": "Omkar Kadam"}

        # 1. GET export Excel
        res_get = client.get("/api/reconcile/runs/run-test-2/ims/export/excel")
        assert res_get.status_code == 200
        assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in res_get.headers["content-type"]
        assert "attachment; filename=" in res_get.headers["content-disposition"]
        assert len(res_get.content) > 1000

        # Load workbook to verify sheets
        wb = load_workbook(io.BytesIO(res_get.content))
        assert "IMS Summary" in wb.sheetnames
        assert "B2B Actions" in wb.sheetnames
        assert "CDNR Actions" in wb.sheetnames

        # 2. POST export Excel with override
        body = {
            "invoices": [
                {
                    "invoice_id": "inv-excel-1",
                    "chosen_action": "hold",
                    "section": "b2b",
                }
            ]
        }
        res_post = client.post("/api/reconcile/runs/run-test-2/ims/export/excel", json=body)
        assert res_post.status_code == 200
        assert len(res_post.content) > 1000

    app.dependency_overrides.clear()

