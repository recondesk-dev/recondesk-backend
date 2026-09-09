"""
test_vendor_intelligence.py
Scenario: Vendor Intelligence scoring — pure function tests.
Run: PYTHONPATH=. pytest tests/test_vendor_intelligence.py -v
"""
import pytest
from decimal import Decimal
from app.services.vendor_intelligence import (
    calculate_supplier_score,
    dedupe_gstr_rows,
    expand_runs_history,
    supplier_distinct_run_ids,
    _is_tolerance_match,
    _is_l1_exact,
    _is_mismatch,
)

GSTIN_A = "27ABCDE1234F1Z0"
GSTIN_B = "29XYZDE1234F1Z0"


# ── helpers to build test data ────────────────────────────────────────────────

def make_flat_row(
    gstin=GSTIN_A,
    invoice="INV001",
    invoice_date="2024-04-01",
    amount_diff_paise=0,
    run_id="run-001",
    created_at="2024-05-01T10:00:00",
    period_end_date="2024-04-30",
):
    return {
        "supplier_gstin": gstin,
        "invoice_number": invoice,
        "invoice_date": invoice_date,
        "amount_difference_paise": amount_diff_paise,
        "reconciliation_run_id": run_id,
        "created_at": created_at,
        "period_end_date": period_end_date,
    }


def make_grouped_run(run_id, records, period_end_date="2024-04-30"):
    return {
        "run_id": run_id,
        "period_end_date": period_end_date,
        "records": records,
    }


# ── _is_tolerance_match ───────────────────────────────────────────────────────

class TestIsToleranceMatch:

    def test_zero_diff_is_tolerance_match(self):
        assert _is_tolerance_match(0) is True

    def test_exactly_100_paise_is_tolerance_match(self):
        """₹1 = 100 paise — within TOLERANCE_PAISE."""
        assert _is_tolerance_match(100) is True

    def test_101_paise_is_not_tolerance_match(self):
        assert _is_tolerance_match(101) is False

    def test_negative_within_tolerance(self):
        assert _is_tolerance_match(-100) is True

    def test_none_is_not_tolerance_match(self):
        assert _is_tolerance_match(None) is False

    def test_string_number_is_handled(self):
        """String '50' should be handled gracefully."""
        assert _is_tolerance_match("50") is True

    def test_invalid_string_is_not_tolerance_match(self):
        assert _is_tolerance_match("abc") is False


# ── _is_l1_exact ──────────────────────────────────────────────────────────────

class TestIsL1Exact:

    def test_zero_is_exact(self):
        assert _is_l1_exact(0) is True

    def test_one_paise_is_not_exact(self):
        assert _is_l1_exact(1) is False

    def test_none_is_not_exact(self):
        assert _is_l1_exact(None) is False

    def test_negative_one_is_not_exact(self):
        assert _is_l1_exact(-1) is False


# ── _is_mismatch ──────────────────────────────────────────────────────────────

class TestIsMismatch:

    def test_zero_is_not_mismatch(self):
        assert _is_mismatch(0) is False

    def test_100_paise_is_not_mismatch(self):
        assert _is_mismatch(100) is False

    def test_101_paise_is_mismatch(self):
        assert _is_mismatch(101) is True

    def test_none_is_mismatch(self):
        """None amount_difference means we can't verify — treat as mismatch."""
        assert _is_mismatch(None) is True


# ── dedupe_gstr_rows ──────────────────────────────────────────────────────────

class TestDedupeGstrRows:

    def test_no_duplicates_returns_all(self):
        rows = [
            make_flat_row(invoice="INV001", run_id="run-001"),
            make_flat_row(invoice="INV002", run_id="run-001"),
        ]
        result = dedupe_gstr_rows(rows)
        assert len(result) == 2

    def test_exact_duplicate_keeps_one(self):
        rows = [
            make_flat_row(invoice="INV001", run_id="run-001", created_at="2024-05-01T10:00:00"),
            make_flat_row(invoice="INV001", run_id="run-001", created_at="2024-05-01T10:00:00"),
        ]
        result = dedupe_gstr_rows(rows)
        assert len(result) == 1

    def test_duplicate_keeps_latest_created_at(self):
        """When same dedup key, keep the row with latest created_at."""
        rows = [
            make_flat_row(invoice="INV001", run_id="run-001",
                         created_at="2024-05-01T09:00:00", amount_diff_paise=0),
            make_flat_row(invoice="INV001", run_id="run-001",
                         created_at="2024-05-01T11:00:00", amount_diff_paise=500),
        ]
        result = dedupe_gstr_rows(rows)
        assert len(result) == 1
        assert result[0]["amount_difference_paise"] == 500, (
            "Must keep the row with latest created_at."
        )

    def test_same_invoice_different_run_ids_kept_separately(self):
        """Same invoice in two different runs — both kept."""
        rows = [
            make_flat_row(invoice="INV001", run_id="run-001"),
            make_flat_row(invoice="INV001", run_id="run-002"),
        ]
        result = dedupe_gstr_rows(rows)
        assert len(result) == 2

    def test_empty_input_returns_empty(self):
        assert dedupe_gstr_rows([]) == []


# ── expand_runs_history ───────────────────────────────────────────────────────

class TestExpandRunsHistory:

    def test_flat_input_returns_copies(self):
        rows = [make_flat_row(invoice="INV001")]
        result = expand_runs_history(rows)
        assert len(result) == 1
        assert result[0] is not rows[0], "Must return copies, not same objects."

    def test_grouped_input_flattens(self):
        grouped = [
            make_grouped_run("run-001", [
                {"supplier_gstin": GSTIN_A, "invoice_number": "INV001"},
                {"supplier_gstin": GSTIN_A, "invoice_number": "INV002"},
            ]),
        ]
        result = expand_runs_history(grouped)
        assert len(result) == 2

    def test_grouped_injects_run_id(self):
        """Each flattened record must have reconciliation_run_id from parent."""
        grouped = [
            make_grouped_run("run-001", [
                {"supplier_gstin": GSTIN_A, "invoice_number": "INV001"},
            ]),
        ]
        result = expand_runs_history(grouped)
        assert result[0]["reconciliation_run_id"] == "run-001"

    def test_grouped_injects_period_end_date(self):
        """Each flattened record must have period_end_date from parent."""
        grouped = [
            make_grouped_run("run-001", [
                {"supplier_gstin": GSTIN_A, "invoice_number": "INV001"},
            ], period_end_date="2024-04-30"),
        ]
        result = expand_runs_history(grouped)
        assert result[0]["period_end_date"] == "2024-04-30"

    def test_empty_input_returns_empty(self):
        assert expand_runs_history([]) == []


# ── calculate_supplier_score ──────────────────────────────────────────────────

class TestCalculateSupplierScore:

    def test_fewer_than_2_runs_returns_none(self):
        """
        Supplier must appear in at least 2 distinct runs.
        With only 1 run, score is not calculable — returns None.
        """
        rows = [make_flat_row(run_id="run-001")]
        result = calculate_supplier_score(GSTIN_A, "Test Supplier", rows)
        assert result is None, (
            "Supplier with only 1 run must return None — not enough history."
        )

    def test_zero_runs_returns_none(self):
        result = calculate_supplier_score(GSTIN_A, "Test Supplier", [])
        assert result is None

    def test_two_runs_perfect_match_is_LOW_risk(self):
        """
        Supplier appears in 2 runs, all invoices within tolerance.
        Filing reliability = 100% → LOW risk.
        """
        rows = [
            make_flat_row(invoice="INV001", run_id="run-001", amount_diff_paise=0),
            make_flat_row(invoice="INV002", run_id="run-002", amount_diff_paise=0),
        ]
        result = calculate_supplier_score(GSTIN_A, "Test Supplier", rows)
        assert result is not None
        assert result["risk_level"] == "LOW", (
            f"Perfect match supplier must be LOW risk. Got: {result['risk_level']}"
        )

    def test_two_runs_all_mismatch_is_HIGH_risk(self):
        """
        All invoices have large mismatches → filing reliability < 80% → HIGH risk.
        """
        rows = [
            make_flat_row(invoice="INV001", run_id="run-001", amount_diff_paise=50000),
            make_flat_row(invoice="INV002", run_id="run-002", amount_diff_paise=50000),
        ]
        result = calculate_supplier_score(GSTIN_A, "Test Supplier", rows)
        assert result is not None
        assert result["risk_level"] == "HIGH", (
            f"All-mismatch supplier must be HIGH risk. Got: {result['risk_level']}"
        )

    def test_result_has_required_keys(self):
        """Score dict must have all required keys for the API."""
        rows = [
            make_flat_row(run_id="run-001", amount_diff_paise=0),
            make_flat_row(run_id="run-002", amount_diff_paise=0),
        ]
        result = calculate_supplier_score(GSTIN_A, "Test Supplier", rows)
        assert result is not None
        required_keys = {
            "filing_reliability_pct",
            "amount_accuracy_pct",
            "avg_late_days",
            "mismatch_count",
            "runs_appeared_in",
            "risk_level",
        }
        missing = required_keys - set(result.keys())
        assert not missing, f"Score dict missing keys: {missing}"

    def test_filing_reliability_is_decimal(self):
        """filing_reliability_pct must be a Decimal for precise display."""
        rows = [
            make_flat_row(run_id="run-001", amount_diff_paise=0),
            make_flat_row(run_id="run-002", amount_diff_paise=0),
        ]
        result = calculate_supplier_score(GSTIN_A, "Test Supplier", rows)
        assert isinstance(result["filing_reliability_pct"], Decimal), (
            "filing_reliability_pct must be Decimal — not float (rounding risk)."
        )

    def test_different_supplier_gstin_returns_none(self):
        """
        Rows are for GSTIN_A but we ask for GSTIN_B.
        Must return None — not mix up suppliers.
        """
        rows = [
            make_flat_row(gstin=GSTIN_A, run_id="run-001"),
            make_flat_row(gstin=GSTIN_A, run_id="run-002"),
        ]
        result = calculate_supplier_score(GSTIN_B, "Other Supplier", rows)
        assert result is None, (
            "Asking for GSTIN_B when all rows are GSTIN_A must return None."
        )

    def test_lowercase_gstin_in_history_still_matches(self):
        """
        History may have lowercase GSTINs from old runs.
        calculate_supplier_score must normalize before comparing.
        """
        rows = [
            make_flat_row(gstin=GSTIN_A.lower(), run_id="run-001", amount_diff_paise=0),
            make_flat_row(gstin=GSTIN_A.lower(), run_id="run-002", amount_diff_paise=0),
        ]
        result = calculate_supplier_score(GSTIN_A, "Test Supplier", rows)
        assert result is not None, (
            "Lowercase GSTIN in history must still match uppercase query GSTIN."
        )

    def test_mismatch_count_is_correct(self):
        """mismatch_count must exactly count rows with diff > 100 paise."""
        rows = [
            make_flat_row(invoice="INV001", run_id="run-001", amount_diff_paise=0),
            make_flat_row(invoice="INV002", run_id="run-001", amount_diff_paise=500),
            make_flat_row(invoice="INV003", run_id="run-002", amount_diff_paise=200),
        ]
        result = calculate_supplier_score(GSTIN_A, "Test", rows)
        assert result is not None
        assert result["mismatch_count"] == 2, (
            f"Must count 2 mismatches (500 and 200 paise > 100). Got: {result['mismatch_count']}"
        )

    def test_runs_appeared_in_counts_distinct_runs(self):
        """runs_appeared_in must count distinct run IDs, not total rows."""
        rows = [
            make_flat_row(invoice="INV001", run_id="run-001"),
            make_flat_row(invoice="INV002", run_id="run-001"),  # same run
            make_flat_row(invoice="INV003", run_id="run-002"),
        ]
        result = calculate_supplier_score(GSTIN_A, "Test", rows)
        assert result is not None
        assert result["runs_appeared_in"] == 2, (
            f"Must count 2 distinct runs not 3 rows. Got: {result['runs_appeared_in']}"
        )

    def test_95pct_filing_reliability_is_LOW(self):
        """Exactly 95% filing reliability → LOW risk (inclusive boundary)."""
        # 19 out of 20 runs reliable = 95%
        rows = []
        for i in range(19):
            rows.append(make_flat_row(invoice=f"INV{i:03d}", run_id=f"run-{i:03d}", amount_diff_paise=0))
        rows.append(make_flat_row(invoice="INV019", run_id="run-019", amount_diff_paise=50000))
        result = calculate_supplier_score(GSTIN_A, "Test", rows)
        assert result is not None
        assert result["risk_level"] == "LOW", (
            f"95% filing reliability must be LOW risk. Got: {result['risk_level']}, "
            f"filing_pct={result['filing_reliability_pct']}"
        )

    def test_grouped_format_works(self):
        """Grouped runs_history format must produce same result as flat."""
        grouped = [
            make_grouped_run("run-001", [
                {"supplier_gstin": GSTIN_A, "invoice_number": "INV001",
                 "amount_difference_paise": 0, "invoice_date": "2024-04-01"},
            ]),
            make_grouped_run("run-002", [
                {"supplier_gstin": GSTIN_A, "invoice_number": "INV002",
                 "amount_difference_paise": 0, "invoice_date": "2024-04-05"},
            ]),
        ]
        result = calculate_supplier_score(GSTIN_A, "Test", grouped)
        assert result is not None, "Grouped format must produce a score."
        assert result["risk_level"] == "LOW"
