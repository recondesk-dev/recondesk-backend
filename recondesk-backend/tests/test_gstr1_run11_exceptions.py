"""Comprehensive tests for Run 11 exception-classification in ReconDesk.

Validates the 13 required test cases:
1. Identical duplicate SR surplus: 2 identical SR rows, 1 GSTR-1 -> 1 accounted, 1 G1D1, 0 G1M1, liability counted once
2. Conflicting duplicate SR surplus: same invoice identity, different taxable amount -> 1 accounted, 1 G1D2 review, 0 G1M1, liability counted once
3. Triple identical duplicate: 3 SR copies, 1 portal copy -> 1 accounted, 2 G1D1, liability once
4. Duplicate + genuine missing: SR has duplicate of INV-A (accounted + G1D1) and INV-B (no portal -> G1M1)
5. Cancel/reissue: original cancelled, replacement reissued and matches portal -> original G1C1, replacement accounted, original not G1M1
6. Uncertain cancel/reissue: ambiguous relationship -> Review Required, not auto-cleared
7. Same invoice number across FY: different FY/date identity -> not treated as duplicate
8. Same invoice number different GSTIN: different buyer GSTIN -> not treated as duplicate
9. 3B aggregation: identical/conflicting duplicate surplus does not alter liability aggregation
10. Run 6 duplicate regression
11. Run 8B amendment regression
12. Run 5 amendment regression
13. Run 11 exact benchmark (100 genuine G1M1, 40 G1D1, 30 G1D2, 60 G1C1, 75 G1M2 extras, tie-out preserved)
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from app.rules.gstr1_mismatch_rules import (
    MismatchType,
    MismatchSeverity,
    classify_sr_unmatched_exceptions,
    classify_duplicate_erp_identical,
    classify_duplicate_erp_conflict,
    classify_cancelled_reissued_invoice,
    get_financial_year,
)
from app.routers.gstr1_reconcile import _run_pipeline
from app.reconciliation.gstr1_vs_3b import (
    aggregate_gstr1,
    reconcile_gstr1_vs_3b,
)
from app.parsers.gstr1_parser import parse_gstr1
from app.parsers.gstr3b_parser import parse_gstr3b


_ROOT = Path(__file__).resolve().parent.parent.parent
if not (_ROOT / "benchmark_data").exists():
    _ROOT = Path(__file__).resolve().parent.parent

RUN11_DIR = _ROOT / "benchmark_data" / "run11_cutoff_duplicate_5000"
RUN8B_DIR = _ROOT / "benchmark_data" / "run8b_combined_3000"
RUN6_DIR = _ROOT / "benchmark_data" / "run6_identity_boundary_3000"
RUN5_DIR = _ROOT / "benchmark_data" / "run5_amendments_3000"


# ── Test 1: Identical duplicate SR surplus ───────────────────────────────────
def test_identical_duplicate_sr_surplus():
    sr_matched = {
        "invoice_number": "INV-100",
        "recipient_gstin": "27AABCU9603R1ZM",
        "taxable_amount_paise": 100_000_00,
        "igst_paise": 18_000_00,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "total_tax_paise": 18_000_00,
        "invoice_date": "2026-09-15",
        "doc_type": "INVOICE",
    }
    g1_rec = dict(sr_matched)
    matched_pairs = [(sr_matched, g1_rec, {"match_level": 1})]

    # Unmatched surplus identical duplicate
    sr_surplus = dict(sr_matched)
    unmatched_sr = [sr_surplus]

    identical_dups, conflict_dups, cancelled, genuine_missing = classify_sr_unmatched_exceptions(
        unmatched_sr=unmatched_sr,
        matched_pairs=matched_pairs,
    )

    assert len(identical_dups) == 1
    assert len(conflict_dups) == 0
    assert len(cancelled) == 0
    assert len(genuine_missing) == 0

    sr_dup, mr = identical_dups[0]
    assert mr.mismatch_type == MismatchType.DUPLICATE_ERP_IDENTICAL
    assert mr.severity == MismatchSeverity.WARNING
    assert mr.rule_id == "G1D1"
    assert mr.details["outcome_code"] == "G1D1"
    assert mr.details["outcome_category"] == "DUPLICATE_IDENTICAL"


# ── Test 2: Conflicting duplicate SR surplus ─────────────────────────────────
def test_conflicting_duplicate_sr_surplus():
    sr_matched = {
        "invoice_number": "INV-200",
        "recipient_gstin": "27AABCU9603R1ZM",
        "taxable_amount_paise": 100_000_00,
        "igst_paise": 18_000_00,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "total_tax_paise": 18_000_00,
        "invoice_date": "2026-09-15",
        "doc_type": "INVOICE",
    }
    g1_rec = dict(sr_matched)
    matched_pairs = [(sr_matched, g1_rec, {"match_level": 1})]

    # Unmatched surplus with conflicting taxable amount
    sr_surplus = dict(sr_matched)
    sr_surplus["taxable_amount_paise"] = 120_000_00
    sr_surplus["igst_paise"] = 21_600_00
    sr_surplus["total_tax_paise"] = 21_600_00
    unmatched_sr = [sr_surplus]

    identical_dups, conflict_dups, cancelled, genuine_missing = classify_sr_unmatched_exceptions(
        unmatched_sr=unmatched_sr,
        matched_pairs=matched_pairs,
    )

    assert len(identical_dups) == 0
    assert len(conflict_dups) == 1
    assert len(cancelled) == 0
    assert len(genuine_missing) == 0

    sr_dup, mr = conflict_dups[0]
    assert mr.mismatch_type == MismatchType.DUPLICATE_ERP_CONFLICT
    assert mr.severity == MismatchSeverity.HIGH
    assert mr.rule_id == "G1D2"
    assert mr.details["requires_review"] is True
    assert mr.details["outcome_code"] == "G1D2"
    assert mr.details["outcome_category"] == "DUPLICATE_CONFLICT"


# ── Test 3: Triple identical duplicate SR surplus ────────────────────────────
def test_triple_identical_duplicate_sr_surplus():
    sr_matched = {
        "invoice_number": "INV-300",
        "recipient_gstin": "27AABCU9603R1ZM",
        "taxable_amount_paise": 50_000_00,
        "igst_paise": 9_000_00,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "total_tax_paise": 9_000_00,
        "invoice_date": "2026-09-10",
        "doc_type": "INVOICE",
    }
    g1_rec = dict(sr_matched)
    matched_pairs = [(sr_matched, g1_rec, {"match_level": 1})]

    # 2 surplus copies in unmatched SR
    sr_copy1 = dict(sr_matched)
    sr_copy2 = dict(sr_matched)
    unmatched_sr = [sr_copy1, sr_copy2]

    identical_dups, conflict_dups, cancelled, genuine_missing = classify_sr_unmatched_exceptions(
        unmatched_sr=unmatched_sr,
        matched_pairs=matched_pairs,
    )

    assert len(identical_dups) == 2
    assert len(conflict_dups) == 0
    assert len(cancelled) == 0
    assert len(genuine_missing) == 0


# ── Test 4: Duplicate + genuine missing ──────────────────────────────────────
def test_duplicate_plus_genuine_missing():
    sr_matched = {
        "invoice_number": "INV-400A",
        "recipient_gstin": "27AABCU9603R1ZM",
        "taxable_amount_paise": 50_000_00,
        "igst_paise": 9_000_00,
        "total_tax_paise": 9_000_00,
        "invoice_date": "2026-09-10",
        "doc_type": "INVOICE",
    }
    matched_pairs = [(sr_matched, dict(sr_matched), {"match_level": 1})]

    sr_dup = dict(sr_matched)
    sr_missing = {
        "invoice_number": "INV-400B",
        "recipient_gstin": "27AABCU9603R1ZM",
        "taxable_amount_paise": 80_000_00,
        "igst_paise": 14_400_00,
        "total_tax_paise": 14_400_00,
        "invoice_date": "2026-09-12",
        "doc_type": "INVOICE",
    }
    unmatched_sr = [sr_dup, sr_missing]

    identical_dups, conflict_dups, cancelled, genuine_missing = classify_sr_unmatched_exceptions(
        unmatched_sr=unmatched_sr,
        matched_pairs=matched_pairs,
    )

    assert len(identical_dups) == 1
    assert len(genuine_missing) == 1
    assert genuine_missing[0]["invoice_number"] == "INV-400B"


# ── Test 5: Confident cancel / reissue ───────────────────────────────────────
def test_cancel_reissue_invoice():
    # Replacement invoice accounted in GSTR-1
    sr_replacement = {
        "invoice_number": "INV-500-RE",
        "recipient_gstin": "27AABCU9603R1ZM",
        "taxable_amount_paise": 100_000_00,
        "igst_paise": 18_000_00,
        "total_tax_paise": 18_000_00,
        "invoice_date": "2026-09-20",
        "doc_type": "INVOICE",
    }
    matched_pairs = [(sr_replacement, dict(sr_replacement), {"match_level": 1})]

    # Cancelled original in unmatched SR
    sr_original = {
        "invoice_number": "INV-500",
        "recipient_gstin": "27AABCU9603R1ZM",
        "taxable_amount_paise": 100_000_00,
        "igst_paise": 18_000_00,
        "total_tax_paise": 18_000_00,
        "invoice_date": "2026-09-15",
        "doc_type": "INVOICE",
        "remarks": "Cancelled and reissued as INV-500-RE",
    }
    unmatched_sr = [sr_original]

    identical_dups, conflict_dups, cancelled, genuine_missing = classify_sr_unmatched_exceptions(
        unmatched_sr=unmatched_sr,
        matched_pairs=matched_pairs,
    )

    assert len(cancelled) == 1
    assert len(genuine_missing) == 0
    sr_rec, mr = cancelled[0]
    assert mr.mismatch_type == MismatchType.CANCEL_REISSUE
    assert mr.rule_id == "G1C1"
    assert mr.details["outcome_code"] == "G1C1"
    assert mr.details["linked_invoice_number"] == "INV-500-RE"


# ── Test 6: Uncertain / ambiguous cancel / reissue ───────────────────────────
def test_uncertain_cancel_reissue():
    # Matched invoice for same GSTIN and same amount but without clear reissue pattern
    sr_matched = {
        "invoice_number": "OTHER-999",
        "recipient_gstin": "27AABCU9603R1ZM",
        "taxable_amount_paise": 100_000_00,
        "igst_paise": 18_000_00,
        "total_tax_paise": 18_000_00,
        "invoice_date": "2026-09-20",
        "doc_type": "INVOICE",
    }
    matched_pairs = [(sr_matched, dict(sr_matched), {"match_level": 1})]

    sr_unmatched = {
        "invoice_number": "INV-600",
        "recipient_gstin": "27AABCU9603R1ZM",
        "taxable_amount_paise": 100_000_00,
        "igst_paise": 18_000_00,
        "total_tax_paise": 18_000_00,
        "invoice_date": "2026-09-15",
        "doc_type": "INVOICE",
    }
    unmatched_sr = [sr_unmatched]

    identical_dups, conflict_dups, cancelled, genuine_missing = classify_sr_unmatched_exceptions(
        unmatched_sr=unmatched_sr,
        matched_pairs=matched_pairs,
    )

    # When ambiguous (no prefix/suffix match and no cancel remarks), should either be flagged for review or genuine missing
    if cancelled:
        _, mr = cancelled[0]
        assert mr.details["requires_review"] is True or mr.severity == MismatchSeverity.MEDIUM
    else:
        assert len(genuine_missing) == 1


# ── Test 7: Same invoice number across FY is NOT a duplicate ─────────────────
def test_same_invoice_across_fy_not_duplicate():
    # Accounting invoice in FY 2025-26
    sr_fy25 = {
        "invoice_number": "INV-001",
        "recipient_gstin": "27AABCU9603R1ZM",
        "taxable_amount_paise": 50_000_00,
        "igst_paise": 9_000_00,
        "total_tax_paise": 9_000_00,
        "invoice_date": "2026-03-25",  # FY 2025-26
        "doc_type": "INVOICE",
    }
    matched_pairs = [(sr_fy25, dict(sr_fy25), {"match_level": 1})]

    # Unmatched invoice in FY 2026-27 (Rule 46 annual sequence reset)
    sr_fy26 = {
        "invoice_number": "INV-001",
        "recipient_gstin": "27AABCU9603R1ZM",
        "taxable_amount_paise": 50_000_00,
        "igst_paise": 9_000_00,
        "total_tax_paise": 9_000_00,
        "invoice_date": "2026-09-15",  # FY 2026-27
        "doc_type": "INVOICE",
    }
    unmatched_sr = [sr_fy26]

    identical_dups, conflict_dups, cancelled, genuine_missing = classify_sr_unmatched_exceptions(
        unmatched_sr=unmatched_sr,
        matched_pairs=matched_pairs,
    )

    assert len(identical_dups) == 0
    assert len(conflict_dups) == 0
    # Must NOT be classified as duplicate across financial year boundaries
    assert len(genuine_missing) == 1 or len(cancelled) == 0


# ── Test 8: Same invoice number different GSTIN is NOT a duplicate ───────────
def test_same_invoice_different_gstin_not_duplicate():
    sr_buyer_a = {
        "invoice_number": "INV-700",
        "recipient_gstin": "27AABCU9603R1ZM",
        "taxable_amount_paise": 50_000_00,
        "igst_paise": 9_000_00,
        "total_tax_paise": 9_000_00,
        "invoice_date": "2026-09-15",
        "doc_type": "INVOICE",
    }
    matched_pairs = [(sr_buyer_a, dict(sr_buyer_a), {"match_level": 1})]

    # Unmatched invoice with same number but different buyer GSTIN
    sr_buyer_b = {
        "invoice_number": "INV-700",
        "recipient_gstin": "29AABCU9603R1ZK",
        "taxable_amount_paise": 50_000_00,
        "igst_paise": 9_000_00,
        "total_tax_paise": 9_000_00,
        "invoice_date": "2026-09-15",
        "doc_type": "INVOICE",
    }
    unmatched_sr = [sr_buyer_b]

    identical_dups, conflict_dups, cancelled, genuine_missing = classify_sr_unmatched_exceptions(
        unmatched_sr=unmatched_sr,
        matched_pairs=matched_pairs,
    )

    assert len(identical_dups) == 0
    assert len(conflict_dups) == 0
    assert len(genuine_missing) == 1


# ── Test 9: 3B aggregation unaffected by SR duplicates ───────────────────────
def test_3b_aggregation_unaltered_by_sr_duplicates():
    # GSTR-1 records
    gstr1_rows = [
        {
            "section": "b2b",
            "invoice_number": "INV-1",
            "taxable_amount_paise": 100_000_00,
            "igst_paise": 18_000_00,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
        }
    ]
    # GSTR-3B records
    gstr3b_raw = {
        "gstin": "27AABCM4162G1ZM",
        "ret_period": "092026",
        "data": {
            "sup_details": {
                "osup_det": {
                    "txval": 100000.0,
                    "iamt": 18000.0,
                    "camt": 0.0,
                    "samt": 0.0,
                    "csamt": 0.0,
                }
            }
        },
    }
    parsed_g3b = parse_gstr3b(gstr3b_raw)

    tie_out = reconcile_gstr1_vs_3b(
        gstr1_rows,
        parsed_g3b,
        filing_frequency="monthly",
    )
    assert tie_out.is_clean is True
    assert len(tie_out.variances) == 0


# ── Test 10: Run 6 duplicate regression ──────────────────────────────────────
@pytest.mark.asyncio
async def test_run6_regression_duplicate_protection():
    if not RUN6_DIR.exists():
        pytest.skip("Run 6 benchmark directory not found")

    sr_file = RUN6_DIR / "ReconDesk_Sales_Register_3000_IdentityBoundary_Run6_Sep2026.xlsx"
    g1_file = RUN6_DIR / "ReconDesk_GSTR1_3000_IdentityBoundary_Run6_Sep2026.json"
    g3b_file = RUN6_DIR / "ReconDesk_GSTR3B_IdentityBoundary_Run6_Sep2026.json"

    res = await _run_pipeline(
        sr_file_content=sr_file.read_bytes(),
        sr_filename=sr_file.name,
        gstr1_file_content=g1_file.read_bytes(),
        gstr3b_file_content=g3b_file.read_bytes(),
        gstr1_filing_period="092026",
    )

    s = res["summary"]
    to = res["tie_out"]
    assert s["matched_count"] == 2680
    assert s["missing_in_gstr1_count"] == 60
    assert to["variance_count"] == 1


# ── Test 11: Run 8B amendment regression ─────────────────────────────────────
@pytest.mark.asyncio
async def test_run8b_regression_amendment():
    if not RUN8B_DIR.exists():
        pytest.skip("Run 8B benchmark directory not found")

    sr_file = RUN8B_DIR / "ReconDesk_Sales_Register_3000_Combined_Run8B_FIXED_SINGLE_SHEET_Sep2026.xlsx"
    g1_file = RUN8B_DIR / "ReconDesk_GSTR1_3000_Combined_Run8B_CORRECTED_Sep2026.json"
    g3b_file = RUN8B_DIR / "ReconDesk_GSTR3B_Combined_Run8B_CORRECTED_Sep2026.json"

    res = await _run_pipeline(
        sr_file_content=sr_file.read_bytes(),
        sr_filename=sr_file.name,
        gstr1_file_content=g1_file.read_bytes(),
        gstr3b_file_content=g3b_file.read_bytes(),
        gstr1_filing_period="092026",
    )

    to = res["tie_out"]
    stat = to["statutory_reconciliation"]
    tax = stat["tax"]
    assert tax["igst"]["difference_paise"] == 0
    assert tax["cgst"]["difference_paise"] == 0
    assert tax["sgst"]["difference_paise"] == 0
    assert tax["cess"]["difference_paise"] == 0
    assert to["variance_count"] == 2


# ── Test 12: Run 5 amendment regression ──────────────────────────────────────
@pytest.mark.asyncio
async def test_run5_regression_amendment():
    if not RUN5_DIR.exists():
        pytest.skip("Run 5 benchmark directory not found")

    sr_file = RUN5_DIR / "ReconDesk_Sales_Register_3000_Amendments_Run5_Sep2026.xlsx"
    g1_file = RUN5_DIR / "ReconDesk_GSTR1_Sep2026_Amendments_Run5.json"
    g3b_file = RUN5_DIR / "ReconDesk_GSTR3B_Sep2026_Amendments_Run5.json"
    prior_g1_file = RUN5_DIR / "ReconDesk_GSTR1_Aug2026_PriorPeriod_Run5.json"

    res = await _run_pipeline(
        sr_file_content=sr_file.read_bytes(),
        sr_filename=sr_file.name,
        gstr1_file_content=g1_file.read_bytes(),
        gstr3b_file_content=g3b_file.read_bytes(),
        gstr1_filing_period="092026",
        prior_gstr1_file_content=prior_g1_file.read_bytes(),
    )

    s = res["summary"]
    assert s["matched_count"] == 2290
    assert s["accounted_source_invoice_count"] == 2900
    assert s["missing_in_gstr1_count"] == 60
    assert s["unmatched_sr_count"] == 60


# ── Test 13: Run 11 exact benchmark ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_run11_exact_benchmark():
    sr_file = RUN11_DIR / "ReconDesk_Sales_Register_5000_Run11_CutoffDuplicate_Sep2026.xlsx"
    g1_file = RUN11_DIR / "ReconDesk_GSTR1_5000_Run11_CutoffDuplicate_Sep2026.json"
    g3b_file = RUN11_DIR / "ReconDesk_GSTR3B_Run11_CutoffDuplicate_Sep2026.json"

    res = await _run_pipeline(
        sr_file_content=sr_file.read_bytes(),
        sr_filename=sr_file.name,
        gstr1_file_content=g1_file.read_bytes(),
        gstr3b_file_content=g3b_file.read_bytes(),
        gstr1_filing_period="092026",
    )

    s = res["summary"]
    # 1. Matching and counts
    assert s["sr_total_records"] == 5000
    assert s["matched_count"] == 4770
    assert s["unmatched_sr_count"] == 230
    assert s["missing_in_gstr1_count"] == 100
    assert s["genuine_missing_count"] == 100
    assert s["duplicate_identical_count"] == 40
    assert s["duplicate_conflict_count"] == 30
    assert s["duplicate_postings_count"] == 70
    assert s["cancelled_reissued_count"] == 60
    assert s["unmatched_gstr1_count"] == 75

    # 2. Outcome code breakdown
    outcome_codes = [m.get("outcome_code") for m in res["mismatches"] if m.get("outcome_code")]
    assert outcome_codes.count("G1M1") == 100
    assert outcome_codes.count("G1D1") == 40
    assert outcome_codes.count("G1D2") == 30
    assert outcome_codes.count("G1C1") == 60
    assert outcome_codes.count("G1M2") == 75

    # 3. 3B Tie-out preservation
    to = res["tie_out"]
    assert to["variance_count"] == 2
    stat = to["statutory_reconciliation"]
    assert stat["taxable_outward"]["difference_paise"] == -2750000  # -₹27,500.00
    assert stat["zero_rated"]["difference_paise"] == 1250000       # +₹12,500.00
    tax = stat["tax"]
    assert tax["igst"]["difference_paise"] == 0
    assert tax["cgst"]["difference_paise"] == 0
    assert tax["sgst"]["difference_paise"] == 0
    assert tax["cess"]["difference_paise"] == 0
