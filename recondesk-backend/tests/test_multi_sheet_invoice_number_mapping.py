"""Regression: multi-sheet PR workbooks with different invoice-number headers.

Each sheet must map its own invoice column independently so every sheet's
rows land with a populated ``invoice_number`` — not just sheets whose header
matches the first sheet's naming convention.
"""

from __future__ import annotations

import io

import pandas as pd
import pytest

from app.parsers.purchase_register_parser import parse_purchase_register


def _xlsx_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)
    return buf.getvalue()


@pytest.fixture
def multi_sheet_different_invoice_headers() -> bytes:
    """Three sheets, three genuine invoice-number column names."""
    tally = pd.DataFrame(
        {
            "Date": ["01-04-2026", "02-04-2026"],
            "Particulars": ["Alpha Traders", "Beta Corp"],
            "Vch Type": ["Purchase", "Purchase"],
            "Vch No.": ["VCH-1001", "VCH-1002"],
            "GSTIN/UIN": ["27AABCU9603R1ZM", "29AABCU9603R1ZN"],
            "Taxable Value": [1000.0, 2000.0],
            "Central Tax": [90.0, 0.0],
            "State Tax": [90.0, 0.0],
            "Integrated Tax": [0.0, 360.0],
        }
    )
    busy = pd.DataFrame(
        {
            "Voucher Date": ["03-04-2026"],
            "Party Name": ["Gamma LLC"],
            "GSTIN No": ["07AABCU9603R1ZO"],
            "Bill No": ["BILL-9001"],
            "Taxable Amt": [1500.0],
            "CGST Amt": [135.0],
            "SGST Amt": [135.0],
            "IGST Amt": [0.0],
        }
    )
    manual = pd.DataFrame(
        {
            "Invoice Date": ["04-04-2026"],
            "Supplier Name": ["Delta Pvt Ltd"],
            "GSTIN": ["19AABCU9603R1ZP"],
            "Invoice Number": ["INV-7001"],
            "Taxable Amount": [3000.0],
            "CGST": [270.0],
            "SGST": [270.0],
            "IGST": [0.0],
            "Total Invoice Value": [3540.0],
        }
    )
    return _xlsx_bytes(
        {
            "Tally Export": tally,
            "Busy Export": busy,
            "Manual Excel": manual,
        }
    )


def test_multi_sheet_different_invoice_headers_all_populated(
    multi_sheet_different_invoice_headers: bytes,
):
    result = parse_purchase_register(
        multi_sheet_different_invoice_headers, "messy_pr.xlsx"
    )

    assert result["success"] is True
    used = {s["sheet"]: s for s in result.get("sheets_used") or []}
    assert set(used) == {"Tally Export", "Busy Export", "Manual Excel"}

    for sheet_name in ("Tally Export", "Busy Export", "Manual Excel"):
        assert "invoice_number" in used[sheet_name]["mapped_fields"], (
            f"{sheet_name} missing invoice_number in mapped_fields: "
            f"{used[sheet_name]['mapped_fields']}"
        )
        assert used[sheet_name].get("has_invoice_number") is True

    records = result["records"]
    assert len(records) == 4  # 2 tally + 1 busy + 1 manual

    by_sheet: dict[str, list[dict]] = {}
    for rec in records:
        by_sheet.setdefault(rec.get("source_sheet") or "?", []).append(rec)

    assert len(by_sheet["Tally Export"]) == 2
    assert len(by_sheet["Busy Export"]) == 1
    assert len(by_sheet["Manual Excel"]) == 1

    for sheet_name, rows in by_sheet.items():
        for rec in rows:
            inv = rec.get("invoice_number") or rec.get("invoice_number_normalized")
            assert inv and str(inv).strip(), (
                f"{sheet_name} row {rec.get('row_number')} has empty invoice_number: {rec}"
            )

    tally_raw = {
        str(r.get("invoice_number") or "") for r in by_sheet["Tally Export"]
    }
    assert any("1001" in v for v in tally_raw)
    assert any("1002" in v for v in tally_raw)
    assert any(
        "9001" in str(r.get("invoice_number") or "")
        for r in by_sheet["Busy Export"]
    )
    assert any(
        "7001" in str(r.get("invoice_number") or "")
        for r in by_sheet["Manual Excel"]
    )

    assert int(result.get("missing_invoice_number_count") or 0) == 0


def test_sheet_without_invoice_column_surfaces_missing_count():
    """A sheet with GSTIN but no invoice-like header must not fail silently."""
    ok_sheet = pd.DataFrame(
        {
            "Invoice Date": ["01-04-2026"],
            "GSTIN": ["27AABCU9603R1ZM"],
            "Invoice Number": ["INV-1"],
            "Taxable Amount": [1000.0],
            "CGST": [90.0],
            "SGST": [90.0],
            "IGST": [0.0],
        }
    )
    bad_sheet = pd.DataFrame(
        {
            "Date": ["02-04-2026"],
            "GSTIN": ["29AABCU9603R1ZN"],
            "Taxable Value": [2000.0],
            "Central Tax": [0.0],
            "State Tax": [0.0],
            "Integrated Tax": [360.0],
            # deliberately no invoice / bill / vch column
        }
    )
    raw = _xlsx_bytes({"Good": ok_sheet, "No Invoice Col": bad_sheet})
    result = parse_purchase_register(raw, "partial.xlsx")
    assert result["success"] is True
    assert int(result.get("missing_invoice_number_count") or 0) >= 1
    warns = " ".join(result.get("warnings") or []).lower()
    assert "invoice number" in warns
    assert "no invoice col" in warns or "missing invoice" in warns


def test_supplier_invoice_preferred_over_voucher_number():
    """When both Vch No and Supplier Invoice No exist, Supplier Invoice No must win."""
    from app.parsers.purchase_register_parser import detect_column_mapping
    df = pd.DataFrame(
        {
            "Date": ["01-04-2026"],
            "Particulars": ["Alpha Traders"],
            "Vch No.": ["1"],
            "Supplier Invoice No.": ["INV-REAL-999"],
            "GSTIN/UIN": ["27AABCU9603R1ZM"],
            "Taxable Value": [1000.0],
            "Central Tax": [90.0],
            "State Tax": [90.0],
            "Integrated Tax": [0.0],
        }
    )
    mapping = detect_column_mapping(df)
    assert mapping["invoice_number"] == "Supplier Invoice No."

