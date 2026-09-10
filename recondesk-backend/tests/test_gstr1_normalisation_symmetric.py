"""Tests verifying symmetric normalisation of SR invoice numbers vs GSTR-1 inum
and credit note numbers vs nt_num at comparison time.
"""

import pytest
from app.services.matcher import normalise_inv_no
from app.matching.generic_matcher import (
    generic_match_pair,
    match_sales_register_to_gstr1,
    SALES_MATCH_CONFIG,
)
from app.routers.gstr1_reconcile import (
    _extract_doc_number,
    _candidate_keys_for_record,
    _build_invoice_index,
)


def test_normalise_inv_no_equivalence():
    """Verify normalise_inv_no matches the TypeScript specification:
    const normaliseInvNo = (s) => String(s ?? '').replace(/[^a-zA-Z0-9]/g, '').toUpperCase()
    """
    assert normalise_inv_no("INV/2025-26/001") == "INV202526001"
    assert normalise_inv_no("202526001") == "202526001"
    assert normalise_inv_no("cn/2025-26/042") == "CN202526042"
    assert normalise_inv_no("CN202526042") == "CN202526042"
    assert normalise_inv_no(None) == ""
    assert normalise_inv_no("") == ""
    assert normalise_inv_no("  INV - 999  ") == "INV999"


def test_extract_doc_number():
    """Verify document number extraction across parser field variations."""
    # GSTR-1 B2B invoice with inum
    g1_inv = {"inum": "INV/2025-26/001", "invoice_number": "INV2025261"}
    assert _extract_doc_number(g1_inv) == "INV/2025-26/001"

    # GSTR-1 CDNR credit note with nt_num
    g1_cn = {"nt_num": "CN/2025-26/002", "invoice_number": "CN2025262"}
    assert _extract_doc_number(g1_cn) == "CN/2025-26/002"

    # SR record with invoice_number_raw
    sr_rec = {
        "invoice_number_raw": "INV/2025-26/001",
        "invoice_number": "2025261",
        "invoice_number_normalized": "2025261",
    }
    assert _extract_doc_number(sr_rec) == "INV/2025-26/001"


def test_candidate_keys_and_index_symmetry():
    """Verify candidate keys resolve both prefix-containing and prefix-stripped forms."""
    # GSTR-1 record with inum="202526001"
    g1_rec = {
        "inum": "202526001",
        "invoice_number_raw": "202526001",
        "recipient_gstin": "27AAPFU0939F1ZV",
    }
    keys_g1 = _candidate_keys_for_record(g1_rec)
    assert "202526001" in keys_g1

    # SR record with raw="INV/2025-26/001"
    sr_rec = {
        "invoice_number_raw": "INV/2025-26/001",
        "invoice_number": "2025261",
        "gstin": "27AAPFU0939F1ZV",
    }
    keys_sr = _candidate_keys_for_record(sr_rec)
    assert "INV202526001" in keys_sr
    assert "202526001" in keys_sr  # Prefix-stripped core key

    # Indexing GSTR-1 allows SR to find GSTR-1 candidate in O(1)
    index = _build_invoice_index([g1_rec])
    cands = []
    for k in keys_sr:
        for c in index.get(k, []):
            if c not in cands:
                cands.append(c)
    assert len(cands) == 1
    assert cands[0]["inum"] == "202526001"


def test_sales_register_to_gstr1_symmetric_match():
    """End-to-end match of SR row against GSTR-1 inum with different formats."""
    sr = {
        "id": "sr_1",
        "gstin": "27AAPFU0939F1ZV",
        "recipient_name": "Acme Corp",
        "invoice_number": "2025261",
        "invoice_number_raw": "INV/2025-26/001",
        "invoice_number_normalized": "2025261",
        "invoice_date": "2026-05-10",
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
        "igst_paise": 18000,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
    }
    g1 = {
        "id": "g1_1",
        "recipient_gstin": "27AAPFU0939F1ZV",
        "recipient_name": "Acme Corp",
        "inum": "202526001",
        "invoice_number_raw": "202526001",
        "invoice_number": "202526001",
        "invoice_number_normalized": "202526001",
        "invoice_date": "2026-05-10",
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
        "igst_paise": 18000,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
    }

    result = match_sales_register_to_gstr1(sr, [g1])
    assert result is not None
    assert result.matched is True
    assert result.level in (1, 2)
    assert result.requires_human_review is False

    # Stored values are untouched
    assert sr["invoice_number_raw"] == "INV/2025-26/001"
    assert g1["inum"] == "202526001"


def test_credit_note_symmetric_match():
    """End-to-end match of SR credit note row against GSTR-1 CDNR nt_num."""
    sr_cn = {
        "id": "sr_cn_1",
        "gstin": "27AAPFU0939F1ZV",
        "recipient_name": "Acme Corp",
        "invoice_number": "CN202526001",
        "invoice_number_raw": "CN/2025-26/001",
        "credit_note_number": "CN/2025-26/001",
        "invoice_date": "2026-05-10",
        "taxable_amount_paise": 50000,
        "total_tax_paise": 9000,
        "igst_paise": 9000,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
    }
    g1_cdnr = {
        "id": "g1_cdnr_1",
        "recipient_gstin": "27AAPFU0939F1ZV",
        "recipient_name": "Acme Corp",
        "nt_num": "CN202526001",
        "invoice_number_raw": "CN202526001",
        "invoice_number": "CN202526001",
        "invoice_number_normalized": "CN202526001",
        "invoice_date": "2026-05-10",
        "taxable_amount_paise": 50000,
        "total_tax_paise": 9000,
        "igst_paise": 9000,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
    }

    result = generic_match_pair(sr_cn, g1_cdnr, SALES_MATCH_CONFIG)
    assert result.matched is True
    assert result.level in (1, 2)
    assert result.requires_human_review is False

    # Stored values are untouched
    assert sr_cn["invoice_number_raw"] == "CN/2025-26/001"
    assert g1_cdnr["nt_num"] == "CN202526001"
