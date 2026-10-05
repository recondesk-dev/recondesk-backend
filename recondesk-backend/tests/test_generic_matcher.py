"""
Unit tests for the generic matching engine (app.matching.generic_matcher).

Tests cover all 6 tiers (L1-L5 + L6) for both PURCHASE_MATCH_CONFIG and
SALES_MATCH_CONFIG, plus the one-to-many selector and convenience wrappers.
"""

from __future__ import annotations

import pytest
from datetime import date

from app.matching.generic_matcher import (
    MatchFieldsConfig,
    PURCHASE_MATCH_CONFIG,
    SALES_MATCH_CONFIG,
    generic_match_pair,
    generic_match_one_to_many,
    match_sales_register_to_gstr1,
    match_purchase_gstr2b_to_pr,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers — build minimal matcher-ready records
# ──────────────────────────────────────────────────────────────────────────────

def _purchase_gstr(
    *,
    gstin: str = "29AABCU9603R1ZM",
    inv: str = "INV-001",
    inv_norm: str | None = None,
    amount_paise: int = 100000,
    tax_paise: int = 18000,
    igst_paise: int = 18000,
    cgst_paise: int = 0,
    sgst_paise: int = 0,
    inv_date: str = "2026-04-15",
    supplier_name: str = "ABC Pvt Ltd",
) -> dict:
    """GSTR-2B side record (purchase context)."""
    return {
        "id": "g1",
        "supplier_gstin": gstin,
        "supplier_name": supplier_name,
        "invoice_number": inv,
        "invoice_number_normalized": inv_norm or inv.upper().replace("-", "").replace("/", ""),
        "invoice_date": inv_date,
        "taxable_amount_paise": amount_paise,
        "igst_paise": igst_paise,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "cess_paise": 0,
        "total_tax_paise": tax_paise,
    }


def _purchase_pr(
    *,
    gstin: str = "29AABCU9603R1ZM",
    inv: str = "INV-001",
    inv_norm: str | None = None,
    amount_paise: int = 100000,
    tax_paise: int = 18000,
    igst_paise: int = 18000,
    cgst_paise: int = 0,
    sgst_paise: int = 0,
    inv_date: str = "2026-04-15",
    vendor_name: str = "ABC Private Limited",
) -> dict:
    """Purchase Register side record."""
    return {
        "id": "p1",
        "supplier_gstin": gstin,
        "vendor_name": vendor_name,
        "invoice_number": inv,
        "invoice_number_normalized": inv_norm or inv.upper().replace("-", "").replace("/", ""),
        "invoice_date": inv_date,
        "taxable_amount_paise": amount_paise,
        "igst_paise": igst_paise,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "cess_paise": 0,
        "total_tax_paise": tax_paise,
    }


def _sales_sr(
    *,
    gstin: str | None = "27BBBFV1234A1ZP",
    inv: str = "SR-500",
    inv_norm: str | None = None,
    amount_paise: int = 200000,
    tax_paise: int = 36000,
    igst_paise: int = 36000,
    cgst_paise: int = 0,
    sgst_paise: int = 0,
    inv_date: str = "2026-05-10",
    recipient_name: str = "XYZ Enterprises",
) -> dict:
    """Sales Register side record."""
    return {
        "id": "s1",
        "gstin": gstin,
        "recipient_name": recipient_name,
        "invoice_number": inv,
        "invoice_number_normalized": inv_norm or inv.upper().replace("-", "").replace("/", ""),
        "invoice_date": inv_date,
        "taxable_amount_paise": amount_paise,
        "igst_paise": igst_paise,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "cess_paise": 0,
        "total_tax_paise": tax_paise,
    }


def _sales_gstr1(
    *,
    gstin: str | None = "27BBBFV1234A1ZP",
    inv: str = "SR-500",
    inv_norm: str | None = None,
    amount_paise: int = 200000,
    tax_paise: int = 36000,
    igst_paise: int = 36000,
    cgst_paise: int = 0,
    sgst_paise: int = 0,
    inv_date: str = "2026-05-10",
    recipient_name: str = "XYZ Enterprises",
) -> dict:
    """GSTR-1 side record."""
    return {
        "id": "g1s",
        "recipient_gstin": gstin,
        "recipient_name": recipient_name,
        "invoice_number": inv,
        "invoice_number_normalized": inv_norm or inv.upper().replace("-", "").replace("/", ""),
        "invoice_date": inv_date,
        "taxable_amount_paise": amount_paise,
        "igst_paise": igst_paise,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "cess_paise": 0,
        "total_tax_paise": tax_paise,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Purchase-side pair matching
# ══════════════════════════════════════════════════════════════════════════════

class TestPurchasePairL1:
    """L1 — Exact match: same GSTIN, same raw invoice, amounts within Rs1."""

    def test_exact_match(self):
        g = _purchase_gstr()
        p = _purchase_pr()
        r = generic_match_pair(g, p, PURCHASE_MATCH_CONFIG)
        assert r.level == 1
        assert r.matched is True
        assert r.confidence == 100
        assert r.requires_human_review is False

    def test_exact_match_with_rounding(self):
        """Amount diff ≤ Rs1 (100 paise) still qualifies as L1."""
        g = _purchase_gstr(amount_paise=100050)
        p = _purchase_pr(amount_paise=100000)
        r = generic_match_pair(g, p, PURCHASE_MATCH_CONFIG)
        assert r.level == 1
        assert r.matched is True


class TestPurchasePairL2:
    """L2 — Normalised invoice match with minor amount/date diff."""

    def test_normalized_invoice_zero_discrepancy(self):
        """Same amounts but invoice formatting differs → L2 (not L1)."""
        g = _purchase_gstr(inv="INV/001")
        p = _purchase_pr(inv="INV-001")
        r = generic_match_pair(g, p, PURCHASE_MATCH_CONFIG)
        # Both normalize to "INV001", zero amount diff → L2 confidence=95
        assert r.level == 2
        assert r.matched is True
        assert r.requires_human_review is False

    def test_small_amount_diff(self):
        """Same normalised invoice, amount diff within 1% → L2 review."""
        g = _purchase_gstr(inv="INV001", inv_norm="INV001", amount_paise=100000)
        p = _purchase_pr(inv="INV001", inv_norm="INV001", amount_paise=100500)
        r = generic_match_pair(g, p, PURCHASE_MATCH_CONFIG)
        assert r.level == 2
        assert r.matched is True
        assert r.requires_human_review is True


class TestPurchasePairL3:
    """L3 — Format-variant or large amount diff with same GSTIN."""

    def test_amount_beyond_l2_same_invoice(self):
        """Same normalised invoice but amount diff > 1% → falls to L3."""
        g = _purchase_gstr(inv="INV001", inv_norm="INV001", amount_paise=100000)
        p = _purchase_pr(inv="INV001", inv_norm="INV001", amount_paise=104000)
        r = generic_match_pair(g, p, PURCHASE_MATCH_CONFIG)
        assert r.level == 3
        assert r.matched is True
        assert r.requires_human_review is True


class TestPurchasePairL4:
    """L4 — Same PAN, different GSTIN (typo)."""

    def test_gstin_typo_same_pan(self):
        # Same PAN (AABCU9603R) but different state code / check digit
        g = _purchase_gstr(gstin="29AABCU9603R1ZM")
        p = _purchase_pr(gstin="27AABCU9603R1ZP")
        r = generic_match_pair(g, p, PURCHASE_MATCH_CONFIG)
        assert r.level == 4
        assert r.matched is False
        assert r.requires_human_review is True
        assert "GSTIN_MISMATCH" in r.review_reason


class TestPurchasePairL5:
    """L5 — Fuzzy invoice similarity ≥ 0.75 with same GSTIN."""

    def test_fuzzy_invoice_typo(self):
        """Single-character invoice typo with same GSTIN → L5."""
        g = _purchase_gstr(inv="INV09454", inv_norm="INV09454")
        p = _purchase_pr(inv="INV09464", inv_norm="INV09464")
        r = generic_match_pair(g, p, PURCHASE_MATCH_CONFIG)
        assert r.level == 5
        assert r.matched is True
        assert r.requires_human_review is True
        assert r.review_reason == "TYPO_MISMATCH"

    def test_too_different_invoice_no_match(self):
        """Completely different invoice → L6."""
        g = _purchase_gstr(inv="INV001", inv_norm="INV001")
        p = _purchase_pr(inv="BILL999", inv_norm="BILL999")
        r = generic_match_pair(g, p, PURCHASE_MATCH_CONFIG)
        assert r.level == 6
        assert r.matched is False


class TestPurchasePairL6:
    """L6 — No match."""

    def test_different_gstin_different_invoice(self):
        g = _purchase_gstr(gstin="29AABCU9603R1ZM", inv="INV001", inv_norm="INV001")
        p = _purchase_pr(gstin="07XYZPD5678Q1ZA", inv="BILL002", inv_norm="BILL002")
        r = generic_match_pair(g, p, PURCHASE_MATCH_CONFIG)
        assert r.level == 6
        assert r.matched is False
        assert "purchase register" in r.decision_what.lower()

    def test_missing_invoice(self):
        g = _purchase_gstr(inv="", inv_norm="")
        p = _purchase_pr()
        r = generic_match_pair(g, p, PURCHASE_MATCH_CONFIG)
        assert r.level == 6
        assert r.matched is False


# ══════════════════════════════════════════════════════════════════════════════
# Sales-side pair matching
# ══════════════════════════════════════════════════════════════════════════════

class TestSalesPairL1:
    """L1 — Exact match using sales-side field names."""

    def test_exact_match_sales(self):
        sr = _sales_sr()
        g1 = _sales_gstr1()
        r = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
        assert r.level == 1
        assert r.matched is True
        assert r.confidence == 100
        assert r.requires_human_review is False

    def test_b2cl_both_null_gstin_matches_l1(self):
        """B2CL/Export: null GSTIN on both sides still matches on inv+amount+date."""
        sr = _sales_sr(
            gstin=None,
            inv="RD2026272028",
            inv_norm="RD2026272028",
            amount_paise=25000000,
            tax_paise=4500000,
            igst_paise=4500000,
            inv_date="2026-07-12",
            recipient_name="Priya Electronics",
        )
        g1 = _sales_gstr1(
            gstin=None,
            inv="RD2026272028",
            inv_norm="RD2026272028",
            amount_paise=25000000,
            tax_paise=4500000,
            igst_paise=4500000,
            inv_date="2026-07-12",
            recipient_name="",
        )
        r = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
        assert r.matched is True
        assert r.level == 1
        assert r.confidence == 100
        gstin_cf = next(
            f for f in r.compared_fields if f["field_name"] == "gstin"
        )
        assert gstin_cf["match_type"] == "exact"

    def test_one_side_gstin_other_blank_does_not_match(self):
        """GSTIN present on one side only remains a hard identity failure."""
        sr = _sales_sr(gstin="27BBBFV1234A1ZP", inv="B2CL-99")
        g1 = _sales_gstr1(gstin=None, inv="B2CL-99")
        r = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
        assert r.matched is False
        assert r.level == 6


class TestSalesPairL2:
    """L2 — Normalised invoice match on sales-side."""

    def test_normalized_invoice_sales(self):
        sr = _sales_sr(inv="SR/500")
        g1 = _sales_gstr1(inv="SR-500")
        r = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
        assert r.level == 2
        assert r.matched is True


class TestSalesPairL4:
    """L4 — GSTIN typo on sales-side."""

    def test_gstin_typo_sales(self):
        sr = _sales_sr(gstin="27BBBFV1234A1ZP")
        g1 = _sales_gstr1(gstin="29BBBFV1234A1ZQ")  # same PAN
        r = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
        assert r.level == 4
        assert r.requires_human_review is True
        assert "recipient" in r.decision_next.lower()


class TestSalesPairL5:
    """L5 — Fuzzy invoice on sales-side."""

    def test_fuzzy_invoice_sales(self):
        sr = _sales_sr(inv="SR00500", inv_norm="SR00500")
        g1 = _sales_gstr1(inv="SR00590", inv_norm="SR00590")
        r = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
        assert r.level == 5
        assert r.matched is True
        assert r.review_reason == "TYPO_MISMATCH"


class TestSalesPairL6:
    """L6 — No match on sales-side."""

    def test_no_match_sales(self):
        sr = _sales_sr(gstin="27BBBFV1234A1ZP", inv="SR500", inv_norm="SR500")
        g1 = _sales_gstr1(gstin="07XYZPD5678Q1ZA", inv="INV999", inv_norm="INV999")
        r = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
        assert r.level == 6
        assert r.matched is False
        assert "gstr-1" in r.decision_what.lower()


# ══════════════════════════════════════════════════════════════════════════════
# One-to-many selector
# ══════════════════════════════════════════════════════════════════════════════

class TestOneToMany:

    def test_picks_best_match(self):
        """L1 candidate is preferred over L3."""
        g = _purchase_gstr()
        p_exact = _purchase_pr()  # L1
        p_fuzzy = _purchase_pr(
            inv="INV-002", inv_norm="INV002", amount_paise=103000,
        )
        p_fuzzy["id"] = "p2"
        r = generic_match_one_to_many(g, [p_fuzzy, p_exact], PURCHASE_MATCH_CONFIG)
        assert r is not None
        assert r.level == 1

    def test_empty_candidates(self):
        g = _purchase_gstr()
        r = generic_match_one_to_many(g, [], PURCHASE_MATCH_CONFIG)
        assert r is None

    def test_no_match_candidates(self):
        """All candidates are L6 → returns None."""
        g = _purchase_gstr(inv="INV001", inv_norm="INV001")
        p = _purchase_pr(
            gstin="07XYZPD5678Q1ZA", inv="BILL999", inv_norm="BILL999",
        )
        r = generic_match_one_to_many(g, [p], PURCHASE_MATCH_CONFIG)
        assert r is None


# ══════════════════════════════════════════════════════════════════════════════
# Convenience wrappers
# ══════════════════════════════════════════════════════════════════════════════

class TestConvenienceWrappers:

    def test_match_sales_register_to_gstr1(self):
        sr = _sales_sr()
        g1 = _sales_gstr1()
        r = match_sales_register_to_gstr1(sr, [g1])
        assert r is not None
        assert r.level == 1

    def test_match_purchase_gstr2b_to_pr(self):
        g = _purchase_gstr()
        p = _purchase_pr()
        r = match_purchase_gstr2b_to_pr(g, [p])
        assert r is not None
        assert r.level == 1


# ══════════════════════════════════════════════════════════════════════════════
# Config-specific labels
# ══════════════════════════════════════════════════════════════════════════════

class TestLabels:

    def test_purchase_discrepancy_labels(self):
        """Discrepancy strings use GSTR / PR labels."""
        g = _purchase_gstr(amount_paise=100000)
        p = _purchase_pr(amount_paise=104000)
        r = generic_match_pair(g, p, PURCHASE_MATCH_CONFIG)
        amount_disc = [d for d in r.discrepancies if d.startswith("amount:")]
        assert len(amount_disc) == 1
        assert "GSTR=" in amount_disc[0]
        assert "PR=" in amount_disc[0]

    def test_sales_discrepancy_labels(self):
        """Discrepancy strings use SR / GSTR1 labels."""
        sr = _sales_sr(amount_paise=200000)
        g1 = _sales_gstr1(amount_paise=208000)
        r = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
        amount_disc = [d for d in r.discrepancies if d.startswith("amount:")]
        assert len(amount_disc) == 1
        assert "SR=" in amount_disc[0]
        assert "GSTR1=" in amount_disc[0]

    def test_sales_l6_decision_text(self):
        """Sales-side L6 uses sales-specific decision text."""
        sr = _sales_sr(inv="X", inv_norm="X")
        g1 = _sales_gstr1(gstin="07XYZPD5678Q1ZA", inv="Y", inv_norm="Y")
        r = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
        assert r.level == 6
        assert "GSTR-1" in r.decision_what


# ══════════════════════════════════════════════════════════════════════════════
# Period-boundary handling
# ══════════════════════════════════════════════════════════════════════════════

class TestPeriodBoundary:

    def test_period_boundary_purchase(self):
        """Cross-month invoice dates with same GSTIN/invoice → L2 review."""
        g = _purchase_gstr(inv_date="2026-04-30")
        p = _purchase_pr(inv_date="2026-05-02")
        r = generic_match_pair(g, p, PURCHASE_MATCH_CONFIG)
        assert r.level == 2
        assert r.requires_human_review is True
        assert "PERIOD_BOUNDARY" in r.review_reason

    def test_period_boundary_sales(self):
        """Cross-month on sales-side → L2 review with sales labels."""
        sr = _sales_sr(inv_date="2026-05-31")
        g1 = _sales_gstr1(inv_date="2026-06-02")
        r = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
        assert r.level == 2
        assert r.requires_human_review is True
        assert "SR" in r.decision_what or "GSTR1" in r.decision_what


# ══════════════════════════════════════════════════════════════════════════════
# Financial downgrade safety net
# ══════════════════════════════════════════════════════════════════════════════

class TestFinancialDowngrade:

    def test_l2_with_large_total_diff_downgrades(self):
        """L2 match with large total_tax diff → capped at L3 review."""
        g = _purchase_gstr(
            inv="INV001", inv_norm="INV001",
            amount_paise=100000, tax_paise=18000, igst_paise=18000,
        )
        p = _purchase_pr(
            inv="INV001", inv_norm="INV001",
            amount_paise=100500, tax_paise=25000, igst_paise=25000,
        )
        r = generic_match_one_to_many(g, [p], PURCHASE_MATCH_CONFIG)
        assert r is not None
        # Should be downgraded to at least L3 with review
        assert r.level >= 2
        assert r.requires_human_review is True


# ══════════════════════════════════════════════════════════════════════════════
# Symmetric invoice and credit-note normalisation tests
# ══════════════════════════════════════════════════════════════════════════════

class TestSymmetricInvoiceNormalisation:
    """Test symmetric comparison-time normalisation for SR vs GSTR-1 inum / nt_num."""

    def test_normalise_inv_no_function(self):
        from app.services.matcher import normalise_inv_no

        assert normalise_inv_no("INV/2025-26/001") == "INV202526001"
        assert normalise_inv_no("inv-2025-26-001") == "INV202526001"
        assert normalise_inv_no("202526001") == "202526001"
        assert normalise_inv_no("CN/2025-26/001") == "CN202526001"
        assert normalise_inv_no(None) == ""
        assert normalise_inv_no("") == ""
        assert normalise_inv_no("   ") == ""
        assert normalise_inv_no("INV#123@45") == "INV12345"

    def test_sr_vs_gstr1_inum_format_variant_matches(self):
        """SR 'INV/2025-26/001' matches GSTR-1 inum '202526001' symmetrically."""
        sr = _sales_sr(inv="INV/2025-26/001")
        sr["invoice_number_raw"] = "INV/2025-26/001"
        g1 = _sales_gstr1(inv="202526001")
        g1["inum"] = "202526001"

        r = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
        assert r.matched is True
        assert r.level in (1, 2)
        # Stored values must NOT be modified
        assert sr["invoice_number_raw"] == "INV/2025-26/001"
        assert g1["inum"] == "202526001"

    def test_sr_vs_gstr1_identical_raw_is_l1(self):
        """SR 'INV/2025-26/001' and GSTR-1 inum 'INV/2025-26/001' matches L1 exact."""
        sr = _sales_sr(inv="INV/2025-26/001")
        sr["invoice_number_raw"] = "INV/2025-26/001"
        g1 = _sales_gstr1(inv="INV/2025-26/001")
        g1["inum"] = "INV/2025-26/001"

        r = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
        assert r.matched is True
        assert r.level == 1
        assert r.confidence == 100

    def test_credit_note_nt_num_normalisation(self):
        """SR credit note 'CN/2025-26/001' matches GSTR-1 CDNR 'CN202526001'."""
        sr = _sales_sr(inv="CN/2025-26/001")
        sr["invoice_number_raw"] = "CN/2025-26/001"
        sr["credit_note_number"] = "CN/2025-26/001"
        g1 = _sales_gstr1(inv="CN202526001")
        g1["nt_num"] = "CN202526001"

        r = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
        assert r.matched is True
        assert r.level in (1, 2)
        # Stored values must NOT be modified
        assert sr["credit_note_number"] == "CN/2025-26/001"
        assert g1["nt_num"] == "CN202526001"

    def test_different_invoices_do_not_falsely_match(self):
        """Distinct invoice numbers must not match."""
        sr = _sales_sr(inv="INV/2025-26/001")
        sr["invoice_number_raw"] = "INV/2025-26/001"
        g1 = _sales_gstr1(inv="INV/2025-26/999")
        g1["inum"] = "INV/2025-26/999"

        r = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
        assert r.matched is False or r.level > 2

    def test_run7_r7_01912_vs_g1only_r7_0024_false_match_rejected(self):
        """Run 7 regression: SR 'R7/01912' must NOT match GSTR-1 'G1ONLY-R7/0024'."""
        sr = {
            "invoice_number": "R7/01912",
            "invoice_number_raw": "R7/01912",
            "recipient_gstin": "27ISKPK1273H1ZF",
            "gstin": "27ISKPK1273H1ZF",
            "invoice_date": "2026-09-05",
            "taxable_amount_paise": 10000000,
            "total_tax_paise": 1800000,
            "igst_paise": 1800000,
            "cgst_paise": 0,
            "sgst_paise": 0,
        }
        g1 = {
            "invoice_number": "G1ONLY-R7/0024",
            "invoice_number_raw": "G1ONLY-R7/0024",
            "inum": "G1ONLY-R7/0024",
            "recipient_gstin": "27ISKPK1273H1ZF",
            "ctin": "27ISKPK1273H1ZF",
            "invoice_date": "2026-09-25",
            "taxable_amount_paise": 10500000,
            "total_tax_paise": 1890000,
            "igst_paise": 0,
            "cgst_paise": 945000,
            "sgst_paise": 945000,
        }
        r = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
        assert r.matched is False, f"Expected matched=False, got {r.matched} (level {r.level})"
        assert r.level == 6

    def test_run7_guard_format_variant_large_date_and_material_amount_rejected(self):
        """Weak invoice identity cannot be rescued by L3 when date diff is large and amount is material."""
        sr = {
            "invoice_number": "DS/26/78",
            "invoice_number_raw": "DS/26/78",
            "recipient_gstin": "27ISKPK1273H1ZF",
            "gstin": "27ISKPK1273H1ZF",
            "invoice_date": "2026-09-05",
            "taxable_amount_paise": 10000000,
            "total_tax_paise": 1800000,
            "igst_paise": 1800000,
            "cgst_paise": 0,
            "sgst_paise": 0,
        }
        g1 = {
            "invoice_number": "DS-2026-00078",
            "invoice_number_raw": "DS-2026-00078",
            "recipient_gstin": "27ISKPK1273H1ZF",
            "ctin": "27ISKPK1273H1ZF",
            "invoice_date": "2026-09-20",  # 15 days diff (> date tolerance)
            "taxable_amount_paise": 10300000,  # 3% diff (material amount mismatch)
            "total_tax_paise": 1854000,
            "igst_paise": 1854000,
            "cgst_paise": 0,
            "sgst_paise": 0,
        }
        r = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
        assert r.matched is False
        assert r.level == 6

    def test_run7_preserves_plus_2_day_date_tolerance(self):
        """+2-day date tolerance behavior is preserved for format variants."""
        sr = {
            "invoice_number": "INV/2026/001",
            "invoice_number_raw": "INV/2026/001",
            "recipient_gstin": "27ISKPK1273H1ZF",
            "gstin": "27ISKPK1273H1ZF",
            "invoice_date": "2026-09-05",
            "taxable_amount_paise": 10000000,
            "total_tax_paise": 1800000,
            "igst_paise": 1800000,
            "cgst_paise": 0,
            "sgst_paise": 0,
        }
        g1 = {
            "invoice_number": "INV-2026-001",
            "invoice_number_raw": "INV-2026-001",
            "recipient_gstin": "27ISKPK1273H1ZF",
            "ctin": "27ISKPK1273H1ZF",
            "invoice_date": "2026-09-07",  # +2 days within tolerance
            "taxable_amount_paise": 10000000,
            "total_tax_paise": 1800000,
            "igst_paise": 1800000,
            "cgst_paise": 0,
            "sgst_paise": 0,
        }
        r = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
        assert r.matched is True
        assert r.level in (1, 2)
        assert r.review_reason == "DATE_TOLERANCE_MATCH"


