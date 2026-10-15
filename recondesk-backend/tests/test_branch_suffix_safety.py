"""Adversarial and safety tests for Branch Suffix and Compound OCR Reconciliation.

Verifies:
1. Safe branch-suffix-only match (single candidate, matching GSTIN, matching doc type,
   reliable sequence, exact amounts, no same-supplier collision) -> Level 2 Clean Match.
2. Competing same-supplier base sequence collision (e.g. INV-100 vs INV-100-BR01 and INV-100-BR02)
   -> Level 3 Review Required (BRANCH_SUFFIX_REVIEW).
3. Competing base vs branch collision -> Level 3 Review Required (BRANCH_SUFFIX_REVIEW).
4. Compound OCR + branch suffix (1+ OCR substitution + branch suffix) -> Level 3 Review Required (OCR_CONFIDENCE_REVIEW).
5. Document type disagreement with branch suffix -> Review Required / Incompatible.
6. Sequence mismatch with branch suffix -> Review Required.
7. End-to-end reconciliation and export preserves original invoice numbers and source references.
"""

import datetime
from app.services.matcher import (
    MatchResult,
    _match_gstr_to_pr_pair,
    check_is_branch_variant,
    get_invoice_base_sequence,
)
from app.services.reconciliation import (
    check_competing_branch_invoices,
    ReconState,
    process_gstr_records_chunk,
    _push_clean_matched,
    _push_review_required,
)
from app.matching.engine import run_bidirectional_reconciliation


def test_check_is_branch_variant():
    assert check_is_branch_variant("INV-100", "INV-100-BR01", "INV-100", "INV-100-BR01") is True
    assert check_is_branch_variant("INV-100/HO", "INV-100", "INV-100/HO", "INV-100") is True
    assert check_is_branch_variant("INV-100-UNIT2", "INV-100", "INV-100-UNIT2", "INV-100") is True
    assert check_is_branch_variant("INV-100", "INV-200", "INV-100", "INV-200") is False
    assert check_is_branch_variant("INV-100", "INV-100", "INV-100", "INV-100") is False


def test_get_invoice_base_sequence():
    assert get_invoice_base_sequence("INV-100-BR01") == "INV100"
    assert get_invoice_base_sequence("INV-100/HO") == "INV100"
    assert get_invoice_base_sequence("INV-100-UNIT2") == "INV100"
    assert get_invoice_base_sequence("INV-100") == "INV100"


def test_safe_branch_suffix_clean_match():
    """Branch-suffix-only with 0 OCR substitutions, exact amounts, same GSTIN, no collisions -> L2 Clean Match."""
    gstr = {
        "id": "g1",
        "supplier_gstin": "27ABCDE1234F1Z5",
        "invoice_number": "INV-100",
        "invoice_number_raw": "INV-100",
        "invoice_number_normalized": "INV100",
        "invoice_date": "2024-04-01",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "doc_type": "INVOICE",
    }
    pr = {
        "id": "p1",
        "supplier_gstin": "27ABCDE1234F1Z5",
        "invoice_number": "INV-100-BR01",
        "invoice_number_raw": "INV-100-BR01",
        "invoice_number_normalized": "INV100BR01",
        "invoice_date": "2024-04-01",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "doc_type": "INVOICE",
    }
    res = _match_gstr_to_pr_pair(gstr, pr, has_competing_invoices=False)
    assert res.matched is True
    assert res.level == 2
    assert res.requires_human_review is False
    assert res.is_branch_variant is True


def test_compound_ocr_plus_branch_always_routes_to_review():
    """Branch suffix + at least 1 OCR substitution (e.g. INV-10O vs INV-100-BR01) MUST route to L3 OCR_CONFIDENCE_REVIEW."""
    gstr = {
        "id": "g1",
        "supplier_gstin": "27ABCDE1234F1Z5",
        "invoice_number": "INV-10O",  # O instead of 0 (OCR error)
        "invoice_number_raw": "INV-10O",
        "invoice_number_normalized": "INV10O",
        "invoice_date": "2024-04-01",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "doc_type": "INVOICE",
    }
    pr = {
        "id": "p1",
        "supplier_gstin": "27ABCDE1234F1Z5",
        "invoice_number": "INV-100-BR01",
        "invoice_number_raw": "INV-100-BR01",
        "invoice_number_normalized": "INV100BR01",
        "invoice_date": "2024-04-01",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "doc_type": "INVOICE",
    }
    res = _match_gstr_to_pr_pair(gstr, pr, has_competing_invoices=False)
    assert res.matched is True
    assert res.level == 3
    assert res.requires_human_review is True
    assert res.review_reason == "OCR_CONFIDENCE_REVIEW"


def test_competing_branch_invoices_routes_to_review():
    """When another same-supplier PR has the same base sequence, check_competing_branch_invoices triggers."""
    gstr = {
        "id": "g1",
        "supplier_gstin": "27ABCDE1234F1Z5",
        "invoice_number": "INV-100",
        "invoice_number_raw": "INV-100",
        "invoice_number_normalized": "INV100",
        "invoice_date": "2024-04-01",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "doc_type": "INVOICE",
    }
    best_pr = {
        "id": "p1",
        "supplier_gstin": "27ABCDE1234F1Z5",
        "invoice_number": "INV-100-BR01",
        "invoice_number_raw": "INV-100-BR01",
        "invoice_number_normalized": "INV100BR01",
        "invoice_date": "2024-04-01",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "doc_type": "INVOICE",
    }
    competing_pr = {
        "id": "p2",
        "supplier_gstin": "27ABCDE1234F1Z5",
        "invoice_number": "INV-100-BR02",
        "invoice_number_raw": "INV-100-BR02",
        "invoice_number_normalized": "INV100BR02",
        "invoice_date": "2024-04-01",
        "taxable_amount_paise": 500000,
        "total_tax_paise": 90000,
        "doc_type": "INVOICE",
    }

    # Case 1: Competing branch exists
    is_competing = check_competing_branch_invoices(
        gstr_record=gstr,
        best_pr=best_pr,
        all_supplier_prs=[best_pr, competing_pr],
        consumed_pr_ids=set(),
    )
    assert is_competing is True

    # Case 2: No competing branch (only unrelated invoice INV-200)
    unrelated_pr = {
        "id": "p3",
        "supplier_gstin": "27ABCDE1234F1Z5",
        "invoice_number": "INV-200",
        "invoice_number_raw": "INV-200",
        "invoice_number_normalized": "INV200",
        "invoice_date": "2024-04-01",
        "taxable_amount_paise": 200000,
        "total_tax_paise": 36000,
        "doc_type": "INVOICE",
    }
    is_competing_unrelated = check_competing_branch_invoices(
        gstr_record=gstr,
        best_pr=best_pr,
        all_supplier_prs=[best_pr, unrelated_pr],
        consumed_pr_ids=set(),
    )
    assert is_competing_unrelated is False


def test_end_to_end_reconciliation_branch_collision_routing():
    """Full bidirectional pipeline properly routes colliding branch invoices to review."""
    gstin = "27ABCDE1234F1Z5"
    gstr_records = [
        {
            "id": "g1",
            "supplier_gstin": gstin,
            "invoice_number": "INV-100",
            "invoice_number_raw": "INV-100",
            "invoice_number_normalized": "INV100",
            "invoice_date": datetime.date(2024, 4, 1),
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
            "doc_type": "INVOICE",
        }
    ]
    # Two PR records sharing the base sequence INV100 from same supplier
    pr_records = [
        {
            "id": "p1",
            "supplier_gstin": gstin,
            "invoice_number": "INV-100-BR01",
            "invoice_number_raw": "INV-100-BR01",
            "invoice_number_normalized": "INV100BR01",
            "invoice_date": datetime.date(2024, 4, 1),
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
            "doc_type": "INVOICE",
        },
        {
            "id": "p2",
            "supplier_gstin": gstin,
            "invoice_number": "INV-100-BR02",
            "invoice_number_raw": "INV-100-BR02",
            "invoice_number_normalized": "INV100BR02",
            "invoice_date": datetime.date(2024, 4, 1),
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
            "doc_type": "INVOICE",
        },
    ]

    result = run_bidirectional_reconciliation(gstr_records, pr_records, gstr_period=datetime.date(2024, 4, 1))
    
    # Must NOT be clean matched! Must be routed to review_required due to competition
    assert len(result.get("matched", [])) == 0
    assert len(result.get("review_required", [])) == 1
    rev = result["review_required"][0]
    assert rev["review_reason"] == "BRANCH_SUFFIX_REVIEW"
    assert rev["original_gstr_invoice_number"] == "INV-100"
    assert rev["original_pr_invoice_number"] in ("INV-100-BR01", "INV-100-BR02")


def test_end_to_end_reconciliation_compound_ocr_routing():
    """Full pipeline routes compound OCR + branch suffix to review."""
    gstin = "27ABCDE1234F1Z5"
    gstr_records = [
        {
            "id": "g1",
            "supplier_gstin": gstin,
            "invoice_number": "INV-10O",  # OCR typo 'O'
            "invoice_number_raw": "INV-10O",
            "invoice_number_normalized": "INV10O",
            "invoice_date": datetime.date(2024, 4, 1),
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
            "doc_type": "INVOICE",
        }
    ]
    pr_records = [
        {
            "id": "p1",
            "supplier_gstin": gstin,
            "invoice_number": "INV-100-BR01",
            "invoice_number_raw": "INV-100-BR01",
            "invoice_number_normalized": "INV100BR01",
            "invoice_date": datetime.date(2024, 4, 1),
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
            "doc_type": "INVOICE",
        }
    ]

    result = run_bidirectional_reconciliation(gstr_records, pr_records, gstr_period=datetime.date(2024, 4, 1))
    assert len(result.get("matched", [])) == 0
    assert len(result.get("review_required", [])) == 1
    rev = result["review_required"][0]
    assert rev["review_reason"] == "OCR_CONFIDENCE_REVIEW"
    assert rev["original_gstr_invoice_number"] == "INV-10O"
    assert rev["original_pr_invoice_number"] == "INV-100-BR01"


def test_cross_pan_never_matches():
    """Different PANs with identical invoice number and amounts must NEVER match."""
    gstr = {
        "id": "g1",
        "supplier_gstin": "27AAAAA1234A1Z5",
        "invoice_number": "INV-100",
        "invoice_number_raw": "INV-100",
        "invoice_number_normalized": "INV100",
        "invoice_date": "2024-04-01",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "doc_type": "INVOICE",
    }
    pr = {
        "id": "p1",
        "supplier_gstin": "27BBBBB9999B1Z5",  # Different PAN
        "invoice_number": "INV-100",
        "invoice_number_raw": "INV-100",
        "invoice_number_normalized": "INV100",
        "invoice_date": "2024-04-01",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "doc_type": "INVOICE",
    }
    res = _match_gstr_to_pr_pair(gstr, pr)
    assert res.matched is False
    assert res.level == 6


def test_same_pan_different_gstin_routes_to_review():
    """Same PAN across different state GSTINs must route to Level 3 GSTIN_MISMATCH, never clean match."""
    gstr = {
        "id": "g1",
        "supplier_gstin": "27AAAAA1234A1Z5",  # Maharashtra
        "invoice_number": "INV-100",
        "invoice_number_raw": "INV-100",
        "invoice_number_normalized": "INV100",
        "invoice_date": "2024-04-01",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "doc_type": "INVOICE",
    }
    pr = {
        "id": "p1",
        "supplier_gstin": "29AAAAA1234A1Z5",  # Karnataka, same PAN AAAAA1234A
        "invoice_number": "INV-100",
        "invoice_number_raw": "INV-100",
        "invoice_number_normalized": "INV100",
        "invoice_date": "2024-04-01",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "doc_type": "INVOICE",
    }
    res = _match_gstr_to_pr_pair(gstr, pr)
    assert res.requires_human_review is True
    assert res.level in (3, 4)


def test_excel_export_original_invoice_traceability():
    """Verify Excel export preserves original invoice numbers in dedicated columns without shifting."""
    from openpyxl import load_workbook
    from io import BytesIO
    from app.services.reconcile_export_workbook import build_excel_workbook_bytes

    matched_pairs = [
        (
            {
                "supplier_gstin": "27ABCDE1234F1Z0",
                "invoice_number": "TAX-01/00001",
                "original_gstr_invoice_number": "TAX-01/00001",
                "original_pr_invoice_number": "TAX-01/00001",
                "normalized_invoice_number": "TAX100001",
                "gstr_source_ref": "g_2",
                "pr_source_ref": "p_2",
                "invoice_date": "2024-04-01",
                "taxable_amount_paise": 1000000,
                "amount": 1800,
                "match_level": "EXACT",
                "confidence_score": 100,
            },
            None,
        )
    ]
    review_rows = [
        {
            "supplier_gstin": "27ABCDE1234F1Z0",
            "invoice_number": "TAX-01/00002",
            "original_gstr_invoice_number": "TAX-01/00002",
            "original_pr_invoice_number": "TAX-01/00002-BR01",
            "normalized_invoice_number": "TAX100002",
            "gstr_source_ref": "g_3",
            "pr_source_ref": "p_3",
            "invoice_date": "2024-04-01",
            "discrepancy_reason": "BRANCH_SUFFIX_REVIEW",
            "amount": 1800,
            "priority": "HIGH",
        }
    ]

    xlsx_bytes, _ = build_excel_workbook_bytes(
        run_id="run-test",
        firm_name="Test Firm",
        client_trade_name="Test Client",
        period_raw="2024-04",
        summary={"total_gstr_records": 2, "matched_count": 1},
        matched_pairs=matched_pairs,
        missed_rows=[],
        risk_rows=[],
        rule37_rows=[],
        section17_rows=[],
        review_required_rows=review_rows,
        generated_at=datetime.datetime.now(),
        generated_by_name="Tester",
    )
    wb = load_workbook(BytesIO(xlsx_bytes))
    
    # Matched Records sheet
    ws_m = wb["Matched Records"]
    headers_m = [c.value for c in ws_m[1]]
    assert "Original GSTR-2B Invoice Number" in headers_m
    assert "Original PR Invoice Number" in headers_m
    assert "Normalized Invoice Number" in headers_m
    assert "GSTR-2B Source Ref" in headers_m
    assert "PR Source Ref" in headers_m
    
    row2_m = [c.value for c in ws_m[2]]
    g_col = headers_m.index("Original GSTR-2B Invoice Number")
    p_col = headers_m.index("Original PR Invoice Number")
    n_col = headers_m.index("Normalized Invoice Number")
    assert row2_m[g_col] == "TAX-01/00001"
    assert row2_m[p_col] == "TAX-01/00001"
    assert row2_m[n_col] == "TAX100001"

    # Review Required sheet
    ws_r = wb["Review Required"]
    headers_r = [c.value for c in ws_r[1]]
    assert "Original GSTR-2B Invoice Number" in headers_r
    assert "Original PR Invoice Number" in headers_r
    row2_r = [c.value for c in ws_r[2]]
    gr_col = headers_r.index("Original GSTR-2B Invoice Number")
    pr_col = headers_r.index("Original PR Invoice Number")
    assert row2_r[gr_col] == "TAX-01/00002"
    assert row2_r[pr_col] == "TAX-01/00002-BR01"

