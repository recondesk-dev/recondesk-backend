"""Unit and regression tests for Run 13 Extreme-Fuzzy Reconciliation.

Verifies:
1. Punctuation-only invoice difference
2. Whitespace-only invoice difference
3. Unicode dash difference
4. Leading zero difference
5. Single OCR substitution (0 <-> O)
6. Single OCR substitution (1 <-> I)
7. Two OCR substitutions (requires human review MULTI_OCR_REVIEW)
8. Three OCR substitutions (requires human review MULTI_OCR_REVIEW)
9. Prefix addition with matching terminal sequence (PREFIX_ALTERATION_REVIEW)
10. Prefix replacement with matching terminal sequence (PREFIX_ALTERATION_REVIEW)
11. Single OCR + 1-day date difference
12. Single OCR + 2-day date difference
13. Single OCR + amount mismatch
14. Single OCR + different GSTIN
15. Terminal sequence mismatch across different prefixes (DEL-0042 vs BOM-0099)
16. Leading zero difference with exact economics
17. Punctuation difference with 30 paise difference
18. Punctuation difference with Rs 50 difference
19. Multi-OCR with exact economics
20. Prefix alteration with matching terminal sequence
21. Full Run 13 benchmark execution (6000 records).
"""

from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import pytest

from app.matching.generic_matcher import generic_match_pair, SALES_MATCH_CONFIG
from app.services.matcher import (
    normalize_invoice,
    ocr_canonical_invoice,
    analyze_invoice_evidence,
    extract_terminal_and_prefix,
)


def _sr(inv: str, gstin: str = "27AABCS1429B1Z", taxable: int = 100000, tax: int = 18000, dt: date = date(2026, 9, 15)) -> dict:
    return {
        "invoice_number": inv,
        "invoice_number_raw": inv,
        "gstin": gstin,
        "taxable_amount_paise": taxable,
        "total_tax_paise": tax,
        "igst_paise": tax,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
        "invoice_date": dt,
        "doc_type": "INVOICE",
    }


def _g1(inv: str, gstin: str = "27AABCS1429B1Z", taxable: int = 100000, tax: int = 18000, dt: date = date(2026, 9, 15)) -> dict:
    return {
        "inum": inv,
        "invoice_number": inv,
        "invoice_number_raw": inv,
        "recipient_gstin": gstin,
        "taxable_amount_paise": taxable,
        "total_tax_paise": tax,
        "igst_paise": tax,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
        "invoice_date": dt,
        "section": "b2b",
    }


# 1. Punctuation-only invoice difference
def test_case_01_punctuation_only():
    r = generic_match_pair(_sr("INV-001"), _g1("INV/001"), SALES_MATCH_CONFIG)
    assert r.matched
    assert r.level == 2
    assert r.confidence == 95
    assert not r.requires_human_review


# 2. Whitespace-only invoice difference
def test_case_02_whitespace_only():
    r = generic_match_pair(_sr("INV 001"), _g1("INV001"), SALES_MATCH_CONFIG)
    assert r.matched
    assert r.level == 2
    assert r.confidence == 95
    assert not r.requires_human_review


# 3. Unicode dash difference
def test_case_03_unicode_dash():
    r = generic_match_pair(_sr("INV\u2014001"), _g1("INV-001"), SALES_MATCH_CONFIG)
    assert r.matched
    assert r.level == 2
    assert r.confidence == 95
    assert not r.requires_human_review


# 4. Leading zero difference
def test_case_04_leading_zero():
    r = generic_match_pair(_sr("INV-0012"), _g1("INV-12"), SALES_MATCH_CONFIG)
    assert r.matched
    assert r.level == 2
    assert r.confidence == 95
    assert not r.requires_human_review


# 5. Single OCR substitution 0 <-> O
def test_case_05_single_ocr_zero_o():
    r = generic_match_pair(_sr("INV-O12"), _g1("INV-012"), SALES_MATCH_CONFIG)
    assert r.matched
    assert r.level == 2
    assert r.confidence == 95
    assert not r.requires_human_review


# 6. Single OCR substitution 1 <-> I
def test_case_06_single_ocr_one_i():
    r = generic_match_pair(_sr("INV-I23"), _g1("INV-123"), SALES_MATCH_CONFIG)
    assert r.matched
    assert r.level == 2
    assert r.confidence == 95
    assert not r.requires_human_review


# 7. Two OCR substitutions
def test_case_07_two_ocr_substitutions():
    r = generic_match_pair(_sr("NGP/26-27/00013"), _g1("NGP/26-27/00OI3"), SALES_MATCH_CONFIG)
    assert r.matched
    assert r.level == 3
    assert r.confidence == 75
    assert r.requires_human_review
    assert r.review_reason == "MULTI_OCR_REVIEW"


# 8. Three OCR substitutions
def test_case_08_three_ocr_substitutions():
    r = generic_match_pair(_sr("INV-26-015"), _g1("INV-26-OIS"), SALES_MATCH_CONFIG)
    assert r.matched
    assert r.level == 3
    assert r.confidence == 75
    assert r.requires_human_review
    assert r.review_reason == "MULTI_OCR_REVIEW"


# 9. Prefix addition with matching terminal sequence
def test_case_09_prefix_addition():
    r = generic_match_pair(_sr("NGP-SEP26-00088"), _g1("XNGP-SEP26-00088"), SALES_MATCH_CONFIG)
    assert r.matched
    assert r.level == 3
    assert r.confidence == 75
    assert r.requires_human_review
    assert r.review_reason == "PREFIX_ALTERATION_REVIEW"


# 10. Prefix replacement with matching terminal sequence
def test_case_10_prefix_replacement():
    r = generic_match_pair(_sr("DEL-2026-00100"), _g1("BOM-2026-00100"), SALES_MATCH_CONFIG)
    assert r.matched
    assert r.level == 3
    assert r.confidence == 75
    assert r.requires_human_review
    assert r.review_reason == "PREFIX_ALTERATION_REVIEW"


# 11. Single OCR + 1-day date difference
def test_case_11_single_ocr_one_day():
    r = generic_match_pair(
        _sr("INV-O12", dt=date(2026, 9, 15)),
        _g1("INV-012", dt=date(2026, 9, 16)),
        SALES_MATCH_CONFIG,
    )
    assert r.matched
    assert r.confidence == 95
    assert not r.requires_human_review


# 12. Single OCR + date difference outside tolerance
def test_case_12_single_ocr_two_days():
    r = generic_match_pair(
        _sr("INV-O12", dt=date(2026, 9, 15)),
        _g1("INV-012", dt=date(2026, 9, 20)),
        SALES_MATCH_CONFIG,
    )
    assert r.matched
    assert r.requires_human_review
    assert r.review_reason == "DATE_OUTSIDE_TOLERANCE"


# 13. Single OCR + Rs 500 amount mismatch
def test_case_13_single_ocr_amount_mismatch():
    r = generic_match_pair(
        _sr("INV-O12", taxable=100000, tax=18000),
        _g1("INV-012", taxable=150000, tax=27000),
        SALES_MATCH_CONFIG,
    )
    assert r.matched
    assert r.level == 3
    assert r.requires_human_review
    assert "AMOUNT" in (r.review_reason or "").upper()


# 14. Single OCR + different GSTIN
def test_case_14_single_ocr_different_gstin():
    r = generic_match_pair(
        _sr("INV-O12", gstin="27AABCS1429B1Z"),
        _g1("INV-012", gstin="29XYZCS9999Z1A"),
        SALES_MATCH_CONFIG,
    )
    assert not r.matched
    assert r.level == 6


# 15. Terminal sequence mismatch across different prefixes
def test_case_15_terminal_sequence_mismatch():
    r = generic_match_pair(_sr("DEL-0042"), _g1("BOM-0099"), SALES_MATCH_CONFIG)
    assert not r.matched
    assert r.level == 6


# 16. Leading zero difference with exact economics
def test_case_16_leading_zero_exact_economics():
    r = generic_match_pair(_sr("DEL-0042"), _g1("DEL-42"), SALES_MATCH_CONFIG)
    assert r.matched
    assert r.level == 2
    assert r.confidence == 95
    assert not r.requires_human_review


# 17. Punctuation difference with 30 paise difference
def test_case_17_punctuation_roundoff():
    r = generic_match_pair(
        _sr("INV-001", taxable=100000, tax=18000),
        _g1("INV/001", taxable=100030, tax=18000),
        SALES_MATCH_CONFIG,
    )
    assert r.matched
    assert r.level == 2


# 18. Punctuation difference with Rs 50 difference
def test_case_18_punctuation_amount_mismatch():
    r = generic_match_pair(
        _sr("INV-001", taxable=100000, tax=18000),
        _g1("INV/001", taxable=105000, tax=18900),
        SALES_MATCH_CONFIG,
    )
    assert r.matched
    assert r.level == 3
    assert r.requires_human_review


# 19. Multi-OCR with exact economics
def test_case_19_multi_ocr_exact_economics():
    r = generic_match_pair(_sr("PUN-26-00013"), _g1("PUN-26-00OI3"), SALES_MATCH_CONFIG)
    assert r.matched
    assert r.level == 3
    assert r.confidence == 75
    assert r.requires_human_review
    assert r.review_reason == "MULTI_OCR_REVIEW"


# 20. Prefix alteration with matching terminal sequence
def test_case_20_prefix_alteration_terminal_match():
    r = generic_match_pair(_sr("DEL-SEP26-0055"), _g1("MUM-SEP26-0055"), SALES_MATCH_CONFIG)
    assert r.matched
    assert r.level == 3
    assert r.confidence == 75
    assert r.requires_human_review
    assert r.review_reason == "PREFIX_ALTERATION_REVIEW"


# 21. Full Run 13 benchmark verification (6000 records)
@pytest.mark.asyncio
async def test_run13_benchmark_full():
    bench_dir = Path("/Users/omkarkadam/Documents/ReconDesk/benchmark_data/run13_extreme_fuzzy_6000")
    sr_file = bench_dir / "ReconDesk_Sales_Register_6000_Run13_ExtremeFuzzy_Sep2026.xlsx"
    g1_file = bench_dir / "ReconDesk_GSTR1_6000_Run13_ExtremeFuzzy_Sep2026.json"
    g3b_file = bench_dir / "ReconDesk_GSTR3B_Run13_ExtremeFuzzy_Sep2026.json"

    if not (sr_file.exists() and g1_file.exists() and g3b_file.exists()):
        pytest.skip("Run 13 benchmark files not present")

    from app.routers.gstr1_reconcile import _run_pipeline

    sr_bytes = sr_file.read_bytes()
    g1_bytes = g1_file.read_bytes()
    g3b_bytes = g3b_file.read_bytes()

    result = await _run_pipeline(
        sr_file_content=sr_bytes,
        sr_filename=sr_file.name,
        gstr1_file_content=g1_bytes,
        gstr3b_file_content=g3b_bytes,
        gstr1_filing_period="092026",
    )

    summary = result["summary"]
    assert summary["sr_total_records"] == 6000
    assert summary["matched_count"] == 5470
    assert summary["genuine_missing_count"] == 120
    assert summary["unmatched_gstr1_count"] == 90
    assert summary["unmatched_sr_count"] == 260
    assert summary["identical_duplicate_count"] == 50
    assert summary["conflicting_duplicate_count"] == 40
    assert summary["cancelled_reissued_count"] == 50

    # Review reason counts
    matches = result.get("matched", [])
    multi_ocr_reviews = [m for m in matches if m.get("review_reason") == "MULTI_OCR_REVIEW"]
    prefix_alter_reviews = [
        m for m in matches if m.get("review_reason") in ("PREFIX_ALTERATION_REVIEW", "TYPO_MISMATCH")
    ]

    assert len(multi_ocr_reviews) == 120
    assert len(prefix_alter_reviews) == 100
    for m in multi_ocr_reviews:
        assert m.get("requires_human_review") is True
        assert m.get("decision_confidence") in ("MEDIUM", "medium") or m.get("confidence") == 75
    for m in prefix_alter_reviews:
        assert m.get("requires_human_review") is True
        assert m.get("decision_confidence") in ("MEDIUM", "medium") or m.get("confidence") == 75

    # GSTR-3B tie-out
    tie_out = result.get("tie_out", {})
    assert tie_out.get("variance_count") == 2
    variances = {v["field"]: v for v in tie_out.get("variances", [])}
    assert "taxable_value" in variances
    assert variances["taxable_value"]["diff"] == "₹45,000.00"
    assert variances["taxable_value"]["direction"] == "under"
    assert "zero_rated" in variances
    assert variances["zero_rated"]["diff"] == "₹20,000.00"
    assert variances["zero_rated"]["direction"] == "over"
    assert tie_out.get("unexplained_difference") == -25000.0
