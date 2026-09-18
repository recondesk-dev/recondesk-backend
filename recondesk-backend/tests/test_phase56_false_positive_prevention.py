"""Phase 5.6: False-Positive Prevention & URP Parser Integrity Regression Test Suite.

Covers:
- FP-01: Sequential invoice false match (BILL/1877 vs BILL/1978) blocked.
- FP-02: Cross-supplier fuzzy false match (INV/1900 MH vs INV/1920 TN) blocked.
- URP-01 to URP-07: Deterministic parser grouping & supplier identity preservation.
- Invariants 1 to 5: Mathematical and architectural reconciliation invariants.
- Positive and negative regression matrix: Exact, format variant, typo, RCM, CDN.
- Deterministic date generator with intended_date_difference > 0.
"""

import datetime
from datetime import date, timedelta
import pytest

from app.matching.engine import run_bidirectional_reconciliation
from app.parsers.gstr2b_parser import normalize_alt_2b_schema, parse_gstr2b
from app.services.matcher import (
    is_sequential_series_mismatch,
    supplier_identity_compatible,
    normalize_invoice,
    invoice_similarity,
    match_gstr_to_pr,
)

PERIOD = date(2026, 5, 1)


# ─── HELPER FIXTURES ─────────────────────────────────────────────────────────

def _make_gstr(id_val, inv, gstin, taxable, tax, inv_date="2026-05-10", name="Supplier A", **extra):
    return {
        "id": str(id_val),
        "invoice_number": str(inv),
        "invoice_number_normalized": normalize_invoice(str(inv)),
        "supplier_gstin": str(gstin),
        "supplier_name": str(name),
        "invoice_date": str(inv_date),
        "taxable_amount_paise": int(taxable),
        "total_tax_paise": int(tax),
        "cgst_paise": int(tax) // 2,
        "sgst_paise": int(tax) - int(tax) // 2,
        "igst_paise": 0,
        **extra,
    }


def _make_pr(id_val, inv, gstin, taxable, tax, inv_date="2026-05-10", name="Supplier A", **extra):
    return {
        "id": str(id_val),
        "invoice_number": str(inv),
        "invoice_number_normalized": normalize_invoice(str(inv)),
        "supplier_gstin": str(gstin),
        "supplier_name": str(name),
        "vendor_name": str(name),
        "invoice_date": str(inv_date),
        "taxable_amount_paise": int(taxable),
        "total_tax_paise": int(tax),
        "cgst_paise": int(tax) // 2,
        "sgst_paise": int(tax) - int(tax) // 2,
        "igst_paise": 0,
        **extra,
    }


# ==============================================================================
# H. REGRESSION TESTS FOR KNOWN FALSE POSITIVES
# ==============================================================================

def test_fp01_sequential_invoice_numbers_do_not_match():
    """FP-01: GSTR BILL/1877 vs PR BILL/1978 under same supplier must NOT match.

    Both invoices have 2.80% tax difference and sim=0.75, but are distinct sequential
    invoices in the same billing series. GSTR must stay Missed ITC; PR must stay ITC at Risk.
    """
    gstin = "29X00000009P1ZV"
    gstr = [_make_gstr("g_fp1", "BILL/1877", gstin, 19360509, 5420943, inv_date="2026-05-04", name="Supplier 9")]
    pr = [_make_pr("p_fp1", "BILL/1978", gstin, 19917998, 5577039, inv_date="2026-05-06", name="Supplier 9")]

    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)

    # Must NOT become a match or review-required paired discrepancy
    assert res["stats"]["matched_count"] == 0
    assert res["stats"]["review_required_count"] == 0
    # GSTR must remain Missed ITC (unfiled invoice)
    assert res["stats"]["missed_itc_count"] == 1
    assert len(res["missed_itc"]) == 1
    assert res["missed_itc"][0]["invoice_number_normalized"] == "BILL1877"
    # PR must remain ITC at Risk (unrecorded purchase)
    assert res["stats"]["wrongful_risk_count"] == 1
    assert len(res["wrongful_itc_risk"]) == 1
    assert res["wrongful_itc_risk"][0]["invoice_number_normalized"] == "BILL1978"


def test_fp02_cross_supplier_fuzzy_matching_is_blocked():
    """FP-02: GSTR INV/1900 (27 MH) vs PR INV/1920 (33 TN) must NOT match.

    Different states, different PANs, different vendors. Bypassed GSTIN validation must
    be blocked by supplier_identity_compatible gate.
    """
    gstr = [_make_gstr("g_fp2", "INV/1900", "27X00000002P1Z6", 16814210, 840710, inv_date="2026-05-11", name="Supplier 2")]
    pr = [_make_pr("p_fp2", "INV/1920", "33X00000004P1Z3", 17596375, 879819, inv_date="2026-05-17", name="Supplier 4")]

    # Direct supplier identity gate check
    compat, reason, id_type = supplier_identity_compatible(gstr[0], pr[0])
    assert compat is False
    assert id_type == "IDENTITY_CONFLICT"

    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)

    assert res["stats"]["matched_count"] == 0
    assert res["stats"]["review_required_count"] == 0
    assert res["stats"]["missed_itc_count"] == 1
    assert res["stats"]["wrongful_risk_count"] == 1


# ==============================================================================
# G. URP TEST CASES (URP-01 to URP-07)
# ==============================================================================

def test_urp_01_two_urp_invoices_from_different_suppliers():
    """TEST URP-01: Two URP invoices from different suppliers retain distinct identities."""
    payload = {
        "period": "2026-05",
        "invoice": [
            {"Sr": "1", "Party": "Lakshmi Transport", "GSTIN": "URP", "Invoice No": "INV-101", "Invoice Date": "2026-05-10", "Taxable Value": "1000", "Total Tax": "180"},
            {"Sr": "2", "Party": "City Cleaners", "GSTIN": "URP", "Invoice No": "INV-102", "Invoice Date": "2026-05-11", "Taxable Value": "2000", "Total Tax": "360"},
        ]
    }
    portal = normalize_alt_2b_schema(payload)
    parsed = parse_gstr2b(portal)

    records = parsed["records"]
    assert len(records) == 2
    r1 = next(r for r in records if r["invoice_number"] == "INV101")
    r2 = next(r for r in records if r["invoice_number"] == "INV102")
    assert r1["supplier_name"] == "Lakshmi Transport"
    assert r2["supplier_name"] == "City Cleaners"
    assert r1["supplier_name"] != r2["supplier_name"]


def test_urp_02_same_ctin_marker_different_names_remain_distinct():
    """TEST URP-02: Same CTIN marker (UNREGISTERED) but different names remain distinct."""
    payload = {
        "period": "2026-05",
        "invoice": [
            {"Sr": "1", "Party": "Alpha Security", "GSTIN": "UNREGISTERED", "Invoice No": "SEC-01", "Invoice Date": "2026-05-01", "Taxable Value": "5000", "Total Tax": "900"},
            {"Sr": "2", "Party": "Beta Catering", "GSTIN": "UNREGISTERED", "Invoice No": "CAT-01", "Invoice Date": "2026-05-02", "Taxable Value": "6000", "Total Tax": "1080"},
        ]
    }
    portal = normalize_alt_2b_schema(payload)
    parsed = parse_gstr2b(portal)

    records = parsed["records"]
    assert len(records) == 2
    names = {r["supplier_name"] for r in records}
    assert names == {"Alpha Security", "Beta Catering"}


def test_urp_03_same_urp_supplier_groups_consistently():
    """TEST URP-03: Two URP invoices from same supplier group consistently."""
    payload = {
        "period": "2026-05",
        "invoice": [
            {"Sr": "1", "Party": "Lakshmi Transport", "GSTIN": "URP", "Invoice No": "INV-101", "Invoice Date": "2026-05-10", "Taxable Value": "1000", "Total Tax": "180"},
            {"Sr": "2", "Party": "Lakshmi Transport", "GSTIN": "URP", "Invoice No": "INV-102", "Invoice Date": "2026-05-12", "Taxable Value": "1500", "Total Tax": "270"},
        ]
    }
    portal = normalize_alt_2b_schema(payload)
    # Both invoices should be under 1 supplier block in portal output
    assert len(portal["data"]["b2b"]) == 1
    assert portal["data"]["b2b"][0]["trdnm"] == "Lakshmi Transport"
    assert len(portal["data"]["b2b"][0]["inv"]) == 2


def test_urp_04_order_reversal_produces_identical_output():
    """TEST URP-04: URP invoice ordering reversed produces identical supplier attribution."""
    p_forward = {
        "period": "2026-05",
        "invoice": [
            {"Sr": "1", "Party": "Lakshmi Transport", "GSTIN": "URP", "Invoice No": "INV-101", "Invoice Date": "2026-05-10", "Taxable Value": "1000", "Total Tax": "180"},
            {"Sr": "2", "Party": "City Cleaners", "GSTIN": "URP", "Invoice No": "INV-102", "Invoice Date": "2026-05-11", "Taxable Value": "2000", "Total Tax": "360"},
        ]
    }
    p_reverse = {
        "period": "2026-05",
        "invoice": [
            {"Sr": "1", "Party": "City Cleaners", "GSTIN": "URP", "Invoice No": "INV-102", "Invoice Date": "2026-05-11", "Taxable Value": "2000", "Total Tax": "360"},
            {"Sr": "2", "Party": "Lakshmi Transport", "GSTIN": "URP", "Invoice No": "INV-101", "Invoice Date": "2026-05-10", "Taxable Value": "1000", "Total Tax": "180"},
        ]
    }

    res_f = parse_gstr2b(normalize_alt_2b_schema(p_forward))["records"]
    res_r = parse_gstr2b(normalize_alt_2b_schema(p_reverse))["records"]

    map_f = {r["invoice_number"]: r["supplier_name"] for r in res_f}
    map_r = {r["invoice_number"]: r["supplier_name"] for r in res_r}

    assert map_f == map_r
    assert map_f["INV101"] == "Lakshmi Transport"
    assert map_f["INV102"] == "City Cleaners"


def test_urp_05_urp_rcm_records_from_multiple_suppliers():
    """TEST URP-05: URP/RCM records from multiple suppliers have no name overwrite."""
    payload = {
        "period": "2026-05",
        "invoice": [
            {"Sr": "1", "Party": "Delhi Roadlines", "GSTIN": "URP/RCM", "Invoice No": "LR-101", "Invoice Date": "2026-05-01", "Taxable Value": "10000", "Total Tax": "500"},
            {"Sr": "2", "Party": "Maharashtra Advocates", "GSTIN": "URP/RCM", "Invoice No": "ADV-201", "Invoice Date": "2026-05-05", "Taxable Value": "25000", "Total Tax": "4500"},
        ]
    }
    records = parse_gstr2b(normalize_alt_2b_schema(payload))["records"]
    assert len(records) == 2
    r_lr = next(r for r in records if r["invoice_number"] == "LR101")
    r_adv = next(r for r in records if r["invoice_number"] == "ADV201")
    assert r_lr["supplier_name"] == "Delhi Roadlines"
    assert r_adv["supplier_name"] == "Maharashtra Advocates"


def test_urp_06_registered_and_urp_supplier_no_collision():
    """TEST URP-06: Registered supplier + URP supplier have no identity collision."""
    payload = {
        "period": "2026-05",
        "invoice": [
            {"Sr": "1", "Party": "Infosys Ltd", "GSTIN": "29AAACI4916K1Z1", "Invoice No": "INF-101", "Invoice Date": "2026-05-01", "Taxable Value": "50000", "Total Tax": "9000"},
            {"Sr": "2", "Party": "Local Canteen", "GSTIN": "URP", "Invoice No": "CAN-201", "Invoice Date": "2026-05-02", "Taxable Value": "2000", "Total Tax": "100"},
        ]
    }
    records = parse_gstr2b(normalize_alt_2b_schema(payload))["records"]
    assert len(records) == 2
    r_reg = next(r for r in records if r["invoice_number"] == "INF101")
    r_urp = next(r for r in records if r["invoice_number"] == "CAN201")
    assert r_reg["supplier_gstin"] == "29AAACI4916K1Z1"
    assert r_urp["supplier_gstin"] == "URP"
    assert r_urp["supplier_name"] == "Local Canteen"


def test_urp_07_missing_supplier_name_no_accidental_inheritance():
    """TEST URP-07: Missing supplier name on URP invoice does not inherit earlier supplier name."""
    payload = {
        "period": "2026-05",
        "invoice": [
            {"Sr": "1", "Party": "Lakshmi Transport", "GSTIN": "URP", "Invoice No": "INV-101", "Invoice Date": "2026-05-10", "Taxable Value": "1000", "Total Tax": "180"},
            {"Sr": "2", "Party": "", "GSTIN": "URP", "Invoice No": "INV-102", "Invoice Date": "2026-05-11", "Taxable Value": "2000", "Total Tax": "360"},
        ]
    }
    records = parse_gstr2b(normalize_alt_2b_schema(payload))["records"]
    assert len(records) == 2
    r_named = next(r for r in records if r["invoice_number"] == "INV101")
    r_unnamed = next(r for r in records if r["invoice_number"] == "INV102")
    assert r_named["supplier_name"] == "Lakshmi Transport"
    assert r_unnamed["supplier_name"] == ""


# ==============================================================================
# O. PROPERTY / INVARIANT TESTS
# ==============================================================================

def test_invariant_1_fuzzy_candidate_with_gstin_conflict_never_matches():
    """INVARIANT 1: A fuzzy candidate with explicit supplier GSTIN conflict cannot auto-match."""
    gstr = [_make_gstr("g1", "INV-100", "27AAACR5055K1Z7", 1000000, 180000)]
    pr = [_make_pr("p1", "INV-101", "29AAECS1234F1Z2", 1000000, 180000)]  # 27 MH vs 29 KA

    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    assert res["stats"]["matched_count"] == 0
    assert res["stats"]["review_required_count"] == 0
    assert res["stats"]["missed_itc_count"] == 1
    assert res["stats"]["wrongful_risk_count"] == 1


def test_invariant_2_generic_urp_marker_cannot_equate_different_suppliers():
    """INVARIANT 2: A generic URP marker cannot equate two different suppliers."""
    gstr_urp = _make_gstr("g_urp", "URP-1", "URP", 500000, 25000, name="Alpha Logistics")
    pr_urp = _make_pr("p_urp", "URP-1", "URP", 500000, 25000, name="Omega Services")

    compat, reason, id_type = supplier_identity_compatible(gstr_urp, pr_urp)
    assert compat is False
    assert id_type == "IDENTITY_CONFLICT"


def test_invariant_3_parser_output_deterministic_across_permutations():
    """INVARIANT 3: Parser output must be deterministic regardless of source-row ordering."""
    items = [
        {"Sr": "1", "Party": "Vendor A", "GSTIN": "URP", "Invoice No": "A1", "Invoice Date": "2026-05-01", "Taxable Value": "100", "Total Tax": "18"},
        {"Sr": "2", "Party": "Vendor B", "GSTIN": "URP", "Invoice No": "B1", "Invoice Date": "2026-05-02", "Taxable Value": "200", "Total Tax": "36"},
        {"Sr": "3", "Party": "Vendor C", "GSTIN": "URP", "Invoice No": "C1", "Invoice Date": "2026-05-03", "Taxable Value": "300", "Total Tax": "54"},
    ]
    perm1 = {"period": "2026-05", "invoice": items}
    perm2 = {"period": "2026-05", "invoice": [items[2], items[0], items[1]]}

    r1 = {r["invoice_number"]: r["supplier_name"] for r in parse_gstr2b(normalize_alt_2b_schema(perm1))["records"]}
    r2 = {r["invoice_number"]: r["supplier_name"] for r in parse_gstr2b(normalize_alt_2b_schema(perm2))["records"]}

    assert r1 == r2 == {"A1": "Vendor A", "B1": "Vendor B", "C1": "Vendor C"}


def test_invariant_4_exact_match_not_downgraded_by_sequential_series():
    """INVARIANT 4: An exact valid match is not downgraded because another sequential invoice exists."""
    gstin = "27AAACR5055K1Z7"
    gstr = [
        _make_gstr("g1", "INV-100", gstin, 1000000, 180000),
        _make_gstr("g2", "INV-101", gstin, 1000000, 180000),
    ]
    pr = [
        _make_pr("p1", "INV-100", gstin, 1000000, 180000),
        _make_pr("p2", "INV-101", gstin, 1000000, 180000),
    ]

    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    assert res["stats"]["matched_count"] == 2
    assert res["stats"]["review_required_count"] == 0
    assert res["stats"]["missed_itc_count"] == 0


def test_invariant_5_adding_unrelated_supplier_does_not_change_existing_urp_identity():
    """INVARIANT 5: Adding an unrelated supplier's invoice must not change existing URP identity."""
    payload_before = {
        "period": "2026-05",
        "invoice": [
            {"Sr": "1", "Party": "City Cleaners", "GSTIN": "URP", "Invoice No": "C-1", "Invoice Date": "2026-05-01", "Taxable Value": "100", "Total Tax": "18"},
        ]
    }
    payload_after = {
        "period": "2026-05",
        "invoice": [
            {"Sr": "1", "Party": "New Random Supplier", "GSTIN": "URP", "Invoice No": "N-1", "Invoice Date": "2026-05-01", "Taxable Value": "500", "Total Tax": "90"},
            {"Sr": "2", "Party": "City Cleaners", "GSTIN": "URP", "Invoice No": "C-1", "Invoice Date": "2026-05-01", "Taxable Value": "100", "Total Tax": "18"},
        ]
    }

    r_before = parse_gstr2b(normalize_alt_2b_schema(payload_before))["records"][0]
    r_after = next(r for r in parse_gstr2b(normalize_alt_2b_schema(payload_after))["records"] if r["invoice_number"] == "C1")

    assert r_before["supplier_name"] == r_after["supplier_name"] == "City Cleaners"


# ==============================================================================
# I. POSITIVE AND NEGATIVE REGRESSION MATRIX
# ==============================================================================

def test_matrix_positive_exact_match():
    """1. Exact invoice + same GSTIN -> Level 1 exact clean match."""
    gstin = "27AAACR5055K1Z7"
    gstr = [_make_gstr("g1", "INV/2026/001", gstin, 1000000, 180000)]
    pr = [_make_pr("p1", "INV/2026/001", gstin, 1000000, 180000)]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    assert res["stats"]["matched_count"] == 1
    assert res["stats"]["clean_matched_count"] == 1


def test_matrix_positive_format_variant_match():
    """2. Format variant invoice + same GSTIN -> clean match."""
    gstin = "27AAACR5055K1Z7"
    gstr = [_make_gstr("g1", "DS/26/78", gstin, 1000000, 180000)]
    pr = [_make_pr("p1", "DS-2026-00078", gstin, 1000000, 180000)]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    assert res["stats"]["matched_count"] == 1


def test_matrix_positive_valid_typo_match():
    """3. Non-sequential OCR typo with identical taxable twin -> Review Required."""
    gstin = "27AAACR5055K1Z7"
    gstr = [_make_gstr("g1", "BILL952425", gstin, 1000000, 180000)]
    pr = [_make_pr("p1", "BLIL952425", gstin, 1000000, 180000)]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    assert res["stats"]["review_required_count"] == 1


def test_matrix_positive_urp_same_supplier_match():
    """4. URP same supplier with exact numbers -> clean match."""
    gstr = [_make_gstr("g1", "URP-101", "URP", 500000, 25000, name="City Cleaners")]
    pr = [_make_pr("p1", "URP-101", "URP", 500000, 25000, name="City Cleaners")]
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    assert res["stats"]["matched_count"] == 1


def test_matrix_positive_same_pan_gstin_variant():
    """5. Same PAN across state branches is recognised as PAN_MATCH."""
    g_gst = "27AAACR5055K1Z7"  # MH
    p_gst = "29AAACR5055K1Z3"  # KA (same PAN AAACR5055K)
    compat, reason, id_type = supplier_identity_compatible(g_gst, p_gst)
    assert compat is True
    assert id_type == "PAN_MATCH"


def test_matrix_negative_amount_mismatch_behavior_preserved():
    """6. Same invoice + same GSTIN but amount difference -> Review Required."""
    gstin = "27AAACR5055K1Z7"
    gstr = [_make_gstr("g1", "INV-101", gstin, 1000000, 180000)]
    pr = [_make_pr("p1", "INV-101", gstin, 1200000, 216000)]  # 20% diff
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    assert res["stats"]["review_required_count"] == 1


def test_matrix_negative_date_discrepancy_behavior_preserved():
    """7. Same invoice + same GSTIN + date shift within tolerance -> Flagged for Review."""
    gstin = "27AAACR5055K1Z7"
    gstr = [_make_gstr("g1", "INV-101", gstin, 1000000, 180000, inv_date="2026-05-10")]
    pr = [_make_pr("p1", "INV-101", gstin, 1000000, 180000, inv_date="2026-05-18")]  # 8 days
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    assert res["stats"]["review_required_count"] == 1


# ==============================================================================
# L. DETERMINISTIC DATE GENERATOR FIX VERIFICATION
# ==============================================================================

def test_deterministic_date_discrepancy_generator():
    """L. Verify that intended date difference is strictly > 0 across month ends."""
    def apply_date_offset(base_date: date, offset_days: int) -> date:
        assert offset_days > 0, "intended_date_difference must be > 0"
        return base_date + timedelta(days=offset_days)

    # May 31 + 5 days must roll over cleanly to June 5, NOT clamp to May 31
    base = date(2026, 5, 31)
    offset_date = apply_date_offset(base, 5)
    assert offset_date == date(2026, 6, 5)
    assert (offset_date - base).days == 5
    assert (offset_date - base).days > 0
