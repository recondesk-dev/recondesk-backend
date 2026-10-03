from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import pytest

from app.matching.generic_matcher import (
    SALES_MATCH_CONFIG,
    generic_match_pair,
)
from app.rules.gstr1_mismatch_rules import (
    MismatchType,
    classify_all_mismatches,
    classify_date_mismatch,
)
from app.rules.gstr1_rules import (
    GSTR1_INVOICE_DATE_TOLERANCE_DAYS,
    get_gstr1_rules,
)
from app.routers.gstr1_reconcile import (
    _categorize_mismatch,
    _is_sr_b2cs_record,
    reconcile_b2cs_aggregate,
)


def test_canonical_gstr1_date_tolerance_constant():
    """Ensure canonical date tolerance is 2 days across rules, configs, and instances."""
    assert GSTR1_INVOICE_DATE_TOLERANCE_DAYS == 2
    assert SALES_MATCH_CONFIG.date_tolerance_days == 2
    rules = get_gstr1_rules("2026-09")
    assert rules.invoice_date_tolerance_days == 2


def test_date_diff_0_exact_match():
    """Exact date match emits Exact match found with exact compared_fields."""
    sr = {
        "invoice_number": "INV001",
        "invoice_number_normalized": "INV001",
        "gstin": "27ABCDE1234F1Z5",
        "taxable_amount_paise": 100000,
        "total_amount_paise": 118000,
        "invoice_date": "2026-09-10",
        "igst_paise": 18000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    g1 = {
        "invoice_number": "INV001",
        "invoice_number_normalized": "INV001",
        "recipient_gstin": "27ABCDE1234F1Z5",
        "taxable_amount_paise": 100000,
        "total_amount_paise": 118000,
        "invoice_date": "2026-09-10",
        "igst_paise": 18000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1
    assert res.decision_what == "Exact match found"
    assert res.review_reason is None
    date_field = next(f for f in res.compared_fields if f["field_name"] == "date")
    assert date_field["match_type"] == "exact"


def test_date_diff_within_tolerance_message_and_compared_fields():
    """+2 days diff matches within configured tolerance and formats dynamic message."""
    sr = {
        "invoice_number": "INV002",
        "invoice_number_normalized": "INV002",
        "gstin": "27ABCDE1234F1Z5",
        "taxable_amount_paise": 100000,
        "total_amount_paise": 118000,
        "invoice_date": "2026-09-10",
        "igst_paise": 18000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    g1 = {
        "invoice_number": "INV002",
        "invoice_number_normalized": "INV002",
        "recipient_gstin": "27ABCDE1234F1Z5",
        "taxable_amount_paise": 100000,
        "total_amount_paise": 118000,
        "invoice_date": "2026-09-12",  # +2 days
        "igst_paise": 18000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1
    assert res.requires_human_review is False
    assert res.decision_what == "Matched within date tolerance"
    assert "date difference is +2 days (within 2-day tolerance)" in res.decision_why
    assert res.review_reason == "DATE_TOLERANCE_MATCH"
    assert any("diff=+2 days" in d for d in res.discrepancies)
    date_field = next(f for f in res.compared_fields if f["field_name"] == "date")
    assert date_field["match_type"] == "tolerance"


def test_date_diff_outside_tolerance_routes_to_review():
    """+6 days diff must NOT auto-clear; routes to Review Required with DATE_OUTSIDE_TOLERANCE."""
    sr = {
        "invoice_number": "INV003",
        "invoice_number_normalized": "INV003",
        "gstin": "27ABCDE1234F1Z5",
        "taxable_amount_paise": 100000,
        "total_amount_paise": 118000,
        "invoice_date": "2026-09-10",
        "igst_paise": 18000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    g1 = {
        "invoice_number": "INV003",
        "invoice_number_normalized": "INV003",
        "recipient_gstin": "27ABCDE1234F1Z5",
        "taxable_amount_paise": 100000,
        "total_amount_paise": 118000,
        "invoice_date": "2026-09-16",  # +6 days
        "igst_paise": 18000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason == "DATE_OUTSIDE_TOLERANCE"
    assert "minor amount difference" not in res.decision_what.lower()
    assert "Invoice date difference outside tolerance (+6 days)" in res.decision_what
    assert "exceeds 2-day tolerance" in res.decision_why


def test_classify_date_mismatch_rule_and_category():
    """classify_date_mismatch flags +6 days and routes to review_required category."""
    sr = {
        "invoice_number": "INV004",
        "invoice_date": "2026-09-05",
    }
    g1 = {
        "invoice_number": "INV004",
        "invoice_date": "2026-09-11",  # +6 days
    }
    mm = classify_date_mismatch(sr, g1, tolerance_days=2)
    assert mm is not None
    assert mm.mismatch_type == MismatchType.DATE_OUTSIDE_TOLERANCE
    assert mm.rule_id == "G1M_012"
    assert mm.details["requires_review"] is True
    assert _categorize_mismatch(mm) == "review_required"


def test_credit_note_signed_tax_structure_match():
    """Credit Note negative values in SR must not trigger false tax_structure mismatch."""
    sr_cn = {
        "invoice_number": "CN/2026/001",
        "invoice_number_normalized": "CN2026001",
        "document_type": "CREDIT_NOTE",
        "gstin": "29ABCDE1234F1Z5",
        "taxable_amount_paise": -100000,
        "total_amount_paise": -118000,
        "invoice_date": "2026-09-15",
        "igst_paise": -18000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    g1_cdnr = {
        "invoice_number": "CN/2026/001",
        "invoice_number_normalized": "CN2026001",
        "document_type": "CREDIT_NOTE",
        "recipient_gstin": "29ABCDE1234F1Z5",
        "taxable_amount_paise": 100000,
        "total_amount_paise": 118000,
        "invoice_date": "2026-09-15",
        "igst_paise": 18000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    res = generic_match_pair(sr_cn, g1_cdnr, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert not any("tax_structure" in d for d in res.discrepancies)
    assert res.financial_status in ("Exact", "Round-off")


def test_credit_note_intra_state_signed_tax_structure_match():
    """Intra-state Credit Note negative CGST/SGST in SR must match GSTR-1 without tax_structure error."""
    sr_cn = {
        "invoice_number": "CN/2026/002",
        "invoice_number_normalized": "CN2026002",
        "document_type": "CREDIT_NOTE",
        "gstin": "27ABCDE1234F1Z5",
        "taxable_amount_paise": -100000,
        "total_amount_paise": -118000,
        "invoice_date": "2026-09-15",
        "igst_paise": 0,
        "cgst_paise": -9000,
        "sgst_paise": -9000,
    }
    g1_cdnr = {
        "invoice_number": "CN/2026/002",
        "invoice_number_normalized": "CN2026002",
        "document_type": "CREDIT_NOTE",
        "recipient_gstin": "27ABCDE1234F1Z5",
        "taxable_amount_paise": 100000,
        "total_amount_paise": 118000,
        "invoice_date": "2026-09-15",
        "igst_paise": 0,
        "cgst_paise": 9000,
        "sgst_paise": 9000,
    }
    res = generic_match_pair(sr_cn, g1_cdnr, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert not any("tax_structure" in d for d in res.discrepancies)


def test_b2cs_unaccounted_invoice_diagnostics_emitted():
    """reconcile_b2cs_aggregate must emit unaccounted invoice numbers in result and mismatches."""
    sr_records = [
        {
            "invoice_number": "B2CS-001",
            "place_of_supply": "29-Karnataka",
            "rate": 18.0,
            "taxable_amount_paise": 100000,
            "igst_paise": 18000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
        },
        {
            "invoice_number": "B2CS-002",
            "place_of_supply": "29-Karnataka",
            "rate": 18.0,
            "taxable_amount_paise": 200000,
            "igst_paise": 36000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
        },
    ]
    g1_b2cs = [
        {
            "pos": "29",
            "rt": 18.0,
            "sply_ty": "INTER",
            "taxable_amount_paise": 500000,  # deliberate mismatch
            "igst_paise": 90000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
        }
    ]
    res = reconcile_b2cs_aggregate(sr_records, g1_b2cs, supplier_gstin="27ISKPK1273H1ZF")
    assert res.status == "MISMATCH"
    assert res.unaccounted_invoice_count == 2
    assert "B2CS-001" in res.unaccounted_invoice_numbers
    assert "B2CS-002" in res.unaccounted_invoice_numbers
    d = res.to_dict()
    assert "unaccounted_invoice_numbers" in d
    assert len(d["unaccounted_invoice_numbers"]) == 2
    # Check mismatch result details
    assert len(res.mismatches) == 1
    assert "B2CS-001" in res.mismatches[0].details["unaccounted_invoice_numbers"]
    assert "B2CS-002" in res.mismatches[0].details["unaccounted_invoice_numbers"]


def test_b2cl_b2cs_threshold_rule():
    """Verify statutory threshold logic for Sep 2026 (post Aug 2024 cutoff: ₹1,00,000)."""
    rules = get_gstr1_rules("2026-09")
    assert rules.b2cl_threshold_paise == 10_000_000

    # Exactly 1,00,000 paise (₹1,00,000.00) is B2CS
    assert rules.is_b2cs(inv_val_paise=10_000_000, is_interstate=True, is_registered=False) is True
    assert rules.is_b2cl(inv_val_paise=10_000_000, is_interstate=True, is_registered=False) is False

    # 1,00,001 paise (₹1,00,000.01) is B2CL
    assert rules.is_b2cl(inv_val_paise=10_000_100, is_interstate=True, is_registered=False) is True
    assert rules.is_b2cs(inv_val_paise=10_000_100, is_interstate=True, is_registered=False) is False
