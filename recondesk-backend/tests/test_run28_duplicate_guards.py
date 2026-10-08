"""Regression tests for Run 28 False-Duplicate Issue.

Requirements:
1. Duplicate classification must require the same full supplier GSTIN, document type, and canonical invoice identity.
2. Canonicalization must preserve meaningful terminal alphabetic suffixes. Invoice suffixes A and B must remain distinct.
3. High invoice similarity plus matching dates and amounts must never, by itself, establish a duplicate.
4. Preserve detection of true identical and conflicting duplicates.
5. Preserve one-to-one allocation: a GSTR-2B document cannot be reused for another purchase-register row.
"""

import pytest
from app.matching.engine import run_bidirectional_reconciliation
from app.services.reconciliation import (
    _same_canonical_invoice_identity,
    _peer_pr_invoice_clone_ok,
    _is_distinct_sequential_invoices,
    _terminal_alpha_suffix,
)


# ── 1. UNIT TESTS: TERMINAL SUFFIX & IDENTITY PRESERVATION ───────────────────


def test_terminal_alpha_suffix_preserves_distinct_suffixes():
    """Meaningful terminal alphabetic suffixes A and B must remain distinct."""
    assert _terminal_alpha_suffix("NEAR/R28/019A", "NEAR/R28/019A") == "A"
    assert _terminal_alpha_suffix("NEAR/R28/019B", "NEAR/R28/019B") == "B"
    assert _terminal_alpha_suffix("NEAR/R28/019-A", "NEAR/R28/019-A") == "A"
    assert _terminal_alpha_suffix("NEAR/R28/019-B", "NEAR/R28/019-B") == "B"
    assert _terminal_alpha_suffix("019A", "019A") == "A"
    assert _terminal_alpha_suffix("019B", "019B") == "B"
    assert _terminal_alpha_suffix("019", "019") == ""


def test_distinct_sequential_invoices_flags_differing_suffixes():
    """Invoices in the same series differing by suffix A vs B are distinct sequential invoices."""
    assert _is_distinct_sequential_invoices(
        "NEARR28019A", "NEARR28019B", "NEAR/R28/019A", "NEAR/R28/019B"
    ) is True
    assert _is_distinct_sequential_invoices(
        "NEARR28019A", "NEARR28019", "NEAR/R28/019A", "NEAR/R28/019"
    ) is True


def test_same_canonical_invoice_identity_rejects_differing_suffixes():
    """Canonical invoice identity rejects invoices with different terminal suffixes A vs B."""
    assert _same_canonical_invoice_identity(
        "NEARR28019A", "NEARR28019B", "NEAR/R28/019A", "NEAR/R28/019B"
    ) is False
    assert _same_canonical_invoice_identity(
        "NEARR28019A", "NEARR28019", "NEAR/R28/019A", "NEAR/R28/019"
    ) is False
    # Same canonical invoice identity preserved for exact matches & format variants with same suffix
    assert _same_canonical_invoice_identity(
        "NEARR28019A", "NEARR28019A", "NEAR/R28/019A", "NEAR/R28/019A"
    ) is True
    assert _same_canonical_invoice_identity(
        "INV00045A", "INV0045A", "INV-00045-A", "INV-0045-A"
    ) is True


def test_peer_pr_invoice_clone_rejects_differing_suffixes():
    """Peer PR clone check strictly rejects differing suffixes even with high string similarity."""
    ok, _ = _peer_pr_invoice_clone_ok(
        "NEARR28019A", "NEARR28019B", "NEAR/R28/019A", "NEAR/R28/019B"
    )
    assert ok is False


# ── 2. E2E REGRESSION: RUN 28 NEAR/R28/019A vs NEAR/R28/019B ────────────────


def test_run28_near_019a_and_019b_false_duplicate_resolved():
    """Regression test for Run 28 false-duplicate issue.

    Same supplier/date/amount, invoices NEAR/R28/019A and NEAR/R28/019B,
    with only A present in GSTR-2B:
    - A retains its correct match.
    - B remains unmatched in the purchase register (wrongful_itc_risk).
    - B is not classified as a duplicate.
    - B cannot reuse A's GSTR-2B document (one-to-one allocation).
    """
    gstr_records = [
        {
            "id": "g_1",
            "invoice_number": "NEAR/R28/019A",
            "invoice_number_normalized": "NEARR28019A",
            "supplier_gstin": "29AABCU9603R1Z2",
            "invoice_date": "2026-09-15",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
            "igst_paise": 180000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "INVOICE",
        }
    ]
    pr_records = [
        {
            "id": "p_a",
            "invoice_number": "NEAR/R28/019A",
            "invoice_number_normalized": "NEARR28019A",
            "supplier_gstin": "29AABCU9603R1Z2",
            "invoice_date": "2026-09-15",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
            "igst_paise": 180000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "INVOICE",
        },
        {
            "id": "p_b",
            "invoice_number": "NEAR/R28/019B",
            "invoice_number_normalized": "NEARR28019B",
            "supplier_gstin": "29AABCU9603R1Z2",
            "invoice_date": "2026-09-15",
            "taxable_amount_paise": 1000000,  # Same amount
            "total_tax_paise": 180000,
            "igst_paise": 180000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "INVOICE",
        },
    ]

    res = run_bidirectional_reconciliation(gstr_records, pr_records, gstr_period="2026-09-01")

    # 1. A retains its correct match
    assert len(res["matched"]) == 1
    assert res["matched"][0]["pr_id"] == "p_a"
    assert res["matched"][0]["gstr_id"] == "g_1"

    # 2. B is NOT classified as a duplicate
    assert len(res["duplicate_entries"]) == 0
    dup_ids = [d["id"] for d in res["duplicate_entries"]]
    assert "p_b" not in dup_ids

    # 3. B remains unmatched in the purchase register (wrongful_itc_risk)
    itc_risk_ids = [r["id"] for r in res["wrongful_itc_risk"]]
    assert "p_b" in itc_risk_ids

    # 4. One-to-one allocation: GSTR-2B document g_1 is NOT reused for B
    matched_gstr_ids = [m["gstr_id"] for m in res["matched"]]
    assert matched_gstr_ids == ["g_1"]


# ── 3. PRESERVE TRUE IDENTICAL AND CONFLICTING DUPLICATES ────────────────────


def test_true_identical_duplicates_preserved():
    """Same canonical invoice identity with identical values -> DUPLICATE_ENTRY preserved."""
    gstr_records = [
        {
            "id": "g_1",
            "invoice_number": "INV/2026/001",
            "invoice_number_normalized": "INV2026001",
            "supplier_gstin": "27AAPFU0939F1ZV",
            "invoice_date": "2026-09-15",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
            "igst_paise": 180000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "INVOICE",
        }
    ]
    pr_records = [
        {
            "id": "p_1",
            "invoice_number": "INV/2026/001",
            "invoice_number_normalized": "INV2026001",
            "supplier_gstin": "27AAPFU0939F1ZV",
            "invoice_date": "2026-09-15",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
            "igst_paise": 180000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "INVOICE",
        },
        {
            "id": "p_2",
            "invoice_number": "INV/2026/001",
            "invoice_number_normalized": "INV2026001",
            "supplier_gstin": "27AAPFU0939F1ZV",
            "invoice_date": "2026-09-15",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
            "igst_paise": 180000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "INVOICE",
        },
    ]

    res = run_bidirectional_reconciliation(gstr_records, pr_records, gstr_period="2026-09-01")

    assert len(res["matched"]) == 1
    assert len(res["duplicate_entries"]) == 1
    assert res["duplicate_entries"][0]["reason"] == "DUPLICATE_ENTRY"
    assert len(res["wrongful_itc_risk"]) == 0


def test_true_conflicting_duplicates_preserved():
    """Same canonical invoice identity with conflicting values -> PR_CLAIMED_BY_BETTER_MATCH preserved."""
    gstr_records = [
        {
            "id": "g_1",
            "invoice_number": "INV/2026/002",
            "invoice_number_normalized": "INV2026002",
            "supplier_gstin": "27AAPFU0939F1ZV",
            "invoice_date": "2026-09-15",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
            "igst_paise": 180000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "INVOICE",
        }
    ]
    pr_records = [
        {
            "id": "p_primary",
            "invoice_number": "INV/2026/002",
            "invoice_number_normalized": "INV2026002",
            "supplier_gstin": "27AAPFU0939F1ZV",
            "invoice_date": "2026-09-15",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
            "igst_paise": 180000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "INVOICE",
        },
        {
            "id": "p_conflicting",
            "invoice_number": "INV/2026/002",
            "invoice_number_normalized": "INV2026002",
            "supplier_gstin": "27AAPFU0939F1ZV",
            "invoice_date": "2026-09-15",
            "taxable_amount_paise": 1200000,  # Conflicting amount
            "total_tax_paise": 216000,
            "igst_paise": 216000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "INVOICE",
        },
    ]

    res = run_bidirectional_reconciliation(gstr_records, pr_records, gstr_period="2026-09-01")

    assert len(res["matched"]) == 1
    assert res["matched"][0]["pr_id"] == "p_primary"
    assert len(res["duplicate_entries"]) == 1
    assert res["duplicate_entries"][0]["reason"] == "PR_CLAIMED_BY_BETTER_MATCH"
    assert len(res["wrongful_itc_risk"]) == 0
