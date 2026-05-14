"""
test_amount_bands.py
Scenario: Amount tolerance band boundaries between L1, L2, L3, and L6.
Run: PYTHONPATH=. pytest tests/test_amount_bands.py -v
"""
import pytest
from datetime import date
from app.services.matcher import match_gstr_to_pr, normalize_invoice

def make_gstr(taxable_paise, invoice="INV001", gstin="27ABCDE1234F1Z0",
              invoice_date="2024-04-01", igst_paise=0, cgst_paise=9000, sgst_paise=9000):
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

def make_pr(taxable_paise, invoice="INV001", gstin="27ABCDE1234F1Z0",
            invoice_date="2024-04-01", igst_paise=0, cgst_paise=9000, sgst_paise=9000, id="pr-001"):
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

class TestL1Boundary:
    def test_zero_diff_is_L1(self):
        g = make_gstr(taxable_paise=100000)
        p = make_pr(taxable_paise=100000)
        result = match_gstr_to_pr(g, [p])
        assert result is not None and result.level == 1

    def test_exactly_rs1_diff_is_L1(self):
        g = make_gstr(taxable_paise=100000)
        p = make_pr(taxable_paise=100100)
        result = match_gstr_to_pr(g, [p])
        assert result is not None and result.level == 1, (
            f"Rs1 diff must be L1. Got L{getattr(result,'level',None)}."
        )

    def test_rs1_plus_one_paise_is_not_L1(self):
        g = make_gstr(taxable_paise=100000)
        p = make_pr(taxable_paise=100101)
        result = match_gstr_to_pr(g, [p])
        assert result is not None and result.level != 1, (
            "101 paise diff must not be L1. System is being too lenient."
        )

class TestL2Boundary:
    def test_large_invoice_rs100_diff_is_L2(self):
        g = make_gstr(taxable_paise=10000000)
        p = make_pr(taxable_paise=9990000)
        result = match_gstr_to_pr(g, [p])
        assert result is not None and result.level == 2, (
            f"Rs100 on Rs1L invoice (0.1%) must be L2. Got L{getattr(result,'level',None)}."
        )

    def test_small_invoice_rs60_diff_is_NOT_L2(self):
        """
        Rs60 on Rs5000 invoice = 1.2% — exceeds 1% threshold.
        Must NOT be L2 auto-accept. CA expects auto-accept but gets L3 review.
        This is a real surprise for CAs with small invoices.
        """
        g = make_gstr(taxable_paise=500000)
        p = make_pr(taxable_paise=494000)
        result = match_gstr_to_pr(g, [p])
        assert result is not None and result.level != 2, (
            f"Rs60 on Rs5000 invoice (1.2%) must NOT be L2. Got L{getattr(result,'level',None)}."
        )

    def test_exactly_1pct_diff_boundary(self):
        g = make_gstr(taxable_paise=1000000)
        p = make_pr(taxable_paise=990000)
        result = match_gstr_to_pr(g, [p])
        assert result is not None and result.level == 2, (
            f"Exactly 1.0% diff must be L2 (inclusive boundary). Got L{getattr(result,'level',None)}."
        )

    def test_just_above_1pct_is_not_L2(self):
        g = make_gstr(taxable_paise=1000000)
        p = make_pr(taxable_paise=989900)
        result = match_gstr_to_pr(g, [p])
        assert result is not None and result.level != 2, (
            f"1.01% diff must not be L2. Got L{getattr(result,'level',None)}."
        )

class TestL3Boundary:
    def test_exactly_5pct_diff_is_L3(self):
        g = make_gstr(taxable_paise=1000000)
        p = make_pr(taxable_paise=950000)
        result = match_gstr_to_pr(g, [p])
        assert result is not None and result.level == 3, (
            f"Exactly 5% diff must be L3. Got L{getattr(result,'level',None)}."
        )

    def test_above_5pct_is_L6(self):
        g = make_gstr(taxable_paise=1000000)
        p = make_pr(taxable_paise=940000)
        result = match_gstr_to_pr(g, [p])
        assert result is None or not result.matched, (
            f"6% diff must be L6 (no match). Got L{getattr(result,'level',None)}."
        )

    def test_L3_requires_human_review(self):
        g = make_gstr(taxable_paise=1000000)
        p = make_pr(taxable_paise=970000)
        result = match_gstr_to_pr(g, [p])
        assert result is not None and result.level == 3
        assert result.requires_human_review is True, (
            "L3 match must always require human review."
        )

    def test_L3_confidence_is_75(self):
        g = make_gstr(taxable_paise=1000000)
        p = make_pr(taxable_paise=970000)
        result = match_gstr_to_pr(g, [p])
        assert result is not None and result.confidence == 75, (
            f"L3 confidence must be 75. Got {getattr(result,'confidence',None)}."
        )

class TestTaxStructureWithAmounts:
    def test_igst_vs_cgst_sgst_same_taxable_is_L3_review(self):
        g = make_gstr(taxable_paise=100000, igst_paise=18000, cgst_paise=0, sgst_paise=0)
        p = make_pr(taxable_paise=100000, igst_paise=0, cgst_paise=9000, sgst_paise=9000)
        result = match_gstr_to_pr(g, [p])
        assert result is not None, "Must produce a result."
        assert result.level >= 3, (
            f"IGST vs CGST+SGST must be L3 or worse. Got L{result.level}."
        )
        assert result.requires_human_review is True

    def test_igst_both_sides_same_amount_is_L1(self):
        g = make_gstr(taxable_paise=100000, igst_paise=18000, cgst_paise=0, sgst_paise=0)
        p = make_pr(taxable_paise=100000, igst_paise=18000, cgst_paise=0, sgst_paise=0)
        result = match_gstr_to_pr(g, [p])
        assert result is not None and result.level == 1

    def test_cgst_sgst_both_sides_same_amount_is_L1(self):
        g = make_gstr(taxable_paise=100000, igst_paise=0, cgst_paise=9000, sgst_paise=9000)
        p = make_pr(taxable_paise=100000, igst_paise=0, cgst_paise=9000, sgst_paise=9000)
        result = match_gstr_to_pr(g, [p])
        assert result is not None and result.level == 1

class TestDateAndAmountCombined:
    def test_rs1_diff_date_3days_is_L1(self):
        g = make_gstr(taxable_paise=100000, invoice_date="2024-04-01")
        p = make_pr(taxable_paise=100100, invoice_date="2024-04-04")
        result = match_gstr_to_pr(g, [p])
        assert result is not None and result.level == 1

    def test_rs1_diff_date_4days_is_not_L1(self):
        g = make_gstr(taxable_paise=100000, invoice_date="2024-04-01")
        p = make_pr(taxable_paise=100100, invoice_date="2024-04-05")
        result = match_gstr_to_pr(g, [p])
        assert result is None or result.level != 1, (
            "Rs1 diff + 4-day date gap must not be L1."
        )

    def test_large_diff_date_within_l2_is_L3(self):
        g = make_gstr(taxable_paise=1000000, invoice_date="2024-04-01")
        p = make_pr(taxable_paise=970000, invoice_date="2024-04-06")
        result = match_gstr_to_pr(g, [p])
        assert result is not None and result.level == 3
        assert result.requires_human_review is True

    def test_large_diff_date_beyond_l2_is_L6(self):
        g = make_gstr(taxable_paise=1000000, invoice_date="2024-04-01")
        p = make_pr(taxable_paise=970000, invoice_date="2024-04-10")
        result = match_gstr_to_pr(g, [p])
        assert result is None or not result.matched, (
            f"3% diff + 9-day date gap must be L6. Got L{getattr(result,'level',None)}."
        )

class TestL5AmountTolerance:
    def test_within_rs50_fuzzy_invoice_fires_L5(self):
        g = make_gstr(invoice="INV001", taxable_paise=100000)
        p = make_pr(invoice="INV002", taxable_paise=100000)
        result = match_gstr_to_pr(g, [p])
        if result is not None and result.matched:
            assert result.level == 5, (
                f"Fuzzy consecutive invoice match must be L5 only. Got L{result.level}."
            )
            assert result.requires_human_review is True

    def test_beyond_rs50_fuzzy_invoice_is_L6(self):
        g = make_gstr(invoice="INV001", taxable_paise=100000)
        p = make_pr(invoice="INV002", taxable_paise=105100)
        result = match_gstr_to_pr(g, [p])
        assert result is None or not result.matched, (
            f"Rs51 diff on fuzzy invoice must be L6. Got L{getattr(result,'level',None)}."
        )
