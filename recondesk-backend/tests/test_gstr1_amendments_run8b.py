"""Tests for GSTR-1 vs GSTR-3B amendment delta aggregation (Run 8B fix).

Acceptance criteria
-------------------
- B2BA/CDNA amendments contribute only their delta (amended − original),
  not the full amended value.
- Zero-economic amendments (number/date only) contribute ₹0.
- Duplicate amendment chains use only the terminal chain delta.
- Run 5 regression: 1 variance, taxable diff = −₹12,500.
- Run 4B regression: SEZ/zero-rated bucket behaviour unchanged.
- Run 8B benchmark:
    3.1(a) GSTR-1 − GSTR-3B = −₹12,500
    3.1(b) GSTR-1 − GSTR-3B = +₹7,500
    IGST = ₹0, CGST = ₹0, SGST = ₹0, Cess = ₹0
    tie_out_variance_count = 2
"""
from __future__ import annotations

import json
import os
import pathlib
from typing import Any

import pytest

# ── helpers ──────────────────────────────────────────────────────────────────

def _paise(rupees: float) -> int:
    return round(rupees * 100)


def _build_record(
    *,
    section: str = "b2b",
    invoice_number: str = "INV-001",
    taxable: float = 100_000.0,
    igst: float = 18_000.0,
    cgst: float = 0.0,
    sgst: float = 0.0,
    cess: float = 0.0,
    supply_type: str | None = None,
    exp_type: str | None = None,
    ntty: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    rec = {
        "section": section,
        "invoice_number": invoice_number,
        "invoice_number_raw": invoice_number,
        "taxable_amount_paise": _paise(taxable),
        "igst_paise": _paise(igst),
        "cgst_paise": _paise(cgst),
        "sgst_paise": _paise(sgst),
        "cess_paise": _paise(cess),
    }
    if supply_type is not None:
        rec["supply_type"] = supply_type
    if exp_type is not None:
        rec["exp_type"] = exp_type
    if ntty is not None:
        rec["ntty"] = ntty
    rec.update(extra)
    return rec


def _build_gstr3b(
    *,
    taxable: float = 0.0,
    igst: float = 0.0,
    cgst: float = 0.0,
    sgst: float = 0.0,
    cess: float = 0.0,
    zero_rated_taxable: float = 0.0,
    zero_rated_igst: float = 0.0,
) -> dict[str, Any]:
    """Minimal parsed GSTR-3B dict matching gstr3b_to_summary expectations."""
    return {
        "ret_period": "092026",
        "sup_details": {
            "osup_det": {
                "txval": taxable,
                "iamt": igst,
                "camt": cgst,
                "samt": sgst,
                "csamt": cess,
            },
            "osup_zero": {
                "txval": zero_rated_taxable,
                "iamt": zero_rated_igst,
                "csamt": 0.0,
            },
            "osup_nil_exmp": {"txval": 0.0},
            "isup_rev": {"txval": 0.0, "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
        },
    }


def _canonical(
    *,
    delta_taxable: float = 0.0,
    delta_igst: float = 0.0,
    delta_cgst: float = 0.0,
    delta_sgst: float = 0.0,
    delta_cess: float = 0.0,
    original_found: bool = True,
    is_latest: bool = True,
    is_zero_rated: bool = False,
) -> "CanonicalAmendment":
    from app.models.canonical_amendment import CanonicalAmendment
    return CanonicalAmendment(
        document_type="INVOICE",
        recipient_gstin=None,
        original_invoice_number="INV-001",
        original_invoice_date=None,
        amended_invoice_number="INV-001A",
        amended_invoice_date=None,
        original_taxable=0.0,
        amended_taxable=round(delta_taxable, 2),
        delta_taxable=round(delta_taxable, 2),
        original_igst=0.0,
        amended_igst=round(delta_igst, 2),
        delta_igst=round(delta_igst, 2),
        original_cgst=0.0,
        amended_cgst=round(delta_cgst, 2),
        delta_cgst=round(delta_cgst, 2),
        original_sgst=0.0,
        amended_sgst=round(delta_sgst, 2),
        delta_sgst=round(delta_sgst, 2),
        original_cess=0.0,
        amended_cess=round(delta_cess, 2),
        delta_cess=round(delta_cess, 2),
        original_taxable_paise=0,
        amended_taxable_paise=_paise(delta_taxable),
        delta_taxable_paise=_paise(delta_taxable),
        original_igst_paise=0,
        amended_igst_paise=_paise(delta_igst),
        delta_igst_paise=_paise(delta_igst),
        original_cgst_paise=0,
        amended_cgst_paise=_paise(delta_cgst),
        delta_cgst_paise=_paise(delta_cgst),
        original_sgst_paise=0,
        amended_sgst_paise=_paise(delta_sgst),
        delta_sgst_paise=_paise(delta_sgst),
        original_cess_paise=0,
        amended_cess_paise=_paise(delta_cess),
        delta_cess_paise=_paise(delta_cess),
        amendment_type="VALUE_AMENDMENT" if (delta_taxable or delta_igst) else "NO_CHANGE",
        source_period="082026",
        filing_period="092026",
        original_found=original_found,
        original_source="SR",
        chain_id="chain-1",
        chain_position=1,
        is_latest_effective_amendment=is_latest,
        source_record=None,
        amendment_record={},
        is_zero_rated=is_zero_rated,
    )


# ── Import the aggregate function ─────────────────────────────────────────────

from app.reconciliation.gstr1_vs_3b import aggregate_gstr1, reconcile_gstr1_vs_3b


# ── Test 1: B2BA value increase ───────────────────────────────────────────────

def test_b2ba_value_increase():
    """Original ₹100k → Amended ₹110k; expected delta +₹10k taxable, +₹1,800 IGST."""
    # One normal B2B invoice
    records = [
        _build_record(section="b2b", invoice_number="INV-001", taxable=500_000.0, igst=90_000.0),
        # b2ba row present but should be skipped when canonical_amendments is provided
        _build_record(section="b2ba", invoice_number="INV-001A", taxable=110_000.0, igst=19_800.0),
    ]
    canons = [
        _canonical(delta_taxable=10_000.0, delta_igst=1_800.0),
    ]
    agg = aggregate_gstr1(records, canonical_amendments=canons)
    # Normal B2B + delta
    assert agg.taxable_value_paise == _paise(500_000 + 10_000)
    assert agg.igst_paise == _paise(90_000 + 1_800)


def test_b2ba_value_decrease():
    """Original ₹100k → Amended ₹90k; expected delta −₹10k."""
    records = [
        _build_record(section="b2b", invoice_number="INV-002", taxable=500_000.0, igst=90_000.0),
        _build_record(section="b2ba", invoice_number="INV-002A", taxable=90_000.0, igst=16_200.0),
    ]
    canons = [
        _canonical(delta_taxable=-10_000.0, delta_igst=-1_800.0),
    ]
    agg = aggregate_gstr1(records, canonical_amendments=canons)
    assert agg.taxable_value_paise == _paise(500_000 - 10_000)
    assert agg.igst_paise == _paise(90_000 - 1_800)


# ── Test 3: B2BA number-only amendment ───────────────────────────────────────

def test_b2ba_number_only_amendment_zero_delta():
    """Amendment changes invoice number only; economic delta must be ₹0."""
    records = [
        _build_record(section="b2b", invoice_number="INV-003", taxable=200_000.0, igst=36_000.0),
        _build_record(section="b2ba", invoice_number="INV-003-REVISED", taxable=200_000.0, igst=36_000.0),
    ]
    # delta = 0 because only invoice number changed
    canons = [_canonical(delta_taxable=0.0, delta_igst=0.0)]
    agg = aggregate_gstr1(records, canonical_amendments=canons)
    assert agg.taxable_value_paise == _paise(200_000)  # only the normal invoice
    assert agg.igst_paise == _paise(36_000)


# ── Test 4: B2BA date-only amendment ─────────────────────────────────────────

def test_b2ba_date_only_amendment_zero_delta():
    """Amendment changes invoice date only; economic delta must be ₹0."""
    records = [
        _build_record(section="b2b", invoice_number="INV-004-NORMAL", taxable=150_000.0, igst=27_000.0),
        _build_record(section="b2ba", invoice_number="INV-004-AMENDED", taxable=150_000.0, igst=27_000.0),
    ]
    canons = [_canonical(delta_taxable=0.0, delta_igst=0.0)]
    agg = aggregate_gstr1(records, canonical_amendments=canons)
    assert agg.taxable_value_paise == _paise(150_000)
    assert agg.igst_paise == _paise(27_000)


# ── Test 5: CDNA Credit Note increase ─────────────────────────────────────────

def test_cdna_credit_note_increase():
    """CN original −₹10k, amended −₹12k; delta = −₹2k."""
    records = [
        _build_record(section="b2b", invoice_number="INV-005", taxable=300_000.0, igst=54_000.0),
        _build_record(section="cdna", invoice_number="CN-005A", taxable=12_000.0, igst=2_160.0, ntty="C"),
    ]
    # delta = -2000 because credit note grew from 10k to 12k (more credit = more negative)
    canons = [_canonical(delta_taxable=-2_000.0, delta_igst=-360.0)]
    agg = aggregate_gstr1(records, canonical_amendments=canons)
    assert agg.taxable_value_paise == _paise(300_000 - 2_000)
    assert agg.igst_paise == _paise(54_000 - 360)


def test_cdna_credit_note_decrease():
    """CN original −₹12k, amended −₹10k; delta = +₹2k."""
    records = [
        _build_record(section="b2b", invoice_number="INV-006", taxable=300_000.0, igst=54_000.0),
        _build_record(section="cdna", invoice_number="CN-006A", taxable=10_000.0, igst=1_800.0, ntty="C"),
    ]
    canons = [_canonical(delta_taxable=2_000.0, delta_igst=360.0)]
    agg = aggregate_gstr1(records, canonical_amendments=canons)
    assert agg.taxable_value_paise == _paise(300_000 + 2_000)
    assert agg.igst_paise == _paise(54_000 + 360)


# ── Test 7: CDNA Debit Note increase ─────────────────────────────────────────

def test_cdna_debit_note_increase():
    """DN original ₹10k, amended ₹12k; delta = +₹2k."""
    records = [
        _build_record(section="b2b", invoice_number="INV-007", taxable=100_000.0, igst=18_000.0),
        _build_record(section="cdna", invoice_number="DN-007A", taxable=12_000.0, igst=2_160.0, ntty="D"),
    ]
    canons = [_canonical(delta_taxable=2_000.0, delta_igst=360.0)]
    agg = aggregate_gstr1(records, canonical_amendments=canons)
    assert agg.taxable_value_paise == _paise(100_000 + 2_000)


def test_cdna_debit_note_decrease():
    """DN original ₹12k, amended ₹10k; delta = −₹2k."""
    records = [
        _build_record(section="b2b", invoice_number="INV-008", taxable=100_000.0, igst=18_000.0),
        _build_record(section="cdna", invoice_number="DN-008A", taxable=10_000.0, igst=1_800.0, ntty="D"),
    ]
    canons = [_canonical(delta_taxable=-2_000.0, delta_igst=-360.0)]
    agg = aggregate_gstr1(records, canonical_amendments=canons)
    assert agg.taxable_value_paise == _paise(100_000 - 2_000)


# ── Test 9: Tax-head delta ────────────────────────────────────────────────────

def test_tax_head_delta_only_difference_contributes():
    """Only the tax-head difference should contribute, not the full amended value."""
    records = [
        _build_record(section="b2b", invoice_number="INV-009", taxable=200_000.0,
                      igst=0.0, cgst=9_000.0, sgst=9_000.0),
        _build_record(section="b2ba", invoice_number="INV-009A", taxable=200_000.0,
                      igst=0.0, cgst=10_000.0, sgst=10_000.0),
    ]
    canons = [_canonical(delta_taxable=0.0, delta_igst=0.0, delta_cgst=1_000.0, delta_sgst=1_000.0)]
    agg = aggregate_gstr1(records, canonical_amendments=canons)
    assert agg.taxable_value_paise == _paise(200_000)
    assert agg.cgst_paise == _paise(9_000 + 1_000)
    assert agg.sgst_paise == _paise(9_000 + 1_000)


# ── Test 10: Cess amendment delta ────────────────────────────────────────────

def test_cess_amendment_delta():
    """Only the cess delta should contribute."""
    records = [
        _build_record(section="b2b", invoice_number="INV-010", taxable=50_000.0,
                      igst=5_000.0, cess=500.0),
        _build_record(section="b2ba", invoice_number="INV-010A", taxable=50_000.0,
                      igst=5_000.0, cess=600.0),
    ]
    canons = [_canonical(delta_taxable=0.0, delta_igst=0.0, delta_cess=100.0)]
    agg = aggregate_gstr1(records, canonical_amendments=canons)
    assert agg.cess_paise == _paise(500 + 100)


# ── Test 11: Duplicate amendment chain ───────────────────────────────────────

def test_duplicate_amendment_chain():
    """Chain: 100k → 110k → 115k; total delta must be +₹15k, not +₹25k or ₹225k."""
    records = [
        _build_record(section="b2b", invoice_number="INV-011", taxable=300_000.0, igst=54_000.0),
        # Intermediate amendment (not latest)
        _build_record(section="b2ba", invoice_number="INV-011A", taxable=110_000.0, igst=19_800.0),
        # Final amendment
        _build_record(section="b2ba", invoice_number="INV-011B", taxable=115_000.0, igst=20_700.0),
    ]
    canons = [
        # Intermediate: is_latest=False → excluded
        _canonical(delta_taxable=10_000.0, delta_igst=1_800.0, is_latest=False),
        # Final: is_latest=True, delta = 115k - 100k = 15k
        _canonical(delta_taxable=15_000.0, delta_igst=2_700.0, is_latest=True),
    ]
    agg = aggregate_gstr1(records, canonical_amendments=canons)
    assert agg.taxable_value_paise == _paise(300_000 + 15_000)
    assert agg.igst_paise == _paise(54_000 + 2_700)


# ── Test 12: Zero-economic number/date amendment ──────────────────────────────

def test_zero_economic_amendment_no_liability():
    """Number-only and date-only amendments must produce zero liability effect."""
    records = [
        _build_record(section="b2b", invoice_number="INV-012", taxable=75_000.0, igst=13_500.0),
        _build_record(section="b2ba", invoice_number="INV-012-REVISED", taxable=75_000.0, igst=13_500.0),
    ]
    canons = [_canonical(delta_taxable=0.0, delta_igst=0.0)]
    agg = aggregate_gstr1(records, canonical_amendments=canons)
    assert agg.taxable_value_paise == _paise(75_000)
    assert agg.igst_paise == _paise(13_500)


# ── Test 13: Unresolved amendment excluded ────────────────────────────────────

def test_unresolved_amendment_excluded():
    """If original_found=False, the amendment must NOT affect liability."""
    records = [
        _build_record(section="b2b", invoice_number="INV-013", taxable=100_000.0, igst=18_000.0),
        _build_record(section="b2ba", invoice_number="INV-013A", taxable=115_000.0, igst=20_700.0),
    ]
    canons = [
        # Unresolved: original not in SR → deltas are 0, original_found=False
        _canonical(delta_taxable=0.0, delta_igst=0.0, original_found=False),
    ]
    agg = aggregate_gstr1(records, canonical_amendments=canons)
    # Only the normal B2B invoice should contribute
    assert agg.taxable_value_paise == _paise(100_000)
    assert agg.igst_paise == _paise(18_000)


# ── Test: Zero-rated amendment goes to 3.1(b) bucket ─────────────────────────

def test_zero_rated_amendment_delta_goes_to_zero_rated_bucket():
    """Zero-rated amendment delta must go to zero_rated_*_paise, not taxable_value_paise."""
    records = [
        # EXP WPAY in b2b-like record; normal path
        _build_record(section="b2b", invoice_number="INV-014", taxable=200_000.0, igst=36_000.0),
        # Amendment to an export invoice
        _build_record(section="expa", invoice_number="EXP-014A",
                      taxable=110_000.0, igst=19_800.0, supply_type="EXPWP"),
    ]
    canons = [
        _canonical(delta_taxable=10_000.0, delta_igst=1_800.0, is_zero_rated=True),
    ]
    agg = aggregate_gstr1(records, canonical_amendments=canons)
    # The delta should go to zero_rated, not to taxable
    assert agg.zero_rated_taxable_paise == _paise(10_000)
    assert agg.zero_rated_igst_paise == _paise(1_800)
    # Without include_zero_rated=True, it should NOT appear in taxable_value_paise
    assert agg.taxable_value_paise == _paise(200_000)


# ── Test: Backward compatibility — no canonical_amendments uses legacy path ───

def test_no_canonical_amendments_legacy_path_unchanged():
    """When canonical_amendments=None, the original behaviour is preserved."""
    records = [
        _build_record(section="b2b", invoice_number="INV-100", taxable=500_000.0, igst=90_000.0),
    ]
    agg = aggregate_gstr1(records, canonical_amendments=None)
    assert agg.taxable_value_paise == _paise(500_000)
    assert agg.igst_paise == _paise(90_000)


# ── Test: No double-counting with canonical_amendments ───────────────────────

def test_no_double_counting_canonical_skips_amendment_rows():
    """Amendment rows must be SKIPPED when canonical_amendments is provided."""
    # Without canonical_amendments, b2ba would add full ₹110k
    records = [
        _build_record(section="b2b", invoice_number="INV-200", taxable=100_000.0, igst=18_000.0),
        _build_record(section="b2ba", invoice_number="INV-200A", taxable=110_000.0, igst=19_800.0),
    ]
    # Provide delta = +10k; b2ba row must be skipped entirely
    canons = [_canonical(delta_taxable=10_000.0, delta_igst=1_800.0)]
    agg = aggregate_gstr1(records, canonical_amendments=canons)
    # Result = 100k (normal) + 10k (delta) = 110k, NOT 100k + 110k = 210k
    assert agg.taxable_value_paise == _paise(110_000)
    assert agg.igst_paise == _paise(19_800)


# ── Test 15 (Run 8B Benchmark) — Integration test ────────────────────────────

BENCHMARK_DIR = pathlib.Path(__file__).parent.parent.parent / "benchmark_data" / "run8b_combined_3000"
_SR_FILE = BENCHMARK_DIR / "ReconDesk_Sales_Register_3000_Combined_Run8B_FIXED_SINGLE_SHEET_Sep2026.xlsx"
_G1_FILE = BENCHMARK_DIR / "ReconDesk_GSTR1_3000_Combined_Run8B_CORRECTED_Sep2026.json"
_G3B_FILE = BENCHMARK_DIR / "ReconDesk_GSTR3B_Combined_Run8B_CORRECTED_Sep2026.json"


@pytest.mark.skipif(
    not (_SR_FILE.exists() and _G1_FILE.exists() and _G3B_FILE.exists()),
    reason="Run 8B benchmark files not available",
)
@pytest.mark.asyncio
async def test_run8b_benchmark_exact_numbers():
    """Run 8B full pipeline must produce exact expected tie-out numbers."""
    from app.routers.gstr1_reconcile import _run_pipeline

    result = await _run_pipeline(
        sr_file_content=_SR_FILE.read_bytes(),
        sr_filename=_SR_FILE.name,
        gstr1_file_content=_G1_FILE.read_bytes(),
        gstr3b_file_content=_G3B_FILE.read_bytes(),
        gstr1_filing_period="2026-09",
        prior_gstr1_file_content=None,
        client_gstin_id=None,
    )

    tie_out = result.get("tie_out") or {}
    variances = tie_out.get("variances", [])
    variance_count = tie_out.get("variance_count", len(variances))

    # Expected: exactly 2 variances (3.1(a) and 3.1(b))
    assert variance_count == 2, f"Expected 2 variances, got {variance_count}: {variances}"

    stat_rec = tie_out.get("statutory_reconciliation", {})

    # 3.1(a) GSTR-1 − GSTR-3B = −₹12,500
    taxable_diff = stat_rec.get("taxable_outward", {}).get("difference", 0.0)
    assert abs(taxable_diff - (-12_500.0)) < 0.01, f"3.1(a) taxable diff expected −₹12,500, got {taxable_diff}"

    # 3.1(b) GSTR-1 − GSTR-3B = +₹7,500
    zero_rated_diff = stat_rec.get("zero_rated", {}).get("difference", 0.0)
    assert abs(zero_rated_diff - 7_500.0) < 0.01, f"3.1(b) zero-rated diff expected +₹7,500, got {zero_rated_diff}"

    # Tax heads: IGST = 0, CGST = 0, SGST = 0, Cess = 0
    tax = stat_rec.get("tax", {})
    for field in ("igst", "cgst", "sgst", "cess"):
        diff = tax.get(field, {}).get("difference", 0.0)
        assert abs(diff) < 0.01, f"{field} difference expected ₹0, got {diff}"

    # Matching metrics must remain unchanged
    summary = result.get("summary", {})
    assert summary.get("sr_total_records") == 3000, f"SR records: {summary.get('sr_total_records')}"
    assert summary.get("missing_in_gstr1_count") == 80, f"Missing: {summary.get('missing_in_gstr1_count')}"
    assert summary.get("unmatched_gstr1_count") == 50, f"Extra: {summary.get('unmatched_gstr1_count')}"
    assert summary.get("aggregate_source_invoice_count") == 200, f"B2CS: {summary.get('aggregate_source_invoice_count')}"
    assert summary.get("b2cs_reconciliation_status") == "MATCHED", f"B2CS status: {summary.get('b2cs_reconciliation_status')}"
    assert summary.get("accounted_source_invoice_count") == 2920, f"Accounted: {summary.get('accounted_source_invoice_count')}"
    assert summary.get("coverage_percentage") == 97.33, f"Coverage: {summary.get('coverage_percentage')}"
    assert summary.get("amendment_accounted_source_count") == 280, f"Amended SR: {summary.get('amendment_accounted_source_count')}"
    assert summary.get("tie_out_variance_count") == 2, f"Tie out variances: {summary.get('tie_out_variance_count')}"

    _log_variances(variances)


def _log_variances(variances: list) -> None:
    import sys
    print("\n=== Run 8B Tie-Out Variances ===", file=sys.stderr)
    for v in variances:
        print(f"  {v['field']}: GSTR-1={v['gstr1']} GSTR-3B={v['gstr3b']} diff={v['diff']}", file=sys.stderr)


# ── Test: reconcile_gstr1_vs_3b passes canonical_amendments through ──────────

def test_reconcile_gstr1_vs_3b_accepts_canonical_amendments():
    """reconcile_gstr1_vs_3b must accept and use canonical_amendments."""
    records = [
        _build_record(section="b2b", invoice_number="INV-300", taxable=500_000.0, igst=90_000.0),
        # Amendment row that should be skipped
        _build_record(section="b2ba", invoice_number="INV-300A", taxable=550_000.0, igst=99_000.0),
    ]
    canons = [_canonical(delta_taxable=50_000.0, delta_igst=9_000.0)]

    # GSTR-3B says 550k taxable (matches 500k + 50k delta, not 500k + 550k)
    gstr3b = _build_gstr3b(taxable=550_000.0, igst=99_000.0)

    result = reconcile_gstr1_vs_3b(records, gstr3b, canonical_amendments=canons)
    # Should be clean — no variance
    assert result.is_clean, (
        f"Expected clean result. Variances: {[(v.field, v.diff_paise) for v in result.variances]}"
    )
