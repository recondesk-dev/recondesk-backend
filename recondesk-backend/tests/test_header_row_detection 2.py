"""
test_header_row_detection.py
──────────────────────────────────────────────────────────────────────────────
Tests for robust Excel header row detection.
Verifies that the parser scans the first 20 rows and correctly identifies
the header row even if it's preceded by title rows or blank rows.
"""

import io

import openpyxl
import pandas as pd

from app.parsers.purchase_register_parser import parse_purchase_register


def build_noisy_header_excel() -> bytes:
    """
    Build an Excel file with noise before the actual header.
    Row 1: Title text
    Row 2: Client name/period
    Row 3: Blank
    Row 4: The actual headers
    Row 5+: Data
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Purchase Register"
    
    # Row 1: Title
    ws.append(["Monthly Purchase Register Export"])
    # Row 2: Metadata
    ws.append(["Client: ACME Corp", "Period: Sep 2025"])
    # Row 3: Blank
    ws.append([])
    
    # Row 4: Actual Headers
    headers = [
        "Supplier GSTIN",
        "Invoice Number",
        "Invoice Date",
        "Taxable Value",
        "Total Tax",
        "Supplier Name",
        "Payment Status",
        "Amount Paid",
    ]
    ws.append(headers)
    
    # Row 5: Data
    ws.append([
        "29AAACR5055K1ZK",
        "INV-001",
        "2025-09-10",
        10000,
        1800,
        "Acme Supplier",
        "Unpaid",
        0,
    ])
    
    # Row 6: Data with some blanks
    ws.append([
        "29AAACR5055K1Z1",
        "INV-002",
        "2025-09-15",
        20000,
        3600,
        "Another Supplier",
        "Paid",
        23600,
    ])
    
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_fallback_excel() -> bytes:
    """
    Build an Excel file where no row meets the threshold of 3 standard fields,
    but Row 1 has GSTIN and Invoice Number (score = 2).
    This ensures fallback logic preserves legacy behavior.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    
    # Row 1: Partial Headers (Score 2)
    ws.append(["Supplier GSTIN", "Invoice Number", "Random Data 1", "Random Data 2"])
    
    # Row 2: Data
    ws.append(["29AAACR5055K1ZK", "INV-001", "Foo", "Bar"])
    
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_robust_header_detection_finds_row_4():
    """Verify that the parser correctly skips noise rows and uses row 4 as headers."""
    file_bytes = build_noisy_header_excel()
    
    result = parse_purchase_register(file_bytes, "noisy_export.xlsx")
    
    assert result["success"] is True, f"Parsing failed: {result.get('errors')}"
    
    # Check that we extracted exactly 2 valid records (from Row 5 and 6)
    assert result["total_rows"] == 2
    assert result["valid_rows"] == 2
    
    # Verify the first record's data is correctly mapped
    rec1 = result["records"][0]
    assert rec1["gstin"] == "29AAACR5055K1ZK"
    assert rec1["invoice_number"] == "INV1"
    assert rec1["invoice_date"] == "2025-09-10"
    assert rec1["taxable_amount_paise"] == 1_000_000  # 10000 * 100
    assert rec1["total_tax_paise"] == 180_000         # 1800 * 100
    assert rec1["supplier_name"] == "Acme Supplier"


def test_fallback_logic_uses_row_0_when_threshold_not_met():
    """Verify that if max score < 3, it falls back to row 0 if it has some matches."""
    file_bytes = build_fallback_excel()
    
    result = parse_purchase_register(file_bytes, "fallback.xlsx")
    
    assert result["success"] is True, f"Parsing failed: {result.get('errors')}"
    
    # Check that we extracted the record
    assert result["total_rows"] == 1
    assert result["valid_rows"] == 1
    
    rec1 = result["records"][0]
    assert rec1["gstin"] == "29AAACR5055K1ZK"
    assert rec1["invoice_number"] == "INV1"
