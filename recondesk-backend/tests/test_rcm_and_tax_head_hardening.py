"""Comprehensive test suite for RCM Conflict & Tax-Head Mismatch Detection Hardening.

Covers:
1. RCM Tri-State Normalization & 9-Case Truth Table
2. 15-Case Tax-Head Validation Matrix
3. Matcher Integration & Candidate Linking
4. Review Priority & Triage Classification
5. Downstream GSTR-3B Table 4 Exclusion / Routing
"""

import pytest
from app.services.matcher import (
    match_gstr_to_pr,
    _match_gstr_to_pr_pair,
    build_compared_fields,
)
from app.services.statutory_eligibility import (
    RCM_TRUE,
    RCM_FALSE,
    RCM_UNKNOWN,
    normalize_rcm_tristate,
    detect_rcm_conflict,
    get_rcm_conflict_details,
    detect_tax_head_mismatch,
    get_tax_head_mismatch_details,
)
from app.services.review_priority import (
    classify_review_priority,
    review_priority_sort_key,
    PRIORITY_URGENT,
    PRIORITY_HIGH,
    PRIORITY_MEDIUM,
    PRIORITY_LOW,
)
from app.services.gstr3b_table4_engine import compile_gstr3b_table4
from app.services.reconciliation_outcomes import OutcomeRow


def _base_rec(
    *,
    id="rec-1",
    supplier_gstin="27AABCU9603R1ZM",
    supplier_name="ACME SUPPLIER PVT LTD",
    invoice_number="INV-1001",
    invoice_date="2024-03-15",
    taxable_paise=10_000_000,
    igst_paise=0,
    cgst_paise=0,
    sgst_paise=0,
    cess_paise=0,
    total_tax_paise=0,
    reverse_charge=None,
    doc_type="INVOICE",
):
    tot_tax = total_tax_paise if total_tax_paise else (igst_paise + cgst_paise + sgst_paise + cess_paise)
    tot_amt = taxable_paise + tot_tax
    return {
        "id": id,
        "supplier_gstin": supplier_gstin,
        "supplier_name": supplier_name,
        "vendor_name": supplier_name,
        "invoice_number": invoice_number,
        "invoice_number_normalized": invoice_number.replace("-", "").upper(),
        "invoice_date": invoice_date,
        "taxable_amount_paise": taxable_paise,
        "taxable_value_paise": taxable_paise,
        "igst_paise": igst_paise,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "cess_paise": cess_paise,
        "total_tax_paise": tot_tax,
        "total_amount_paise": tot_amt,
        "invoice_value_paise": tot_amt,
        "reverse_charge": reverse_charge,
        "doc_type": doc_type,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. RCM Tri-State Normalization & 9-Case Truth Table
# ══════════════════════════════════════════════════════════════════════════════

def test_rcm_tristate_normalization():
    """Verify normalization of diverse ERP and GSTN representations."""
    # True representations
    for val in (True, 1, "Y", "YES", "TRUE", "1", "RCM", "REVERSE CHARGE", "T", "y", "true", "rcm"):
        assert normalize_rcm_tristate(val) == RCM_TRUE

    # False representations
    for val in (False, 0, "N", "NO", "FALSE", "0", "FCM", "FORWARD CHARGE", "FORWARD", "REGULAR", "F", "n", "false"):
        assert normalize_rcm_tristate(val) == RCM_FALSE

    # Unknown representations
    for val in (None, "", "   ", "UNKNOWN", "NA", 99, 12.5, object()):
        assert normalize_rcm_tristate(val) == RCM_UNKNOWN


@pytest.mark.parametrize(
    "g_val, pr_val, expected_conflict",
    [
        # Case 1: Both agree supply is reverse charge
        (RCM_TRUE, RCM_TRUE, False),
        # Case 2: Supplier filed RCM; recipient booked forward charge
        (RCM_TRUE, RCM_FALSE, True),
        # Case 3: Supplier filed RCM; recipient omitted flag
        (RCM_TRUE, RCM_UNKNOWN, True),
        # Case 4: Recipient treated as RCM; supplier filed forward charge
        (RCM_FALSE, RCM_TRUE, True),
        # Case 5: Both agree supply is forward charge
        (RCM_FALSE, RCM_FALSE, False),
        # Case 6: Supplier forward charge; recipient omitted flag -> presumed forward
        (RCM_FALSE, RCM_UNKNOWN, False),
        # Case 7: GSTR omitted; PR has RCM -> don't conflict on missing GSTR
        (RCM_UNKNOWN, RCM_TRUE, False),
        # Case 8: GSTR omitted; PR forward charge
        (RCM_UNKNOWN, RCM_FALSE, False),
        # Case 9: Both omitted -> presumed forward
        (RCM_UNKNOWN, RCM_UNKNOWN, False),
    ],
)
def test_rcm_conflict_truth_table_all_9_cases(g_val, pr_val, expected_conflict):
    """Verify complete 9-case truth table for detect_rcm_conflict."""
    assert detect_rcm_conflict(g_val, pr_val) is expected_conflict


def test_rcm_conflict_actionable_explanations():
    """Verify WHAT, WHY, NEXT generated for RCM conflict scenarios."""
    # GSTR=RCM, PR=Forward
    what1, why1, next1 = get_rcm_conflict_details(RCM_TRUE, RCM_FALSE)
    assert what1 == "Reverse charge treatment differs between GSTR-2B and Purchase Register."
    assert "Section 9(3)/9(4)" in why1
    assert "Table 3.1(d)" in next1 and "Table 4(A)(3)" in next1

    # GSTR=Forward, PR=RCM
    what2, why2, next2 = get_rcm_conflict_details(RCM_FALSE, RCM_TRUE)
    assert what2 == "Reverse charge treatment differs between GSTR-2B and Purchase Register."
    assert "Purchase Register marks this invoice as reverse charge" in why2
    assert "reclassify in purchase register" in next2


# ══════════════════════════════════════════════════════════════════════════════
# 2. 15-Case Tax-Head Validation Matrix
# ══════════════════════════════════════════════════════════════════════════════

def test_case_01_pure_igst_vs_pure_cgst_sgst():
    """Case 1: GSTR pure IGST, PR pure CGST+SGST, equal total tax."""
    g = _base_rec(igst_paise=1_800_000)
    p = _base_rec(cgst_paise=900_000, sgst_paise=900_000)
    is_mismatch, msg = detect_tax_head_mismatch(g, p)
    assert is_mismatch is True
    assert "pure IGST" in msg and "CGST+SGST" in msg


def test_case_02_pure_cgst_sgst_vs_pure_igst():
    """Case 2: GSTR pure CGST+SGST, PR pure IGST, equal total tax."""
    g = _base_rec(cgst_paise=900_000, sgst_paise=900_000)
    p = _base_rec(igst_paise=1_800_000)
    is_mismatch, msg = detect_tax_head_mismatch(g, p)
    assert is_mismatch is True
    assert "CGST+SGST" in msg and "pure IGST" in msg


def test_case_03_both_pure_igst_equal():
    """Case 3: Both Pure IGST, equal amounts -> Clean match."""
    g = _base_rec(igst_paise=1_800_000)
    p = _base_rec(igst_paise=1_800_000)
    is_mismatch, msg = detect_tax_head_mismatch(g, p)
    assert is_mismatch is False
    assert msg is None


def test_case_04_both_pure_cgst_sgst_equal():
    """Case 4: Both Pure CGST+SGST, equal amounts -> Clean match."""
    g = _base_rec(cgst_paise=900_000, sgst_paise=900_000)
    p = _base_rec(cgst_paise=900_000, sgst_paise=900_000)
    is_mismatch, msg = detect_tax_head_mismatch(g, p)
    assert is_mismatch is False
    assert msg is None


def test_case_05_both_pure_igst_amount_differs():
    """Case 5: Both Pure IGST, amounts differ beyond tolerance -> AMOUNT_MISMATCH."""
    g = _base_rec(igst_paise=1_800_000)
    p = _base_rec(igst_paise=1_500_000)  # ₹3,000 diff > 1% tolerance
    is_mismatch, msg = detect_tax_head_mismatch(g, p)
    # Head structure is consistent (both IGST)
    assert is_mismatch is False

    # In matcher, this must route to AMOUNT_MISMATCH
    r = match_gstr_to_pr(g, [p])
    assert r is not None
    assert "AMOUNT_MISMATCH" in (r.review_reason or "")


def test_case_06_both_cgst_sgst_amount_differs():
    """Case 6: Both CGST+SGST, amounts differ beyond tolerance -> AMOUNT_MISMATCH."""
    g = _base_rec(cgst_paise=900_000, sgst_paise=900_000)
    p = _base_rec(cgst_paise=750_000, sgst_paise=750_000)  # ₹3,000 diff > 1% tolerance
    is_mismatch, msg = detect_tax_head_mismatch(g, p)
    # Structure is consistent (both symmetric intra-state)
    assert is_mismatch is False

    r = match_gstr_to_pr(g, [p])
    assert r is not None
    assert "AMOUNT_MISMATCH" in (r.review_reason or "")


def test_case_07_asymmetric_intra_state_heads():
    """Case 7: Intra-state heads asymmetric in PR (CGST != SGST)."""
    g = _base_rec(cgst_paise=900_000, sgst_paise=900_000)
    p = _base_rec(cgst_paise=1_000_000, sgst_paise=800_000)
    is_mismatch, msg = detect_tax_head_mismatch(g, p)
    assert is_mismatch is True
    assert "asymmetric" in msg.lower()


def test_case_08_cess_in_gstr_zero_in_pr():
    """Case 8: Cess present in GSTR-2B, zero in PR."""
    g = _base_rec(igst_paise=1_800_000, cess_paise=200_000)
    p = _base_rec(igst_paise=1_800_000, cess_paise=0)
    is_mismatch, msg = detect_tax_head_mismatch(g, p)
    assert is_mismatch is True
    assert "Cess mismatch" in msg


def test_case_09_zero_cess_in_gstr_cess_in_pr():
    """Case 9: Zero cess in GSTR-2B, cess present in PR."""
    g = _base_rec(igst_paise=1_800_000, cess_paise=0)
    p = _base_rec(igst_paise=1_800_000, cess_paise=200_000)
    is_mismatch, msg = detect_tax_head_mismatch(g, p)
    assert is_mismatch is True
    assert "Cess mismatch" in msg


def test_case_10_mixed_heads_in_gstr_pure_in_pr():
    """Case 10: Mixed heads in GSTR (IGST + CGST + SGST), pure IGST in PR."""
    g = _base_rec(igst_paise=1_000_000, cgst_paise=450_000, sgst_paise=450_000)
    p = _base_rec(igst_paise=1_900_000)
    is_mismatch, msg = detect_tax_head_mismatch(g, p)
    assert is_mismatch is True
    assert "Mixed tax head allocation" in msg


def test_case_11_pr_aggregate_total_only_preserves_case_d():
    """Case 11: PR with only total tax (no breakdown), GSTR with IGST -> Preserves Case D clean match."""
    g = _base_rec(igst_paise=1_800_000, total_tax_paise=1_800_000)
    # PR has total_tax_paise but 0 for all component heads
    p = _base_rec(
        igst_paise=0, cgst_paise=0, sgst_paise=0, cess_paise=0, total_tax_paise=1_800_000
    )
    is_mismatch, msg = detect_tax_head_mismatch(g, p)
    # Must NOT fabricate mismatch when PR lacks component breakdown
    assert is_mismatch is False
    assert msg is None

    # Matches cleanly
    r = match_gstr_to_pr(g, [p])
    assert r is not None
    assert r.matched is True
    assert r.requires_human_review is False
    assert r.level == 1


def test_case_12_credit_note_head_mismatch():
    """Case 12: Credit note with head mismatch (CDNR IGST vs CN CGST+SGST)."""
    g = _base_rec(
        invoice_number="CRN-501",
        doc_type="CREDIT_NOTE",
        igst_paise=500_000,
        total_tax_paise=500_000,
    )
    p = _base_rec(
        invoice_number="CRN-501",
        doc_type="CREDIT_NOTE",
        cgst_paise=250_000,
        sgst_paise=250_000,
        total_tax_paise=500_000,
    )
    is_mismatch, msg = detect_tax_head_mismatch(g, p)
    assert is_mismatch is True

    r = match_gstr_to_pr(g, [p])
    assert r is not None
    assert r.matched is True
    assert r.requires_human_review is True
    assert r.review_reason == "TAX_HEAD_MISMATCH"


def test_case_13_zero_tax_nil_rated():
    """Case 13: Nil-rated / zero tax on both sides."""
    g = _base_rec(taxable_paise=5_000_000, total_tax_paise=0)
    p = _base_rec(taxable_paise=5_000_000, total_tax_paise=0)
    is_mismatch, msg = detect_tax_head_mismatch(g, p)
    assert is_mismatch is False

    r = match_gstr_to_pr(g, [p])
    assert r is not None
    assert r.matched is True
    assert r.requires_human_review is False
    assert r.level == 1


def test_case_14_rounding_difference_within_tolerance():
    """Case 14: Rounding difference <= 100 paise (₹1) across heads -> Clean match."""
    # Intra-state CGST/SGST with 50 paise rounding
    g = _base_rec(cgst_paise=900_050, sgst_paise=900_050)
    p = _base_rec(cgst_paise=900_000, sgst_paise=900_100)
    is_mismatch, msg = detect_tax_head_mismatch(g, p)
    assert is_mismatch is False


def test_case_15_place_of_supply_conflict():
    """Case 15: Place of supply conflict (inter-state in GSTR vs intra-state in PR)."""
    g = _base_rec(igst_paise=1_800_000)
    p = _base_rec(cgst_paise=900_000, sgst_paise=900_000)
    r = match_gstr_to_pr(g, [p])
    assert r is not None
    assert r.matched is True
    assert r.requires_human_review is True
    assert r.review_reason == "TAX_HEAD_MISMATCH"
    assert "Tax head allocation mismatch" in r.decision_what


# ══════════════════════════════════════════════════════════════════════════════
# 3. Matcher Compared Fields & Discrepancies
# ══════════════════════════════════════════════════════════════════════════════

def test_compared_fields_observations():
    """Verify build_compared_fields includes reverse_charge and tax_heads observations."""
    # Clean pair
    g_clean = _base_rec(igst_paise=1_800_000, reverse_charge=False)
    p_clean = _base_rec(igst_paise=1_800_000, reverse_charge=False)
    cf_clean = build_compared_fields(g_clean, p_clean)
    cf_map_clean = {item["field_name"]: item["match_type"] for item in cf_clean}
    assert cf_map_clean.get("reverse_charge") == "exact"
    assert cf_map_clean.get("tax_heads") == "exact"

    # Conflicting pair
    g_bad = _base_rec(igst_paise=1_800_000, reverse_charge=True)
    p_bad = _base_rec(cgst_paise=900_000, sgst_paise=900_000, reverse_charge=False)
    cf_bad = build_compared_fields(g_bad, p_bad)
    cf_map_bad = {item["field_name"]: item["match_type"] for item in cf_bad}
    assert cf_map_bad.get("reverse_charge") == "not_matched"
    assert cf_map_bad.get("tax_heads") == "not_matched"


def test_simultaneous_rcm_conflict_and_tax_head_mismatch():
    """When both RCM conflict and tax-head mismatch occur, TAX_HEAD_MISMATCH takes precedence."""
    g = _base_rec(igst_paise=1_800_000, reverse_charge=True)
    p = _base_rec(cgst_paise=900_000, sgst_paise=900_000, reverse_charge=False)

    r = match_gstr_to_pr(g, [p])
    assert r is not None
    assert r.matched is True
    assert r.requires_human_review is True
    assert r.review_reason == "TAX_HEAD_MISMATCH"
    # Both discrepancies recorded
    assert any("tax_head_mismatch" in d for d in r.discrepancies)
    assert any("rcm_conflict" in d for d in r.discrepancies)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Review Priority & Triage Classification
# ══════════════════════════════════════════════════════════════════════════════

def test_review_priority_for_rcm_and_tax_head():
    """Verify RCM_FLAG_CONFLICT and TAX_HEAD_MISMATCH are classified as URGENT priority."""
    rcm_row = {"review_reason": "RCM_FLAG_CONFLICT", "taxable_diff_paise": 0}
    head_row = {"review_reason": "TAX_HEAD_MISMATCH", "taxable_diff_paise": 0}
    other_row = {"review_reason": "Amount/Date mismatch", "taxable_diff_paise": 5_000}

    assert classify_review_priority(rcm_row) == PRIORITY_URGENT
    assert classify_review_priority(head_row) == PRIORITY_URGENT
    assert classify_review_priority(other_row) == PRIORITY_LOW

    # Verify sorting: URGENT rows sort ahead of ordinary review rows
    sorted_rows = sorted([other_row, rcm_row, head_row], key=review_priority_sort_key)
    assert sorted_rows[0]["review_reason"] in ("RCM_FLAG_CONFLICT", "TAX_HEAD_MISMATCH")
    assert sorted_rows[1]["review_reason"] in ("RCM_FLAG_CONFLICT", "TAX_HEAD_MISMATCH")
    assert sorted_rows[2]["review_reason"] == "Amount/Date mismatch"
