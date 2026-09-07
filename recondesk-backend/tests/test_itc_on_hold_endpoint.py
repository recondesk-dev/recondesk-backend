import pytest
from collections import Counter
from unittest.mock import MagicMock
from app.routers.reconciliation_api import (
    _build_matched_pair_records,
    _build_itc_on_hold_records,
)
from app.services.reconciliation_outcomes import OutcomeRow


def _make_outcome_row(row_id: str, category: str, match_status: str, amount_paise: int = 100000, **kwargs) -> OutcomeRow:
    return OutcomeRow(
        id=row_id,
        category=category,
        supplier_gstin=kwargs.get("supplier_gstin", "27AABCU9603R1ZM"),
        invoice_number=kwargs.get("invoice_number", "INV-001"),
        invoice_date=kwargs.get("invoice_date", "2026-08-01"),
        match_status=match_status,
        taxable_value_diff=0,
        igst_diff=0,
        cgst_diff=0,
        sgst_diff=0,
        total_tax_diff_paise=0,
        decision_what=kwargs.get("decision_what", "What text"),
        decision_why=kwargs.get("decision_why", "Why text"),
        decision_next=kwargs.get("decision_next", "Next text"),
        rule37_flag=kwargs.get("rule37_flag", False),
        blocked_credit_flag=kwargs.get("blocked_credit_flag", False),
        late_filing_flag=kwargs.get("late_filing_flag", False),
        is_credit_note=kwargs.get("is_credit_note", False),
        amount=amount_paise,
        supplier_name=kwargs.get("supplier_name", "Supplier A"),
        matched_pr_id=kwargs.get("matched_pr_id", "pr-1"),
        match_confidence=kwargs.get("match_confidence", 100.0),
        rule37a_flag=kwargs.get("rule37a_flag", False),
        itc_available=kwargs.get("itc_available", True),
        itc_reason=kwargs.get("itc_reason", None),
        compared_fields=None,
    )


def test_build_matched_pair_records_filters_out_ineligible_rows(monkeypatch):
    mock_sb = MagicMock()
    engine = {
        "matched": [
            {"gstr_id": "g-1", "pr_id": "p-1"},
            {"gstr_id": "g-2", "pr_id": "p-2"},
            {"gstr_id": "g-3", "pr_id": "p-3"},
        ]
    }
    payload = {"engine": engine}

    outcomes = [
        _make_outcome_row("pm:g-1", "matched", "MATCHED", 100000, itc_available=True),
        _make_outcome_row("pm:g-2", "rule37_warnings", "RULE37A", 200000, itc_available=False, rule37a_flag=True),
        _make_outcome_row("pm:g-3", "blocked_credit", "BLOCKED", 300000, itc_available=False, blocked_credit_flag=True),
    ]

    monkeypatch.setattr("app.services.reconciliation_outcomes.build_outcome_rows", lambda sb, rid, p: (outcomes, {}, {}))
    monkeypatch.setattr("app.services.reconciliation_outcomes.load_gstr_map", lambda sb, rid: {
        "g-1": {"matcher": {"total_tax_paise": 100000}},
        "g-2": {"matcher": {"total_tax_paise": 200000}},
        "g-3": {"matcher": {"total_tax_paise": 300000}},
    })
    monkeypatch.setattr("app.services.reconciliation_outcomes.load_pr_map", lambda sb, rid: {
        "p-1": {"matcher": {"total_tax_paise": 100000}},
        "p-2": {"matcher": {"total_tax_paise": 200000}},
        "p-3": {"matcher": {"total_tax_paise": 300000}},
    })

    pairs = _build_matched_pair_records(
        mock_sb,
        rid="run-test",
        payload=payload,
        note_counts=Counter(),
        fetch_review_required=False,
    )

    # Only g-1 should be present in matched pairs
    assert len(pairs) == 1
    api_row, orow = pairs[0]
    assert api_row["id"] == "pm:g-1"
    assert orow.category == "matched"


def test_build_itc_on_hold_records(monkeypatch):
    mock_sb = MagicMock()
    outcomes = [
        _make_outcome_row("pm:g-1", "matched", "MATCHED", 100000, itc_available=True),
        _make_outcome_row(
            "pm:g-2", "rule37_warnings", "RULE37A", 200000,
            itc_available=False, rule37a_flag=True,
            decision_what="What R37A", decision_why="Why R37A", decision_next="Next R37A"
        ),
        _make_outcome_row(
            "pm:g-3", "blocked_credit", "BLOCKED", 300000,
            itc_available=False, blocked_credit_flag=True, itc_reason="Motor vehicles",
            decision_what="What S17", decision_why="Why S17", decision_next="Next S17"
        ),
    ]

    monkeypatch.setattr("app.services.reconciliation_outcomes.build_outcome_rows", lambda sb, rid, p: (outcomes, {}, {}))
    monkeypatch.setattr("app.services.reconciliation_outcomes.load_gstr_map", lambda sb, rid: {
        "g-1": {"matcher": {"total_tax_paise": 100000}},
        "g-2": {"matcher": {"total_tax_paise": 200000}},
        "g-3": {"matcher": {"total_tax_paise": 300000}},
    })
    monkeypatch.setattr("app.services.reconciliation_outcomes.load_pr_map", lambda sb, rid: {
        "p-1": {"matcher": {"total_tax_paise": 100000}},
        "p-2": {"matcher": {"total_tax_paise": 200000}},
        "p-3": {"matcher": {"total_tax_paise": 300000}},
    })

    hold_rows = _build_itc_on_hold_records(
        mock_sb,
        rid="run-test",
        payload={},
        note_counts=Counter(),
    )

    assert len(hold_rows) == 2
    r37a = next(r for r in hold_rows if r["id"] == "pm:g-2")
    assert r37a["hold_type"] == "RULE37A"
    assert r37a["rule37a_flag"] is True
    assert r37a["amount"] == 2000.0
    assert r37a["decision_what"] == "What R37A"

    s17 = next(r for r in hold_rows if r["id"] == "pm:g-3")
    assert s17["hold_type"] == "BLOCKED_CREDIT"
    assert s17["blocked_credit_flag"] is True
    assert s17["amount"] == 3000.0
    assert s17["itc_reason"] == "Motor vehicles"
