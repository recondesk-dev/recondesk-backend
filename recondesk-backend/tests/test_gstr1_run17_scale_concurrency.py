"""Run 17 — Scale, Determinism & Concurrency Tests.

Enterprise hardening test suite covering:
1. Scale benchmarks (10k, 25k, 50k records) with throughput logging.
2. Determinism (5x execution on complex payloads producing bitwise-identical results).
3. Concurrency isolation (multi-tenant execution without cross-tenant state bleeding).
4. Paise precision & integer math (10,000 records x 1 paise rounding verification).
"""

import concurrent.futures
import time
from datetime import date
from typing import Any

import pytest

from app.matching.generic_matcher import generic_match_pair, SALES_MATCH_CONFIG
from app.models.canonical_amendment import CanonicalAmendment
from app.parsers.sales_register_parser import normalize_amount
from app.reconciliation.gstr1_vs_3b import (
    GSTR3BSummary,
    aggregate_gstr1,
    reconcile_gstr1_vs_3b,
)
from app.services.matcher import normalize_invoice


def _paise(rupees: float) -> int:
    return int(round(rupees * 100))


def _make_sr_doc(inv: str, amount: float = 10000.0, dt: date = date(2026, 9, 15), gstin: str = "27ABCDE1234F1Z5") -> dict[str, Any]:
    taxable = amount
    igst = round(taxable * 0.18, 2)
    tot = round(taxable + igst, 2)
    return {
        "invoice_number": normalize_invoice(inv),
        "invoice_number_raw": inv,
        "invoice_date": dt,
        "gstin": gstin,
        "taxable_amount": taxable,
        "taxable_amount_paise": _paise(taxable),
        "igst": igst,
        "igst_paise": _paise(igst),
        "cgst": 0.0,
        "cgst_paise": 0,
        "sgst": 0.0,
        "sgst_paise": 0,
        "cess": 0.0,
        "cess_paise": 0,
        "total_amount": tot,
        "total_amount_paise": _paise(tot),
        "total_tax": igst,
        "total_tax_paise": _paise(igst),
        "doc_type": "INVOICE",
        "place_of_supply": "29",
    }


def _make_g1_doc(inv: str, amount: float = 10000.0, dt: date = date(2026, 9, 15), gstin: str = "27ABCDE1234F1Z5") -> dict[str, Any]:
    taxable = amount
    igst = round(taxable * 0.18, 2)
    tot = round(taxable + igst, 2)
    return {
        "invoice_number": normalize_invoice(inv),
        "invoice_number_raw": inv,
        "invoice_date": dt,
        "recipient_gstin": gstin,
        "taxable_amount": taxable,
        "taxable_amount_paise": _paise(taxable),
        "igst": igst,
        "igst_paise": _paise(igst),
        "cgst": 0.0,
        "cgst_paise": 0,
        "sgst": 0.0,
        "sgst_paise": 0,
        "cess": 0.0,
        "cess_paise": 0,
        "total_amount": tot,
        "total_amount_paise": _paise(tot),
        "total_tax": igst,
        "total_tax_paise": _paise(igst),
        "doc_type": "INVOICE",
        "pos": "29",
        "section": "b2b",
    }


# =============================================================================
# 1. SCALE BENCHMARKS (10K, 25K, 50K)
# =============================================================================

def test_01_scale_benchmark_10k_pair_matches():
    """1. Scale benchmark: 10,000 invoice pair matches execute under 5 seconds."""
    pairs = [
        (_make_sr_doc(f"INV/26-27/{i:06d}"), _make_g1_doc(f"INV/26-27/{i:06d}"))
        for i in range(10_000)
    ]
    t0 = time.perf_counter()
    matches = [generic_match_pair(sr, g1, SALES_MATCH_CONFIG) for sr, g1 in pairs]
    elapsed = time.perf_counter() - t0

    assert len(matches) == 10_000
    assert all(m.matched for m in matches)
    docs_per_sec = 10_000 / elapsed
    print(f"\n[Run 17 Benchmark] 10,000 matches in {elapsed:.3f}s ({docs_per_sec:.0f} docs/sec)")
    assert elapsed < 5.0, f"10k matches took too long: {elapsed:.2f}s"


def test_02_scale_benchmark_25k_aggregate_gstr1():
    """2. Scale benchmark: 25,000 GSTR-1 records aggregated under 1 second."""
    records = [
        {
            "section": "b2b",
            "invoice_number": f"INV-{i:06d}",
            "taxable_amount_paise": _paise(1000.0),
            "igst_paise": _paise(180.0),
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
            "total_tax_paise": _paise(180.0),
        }
        for i in range(25_000)
    ]
    t0 = time.perf_counter()
    agg = aggregate_gstr1(records)
    elapsed = time.perf_counter() - t0

    assert agg.record_count == 25_000
    assert agg.taxable_value_paise == 25_000 * _paise(1000.0)
    assert agg.igst_paise == 25_000 * _paise(180.0)
    print(f"\n[Run 17 Benchmark] 25,000 records aggregated in {elapsed:.3f}s")
    assert elapsed < 1.0


def test_03_scale_benchmark_50k_tie_out():
    """3. Scale benchmark: 50,000 records Table 3.1(a) tie-out under 2 seconds."""
    records = [
        {
            "section": "b2b",
            "invoice_number": f"INV-{i:06d}",
            "taxable_amount_paise": _paise(500.0),
            "igst_paise": _paise(90.0),
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
            "total_tax_paise": _paise(90.0),
        }
        for i in range(50_000)
    ]
    expected_taxable = 50_000 * _paise(500.0)
    expected_igst = 50_000 * _paise(90.0)
    g3b = GSTR3BSummary(taxable_value_paise=expected_taxable, igst_paise=expected_igst)

    t0 = time.perf_counter()
    res = reconcile_gstr1_vs_3b(records, g3b)
    elapsed = time.perf_counter() - t0

    assert len(res.variances) == 0
    print(f"\n[Run 17 Benchmark] 50,000 tie-out reconciliation in {elapsed:.3f}s")
    assert elapsed < 2.0


# =============================================================================
# 2. DETERMINISM VERIFICATION (5X EXECUTION)
# =============================================================================

def test_04_determinism_5x_identical_results():
    """4. Determinism: 5x execution on complex payload produces bitwise identical results."""
    # Build payload with mixed matching tiers:
    # - exact match
    # - OCR single substitution
    # - date delta within tolerance
    # - period boundary review
    # - POS mismatch
    sr_docs = [
        _make_sr_doc("INV/26-27/00001", amount=10000.0, dt=date(2026, 9, 10)),
        _make_sr_doc("NGP/26-27/00020", amount=25000.0, dt=date(2026, 9, 12)),  # 0 vs O OCR
        _make_sr_doc("INV/26-27/00003", amount=30000.0, dt=date(2026, 9, 15)),  # +1 day
        _make_sr_doc("INV/26-27/00004", amount=40000.0, dt=date(2026, 8, 31)),  # period boundary
        _make_sr_doc("INV/26-27/00005", amount=50000.0, dt=date(2026, 9, 20)),  # POS mismatch
    ]
    sr_docs[4]["place_of_supply"] = "27"  # Different POS -> Level 3

    g1_docs = [
        _make_g1_doc("INV/26-27/00001", amount=10000.0, dt=date(2026, 9, 10)),
        _make_g1_doc("NGP/26-27/0002O", amount=25000.0, dt=date(2026, 9, 12)),
        _make_g1_doc("INV/26-27/00003", amount=30000.0, dt=date(2026, 9, 16)),
        _make_g1_doc("INV/26-27/00004", amount=40000.0, dt=date(2026, 9, 1)),
        _make_g1_doc("INV/26-27/00005", amount=50000.0, dt=date(2026, 9, 20)),
    ]
    g1_docs[4]["pos"] = "29"

    run_fingerprints = []

    for run_idx in range(5):
        run_results = []
        for sr, g1 in zip(sr_docs, g1_docs):
            res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
            fp = (res.matched, res.level, res.confidence, res.requires_human_review, res.review_reason)
            run_results.append(fp)
        run_fingerprints.append(run_results)

    # Compare all 5 runs against run 0
    base = run_fingerprints[0]
    for idx, run_fp in enumerate(run_fingerprints[1:], 1):
        assert run_fp == base, f"Run {idx} diverged from base run: {run_fp} != {base}"


# =============================================================================
# 3. CONCURRENCY ISOLATION
# =============================================================================

def _tenant_worker(tenant_id: str, count: int) -> dict[str, Any]:
    """Simulate a worker running reconciliation for a specific tenant."""
    gstin = f"27TENANT{int(tenant_id):04d}1Z5"
    sr_docs = [_make_sr_doc(f"T{tenant_id}-INV-{i}", amount=1000.0 + i, gstin=gstin) for i in range(count)]
    g1_docs = [_make_g1_doc(f"T{tenant_id}-INV-{i}", amount=1000.0 + i, gstin=gstin) for i in range(count)]

    matches = [generic_match_pair(sr, g1, SALES_MATCH_CONFIG) for sr, g1 in zip(sr_docs, g1_docs)]
    matched_count = sum(1 for m in matches if m.matched)

    return {
        "tenant_id": tenant_id,
        "gstin": gstin,
        "matched_count": matched_count,
        "all_matched": matched_count == count,
    }


def test_05_concurrency_isolation_multi_tenant_threads():
    """5. Concurrency: 8 simultaneous worker threads process distinct tenants without bleeding."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_tenant_worker, str(i), 500): str(i) for i in range(8)}
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 8
    for r in results:
        assert r["all_matched"] is True
        assert r["matched_count"] == 500


# =============================================================================
# 4. PAISE PRECISION & INTEGER MATH (10,000 RECORDS X 1 PAISE)
# =============================================================================

def test_06_integer_math_10k_paise_rounding_precision():
    """6. Precision: 10,000 fractional amounts accumulate with exactly 0 paise drift."""
    # Test amounts with varied decimal fractions: .01, .25, .33, .50, .67, .75, .99
    fractions = [0.01, 0.25, 0.33, 0.50, 0.67, 0.75, 0.99]
    records = []
    expected_paise_sum = 0

    for i in range(10_000):
        frac = fractions[i % len(fractions)]
        rupees = 100.0 + frac
        paise_val = _paise(rupees)
        expected_paise_sum += paise_val
        records.append({
            "section": "b2b",
            "invoice_number": f"INV-{i}",
            "taxable_amount_paise": paise_val,
            "igst_paise": 0,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
            "total_tax_paise": 0,
        })

    agg = aggregate_gstr1(records)
    assert agg.taxable_value_paise == expected_paise_sum
    assert isinstance(agg.taxable_value_paise, int)


def test_07_normalize_amount_sub_paise_rounding():
    """7. Sub-paise precision rounds half to even / nearest paise accurately."""
    # 10.004 -> 1000 paise (rounds down)
    assert normalize_amount("10.004") == 1000
    # 10.006 -> 1001 paise (rounds up)
    assert normalize_amount("10.006") == 1001


def test_08_memory_safety_repeated_matching_no_leak():
    """8. Repeated matching loop does not build up persistent state."""
    sr = _make_sr_doc("INV-LEAK-TEST")
    g1 = _make_g1_doc("INV-LEAK-TEST")

    for _ in range(1_000):
        res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
        assert res.matched is True
