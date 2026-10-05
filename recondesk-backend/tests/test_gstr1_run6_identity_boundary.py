"""Targeted regression tests for ReconDesk Run 6 Identity Boundary and Duplicate Handling.

Validates:
1. September 2026 B2CL threshold boundary (invoice_value > ₹1,00,000 -> B2CL, <= ₹1,00,000 -> B2CS).
2. Historical July 2024 threshold boundary (invoice_value > ₹2,50,000 -> B2CL, <= ₹2,50,000 -> B2CS).
3. Legitimate distinct invoices (different GSTIN or different date) are NOT duplicates.
4. Identical duplicate GSTR-1 records surfaced as G1M_DUPLICATE_IDENTICAL (warning), not G1M2 Extra.
5. Conflicting duplicate GSTR-1 records surfaced as G1M_DUPLICATE_CONFLICT (review required), not G1M2 Extra.
6. 100 surplus duplicate records in Run 6 recognized (60 identical + 40 conflicting).
7. Genuine 50 GSTR-1-only records reported as unmatched/extra.
8. Duplicate-aware liability aggregation prevents double-counting in GSTR-1 vs 3B tie-out.
9. Run 6 tie-out produces exactly the 1 intentional variance (-₹20,000 taxable), 0 tax variances.
10. All 40 boundary rows accounted in B2CS; missing count is exactly 60; coverage is 98.00%.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from app.rules.gstr1_rules import get_gstr1_rules
from app.routers.gstr1_reconcile import _is_sr_b2cs_record, _run_pipeline
from app.reconciliation.gstr1_vs_3b import (
    aggregate_gstr1,
    reconcile_gstr1_vs_3b,
    _records_deduplicated_for_liability,
)
from app.parsers.gstr1_parser import parse_gstr1
from app.parsers.gstr3b_parser import parse_gstr3b
from app.rules.gstr1_mismatch_rules import (
    MismatchType,
    MismatchSeverity,
    classify_duplicate_identical,
    classify_duplicate_conflict,
)

_ROOT = Path(__file__).resolve().parent.parent.parent
if not (_ROOT / "benchmark_data").exists():
    _ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_DIR = _ROOT / "benchmark_data" / "run6_identity_boundary_3000"
SR_FILE = BENCHMARK_DIR / "ReconDesk_Sales_Register_3000_IdentityBoundary_Run6_Sep2026.xlsx"
G1_FILE = BENCHMARK_DIR / "ReconDesk_GSTR1_3000_IdentityBoundary_Run6_Sep2026.json"
G3B_FILE = BENCHMARK_DIR / "ReconDesk_GSTR3B_IdentityBoundary_Run6_Sep2026.json"


# ── Test 1: Sep 2026 ₹100,000.00 -> B2CS ───────────────────────────────────
def test_sep2026_boundary_100k_exact_is_b2cs():
    rules = get_gstr1_rules("2026-09")
    assert rules.b2cl_threshold_paise == 10_000_000

    # Invoice value exactly ₹1,00,000.00 (10,000,000 paise)
    assert rules.is_b2cs(inv_val_paise=10_000_000, is_interstate=True, is_registered=False) is True
    assert rules.is_b2cl(inv_val_paise=10_000_000, is_interstate=True, is_registered=False) is False

    rec = {
        "invoice_number": "INV-100K-EXACT",
        "invoice_value_paise": 10_000_000,
        "taxable_amount_paise": 84_745_76,
        "igst_paise": 15_254_24,
        "place_of_supply": "29-Karnataka",
        "gstin": None,
    }
    assert _is_sr_b2cs_record(rec, supplier_gstin="27ISKPK1273H1ZF", return_period="2026-09") is True


# ── Test 2: Sep 2026 ₹100,000.01 -> B2CL ───────────────────────────────────
def test_sep2026_boundary_100k_01_is_b2cl():
    rules = get_gstr1_rules("2026-09")

    # Invoice value ₹1,00,000.01 (10,000,001 paise)
    assert rules.is_b2cs(inv_val_paise=10_000_001, is_interstate=True, is_registered=False) is False
    assert rules.is_b2cl(inv_val_paise=10_000_001, is_interstate=True, is_registered=False) is True

    rec = {
        "invoice_number": "INV-100K-01",
        "invoice_value_paise": 10_000_001,
        "taxable_amount_paise": 84_745_77,
        "igst_paise": 15_254_24,
        "place_of_supply": "29-Karnataka",
        "gstin": None,
    }
    assert _is_sr_b2cs_record(rec, supplier_gstin="27ISKPK1273H1ZF", return_period="2026-09") is False


# ── Test 3: Jul 2024 ₹250,000.00 -> B2CS ───────────────────────────────────
def test_jul2024_boundary_250k_exact_is_b2cs():
    rules = get_gstr1_rules("2024-07")
    assert rules.b2cl_threshold_paise == 25_000_000

    # Invoice value exactly ₹2,50,000.00 (25,000,000 paise)
    assert rules.is_b2cs(inv_val_paise=25_000_000, is_interstate=True, is_registered=False) is True
    assert rules.is_b2cl(inv_val_paise=25_000_000, is_interstate=True, is_registered=False) is False

    rec = {
        "invoice_number": "INV-250K-EXACT",
        "invoice_value_paise": 25_000_000,
        "taxable_amount_paise": 211_864_41,
        "igst_paise": 38_135_59,
        "place_of_supply": "29-Karnataka",
        "gstin": None,
    }
    assert _is_sr_b2cs_record(rec, supplier_gstin="27ISKPK1273H1ZF", return_period="2024-07") is True


# ── Test 4: Jul 2024 ₹250,000.01 -> B2CL ───────────────────────────────────
def test_jul2024_boundary_250k_01_is_b2cl():
    rules = get_gstr1_rules("2024-07")

    # Invoice value ₹2,50,000.01 (25,000,001 paise)
    assert rules.is_b2cs(inv_val_paise=25_000_001, is_interstate=True, is_registered=False) is False
    assert rules.is_b2cl(inv_val_paise=25_000_001, is_interstate=True, is_registered=False) is True

    rec = {
        "invoice_number": "INV-250K-01",
        "invoice_value_paise": 25_000_001,
        "taxable_amount_paise": 211_864_42,
        "igst_paise": 38_135_59,
        "place_of_supply": "29-Karnataka",
        "gstin": None,
    }
    assert _is_sr_b2cs_record(rec, supplier_gstin="27ISKPK1273H1ZF", return_period="2024-07") is False


# ── Test 5: Same invoice number, different GSTIN -> NOT duplicate ───────────
def test_same_invno_diff_gstin_not_duplicate():
    r1 = {
        "section": "b2b",
        "recipient_gstin": "24TYDMR7639A1Z4",
        "invoice_number": "INV-001",
        "invoice_date": "2026-09-10",
        "document_type": "INVOICE",
        "taxable_amount_paise": 1000000,
        "igst_paise": 180000,
    }
    r2 = {
        "section": "b2b",
        "recipient_gstin": "36MVEVE7030V1ZE",
        "invoice_number": "INV-001",
        "invoice_date": "2026-09-10",
        "document_type": "INVOICE",
        "taxable_amount_paise": 1000000,
        "igst_paise": 180000,
    }

    deduped = _records_deduplicated_for_liability([r1, r2])
    assert len(deduped) == 2, "Different GSTINs must not be conflated as duplicates"


# ── Test 6: Same invoice number, same GSTIN, different date -> NOT duplicate
def test_same_invno_same_gstin_diff_date_not_duplicate():
    r1 = {
        "section": "b2b",
        "recipient_gstin": "24TYDMR7639A1Z4",
        "invoice_number": "INV-002",
        "invoice_date": "2026-09-05",
        "document_type": "INVOICE",
        "taxable_amount_paise": 2000000,
        "igst_paise": 360000,
    }
    r2 = {
        "section": "b2b",
        "recipient_gstin": "24TYDMR7639A1Z4",
        "invoice_number": "INV-002",
        "invoice_date": "2026-09-20",
        "document_type": "INVOICE",
        "taxable_amount_paise": 3000000,
        "igst_paise": 540000,
    }

    deduped = _records_deduplicated_for_liability([r1, r2])
    assert len(deduped) == 2, "Different invoice dates must not be conflated as duplicates"


# ── Test 7: Identical duplicate GSTR-1 -> matched once, warning surfaced ────
def test_identical_duplicate_gstr1_handling():
    r_dup = {
        "section": "b2b",
        "recipient_gstin": "24TYDMR7639A1Z4",
        "invoice_number": "INV-IDENTICAL-01",
        "invoice_date": "2026-09-15",
        "document_type": "INVOICE",
        "taxable_amount_paise": 5000000,
        "total_tax_paise": 900000,
    }
    canon = dict(r_dup)

    mr = classify_duplicate_identical(r_dup, canon)
    assert mr.mismatch_type == MismatchType.DUPLICATE_IDENTICAL
    assert mr.severity == MismatchSeverity.WARNING
    assert mr.rule_id == "G1M_DUPLICATE_IDENTICAL"
    assert "IDENTICAL" in mr.decision_what


# ── Test 8: Conflicting duplicate -> accounted once, review required ─────────
def test_conflicting_duplicate_handling():
    canon = {
        "section": "b2b",
        "recipient_gstin": "24TYDMR7639A1Z4",
        "invoice_number": "INV-CONFLICT-01",
        "invoice_date": "2026-09-15",
        "document_type": "INVOICE",
        "taxable_amount_paise": 5000000,
        "total_tax_paise": 900000,
    }
    dup = {
        "section": "b2b",
        "recipient_gstin": "24TYDMR7639A1Z4",
        "invoice_number": "INV-CONFLICT-01",
        "invoice_date": "2026-09-15",
        "document_type": "INVOICE",
        "taxable_amount_paise": 5500000,
        "total_tax_paise": 990000,
    }

    mr = classify_duplicate_conflict(dup, canon, differed_fields=["taxable_amount", "total_tax"])
    assert mr.mismatch_type == MismatchType.DUPLICATE_CONFLICT
    assert mr.severity == MismatchSeverity.HIGH
    assert mr.rule_id == "G1M_DUPLICATE_CONFLICT"
    assert "CONFLICT" in mr.decision_what
    assert mr.details["differed_fields"] == ["taxable_amount", "total_tax"]


# ── Tests 9–14: Complete 3,000-record Run 6 End-to-End Benchmark Gate ────────
@pytest.fixture(scope="module")
def run6_benchmark_result():
    if not SR_FILE.exists() or not G1_FILE.exists() or not G3B_FILE.exists():
        pytest.skip("Run 6 benchmark files not found")

    import asyncio
    with open(SR_FILE, "rb") as f_sr, open(G1_FILE, "rb") as f_g1, open(G3B_FILE, "rb") as f_g3b:
        sr_bytes = f_sr.read()
        g1_bytes = f_g1.read()
        g3b_bytes = f_g3b.read()

    res = asyncio.run(_run_pipeline(
        sr_bytes, "sr.xlsx",
        g1_bytes,
        g3b_bytes,
        "2026-09",
        None,
        None,
    ))
    return res


def test_test9_run6_benchmark_duplicate_counts(run6_benchmark_result):
    summary = run6_benchmark_result["summary"]
    assert summary["duplicate_gstr1_record_count"] == 100, "Must detect exactly 100 surplus duplicate records"
    assert summary["duplicate_gstr1_group_count"] == 100, "Must detect exactly 100 duplicate groups"
    assert summary["identical_duplicate_count"] == 60, "Must detect exactly 60 identical duplicates"
    assert summary["conflicting_duplicate_count"] == 40, "Must detect exactly 40 conflicting duplicates"


def test_test10_run6_genuine_extra_invoices(run6_benchmark_result):
    summary = run6_benchmark_result["summary"]
    assert summary["unmatched_gstr1_count"] == 50, "Genuine extra invoices in GSTR-1 must be exactly 50"


def test_test11_duplicate_aware_gstr1_aggregation():
    with open(G1_FILE, "rb") as f:
        parsed_g1 = parse_gstr1(f.read())
    with open(G3B_FILE, "rb") as f:
        parsed_g3b = parse_gstr3b(json.loads(f.read()))

    # Direct aggregate with deduplication
    agg = aggregate_gstr1(parsed_g1["records"])
    # GSTR-3B Table 3.1(a) taxable is 365,340,189.39; intentional diff is -20,000.00
    expected_taxable_paise = 365_320_189_39  # 365,340,189.39 - 20,000.00
    assert agg.taxable_value_paise == expected_taxable_paise, (
        f"GSTR-1 aggregation must not be inflated by duplicate records. "
        f"Expected {expected_taxable_paise}, got {agg.taxable_value_paise}"
    )


def test_test12_run6_tieout_single_intentional_variance(run6_benchmark_result):
    tieout = run6_benchmark_result["tie_out"]
    assert tieout["is_clean"] is False
    assert len(tieout["variances"]) == 1, f"Expected exactly 1 variance, got {len(tieout['variances'])}: {tieout['variances']}"

    v = tieout["variances"][0]
    assert v["field"] == "taxable_value"
    assert v["diff"] == "₹20,000.00"
    assert v["gstr1"] == "₹365,320,189.39"
    assert v["gstr3b"] == "₹365,340,189.39"


def test_test13_run6_b2cs_boundary_rows_included(run6_benchmark_result):
    b2cs = run6_benchmark_result["b2cs_reconciliation"]
    assert b2cs["source_invoice_count"] == 260, (
        "B2CS must include 220 B2CS_EXACT + 40 B2CL_BOUNDARY_EQ_100000 = 260 rows"
    )
    assert b2cs["accounted_invoice_count"] == 260
    assert b2cs["unaccounted_invoice_count"] == 0


def test_test14_run6_missing_count_genuine_60(run6_benchmark_result):
    summary = run6_benchmark_result["summary"]
    assert summary["missing_in_gstr1_count"] == 60, "Only the 60 MISSING_G1 invoices must be missing"
    assert summary["matched_count"] == 2680
    assert summary["accounted_source_invoice_count"] == 2940
    assert summary["unaccounted_source_invoice_count"] == 60
    assert summary["coverage_percentage"] == 98.0
