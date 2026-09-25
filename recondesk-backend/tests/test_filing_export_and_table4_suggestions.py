"""Unit tests for GSTR-1 and GSTR-3B offline JSON export & Table 4 suggestions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from fastapi import HTTPException

from app.filing.gstr3b_suggestions import (
    load_table4_suggestion,
    REASON_NO_GSTR2B_RUN,
)
from app.routers.filing import (
    ExportGstr3bJsonBody,
    ExportGstr1JsonBody,
    filing_features,
    filing_history,
    gstr1_export_json,
    gstr3b_export_json,
    gstr3b_suggest_table4,
)

GSTIN = "27AAACB1234A1Z1"
PERIOD = "2026-07"
CLIENT_ID = "00000000-0000-0000-0000-000000000001"
USER = {"id": "user-1", "firm_id": "firm-1", "is_active": True}


def test_filing_features_returns_preparation_enabled():
    res = filing_features()
    assert res["gstr1_filing_enabled"] is True
    assert res["gstr3b_preparation_enabled"] is True
    assert "gstr3b_filing_enabled" in res


def test_load_table4_suggestion_unavailable_when_no_run():
    sb = MagicMock()
    # Mock no runs returned
    sb.table().select().eq().in_().order().limit().execute.return_value = MagicMock(data=[])
    res = load_table4_suggestion(sb, client_gstin_id=CLIENT_ID, period=PERIOD)
    assert res["available"] is False
    assert res["reason"] == REASON_NO_GSTR2B_RUN


def test_load_table4_suggestion_success():
    sb = MagicMock()
    # Mock finding a run
    sb.table().select().eq().in_().order().limit().execute.return_value = MagicMock(
        data=[{"id": "run-123", "period": "2026-07", "status": "COMPLETED"}]
    )

    mock_t4 = {
        "table_4": {
            "section_4a": {
                "row_4a1_import_goods": {"igst": 1000.0, "cess": 50.0},
                "row_4a2_import_services": {"igst": 2000.0, "cess": 0.0},
                "row_4a3_inward_rcm": {"igst": 300.0, "cgst": 150.0, "sgst": 150.0, "cess": 0.0},
                "row_4a4_isd": {"igst": 400.0, "cgst": 200.0, "sgst": 200.0, "cess": 0.0},
                "row_4a5_all_other_itc": {"igst": 50000.0, "cgst": 25000.0, "sgst": 25000.0, "cess": 500.0},
            },
            "section_4b": {
                "row_4b1_rule38_42_43_sec175": {"igst": 500.0, "cgst": 250.0, "sgst": 250.0, "cess": 0.0},
                "row_4b2_others_rule37_37a": {"igst": 300.0, "cgst": 150.0, "sgst": 150.0, "cess": 0.0},
            },
            "section_4c_net_itc": {"igst": 52900.0, "cgst": 24950.0, "sgst": 24950.0, "cess": 550.0},
            "section_4d": {
                "row_4d1_reclaimed": {"igst": 100.0, "cgst": 50.0, "sgst": 50.0, "cess": 0.0},
                "row_4d2_ineligible_16_4_pos": {"igst": 200.0, "cgst": 100.0, "sgst": 100.0, "cess": 0.0},
            },
        }
    }

    with patch("app.services.gstr3b_table4_engine.compile_gstr3b_table4", return_value=mock_t4):
        res = load_table4_suggestion(sb, client_gstin_id=CLIENT_ID, period=PERIOD)

    assert res["available"] is True
    assert res["run_id"] == "run-123"
    assert "itc_elg" in res

    avl = {r["ty"]: r for r in res["itc_elg"]["itc_avl"]}
    assert avl["IMPG"]["iamt"] == 1000.0
    assert avl["OTH"]["iamt"] == 50000.0
    assert avl["OTH"]["camt"] == 25000.0

    rev = {r["ty"]: r for r in res["itc_elg"]["itc_rev"]}
    assert rev["RUL"]["iamt"] == 500.0
    assert rev["OTH"]["iamt"] == 300.0

    net = res["itc_elg"]["itc_net"][0]
    assert net["iamt"] == 52900.0


def test_gstr3b_export_json_endpoint():
    sb = MagicMock()
    body = ExportGstr3bJsonBody(
        client_gstin_id=CLIENT_ID,
        figures={
            "sup_details": {
                "osup_det": {"txval": 100000.0, "iamt": 18000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                "osup_zero": {"txval": 0.0, "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                "osup_nil_exmp": {"txval": 0.0, "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                "osup_nongst": {"txval": 0.0, "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                "isup_rev": {"txval": 0.0, "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
            },
            "itc_elg": {
                "itc_avl": [
                    {"ty": "IMPG", "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                    {"ty": "IMPS", "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                    {"ty": "ISRC", "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                    {"ty": "ISD", "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                    {"ty": "OTH", "iamt": 18000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                ],
                "itc_rev": [
                    {"ty": "RUL", "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                    {"ty": "OTH", "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                ],
                "itc_net": [{"ty": "", "iamt": 18000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}],
                "itc_inelg": [
                    {"ty": "RUL", "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                    {"ty": "OTH", "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                ],
            },
        },
    )

    with patch("app.routers.filing.get_supabase", return_value=sb), \
         patch("app.routers.filing._firm_id", return_value="firm-1"), \
         patch("app.routers.filing._assert_client_access", return_value={"id": CLIENT_ID, "gstin": GSTIN}):
        res = gstr3b_export_json(period=PERIOD, body=body, current_user=USER)

    assert res["filename"] == f"gstr3b_{GSTIN}_072026.json"
    assert res["gstin"] == GSTIN
    assert res["ret_period"] == "072026"
    assert "payload" in res
    assert res["payload"]["gstin"] == GSTIN
    assert res["payload"]["ret_period"] == "072026"
    assert "sup_details" in res["payload"]
    assert "itc_elg" in res["payload"]


def test_gstr1_export_json_endpoint():
    sb = MagicMock()
    sample_record = {
        "invoice_number": "INV-001",
        "invoice_date": "2026-07-10",
        "taxable_amount": 10000.0,
        "igst": 1800.0,
        "cgst": 0.0,
        "sgst": 0.0,
        "cess": 0.0,
        "invoice_type": "B2B",
        "customer_gstin": "27BBBBB1111B1Z2",
        "pos": "27",
    }
    body = ExportGstr1JsonBody(
        client_gstin_id=CLIENT_ID,
        records=[sample_record],
        gt=500000.0,
        cur_gt=10000.0,
    )

    with patch("app.routers.filing.get_supabase", return_value=sb), \
         patch("app.routers.filing._firm_id", return_value="firm-1"), \
         patch("app.routers.filing._assert_client_access", return_value={"id": CLIENT_ID, "gstin": GSTIN}):
        res = gstr1_export_json(period=PERIOD, body=body, current_user=USER)

    assert res["filename"] == f"gstr1_{GSTIN}_072026.json"
    assert res["gstin"] == GSTIN
    assert res["fp"] == "072026"
    assert res["record_count"] == 1
    assert "payload" in res
    assert res["payload"]["gstin"] == GSTIN
    assert res["payload"]["fp"] == "072026"


def test_filing_history_endpoint():
    sb = MagicMock()
    mock_runs = [
        {
            "id": "run-1",
            "return_type": "gstr-1",
            "period": "2026-07",
            "status": "filed",
            "reference_id": "REF-1",
            "arn": "AA2707260000001",
            "filing_method": "evc",
            "created_at": "2026-08-10T10:00:00Z",
            "updated_at": "2026-08-10T10:05:00Z",
            "offset_completed_at": None,
            "filed_at": "2026-08-10T10:05:00Z",
        }
    ]
    sb.table().select().eq().order().limit().execute.return_value = MagicMock(data=mock_runs)

    with patch("app.routers.filing.get_supabase", return_value=sb), \
         patch("app.routers.filing._firm_id", return_value="firm-1"), \
         patch("app.routers.filing._assert_client_access", return_value={"id": CLIENT_ID, "gstin": GSTIN}):
        res = filing_history(client_gstin_id=CLIENT_ID, current_user=USER)

    assert res["gstin"] == GSTIN
    assert res["client_gstin_id"] == CLIENT_ID
    assert len(res["filings"]) == 1
    assert res["filings"][0]["arn"] == "AA2707260000001"
