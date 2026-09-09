"""Unit tests for additive GSTR-3B `filed` summary on the API response helper."""

from __future__ import annotations

from app.parsers.gstr3b_parser import parse_gstr3b
from app.routers.reconciliation_api import (
    _filed_from_parsed,
    _gstr3b_row_to_response,
    _parse_filed_from_raw,
)


def _minimal_row(**overrides):
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "run_id": "22222222-2222-2222-2222-222222222222",
        "client_gstin": "27AABCM4162G1ZM",
        "tax_period": "2026-05",
        "overall_status": "MATCHED",
        "gstr3b_igst_claimed": 100,
        "gstr3b_cgst_claimed": 50,
        "gstr3b_sgst_claimed": 50,
        "gstr2b_igst_available": 100,
        "gstr2b_cgst_available": 50,
        "gstr2b_sgst_available": 50,
        "igst_difference": 0,
        "cgst_difference": 0,
        "sgst_difference": 0,
        "igst_status": "MATCHED",
        "cgst_status": "MATCHED",
        "sgst_status": "MATCHED",
        "outward_supply_total": 1180,
        "uploaded_at": "2026-07-18T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_filed_from_parsed_includes_by_source_and_secondary():
    parsed = parse_gstr3b({
        "gstin": "27AABCM4162G1ZM",
        "ret_period": "052026",
        "data": {
            "itcElg": {
                "itcAvl": [
                    {"ty": "IMPG", "iamt": 10, "camt": 0, "samt": 0, "csamt": 0},
                    {"ty": "All other ITC", "iamt": 0, "camt": 40, "samt": 40, "csamt": 0},
                ],
                "itcNet": {"iamt": 10, "camt": 40, "samt": 40, "csamt": 0},
            },
            "sup_details": {
                "osup_det": {"txval": 1000, "iamt": 100, "camt": 50, "samt": 50, "csamt": 0},
                "osup_zero": {"txval": 200, "iamt": 0, "csamt": 0},
            },
            "intr_ltfee": {
                "intr_details": {"iamt": 0, "camt": 1, "samt": 1, "csamt": 0},
                "ltfee_details": {"camt": 25, "samt": 25},
            },
        },
    })
    filed = _filed_from_parsed(parsed)
    assert filed is not None
    assert filed.outward_supply.taxable_value == 1000.0
    assert filed.outward_supply.cgst == 50.0
    assert filed.osup_zero.taxable_value == 200.0
    assert filed.itc_avl_by_source["IMPG"].igst == 10.0
    assert filed.itc_avl_by_source["OTH"].cgst == 40.0
    assert filed.late_fee.cgst == 25.0
    assert filed.interest_late_fee.cgst == 1.0


def test_row_to_response_uses_filed_parsed_without_raw():
    parsed = parse_gstr3b({
        "gstin": "27AABCM4162G1ZM",
        "ret_period": "052026",
        "data": {
            "itcElg": {"itcNet": {"iamt": 100, "camt": 50, "samt": 50, "csamt": 0}},
            "sup_details": {
                "osup_det": {"txval": 1000, "iamt": 180, "camt": 0, "samt": 0, "csamt": 0},
            },
        },
    })
    resp = _gstr3b_row_to_response(
        _minimal_row(),
        filed_parsed=parsed,
        client_gstin_id="cg-1",
    )
    assert resp.filed is not None
    assert resp.filed.outward_supply.igst == 180.0
    assert resp.client_gstin_id == "cg-1"
    assert resp.drc01c is not None
    assert resp.drc01c.threshold_status == "CLEAR"


def test_row_to_response_reparses_raw_gstr3b():
    raw = {
        "gstin": "27AABCM4162G1ZM",
        "ret_period": "052026",
        "data": {
            "itcElg": {
                "itcAvl": [{"ty": "OTH", "iamt": 5, "camt": 0, "samt": 0, "csamt": 0}],
                "itcNet": {"iamt": 5, "camt": 0, "samt": 0, "csamt": 0},
            },
            "sup_details": {
                "osup_det": {"txval": 10, "iamt": 1.8, "camt": 0, "samt": 0, "csamt": 0},
            },
        },
    }
    resp = _gstr3b_row_to_response(_minimal_row(raw_gstr3b=raw))
    assert resp.filed is not None
    assert resp.filed.itc_avl_by_source["OTH"].igst == 5.0


def test_missing_or_bad_raw_yields_filed_null():
    assert _parse_filed_from_raw(None) is None
    assert _parse_filed_from_raw("not-json") is None
    assert _parse_filed_from_raw({"gstin": "x"}) is None  # unsupported schema
    resp = _gstr3b_row_to_response(_minimal_row(raw_gstr3b=None))
    assert resp.filed is None
    assert resp.overall_status == "MATCHED"
