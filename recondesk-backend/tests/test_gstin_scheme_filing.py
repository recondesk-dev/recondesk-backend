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
