"""Rule 37 summary coverage / pending-verification helpers."""

from __future__ import annotations

from collections import Counter
from datetime import date
from unittest.mock import MagicMock

from app.routers.reconciliation_api import (
    _build_rule37_summary_payload,
    _rule37_coverage_from_payload,
    _rule37_pending_verification_from_payload,
)
from app.services.reconciliation_payload_store import (
    build_run_summary_metrics,
    build_stored_results_payload,
)
from app.services.rule37_tracker import (
    PENDING_VERIFICATION,
    check_rule_37_compliance,
)


def test_pending_verification_carries_potential_itc_exposure():
    pr = {
        "id": "pv-1",
        "supplier_gstin": "27AAAAA0000A1Z5",
        "invoice_number_normalized": "INV-1",
        "invoice_date": "2020-01-01",
        "total_tax_paise": 18_000,
        "taxable_amount_paise": 100_000,
        "invoice_value_paise": 118_000,
        "itc_claimed": True,
        # blank payment_status → PENDING_VERIFICATION past 180 days
    }
    results = check_rule_37_compliance([pr], [], today=date(2025, 9, 30))
    assert len(results) == 1
    assert results[0]["status"] == PENDING_VERIFICATION
    assert results[0]["itc_at_risk_paise"] == 0
    assert results[0]["potential_itc_paise"] == 18_000
    assert results[0]["total_tax_paise"] == 18_000


def test_coverage_from_payload_prefers_compliance_blob():
    payload = {
        "compliance": {
            "rule37_coverage": {
                "claimed_invoice_count": 70,
                "payment_status_known_count": 12,
                "payment_status_unknown_count": 58,
            }
        }
    }
    cov = _rule37_coverage_from_payload(payload)
    assert cov["coverage_available"] is True
    assert cov["claimed_invoice_count"] == 70
    assert cov["payment_status_known_count"] == 12
    assert cov["payment_status_unknown_count"] == 58


def test_coverage_falls_back_to_run_summary():
    payload = {"compliance": {}}
    rs = {
        "rule37_claimed_invoice_count": 40,
        "rule37_payment_status_known_count": 40,
        "rule37_payment_status_unknown_count": 0,
    }
    cov = _rule37_coverage_from_payload(payload, run_summary=rs)
    assert cov["coverage_available"] is True
    assert cov["claimed_invoice_count"] == 40
    assert cov["payment_status_known_count"] == 40
    assert cov["payment_status_unknown_count"] == 0


def test_coverage_unavailable_for_legacy_runs():
    cov = _rule37_coverage_from_payload({"compliance": {}})
    assert cov["coverage_available"] is False
    assert cov["claimed_invoice_count"] == 0


def test_pending_verification_list_from_payload():
    payload = {
        "compliance": {
            "rule37_pending_verification": [
                {
                    "pr_id": "a",
                    "potential_itc_paise": 1000,
                    "status": PENDING_VERIFICATION,
                },
                {
                    "pr_id": "b",
                    "total_tax_paise": 2000,
                    "status": PENDING_VERIFICATION,
                },
            ]
        }
    }
    rows = _rule37_pending_verification_from_payload(payload)
    assert len(rows) == 2


def test_stored_payload_includes_rule37_coverage():
    slim = build_stored_results_payload(
        matched=[],
        missed_itc=[],
        wrongful_itc_risk=[],
        rule37=[],
        section_175_warnings=[],
        credit_note_adjustment={},
        decision_payload={"rows": []},
        matching_version="1.0.0",
        rules_version="1.0.0",
        decision_version="1.0.0",
        rule37_pending_verification=[
            {"pr_id": "x", "potential_itc_paise": 500, "itc_at_risk_paise": 0}
        ],
        rule37_coverage={
            "claimed_invoice_count": 10,
            "payment_status_known_count": 3,
            "payment_status_unknown_count": 7,
        },
    )
    assert slim["compliance"]["rule37_coverage"]["claimed_invoice_count"] == 10
    assert len(slim["compliance"]["rule37_pending_verification"]) == 1


def test_run_summary_metrics_include_coverage_scalars():
    summary = build_run_summary_metrics(
        n_gstr=10,
        n_pr=10,
        matched_count=8,
        missed_itc_count=1,
        wrongful_count=1,
        itc_missed=100,
        wrongful_paise=200,
        rule37_itc_paise=0,
        itc_at_risk_total=100,
        late_itc_paise=0,
        late_match_count=0,
        rule37_pending_verification_count=5,
        rule37_pending_verification_paise=50_000,
        rule37_claimed_invoice_count=70,
        rule37_payment_status_known_count=12,
        rule37_payment_status_unknown_count=58,
    )
    assert summary["rule37_claimed_invoice_count"] == 70
    assert summary["rule37_payment_status_known_count"] == 12
    assert summary["rule37_payment_status_unknown_count"] == 58
    assert summary["rule37_pending_verification_count"] == 5
    assert summary["rule37_pending_verification_paise"] == 50_000


def test_build_rule37_summary_payload_surfaces_verification_and_coverage():
    sb = MagicMock()
    # No rule37_warnings table / actions
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[])
    )
    payload = {
        "compliance": {
            "rule37": [],
            "rule37_pending_verification": [
                {
                    "pr_id": "p1",
                    "potential_itc_paise": 12_345,
                    "itc_at_risk_paise": 0,
                    "status": PENDING_VERIFICATION,
                }
            ],
            "rule37_coverage": {
                "claimed_invoice_count": 70,
                "payment_status_known_count": 12,
                "payment_status_unknown_count": 58,
            },
        },
        "decisions": {"rule37": []},
    }
    body = _build_rule37_summary_payload(sb, "run-1", payload, Counter())
    s = body["summary"]
    assert s["total_itc_at_risk"] == 0.0
    assert s["pending_verification_count"] == 1
    assert s["pending_verification_exposure"] == 123.45
    assert s["claimed_invoice_count"] == 70
    assert s["payment_status_known_count"] == 12
    assert s["payment_status_unknown_count"] == 58
    assert s["coverage_available"] is True
    # Confirmed at-risk stays separate from pending-verification exposure
    assert s["pending_verification_exposure"] != s["total_itc_at_risk"]
    assert s["pending_action"] == 0.0
