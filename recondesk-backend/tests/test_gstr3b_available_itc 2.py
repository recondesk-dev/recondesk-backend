"""Adversarial / ground-truth tests for GSTR-3B vs GSTR-2B available ITC."""

from __future__ import annotations

from app.services.gstr3b_reconciliation import (
    accumulate_gstr2b_available_itc,
    compute_drc01c_threshold,
)
from app.services.gstr9c_itc_fy_rollup import periods_match_yyyy_mm


def test_periods_match_yyyy_mm_accepts_run_date_vs_portal_month():
    """Wizard stores YYYY-MM-01; portal 3B emits YYYY-MM — must not 422."""
    assert periods_match_yyyy_mm("2026-05", "2026-05-01") is True
    assert periods_match_yyyy_mm("052026", "2026-05-01") is True
    assert periods_match_yyyy_mm("2026-05", "2026-06-01") is False
    assert periods_match_yyyy_mm("2026-05", "2026-05") is True


def test_available_itc_skips_itcavl_n():
    records = [
        {
            "doc_type": "INVOICE",
            "itc_available": True,
            "items": [{"igst_paise": 10_000, "cgst_paise": 0, "sgst_paise": 0}],
        },
        {
            "doc_type": "INVOICE",
            "itc_available": False,
            "items": [{"igst_paise": 99_000, "cgst_paise": 0, "sgst_paise": 0}],
        },
    ]
    out = accumulate_gstr2b_available_itc(records)
    assert out == {"igst": 100.0, "cgst": 0.0, "sgst": 0.0}


def test_available_itc_credit_note_reduces_total():
    """Portal CDNR taxes are positive; available ITC must subtract them."""
    records = [
        {
            "doc_type": "INVOICE",
            "itc_available": True,
            "items": [
                {"igst_paise": 0, "cgst_paise": 50_000, "sgst_paise": 50_000},
            ],
        },
        {
            "doc_type": "CREDIT_NOTE",
            "itc_available": True,
            "items": [
                {"igst_paise": 0, "cgst_paise": 10_000, "sgst_paise": 10_000},
            ],
        },
    ]
    out = accumulate_gstr2b_available_itc(records)
    assert out == {"igst": 0.0, "cgst": 400.0, "sgst": 400.0}


def test_available_itc_invoice_level_paise_when_no_items():
    records = [
        {
            "doc_type": "INVOICE",
            "itc_available": True,
            "items": [],
            "igst_paise": 25_000,
            "cgst_paise": 0,
            "sgst_paise": 0,
        }
    ]
    out = accumulate_gstr2b_available_itc(records)
    assert out == {"igst": 250.0, "cgst": 0.0, "sgst": 0.0}


def test_credit_note_inflation_would_mask_drc01c_without_sign_fix():
    """Regression: treating CN as +available can hide a real DRC-01C overclaim."""
    # Claimed ₹40L; invoices ₹10L; CN ₹5L (positive in portal).
    # Wrong (old): available = 15L → excess 25L → not > 25L → no trigger.
    # Correct: available = 5L → excess 35L and >20% → trigger.
    claimed = 4_000_000.0
    wrong_available = 1_500_000.0
    correct_available = 500_000.0

    wrong = compute_drc01c_threshold(claimed, wrong_available)
    right = compute_drc01c_threshold(claimed, correct_available)
    assert wrong["triggers_drc01c"] is False
    assert right["triggers_drc01c"] is True

    records = [
        {
            "doc_type": "INVOICE",
            "itc_available": True,
            "items": [{"igst_paise": 100_000_000, "cgst_paise": 0, "sgst_paise": 0}],
        },
        {
            "doc_type": "CREDIT_NOTE",
            "itc_available": True,
            "items": [{"igst_paise": 50_000_000, "cgst_paise": 0, "sgst_paise": 0}],
        },
    ]
    avail = accumulate_gstr2b_available_itc(records)
    assert avail["igst"] == correct_available
    assert compute_drc01c_threshold(claimed, avail["igst"])["triggers_drc01c"] is True
