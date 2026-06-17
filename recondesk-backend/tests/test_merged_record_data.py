"""Merged reconcile row data exposes rupee display keys for the results UI."""

from app.routers.reconciliation_api import (
    _enrich_reconcile_display_fields,
    _merged_record_data,
)


def test_merged_record_data_maps_gstr_paise_to_display_fields():
    rd = {"supplier_gstin_norm": "27ABCDE1234F1Z0"}
    matcher = {
        "supplier_gstin": "27ABCDE1234F1Z0",
        "invoice_number_normalized": "INV001",
        "invoice_date": "2024-04-01",
        "taxable_amount_paise": 1_000_000,
        "igst_paise": 180_000,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "total_tax_paise": 180_000,
    }
    out = _merged_record_data(rd, matcher)
    assert out["taxable_amount"] == 10_000.0
    assert out["Taxable Amount"] == 10_000.0
    assert out["igst"] == 1_800.0
    assert out["IGST"] == 1_800.0
    assert out["cgst"] == 0.0
    assert out["sgst"] == 0.0


def test_enrich_preserves_existing_human_readable_values():
    merged = {
        "taxable_amount_paise": 1_000_000,
        "Taxable Amount": "9999",
    }
    out = _enrich_reconcile_display_fields(merged)
    assert out["Taxable Amount"] == "9999"
    assert out["taxable_amount"] == 10_000.0
