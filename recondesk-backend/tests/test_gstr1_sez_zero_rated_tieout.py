"""Targeted test suite for SEZ and zero-rated GSTR-1 -> GSTR-3B tie-out classification.

Validates:
TEST 1 — SEZWP classification (3.1(b) taxable + IGST, 0 to 3.1(a), 0 to 3.1(c))
TEST 2 — SEZWOP classification (3.1(b) taxable, 0 to 3.1(a), 0 to 3.1(c))
TEST 3 — Export WPAY -> 3.1(b)
TEST 4 — Export WOPAY -> 3.1(b)
TEST 5 — 0% ordinary domestic supply -> 3.1(c) (ensures 0% domestic does not route to 3.1(b))
TEST 6 — Mixed bucket regression (one record per bucket lands in exactly one bucket)
TEST 7 — SEZWP IGST isolation (included in 3.1(b), excluded from 3.1(a))
TEST 8 — SEZWOP taxable preservation (taxable value preserved when tax = 0)
BENCHMARK — Corrected Run 4B 3,000-record benchmark tie-out (only the 2 intended variances)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.parsers.gstr1_parser import parse_gstr1
from app.parsers.gstr3b_parser import parse_gstr3b
from app.reconciliation.gstr1_vs_3b import (
    GSTR1Aggregate,
    GSTR3BBucket,
    GSTR3BSummary,
    aggregate_gstr1,
    compute_variances,
    map_gstr1_supply_to_gstr3b_bucket,
    reconcile_gstr1_vs_3b,
    TieOutVarianceType,
)


# ══════════════════════════════════════════════════════════════════════════════
# Focused Tests 1 to 8
# ══════════════════════════════════════════════════════════════════════════════

def test_1_sezwp_classification():
    """TEST 1 — SEZWP classification.

    Input:
    inv_typ = SEZWP, taxable = 100000, IGST = 18000
    Expected:
    3.1(b): taxable = 100000, IGST = 18000
    3.1(a): 0 contribution
    3.1(c): 0 contribution
    """
    rec = {
        "section": "b2b",
        "inv_typ": "SEZWP",
        "invoice_type": "B2B",
        "doc_type": "INVOICE",
        "taxable_amount_paise": 100_000_00,  # ₹100,000
        "igst_paise": 18_000_00,            # ₹18,000
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
        "rate": 18.0,
    }

    assert map_gstr1_supply_to_gstr3b_bucket(rec) == GSTR3BBucket.TABLE_3_1_B_ZERO_RATED

    agg = aggregate_gstr1([rec])
    # 3.1(b) contribution
    assert agg.zero_rated_taxable_paise == 100_000_00
    assert agg.zero_rated_igst_paise == 18_000_00

    # 3.1(a) zero contribution
    assert agg.taxable_value_paise == 0
    assert agg.igst_paise == 0
    assert agg.cgst_paise == 0
    assert agg.sgst_paise == 0

    # 3.1(c) zero contribution
    assert agg.nil_exempt_taxable_paise == 0


def test_2_sezwop_classification():
    """TEST 2 — SEZWOP classification.

    Input:
    inv_typ = SEZWOP, taxable = 100000, IGST = 0
    Expected:
    3.1(b): taxable = 100000
    3.1(a): 0
    3.1(c): 0
    """
    rec = {
        "section": "b2b",
        "inv_typ": "SEZWOP",
        "invoice_type": "B2B",
        "doc_type": "INVOICE",
        "taxable_amount_paise": 100_000_00,
        "igst_paise": 0,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
        "rate": 0.0,
    }

    assert map_gstr1_supply_to_gstr3b_bucket(rec) == GSTR3BBucket.TABLE_3_1_B_ZERO_RATED

    agg = aggregate_gstr1([rec])
    # 3.1(b) contribution
    assert agg.zero_rated_taxable_paise == 100_000_00
    assert agg.zero_rated_igst_paise == 0

    # 3.1(a) zero contribution
    assert agg.taxable_value_paise == 0
    assert agg.igst_paise == 0

    # 3.1(c) zero contribution
    assert agg.nil_exempt_taxable_paise == 0


def test_3_export_wpay_classification():
    """TEST 3 — Export WPAY -> 3.1(b)."""
    rec = {
        "section": "exp",
        "export_type": "WPAY",
        "invoice_type": "EXPORT",
        "doc_type": "INVOICE",
        "taxable_amount_paise": 250_000_00,
        "igst_paise": 45_000_00,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
        "rate": 18.0,
    }
    assert map_gstr1_supply_to_gstr3b_bucket(rec) == GSTR3BBucket.TABLE_3_1_B_ZERO_RATED

    agg = aggregate_gstr1([rec])
    assert agg.zero_rated_taxable_paise == 250_000_00
    assert agg.zero_rated_igst_paise == 45_000_00
    assert agg.taxable_value_paise == 0
    assert agg.nil_exempt_taxable_paise == 0


def test_4_export_wopay_classification():
    """TEST 4 — Export WOPAY -> 3.1(b)."""
    rec = {
        "section": "exp",
        "export_type": "WOPAY",
        "invoice_type": "EXPORT",
        "doc_type": "INVOICE",
        "taxable_amount_paise": 300_000_00,
        "igst_paise": 0,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
        "rate": 0.0,
    }
    assert map_gstr1_supply_to_gstr3b_bucket(rec) == GSTR3BBucket.TABLE_3_1_B_ZERO_RATED

    agg = aggregate_gstr1([rec])
    assert agg.zero_rated_taxable_paise == 300_000_00
    assert agg.zero_rated_igst_paise == 0
    assert agg.taxable_value_paise == 0
    assert agg.nil_exempt_taxable_paise == 0


def test_5_zero_percent_ordinary_domestic_supply():
    """TEST 5 — 0% ordinary domestic supply.

    Input: regular domestic supply, rate = 0
    Expected: follows existing nil/exempt domain rule (3.1(c)).
    Ensures SEZ fix does not globally route all 0% supplies to 3.1(b).
    """
    rec = {
        "section": "b2b",
        "inv_typ": "R",
        "invoice_type": "B2B",
        "doc_type": "INVOICE",
        "taxable_amount_paise": 50_000_00,
        "igst_paise": 0,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
        "rate": 0.0,
    }
    assert map_gstr1_supply_to_gstr3b_bucket(rec) == GSTR3BBucket.TABLE_3_1_C_NIL_EXEMPT

    agg = aggregate_gstr1([rec])
    # Must land in 3.1(c), NOT 3.1(b) or 3.1(a)
    assert agg.nil_exempt_taxable_paise == 50_000_00
    assert agg.zero_rated_taxable_paise == 0
    assert agg.taxable_value_paise == 0


def test_6_mixed_bucket_regression():
    """TEST 6 — Mixed bucket regression.

    Create one record each:
    - B2B regular -> 3.1(a)
    - B2CS -> 3.1(a)
    - B2CL -> 3.1(a)
    - Export WPAY -> 3.1(b)
    - Export WOPAY -> 3.1(b)
    - SEZWP -> 3.1(b)
    - SEZWOP -> 3.1(b)
    - nil/exempt domestic -> 3.1(c)

    Verify every record lands in exactly one correct 3B bucket.
    """
    records = [
        {"section": "b2b", "inv_typ": "R", "invoice_type": "B2B", "taxable_amount_paise": 10_000_00, "cgst_paise": 900_00, "sgst_paise": 900_00, "rate": 18.0},
        {"section": "b2cs", "invoice_type": "B2C_SMALL", "taxable_amount_paise": 20_000_00, "cgst_paise": 1800_00, "sgst_paise": 1800_00, "rate": 18.0},
        {"section": "b2cl", "invoice_type": "B2C_LARGE", "taxable_amount_paise": 30_000_00, "igst_paise": 5400_00, "rate": 18.0},
        {"section": "exp", "export_type": "WPAY", "invoice_type": "EXPORT", "taxable_amount_paise": 40_000_00, "igst_paise": 7200_00, "rate": 18.0},
        {"section": "exp", "export_type": "WOPAY", "invoice_type": "EXPORT", "taxable_amount_paise": 50_000_00, "igst_paise": 0, "rate": 0.0},
        {"section": "b2b", "inv_typ": "SEZWP", "invoice_type": "B2B", "taxable_amount_paise": 60_000_00, "igst_paise": 10800_00, "rate": 18.0},
        {"section": "b2b", "inv_typ": "SEZWOP", "invoice_type": "B2B", "taxable_amount_paise": 70_000_00, "igst_paise": 0, "rate": 0.0},
        {"section": "nil", "invoice_type": "NIL_RATED", "taxable_amount_paise": 80_000_00, "rate": 0.0},
    ]

    expected_buckets = [
        GSTR3BBucket.TABLE_3_1_A_TAXABLE,     # B2B regular
        GSTR3BBucket.TABLE_3_1_A_TAXABLE,     # B2CS
        GSTR3BBucket.TABLE_3_1_A_TAXABLE,     # B2CL
        GSTR3BBucket.TABLE_3_1_B_ZERO_RATED,  # Export WPAY
        GSTR3BBucket.TABLE_3_1_B_ZERO_RATED,  # Export WOPAY
        GSTR3BBucket.TABLE_3_1_B_ZERO_RATED,  # SEZWP
        GSTR3BBucket.TABLE_3_1_B_ZERO_RATED,  # SEZWOP
        GSTR3BBucket.TABLE_3_1_C_NIL_EXEMPT,   # Nil/exempt domestic
    ]

    for rec, expected in zip(records, expected_buckets):
        assert map_gstr1_supply_to_gstr3b_bucket(rec) == expected

    agg = aggregate_gstr1(records)
    # 3.1(a) = B2B (10k) + B2CS (20k) + B2CL (30k) = 60,000 paise (₹600)
    assert agg.taxable_value_paise == 60_000_00
    # 3.1(b) = Export WPAY (40k) + Export WOPAY (50k) + SEZWP (60k) + SEZWOP (70k) = 220,000 paise (₹2,200)
    assert agg.zero_rated_taxable_paise == 220_000_00
    # 3.1(c) = Nil (80k) = 80,000 paise (₹800)
    assert agg.nil_exempt_taxable_paise == 80_000_00


def test_7_sezwp_igst_isolation():
    """TEST 7 — SEZWP IGST isolation.

    Verify SEZWP IGST is:
    - included in 3.1(b) zero_rated_igst_paise
    - excluded from 3.1(a) igst_paise
    """
    records = [
        {"section": "b2b", "inv_typ": "R", "taxable_amount_paise": 100_000_00, "igst_paise": 18_000_00, "rate": 18.0},
        {"section": "b2b", "inv_typ": "SEZWP", "taxable_amount_paise": 200_000_00, "igst_paise": 36_000_00, "rate": 18.0},
    ]

    agg = aggregate_gstr1(records)
    # Ordinary taxable IGST must ONLY have the regular B2B invoice (₹18,000)
    assert agg.igst_paise == 18_000_00
    # Zero-rated IGST must ONLY have the SEZWP invoice (₹36,000)
    assert agg.zero_rated_igst_paise == 36_000_00
    # Total tax must sum both
    assert agg.total_tax_paise == 54_000_00


def test_8_sezwop_taxable_preservation():
    """TEST 8 — SEZWOP taxable preservation.

    Verify taxable value is not lost merely because tax = 0.
    """
    rec = {
        "section": "b2b",
        "inv_typ": "SEZWOP",
        "taxable_amount_paise": 500_000_00,  # ₹500,000
        "igst_paise": 0,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
        "rate": 0.0,
    }

    agg = aggregate_gstr1([rec])
    assert agg.zero_rated_taxable_paise == 500_000_00
    assert agg.total_outward_taxable_paise == 500_000_00


# ══════════════════════════════════════════════════════════════════════════════
# Run 4B Benchmark Verification
# ══════════════════════════════════════════════════════════════════════════════

def test_run_4b_benchmark_tieout_exact_two_variances():
    """Verify Run 4B benchmark reproduces ONLY the 2 expected variances.

    Expected GSTR-1 aggregate bases:
    - ordinary taxable base: ₹313,488,352.41
    - zero-rated base:       ₹76,020,664.38

    Expected GSTR-3B values:
    - 3.1(a): ₹313,503,352.41 (variance +₹15,000)
    - 3.1(b): ₹76,012,664.38  (variance -₹8,000)

    Expected tie-out:
    - is_clean = False
    - variance_count = 2 (taxable_value and zero_rated only)
    """
    g1_path = Path("benchmark_data/run4b_adversarial_3000/ReconDesk_GSTR1_3000_Adversarial_Run4B_CORRECTED_Sep2026.json")
    g3b_path = Path("benchmark_data/run4b_adversarial_3000/ReconDesk_GSTR3B_Adversarial_Run4B_CORRECTED_Sep2026.json")

    if not g1_path.exists() or not g3b_path.exists():
        pytest.skip("Benchmark Run 4B files not found")

    with open(g1_path, "rb") as f:
        parsed_g1 = parse_gstr1(f.read())
    with open(g3b_path, "r") as f:
        parsed_g3b = parse_gstr3b(json.load(f))

    records = parsed_g1["records"]

    # Verify SEZ counts parsed from GSTR-1
    sezwp_recs = [r for r in records if r.get("inv_typ") == "SEZWP"]
    sezwop_recs = [r for r in records if r.get("inv_typ") == "SEZWOP"]
    assert len(sezwp_recs) == 100
    assert len(sezwop_recs) == 60

    # Aggregate GSTR-1
    agg = aggregate_gstr1(records)

    # Assert exact GSTR-1 aggregate bases in paise
    assert agg.taxable_value_paise == 31_348_835_241      # ₹313,488,352.41
    assert agg.zero_rated_taxable_paise == 7_602_066_438  # ₹76,020,664.38
    assert agg.nil_exempt_taxable_paise == 0              # No leakage into 3.1(c)
    assert agg.igst_paise == 4_422_719_874                # ₹44,227,198.74 (matches 3.1(a) exactly)
    assert agg.zero_rated_igst_paise == 818_669_461       # ₹8,186,694.61 (matches 3.1(b) exactly)

    # Perform tie-out
    tie_out = reconcile_gstr1_vs_3b(records, parsed_g3b)

    assert tie_out.is_clean is False
    assert len(tie_out.variances) == 2

    # Verify exact variance fields and amounts
    var_map = {v.field: v for v in tie_out.variances}
    assert "taxable_value" in var_map
    assert "zero_rated" in var_map
    assert "igst" not in var_map
    assert "nil_exempt" not in var_map

    # 3.1(a) taxable diff: gstr1 - gstr3b = -15,000 paise * 100 = -1,500,000 paise (-₹15,000.00)
    assert var_map["taxable_value"].diff_paise == -1_500_000
    assert var_map["taxable_value"].gstr1_paise == 31_348_835_241
    assert var_map["taxable_value"].gstr3b_paise == 31_350_335_241

    # 3.1(b) zero-rated diff: gstr1 - gstr3b = +8,000 paise * 100 = +800,000 paise (+₹8,000.00)
    assert var_map["zero_rated"].diff_paise == 800_000
    assert var_map["zero_rated"].gstr1_paise == 7_602_066_438
    assert var_map["zero_rated"].gstr3b_paise == 7_601_266_438
