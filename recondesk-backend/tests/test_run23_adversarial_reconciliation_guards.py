"""Regression tests for Run 23 Adversarial Reconciliation Guards.

Covers:
1. Multi-OCR Safety:
   - 1 OCR substitution -> can match
   - 2+ OCR substitutions -> review (OCR_CONFIDENCE_REVIEW)
   - 2+ OCR substitutions + prefix alteration -> review
2. Prefix Alteration Safety:
   - SUP/0926/00123 vs SUP-0926-00123 -> match
   - SUP/0926/00123 vs XSUP/0926/00123 -> review (PREFIX_ALTERATION_REVIEW)
   - SI-02392-A vs SI-02392-A/BR01 -> preserve existing intended behavior (match)
3. Terminal-Sequence Hard Guard:
   - PR: SUP000002 vs 2B: XSUP000039 (same GSTIN/date/amount) -> no candidate link
   - Both rows remain unmatched (Wrongful Risk on PR, Missed ITC on 2B)
4. Canonical Date Tolerance Policy:
   - GSTR-2B L1 tolerance = 3 days (DATE_TOLERANCE_L1_DAYS == 3)
   - GSTR-1 outward tolerance = 2 days (GSTR1_INVOICE_DATE_TOLERANCE_DAYS == 2)
5. Conflicting Duplicate Classification:
   - Identical duplicate -> duplicate entry
   - Conflicting duplicate amount -> duplicate review (PR_CLAIMED_BY_BETTER_MATCH), not wrongful ITC risk
   - Same invoice number from different GSTINs -> NOT duplicate across vendors
"""

from datetime import date
import pytest

from app.services.matcher import (
    DATE_TOLERANCE_L1_DAYS,
    _match_gstr_to_pr_pair,
    is_sequential_series_mismatch,
    is_invoice_format_variant,
    count_ocr_substitutions,
    analyze_invoice_evidence,
)
from app.rules.gstr1_rules import GSTR1_INVOICE_DATE_TOLERANCE_DAYS
from app.matching.engine import run_bidirectional_reconciliation


# ── 1. MULTI-OCR SAFETY ────────────────────────────────────────────────────────


def test_single_ocr_substitution_can_match():
    """1 OCR substitution can clean match when GSTIN/date/economics align."""
    gstr = {
        "invoice_number": "BILL-00042O",
        "invoice_number_normalized": "BILL42O",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    pr = {
        "invoice_number": "BILL-000420",
        "invoice_number_normalized": "BILL420",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    res = _match_gstr_to_pr_pair(gstr, pr)
    assert res.matched is True
    assert res.requires_human_review is False
    assert res.level == 2


def test_multi_ocr_substitutions_routes_to_review():
    """2+ OCR substitutions must NOT clean match; route to Review Required (OCR_CONFIDENCE_REVIEW)."""
    gstr = {
        "invoice_number": "BILLO0042O",
        "invoice_number_normalized": "BILLO42O",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    pr = {
        "invoice_number": "BILL000420",
        "invoice_number_normalized": "BILL420",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    res = _match_gstr_to_pr_pair(gstr, pr)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason == "OCR_CONFIDENCE_REVIEW"


def test_multi_ocr_with_prefix_alteration_routes_to_review():
    """2+ OCR substitutions + prefix alteration must route to Review Required."""
    gstr = {
        "invoice_number": "XBILLO0042O",
        "invoice_number_normalized": "XBILLO42O",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    pr = {
        "invoice_number": "BILL000420",
        "invoice_number_normalized": "BILL420",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    res = _match_gstr_to_pr_pair(gstr, pr)
    assert res.matched is True
    assert res.requires_human_review is True


# ── 2. PREFIX ALTERATION SAFETY ───────────────────────────────────────────────


def test_delimiter_variant_matches_cleanly():
    """SUP/0926/00123 vs SUP-0926-00123 is a safe format variant and clean matches."""
    gstr = {
        "invoice_number": "SUP/0926/00123",
        "invoice_number_normalized": "SUP926123",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    pr = {
        "invoice_number": "SUP-0926-00123",
        "invoice_number_normalized": "SUP926123",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    res = _match_gstr_to_pr_pair(gstr, pr)
    assert res.matched is True
    assert res.requires_human_review is False


def test_prefix_alteration_routes_to_review():
    """SUP/0926/00123 vs XSUP/0926/00123 must route to Review Required (PREFIX_ALTERATION_REVIEW)."""
    gstr = {
        "invoice_number": "XSUP/0926/00123",
        "invoice_number_normalized": "XSUP926123",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    pr = {
        "invoice_number": "SUP/0926/00123",
        "invoice_number_normalized": "SUP926123",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    res = _match_gstr_to_pr_pair(gstr, pr)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason == "PREFIX_ALTERATION_REVIEW"


def test_branch_suffix_variant_preserves_clean_match():
    """SI-02392-A vs SI-02392-A/BR01 preserves intended clean matching behavior."""
    gstr = {
        "invoice_number": "SI-02392-A/BR01",
        "invoice_number_normalized": "SI2392ABR01",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    pr = {
        "invoice_number": "SI-02392-A",
        "invoice_number_normalized": "SI2392A",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    res = _match_gstr_to_pr_pair(gstr, pr)
    assert res.matched is True
    assert res.requires_human_review is False


# ── 3. TERMINAL-SEQUENCE HARD GUARD ───────────────────────────────────────────


def test_terminal_sequence_decoy_rejected():
    """PR: SUP000002 vs 2B: XSUP000039 with identical GSTIN/date/amount must NOT link."""
    gstr_records = [
        {
            "id": "g_decoy",
            "invoice_number": "XSUP000039",
            "invoice_number_normalized": "XSUP39",
            "supplier_gstin": "27AAPFU0939F1ZV",
            "invoice_date": "2026-09-15",
            "taxable_paise": 5000000,
            "total_tax_paise": 900000,
            "igst_paise": 900000,
            "cgst_paise": 0,
            "sgst_paise": 0,
        }
    ]
    pr_records = [
        {
            "id": "p_decoy",
            "invoice_number": "SUP000002",
            "invoice_number_normalized": "SUP2",
            "supplier_gstin": "27AAPFU0939F1ZV",
            "invoice_date": "2026-09-15",
            "taxable_paise": 5000000,
            "total_tax_paise": 900000,
            "igst_paise": 900000,
            "cgst_paise": 0,
            "sgst_paise": 0,
        }
    ]
    res = run_bidirectional_reconciliation(gstr_records, pr_records)
    assert len(res["matched"]) == 0
    assert len(res["review_required"]) == 0
    assert len(res["missed_itc"]) == 1
    assert len(res["wrongful_itc_risk"]) == 1
    assert res["missed_itc"][0]["gstr_id"] == "g_decoy"
    assert res["wrongful_itc_risk"][0]["id"] == "p_decoy"


def test_is_sequential_series_mismatch_catches_decoy():
    """Sequential series mismatch helper flags distinct terminal sequences across prefixes."""
    assert is_sequential_series_mismatch("XSUP39", "SUP2", "XSUP000039", "SUP000002") is True


# ── 4. CANONICAL DATE TOLERANCE POLICY ─────────────────────────────────────────


def test_canonical_date_tolerance_policy():
    """Verify single source of truth for date tolerance policies across modules."""
    # GSTR-2B ↔ PR reconciliation canonical L1 tolerance is 3 days:
    assert DATE_TOLERANCE_L1_DAYS == 3
    # GSTR-1 outward supplies canonical invoice tolerance is 2 days:
    assert GSTR1_INVOICE_DATE_TOLERANCE_DAYS == 2


# ── 5. CONFLICTING DUPLICATE CLASSIFICATION ───────────────────────────────────


def test_identical_duplicate_classified_as_duplicate_entry():
    """Identical ERP duplicate rows: primary matches GSTR; surplus is DUPLICATE_ENTRY."""
    gstr_records = [
        {
            "id": "g_1",
            "invoice_number": "INV-00100",
            "invoice_number_normalized": "INV100",
            "supplier_gstin": "27AAPFU0939F1ZV",
            "invoice_date": "2026-09-15",
            "taxable_paise": 1000000,
            "total_tax_paise": 180000,
            "igst_paise": 180000,
            "cgst_paise": 0,
            "sgst_paise": 0,
        }
    ]
    pr_records = [
        {
            "id": "p_prim",
            "invoice_number": "INV-00100",
            "invoice_number_normalized": "INV100",
            "supplier_gstin": "27AAPFU0939F1ZV",
            "invoice_date": "2026-09-15",
            "taxable_paise": 1000000,
            "total_tax_paise": 180000,
            "igst_paise": 180000,
            "cgst_paise": 0,
            "sgst_paise": 0,
        },
        {
            "id": "p_dup",
            "invoice_number": "INV-00100",
            "invoice_number_normalized": "INV100",
            "supplier_gstin": "27AAPFU0939F1ZV",
            "invoice_date": "2026-09-15",
            "taxable_paise": 1000000,
            "total_tax_paise": 180000,
            "igst_paise": 180000,
            "cgst_paise": 0,
            "sgst_paise": 0,
        },
    ]
    res = run_bidirectional_reconciliation(gstr_records, pr_records)
    assert len(res["matched"]) == 1
    assert len(res["duplicate_entries"]) == 1
    assert len(res["wrongful_itc_risk"]) == 0
    assert {res["matched"][0]["pr_id"], res["duplicate_entries"][0]["id"]} == {"p_prim", "p_dup"}
    assert res["duplicate_entries"][0]["reason"] == "DUPLICATE_ENTRY"


def test_conflicting_duplicate_amount_classified_as_claimed_by_better_match():
    """Surplus ERP duplicate with conflicting amount is classified as duplicate exception, NOT wrongful risk."""
    gstr_records = [
        {
            "id": "g_1",
            "invoice_number": "PO/26-27/00035",
            "invoice_number_normalized": "PO262700035",
            "supplier_gstin": "08IXMPE2332H1ZF",
            "invoice_date": "2026-09-01",
            "taxable_paise": 5798022,
            "total_tax_paise": 1043644,
            "igst_paise": 1043644,
            "cgst_paise": 0,
            "sgst_paise": 0,
        }
    ]
    pr_records = [
        {
            "id": "p_primary",
            "invoice_number": "PO/26-27/00035",
            "invoice_number_normalized": "PO262700035",
            "supplier_gstin": "08IXMPE2332H1ZF",
            "invoice_date": "2026-09-01",
            "taxable_paise": 5798022,
            "total_tax_paise": 1043644,
            "igst_paise": 1043644,
            "cgst_paise": 0,
            "sgst_paise": 0,
        },
        {
            "id": "p_surplus_conflicting",
            "invoice_number": "PO/26-27/00035",
            "invoice_number_normalized": "PO262700035",
            "supplier_gstin": "08IXMPE2332H1ZF",
            "invoice_date": "2026-09-01",
            "taxable_paise": 6230128,  # > 7% conflicting amount
            "total_tax_paise": 1121423,
            "igst_paise": 1121423,
            "cgst_paise": 0,
            "sgst_paise": 0,
        },
    ]
    res = run_bidirectional_reconciliation(gstr_records, pr_records)
    assert len(res["matched"]) == 1
    assert res["matched"][0]["pr_id"] == "p_primary"
    assert len(res["duplicate_entries"]) == 1
    assert res["duplicate_entries"][0]["id"] == "p_surplus_conflicting"
    assert res["duplicate_entries"][0]["reason"] == "PR_CLAIMED_BY_BETTER_MATCH"
    assert len(res["wrongful_itc_risk"]) == 0


def test_same_invoice_from_different_gstins_not_duplicate():
    """Same invoice number issued by different GSTINs are distinct vendors, NOT duplicates."""
    gstr_records = [
        {
            "id": "g_v1",
            "invoice_number": "INV-2026-001",
            "invoice_number_normalized": "INV2026001",
            "supplier_gstin": "27AAPFU0939F1ZV",
            "invoice_date": "2026-09-15",
            "taxable_paise": 1000000,
            "total_tax_paise": 180000,
            "igst_paise": 180000,
            "cgst_paise": 0,
            "sgst_paise": 0,
        },
        {
            "id": "g_v2",
            "invoice_number": "INV-2026-001",
            "invoice_number_normalized": "INV2026001",
            "supplier_gstin": "29BBBBB1111B1Z2",
            "invoice_date": "2026-09-15",
            "taxable_paise": 2000000,
            "total_tax_paise": 360000,
            "igst_paise": 360000,
            "cgst_paise": 0,
            "sgst_paise": 0,
        },
    ]
    pr_records = [
        {
            "id": "p_v1",
            "invoice_number": "INV-2026-001",
            "invoice_number_normalized": "INV2026001",
            "supplier_gstin": "27AAPFU0939F1ZV",
            "invoice_date": "2026-09-15",
            "taxable_paise": 1000000,
            "total_tax_paise": 180000,
            "igst_paise": 180000,
            "cgst_paise": 0,
            "sgst_paise": 0,
        },
        {
            "id": "p_v2",
            "invoice_number": "INV-2026-001",
            "invoice_number_normalized": "INV2026001",
            "supplier_gstin": "29BBBBB1111B1Z2",
            "invoice_date": "2026-09-15",
            "taxable_paise": 2000000,
            "total_tax_paise": 360000,
            "igst_paise": 360000,
            "cgst_paise": 0,
            "sgst_paise": 0,
        },
    ]
    res = run_bidirectional_reconciliation(gstr_records, pr_records)
    assert len(res["matched"]) == 2
    assert len(res["duplicate_entries"]) == 0
    assert len(res["wrongful_itc_risk"]) == 0
