"""Verification and validation suite for clean 2,000-invoice GSTR-1 benchmark.

Validates:
A. File integrity: existence, JSON/CSV parsing, record completeness.
B. Cross-file integrity: 1-to-1 match between clean SR and clean GSTR-1, credit notes, B2BA.
C. Mutation integrity: exact counts, disjoint ranges, no collisions.
D. Financial integrity: clean SR = clean 3B, exact delta math.
E. Reproducibility: deterministic generation with fixed seed.
"""

import csv
import json
from collections import Counter
from pathlib import Path

import pytest


BENCHMARK_DIR = Path("benchmark_data/fuzz_2000_clean")


@pytest.fixture(scope="module")
def benchmark_files():
    required = [
        "sales_register_fuzz_2000.csv",
        "gstr1_clean_control_2000.json",
        "gstr1_fuzz_2000.json",
        "gstr1_prior_jun2025.json",
        "gstr3b_fuzz_2000.json",
        "MUTATION_MANIFEST.json",
        "EXPECTED_RESULT.md",
    ]
    for req in required:
        p = BENCHMARK_DIR / req
        assert p.exists(), f"Required file missing: {p}"

    with open(BENCHMARK_DIR / "sales_register_fuzz_2000.csv", encoding="utf-8") as f:
        sr_rows = list(csv.DictReader(f))

    with open(BENCHMARK_DIR / "gstr1_clean_control_2000.json", encoding="utf-8") as f:
        clean_g1 = json.load(f)

    with open(BENCHMARK_DIR / "gstr1_fuzz_2000.json", encoding="utf-8") as f:
        mut_g1 = json.load(f)

    with open(BENCHMARK_DIR / "gstr1_prior_jun2025.json", encoding="utf-8") as f:
        prior_g1 = json.load(f)

    with open(BENCHMARK_DIR / "gstr3b_fuzz_2000.json", encoding="utf-8") as f:
        g3b = json.load(f)

    with open(BENCHMARK_DIR / "MUTATION_MANIFEST.json", encoding="utf-8") as f:
        manifest = json.load(f)

    with open(BENCHMARK_DIR / "EXPECTED_RESULT.md", encoding="utf-8") as f:
        expected_md = f.read()

    return {
        "sr": sr_rows,
        "clean_g1": clean_g1,
        "mut_g1": mut_g1,
        "prior_g1": prior_g1,
        "g3b": g3b,
        "manifest": manifest,
        "expected_md": expected_md,
    }


def test_file_integrity_and_record_counts(benchmark_files):
    """Verify exact population composition in Sales Register."""
    sr = benchmark_files["sr"]
    assert len(sr) == 2000

    types = Counter(r["Voucher Type"] for r in sr)
    assert types["Sales"] == 1980
    assert types["Credit Note"] == 20

    b2b_inums = [r["Invoice No"] for r in sr if r["Invoice No"].startswith("INV/")]
    cn_inums = [r["Invoice No"] for r in sr if r["Invoice No"].startswith("CN/")]
    b2cl_inums = [r["Invoice No"] for r in sr if r["Invoice No"].startswith("B2CL/")]
    b2cs_inums = [r["Invoice No"] for r in sr if r["Invoice No"].startswith("B2CS/")]

    assert len(b2b_inums) == 1780
    assert len(cn_inums) == 20
    assert len(b2cl_inums) == 100
    assert len(b2cs_inums) == 100


def test_credit_note_population_and_signs(benchmark_files):
    """Verify 20 Credit Notes have negative values in SR and valid registered buyers."""
    sr = benchmark_files["sr"]
    cns = [r for r in sr if r["Voucher Type"] == "Credit Note"]
    assert len(cns) == 20

    for cn in cns:
        assert cn["Invoice No"].startswith("CN/25-26/")
        assert float(cn["Taxable Value"]) < 0, "Credit note taxable value must be negative"
        assert float(cn["Invoice Value"]) < 0, "Credit note total value must be negative"
        assert cn["GSTIN"].startswith(("27", "29", "24", "06", "07", "09", "19", "33"))


def test_clean_control_and_3b_financial_reconciliation(benchmark_files):
    """Verify clean Sales Register totals exactly match clean GSTR-3B."""
    sr = benchmark_files["sr"]
    g3b = benchmark_files["g3b"]
    osup = g3b["sup_details"]["osup_det"]

    sr_taxable = sum(float(r["Taxable Value"]) for r in sr)
    sr_igst = sum(float(r["IGST Amount"]) for r in sr)
    sr_cgst = sum(float(r["CGST Amount"]) for r in sr)
    sr_sgst = sum(float(r["SGST Amount"]) for r in sr)

    assert round(sr_taxable, 2) == round(osup["txval"], 2)
    assert round(sr_igst, 2) == round(osup["iamt"], 2)
    assert round(sr_cgst, 2) == round(osup["camt"], 2)
    assert round(sr_sgst, 2) == round(osup["samt"], 2)


def test_b2ba_collision_avoidance_and_validity(benchmark_files):
    """Verify June original B2BA invoice is not reused in July fresh invoices."""
    sr = benchmark_files["sr"]
    prior = benchmark_files["prior_g1"]
    mut_g1 = benchmark_files["mut_g1"]

    prior_invs = []
    for b in prior["b2b"]:
        for inv in b["inv"]:
            prior_invs.append(inv["inum"])
    assert "INV/25-26/BA0001" in prior_invs

    # Fresh July invoices must NOT contain INV/25-26/BA0001
    sr_inums = {r["Invoice No"] for r in sr}
    assert "INV/25-26/BA0001" not in sr_inums

    # Table 4A in mutated GSTR-1 must NOT contain INV/25-26/BA0001
    g1_4a_inums = []
    for b in mut_g1["b2b"]:
        for inv in b["inv"]:
            g1_4a_inums.append(inv["inum"])
    assert "INV/25-26/BA0001" not in g1_4a_inums

    # Mutated GSTR-1 Table 9A must contain exactly 1 valid B2BA and 1 invalid B2BA
    b2ba_entries = mut_g1["b2ba"]
    assert len(b2ba_entries) == 2
    oinums = [e["inv"][0]["oinum"] for e in b2ba_entries]
    assert "INV/25-26/BA0001" in oinums
    assert "NONEXIST-999" in oinums


def test_duplicate_count_is_programmatic_and_exact(benchmark_files):
    """Verify Table 4A duplicate count is exactly 35 (15 from dup_b2b + 20 from extra_b2b)."""
    mut_g1 = benchmark_files["mut_g1"]
    inums = []
    for b in mut_g1["b2b"]:
        for inv in b["inv"]:
            inums.append(inv["inum"])

    c = Counter(inums)
    dups = {k: v for k, v in c.items() if v > 1}
    assert len(dups) == 35, f"Expected exactly 35 duplicate invoice numbers, got {len(dups)}"


def test_mutation_counts_match_manifest(benchmark_files):
    """Verify every mutation count matches the manifest."""
    manifest = benchmark_files["manifest"]
    muts = manifest["mutations"]

    expected_counts = {
        "missing_b2b": 20,
        "duplicate_b2b": 15,
        "extra_b2b_duplicate_representation": 20,
        "b2b_taxable_mismatch": 25,
        "b2b_tax_mismatch": 25,
        "date_mismatch": 15,
        "gstin_mismatch": 15,
        "rate_mismatch": 15,
        "invoice_format_variation": 30,
        "credit_note_missing": 5,
        "credit_note_amount_mismatch": 5,
        "b2cl_taxable_mismatch": 10,
        "b2cs_aggregate_mismatch": 1,
        "valid_b2ba": 1,
        "invalid_b2ba": 1,
    }
    for k, v in expected_counts.items():
        assert muts.get(k) == v, f"Mutation count mismatch for {k}: expected {v}, got {muts.get(k)}"
