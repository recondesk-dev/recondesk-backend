"""Regression tests for Run 24 Duplicate Classification Guards.

Covers:
1. AMOUNT_COLLISION_WRONG_INV:
   - Same vendor GSTIN and identical amounts, but materially different invoice numbers
     (e.g., AMTCOLL/R24/014A vs AMTCOLL/R24/014B).
   - Must NOT be classified as duplicate.
2. ONE_TO_MANY_COLLISION:
   - One GSTR invoice matches a PR row, while surplus PR rows have different invoice
     identities (e.g., OTM/R24/012A vs OTM/R24/012C).
   - Surplus row must NOT be classified as duplicate.
3. DOC_TYPE_COLLISION_TRAP:
   - Identical invoice number and same vendor GSTIN, but incompatible document types
     (e.g., INVOICE vs DEBIT_NOTE).
   - Must NOT be classified as duplicate.
4. TRUE DUPLICATE PRESERVATION:
   - Identical duplicate ERP booking -> DUPLICATE_ENTRY
   - Conflicting amount duplicate ERP booking -> PR_CLAIMED_BY_BETTER_MATCH
"""

import pytest
from app.matching.engine import run_bidirectional_reconciliation


# ── 1. AMOUNT COLLISION WRONG INVOICE ─────────────────────────────────────────


def test_amount_collision_different_invoice_numbers_not_duplicate():
    """Different invoice numbers with identical GSTIN and amounts must NOT be flagged as duplicate."""
    gstr_records = [
        {
            "id": "g_1",
            "invoice_number": "AMTCOLL/R24/014A",
            "invoice_number_normalized": "AMTCOLLR24014A",
            "supplier_gstin": "29XWVSR6221O1ZN",
            "invoice_date": "2026-09-15",
            "taxable_amount_paise": 9457622,
            "total_tax_paise": 1702372,
            "igst_paise": 1702372,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "INVOICE",
        }
    ]
    pr_records = [
        {
            "id": "p_primary",
            "invoice_number": "AMTCOLL/R24/014A",
            "invoice_number_normalized": "AMTCOLLR24014A",
            "supplier_gstin": "29XWVSR6221O1ZN",
            "invoice_date": "2026-09-15",
            "taxable_amount_paise": 9457622,
            "total_tax_paise": 1702372,
            "igst_paise": 1702372,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "INVOICE",
        },
        {
            "id": "p_different_inv",
            "invoice_number": "AMTCOLL/R24/014B",
            "invoice_number_normalized": "AMTCOLLR24014B",
            "supplier_gstin": "29XWVSR6221O1ZN",
            "invoice_date": "2026-09-15",
            "taxable_amount_paise": 9457622,  # Exactly same amounts
            "total_tax_paise": 1702372,
            "igst_paise": 1702372,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "INVOICE",
        },
    ]

    res = run_bidirectional_reconciliation(gstr_records, pr_records)

    assert len(res["matched"]) == 1
    assert res["matched"][0]["pr_id"] == "p_primary"
    # p_different_inv must NOT be classified as duplicate
    assert len(res["duplicate_entries"]) == 0
    assert any(r["id"] == "p_different_inv" for r in res["wrongful_itc_risk"])


# ── 2. ONE-TO-MANY COLLISION ──────────────────────────────────────────────────


def test_one_to_many_surplus_different_invoice_identity_not_duplicate():
    """Surplus rows with distinct invoice identities in 1-to-many context must NOT be duplicate."""
    gstr_records = [
        {
            "id": "g_1",
            "invoice_number": "OTM/R24/012A",
            "invoice_number_normalized": "OTMR24012A",
            "supplier_gstin": "09CNYTE6032Z1ZD",
            "invoice_date": "2026-09-15",
            "taxable_amount_paise": 9132432,
            "total_tax_paise": 1643838,
            "igst_paise": 1643838,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "INVOICE",
        }
    ]
    pr_records = [
        {
            "id": "p_matched",
            "invoice_number": "OTM/R24/012A",
            "invoice_number_normalized": "OTMR24012A",
            "supplier_gstin": "09CNYTE6032Z1ZD",
            "invoice_date": "2026-09-15",
            "taxable_amount_paise": 9132432,
            "total_tax_paise": 1643838,
            "igst_paise": 1643838,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "INVOICE",
        },
        {
            "id": "p_surplus_otm",
            "invoice_number": "OTM/R24/012C",
            "invoice_number_normalized": "OTMR24012C",
            "supplier_gstin": "09CNYTE6032Z1ZD",
            "invoice_date": "2026-09-16",
            "taxable_amount_paise": 9182432,  # Close amount (~0.5% drift)
            "total_tax_paise": 1652838,
            "igst_paise": 1652838,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "INVOICE",
        },
    ]

    res = run_bidirectional_reconciliation(gstr_records, pr_records)

    assert len(res["matched"]) == 1
    assert res["matched"][0]["pr_id"] == "p_matched"
    assert len(res["duplicate_entries"]) == 0
    assert any(r["id"] == "p_surplus_otm" for r in res["wrongful_itc_risk"])


# ── 3. DOC TYPE COLLISION TRAP ────────────────────────────────────────────────


def test_doc_type_collision_invoice_vs_debit_note_not_duplicate():
    """Invoice and Debit Note sharing the same invoice number are distinct document types, NOT duplicates."""
    gstr_records = [
        {
            "id": "g_inv",
            "invoice_number": "DOCCOLL/R24/010",
            "invoice_number_normalized": "DOCCOLLR24010",
            "supplier_gstin": "09WDKXE5250R1ZY",
            "invoice_date": "2026-09-10",
            "taxable_amount_paise": 3710254,
            "total_tax_paise": 445230,
            "igst_paise": 445230,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "INVOICE",
        }
    ]
    pr_records = [
        {
            "id": "p_inv",
            "invoice_number": "DOCCOLL/R24/010",
            "invoice_number_normalized": "DOCCOLLR24010",
            "supplier_gstin": "09WDKXE5250R1ZY",
            "invoice_date": "2026-09-10",
            "taxable_amount_paise": 14841016,
            "total_tax_paise": 1780922,
            "igst_paise": 1780922,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "INVOICE",
        },
        {
            "id": "p_dn",
            "invoice_number": "DOCCOLL/R24/010",
            "invoice_number_normalized": "DOCCOLLR24010",
            "supplier_gstin": "09WDKXE5250R1ZY",
            "invoice_date": "2026-09-12",
            "taxable_amount_paise": 3710254,
            "total_tax_paise": 445230,
            "igst_paise": 445230,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "DEBIT_NOTE",
        },
    ]

    res = run_bidirectional_reconciliation(gstr_records, pr_records)

    # Incompatible document types must never be flagged as duplicates of each other
    assert len(res["duplicate_entries"]) == 0
    # Debit note should NOT be consumed as a duplicate
    dup_ids = [d["id"] for d in res["duplicate_entries"]]
    assert "p_dn" not in dup_ids


def test_doc_type_collision_invoice_vs_credit_note_not_duplicate():
    """Invoice and Credit Note sharing the same number must NOT be duplicate."""
    gstr_records = [
        {
            "id": "g_inv",
            "invoice_number": "INV-1001",
            "invoice_number_normalized": "INV1001",
            "supplier_gstin": "27AAPFU0939F1ZV",
            "invoice_date": "2026-09-10",
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
            "id": "p_inv",
            "invoice_number": "INV-1001",
            "invoice_number_normalized": "INV1001",
            "supplier_gstin": "27AAPFU0939F1ZV",
            "invoice_date": "2026-09-10",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
            "igst_paise": 180000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "INVOICE",
        },
        {
            "id": "p_cn",
            "invoice_number": "INV-1001",
            "invoice_number_normalized": "INV1001",
            "supplier_gstin": "27AAPFU0939F1ZV",
            "invoice_date": "2026-09-10",
            "taxable_amount_paise": -1000000,
            "total_tax_paise": -180000,
            "igst_paise": -180000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "CREDIT_NOTE",
        },
    ]

    res = run_bidirectional_reconciliation(gstr_records, pr_records)
    assert len(res["duplicate_entries"]) == 0


# ── 4. TRUE DUPLICATE PRESERVATION ───────────────────────────────────────────


def test_true_identical_duplicate_pr_booking_is_duplicate_entry():
    """True identical duplicate PR rows (same GSTIN, inv, doc_type, amount) -> DUPLICATE_ENTRY."""
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

    res = run_bidirectional_reconciliation(gstr_records, pr_records)

    assert len(res["matched"]) == 1
    assert len(res["duplicate_entries"]) == 1
    assert res["duplicate_entries"][0]["reason"] == "DUPLICATE_ENTRY"
    assert len(res["wrongful_itc_risk"]) == 0


def test_true_conflicting_amount_duplicate_is_claimed_by_better_match():
    """True duplicate PR booking with conflicting amount -> PR_CLAIMED_BY_BETTER_MATCH."""
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
            "taxable_amount_paise": 1200000,  # 20% conflicting amount
            "total_tax_paise": 216000,
            "igst_paise": 216000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "doc_type": "INVOICE",
        },
    ]

    res = run_bidirectional_reconciliation(gstr_records, pr_records)

    assert len(res["matched"]) == 1
    assert res["matched"][0]["pr_id"] == "p_primary"
    assert len(res["duplicate_entries"]) == 1
    assert res["duplicate_entries"][0]["reason"] == "PR_CLAIMED_BY_BETTER_MATCH"
    assert len(res["wrongful_itc_risk"]) == 0
