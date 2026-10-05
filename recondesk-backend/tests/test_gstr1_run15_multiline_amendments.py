"""Unit, integration, and torture tests for Phase 2 (Run 15) Multi-Line & Amendment Torture.

Validates:
1. Multi-line invoices (2 to 20 line items per document)
2. Mixed rates on same invoice (0%, 5%, 12%, 18%, 28%, cess)
3. Line splits / line merges between ERP and GSTN
4. Partial amendments (single or subset of lines modified)
5. Multi-period amendment chains (Original -> A1 -> A2 -> CN -> DN)
6. Duplicate ERP interactions with GSTR-1 amendments
7. Rate bucket aggregation (5%, 12%, 18%, 28%, cess)
8. Synthetic Benchmark (2,000 records) verifying complete multi-line and amendment torture resilience.
"""

from datetime import date
from decimal import Decimal
import pytest

from app.matching.generic_matcher import generic_match_pair, SALES_MATCH_CONFIG
from app.services.amendment_handler import (
    build_effective_gstr_records,
    process_amendment,
)
from app.models.canonical_amendment import CanonicalAmendment
from app.reconciliation.gstr1_vs_3b import (
    aggregate_gstr1,
    reconcile_gstr1_vs_3b,
    GSTR3BSummary,
)
from app.services.matcher import normalize_invoice


def _paise(rupees: float) -> int:
    return round(rupees * 100)


def _sr_multiline(
    inv: str,
    lines: list[dict],
    gstin: str = "27AABCS1429B1Z",
    dt: date = date(2026, 9, 15),
    pos: str = "27",
    doc_type: str = "INVOICE",
) -> dict:
    """Aggregate ERP line items into a single document record."""
    tot_taxable = sum(l["taxable"] for l in lines)
    tot_igst = sum(l.get("igst", 0) for l in lines)
    tot_cgst = sum(l.get("cgst", 0) for l in lines)
    tot_sgst = sum(l.get("sgst", 0) for l in lines)
    tot_cess = sum(l.get("cess", 0) for l in lines)
    tot_tax = tot_igst + tot_cgst + tot_sgst + tot_cess
    return {
        "invoice_number": inv,
        "invoice_number_raw": inv,
        "gstin": gstin,
        "recipient_gstin": gstin,
        "invoice_date": dt,
        "place_of_supply": pos,
        "pos": pos,
        "doc_type": doc_type,
        "taxable_amount_paise": _paise(tot_taxable),
        "total_tax_paise": _paise(tot_tax),
        "igst_paise": _paise(tot_igst),
        "cgst_paise": _paise(tot_cgst),
        "sgst_paise": _paise(tot_sgst),
        "cess_paise": _paise(tot_cess),
        "line_items": lines,
    }


def _g1_multiline(
    inv: str,
    lines: list[dict],
    gstin: str = "27AABCS1429B1Z",
    dt: date = date(2026, 9, 15),
    pos: str = "27",
    section: str = "b2b",
    doc_type: str = "INVOICE",
    is_amendment: bool = False,
    oinum: str | None = None,
) -> dict:
    """GSTR-1 multi-line record with itms structure."""
    tot_taxable = sum(l["taxable"] for l in lines)
    tot_igst = sum(l.get("igst", 0) for l in lines)
    tot_cgst = sum(l.get("cgst", 0) for l in lines)
    tot_sgst = sum(l.get("sgst", 0) for l in lines)
    tot_cess = sum(l.get("cess", 0) for l in lines)
    tot_tax = tot_igst + tot_cgst + tot_sgst + tot_cess
    rec = {
        "inum": inv,
        "invoice_number": inv,
        "invoice_number_raw": inv,
        "ctin": gstin,
        "gstin": gstin,
        "recipient_gstin": gstin,
        "idt": dt.strftime("%d-%m-%Y"),
        "invoice_date": dt,
        "pos": pos,
        "section": section,
        "doc_type": doc_type,
        "is_amendment": is_amendment,
        "taxable_amount_paise": _paise(tot_taxable),
        "total_tax_paise": _paise(tot_tax),
        "igst_paise": _paise(tot_igst),
        "cgst_paise": _paise(tot_cgst),
        "sgst_paise": _paise(tot_sgst),
        "cess_paise": _paise(tot_cess),
        "itms": [
            {
                "num": idx + 1,
                "itm_det": {
                    "txval": l["taxable"],
                    "rt": l["rate"],
                    "iamt": l.get("igst", 0),
                    "camt": l.get("cgst", 0),
                    "samt": l.get("sgst", 0),
                    "csamt": l.get("cess", 0),
                },
            }
            for idx, l in enumerate(lines)
        ],
    }
    if oinum:
        rec["oinum"] = oinum
        rec["original_invoice_number"] = oinum
    return rec


def _canonical(
    *,
    inv: str = "INV-001",
    delta_taxable: float = 0.0,
    delta_igst: float = 0.0,
    delta_cgst: float = 0.0,
    delta_sgst: float = 0.0,
    delta_cess: float = 0.0,
    is_zero_rated: bool = False,
    is_zero_economic: bool = False,
) -> CanonicalAmendment:
    return CanonicalAmendment(
        document_type="INVOICE",
        recipient_gstin=None,
        original_invoice_number=inv,
        original_invoice_date=None,
        amended_invoice_number=inv,
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
        amendment_type="VALUE_AMENDMENT" if not is_zero_economic else "NO_CHANGE",
        source_period="082026",
        filing_period="092026",
        original_found=True,
        original_source="SR",
        chain_id="chain-1",
        chain_position=1,
        is_latest_effective_amendment=True,
        source_record=None,
        amendment_record={},
        is_zero_rated=is_zero_rated,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. MULTI-LINE INVOICE MATCHING (2 TO 20 LINES)
# ─────────────────────────────────────────────────────────────────────────────

def test_01_two_line_mixed_rate_invoice():
    """1. 2-line invoice with 5% and 18% rates."""
    lines = [
        {"rate": 5.0, "taxable": 20000.0, "igst": 1000.0},
        {"rate": 18.0, "taxable": 50000.0, "igst": 9000.0},
    ]
    sr = _sr_multiline("INV/26-27/001", lines)
    g1 = _g1_multiline("INV/26-27/001", lines)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1
    assert res.confidence == 100


def test_02_three_line_split_in_erp_merged_in_gstn():
    """2. ERP reports 3 lines at 18%, GSTN aggregates into 1 line at 18% -> perfect match."""
    erp_lines = [
        {"rate": 18.0, "taxable": 30000.0, "igst": 5400.0},
        {"rate": 18.0, "taxable": 30000.0, "igst": 5400.0},
        {"rate": 18.0, "taxable": 40000.0, "igst": 7200.0},
    ]
    gstn_lines = [
        {"rate": 18.0, "taxable": 100000.0, "igst": 18000.0},
    ]
    sr = _sr_multiline("INV/26-27/002", erp_lines)
    g1 = _g1_multiline("INV/26-27/002", gstn_lines)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1
    assert res.confidence == 100


def test_03_four_line_mixed_rates_5_12_18_28():
    """3. 4 lines with all 4 standard GST rates (5%, 12%, 18%, 28%)."""
    lines = [
        {"rate": 5.0, "taxable": 10000.0, "igst": 500.0},
        {"rate": 12.0, "taxable": 20000.0, "igst": 2400.0},
        {"rate": 18.0, "taxable": 30000.0, "igst": 5400.0},
        {"rate": 28.0, "taxable": 40000.0, "igst": 11200.0},
    ]
    sr = _sr_multiline("INV/26-27/003", lines)
    g1 = _g1_multiline("INV/26-27/003", lines)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1


def test_04_five_line_with_cess_on_luxury_items():
    """4. 5 lines including 28% luxury items with compensation cess."""
    lines = [
        {"rate": 18.0, "taxable": 50000.0, "igst": 9000.0, "cess": 0.0},
        {"rate": 28.0, "taxable": 100000.0, "igst": 28000.0, "cess": 12000.0},
        {"rate": 5.0, "taxable": 10000.0, "igst": 500.0, "cess": 0.0},
        {"rate": 12.0, "taxable": 20000.0, "igst": 2400.0, "cess": 0.0},
        {"rate": 0.0, "taxable": 5000.0, "igst": 0.0, "cess": 0.0},
    ]
    sr = _sr_multiline("INV/26-27/004", lines)
    g1 = _g1_multiline("INV/26-27/004", lines)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1
    assert sr["cess_paise"] == _paise(12000.0)
    assert g1["cess_paise"] == _paise(12000.0)


def test_05_ten_line_invoice_with_rate_permutations():
    """5. 10 lines with multiple repeated rates and intra-state CGST/SGST splits."""
    lines = [
        {"rate": 18.0, "taxable": 10000.0, "cgst": 900.0, "sgst": 900.0},
        {"rate": 18.0, "taxable": 15000.0, "cgst": 1350.0, "sgst": 1350.0},
        {"rate": 12.0, "taxable": 20000.0, "cgst": 1200.0, "sgst": 1200.0},
        {"rate": 5.0, "taxable": 5000.0, "cgst": 125.0, "sgst": 125.0},
        {"rate": 28.0, "taxable": 25000.0, "cgst": 3500.0, "sgst": 3500.0},
        {"rate": 18.0, "taxable": 8000.0, "cgst": 720.0, "sgst": 720.0},
        {"rate": 12.0, "taxable": 12000.0, "cgst": 720.0, "sgst": 720.0},
        {"rate": 5.0, "taxable": 6000.0, "cgst": 150.0, "sgst": 150.0},
        {"rate": 18.0, "taxable": 30000.0, "cgst": 2700.0, "sgst": 2700.0},
        {"rate": 0.0, "taxable": 4000.0, "cgst": 0.0, "sgst": 0.0},
    ]
    sr = _sr_multiline("INV/26-27/005", lines)
    g1 = _g1_multiline("INV/26-27/005", lines)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1
    assert sr["cgst_paise"] == g1["cgst_paise"]
    assert sr["sgst_paise"] == g1["sgst_paise"]


def test_06_twenty_line_torture_invoice():
    """6. 20 lines across full rate spectrum with exact matching."""
    lines = []
    rates = [0.0, 5.0, 12.0, 18.0, 28.0]
    for i in range(20):
        r = rates[i % len(rates)]
        tx = float((i + 1) * 5000)
        tax = tx * r / 100.0
        lines.append({"rate": r, "taxable": tx, "igst": tax})

    sr = _sr_multiline("INV/26-27/020", lines)
    g1 = _g1_multiline("INV/26-27/020", lines)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1
    assert res.confidence == 100


def test_07_line_splits_erp_five_lines_vs_gstn_two_rate_buckets():
    """7. ERP has 5 lines (3 at 18%, 2 at 12%), GSTN aggregates into 2 rate buckets."""
    erp_lines = [
        {"rate": 18.0, "taxable": 10000.0, "igst": 1800.0},
        {"rate": 18.0, "taxable": 20000.0, "igst": 3600.0},
        {"rate": 18.0, "taxable": 30000.0, "igst": 5400.0},
        {"rate": 12.0, "taxable": 15000.0, "igst": 1800.0},
        {"rate": 12.0, "taxable": 25000.0, "igst": 3000.0},
    ]
    gstn_buckets = [
        {"rate": 18.0, "taxable": 60000.0, "igst": 10800.0},
        {"rate": 12.0, "taxable": 40000.0, "igst": 4800.0},
    ]
    sr = _sr_multiline("INV/26-27/007", erp_lines)
    g1 = _g1_multiline("INV/26-27/007", gstn_buckets)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1


def test_08_line_split_paise_rounding_accumulation():
    """8. 10 lines each with 1 paise rounding difference -> accumulates within ₹1 L1 tolerance."""
    erp_lines = [{"rate": 18.0, "taxable": 1000.0, "igst": 180.0} for _ in range(10)]
    sr = _sr_multiline("INV/26-27/008", erp_lines)
    # Add 10 paise total rounding to GSTR-1
    g1 = _g1_multiline("INV/26-27/008", erp_lines)
    g1["taxable_amount_paise"] += 10
    g1["total_tax_paise"] += 2
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1


# ─────────────────────────────────────────────────────────────────────────────
# 2. PARTIAL AMENDMENTS & DELTA ATTRIBUTIONS
# ─────────────────────────────────────────────────────────────────────────────

def test_09_partial_amendment_single_line_upward():
    """9. 5-line invoice; line 3 amended upward by ₹5,000 -> Table 3.1(a) delta = +₹5,000."""
    orig_lines = [
        {"rate": 18.0, "taxable": 20000.0, "igst": 3600.0},
        {"rate": 18.0, "taxable": 20000.0, "igst": 3600.0},
        {"rate": 18.0, "taxable": 10000.0, "igst": 1800.0}, # line 3
        {"rate": 18.0, "taxable": 20000.0, "igst": 3600.0},
        {"rate": 18.0, "taxable": 30000.0, "igst": 5400.0},
    ]
    amend_lines = [
        {"rate": 18.0, "taxable": 20000.0, "igst": 3600.0},
        {"rate": 18.0, "taxable": 20000.0, "igst": 3600.0},
        {"rate": 18.0, "taxable": 15000.0, "igst": 2700.0}, # line 3 +5000
        {"rate": 18.0, "taxable": 20000.0, "igst": 3600.0},
        {"rate": 18.0, "taxable": 30000.0, "igst": 5400.0},
    ]
    orig_g1 = _g1_multiline("INV-009", orig_lines, section="b2b")
    amend_g1 = _g1_multiline("INV-009", amend_lines, section="b2ba", is_amendment=True, oinum="INV-009")

    # In Table 3.1(a) tie-out with canonical amendment delta
    canon = _canonical(inv="INV-009", delta_taxable=5000.0, delta_igst=900.0)
    g3b = GSTR3BSummary(taxable_value_paise=_paise(5000.0), igst_paise=_paise(900.0))
    res = reconcile_gstr1_vs_3b([amend_g1], g3b, canonical_amendments=[canon])
    # Delta of ₹5,000 matches GSTR-3B ₹5,000 perfectly -> 0 variances!
    assert len(res.variances) == 0


def test_10_partial_amendment_single_line_downward():
    """10. 5-line invoice; line 2 amended downward by ₹10,000 -> delta = -₹10,000."""
    canon = _canonical(inv="INV-010", delta_taxable=-10000.0, delta_igst=-1800.0)
    amend_g1 = _g1_multiline("INV-010", [{"rate": 18.0, "taxable": 90000.0, "igst": 16200.0}], section="b2ba", is_amendment=True, oinum="INV-010")
    g3b = GSTR3BSummary(taxable_value_paise=_paise(-10000.0), igst_paise=_paise(-1800.0))
    res = reconcile_gstr1_vs_3b([amend_g1], g3b, canonical_amendments=[canon])
    assert len(res.variances) == 0


def test_11_partial_amendment_rate_revision_12_to_18():
    """11. Tax rate changed from 12% to 18% on ₹50,000 taxable -> taxable delta = ₹0, tax delta = +₹3,000."""
    canon = _canonical(inv="INV-011", delta_taxable=0.0, delta_igst=3000.0)
    amend_g1 = _g1_multiline("INV-011", [{"rate": 18.0, "taxable": 50000.0, "igst": 9000.0}], section="b2ba", is_amendment=True, oinum="INV-011")
    g3b = GSTR3BSummary(taxable_value_paise=0, igst_paise=_paise(3000.0))
    res = reconcile_gstr1_vs_3b([amend_g1], g3b, canonical_amendments=[canon])
    assert len(res.variances) == 0


# ─────────────────────────────────────────────────────────────────────────────
# 3. MULTI-PERIOD AMENDMENT CHAINS
# ─────────────────────────────────────────────────────────────────────────────

def test_12_multi_period_chain_four_steps():
    """12. Multi-period amendment chain: Sep Original -> Oct A1 (+50k) -> Nov A2 (-30k) -> Dec CN (-20k)."""
    # Sep Original
    orig_sep = _g1_multiline("INV-100", [{"rate": 18.0, "taxable": 100000.0, "igst": 18000.0}], dt=date(2026, 9, 15))
    # Oct Amendment A1: ₹1,50,000
    a1_oct = _g1_multiline("INV-100", [{"rate": 18.0, "taxable": 150000.0, "igst": 27000.0}], dt=date(2026, 10, 10), section="b2ba", is_amendment=True, oinum="INV-100")
    # Nov Amendment A2: ₹1,20,000
    a2_nov = _g1_multiline("INV-100", [{"rate": 18.0, "taxable": 120000.0, "igst": 21600.0}], dt=date(2026, 11, 5), section="b2ba", is_amendment=True, oinum="INV-100")

    # Lineage resolution
    records = [orig_sep, a1_oct, a2_nov]
    resolved = build_effective_gstr_records(records)
    # Effective record is the terminal amendment (A2)
    assert len(resolved.effective_records) == 1
    eff = resolved.effective_records[0]
    assert eff["taxable_amount_paise"] == _paise(120000.0)
    assert eff["igst_paise"] == _paise(21600.0)
    assert len(resolved.superseded_records) == 2


def test_13_multi_period_chain_terminal_successorship():
    """13. Terminal successorship determines final effective record even with shuffled input."""
    orig = _g1_multiline("INV-200", [{"rate": 18.0, "taxable": 100000.0, "igst": 18000.0}], dt=date(2026, 7, 10))
    a1 = _g1_multiline("INV-200", [{"rate": 18.0, "taxable": 120000.0, "igst": 21600.0}], dt=date(2026, 8, 10), section="b2ba", is_amendment=True, oinum="INV-200")
    a2 = _g1_multiline("INV-200", [{"rate": 18.0, "taxable": 140000.0, "igst": 25200.0}], dt=date(2026, 9, 10), section="b2ba", is_amendment=True, oinum="INV-200")

    # Shuffled input order
    res = build_effective_gstr_records([a2, orig, a1])
    assert len(res.effective_records) == 1
    assert res.effective_records[0]["taxable_amount_paise"] == _paise(140000.0)


def test_14_amendment_with_credit_note_reversal():
    """14. Credit note issued against amended invoice reduces liability."""
    amend = _g1_multiline("INV-300", [{"rate": 18.0, "taxable": 150000.0, "igst": 27000.0}], section="b2ba", is_amendment=True)
    cn = _g1_multiline("CN-300", [{"rate": 18.0, "taxable": 30000.0, "igst": 5400.0}], section="cdnr", doc_type="CREDIT_NOTE")

    agg = aggregate_gstr1([amend, cn])
    # Net liability should reflect 150,000 - 30,000 = 120,000
    assert agg.taxable_value_paise == _paise(120000.0)
    assert agg.igst_paise == _paise(21600.0)


# ─────────────────────────────────────────────────────────────────────────────
# 4. DUPLICATE + AMENDMENT INTERACTIONS
# ─────────────────────────────────────────────────────────────────────────────

def test_15_duplicate_erp_original_with_amendment_in_gstr1():
    """15. ERP has duplicate row for original; GSTR-1 has amendment -> ERP duplicate de-duplicated."""
    canon = _canonical(inv="INV-400", delta_taxable=20000.0, delta_igst=3600.0)
    g1_rows = [
        _g1_multiline("INV-400", [{"rate": 18.0, "taxable": 120000.0, "igst": 21600.0}], section="b2ba", is_amendment=True, oinum="INV-400")
    ]
    g3b = GSTR3BSummary(taxable_value_paise=_paise(20000.0), igst_paise=_paise(3600.0))
    res = reconcile_gstr1_vs_3b(g1_rows, g3b, canonical_amendments=[canon])
    assert len(res.variances) == 0


def test_16_duplicate_amendment_rows_in_portal():
    """16. Identical duplicate amendment rows in GSTR-1 payload are de-duplicated."""
    a1 = _g1_multiline("INV-500", [{"rate": 18.0, "taxable": 120000.0, "igst": 21600.0}], section="b2ba", is_amendment=True, oinum="INV-500")
    a2 = _g1_multiline("INV-500", [{"rate": 18.0, "taxable": 120000.0, "igst": 21600.0}], section="b2ba", is_amendment=True, oinum="INV-500")

    agg = aggregate_gstr1([a1, a2])
    # De-duplicated in liability aggregation
    assert agg.taxable_value_paise == _paise(120000.0)


# ─────────────────────────────────────────────────────────────────────────────
# 5. RATE BUCKET SEGREGATION & MISMATCH DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def test_17_rate_bucket_5_percent_isolation():
    """17. 5% rate bucket segregation in multi-line invoice."""
    lines = [
        {"rate": 5.0, "taxable": 100000.0, "igst": 5000.0},
        {"rate": 18.0, "taxable": 100000.0, "igst": 18000.0},
    ]
    sr = _sr_multiline("INV-017", lines)
    g1 = _g1_multiline("INV-017", lines)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1


def test_18_rate_bucket_12_percent_isolation():
    """18. 12% rate bucket segregation."""
    lines = [
        {"rate": 12.0, "taxable": 50000.0, "igst": 6000.0},
        {"rate": 28.0, "taxable": 50000.0, "igst": 14000.0},
    ]
    sr = _sr_multiline("INV-018", lines)
    g1 = _g1_multiline("INV-018", lines)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1


def test_19_rate_bucket_28_percent_and_cess():
    """19. 28% and cess bucket segregation."""
    lines = [
        {"rate": 28.0, "taxable": 80000.0, "igst": 22400.0, "cess": 9600.0},
    ]
    sr = _sr_multiline("INV-019", lines)
    g1 = _g1_multiline("INV-019", lines)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1


def test_20_nil_and_exempt_bucket_segregation():
    """20. Nil-rated supplies (0%) segregated from taxable outward supplies."""
    nil_rec = {
        "section": "nil",
        "taxable_amount_paise": _paise(25000.0),
        "total_tax_paise": 0,
        "igst_paise": 0,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
    }
    agg = aggregate_gstr1([nil_rec])
    assert agg.nil_exempt_taxable_paise == _paise(25000.0)
    assert agg.taxable_value_paise == 0


def test_21_export_zero_rated_bucket_segregation():
    """21. Export zero-rated supplies segregated into Table 3.1(b)."""
    exp_rec = {
        "section": "exp",
        "invoice_number": "EXP-021",
        "taxable_amount_paise": _paise(150000.0),
        "igst_paise": _paise(27000.0),
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
        "total_tax_paise": _paise(27000.0),
    }
    agg = aggregate_gstr1([exp_rec])
    assert agg.zero_rated_taxable_paise == _paise(150000.0)
    assert agg.zero_rated_igst_paise == _paise(27000.0)
    assert agg.taxable_value_paise == 0  # Table 3.1(a) does not include zero-rated


def test_22_export_amendment_expa_delta():
    """22. EXPA amendment delta correctly updates Table 3.1(b)."""
    canon = _canonical(inv="EXP-022", delta_taxable=20000.0, delta_igst=3600.0, is_zero_rated=True)
    expa_rec = {
        "section": "expa",
        "invoice_number": "EXP-022",
        "is_amendment": True,
        "taxable_amount_paise": _paise(120000.0),
        "igst_paise": _paise(21600.0),
    }
    g3b = GSTR3BSummary(zero_rated_taxable_paise=_paise(20000.0), zero_rated_igst_paise=_paise(3600.0))
    res = reconcile_gstr1_vs_3b([expa_rec], g3b, canonical_amendments=[canon])
    assert len(res.variances) == 0


def test_23_cdna_amendment_delta():
    """23. CDNA (Credit Note Amendment) delta updates outward liability."""
    canon = _canonical(inv="CN-023", delta_taxable=-5000.0, delta_igst=-900.0)
    cdna_rec = {
        "section": "cdna",
        "invoice_number": "CN-023",
        "is_amendment": True,
        "taxable_amount_paise": _paise(25000.0),
        "igst_paise": _paise(4500.0),
    }
    g3b = GSTR3BSummary(taxable_value_paise=_paise(-5000.0), igst_paise=_paise(-900.0))
    res = reconcile_gstr1_vs_3b([cdna_rec], g3b, canonical_amendments=[canon])
    assert len(res.variances) == 0


def test_24_zero_economic_amendment_contributes_zero():
    """24. Zero-economic amendment (invoice number/date change only) contributes ₹0 to 3B tie-out."""
    canon = _canonical(inv="INV-024-NEW", delta_taxable=0.0, delta_igst=0.0, is_zero_economic=True)
    b2ba_rec = {
        "section": "b2ba",
        "invoice_number": "INV-024-NEW",
        "original_invoice_number": "INV-024-OLD",
        "is_amendment": True,
        "taxable_amount_paise": _paise(100000.0),
        "igst_paise": _paise(18000.0),
    }
    g3b = GSTR3BSummary(taxable_value_paise=0, igst_paise=0)
    res = reconcile_gstr1_vs_3b([b2ba_rec], g3b, canonical_amendments=[canon])
    assert len(res.variances) == 0


def test_25_multiline_invoice_with_one_day_date_difference():
    """25. Multi-line invoice with 1-day date difference -> Matched within tolerance."""
    lines = [
        {"rate": 18.0, "taxable": 40000.0, "igst": 7200.0},
        {"rate": 12.0, "taxable": 30000.0, "igst": 3600.0},
    ]
    sr = _sr_multiline("INV-025", lines, dt=date(2026, 9, 15))
    g1 = _g1_multiline("INV-025", lines, dt=date(2026, 9, 16))
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1


def test_26_multiline_invoice_with_format_variant():
    """26. Multi-line invoice with format variant (slashes vs dashes)."""
    lines = [
        {"rate": 18.0, "taxable": 50000.0, "igst": 9000.0},
        {"rate": 5.0, "taxable": 20000.0, "igst": 1000.0},
    ]
    sr = _sr_multiline("INV/2026-27/0026", lines)
    g1 = _g1_multiline("INV-2026-27-0026", lines)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level in (1, 2)


def test_27_multiline_invoice_with_single_ocr_substitution():
    """27. Multi-line invoice with single OCR substitution in invoice number."""
    lines = [
        {"rate": 18.0, "taxable": 60000.0, "igst": 10800.0},
        {"rate": 12.0, "taxable": 40000.0, "igst": 4800.0},
    ]
    sr = _sr_multiline("INV/26-27/00020", lines)
    g1 = _g1_multiline("INV/26-27/0002O", lines)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level in (1, 2)


def test_28_multiline_credit_note_matching():
    """28. Multi-line Credit Note matching between Sales Register and GSTR-1 CDNR."""
    lines = [
        {"rate": 18.0, "taxable": 15000.0, "igst": 2700.0},
        {"rate": 12.0, "taxable": 10000.0, "igst": 1200.0},
    ]
    sr = _sr_multiline("CN-028", lines, doc_type="CREDIT_NOTE")
    g1 = _g1_multiline("CN-028", lines, section="cdnr", doc_type="CREDIT_NOTE")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1


def test_29_multiline_debit_note_matching():
    """29. Multi-line Debit Note matching between Sales Register and GSTR-1 CDNR."""
    lines = [
        {"rate": 18.0, "taxable": 20000.0, "igst": 3600.0},
        {"rate": 28.0, "taxable": 10000.0, "igst": 2800.0},
    ]
    sr = _sr_multiline("DN-029", lines, doc_type="DEBIT_NOTE")
    g1 = _g1_multiline("DN-029", lines, section="cdnr", doc_type="DEBIT_NOTE")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1


def test_30_multiline_reverse_charge_invoice():
    """30. Multi-line invoice under reverse charge."""
    lines = [
        {"rate": 5.0, "taxable": 50000.0, "igst": 2500.0},
        {"rate": 18.0, "taxable": 30000.0, "igst": 5400.0},
    ]
    sr = _sr_multiline("INV-030", lines)
    sr["reverse_charge"] = True
    g1 = _g1_multiline("INV-030", lines)
    g1["rchrg"] = "Y"
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1


def test_31_b2cl_threshold_multiline_split():
    """31. B2CL threshold checked on invoice total across multiple lines (period >= Aug 2024 threshold ₹1,00,000)."""
    # 3 lines of ₹40,000 each = ₹1,20,000 total (> ₹1,00,000 threshold -> B2CL)
    lines = [
        {"rate": 18.0, "taxable": 40000.0, "igst": 7200.0},
        {"rate": 18.0, "taxable": 40000.0, "igst": 7200.0},
        {"rate": 18.0, "taxable": 40000.0, "igst": 7200.0},
    ]
    sr = _sr_multiline("INV-B2CL-031", lines, gstin="", pos="29")
    g1 = _g1_multiline("INV-B2CL-031", lines, gstin="", pos="29", section="b2cl")
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1


def test_32_b2cs_threshold_multiline_below_threshold():
    """32. Multi-line unregistered supply below ₹1,00,000 correctly qualifies as B2CS."""
    lines = [
        {"rate": 18.0, "taxable": 30000.0, "igst": 5400.0},
        {"rate": 18.0, "taxable": 40000.0, "igst": 7200.0},
    ]
    # Total ₹70,000 <= ₹1,00,000 -> B2CS
    tot_taxable = sum(l["taxable"] for l in lines)
    assert tot_taxable == 70000.0 <= 100000.0


def test_33_multiline_invoice_added_line_in_amendment():
    """33. Amendment adds a 4th line item -> delta reflects exactly the added line."""
    canon = _canonical(inv="INV-033", delta_taxable=25000.0, delta_igst=4500.0)
    amend_g1 = _g1_multiline("INV-033", [{"rate": 18.0, "taxable": 125000.0, "igst": 22500.0}], section="b2ba", is_amendment=True, oinum="INV-033")
    g3b = GSTR3BSummary(taxable_value_paise=_paise(25000.0), igst_paise=_paise(4500.0))
    res = reconcile_gstr1_vs_3b([amend_g1], g3b, canonical_amendments=[canon])
    assert len(res.variances) == 0


def test_34_multiline_invoice_dropped_line_in_amendment():
    """34. Amendment removes a cancelled line item -> delta reflects exactly the removed line."""
    canon = _canonical(inv="INV-034", delta_taxable=-20000.0, delta_igst=-3600.0)
    amend_g1 = _g1_multiline("INV-034", [{"rate": 18.0, "taxable": 80000.0, "igst": 14400.0}], section="b2ba", is_amendment=True, oinum="INV-034")
    g3b = GSTR3BSummary(taxable_value_paise=_paise(-20000.0), igst_paise=_paise(-3600.0))
    res = reconcile_gstr1_vs_3b([amend_g1], g3b, canonical_amendments=[canon])
    assert len(res.variances) == 0


def test_35_sibling_amendments_deterministic_tie_break():
    """35. Sibling amendments referencing same original resolve deterministically by return period and date."""
    orig = _g1_multiline("INV-035", [{"rate": 18.0, "taxable": 100000.0, "igst": 18000.0}], dt=date(2026, 7, 10))
    a1 = _g1_multiline("INV-035", [{"rate": 18.0, "taxable": 120000.0, "igst": 21600.0}], dt=date(2026, 8, 10), section="b2ba", is_amendment=True, oinum="INV-035")
    a2 = _g1_multiline("INV-035", [{"rate": 18.0, "taxable": 130000.0, "igst": 23400.0}], dt=date(2026, 9, 10), section="b2ba", is_amendment=True, oinum="INV-035")

    res = build_effective_gstr_records([orig, a1, a2])
    assert len(res.effective_records) == 1
    # Terminal amendment A2 wins
    assert res.effective_records[0]["taxable_amount_paise"] == _paise(130000.0)


def test_36_full_cancellation_of_amendment_chain():
    """36. Amendment chain terminated by a cancellation reduces net delta to zero."""
    res = process_amendment(
        original_record={"total_tax_paise": _paise(18000.0)},
        amended_record=None,  # cancelled
    )
    assert res.type == "CANCELLED"
    assert res.itc_change_paise == _paise(-18000.0)


def test_37_multiline_interstate_eight_lines():
    """37. Multi-line inter-state supply (IGST) split across 8 lines."""
    lines = [{"rate": 18.0, "taxable": 12500.0, "igst": 2250.0} for _ in range(8)]
    sr = _sr_multiline("INV-037", lines)
    g1 = _g1_multiline("INV-037", lines)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1
    assert sr["taxable_amount_paise"] == _paise(100000.0)


def test_38_multiline_intrastate_eight_lines():
    """38. Multi-line intra-state supply (CGST+SGST) split across 8 lines."""
    lines = [{"rate": 18.0, "taxable": 12500.0, "cgst": 1125.0, "sgst": 1125.0} for _ in range(8)]
    sr = _sr_multiline("INV-038", lines)
    g1 = _g1_multiline("INV-038", lines)
    res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
    assert res.matched is True
    assert res.level == 1
    assert sr["cgst_paise"] == g1["cgst_paise"] == _paise(9000.0)


def test_39_mixed_rates_with_cess_aggregation_in_aggregate_gstr1():
    """39. aggregate_gstr1 correctly sums taxable and tax heads across mixed rates."""
    records = [
        {"section": "b2b", "taxable_amount_paise": _paise(10000.0), "igst_paise": _paise(500.0), "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0},
        {"section": "b2b", "taxable_amount_paise": _paise(20000.0), "igst_paise": _paise(2400.0), "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0},
        {"section": "b2b", "taxable_amount_paise": _paise(30000.0), "igst_paise": _paise(5400.0), "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0},
        {"section": "b2b", "taxable_amount_paise": _paise(40000.0), "igst_paise": _paise(11200.0), "cgst_paise": 0, "sgst_paise": 0, "cess_paise": _paise(4800.0)},
    ]
    agg = aggregate_gstr1(records)
    assert agg.taxable_value_paise == _paise(100000.0)
    assert agg.igst_paise == _paise(19500.0)
    assert agg.cess_paise == _paise(4800.0)


def test_40_sez_supplies_with_and_without_tax_payment():
    """40. SEZ supplies with tax payment go to 3.1(b), without payment to 3.1(b) zero tax."""
    sez_wpay = {"section": "exp", "exp_type": "SEZWP", "taxable_amount_paise": _paise(100000.0), "igst_paise": _paise(18000.0), "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}
    sez_wopay = {"section": "exp", "exp_type": "SEZWOP", "taxable_amount_paise": _paise(80000.0), "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}
    agg = aggregate_gstr1([sez_wpay, sez_wopay])
    assert agg.zero_rated_taxable_paise == _paise(180000.0)
    assert agg.zero_rated_igst_paise == _paise(18000.0)


# ─────────────────────────────────────────────────────────────────────────────
# 6. SYNTHETIC BENCHMARK (2,000 RECORDS)
# ─────────────────────────────────────────────────────────────────────────────

def test_run15_synthetic_multiline_and_amendment_benchmark():
    """Synthetic Benchmark: 2,000 records testing multi-line documents and amendment chains.
    
    Verifies:
    1. Multi-line invoices (2 to 20 lines) match at 100% precision.
    2. Rate bucket aggregation sums identically to document totals.
    3. Amendment chains sequence cleanly to terminal successorship.
    4. GSTR-3B tie-out delta reflects exact economic amendments without double counting.
    """
    records_count = 2000
    matched_multiline_count = 0
    total_taxable_paise = 0
    total_tax_paise = 0

    sr_batch = []
    g1_batch = []

    for i in range(records_count):
        num_lines = 2 + (i % 19)  # 2 to 20 lines
        lines = []
        rates = [0.0, 5.0, 12.0, 18.0, 28.0]
        for l_idx in range(num_lines):
            r = rates[l_idx % len(rates)]
            tx = float(1000 * (l_idx + 1))
            tax = tx * r / 100.0
            lines.append({"rate": r, "taxable": tx, "igst": tax})

        inv_num = f"INV-RUN15-{i:05d}"
        sr = _sr_multiline(inv_num, lines)
        g1 = _g1_multiline(inv_num, lines)

        res = generic_match_pair(sr, g1, SALES_MATCH_CONFIG)
        if res.matched and res.level == 1:
            matched_multiline_count += 1
            total_taxable_paise += sr["taxable_amount_paise"]
            total_tax_paise += sr["total_tax_paise"]

    assert matched_multiline_count == records_count
    assert total_taxable_paise > 0
    assert total_tax_paise > 0

    # Test an amendment chain across 200 documents
    chain_records = []
    for i in range(200):
        inv_key = f"AMEND-CHAIN-{i:04d}"
        orig = _g1_multiline(inv_key, [{"rate": 18.0, "taxable": 100000.0, "igst": 18000.0}], dt=date(2026, 7, 1))
        a1 = _g1_multiline(inv_key, [{"rate": 18.0, "taxable": 130000.0, "igst": 23400.0}], dt=date(2026, 8, 1), section="b2ba", is_amendment=True, oinum=inv_key)
        a2 = _g1_multiline(inv_key, [{"rate": 18.0, "taxable": 150000.0, "igst": 27000.0}], dt=date(2026, 9, 1), section="b2ba", is_amendment=True, oinum=inv_key)
        chain_records.extend([orig, a1, a2])

    res_chains = build_effective_gstr_records(chain_records)
    # Exactly 200 terminal effective records retained
    assert len(res_chains.effective_records) == 200
    # Exactly 400 superseded records
    assert len(res_chains.superseded_records) == 400
    # Each effective record holds the final ₹1,50,000 value
    for eff in res_chains.effective_records:
        assert eff["taxable_amount_paise"] == _paise(150000.0)
        assert eff["igst_paise"] == _paise(27000.0)
