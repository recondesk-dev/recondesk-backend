"""Tests for compact reconciliation_results persistence."""

import json
import uuid

from app.services.reconciliation_payload_store import (
    build_run_summary_metrics,
    build_stored_results_payload,
    payload_json_byte_size,
    slim_decision_rows,
    slim_engine_matched,
)


def _matched_row(**kwargs):
    base = {
        "gstr_id": str(uuid.uuid4()),
        "pr_id": str(uuid.uuid4()),
        "confidence_score": 100,
        "match_reasons": ["Invoice number, amount, and date all match", "amount: diff=Rs 0.63"],
        "is_late_filing": False,
        "original_period": None,
        "late_months": 0,
        "match_status_text": "Matched",
        "vendor_similarity_score": 0.91,
    }
    base.update(kwargs)
    return base


def test_slim_engine_matched_drops_match_reasons():
    rows = [_matched_row() for _ in range(100)]
    slim = slim_engine_matched(rows)
    assert len(slim) == 100
    assert "match_reasons" not in slim[0]
    assert "gstr_id" in slim[0]
    assert "pr_id" in slim[0]


def test_stored_payload_much_smaller_than_fat_engine():
    matched = [_matched_row() for _ in range(3500)]
    decision_rows = [
        {
            **_matched_row(),
            "decision_what": "Exact match found",
            "decision_why": "Invoice number, amount, and date all match within rounding tolerance",
            "decision_next": "No action required",
            "decision_rule": "L1_EXACT",
            "decision_confidence": "HIGH",
            "decision_matched_fields": ["gstin", "invoice_number", "invoice_date"],
            "decision_differed_fields": [],
            "decision_normalized_pairs": [],
        }
        for _ in range(3500)
    ]
    fat = {
        "engine": {"matched": matched, "missed_itc": [], "wrongful_itc_risk": []},
        "decisions": {"rows": decision_rows},
        "summary": {"decisions": {"rows": decision_rows}},
    }
    slim = build_stored_results_payload(
        matched=matched,
        missed_itc=[],
        wrongful_itc_risk=[],
        rule37=[],
        section_175_warnings=[],
        credit_note_adjustment={},
        decision_payload={"rows": decision_rows},
        matching_version="1.0.0",
        rules_version="1.0.0",
        decision_version="1.0.0",
    )
    fat_mb = payload_json_byte_size(fat) / (1024 * 1024)
    slim_mb = payload_json_byte_size(slim) / (1024 * 1024)
    assert slim_mb < fat_mb * 0.35
    assert slim_mb < 2.0


def test_run_summary_metrics_has_no_nested_decisions():
    summary = build_run_summary_metrics(
        n_gstr=3828,
        n_pr=3794,
        matched_count=3417,
        missed_itc_count=411,
        wrongful_count=377,
        itc_missed=100,
        wrongful_paise=200,
        rule37_itc_paise=0,
        itc_at_risk_total=100,
        late_itc_paise=0,
        late_match_count=0,
    )
    assert summary["matched_count"] == 3417
    assert "decisions" not in summary
    assert "compliance" not in summary
    assert len(json.dumps(summary)) < 500
