"""Unit tests for the audit observations aggregation layer."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from app.audit.observation_builder import (
    build_observations,
    compute_financial_impact,
)
from app.audit.observation_rules import OBSERVATION_RULES, RULE37_INTEREST_RATE_PA
from app.rules.gstr1_mismatch_rules import MismatchType


def test_observation_rules_keys_match_engine_enums():
    """Catalogue keys for G1M1–G1M10 must match MismatchType values exactly."""
    expected = {
        MismatchType.MISSING_INVOICE.value,
        MismatchType.EXTRA_INVOICE.value,
        MismatchType.AMOUNT_MISMATCH.value,
        MismatchType.WRONG_CLASSIFICATION.value,
        MismatchType.RATE_MISMATCH.value,
        MismatchType.PERIOD_MISMATCH.value,
        MismatchType.INVALID_GSTIN.value,
        MismatchType.INVOICE_SERIES_ISSUE.value,
        MismatchType.HSN_RATE_ISSUE.value,
        MismatchType.DOCUMENTS_ISSUED_SUMMARY.value,
    }
    for key in expected:
        assert key in OBSERVATION_RULES, f"missing catalogue entry for {key}"


def test_itc_plus_interest_formula():
    # ITC ₹1000, 365 days overdue → interest = 1000 * 0.18 * 1 = ₹180
    row = {"itc_at_risk_paise": 100_000, "days_remaining": -365}
    impact = compute_financial_impact("RULE37_UNPAID_180", row)
    assert impact == pytest.approx(1000.0 + 1000.0 * RULE37_INTEREST_RATE_PA, abs=0.01)


def test_itc_plus_interest_from_claim_period_proxy():
    """Claim period 2026-06 → GSTR-3B due 2026-07-20; 365 days later → full year interest."""
    from datetime import date

    from app.audit.observation_builder import _itc_plus_interest_rupees

    row = {
        "itc_at_risk_paise": 100_000,
        "itc_claimed_period": "2026-06",
        # Deadline-based days would understate — claim proxy must win.
        "days_remaining": -10,
    }
    impact = _itc_plus_interest_rupees(row, today=date(2027, 7, 20))
    assert impact == pytest.approx(1000.0 + 1000.0 * RULE37_INTEREST_RATE_PA, abs=0.01)


def test_gstr3b_claim_date_proxy():
    from datetime import date

    from app.audit.observation_builder import _gstr3b_claim_date_proxy

    assert _gstr3b_claim_date_proxy("2026-06") == date(2026, 7, 20)
    assert _gstr3b_claim_date_proxy("2026-06-01") == date(2026, 7, 20)
    assert _gstr3b_claim_date_proxy("2025-12") == date(2026, 1, 20)


def test_tax_differential_from_mismatch_fields():
    row = {"tax_diff_paise": 18_000}
    assert compute_financial_impact("G1M3_AMOUNT_MISMATCH", row) == 180.0


def test_none_impact_returns_null():
    assert compute_financial_impact("G1M4_WRONG_CLASSIFICATION", {"total_tax_paise": 100}) is None


def _gstr1_payload() -> dict[str, Any]:
    return {
        "success": True,
        "mismatches": [
            {
                "mismatch_type": "G1M1_MISSING_INVOICE",
                "decision_why": "Invoice INV-001 not filed in GSTR-1.",
                "decision_next": "Add INV-001 to GSTR-1 before filing.",
                "invoice_number": "INV-001",
                "total_tax_paise": 18_000,
            },
            {
                "mismatch_type": "G1M3_AMOUNT_MISMATCH",
                "decision_why": "Taxable value differs between books and GSTR-1.",
                "decision_next": "Reconcile and amend GSTR-1.",
                "invoice_number": "INV-002",
                "tax_diff_paise": 9_000,
            },
            {
                "mismatch_type": "G1M4_WRONG_CLASSIFICATION",
                "decision_why": "B2B vs B2C classification mismatch.",
                "decision_next": "Correct the table in GSTR-1.",
                "invoice_number": "INV-003",
            },
            {
                # Not in OBSERVATION_RULES — must be skipped
                "mismatch_type": "G1M11_AMENDMENT_REQUIRED",
                "invoice_number": "INV-AMD",
                "total_tax_paise": 500,
            },
        ],
        "tie_out": {
            "mismatch_decisions": [
                {
                    "decision_rule": "G1_3B_TIEOUT",
                    "decision_why": "IGST liability differs between GSTR-1 and 3B.",
                    "decision_next": "Align Table 3.1 with GSTR-1.",
                    "field": "igst",
                    "diff_paise": 50_000,
                }
            ]
        },
    }


def test_build_observations_from_gstr1_run():
    fake_row = {
        "id": "g1-run-1",
        "client_gstin_id": "client-1",
        "result_payload": _gstr1_payload(),
    }
    with (
        patch(
            "app.audit.observation_builder.get_gstr1_run",
            return_value=fake_row,
        ),
        patch(
            "app.audit.observation_builder.ro.load_payload",
            return_value={},
        ),
    ):
        out = build_observations("g1-run-1", sb=object())  # type: ignore[arg-type]

    assert out is not None
    assert out["run_type"] == "gstr1"
    assert out["summary"]["critical_count"] == 1  # G1M1
    assert out["summary"]["high_count"] == 2  # G1M3 + tie-out
    assert out["summary"]["medium_count"] == 1  # G1M4
    assert out["summary"]["low_count"] == 0

    by_rule = {o["source_rule"]: o for o in out["observations"]}
    assert "G1M11_AMENDMENT_REQUIRED" not in by_rule
    assert by_rule["G1M1_MISSING_INVOICE"]["financial_impact"] == 180.0
    assert by_rule["G1M1_MISSING_INVOICE"]["description"].startswith("Invoice INV-001")
    assert by_rule["G1M1_MISSING_INVOICE"]["recommendation"].startswith("Add INV-001")
    assert by_rule["G1M1_MISSING_INVOICE"]["linked_invoice_ids"] == ["INV-001"]
    assert by_rule["G1M3_AMOUNT_MISMATCH"]["financial_impact"] == 90.0
    assert by_rule["G1M4_WRONG_CLASSIFICATION"]["financial_impact"] is None
    tie = by_rule["GSTR1_VS_3B_LIABILITY_MISMATCH"]
    assert tie["financial_impact"] == 500.0
    assert tie["affected_count"] == 1
    assert tie["linked_fields"] == ["igst"]
    assert "linked_invoice_ids" not in tie
    # 180 + 90 + 500
    assert out["summary"]["total_financial_impact"] == 770.0


def test_build_observations_from_purchase_payload():
    purchase_payload = {
        "engine": {},
        "compliance": {
            "rule37": [
                {
                    "pr_id": "pr-1",
                    "invoice_number": "P-100",
                    "supplier_gstin": "27AAAAA0000A1Z5",
                    "status": "OVERDUE_UNPAID",
                    "days_remaining": -100,
                    "itc_at_risk_paise": 10_000,  # ₹100
                },
                {
                    "pr_id": "pr-2",
                    "invoice_number": "P-101",
                    "status": "WARNING_30_DAYS",
                    "days_remaining": 20,
                    "itc_at_risk_paise": 5_000,
                },
            ],
            "section_17_5": [
                {
                    "invoice_number": "P-200",
                    "supplier_gstin": "27BBBBB0000B1Z5",
                    "estimated_itc_amount": 250.0,
                    "reason": "Motor vehicle",
                }
            ],
        },
        "decisions": {
            "rule37": [
                {
                    "pr_id": "pr-1",
                    "decision_why": "Payment overdue beyond 180 days.",
                    "decision_next": "Reverse ITC under Rule 37.",
                }
            ],
            "section_175": [
                {
                    "invoice_number": "P-200",
                    "supplier_gstin": "27BBBBB0000B1Z5",
                    "decision_why": "ITC blocked under Section 17(5).",
                    "decision_next": "Reverse ineligible ITC in GSTR-3B.",
                }
            ],
        },
    }

    with (
        patch(
            "app.audit.observation_builder.get_gstr1_run",
            return_value=None,
        ),
        patch(
            "app.audit.observation_builder.ro.load_payload",
            return_value=purchase_payload,
        ),
    ):
        out = build_observations("purchase-run-1", sb=object())  # type: ignore[arg-type]

    assert out is not None
    assert out["run_type"] == "purchase"
    by_rule = {o["source_rule"]: o for o in out["observations"]}
    assert set(by_rule) == {"RULE37_UNPAID_180", "BLOCKED_ITC_17_5"}
    r37 = by_rule["RULE37_UNPAID_180"]
    assert r37["affected_count"] == 1
    assert r37["linked_invoice_ids"] == ["pr-1"]
    assert r37["description"].startswith("Payment overdue beyond 180 days.")
    assert "lower bound" in r37["description"]
    assert "180-day due date" in r37["financial_impact_note"]
    # 100 + 100*0.18*100/365  (deadline-based lower bound, not full Rule 37(3))
    expected_r37 = round(100.0 + 100.0 * 0.18 * (100 / 365.0), 2)
    assert r37["financial_impact"] == expected_r37
    assert by_rule["BLOCKED_ITC_17_5"]["financial_impact"] == 250.0
    assert out["summary"]["critical_count"] == 2
    assert out["summary"]["total_financial_impact"] == round(expected_r37 + 250.0, 2)


def test_build_observations_rule37_with_claim_period_skips_lower_bound_note():
    """When itc_claimed_period is stamped, no deadline lower-bound caveat."""
    from datetime import date as real_date

    purchase_payload = {
        "success": True,
        "compliance": {
            "rule37": [
                {
                    "pr_id": "pr-1",
                    "invoice_number": "P-100",
                    "status": "OVERDUE_UNPAID",
                    "days_remaining": -100,
                    "itc_at_risk_paise": 10_000,
                    "itc_claimed_period": "2026-06",
                },
            ],
            "section_17_5": [],
        },
        "decisions": {
            "rule37": [
                {
                    "pr_id": "pr-1",
                    "decision_why": "Payment overdue beyond 180 days.",
                    "decision_next": "Reverse ITC under Rule 37.",
                }
            ],
            "section_175": [],
        },
    }

    class _PinnedDate(real_date):
        @classmethod
        def today(cls):  # type: ignore[override]
            return real_date(2026, 8, 20)

    with (
        patch(
            "app.audit.observation_builder.get_gstr1_run",
            return_value=None,
        ),
        patch(
            "app.audit.observation_builder.ro.load_payload",
            return_value=purchase_payload,
        ),
        patch("app.audit.observation_builder.date", _PinnedDate),
    ):
        out = build_observations("purchase-run-claim", sb=object())  # type: ignore[arg-type]

    assert out is not None
    r37 = next(o for o in out["observations"] if o["source_rule"] == "RULE37_UNPAID_180")
    assert "lower bound" not in r37["description"]
    assert "financial_impact_note" not in r37
    # claim 2026-07-20 → today 2026-08-20 = 31 days
    expected = round(100.0 + 100.0 * 0.18 * (31 / 365.0), 2)
    assert r37["financial_impact"] == expected


def test_build_observations_missing_run_returns_none():
    with (
        patch(
            "app.audit.observation_builder.get_gstr1_run",
            return_value=None,
        ),
        patch(
            "app.audit.observation_builder.ro.load_payload",
            return_value={},
        ),
    ):
        assert build_observations("missing", sb=object()) is None  # type: ignore[arg-type]
