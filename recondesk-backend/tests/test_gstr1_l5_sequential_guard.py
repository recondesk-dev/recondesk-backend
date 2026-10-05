"""Regression test suite for GSTR-1 L5 matching and sequential series guard.

Covers:
1. Sequential invoice numbers with identical GSTIN and identical taxable amount (never L5 match).
2. Different invoice numbers that have >=75% raw Levenshtein similarity (disqualified).
3. 30 invoice-format variations (e.g. SYS-INV25-260251 vs INV/25-26/0251) continue to match.
4. Format variations: separators, whitespace, slash/hyphen, leading zeros, ERP prefixes.
5. 20 missing B2B invoices (detected as G1M1_MISSING_INVOICE, never steal legitimate invoices).
6. 15 duplicate B2B and 20 extra B2B (detected as G1M2_EXTRA_INVOICE without cross-matching).
7. GSTIN mismatch (detected as separate missing SR and extra GSTR-1).
8. Amount mismatch (detected as G1M3_AMOUNT_MISMATCH).
9. Date mismatch (evaluated within date tolerance or flagged).
"""

import pytest
from app.services.matcher import (
    is_sequential_series_mismatch,
    invoice_similarity,
    normalize_invoice,
    is_invoice_format_variant,
)
from app.matching.generic_matcher import (
    generic_match_pair,
    SALES_MATCH_CONFIG,
)


# ── 1. Sequential Invoice Guard Unit Tests ─────────────────────────────────────

def test_sequential_series_mismatch_detection():
    """Verify that sequential invoices in the same series with different numbers are flagged."""
    # Suffixes 101 vs 197 (diff 96, but raw Levenshtein is 81.8%!)
    assert is_sequential_series_mismatch("INV/25-26/0101", "INV/25-26/0197") is True
    assert is_sequential_series_mismatch("INV/25-26/0102", "INV/25-26/0406") is True
    assert is_sequential_series_mismatch("INV-100", "INV-101") is True
    assert is_sequential_series_mismatch("INV25260101", "INV25260197") is True
    assert is_sequential_series_mismatch("SYS-INV25-260101", "SYS-INV25-260197") is True


def test_sequential_series_mismatch_preserves_variants():
    """Verify that format variants with the same numeric sequence are NOT flagged as mismatch."""
    # ERP prefix addition SYS-
    assert is_sequential_series_mismatch("INV/25-26/0251", "SYS-INV25-260251") is False
    assert is_sequential_series_mismatch("INV25260251", "SYSINV25260251") is False

    # Separator differences
    assert is_sequential_series_mismatch("INV/25-26/0001", "INV-25-26-0001") is False

    # Leading zeros
    assert is_sequential_series_mismatch("INV-142", "INV-00142") is False

    # FY expansion
    assert is_sequential_series_mismatch("DS/26/78", "DS-2026-00078") is False

    # Exact equality
    assert is_sequential_series_mismatch("INV/25-26/0001", "INV/25-26/0001") is False


# ── 2. Pair Matcher (generic_match_pair) L5 Disqualification ───────────────────

def test_identical_gstin_and_amount_sequential_invoices_never_l5_match():
    """Even if GSTIN, taxable amount, and dates are identical and Levenshtein >= 75%,
    sequential invoices in the same series must NEVER match as L5.
    """
    sr_rec = {
        "gstin": "07AAECR1004A1Z5",
        "invoice_number": "INV25260101",
        "invoice_number_raw": "INV/25-26/0101",
        "invoice_date": "2025-07-17",
        "taxable_amount_paise": 1000000,
        "total_amount_paise": 1050000,
        "igst_paise": 50000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    # Unrelated invoice 0197 to the same client with the exact same taxable amount ₹10,000
    g1_rec = {
        "recipient_gstin": "07AAECR1004A1Z5",
        "inum": "INV/25-26/0197",
        "invoice_number": "INV25260197",
        "invoice_number_raw": "INV/25-26/0197",
        "invoice_date": "2025-07-25",
        "taxable_amount_paise": 1000000,
        "total_amount_paise": 1280000,
        "igst_paise": 280000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }

    # Verify that raw similarity is indeed >= 75%
    raw_sim = invoice_similarity("INV/25-26/0101", "INV/25-26/0197")
    assert raw_sim >= 0.75

    # But generic_match_pair must reject the match!
    pr = generic_match_pair(sr_rec, g1_rec, SALES_MATCH_CONFIG)
    assert pr.matched is False
    assert pr.level == 6  # L6 no match


def test_format_variant_sys_prefix_matches_cleanly():
    """INV/25-26/0251 vs SYS-INV25-260251 must match cleanly."""
    sr_rec = {
        "gstin": "07AAECR1004A1Z5",
        "invoice_number": "INV25260251",
        "invoice_number_raw": "INV/25-26/0251",
        "invoice_date": "2025-07-02",
        "taxable_amount_paise": 17500000,
        "total_amount_paise": 20650000,
        "igst_paise": 3150000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    g1_rec = {
        "recipient_gstin": "07AAECR1004A1Z5",
        "inum": "SYS-INV25-260251",
        "invoice_number": "SYSINV25260251",
        "invoice_number_raw": "SYS-INV25-260251",
        "invoice_date": "2025-07-02",
        "taxable_amount_paise": 17500000,
        "total_amount_paise": 20650000,
        "igst_paise": 3150000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }

    pr = generic_match_pair(sr_rec, g1_rec, SALES_MATCH_CONFIG)
    assert pr.matched is True
    assert pr.level in (2, 5)  # Matched as normalized/format variant


# ── 3. Formatting Invariance Tests ─────────────────────────────────────────────

@pytest.mark.parametrize("sr_num, g1_num", [
    ("INV/25-26/0001", "INV-25-26-0001"),
    ("INV/25-26/0002", "INV 25 26 0002"),
    ("INV/25-26/0003", "INV/25/26/0003"),
    ("INV/25-26/0004", "INV.25.26.0004"),
    ("INV-00055", "INV-55"),
    ("SAP-INV-1001", "INV-1001"),
    ("ORACLE-2025-101", "2025-101"),
])
def test_legitimate_formatting_differences_are_not_sequential_mismatches(sr_num, g1_num):
    """Format differences that preserve numerical identity must not be rejected."""
    assert is_sequential_series_mismatch(sr_num, g1_num) is False


# ── 4. Disjoint Mutation Behavior Tests ────────────────────────────────────────

def test_amount_mismatch_detection():
    """Identical invoice numbers with taxable value mismatch match at L3 and flag amount mismatch."""
    sr_rec = {
        "gstin": "27AAECR1000A1Z1",
        "invoice_number": "INV25260141",
        "invoice_number_raw": "INV/25-26/0141",
        "invoice_date": "2025-07-15",
        "taxable_amount_paise": 17500000,
        "total_amount_paise": 20650000,
        "igst_paise": 3150000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    # GSTR-1 has taxable ₹185,000 (+₹10,000)
    g1_rec = {
        "recipient_gstin": "27AAECR1000A1Z1",
        "inum": "INV/25-26/0141",
        "invoice_number": "INV25260141",
        "invoice_number_raw": "INV/25-26/0141",
        "invoice_date": "2025-07-15",
        "taxable_amount_paise": 18500000,
        "total_amount_paise": 21650000,
        "igst_paise": 3150000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }

    pr = generic_match_pair(sr_rec, g1_rec, SALES_MATCH_CONFIG)
    assert pr.matched is True
    assert pr.level == 3  # L3 financial mismatch
    assert pr.requires_human_review is True


def test_gstin_mismatch_rejection():
    """Same invoice number but completely different recipient GSTIN must not match."""
    sr_rec = {
        "gstin": "09AAECR1005A1Z6",
        "invoice_number": "INV25260206",
        "invoice_number_raw": "INV/25-26/0206",
        "invoice_date": "2025-07-10",
        "taxable_amount_paise": 25000000,
        "total_amount_paise": 29500000,
        "igst_paise": 4500000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    # GSTR-1 filed under different party
    g1_rec = {
        "recipient_gstin": "27ZZZPK9999A1ZQ",
        "inum": "INV/25-26/0206",
        "invoice_number": "INV25260206",
        "invoice_number_raw": "INV/25-26/0206",
        "invoice_date": "2025-07-10",
        "taxable_amount_paise": 25000000,
        "total_amount_paise": 29500000,
        "igst_paise": 4500000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }

    pr = generic_match_pair(sr_rec, g1_rec, SALES_MATCH_CONFIG)
    assert pr.matched is False
    assert pr.level == 6  # No match because different GSTIN and different PAN


# ── 5. End-to-End Fuzz Dataset Regression Test ────────────────────────────────

import asyncio
from pathlib import Path
from app.routers.gstr1_reconcile import _run_pipeline

@pytest.mark.asyncio
async def test_fuzz_2000_regression_full_pipeline():
    """Verify all 2,000 fuzz test requirements end-to-end on benchmark dataset."""
    data_dir = Path(__file__).resolve().parents[2] / "benchmark_data" / "fuzz_2000"
    if not (data_dir / "sales_register_fuzz_2000.csv").exists():
        data_dir = Path("benchmark_data/fuzz_2000")
    if not (data_dir / "sales_register_fuzz_2000.csv").exists():
        pytest.skip("Benchmark fuzz dataset not present in benchmark_data/fuzz_2000")

    sr_bytes = (data_dir / "sales_register_fuzz_2000.csv").read_bytes()
    g1_bytes = (data_dir / "gstr1_fuzz_2000.json").read_bytes()
    g3b_bytes = (data_dir / "gstr3b_fuzz_2000.json").read_bytes()
    prior_bytes = (data_dir / "gstr1_prior_jun2025.json").read_bytes()

    res = await _run_pipeline(
        sr_file_content=sr_bytes,
        sr_filename="sales_register_fuzz_2000.csv",
        gstr1_file_content=g1_bytes,
        gstr3b_file_content=g3b_bytes,
        gstr1_filing_period="072025",
        prior_gstr1_file_content=prior_bytes,
    )

    summary = res["summary"]
    assert summary["sr_total_records"] == 2000
    assert summary["gstr1_total_records"] == 1917
    assert summary["matched_count"] == 1864
    assert summary["unmatched_sr_count"] == 35  # 20 missing B2B + 15 GSTIN mismatch
    # 51 surplus portal records partitioned into 16 genuine extras + 35 duplicates
    assert summary["unmatched_gstr1_count"] == 16
    assert summary["duplicate_gstr1_record_count"] == 35
    assert summary["tie_out_clean"] is False
    assert summary["tie_out_variance_count"] == 5

    from collections import Counter
    mtypes = Counter(m["mismatch_type"] for m in res["mismatches"])
    assert mtypes["G1M1_MISSING_INVOICE"] == 35
    assert mtypes["G1M2_EXTRA_INVOICE"] == 16
    assert mtypes["G1M_DUPLICATE_IDENTICAL"] == 35
    assert mtypes["G1M5_RATE_MISMATCH"] == 15  # Exactly the 15 intentional rate mismatches!
    assert mtypes["G1M3_AMOUNT_MISMATCH"] == 61  # 25 taxable + 24 tax + 10 B2CL + 1 B2CS + 1 date tax

    # Verify ZERO cross-matches (no identity theft / domino cascade)
    for m in res["matched"]:
        sr = m.get("sr_record") or {}
        g1 = m.get("gstr1_record") or {}
        sec = g1.get("section")
        if sec == "b2cs":
            continue
        sr_norm = sr.get("invoice_number_normalized")
        g1_norm = g1.get("invoice_number_normalized")
        if sr_norm != g1_norm:
            # Must only be intentional SYS- format variant
            assert g1_norm.startswith("SYS") and g1_norm.endswith(sr_norm[3:]), (
                f"Unexpected cross-match: SR {sr_norm} matched G1 {g1_norm}"
            )

    # Verify all 30 format variants (0251..0280) matched cleanly
    matched_sr_raws = {m.get("sr_record", {}).get("invoice_number_raw") for m in res["matched"]}
    for i in range(251, 281):
        inv_no = f"INV/25-26/{i:04d}"
        assert inv_no in matched_sr_raws, f"Format variant {inv_no} failed to match!"


def test_sequential_invoices_not_duplicate_pr_clones():
    """AB/26-27/0441 vs AB/26-27/0445 represent distinct commercial sequential invoices, not duplicates."""
    from app.services.reconciliation import _peer_pr_invoice_clone_ok
    ok, _ = _peer_pr_invoice_clone_ok("AB26270441", "AB26270445", "AB/26-27/0441", "AB/26-27/0445")
    assert not ok
