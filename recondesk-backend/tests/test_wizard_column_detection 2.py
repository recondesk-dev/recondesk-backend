"""Wizard PR column detection must match purchase_register_parser mapping."""

import io

import openpyxl
import pandas as pd

from app.services.reconciliation_import_wizard.wizard_service import (
    _read_pr_dataframe,
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


def test_read_pr_dataframe_detects_headers_in_noisy_excel():
    """Verify _read_pr_dataframe finds the correct header row in a CA-style
    export with 3 noise rows before the actual headers (row 4)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Purchase Register"
    # Noise rows
    ws.append(["Monthly Purchase Register Export"])
    ws.append(["Client: ACME Corp", "Period: Sep 2025"])
    ws.append([])
    # Actual headers at row 4
    ws.append([
        "Supplier GSTIN", "Invoice Number", "Invoice Date",
        "Taxable Value", "Total Tax", "Supplier Name",
    ])
    # Data rows
    ws.append(["29AAACR5055K1ZK", "INV-001", "2025-09-10", "10000", "1800", "Acme Ltd"])
    ws.append(["29BBBBR5055K1ZK", "INV-002", "2025-09-11", "20000", "3600", "Beta Ltd"])

    buf = io.BytesIO()
    wb.save(buf)
    raw_bytes = buf.getvalue()

    df = _read_pr_dataframe(raw_bytes, "noisy_export.xlsx")

    # The returned DataFrame must use the actual header row, not the noise rows
    assert "Supplier GSTIN" in df.columns, f"Got columns: {list(df.columns)}"
    assert "Invoice Number" in df.columns
    assert "Taxable Value" in df.columns
    # Noise rows must NOT appear as data
    assert len(df) == 2, f"Expected 2 data rows, got {len(df)}"
    assert df.iloc[0]["Supplier GSTIN"] == "29AAACR5055K1ZK"



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
