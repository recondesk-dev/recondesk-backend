"""Tests for DB row → matcher row mapping (GSTR-2B vs purchase register units)."""

from app.services.reconciliation_record_adapter import (
    gstr_db_row_to_matcher_row,
    pr_db_row_to_matcher_row,
)


def test_pr_row_preserves_parser_paise_and_normalizes_invoice():
    row = {
        "id": 1,
        "record_data": {
            "gstin": "27AABCU9603R1ZX",
            "invoice_number_normalized": "INV-2025-001",
            "taxable_amount_paise": 10_000_000,
            "igst_paise": 1_800_000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "total_tax_paise": 1_800_000,
        },
    }
    m = pr_db_row_to_matcher_row(row)
    assert m["invoice_number_normalized"] == "INV2025001"
    assert m["taxable_amount_paise"] == 10_000_000
    assert m["igst_paise"] == 1_800_000
    assert m["total_tax_paise"] == 1_800_000


def test_pr_row_computes_total_tax_from_components_when_field_missing():
    """When record_data has no top-level total_tax_paise, sum the components.

    Mirrors the GSTR adapter so a matched pair does not project total_tax_paise=0
    on the PR side, which would surface a fake "discrepancy" equal to the full
    invoice tax on the Matched tab.
    """
    row = {
        "id": 7,
        "record_data": {
            "gstin": "27AABCU9603R1ZX",
            "invoice_number": "INV5210",
            "taxable_amount_paise": 8_390_898,
            "igst_paise": 1_510_362,
            "cgst_paise": 0,
            "sgst_paise": 0,
            # no total_tax_paise key on purpose
        },
    }
    m = pr_db_row_to_matcher_row(row)
    assert m["total_tax_paise"] == 1_510_362


def test_pr_row_prefers_explicit_total_tax_over_component_sum():
    row = {
        "id": 8,
        "record_data": {
            "gstin": "27AABCU9603R1ZX",
            "invoice_number": "INV9",
            "taxable_amount_paise": 1_000_000,
            "igst_paise": 90_000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "total_tax_paise": 250_000,
        },
    }
    m = pr_db_row_to_matcher_row(row)
    assert m["total_tax_paise"] == 250_000


def test_gstr_row_normalizes_invoice_to_match_matcher():
    row = {
        "id": 2,
        "record_data": {
            "supplier_gstin_norm": "27AABCU9603R1ZX",
            "invoice_number": "inv-9",
            "invoice_date_norm": "2025-01-15",
            "items": [
                {
                    "taxable_value_paise": 1_000_000,
                    "igst_paise": 0,
                    "cgst_paise": 0,
                    "sgst_paise": 0,
                }
            ],
        },
    }
    m = gstr_db_row_to_matcher_row(row)
    assert m["invoice_number_normalized"] == "INV9"
    assert m["taxable_amount_paise"] == 1_000_000

def test_gstr_row_computes_tax_from_top_level_fallback():
    row = {
        "id": 3,
        "record_data": {
            "supplier_gstin_norm": "27AABCU9603R1ZX",
            "invoice_number": "inv-10",
            "invoice_date_norm": "2025-01-16",
            "cgst_paise": 90_000,
            "sgst_paise": 90_000,
            "taxable_value_paise": 1_000_000,
        },
    }
    m = gstr_db_row_to_matcher_row(row)
    assert m["total_tax_paise"] == 180_000

def test_gstr_row_computes_tax_from_invoice_value_difference():
    row = {
        "id": 4,
        "record_data": {
            "supplier_gstin_norm": "27AABCU9603R1ZX",
            "invoice_number": "inv-11",
            "invoice_value_paise": 1_180_000,
            "items": [
                {
                    "taxable_value_paise": 1_000_000,
                }
            ],
        },
    }
    m = gstr_db_row_to_matcher_row(row)
    assert m["taxable_amount_paise"] == 1_000_000
    assert m["total_tax_paise"] == 180_000

def test_gstr_row_prefers_explicit_total_tax_paise():
    row = {
        "id": 5,
        "record_data": {
            "supplier_gstin_norm": "27AABCU9603R1ZX",
            "invoice_number": "inv-12",
            "total_tax_paise": 250_000,
            "taxable_value_paise": 1_000_000,
        },
    }
    m = gstr_db_row_to_matcher_row(row)
    assert m["total_tax_paise"] == 250_000

