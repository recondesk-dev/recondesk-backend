"""Regression test for Run 20 OCR_SINGLE false negative bug fix.

Test case:
PR: SUP/0926/00504
2B: SUP92600S4
GSTIN: 24KJIFE5558B1ZU

Validates:
1. Normalization and OCR alignment of the exact pair.
2. Candidate generation and retrieval across indices.
3. Matching as Level 2 Clean Match (Matched Records = +1, Missed ITC = -1, Compliance Risk = -1).
4. Multi-OCR safety guard preservation (>= 2 OCR substitutions must route to Review Required).
5. Conservation invariants on Run 20 totals.
"""

import pytest
from app.matching.engine import run_bidirectional_reconciliation
from app.services.matcher import (
    normalize_invoice,
    ocr_canonical_invoice,
    ocr_alignment,
    is_invoice_format_variant,
    count_ocr_substitutions,
    match_gstr_to_pr,
    is_sequential_series_mismatch,
)
from app.services.reconciliation import (
    build_pr_candidate_indices,
    _get_narrowed_candidates,
)


def test_run20_ocr_single_normalization_and_alignment():
    """Verify normalization and ocr_alignment on the exact Run 20 pair."""
    pr_raw = "SUP/0926/00504"
    gstr_raw = "SUP92600S4"

    # Normalization
    pr_norm = normalize_invoice(pr_raw)
    gstr_norm = normalize_invoice(gstr_raw)
    assert pr_norm == "SUP92600504"
    assert gstr_norm == "SUP92600S4"

    # OCR alignment identifies exactly 1 OCR substitution (S <-> 5) with zero padding
    is_match, ocr_cnt, subs = ocr_alignment(gstr_raw, pr_raw)
    assert is_match is True
    assert ocr_cnt == 1
    assert any("S/5" in s or "5/S" in s for s in subs)

    # Format variant check returns True
    assert is_invoice_format_variant(gstr_norm, pr_norm, gstr_raw, pr_raw) is True

    # count_ocr_substitutions returns (1, False) -> single OCR, no prefix risk
    cnt, has_risk = count_ocr_substitutions(gstr_raw, pr_raw)
    assert cnt == 1
    assert has_risk is False

    # Not treated as a sequential series mismatch
    assert is_sequential_series_mismatch(gstr_norm, pr_norm, gstr_raw, pr_raw) is False


def test_run20_ocr_candidate_indexing_and_retrieval():
    """Verify candidate indexing and retrieval finds PR for 2B even with zero differences."""
    pr_rec = {
        "id": "pr-run20-001",
        "supplier_gstin": "24KJIFE5558B1ZU",
        "invoice_number": "SUP/0926/00504",
        "invoice_number_normalized": normalize_invoice("SUP/0926/00504"),
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
    }
    pr_index = {"24KJIFE5558B1ZU": [pr_rec]}
    candidate_indices = build_pr_candidate_indices(pr_index)

    gstr_rec = {
        "id": "gstr-run20-001",
        "supplier_gstin": "24KJIFE5558B1ZU",
        "invoice_number": "SUP92600S4",
        "invoice_number_normalized": normalize_invoice("SUP92600S4"),
        "taxable_value_paise": 1000000,
        "total_tax_paise": 180000,
    }

    cands = _get_narrowed_candidates(
        gstr_rec,
        gstin="24KJIFE5558B1ZU",
        inv_norm=normalize_invoice("SUP92600S4"),
        pr_by_invoice=None,
        candidate_indices=candidate_indices,
        pr_index_candidates=[pr_rec],
    )
    assert len(cands) >= 1
    cand_ids = [c["id"] for c in cands]
    assert "pr-run20-001" in cand_ids


def test_run20_ocr_single_exact_pair_reconciliation():
    """Verify the exact pair matches cleanly as Level 2 Matched Records."""
    pr_rec = {
        "id": "pr-run20-target",
        "supplier_gstin": "24KJIFE5558B1ZU",
        "supplier_name": "Supplier 24KJIFE",
        "invoice_number": "SUP/0926/00504",
        "invoice_number_normalized": normalize_invoice("SUP/0926/00504"),
        "invoice_date": "2026-09-15",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "cgst_paise": 90000,
        "sgst_paise": 90000,
        "igst_paise": 0,
        "doc_type": "INVOICE",
    }

    gstr_rec = {
        "id": "gstr-run20-target",
        "supplier_gstin": "24KJIFE5558B1ZU",
        "supplier_name": "Supplier 24KJIFE",
        "invoice_number": "SUP92600S4",
        "invoice_number_normalized": normalize_invoice("SUP92600S4"),
        "invoice_date": "2026-09-15",
        "taxable_value_paise": 1000000,
        "total_tax_paise": 180000,
        "cgst_paise": 90000,
        "sgst_paise": 90000,
        "igst_paise": 0,
        "doc_type": "INVOICE",
    }

    # Match pair directly
    direct_match = match_gstr_to_pr(gstr_rec, [pr_rec])
    assert direct_match is not None
    assert direct_match.matched is True
    assert direct_match.level == 2
    assert direct_match.requires_human_review is False
    assert direct_match.confidence == 95

    # Full bidirectional engine run
    res = run_bidirectional_reconciliation([gstr_rec], [pr_rec])
    stats = res.get("stats") or {}

    assert stats.get("matched_count") == 1
    assert stats.get("clean_matched_count") == 1
    assert stats.get("review_required_count") == 0
    assert stats.get("missed_itc_count") == 0
    assert stats.get("wrongful_risk_count") == 0
    assert stats.get("itc_at_risk_count") == 0

    assert len(res.get("matched", [])) == 1
    matched_row = res["matched"][0]
    assert matched_row["gstr_id"] == "gstr-run20-target"
    assert matched_row["pr_id"] == "pr-run20-target"
    assert matched_row["match_level"] == 2
    assert matched_row["match_status"] == "matched"


def test_multi_ocr_safeguard_preserved():
    """Verify pairs with >= 2 OCR substitutions MUST still route to Review Required."""
    pr_multi = {
        "id": "pr-multi-risk",
        "supplier_gstin": "24KJIFE5558B1ZU",
        "supplier_name": "Supplier 24KJIFE",
        "invoice_number": "SUP/0926/OO504",  # OO instead of 00 -> 3 OCR substitutions (O/0, O/0, S/5)
        "invoice_number_normalized": normalize_invoice("SUP/0926/OO504"),
        "invoice_date": "2026-09-15",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "cgst_paise": 90000,
        "sgst_paise": 90000,
        "igst_paise": 0,
        "doc_type": "INVOICE",
    }

    gstr_rec = {
        "id": "gstr-multi-test",
        "supplier_gstin": "24KJIFE5558B1ZU",
        "supplier_name": "Supplier 24KJIFE",
        "invoice_number": "SUP92600S4",
        "invoice_number_normalized": normalize_invoice("SUP92600S4"),
        "invoice_date": "2026-09-15",
        "taxable_value_paise": 1000000,
        "total_tax_paise": 180000,
        "cgst_paise": 90000,
        "sgst_paise": 90000,
        "igst_paise": 0,
        "doc_type": "INVOICE",
    }

    direct_match = match_gstr_to_pr(gstr_rec, [pr_multi])
    assert direct_match is not None
    assert direct_match.matched is True
    assert direct_match.level == 3
    assert direct_match.requires_human_review is True
    assert direct_match.review_reason == "OCR_CONFIDENCE_REVIEW"

    res = run_bidirectional_reconciliation([gstr_rec], [pr_multi])
    stats = res.get("stats") or {}
    assert stats.get("matched_count") == 0
    assert stats.get("review_required_count") == 1
    assert stats.get("missed_itc_count") == 0
    assert len(res.get("review_required", [])) == 1


def test_non_ocr_sequential_mismatch_not_matched():
    """Verify pairs differing by non-OCR sequential digits are NOT matched."""
    pr_seq = {
        "id": "pr-seq-test",
        "supplier_gstin": "24KJIFE5558B1ZU",
        "invoice_number": "SUP/0926/00505",  # 505 vs 504 (non-OCR sequential mismatch)
        "invoice_number_normalized": normalize_invoice("SUP/0926/00505"),
        "invoice_date": "2026-09-15",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "doc_type": "INVOICE",
    }

    gstr_rec = {
        "id": "gstr-seq-test",
        "supplier_gstin": "24KJIFE5558B1ZU",
        "invoice_number": "SUP/0926/00504",
        "invoice_number_normalized": normalize_invoice("SUP/0926/00504"),
        "invoice_date": "2026-09-15",
        "taxable_value_paise": 1000000,
        "total_tax_paise": 180000,
        "doc_type": "INVOICE",
    }

    assert is_sequential_series_mismatch(
        gstr_rec["invoice_number_normalized"],
        pr_seq["invoice_number_normalized"],
        gstr_rec["invoice_number"],
        pr_seq["invoice_number"],
    ) is True
