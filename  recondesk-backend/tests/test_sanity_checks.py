"""Tests for ``app.services.sanity`` — one deliberate failure mode per case where applicable."""

import datetime

from app.services.sanity import SanityCheck, detect_duplicates, run_import_sanity
from app.utils.test_helpers import make_valid_test_gstin


def _gst(i: int = 0) -> str:
    return make_valid_test_gstin(i)


def _base(**kwargs):
    r = {
        "gstin": _gst(0),
        "invoice_number_normalized": "INV-1",
        "invoice_date": "2020-06-01",
        "taxable_amount_paise": 100_000,
        "total_tax_paise": 18_000,
        "cgst_paise": 9_000,
        "sgst_paise": 9_000,
        "igst_paise": 0,
        "tax_rate": 18,
        "document_type": "INVOICE",
    }
    r.update(kwargs)
    return r


def _by_name(checks: list[SanityCheck], name: str) -> SanityCheck:
    for c in checks:
        if c.name == name:
            return c
    raise AssertionError(f"missing check {name!r}")


def test_row_count_passes_when_actual_equals_expected():
    rows = [_base(invoice_number_normalized=f"INV-{i}") for i in range(3)]
    checks = run_import_sanity(rows, expected_count=3, source_type="csv")
    c = _by_name(checks, "Row Count")
    assert c.passed is True
    assert c.severity == "info"


def test_row_count_fails_when_counts_differ():
    rows = [_base()]
    checks = run_import_sanity(rows, expected_count=2, source_type="csv")
    c = _by_name(checks, "Row Count")
    assert c.passed is False
    assert c.severity == "error"


def test_gstin_validity_passes_for_valid_gstin():
    checks = run_import_sanity([_base()], expected_count=1, source_type="x")
    c = _by_name(checks, "GSTIN Validity")
    assert c.passed is True


def test_gstin_validity_fails_for_invalid_gstin():
    bad = _base(gstin="INVALID")
    checks = run_import_sanity([bad], expected_count=1, source_type="x")
    c = _by_name(checks, "GSTIN Validity")
    assert c.passed is False
    assert len(c.affected_records) >= 1


# ── PR-specific GSTIN behaviour ──────────────────────────────────────────────

def test_pr_malformed_gstin_is_warning_not_error():
    """Malformed (but non-blank) supplier GSTINs in a PR must be warnings so the run is not blocked."""
    bad = _base(gstin="27AAAPZ1234A1Z5EXTRA")  # too long → invalid format
    checks = run_import_sanity([bad], expected_count=1, source_type="purchase_register")
    c = _by_name(checks, "GSTIN Validity")
    assert c.passed is False
    assert c.severity == "warning"
    assert len(c.affected_records) >= 1


def test_pr_blank_gstin_is_error():
    """A completely blank supplier GSTIN in a PR must still be an error — the row is meaningless."""
    blank = _base(gstin="")
    checks = run_import_sanity([blank], expected_count=1, source_type="purchase_register")
    c = _by_name(checks, "GSTIN Validity")
    assert c.passed is False
    assert c.severity == "error"


def test_pr_valid_gstin_passes():
    checks = run_import_sanity([_base()], expected_count=1, source_type="purchase_register")
    c = _by_name(checks, "GSTIN Validity")
    assert c.passed is True
    assert c.severity == "info"


def test_tax_math_passes_within_500_paise_tolerance():
    # 100000 * 18 / 100 = 18000; off by 500 is still ok
    r = _base(total_tax_paise=18_500, tax_rate=18)
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "Tax Math")
    assert c.passed is True


def test_tax_math_fails_beyond_tolerance():
    r = _base(total_tax_paise=19_000, tax_rate=18)  # diff 1000 > 500
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "Tax Math")
    assert c.passed is False


def test_tax_math_passes_when_tax_rate_missing_skipped():
    r = _base()
    del r["tax_rate"]
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "Tax Math")
    assert c.passed is True


def test_tax_math_passes_using_cgst_sgst_igst_without_total_tax_paise():
    r = _base()
    del r["total_tax_paise"]
    r["cgst_paise"] = 9_000
    r["sgst_paise"] = 9_000
    r["igst_paise"] = 0
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "Tax Math")
    assert c.passed is True


def test_cgst_igst_conflict_detects_both_positive():
    # Tax total still matches rate math; components are intentionally inconsistent with CGST+IGST both > 0
    r = _base(cgst_paise=100, igst_paise=100, sgst_paise=0, total_tax_paise=18_000)
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "CGST/IGST Conflict")
    assert c.passed is False


def test_cgst_igst_conflict_detects_short_keys_cgst_igst():
    """Records may use cgst/igst instead of cgst_paise/igst_paise (e.g. raw GSTR-style fields)."""
    r = _base(cgst_paise=0, igst_paise=0, sgst_paise=0, total_tax_paise=18_000)
    del r["cgst_paise"]
    del r["igst_paise"]
    r["cgst"] = 900
    r["igst"] = 1800
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "CGST/IGST Conflict")
    assert c.passed is False
    assert len(c.affected_records) == 1


def test_cgst_igst_no_conflict_when_only_igst():
    r = _base(cgst_paise=0, sgst_paise=0, igst_paise=18_000, total_tax_paise=18_000)
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "CGST/IGST Conflict")
    assert c.passed is True


def test_future_date_fails():
    future = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    r = _base(invoice_date=future)
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "Future Date")
    assert c.passed is False
    assert len(c.affected_records) >= 1


def test_zero_taxable_amount_flagged():
    r = _base(taxable_amount_paise=0, total_tax_paise=0, cgst_paise=0, sgst_paise=0, tax_rate=0)
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "Zero Amount")
    assert c.passed is False
    assert c.severity == "warning"


def test_negative_tax_flagged():
    r = _base(cgst_paise=-100, sgst_paise=9_100, igst_paise=0, total_tax_paise=18_000)
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "Negative Tax")
    assert c.passed is False


def test_duplicates_within_batch_second_row_flagged():
    a = _base(invoice_number_normalized="DUP")
    b = _base(invoice_number_normalized="DUP")
    res = detect_duplicates([a, b])
    assert res["has_duplicates"] is True
    assert len(res["within_batch"]) == 1
    assert len(res["clean_records"]) == 1


def test_duplicates_against_existing_history():
    hist = [_base(invoice_number_normalized="H1")]
    incoming = [_base(invoice_number_normalized="H1")]
    res = detect_duplicates(incoming, existing_records=hist)
    assert res["has_duplicates"] is True
    assert len(res["against_history"]) == 1
    assert res["clean_records"] == []


def test_detect_duplicates_never_drops_rows_partition():
    """Every input row appears exactly once across clean, within_batch, and against_history."""
    e1 = _base(invoice_number_normalized="E1")
    e2 = _base(invoice_number_normalized="E2")
    hist = [e1]
    incoming = [e1, e2, e2]
    res = detect_duplicates(incoming, existing_records=hist)
    all_out = res["clean_records"] + res["within_batch"] + res["against_history"]
    assert len(all_out) == len(incoming)
    assert len(res["against_history"]) == 1
    assert len(res["clean_records"]) == 1
    assert len(res["within_batch"]) == 1
