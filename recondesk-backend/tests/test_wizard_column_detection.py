"""Wizard PR column detection must match purchase_register_parser mapping."""

import pandas as pd

from app.services.reconciliation_import_wizard.wizard_service import (
    _wizard_columns_from_dataframe,
)


def _field_map(rows: list[dict]) -> dict[str, str | None]:
    return {
        str(r["standard_field"]): r.get("detected_column")
        for r in rows
    }


def test_adversarial_pr_prefers_supplier_gstin_over_client():
    """Regression: substring 'gstin' must not map Client GSTIN before Supplier GSTIN."""
    df = pd.DataFrame(
        columns=[
            "Client GSTIN",
            "Return Period",
            "Supplier GSTIN",
            "Supplier Name",
            "Document Type",
            "Invoice Number",
            "Invoice Date",
            "Taxable Value",
            "IGST",
            "CGST",
            "SGST",
        ]
    )
    mapping = _field_map(_wizard_columns_from_dataframe(df))
    assert mapping["gstin"] == "Supplier GSTIN"
    assert mapping["supplier_name"] == "Supplier Name"
    assert mapping["taxable_value"] == "Taxable Value"
    assert mapping["invoice_number"] == "Invoice Number"
    assert mapping["invoice_date"] == "Invoice Date"
    assert mapping["total_tax"] is None


def test_tally_style_headers_still_detect():
    df = pd.DataFrame(
        columns=[
            "Supplier GSTIN",
            "Invoice No",
            "Invoice Date",
            "Taxable Value",
            "IGST Amount",
            "Grand Total",
        ]
    )
    mapping = _field_map(_wizard_columns_from_dataframe(df))
    assert mapping["gstin"] == "Supplier GSTIN"
    assert mapping["invoice_number"] == "Invoice No"
    assert mapping["invoice_date"] == "Invoice Date"
    assert mapping["taxable_value"] == "Taxable Value"
