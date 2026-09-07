"""
test_rule37a_non_filer.py

End-to-end tests for Rule 37A (Supplier GSTR-3B Non-Filer) and ITC Ineligibility
handling across parser, matcher adapter, outcomes builder, decision layer,
Excel export, and IMS recommendation engine.
"""

import io
from datetime import date, datetime
from unittest.mock import MagicMock
import pytest
from openpyxl import load_workbook

from app.parsers.gstr2b_parser import parse_gstr2b
from app.services.reconciliation_record_adapter import gstr_db_row_to_matcher_row
from app.services.reconciliation_outcomes import build_outcome_rows, OutcomeRow
from app.services.reconcile_export_workbook import build_excel_workbook_bytes
from app.ims.ims_recommendation import (
    InvoiceRecommendationInput,
    recommend_invoice,
    REASON_RULE37A_NON_FILER,
)
from app.ims.ims_run_service import build_recommendations_for_run


def test_parser_retains_itcavl_n_and_rsn_json():
    payload = {
        "data": {
            "gstin": "27TESTBUYER1Z0",
            "rtnprd": "072026",
            "b2b": [
                {
                    "ctin": "27AABCU9603R1ZM",
                    "inv": [
                        {
                            "inum": "INV-2026-001",
                            "idt": "15-07-2026",
                            "val": 118000.0,
                            "pos": "27",
                            "rchrg": "N",
                            "inv_typ": "R",
                            "itcavl": "N",
                            "rsn": "Supplier has not filed GSTR-3B for the said period",
                            "itms": [
                                {
                                    "num": 1,
                                    "itm_det": {
                                        "rt": 18.0,
                                        "txval": 100000.0,
                                        "iamt": 0.0,
                                        "camt": 9000.0,
                                        "samt": 9000.0,
                                        "csamt": 0.0,
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    }
    res = parse_gstr2b(payload)
    assert len(res["records"]) == 1
    rec = res["records"][0]
    assert rec["itc_available"] is False
    assert rec["itc_reason"] == "Supplier has not filed GSTR-3B for the said period"


def test_parser_retains_alt_spreadsheet_itc_availability_and_reason():
    alt_payload = {
        "invoice": [
            {
                "GSTIN of Supplier": "27AABCU9603R1ZM",
                "Trade/Legal Name of Supplier": "Test Supplier",
                "Invoice number": "INV-2026-002",
                "Invoice Date": "15-07-2026",
                "Invoice Value (₹)": 118000.0,
                "Taxable Value (₹)": 100000.0,
                "Central Tax (₹)": 9000.0,
                "State/UT Tax (₹)": 9000.0,
                "Integrated Tax (₹)": 0.0,
                "ITC Availability": "No",
                "Reason": "Supplier has not filed GSTR-3B for the said period",
            }
        ]
    }
    res = parse_gstr2b(alt_payload, fallback_buyer_gstin="27TESTBUYER1Z0", fallback_period="2026-07")
    assert len(res["records"]) == 1
    rec = res["records"][0]
    assert rec["itc_available"] is False
    assert rec["itc_reason"] == "Supplier has not filed GSTR-3B for the said period"


def test_reconciliation_record_adapter_itc_fields():
    gstr_db_row = {
        "id": "g-123",
        "record_data": {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-001",
            "invoice_date_norm": "2026-07-15",
            "taxable_value_paise": 10000000,
            "cgst_paise": 900000,
            "sgst_paise": 900000,
            "igst_paise": 0,
            "total_tax_paise": 1800000,
            "itc_available": False,
            "itc_reason": "Supplier has not filed GSTR-3B for the said period",
        },
    }
    matcher_row = gstr_db_row_to_matcher_row(gstr_db_row)
    assert matcher_row["itc_available"] is False
    assert matcher_row["itc_reason"] == "Supplier has not filed GSTR-3B for the said period"


def test_outcomes_routes_matched_non_filer_to_rule37_warnings():
    sb = MagicMock()
    run_id = "test-run-r37a"

    gstr_db_row = {
        "id": "g-1",
        "record_data": {
            "supplier_gstin": "27AABCU9603R1ZM",
            "supplier_name": "Test Supplier",
            "invoice_number": "INV-001",
            "invoice_date_norm": "2026-07-15",
            "taxable_value_paise": 10000000,
            "cgst_paise": 900000,
            "sgst_paise": 900000,
            "igst_paise": 0,
            "total_tax_paise": 1800000,
            "itc_available": False,
            "itc_reason": "Supplier has not filed GSTR-3B for the said period",
        },
    }

    pr_db_row = {
        "id": "p-1",
        "record_data": {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-001",
            "invoice_date_norm": "2026-07-15",
            "taxable_value_paise": 10000000,
            "cgst_paise": 900000,
            "sgst_paise": 900000,
            "igst_paise": 0,
            "total_tax_paise": 1800000,
        },
    }

    # Wire supabase pagination loop
    sb.table().select().eq().limit().execute.return_value = MagicMock(count=1)
    sb.table().select().eq().range().execute.side_effect = [
        MagicMock(data=[gstr_db_row]),
        MagicMock(data=[pr_db_row]),
    ]

    payload = {
        "engine": {
            "matched": [
                {
                    "gstr_id": "g-1",
                    "pr_id": "p-1",
                    "match_confidence": 1.0,
                }
            ],
            "missed_itc": [],
            "wrongful_itc_risk": [],
        },
        "compliance": {},
        "decisions": {},
    }

    rows, ccounts, stats = build_outcome_rows(sb, run_id, payload)

    assert len(rows) == 1
    r = rows[0]
    assert r.category == "rule37_warnings"
    assert r.match_status == "RULE37A"
    assert r.rule37a_flag is True
    assert r.itc_available is False
    assert "Rule 37A" in r.decision_what
    assert "GSTR-3B" in r.decision_why
    assert "Hold on IMS" in r.decision_next

    assert ccounts["matched"] == 0
    assert ccounts["rule37_warnings"] == 1
    assert stats["matched_count"] == 0
    assert stats["rule37_warnings_count"] == 1


def test_excel_export_includes_rule37a_in_ws5_and_not_in_matched():
    r37a_row = {
        "id": "pm:g-1",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "INV-001",
        "invoice_date": "2026-07-15",
        "amount": 18000.0,
        "rule37_urgency": "HIGH",
        "rule37a_flag": True,
        "status": "RULE37A",
        "decision_what": "ITC unavailable in GSTR-2B (Supplier GSTR-3B Non-Filer / Rule 37A)",
        "decision_why": "Supplier has not filed GSTR-3B for the tax period (Rule 37A risk).",
        "decision_next": "Hold on IMS and do not claim in GSTR-3B.",
    }

    xlsx_bytes, _ = build_excel_workbook_bytes(
        run_id="test-run",
        firm_name="Test Firm",
        client_trade_name="Test Client",
        period_raw="2026-07",
        summary={"total_records": 1, "total_matched": 0},
        matched_pairs=[],  # Excluded from matched
        missed_rows=[],
        risk_rows=[],
        rule37_rows=[r37a_row],
        section17_rows=[],
        review_required_rows=[],
        duplicate_rows=[],
        generated_at=datetime.now(),
        generated_by_name="Test User",
    )

    wb = load_workbook(io.BytesIO(xlsx_bytes))
    ws_matched = wb["Matched Records"]
    # Matched sheet should only have header or empty message
    assert ws_matched.max_row <= 2

    ws_r37 = wb["Rule 37 & Section 17-5"]
    assert ws_r37.max_row >= 2
    row2_vals = [cell.value for cell in ws_r37[2]]
    assert row2_vals[0] == "Rule 37A"
    assert row2_vals[1] == "27AABCU9603R1ZM"
    assert row2_vals[2] == "INV-001"
    assert row2_vals[5] == "HIGH"
    assert "Rule 37A" in str(row2_vals[6])


def test_ims_recommendation_hold_for_rule37a_non_filer():
    inp = InvoiceRecommendationInput(
        invoice_id="pm:g-1",
        supplier_gstin="27AABCU9603R1ZM",
        invoice_number="INV-001",
        category="rule37_warnings",
        match_status="RULE37A",
        rule37a_flag=True,
        rule37_flag=True,
    )
    rec = recommend_invoice(inp)
    assert rec is not None
    assert rec.recommended_action == "hold"
    assert REASON_RULE37A_NON_FILER in rec.reason_codes
    assert "Rule 37A" in rec.human_readable_why


def test_outcomes_does_not_route_to_rule37_warnings_when_no_r37a_signal():
    """When is_itc_avail is False but there is NO Rule 37A signal (no itc_reason,
    no non-filer keyword), the row must land in category='matched' and
    itc_available=False must be preserved on the row (not silently overwritten to True)."""
    sb = MagicMock()
    run_id = "test-run-no-r37a-signal"

    gstr_db_row = {
        "id": "g-clean",
        "record_data": {
            "supplier_gstin": "27AABCU9603R1ZM",
            "supplier_name": "Test Supplier",
            "invoice_number": "INV-100",
            "invoice_date_norm": "2026-07-15",
            "taxable_value_paise": 10000000,
            "cgst_paise": 900000,
            "sgst_paise": 900000,
            "igst_paise": 0,
            "total_tax_paise": 1800000,
            "itc_available": False,
            "itc_reason": None,  # No reason provided
        },
    }

    pr_db_row = {
        "id": "p-clean",
        "record_data": {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-100",
            "invoice_date_norm": "2026-07-15",
            "taxable_value_paise": 10000000,
            "cgst_paise": 900000,
            "sgst_paise": 900000,
            "igst_paise": 0,
            "total_tax_paise": 1800000,
        },
    }

    sb.table().select().eq().limit().execute.return_value = MagicMock(count=1)
    sb.table().select().eq().range().execute.side_effect = [
        MagicMock(data=[gstr_db_row]),
        MagicMock(data=[pr_db_row]),
    ]

    payload = {
        "engine": {
            "matched": [
                {
                    "gstr_id": "g-clean",
                    "pr_id": "p-clean",
                    "match_confidence": 1.0,
                }
            ],
            "missed_itc": [],
            "wrongful_itc_risk": [],
        },
        "compliance": {},
        "decisions": {},
    }

    rows, ccounts, stats = build_outcome_rows(sb, run_id, payload)

    assert len(rows) == 1
    r = rows[0]
    assert r.category == "matched"
    assert r.rule37a_flag is False
    assert r.itc_available is False  # Must be preserved, NOT silently overwritten to True
    assert r.itc_reason is None
    assert ccounts["matched"] == 1
    assert ccounts["rule37_warnings"] == 0
    assert stats["matched_count"] == 1
    assert stats["rule37_warnings_count"] == 0


def test_outcomes_routes_blocked_credit_when_itc_unavailable_due_to_sec_17_5():
    """When is_itc_avail is False and itc_reason indicates Section 17(5) blocked credit,
    the row must route to category='blocked_credit'."""
    sb = MagicMock()
    run_id = "test-run-sec175-blocked"

    gstr_db_row = {
        "id": "g-blocked",
        "record_data": {
            "supplier_gstin": "27AABCU9603R1ZM",
            "supplier_name": "Test Supplier",
            "invoice_number": "INV-200",
            "invoice_date_norm": "2026-07-15",
            "taxable_value_paise": 10000000,
            "cgst_paise": 900000,
            "sgst_paise": 900000,
            "igst_paise": 0,
            "total_tax_paise": 1800000,
            "itc_available": False,
            "itc_reason": "Ineligible under Section 17(5) blocked credit",
        },
    }

    pr_db_row = {
        "id": "p-blocked",
        "record_data": {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-200",
            "invoice_date_norm": "2026-07-15",
            "taxable_value_paise": 10000000,
            "cgst_paise": 900000,
            "sgst_paise": 900000,
            "igst_paise": 0,
            "total_tax_paise": 1800000,
        },
    }

    sb.table().select().eq().limit().execute.return_value = MagicMock(count=1)
    sb.table().select().eq().range().execute.side_effect = [
        MagicMock(data=[gstr_db_row]),
        MagicMock(data=[pr_db_row]),
    ]

    payload = {
        "engine": {
            "matched": [
                {
                    "gstr_id": "g-blocked",
                    "pr_id": "p-blocked",
                    "match_confidence": 1.0,
                }
            ],
            "missed_itc": [],
            "wrongful_itc_risk": [],
        },
        "compliance": {},
        "decisions": {},
    }

    rows, ccounts, stats = build_outcome_rows(sb, run_id, payload)

    assert len(rows) == 1
    r = rows[0]
    assert r.category == "blocked_credit"
    assert r.match_status == "BLOCKED"
    assert r.blocked_credit_flag is True
    assert r.rule37a_flag is False
    assert r.itc_available is False
    assert ccounts["blocked_credit"] == 1
    assert ccounts["matched"] == 0
    assert ccounts["rule37_warnings"] == 0

