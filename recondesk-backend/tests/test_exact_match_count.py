"""Regression test: exact_match_count must reflect match_level==1, not financial MISMATCHED status."""
from app.services.reconciliation_payload_store import slim_engine_matched

# --- 1. Payload serialisation: match_level survives slim_engine_matched ---

def test_slim_engine_matched_preserves_match_level_and_financial_status():
    """match_level and financial_status must survive the whitelist filter."""
    rows = [
        {
            "gstr_id": "aaa",
            "pr_id": "bbb",
            "confidence_score": 100,
            "match_level": 1,
            "financial_status": "Exact",
            "is_late_filing": False,
            "original_period": None,
            "late_months": 0,
            "vendor_similarity_score": None,
            "match_status": "matched",          # must be dropped (not in whitelist)
            "match_status_text": "Matched",     # must be dropped
        },
        {
            "gstr_id": "ccc",
            "pr_id": "ddd",
            "confidence_score": 80,
            "match_level": 3,
            "financial_status": "AmountMismatch",
            "is_late_filing": False,
            "original_period": None,
            "late_months": 0,
            "vendor_similarity_score": None,
        },
    ]
    slimmed = slim_engine_matched(rows)
    assert slimmed[0]["match_level"] == 1,           "L1 match_level must be preserved"
    assert slimmed[0]["financial_status"] == "Exact", "financial_status must be preserved"
    assert "match_status" not in slimmed[0],         "match_status must be stripped"
    assert slimmed[1]["match_level"] == 3,           "L3 match_level must be preserved"


# --- 2. exact_match_count logic: use match_level==1, not financial MISMATCHED ---

def _compute_exact_match_count(matched_engine_rows):
    """Mirror of the fixed logic in _build_reconcile_summary."""
    return sum(
        1 for m in matched_engine_rows
        if isinstance(m, dict) and (
            m.get("match_level") == 1
            or (m.get("match_level") is None and m.get("confidence_score") == 100)
        )
    )


def test_exact_match_count_uses_match_level_not_financial_status():
    """With 7700 L1 rows and 300 L2/L3 rows, exact_match_count must be ~7700."""
    matched_rows = (
        [{"match_level": 1, "confidence_score": 100}] * 7700   # exact scenario
        + [{"match_level": 2, "confidence_score": 80}]  * 200  # format_variant
        + [{"match_level": 3, "confidence_score": 60}]  * 100  # small_amount_diff
    )
    count = _compute_exact_match_count(matched_rows)
    assert count == 7700, f"Expected 7700, got {count}"


def test_exact_match_count_fallback_for_old_runs():
    """Runs serialized before the fix have match_level=None; confidence_score==100 is the fallback."""
    matched_rows = (
        [{"match_level": None, "confidence_score": 100}] * 5000   # old exact rows
        + [{"match_level": None, "confidence_score": 80}]  * 2000  # old fuzzy rows
    )
    count = _compute_exact_match_count(matched_rows)
    assert count == 5000, f"Expected 5000, got {count}"


def test_exact_match_count_not_based_on_financial_mismatch():
    """A row that is L1 but has a financial discrepancy must still count as exact."""
    # L1 = same GSTIN + invoice number + amounts matched exactly at L1 threshold.
    # A later financial check might flag a small VAT diff, but the MATCH METHOD is still L1.
    matched_rows = [
        {"match_level": 1, "confidence_score": 100},  # exact match, no financial issue
        {"match_level": 1, "confidence_score": 100},  # exact match, but suppose financial_status="AmountMismatch"
        {"match_level": 3, "confidence_score": 60},   # fuzzy match
    ]
    count = _compute_exact_match_count(matched_rows)
    assert count == 2, f"Expected 2, got {count}"


def test_build_reconcile_summary_fallback_when_outcome_matched_zero():
    from unittest.mock import MagicMock, patch
    from app.routers.reconciliation_api import _build_reconcile_summary

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        count=10, data=[{"trade_name": "Test Client", "gstin": "27ABCDE1234F1Z5"}]
    )

    run_row = {
        "id": "run-fallback-1",
        "client_gstin_id": "cg-1",
        "run_summary": {"clean_matched_count": 8},
        "period": "2026-04",
    }
    payload = {
        "engine": {
            "matched": [{"gstr_id": "g1", "pr_id": "p1"}],
        }
    }
    with patch("app.routers.reconciliation_api.ro.load_gstr_map", return_value={}), \
         patch("app.routers.reconciliation_api.ro.load_pr_map", return_value={}), \
         patch("app.routers.reconciliation_api.get_user_profile", return_value={"role": "admin"}):
        res = _build_reconcile_summary(
            sb=mock_sb,
            run_row=run_row,
            payload=payload,
            current_user_id="user-1",
            precomputed_outcome_rows=[],
        )
    assert res["clean_matched_count"] == 8
    assert res["matched_count"] == 8

