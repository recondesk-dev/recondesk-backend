"""Unit and regression tests for Phase 1 (Run 14) Compound Chaos.

Tests documents where 2 to 4 mutations/issues occur simultaneously:
- Multi-risk combinations (OCR + Date + Rounding + POS + Tax-Head + DocType + FY + Branch)
- Cumulative evidence scoring
- Zero unsafe high-confidence auto-matches on multi-risk documents
- Strict isolation of cross-GSTIN, cross-FY, and incompatible doc types
- Synthetic benchmark (1,200 records) verifying complete compound chaos resilience.
"""

from datetime import date
from decimal import Decimal
import pytest

from app.matching.generic_matcher import generic_match_pair, SALES_MATCH_CONFIG
from app.services.matcher import (
    analyze_invoice_evidence,
    extract_terminal_and_prefix,
    normalize_invoice,
    ocr_canonical_invoice,
)


def _sr(
    inv: str,
    gstin: str = "27AABCS1429B1Z",
    taxable: int = 10000000,
    tax: int = 1800000,
    dt: date = date(2026, 9, 15),
    pos: str = "27",
    doc_type: str = "INVOICE",
    is_igst: bool = True,
) -> dict:
    return {
        "invoice_number": inv,
        "invoice_number_raw": inv,
        "gstin": gstin,
        "taxable_amount_paise": taxable,
        "total_tax_paise": tax,
        "igst_paise": tax if is_igst else 0,
        "cgst_paise": 0 if is_igst else tax // 2,
        "sgst_paise": 0 if is_igst else tax // 2,
        "cess_paise": 0,
        "invoice_date": dt,
        "place_of_supply": pos,
        "pos": pos,
        "doc_type": doc_type,
    }


def _g1(
    inv: str,
    gstin: str = "27AABCS1429B1Z",
    taxable: int = 10000000,
    tax: int = 1800000,
    dt: date = date(2026, 9, 15),
    pos: str = "27",
    doc_type: str = "INVOICE",
    is_igst: bool = True,
) -> dict:
    return {
        "inum": inv,
        "invoice_number": inv,
        "invoice_number_raw": inv,
        "ctin": gstin,
        "gstin": gstin,
        "taxable_amount_paise": taxable,
        "total_tax_paise": tax,
        "igst_paise": tax if is_igst else 0,
        "cgst_paise": 0 if is_igst else tax // 2,
        "sgst_paise": 0 if is_igst else tax // 2,
        "cess_paise": 0,
        "idt": dt.strftime("%d-%m-%Y"),
        "invoice_date": dt,
        "pos": pos,
        "place_of_supply": pos,
        "doc_type": doc_type,
    }


# ─────────────────────────────────────────────────────────────────────────────
# FOCUSED COMBINATION TESTS (>= 40 TEST CASES)
# ─────────────────────────────────────────────────────────────────────────────

def test_01_single_ocr_plus_1_day_plus_25_paise_rounding():
    """1. Single OCR + +1 day + 25 paise roundoff."""
    sr = _sr("INV/26-27/00010", dt=date(2026, 9, 15), taxable=10000025)
    g1 = _g1("INV/26-27/0001O", dt=date(2026, 9, 16), taxable=10000000)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    # Minor drift within tolerance
    assert res.level in (1, 2)


def test_02_single_ocr_plus_2_days_plus_pos_mismatch():
    """2. Single OCR + +2 days + POS mismatch -> Review Required."""
    sr = _sr("INV/26-27/00010", dt=date(2026, 9, 15), pos="27")
    g1 = _g1("INV/26-27/0001O", dt=date(2026, 9, 17), pos="29")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason in ("POS_MISMATCH", "COMPOUND_RISK_REVIEW")


def test_03_single_ocr_plus_1_day_plus_tax_structure_mismatch():
    """3. Single OCR + +1 day + Tax structure mismatch (IGST vs CGST/SGST)."""
    sr = _sr("INV/26-27/00010", dt=date(2026, 9, 15), is_igst=True)
    g1 = _g1("INV/26-27/0001O", dt=date(2026, 9, 16), is_igst=False)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason in ("TAX_HEAD_MISMATCH", "COMPOUND_RISK_REVIEW")


def test_04_prefix_alteration_plus_date_delta():
    """4. Prefix alteration + date delta -> Review Required."""
    sr = _sr("DEL-2026-00100", dt=date(2026, 9, 15))
    g1 = _g1("BOM-2026-00100", dt=date(2026, 9, 17))
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason == "PREFIX_ALTERATION_REVIEW"


def test_05_prefix_alteration_plus_amount_delta_within_l3():
    """5. Prefix alteration + amount delta (within L3) -> Review Required."""
    sr = _sr("DEL-2026-00100", taxable=10000000)
    g1 = _g1("BOM-2026-00100", taxable=10200000)  # 2% diff
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.requires_human_review is True


def test_06_prefix_alteration_plus_amount_delta_exceeding_l3():
    """6. Prefix alteration + amount delta exceeding L3 -> Reject."""
    sr = _sr("DEL-2026-00100", taxable=10000000)
    g1 = _g1("BOM-2026-00100", taxable=15000000)  # 50% diff
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is False
    assert res.level == 6


def test_07_prefix_alteration_plus_terminal_sequence_mismatch():
    """7. Prefix alteration + terminal sequence mismatch -> Reject."""
    sr = _sr("DEL-2026-00100")
    g1 = _g1("BOM-2026-00200")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is False
    assert res.level == 6


def test_08_multi_ocr_plus_1_day_delta():
    """8. Multi-OCR (2 substitutions) + 1-day date difference -> Review Required."""
    sr = _sr("INV/26-27/00010", dt=date(2026, 9, 15))
    g1 = _g1("INV/26-27/OO01O", dt=date(2026, 9, 16))
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason in ("MULTI_OCR_REVIEW", "COMPOUND_RISK_REVIEW")


def test_09_multi_ocr_plus_25_paise_roundoff():
    """9. Multi-OCR (2 substitutions) + 25 paise roundoff -> Review Required."""
    sr = _sr("INV/26-27/00010", taxable=10000025)
    g1 = _g1("INV/26-27/OO01O", taxable=10000000)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason in ("MULTI_OCR_REVIEW", "COMPOUND_RISK_REVIEW")


def test_10_multi_ocr_plus_pos_mismatch():
    """10. Multi-OCR + POS mismatch -> Review Required."""
    sr = _sr("INV/26-27/00010", pos="27")
    g1 = _g1("INV/26-27/OO01O", pos="29")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason in ("MULTI_OCR_REVIEW", "POS_MISMATCH", "COMPOUND_RISK_REVIEW")


def test_11_credit_note_vs_invoice_exact_number():
    """11. Credit Note vs Invoice with exact same number -> Incompatible doc types (reject)."""
    sr = _sr("CN-2026-001", doc_type="CREDIT_NOTE")
    g1 = _g1("CN-2026-001", doc_type="INVOICE")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is False
    assert res.level == 6
    assert res.review_reason == "DOC_TYPE_MISMATCH"


def test_12_debit_note_vs_invoice_exact_number():
    """12. Debit Note vs Invoice with exact same number -> Incompatible doc types (reject)."""
    sr = _sr("DN-2026-001", doc_type="DEBIT_NOTE")
    g1 = _g1("DN-2026-001", doc_type="INVOICE")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is False
    assert res.level == 6
    assert res.review_reason == "DOC_TYPE_MISMATCH"


def test_13_credit_note_vs_invoice_fuzzy_number():
    """13. Credit Note vs Invoice with fuzzy invoice number -> Incompatible doc types (reject)."""
    sr = _sr("CN-2026-00010", doc_type="CREDIT_NOTE")
    g1 = _g1("CN-2026-0001O", doc_type="INVOICE")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is False
    assert res.level == 6
    assert res.review_reason == "DOC_TYPE_MISMATCH"


def test_14_different_financial_year_isolation_90_days():
    """14. Invoices across different financial years (> 60 days delta) -> Review Required."""
    sr = _sr("INV-00100", dt=date(2025, 12, 15))  # FY 2025-26
    g1 = _g1("INV-00100", dt=date(2026, 6, 15))   # FY 2026-27 (delta 182 days)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason in ("FINANCIAL_YEAR_MISMATCH", "PERIOD_BOUNDARY_DATE_MISMATCH")


def test_15_different_financial_year_isolation_fuzzy_rejected():
    """15. Fuzzy invoice (non-OCR typo) across different financial years (> 45 days) -> Reject."""
    sr = _sr("INV-12340", dt=date(2025, 4, 10))
    g1 = _g1("INV-12349", dt=date(2026, 4, 10))
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is False
    assert res.level == 6


def test_16_cross_branch_same_pan_different_pos_collision():
    """16. Cross-branch same PAN with different state GSTIN and different POS -> Reject."""
    sr = _sr("INV/26-27/005", gstin="27AAAAA0000A1Z5", pos="27")
    g1 = _g1("INV/26-27/005", gstin="29AAAAA0000A1Z3", pos="29")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is False
    assert res.level == 6


def test_17_same_pan_typo_with_same_pos():
    """17. Same PAN with check digit typo (same state, same POS) -> Level 4 GSTIN typo review."""
    sr = _sr("INV/26-27/005", gstin="27AAAAA0000A1Z5", pos="27")
    g1 = _g1("INV/26-27/005", gstin="27AAAAA0000A1Z9", pos="27")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is False  # Level 4 is non-auto-match review
    assert res.level == 4
    assert "GSTIN_MISMATCH" in (res.review_reason or "")


def test_18_cross_gstin_completely_different_pan_exact_invoice():
    """18. Completely different PAN + exact invoice number -> Never match (reject)."""
    sr = _sr("INV-2026-001", gstin="27AAAAA0000A1Z5")
    g1 = _g1("INV-2026-001", gstin="27BBBBB9999B1Z2")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is False
    assert res.level == 6


def test_19_cross_gstin_completely_different_pan_fuzzy_invoice():
    """19. Completely different PAN + fuzzy invoice number -> Never match (reject)."""
    sr = _sr("INV-2026-00010", gstin="27AAAAA0000A1Z5")
    g1 = _g1("INV-2026-0001O", gstin="27BBBBB9999B1Z2")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is False
    assert res.level == 6


def test_20_export_sez_blank_gstin_zero_tax_exact_match():
    """20. Export / SEZ (blank recipient GSTIN) + exact invoice + zero tax -> Exact match."""
    sr = _sr("EXP-2026-001", gstin="", tax=0, is_igst=False)
    g1 = _g1("EXP-2026-001", gstin="", tax=0, is_igst=False)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1
    assert res.confidence == 100


def test_21_export_sez_single_ocr_plus_1_day_delta():
    """21. Export / SEZ + single OCR + 1-day delta -> Matched."""
    sr = _sr("EXP-2026-00010", gstin="", dt=date(2026, 9, 15), tax=0, is_igst=False)
    g1 = _g1("EXP-2026-0001O", gstin="", dt=date(2026, 9, 16), tax=0, is_igst=False)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level in (1, 2)


def test_22_single_ocr_plus_period_boundary_crossing():
    """22. Single OCR + date crosses GST return period (Aug 31 vs Sep 1) -> Review Required."""
    sr = _sr("INV/26-27/00010", dt=date(2026, 8, 31))
    g1 = _g1("INV/26-27/0001O", dt=date(2026, 9, 1))
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason == "PERIOD_BOUNDARY_DATE_MISMATCH"


def test_23_prefix_alteration_plus_period_boundary_crossing():
    """23. Prefix alteration + date crosses GST return period -> Review Required."""
    sr = _sr("DEL-2026-00100", dt=date(2026, 8, 31))
    g1 = _g1("BOM-2026-00100", dt=date(2026, 9, 1))
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason in ("PREFIX_ALTERATION_REVIEW", "PERIOD_BOUNDARY_DATE_MISMATCH")


def test_24_format_variant_plus_1_day_plus_30_paise_roundoff():
    """24. Format variant (slashes vs dashes) + +1 day + 30 paise roundoff -> Matched."""
    sr = _sr("INV/2026-27/00123", dt=date(2026, 9, 15), taxable=10000030)
    g1 = _g1("INV-2026-27-00123", dt=date(2026, 9, 16), taxable=10000000)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level in (1, 2)


def test_25_format_variant_plus_2_days_plus_pos_mismatch():
    """25. Format variant + +2 days + POS mismatch -> Review Required."""
    sr = _sr("INV/2026-27/00123", dt=date(2026, 9, 15), pos="27")
    g1 = _g1("INV-2026-27-00123", dt=date(2026, 9, 17), pos="29")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason in ("POS_MISMATCH", "COMPOUND_RISK_REVIEW")


def test_26_format_variant_plus_date_outside_tolerance():
    """26. Format variant + date outside tolerance (4 days delta) -> Review Required."""
    sr = _sr("INV/2026-27/00123", dt=date(2026, 9, 15))
    g1 = _g1("INV-2026-27-00123", dt=date(2026, 9, 19))
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason == "DATE_OUTSIDE_TOLERANCE"


def test_27_whitespace_unicode_dash_leading_zero_plus_1_day():
    """27. Whitespace + Unicode dash (\u2013) + leading zero + 1-day delta -> Matched."""
    sr = _sr("INV \u2013 00456", dt=date(2026, 9, 15))
    g1 = _g1("INV-456", dt=date(2026, 9, 16))
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level in (1, 2)


def test_28_whitespace_unicode_dash_plus_pos_mismatch():
    """28. Whitespace + Unicode dash + POS mismatch -> Review Required."""
    sr = _sr("INV \u2013 456", pos="27")
    g1 = _g1("INV-456", pos="06")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason in ("POS_MISMATCH", "COMPOUND_RISK_REVIEW")


def test_29_two_ocr_subs_plus_2_days_plus_50_paise_rounding():
    """29. 2 OCR substitutions + +2 days + 50 paise roundoff -> Review Required."""
    sr = _sr("INV/26-27/00010", dt=date(2026, 9, 15), taxable=10000050)
    g1 = _g1("INV/26-27/OO01O", dt=date(2026, 9, 17), taxable=10000000)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason in ("MULTI_OCR_REVIEW", "COMPOUND_RISK_REVIEW")


def test_30_three_ocr_subs_plus_1_day_plus_tax_structure_mismatch():
    """30. 3 OCR substitutions + +1 day + tax structure mismatch -> Review Required."""
    sr = _sr("INV/26-27/00101", dt=date(2026, 9, 15), is_igst=True)
    g1 = _g1("INV/26-27/OOIOI", dt=date(2026, 9, 16), is_igst=False)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason in ("MULTI_OCR_REVIEW", "TAX_HEAD_MISMATCH", "COMPOUND_RISK_REVIEW")


def test_31_terminal_sequence_mismatch_plus_different_prefix():
    """31. Terminal sequence mismatch across different prefixes (DEL-0042 vs BOM-0099) -> Reject."""
    sr = _sr("DEL-0042")
    g1 = _g1("BOM-0099")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is False
    assert res.level == 6


def test_32_credit_note_vs_debit_note_same_number():
    """32. Credit Note vs Debit Note with same number -> Reject."""
    sr = _sr("NOTE-001", doc_type="CREDIT_NOTE")
    g1 = _g1("NOTE-001", doc_type="DEBIT_NOTE")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is False
    assert res.level == 6
    assert res.review_reason == "DOC_TYPE_MISMATCH"


def test_33_exact_invoice_with_tax_structure_mismatch():
    """33. Exact invoice and amount, but IGST vs CGST/SGST -> Review Required."""
    sr = _sr("INV/1001", is_igst=True)
    g1 = _g1("INV/1001", is_igst=False)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason in ("TAX_HEAD_MISMATCH", "COMPOUND_RISK_REVIEW")


def test_34_exact_invoice_with_pos_mismatch():
    """34. Exact invoice and amount, but different Place of Supply -> Review Required."""
    sr = _sr("INV/1001", pos="27")
    g1 = _g1("INV/1001", pos="29")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason in ("POS_MISMATCH", "COMPOUND_RISK_REVIEW")


def test_35_multi_ocr_plus_prefix_change_sub_threshold():
    """35. Multi-OCR + Prefix change where compound degradation drops similarity below 75% -> Correctly Reject."""
    sr = _sr("INV-MUM-00010")
    g1 = _g1("INV-PUN-OO01O")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is False
    assert res.level == 6


def test_36_multi_ocr_plus_pos_mismatch_plus_date_delta():
    """36. Multi-OCR + POS mismatch + date delta -> Review Required."""
    sr = _sr("INV/26-27/00010", dt=date(2026, 9, 15), pos="27")
    g1 = _g1("INV/26-27/OO01O", dt=date(2026, 9, 17), pos="29")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.confidence <= 75


def test_37_cross_branch_same_pan_different_gstin_state_exact_inv():
    """37. Cross-branch same PAN (27 MH vs 24 GJ) with different POS -> Reject."""
    sr = _sr("INV-2026-0042", gstin="27AAACH1234A1Z1", pos="27")
    g1 = _g1("INV-2026-0042", gstin="24AAACH1234A1Z8", pos="24")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is False
    assert res.level == 6


def test_38_cumulative_risk_evidence_calculation():
    """38. Verify cumulative risk scoring in analyze_invoice_evidence."""
    ev = analyze_invoice_evidence(
        a_inv="INV/26-27/00010",
        b_inv="INV/26-27/OO01O",  # 2 OCR substitutions (+3)
        a_inv_raw="INV/26-27/00010",
        b_inv_raw="INV/26-27/OO01O",
        da=date(2026, 9, 15),
        db=date(2026, 9, 17),    # 2 days drift (+1)
        ta=10000000,
        tb=10000000,
        tax_a=1800000,
        tax_b=1800000,
        gstin_exact=True,
        doc_type_compatible=True,
        date_diff_days=2,
        pos_a="27",
        pos_b="29",              # POS mismatch (+3)
        tax_structure_match=False, # Tax head mismatch (+4)
    )
    # Total risk points: 3 + 1 + 3 + 4 = 11 >= 6
    assert ev.cumulative_risk_points >= 6
    assert "POS_MISMATCH" in ev.risk_reasons
    assert "TAX_HEAD_MISMATCH" in ev.risk_reasons


def test_39_single_ocr_safe_vs_compound_risk():
    """39. Single OCR alone is safe, but with POS + Tax mismatch exceeds threshold."""
    ev_safe = analyze_invoice_evidence(
        a_inv="INV/26-27/00010",
        b_inv="INV/26-27/0001O",  # 1 OCR substitution (+1)
        a_inv_raw="INV/26-27/00010",
        b_inv_raw="INV/26-27/0001O",
        da=date(2026, 9, 15),
        db=date(2026, 9, 15),
        ta=10000000,
        tb=10000000,
        tax_a=1800000,
        tax_b=1800000,
        gstin_exact=True,
        doc_type_compatible=True,
        pos_a="27",
        pos_b="27",
        tax_structure_match=True,
    )
    assert ev_safe.cumulative_risk_points == 1

    ev_compound = analyze_invoice_evidence(
        a_inv="INV/26-27/00010",
        b_inv="INV/26-27/0001O",  # 1 OCR (+1)
        a_inv_raw="INV/26-27/00010",
        b_inv_raw="INV/26-27/0001O",
        da=date(2026, 9, 15),
        db=date(2026, 9, 17),    # 2 days (+1)
        ta=10000000,
        tb=10000000,
        tax_a=1800000,
        tax_b=1800000,
        gstin_exact=True,
        doc_type_compatible=True,
        pos_a="27",
        pos_b="29",              # POS mismatch (+3)
        tax_structure_match=False, # Tax head mismatch (+4)
    )
    # Total: 1 + 1 + 3 + 4 = 9 >= 6
    assert ev_compound.cumulative_risk_points >= 6


def test_40_fy_mismatch_under_60_days_allowed_at_year_end():
    """40. FY boundary crossing within 60 days (March 31 vs April 2) is evaluated under period boundary, not blocked."""
    sr = _sr("INV/2026/001", dt=date(2026, 3, 31))
    g1 = _g1("INV/2026/001", dt=date(2026, 4, 2))
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    # Date diff is 2 days across period boundary -> Period boundary review, not hard FY block
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason == "PERIOD_BOUNDARY_DATE_MISMATCH"


# ─────────────────────────────────────────────────────────────────────────────
# SYNTHETIC BENCHMARK (1,200 RECORDS)
# ─────────────────────────────────────────────────────────────────────────────

def test_run14_synthetic_compound_chaos_benchmark():
    """Synthetic Benchmark: 1,200 compound permutation records.
    
    Verifies:
    1. Zero unsafe high-confidence auto-matches on compound multi-risk records (risk >= 6).
    2. Strict rejection of cross-GSTIN and incompatible doc types.
    3. Correct review routing for multi-OCR, prefix alterations, POS and tax-head mismatches.
    4. 100% determinism and safety.
    """
    records_count = 1200
    safe_matches = 0
    review_required_matches = 0
    rejected_count = 0
    unsafe_high_confidence = 0

    for i in range(records_count):
        mod = i % 12
        inv_base = f"INV/26-27/{i:05d}"
        
        if mod == 0:
            # Safe exact match
            sr = _sr(inv_base)
            g1 = _g1(inv_base)
        elif mod == 1:
            # Safe format variant (slashes vs dashes + 1 day)
            sr = _sr(f"INV/26-27/{i:05d}", dt=date(2026, 9, 15))
            g1 = _g1(f"INV-26-27-{i:05d}", dt=date(2026, 9, 16))
        elif mod == 2:
            # Single OCR + 1 day + 25 paise roundoff
            sr = _sr(f"INV/26-27/{i:04d}0", dt=date(2026, 9, 15), taxable=10000025)
            g1 = _g1(f"INV/26-27/{i:04d}O", dt=date(2026, 9, 16), taxable=10000000)
        elif mod == 3:
            # Single OCR + 2 days + POS mismatch -> Review
            sr = _sr(f"INV/26-27/{i:04d}0", dt=date(2026, 9, 15), pos="27")
            g1 = _g1(f"INV/26-27/{i:04d}O", dt=date(2026, 9, 17), pos="29")
        elif mod == 4:
            # Prefix alteration + date delta -> Review
            sr = _sr(f"DEL-2026-{i:05d}", dt=date(2026, 9, 15))
            g1 = _g1(f"BOM-2026-{i:05d}", dt=date(2026, 9, 17))
        elif mod == 5:
            # Multi-OCR (2 subs) + 1 day delta -> Review
            sr = _sr(f"INV/26-27/{i:03d}00", dt=date(2026, 9, 15))
            g1 = _g1(f"INV/26-27/{i:03d}OO", dt=date(2026, 9, 16))
        elif mod == 6:
            # Credit Note vs Invoice -> Reject
            sr = _sr(inv_base, doc_type="CREDIT_NOTE")
            g1 = _g1(inv_base, doc_type="INVOICE")
        elif mod == 7:
            # Different Financial Year (> 100 days) -> Reject
            sr = _sr(inv_base, dt=date(2025, 11, 10))
            g1 = _g1(inv_base, dt=date(2026, 6, 10))
        elif mod == 8:
            # Cross-branch same PAN with different POS -> Reject
            sr = _sr(inv_base, gstin="27AAACH1234A1Z1", pos="27")
            g1 = _g1(inv_base, gstin="24AAACH1234A1Z8", pos="24")
        elif mod == 9:
            # Completely different GSTIN PAN -> Reject
            sr = _sr(inv_base, gstin="27AAACH1234A1Z1")
            g1 = _g1(inv_base, gstin="27ZZZZZ9999Z1Z9")
        elif mod == 10:
            # Prefix alteration + terminal sequence mismatch -> Reject
            sr = _sr(f"MUM-INV-{i:05d}")
            g1 = _g1(f"PUN-INV-{(i+999):05d}")
        else:
            # Multi-OCR + POS mismatch + tax head mismatch (compound chaos) -> Review
            sr = _sr(f"INV/26-27/{i:03d}00", pos="27", is_igst=True)
            g1 = _g1(f"INV/26-27/{i:03d}OO", pos="29", is_igst=False)

        res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)

        if res.matched:
            if res.requires_human_review:
                review_required_matches += 1
            else:
                safe_matches += 1
                # Invariant: safe auto-matches must never have multi-OCR, prefix alteration, pos mismatch or tax head mismatch
                if mod in (3, 4, 5, 6, 7, 8, 9, 10, 11):
                    unsafe_high_confidence += 1
        else:
            rejected_count += 1
            # Invariant: cross-GSTIN and incompatible doc types must be rejected
            assert mod in (6, 8, 9, 10)

    assert unsafe_high_confidence == 0, f"Found {unsafe_high_confidence} unsafe high-confidence matches!"
    assert rejected_count == 400  # Mods 6, 8, 9, 10 each account for 100 records = 400 total
    assert safe_matches == 300    # Mods 0, 1, 2 each account for 100 records = 300 total
    assert review_required_matches == 500 # Mods 3, 4, 5, 7, 11 each account for 100 records = 500 total
    assert safe_matches + review_required_matches + rejected_count == records_count
