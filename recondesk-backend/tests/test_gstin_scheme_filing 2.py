"""Unit tests for GST scheme_type and filing_frequency integration across backend.

Tests:
1. Decision layer composition scheme gating (COMPOSITION_SCHEME_NO_ITC).
2. Multi-period wizard QRMP period slot generation mechanics.
3. GSTR-1 vs GSTR-3B tie-out QRMP timing suppression.
"""

from unittest.mock import MagicMock, patch
import pytest

from app.decisions.layer import _decision_for_row, populate_decisions
from app.reconciliation.gstr1_vs_3b import reconcile_gstr1_vs_3b, _extract_month_from_period
from app.services.multi_period_wizard import create_batch, is_gstr1_due_in_period


def test_decision_layer_composition_gating():
    """Composition scheme dealers cannot claim ITC -- suppress MISSED_ITC, WRONGFUL_ITC, RULE37, etc."""
    missed_row = {
        "is_missed_itc": True,
        "mismatch_type": "MISSED_ITC",
        "supplier_gstin": "27AAACB1234C1Z1",
        "itc_amount": 5000,
        "scheme_type": "composition",
    }
    decision = _decision_for_row(missed_row, scheme_type="composition")
    assert decision.rule == "COMPOSITION_SCHEME_NO_ITC"
    assert "Composition Scheme" in decision.what
    assert "Section 10(4)" in decision.why


def test_populate_decisions_composition_suppression():
    """populate_decisions must replace rule37 and section_175 decisions for composition filers."""
    rule37 = [{
        "supplier_gstin": "27AAACB1234C1Z1",
        "days_remaining": 0,
        "itc_at_risk_paise": 100000,
        "status": "OVERDUE",
    }]
    s175 = [{
        "supplier_gstin": "27AAACB1234C1Z1",
        "hsn_code": "8703",
        "category": "Motor vehicles",
    }]

    result = populate_decisions(
        [],
        scheme_type="composition",
        rule37=rule37,
        section_175_warnings=s175,
    )

    assert len(result["rule37"]) == 1
    assert result["rule37"][0]["decision_rule"] == "COMPOSITION_SCHEME_NO_ITC"

    assert len(result["section_175"]) == 1
    assert result["section_175"][0]["decision_rule"] == "COMPOSITION_SCHEME_NO_ITC"


def test_is_gstr1_due_in_period_qrmp():
    """Monthly filers require GSTR-1 every month; QRMP filers only in quarter-end months."""
    # Monthly
    assert is_gstr1_due_in_period("2025-04", "monthly") is True
    assert is_gstr1_due_in_period("2025-05", "monthly") is True
    assert is_gstr1_due_in_period("2025-06", "monthly") is True

    # QRMP
    assert is_gstr1_due_in_period("2025-04", "qrmp") is False  # Month 1 of Q1
    assert is_gstr1_due_in_period("2025-05", "qrmp") is False  # Month 2 of Q1
    assert is_gstr1_due_in_period("2025-06", "qrmp") is True   # Quarter-end Q1
    assert is_gstr1_due_in_period("2025-09", "qrmp") is True   # Quarter-end Q2
    assert is_gstr1_due_in_period("2025-12", "qrmp") is True   # Quarter-end Q3
    assert is_gstr1_due_in_period("2026-03", "qrmp") is True   # Quarter-end Q4


def test_extract_month_from_period():
    assert _extract_month_from_period("042025") == "04"
    assert _extract_month_from_period("2025-04") == "04"
    assert _extract_month_from_period("04-2025") == "04"
    assert _extract_month_from_period("122025") == "12"


def test_gstr1_vs_3b_qrmp_timing_suppression():
    """In non-quarter-end months (e.g. April 04), missing GSTR-1 is not flagged for QRMP filers."""
    parsed_3b = {
        "ret_period": "042025",
        "outward_supply": {
            "taxable_value": 100000.0,
            "igst": 18000.0,
            "cgst": 0.0,
            "sgst": 0.0,
        },
    }
    # For monthly filer, missing GSTR-1 produces variances
    monthly_res = reconcile_gstr1_vs_3b([], parsed_3b, filing_frequency="monthly")
    assert monthly_res.is_clean is False
    assert len(monthly_res.variances) > 0

    # For QRMP filer in April (month 04), GSTR-1 tie-out is suppressed
    qrmp_res = reconcile_gstr1_vs_3b([], parsed_3b, filing_frequency="qrmp")
    assert qrmp_res.is_clean is True
    assert len(qrmp_res.variances) == 0


def test_gstr1_vs_3b_qrmp_quarter_end_checked():
    """In quarter-end months (e.g. June 06), GSTR-1 tie-out IS run for QRMP filers."""
    parsed_3b = {
        "ret_period": "062025",
        "outward_supply": {
            "taxable_value": 100000.0,
            "igst": 18000.0,
            "cgst": 0.0,
            "sgst": 0.0,
        },
    }
    qrmp_res = reconcile_gstr1_vs_3b([], parsed_3b, filing_frequency="qrmp")
    assert qrmp_res.is_clean is False
    assert len(qrmp_res.variances) > 0


def test_qrmp_full_quarter_tie_out_flow():
    """Across a full quarter (Apr, May, Jun):
    - Apr (m1) & May (m2): No GSTR-3B slot / missing 3B flag; tie-out returns clean with 0 variances.
    - Jun (m3): Consolidated quarterly GSTR-3B + GSTR-2B tie-out runs and detects variances if mismatched.
    """
    sample_gstr1 = [{
        "invoice_number": "INV-101",
        "invoice_date": "2025-04-10",
        "taxable_amount_paise": 10000000,
        "igst_paise": 1800000,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
    }]
    parsed_3b_m1 = {"ret_period": "042025", "outward_supply": {"taxable_value": 100000.0, "igst": 18000.0}}
    parsed_3b_m2 = {"ret_period": "052025", "outward_supply": {"taxable_value": 50000.0, "igst": 9000.0}}
    parsed_3b_m3 = {"ret_period": "062025", "outward_supply": {"taxable_value": 300000.0, "igst": 54000.0}}

    # Month 1 (April) -> QRMP tie-out suppressed completely
    res_m1 = reconcile_gstr1_vs_3b(sample_gstr1, parsed_3b_m1, filing_frequency="qrmp")
    assert res_m1.is_clean is True
    assert len(res_m1.variances) == 0

    # Month 2 (May) -> QRMP tie-out suppressed completely
    res_m2 = reconcile_gstr1_vs_3b([], parsed_3b_m2, filing_frequency="qrmp")
    assert res_m2.is_clean is True
    assert len(res_m2.variances) == 0

    # Month 3 (June - quarter-end) -> Tie-out executed against GSTR-3B quarterly return
    res_m3 = reconcile_gstr1_vs_3b(sample_gstr1, parsed_3b_m3, filing_frequency="qrmp")
    assert res_m3.is_clean is False
    assert len(res_m3.variances) > 0
