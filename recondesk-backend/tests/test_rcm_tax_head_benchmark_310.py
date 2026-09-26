"""Deterministic 310-Record Benchmark Fixture for ReconDesk.

Proves mathematically that:
1. Exactly 160 records classified as clean matches (100 clean forward + 50 clean RCM + 10 incomplete breakdown).
2. Exactly 70 records classified as RCM_FLAG_CONFLICT (30 + 20 + 20).
3. Exactly 60 records classified as TAX_HEAD_MISMATCH (30 equal total + 10 mixed + 10 cess + 10 credit notes).
4. Exactly 20 records classified as AMOUNT_MISMATCH.
5. Zero records with RCM conflict or tax-head mismatch classified as clean matches.
6. Zero records with RCM conflict or tax-head mismatch routed to Table 4(A)(5).
7. All 50 clean RCM records routed to Table 3.1(d) and Table 4(A)(3).
8. All 150 review records assigned URGENT or appropriate priority.
"""

from typing import Any
import pytest
from app.services.matcher import match_gstr_to_pr
from app.services.review_priority import classify_review_priority, PRIORITY_URGENT
from app.services.statutory_eligibility import (
    classify_statutory_treatment_for_matched,
    ITCEligibilityStatus,
)


def _make_pair(
    *,
    idx: int,
    prefix: str,
    g_rcm: Any = False,
    p_rcm: Any = False,
    g_taxable: int = 10_000_000,
    p_taxable: int = 10_000_000,
    g_igst: int = 0,
    g_cgst: int = 0,
    g_sgst: int = 0,
    g_cess: int = 0,
    g_tot: int = 0,
    p_igst: int = 0,
    p_cgst: int = 0,
    p_sgst: int = 0,
    p_cess: int = 0,
    p_tot: int = 0,
    doc_type: str = "INVOICE",
):
    inv_num = f"{prefix}-{idx:04d}"
    g_tot_tax = g_tot if g_tot else (g_igst + g_cgst + g_sgst + g_cess)
    p_tot_tax = p_tot if p_tot else (p_igst + p_cgst + p_sgst + p_cess)

    g = {
        "id": f"g-{inv_num}",
        "supplier_gstin": "27AABCU9603R1ZM",
        "supplier_name": "ACME SUPPLIER PVT LTD",
        "invoice_number": inv_num,
        "invoice_number_normalized": inv_num.replace("-", "").upper(),
        "invoice_date": "2024-03-15",
        "taxable_amount_paise": g_taxable,
        "taxable_value_paise": g_taxable,
        "igst_paise": g_igst,
        "cgst_paise": g_cgst,
        "sgst_paise": g_sgst,
        "cess_paise": g_cess,
        "total_tax_paise": g_tot_tax,
        "invoice_value_paise": g_taxable + g_tot_tax,
        "total_amount_paise": g_taxable + g_tot_tax,
        "reverse_charge": g_rcm,
        "doc_type": doc_type,
    }
    p = {
        "id": f"p-{inv_num}",
        "supplier_gstin": "27AABCU9603R1ZM",
        "vendor_name": "ACME SUPPLIER PVT LTD",
        "invoice_number": inv_num,
        "invoice_number_normalized": inv_num.replace("-", "").upper(),
        "invoice_date": "2024-03-15",
        "taxable_amount_paise": p_taxable,
        "taxable_value_paise": p_taxable,
        "igst_paise": p_igst,
        "cgst_paise": p_cgst,
        "sgst_paise": p_sgst,
        "cess_paise": p_cess,
        "total_tax_paise": p_tot_tax,
        "invoice_value_paise": p_taxable + p_tot_tax,
        "total_amount_paise": p_taxable + p_tot_tax,
        "reverse_charge": p_rcm,
        "doc_type": doc_type,
    }
    return g, p


def generate_benchmark_310():
    """Generates the full deterministic 310 benchmark records across 11 buckets."""
    pairs = []

    # Bucket 1: 100 Clean forward charge
    for i in range(1, 101):
        g, p = _make_pair(
            idx=i, prefix="FWD",
            g_rcm=False, p_rcm=False,
            g_igst=1_800_000, p_igst=1_800_000,
        )
        pairs.append(("CLEAN_FORWARD", g, p))

    # Bucket 2: 50 Clean RCM
    for i in range(1, 51):
        g, p = _make_pair(
            idx=i, prefix="RCM-CLEAN",
            g_rcm=True, p_rcm=True,
            g_igst=1_800_000, p_igst=1_800_000,
        )
        pairs.append(("CLEAN_RCM", g, p))

    # Bucket 3: 30 RCM vs forward charge (GSTR=True, PR=False)
    for i in range(1, 31):
        g, p = _make_pair(
            idx=i, prefix="RCM-VS-FWD",
            g_rcm=True, p_rcm=False,
            g_igst=1_800_000, p_igst=1_800_000,
        )
        pairs.append(("RCM_FLAG_CONFLICT", g, p))

    # Bucket 4: 20 GSTR RCM, PR missing flag (GSTR=True, PR=None)
    for i in range(1, 21):
        g, p = _make_pair(
            idx=i, prefix="RCM-PR-MISSING",
            g_rcm=True, p_rcm=None,
            g_igst=1_800_000, p_igst=1_800_000,
        )
        pairs.append(("RCM_FLAG_CONFLICT", g, p))

    # Bucket 5: 20 Forward GSTR, PR RCM (GSTR=False, PR=True)
    for i in range(1, 21):
        g, p = _make_pair(
            idx=i, prefix="FWD-PR-RCM",
            g_rcm=False, p_rcm=True,
            g_igst=1_800_000, p_igst=1_800_000,
        )
        pairs.append(("RCM_FLAG_CONFLICT", g, p))

    # Bucket 6: 30 Equal total tax, IGST vs CGST+SGST
    for i in range(1, 31):
        g, p = _make_pair(
            idx=i, prefix="HEAD-SWAP",
            g_rcm=False, p_rcm=False,
            g_igst=1_800_000,
            p_cgst=900_000, p_sgst=900_000,
        )
        pairs.append(("TAX_HEAD_MISMATCH", g, p))

    # Bucket 7: 20 Same heads, amount mismatch beyond tolerance
    for i in range(1, 21):
        g, p = _make_pair(
            idx=i, prefix="AMT-DIFF",
            g_rcm=False, p_rcm=False,
            g_igst=1_800_000,
            p_igst=1_500_000,  # diff ₹3,000 > tolerance
        )
        pairs.append(("AMOUNT_MISMATCH", g, p))

    # Bucket 8: 10 Mixed head allocations (mixed vs pure)
    for i in range(1, 11):
        g, p = _make_pair(
            idx=i, prefix="MIXED",
            g_rcm=False, p_rcm=False,
            g_igst=1_000_000, g_cgst=450_000, g_sgst=450_000,
            p_igst=1_900_000,
        )
        pairs.append(("TAX_HEAD_MISMATCH", g, p))

    # Bucket 9: 10 Incomplete head breakdown (PR aggregate total only, Case D)
    for i in range(1, 11):
        g, p = _make_pair(
            idx=i, prefix="NO-BREAKDOWN",
            g_rcm=False, p_rcm=False,
            g_igst=1_800_000, g_tot=1_800_000,
            p_igst=0, p_cgst=0, p_sgst=0, p_cess=0, p_tot=1_800_000,
        )
        pairs.append(("CLEAN_INCOMPLETE_BREAKDOWN", g, p))

    # Bucket 10: 10 Cess discrepancies (cess present on one side only)
    for i in range(1, 11):
        g, p = _make_pair(
            idx=i, prefix="CESS-DIFF",
            g_rcm=False, p_rcm=False,
            g_igst=1_800_000, g_cess=200_000,
            p_igst=1_800_000, p_cess=0,
        )
        pairs.append(("TAX_HEAD_MISMATCH", g, p))

    # Bucket 11: 10 Credit notes (CDNR IGST vs CN CGST+SGST)
    for i in range(1, 11):
        g, p = _make_pair(
            idx=i, prefix="CRN-DIFF",
            g_rcm=False, p_rcm=False,
            g_igst=500_000,
            p_cgst=250_000, p_sgst=250_000,
            doc_type="CREDIT_NOTE",
        )
        pairs.append(("TAX_HEAD_MISMATCH", g, p))

    return pairs


def test_deterministic_310_record_benchmark_fixture():
    """Execute the full 310 benchmark and verify exact mathematical counts & assertions."""
    pairs = generate_benchmark_310()
    assert len(pairs) == 310

    clean_matches = []
    rcm_conflicts = []
    tax_head_mismatches = []
    amount_mismatches = []
    other_reviews = []

    # Table 4 and statutory tracking
    t4a5_eligible_count = 0
    t4a3_rcm_count = 0
    t31d_liability_count = 0

    for bucket_type, g, p in pairs:
        r = match_gstr_to_pr(g, [p])
        assert r is not None
        assert r.matched is True

        # Classify outcome
        if not r.requires_human_review:
            clean_matches.append((bucket_type, g, p, r))
            # Statutory evaluation for clean matches
            sc = classify_statutory_treatment_for_matched(
                g, {}, p, {},
                is_itc_avail=True,
                itc_rsn=None,
                is_r37a=False,
                is_blocked_credit=False,
                default_d_what="Clean match",
                default_d_why="Aligned",
                default_d_next="None",
            )
            if sc.claim_table == "4(A)(5)":
                t4a5_eligible_count += 1
            elif sc.claim_table == "4(A)(3)":
                t4a3_rcm_count += 1
            if sc.liability_table == "3.1(d)":
                t31d_liability_count += 1

        else:
            prio = classify_review_priority({"review_reason": r.review_reason, "taxable_diff_paise": 0})
            if r.review_reason == "RCM_FLAG_CONFLICT":
                rcm_conflicts.append((bucket_type, g, p, r, prio))
            elif r.review_reason == "TAX_HEAD_MISMATCH":
                tax_head_mismatches.append((bucket_type, g, p, r, prio))
            elif r.review_reason and "AMOUNT_MISMATCH" in r.review_reason:
                amount_mismatches.append((bucket_type, g, p, r, prio))
            else:
                other_reviews.append((bucket_type, g, p, r, prio))

    # ══════════════════════════════════════════════════════════════════════════
    # Benchmark Verification Assertions (Prompt Section 12)
    # ══════════════════════════════════════════════════════════════════════════

    # 1. Exactly 160 records classified as clean matches (100 clean forward + 50 clean RCM + 10 incomplete breakdown)
    assert len(clean_matches) == 160, f"Expected 160 clean matches, got {len(clean_matches)}"

    # 2. Exactly 70 records classified as RCM_FLAG_CONFLICT (30 + 20 + 20)
    assert len(rcm_conflicts) == 70, f"Expected 70 RCM conflicts, got {len(rcm_conflicts)}"

    # 3. Exactly 60 records classified as TAX_HEAD_MISMATCH (30 equal total + 10 mixed + 10 cess + 10 credit notes)
    assert len(tax_head_mismatches) == 60, f"Expected 60 tax head mismatches, got {len(tax_head_mismatches)}"

    # 4. Exactly 20 records classified as AMOUNT_MISMATCH
    assert len(amount_mismatches) == 20, f"Expected 20 amount mismatches, got {len(amount_mismatches)}"

    # Total check: 160 clean + 70 rcm + 60 head + 20 amount = 310
    total_reviews = len(rcm_conflicts) + len(tax_head_mismatches) + len(amount_mismatches)
    assert total_reviews == 150
    assert len(clean_matches) + total_reviews == 310

    # 5. Zero records with RCM conflict or tax-head mismatch classified as clean matches
    for bucket_type, g, p, r in clean_matches:
        assert bucket_type in ("CLEAN_FORWARD", "CLEAN_RCM", "CLEAN_INCOMPLETE_BREAKDOWN")
        assert r.requires_human_review is False

    # 6. Zero records with RCM conflict or tax-head mismatch routed to Table 4(A)(5)
    # 7. All 50 clean RCM records routed to Table 3.1(d) and Table 4(A)(3)
    assert t4a5_eligible_count == 110  # 100 clean forward + 10 incomplete breakdown
    assert t4a3_rcm_count == 50        # exactly 50 clean RCM
    assert t31d_liability_count == 50  # exactly 50 clean RCM

    # 8. All 130 RCM and tax-head review records assigned URGENT priority
    for item in rcm_conflicts:
        assert item[4] == PRIORITY_URGENT
    for item in tax_head_mismatches:
        assert item[4] == PRIORITY_URGENT
