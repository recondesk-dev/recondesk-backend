"""
test_gstin_traps.py
Scenario: GSTIN matching failures that cause silent ITC loss.
Run: PYTHONPATH=. pytest tests/test_gstin_traps.py -v
"""
import pytest
from datetime import date
from app.services.matcher import match_gstr_to_pr, normalize_invoice

def make_gstr(gstin="27ABCDE1234F1Z0", invoice="INV001",
              invoice_date="2024-04-01", taxable_paise=100000,
              igst_paise=0, cgst_paise=9000, sgst_paise=9000):
    return {
        "supplier_gstin": gstin,
        "invoice_number_normalized": normalize_invoice(invoice),
        "invoice_number": invoice,
        "invoice_date": date.fromisoformat(invoice_date),
        "taxable_amount_paise": taxable_paise,
        "igst_paise": igst_paise,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "total_tax_paise": igst_paise + cgst_paise + sgst_paise,
    }

def make_pr(gstin="27ABCDE1234F1Z0", invoice="INV001",
            invoice_date="2024-04-01", taxable_paise=100000,
            igst_paise=0, cgst_paise=9000, sgst_paise=9000, id="pr-001"):
    return {
        "id": id,
        "supplier_gstin": gstin,
        "invoice_number_normalized": normalize_invoice(invoice),
        "invoice_number": invoice,
        "invoice_date": date.fromisoformat(invoice_date),
        "taxable_amount_paise": taxable_paise,
        "igst_paise": igst_paise,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "total_tax_paise": igst_paise + cgst_paise + sgst_paise,
    }

class TestGSTINCase:
    def test_lowercase_gstin_in_pr_causes_no_match(self):
        g = make_gstr(gstin="27ABCDE1234F1Z0")
        p = make_pr(gstin="27abcde1234f1z0")
        result = match_gstr_to_pr(g, [p])
        if result is None or not result.matched:
            pytest.fail(
                "BUG: Lowercase GSTIN in purchase register causes L6 (no match).\n"
                "Fix: normalize supplier_gstin to uppercase in PR parser or _gstin_match_spec."
            )

    def test_uppercase_gstin_both_sides_is_L1(self):
        g = make_gstr(gstin="27ABCDE1234F1Z0")
        p = make_pr(gstin="27ABCDE1234F1Z0")
        result = match_gstr_to_pr(g, [p])
        assert result is not None and result.level == 1

class TestGSTINWhitespace:
    def test_trailing_space_in_pr_gstin_causes_no_match(self):
        g = make_gstr(gstin="27ABCDE1234F1Z0")
        p = make_pr(gstin="27ABCDE1234F1Z0 ")
        result = match_gstr_to_pr(g, [p])
        if result is None or not result.matched:
            pytest.fail(
                "BUG: Trailing space in GSTIN causes L6.\n"
                "Fix: strip() GSTIN in _gstin_match_spec or at parser level."
            )

    def test_leading_space_in_gstr_gstin_causes_no_match(self):
        g = make_gstr(gstin=" 27ABCDE1234F1Z0")
        p = make_pr(gstin="27ABCDE1234F1Z0")
        result = match_gstr_to_pr(g, [p])
        if result is None or not result.matched:
            pytest.fail(
                "BUG: Leading space in GSTR GSTIN causes L6.\n"
                "Fix: strip() both sides in _gstin_match_spec."
            )

class TestGSTINValidity:
    def test_different_state_code_always_L6(self):
        g = make_gstr(gstin="27ABCDE1234F1Z0")
        p = make_pr(gstin="29ABCDE1234F1Z0")
        result = match_gstr_to_pr(g, [p])
        assert result is None or not result.matched, (
            "CRITICAL: Different state code GSTINs must never match. ITC fraud risk."
        )

    def test_different_pan_in_gstin_always_L6(self):
        g = make_gstr(gstin="27ABCDE1234F1Z0")
        p = make_pr(gstin="27XYZDE1234F1Z0")
        result = match_gstr_to_pr(g, [p])
        assert result is None or not result.matched, (
            "Different PAN in GSTIN must never match."
        )

    def test_empty_gstin_in_pr_always_L6(self):
        g = make_gstr(gstin="27ABCDE1234F1Z0")
        p = make_pr(gstin="")
        result = match_gstr_to_pr(g, [p])
        assert result is None or not result.matched

    def test_none_gstin_in_pr_always_L6(self):
        g = make_gstr(gstin="27ABCDE1234F1Z0")
        p = make_pr(gstin="27ABCDE1234F1Z0")
        p["supplier_gstin"] = None
        result = match_gstr_to_pr(g, [p])
        assert result is None or not result.matched, (
            "None GSTIN in PR must not crash and must not match."
        )

    def test_correct_gstin_one_wrong_gstin_picks_correct(self):
        g = make_gstr(gstin="27ABCDE1234F1Z0")
        p_wrong   = make_pr(gstin="29ABCDE1234F1Z0", id="wrong")
        p_correct = make_pr(gstin="27ABCDE1234F1Z0", id="correct")
        result = match_gstr_to_pr(g, [p_wrong, p_correct])
        assert result is not None and result.level == 1, (
            "Matcher must ignore wrong-GSTIN candidate and match correct one at L1."
        )
