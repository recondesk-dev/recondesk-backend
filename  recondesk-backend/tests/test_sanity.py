"""Pytest suite for sanity checks (``app.validators.sanity_checks``; re-exported from ``app.services.sanity``)."""

import datetime

import pytest

from app.services.sanity import (
    SanityCheck,
    _tax_tolerance_paise,
    detect_duplicates,
    is_valid_gstin,
    make_dedup_key_string,
    run_import_sanity,
)
from app.validators.sanity_checks import SanityIssue

VALID_GSTIN = "27ABCDE1234F1Z1"


def _base(**kwargs):
    r = {
        "gstin": VALID_GSTIN,
        "invoice_number_normalized": "INV-1",
        "invoice_date": "2024-06-01",
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


# ---------------------------------------------------------------------------
# 1. Row count mismatch (minor + major)
# ---------------------------------------------------------------------------


def test_row_count_minor_and_major_mismatch():
    good = [_base(invoice_number_normalized=f"INV-{i}") for i in range(100)]
    minor = run_import_sanity(good, expected_count=102, source_type="csv")
    c1 = _by_name(minor, "Row Count")
    assert c1.severity == "warning"
    assert c1.passed is False
    assert c1.affected_count == 2  # |expected − actual| when within minor-mismatch band

    major = run_import_sanity(good, expected_count=200, source_type="csv")
    c2 = _by_name(major, "Row Count")
    assert c2.severity == "error"
    assert c2.passed is False


# ---------------------------------------------------------------------------
# 2. Missing fields
# ---------------------------------------------------------------------------


def test_missing_mandatory_fields():
    bad = _base()
    del bad["gstin"]
    r2 = _base(invoice_number_normalized="X")
    r2["invoice_date"] = None
    checks = run_import_sanity([bad, r2], expected_count=None, source_type="x")
    m = _by_name(checks, "Mandatory Fields")
    assert m.severity == "error"
    assert m.passed is False
    assert m.affected_count == 2
    assert any("_missing_fields" in x for x in m.affected_records)


# ---------------------------------------------------------------------------
# 3. Invalid GSTIN
# ---------------------------------------------------------------------------


def test_invalid_gstin():
    assert SanityIssue is SanityCheck
    bad = _base(gstin="INVALID")
    checks = run_import_sanity([bad], None, "t")
    g = _by_name(checks, "GSTIN Validity")
    assert g.severity == "error"
    assert g.affected_count == 1
    assert is_valid_gstin("NA") is False


# ---------------------------------------------------------------------------
# 4. Tax mismatch (rate + component)
# ---------------------------------------------------------------------------


def test_tax_mismatch_rate_and_components():
    rate_bad = _base(
        taxable_amount_paise=100_000,
        total_tax_paise=18_000,
        tax_rate=18,
        cgst_paise=9_000,
        sgst_paise=9_000,
        igst_paise=0,
    )
    # Force large rate mismatch: expected 18000, actual 5000
    rate_bad["total_tax_paise"] = 5_000

    comp_bad = _base(invoice_number_normalized="INV-C")
    comp_bad["total_tax_paise"] = 18_000
    comp_bad["cgst_paise"] = 1_000
    comp_bad["sgst_paise"] = 1_000
    comp_bad["igst_paise"] = 0

    checks = run_import_sanity([rate_bad, comp_bad], None, "t")
    t = _by_name(checks, "Tax Math")
    assert t.affected_count == 2
    assert t.severity == "error"


# ---------------------------------------------------------------------------
# 5. CGST/IGST conflict
# ---------------------------------------------------------------------------


def test_cgst_igst_conflict():
    bad = _base(
        cgst_paise=100,
        sgst_paise=0,
        igst_paise=50,
        total_tax_paise=150,
    )
    checks = run_import_sanity([bad], None, "t")
    s = _by_name(checks, "Tax Structure")
    assert s.severity == "error"
    assert s.affected_count == 1


# ---------------------------------------------------------------------------
# 6. Future date
# ---------------------------------------------------------------------------


def test_future_date_error():
    far = (datetime.date.today() + datetime.timedelta(days=40)).isoformat()
    bad = _base(invoice_date=far)
    checks = run_import_sanity([bad], None, "t")
    d = _by_name(checks, "Date Validity")
    assert d.severity == "error"
    assert d.affected_count == 1


# ---------------------------------------------------------------------------
# 7. Zero taxable edge cases
# ---------------------------------------------------------------------------


def test_zero_taxable_credit_note_vs_invoice():
    cn = _base(
        document_type="CREDIT_NOTE",
        taxable_amount_paise=0,
        total_tax_paise=0,
        cgst_paise=0,
        sgst_paise=0,
        igst_paise=0,
        tax_rate=0,
    )
    inv = _base(
        invoice_number_normalized="INV-Z",
        document_type="INVOICE",
        taxable_amount_paise=0,
        total_tax_paise=0,
        cgst_paise=0,
        sgst_paise=0,
        igst_paise=0,
        tax_rate=0,
    )
    checks = run_import_sanity([cn, inv], None, "t")
    z = _by_name(checks, "Zero Taxable")
    assert z.affected_count == 1
    assert z.severity == "warning"
    assert z.passed is False


# ---------------------------------------------------------------------------
# 8. Negative misuse
# ---------------------------------------------------------------------------


def test_negative_not_allowed_on_invoice():
    bad = _base(
        taxable_amount_paise=-100,
        total_tax_paise=0,
        cgst_paise=0,
        sgst_paise=0,
        igst_paise=0,
        tax_rate=0,
    )
    checks = run_import_sanity([bad], None, "t")
    n = _by_name(checks, "Negative Values")
    assert n.severity == "error"
    assert n.affected_count == 1


# ---------------------------------------------------------------------------
# 9. Invalid tax rate (warning only)
# ---------------------------------------------------------------------------


def test_invalid_tax_rate_warning():
    odd = _base(tax_rate=7.5)
    checks = run_import_sanity([odd], None, "t")
    tr = _by_name(checks, "Tax Rate")
    assert tr.severity == "warning"
    assert tr.affected_count == 1
    assert tr.passed is False


# ---------------------------------------------------------------------------
# 10. Outliers (₹ vs paise) + large taxable warning
# ---------------------------------------------------------------------------


def test_currency_unit_rupees_vs_paise_error():
    # 25 records with tiny "paise" values simulating rupees mis-imported as paise
    tiny = [
        _base(
            invoice_number_normalized=f"T-{i}",
            taxable_amount_paise=50,
            total_tax_paise=9,
            cgst_paise=4,
            sgst_paise=4,
            igst_paise=0,
        )
        for i in range(25)
    ]
    checks = run_import_sanity(tiny, None, "t")
    c = _by_name(checks, "Unit Consistency")
    assert c.severity == "error"
    assert c.affected_count == 25

    huge = _base(taxable_amount_paise=2_000_000_000)
    checks2 = run_import_sanity([huge], None, "t")
    o = _by_name(checks2, "Outliers")
    assert o.severity == "warning"
    assert o.affected_count == 1


# ---------------------------------------------------------------------------
# 11. Duplicate within batch
# ---------------------------------------------------------------------------


def test_duplicate_within_batch():
    a = _base(invoice_number_normalized="DUP", invoice_date="2024-01-01")
    b = dict(a)
    res = detect_duplicates([a, b])
    assert res["has_duplicates"] is True
    assert res["counts"]["within_batch"] == 1
    assert res["counts"]["clean"] == 1
    assert len(res["duplicate_keys"]) == 1
    k = make_dedup_key_string(a)
    assert res["duplicate_keys"][k] == 2


# ---------------------------------------------------------------------------
# 12. Duplicate against history
# ---------------------------------------------------------------------------


def test_duplicate_against_history():
    cur = _base()
    hist = [dict(cur)]
    res = detect_duplicates([cur], existing_records=hist)
    assert res["has_duplicates"] is True
    assert res["counts"]["against_history"] == 1
    assert res["counts"]["clean"] == 0
    assert res["counts"]["within_batch"] == 0


# ---------------------------------------------------------------------------
# 13. Same invoice different casing (dedup key differs)
# ---------------------------------------------------------------------------


def test_same_invoice_different_casing_normalizes_to_duplicate_key():
    lo = _base(invoice_number_normalized="abc")
    hi = _base(invoice_number_normalized="ABC")
    assert make_dedup_key_string(lo) == make_dedup_key_string(hi)
    res = detect_duplicates([lo, hi])
    assert res["has_duplicates"] is True
    assert res["counts"]["within_batch"] == 1
    assert res["counts"]["clean"] == 1


# ---------------------------------------------------------------------------
# 14. Mixed valid/invalid batch
# ---------------------------------------------------------------------------


def test_mixed_valid_invalid_batch():
    ok = _base(invoice_number_normalized="OK-1")
    bad_gstin = _base(gstin="BAD", invoice_number_normalized="OK-2")
    missing = _base()
    del missing["invoice_date"]
    checks = run_import_sanity([ok, bad_gstin, missing], expected_count=3, source_type="t")
    assert _by_name(checks, "Mandatory Fields").affected_count == 1
    assert _by_name(checks, "GSTIN Validity").affected_count == 1
    assert _by_name(checks, "Row Count").passed is True


def test_mandatory_missing_does_not_suppress_other_checks():
    """Rows with missing mandatory fields must still run independent checks (no global valid-only gate)."""
    bad = {
        "gstin": "BADGSTIN",
        "invoice_number_normalized": "",
        "invoice_date": "2035-01-01",
        "taxable_amount_paise": 0,
        "total_tax_paise": 99999,
        "cgst_paise": 50000,
        "sgst_paise": 0,
        "igst_paise": 50000,
        "tax_rate": 99,
        "document_type": "INVOICE",
    }
    checks = run_import_sanity([bad], expected_count=50, source_type="test")
    assert _by_name(checks, "Mandatory Fields").affected_count == 1
    assert _by_name(checks, "GSTIN Validity").affected_count == 1
    assert _by_name(checks, "Date Validity").passed is False
    assert _by_name(checks, "Tax Math").affected_count >= 1
    assert _by_name(checks, "Tax Structure").affected_count >= 1
    assert _by_name(checks, "Tax Rate").affected_count >= 1
    assert _by_name(checks, "Zero Taxable").affected_count >= 1
    assert _by_name(checks, "Row Count").affected_count == 49


# ---------------------------------------------------------------------------
# 15. Large dataset (performance + correctness)
# ---------------------------------------------------------------------------


def test_large_dataset_deterministic():
    n = 5000
    rows = [
        _base(
            invoice_number_normalized=f"B-{i}",
            taxable_amount_paise=10_000 + i,
            total_tax_paise=1800,
            cgst_paise=900,
            sgst_paise=900,
            igst_paise=0,
        )
        for i in range(n)
    ]
    c1 = run_import_sanity(rows, expected_count=n, source_type="bulk")
    c2 = run_import_sanity(rows, expected_count=n, source_type="bulk")
    assert c1 == c2
    assert len(c1) == 15  # 13 core + Duplicate Records + Invoice Conflicts
    assert _by_name(c1, "Row Count").passed is True

    d1 = detect_duplicates(rows)
    d2 = detect_duplicates(rows)
    assert d1 == d2
    assert d1["counts"]["clean"] == n


# ---------------------------------------------------------------------------
# 16–22. Check 5 — tax math (multi-case: rate / inferred / component / bands)
# ---------------------------------------------------------------------------


def test_check5_rate_mismatch_warning_band():
    """0 < diff <= tol → warning (diff within tolerance)."""
    taxable = 100_000
    tol = _tax_tolerance_paise(taxable)
    assert tol == 1_000
    # expected_tax = 100_000 * 18 / 100 = 18_000; total = 17_500 → diff = 500 ≤ 1_000
    total = 17_500
    r = _base(
        total_tax_paise=total,
        cgst_paise=total // 2,
        sgst_paise=total - total // 2,
    )
    t = _by_name(run_import_sanity([r], None, "t"), "Tax Math")
    assert t.affected_count == 1
    assert t.severity == "warning"


def test_check5_rate_mismatch_error_band():
    """diff > tol → error."""
    taxable = 100_000
    tol = _tax_tolerance_paise(taxable)
    assert tol == 1_000
    # expected_tax = 18_000; total = 15_500 → diff = 2_500 > 1_000
    total = 15_500
    r = _base(
        total_tax_paise=total,
        cgst_paise=total // 2,
        sgst_paise=total - total // 2,
    )
    t = _by_name(run_import_sanity([r], None, "t"), "Tax Math")
    assert t.affected_count == 1
    assert t.severity == "error"


def test_tax_math_mixed_warning_and_error_rows():
    """Within-tolerance row → warning band; beyond-tolerance row → error; overall severity error."""
    inv1 = _base(
        invoice_number_normalized="INV1",
        taxable_amount_paise=10_000,
        total_tax_paise=1_850,
        cgst_paise=925,
        sgst_paise=925,
        igst_paise=0,
        tax_rate=18,
    )
    inv2 = _base(
        invoice_number_normalized="INV2",
        taxable_amount_paise=10_000,
        total_tax_paise=3_000,
        cgst_paise=1_500,
        sgst_paise=1_500,
        igst_paise=0,
        tax_rate=18,
    )
    t = _by_name(run_import_sanity([inv1, inv2], None, "test"), "Tax Math")
    assert t.affected_count == 2
    assert t.severity == "error"
    assert "2 mismatches found (1 within tolerance, 1 beyond tolerance)" in t.detail


def test_check5_inferred_slab_warning_no_tax_rate():
    """Inferred slab: diff within tolerance → warning."""
    taxable = 100_000
    tol = _tax_tolerance_paise(taxable)
    assert tol == 1_000
    # Nearest slab for ~17.5% is 18%, expected = 18_000; total = 17_500 → diff = 500
    total = 17_500
    r = _base(
        tax_rate=None,
        total_tax_paise=total,
        cgst_paise=total // 2,
        sgst_paise=total - total // 2,
    )
    t = _by_name(run_import_sanity([r], None, "t"), "Tax Math")
    assert t.affected_count == 1
    assert t.severity == "warning"


def test_check5_inferred_slab_error_no_tax_rate():
    """Inferred slab: diff > tolerance → error."""
    # total 8_000 on taxable 100_000 → infer ~8% → nearest slab 5% → expected 5_000
    # diff = 3_000 > tol 1_000 → error
    r = _base(
        tax_rate=None,
        total_tax_paise=8_000,
        cgst_paise=4_000,
        sgst_paise=4_000,
    )
    t = _by_name(run_import_sanity([r], None, "t"), "Tax Math")
    assert t.severity == "error"


def test_check5_component_mismatch_warning():
    """Component diff within tolerance → warning."""
    # total_tax = 18_000; cgst + sgst = 8_750 + 8_750 = 17_500; diff = 500 ≤ 1_000
    r = _base(
        total_tax_paise=18_000,
        cgst_paise=8_750,
        sgst_paise=8_750,
        igst_paise=0,
    )
    t = _by_name(run_import_sanity([r], None, "t"), "Tax Math")
    assert t.affected_count == 1
    assert t.severity == "warning"


def test_check5_component_mismatch_error():
    """Component diff > tolerance → error."""
    # total_tax = 18_000; cgst + sgst = 2_000; diff = 16_000 > 1_000
    r = _base(
        total_tax_paise=18_000,
        cgst_paise=1_000,
        sgst_paise=1_000,
        igst_paise=0,
    )
    t = _by_name(run_import_sanity([r], None, "t"), "Tax Math")
    assert t.severity == "error"


def test_check5_zero_taxable_skips_inferred_and_matches():
    r = _base(
        tax_rate=None,
        taxable_amount_paise=0,
        total_tax_paise=0,
        cgst_paise=0,
        sgst_paise=0,
        igst_paise=0,
    )
    t = _by_name(run_import_sanity([r], None, "t"), "Tax Math")
    assert t.affected_count == 0
    assert t.passed is True


# ---------------------------------------------------------------------------
# 23–25. Dedup / conflicts / aliases
# ---------------------------------------------------------------------------


def test_invoice_conflict_same_semantic_key_different_amounts():
    a = _base(invoice_number_normalized="SKEY", taxable_amount_paise=100_000)
    b = _base(
        invoice_number_normalized="SKEY",
        taxable_amount_paise=80_000,
        total_tax_paise=14_400,
        cgst_paise=7_200,
        sgst_paise=7_200,
    )
    res = detect_duplicates([a, b])
    assert res["has_conflicts"] is True
    assert res["has_duplicates"] is False
    assert res["counts"]["conflicts"] == 2
    assert res["conflicts"][0].get("_conflict_kind") == "invoice_conflict"


def test_invoice_conflict_against_history_amount_mismatch():
    hist = [_base(taxable_amount_paise=100_000, total_tax_paise=18_000)]
    incoming = _base(
        taxable_amount_paise=99_000,
        total_tax_paise=17_820,
        cgst_paise=8_910,
        sgst_paise=8_910,
    )
    res = detect_duplicates([incoming], existing_records=hist)
    assert res["has_conflicts"] is True
    assert res["counts"]["against_history"] == 0


def test_duplicate_detection_check12_calls_detect_duplicates():
    hist = [_base(invoice_number_normalized="D12")]
    checks = run_import_sanity(
        [_base(invoice_number_normalized="D12")],
        None,
        "t",
        existing_records=hist,
    )
    dup = _by_name(checks, "Duplicate Indicators (Pre-check)")
    assert dup.name == "Duplicate Indicators (Pre-check)"
    assert dup.passed is False
    assert dup.severity == "error"
    assert "Duplicates" in dup.detail

    dup_rec = _by_name(checks, "Duplicate Records")
    assert dup_rec.passed is False
    assert dup_rec.affected_count > 0

    inv_conf = _by_name(checks, "Invoice Conflicts")
    assert inv_conf.passed is True

    rows = [
        _base(
            invoice_number_normalized=f"P-{i}",
            taxable_amount_paise=100_000 + i,
            total_tax_paise=18_000,
            cgst_paise=9_000,
            sgst_paise=9_000,
        )
        for i in range(25)
    ]
    c = _by_name(run_import_sanity(rows, None, "t"), "Unit Consistency")
    assert c.passed is True
    assert c.affected_count == 0
