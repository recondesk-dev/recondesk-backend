"""Tests for multi-sheet Purchase Register upload handling.

Covers:
1. Purchase Register + Control sheet (control sheet ignored as non-transactional)
2. Purchase Register + Summary sheet (summary sheet ignored as non-transactional)
3. Two compatible Purchase Register sheets (auto-combined with multi-sheet warning)
4. Two incompatible transactional sheets (differing schemas require user confirmation & sheet selection)
5. is_transactional_pr_sheet schema detection unit checks
6. Wizard sheet selection check generation & gating
"""
from __future__ import annotations

import io
import openpyxl
import pytest

from app.parsers.purchase_register_parser import (
    are_sheet_schemas_compatible,
    is_transactional_pr_sheet,
    parse_purchase_register,
)
from app.services.reconciliation_import_wizard.wizard_service import (
    build_multi_sheet_combine_check,
    build_sheet_selection_check,
    MULTI_SHEET_COMBINE_CHECK_ID,
    SHEET_SELECTION_REQUIRED_CHECK_ID,
)

GSTIN = "27AABCU9603R1ZM"


def _create_workbook_bytes(sheets_data: dict[str, list[list]]) -> bytes:
    """Helper to create an in-memory xlsx file with multiple sheets."""
    wb = openpyxl.Workbook()
    first = True
    for title, rows in sheets_data.items():
        if first:
            ws = wb.active
            ws.title = title
            first = False
        else:
            ws = wb.create_sheet(title)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. Purchase Register + Control sheet
# ---------------------------------------------------------------------------

def test_purchase_register_plus_control_sheet():
    """Control sheet (e.g. Run30 Control) must be ignored and not combined."""
    data = {
        "Purchase Register": [
            ["GSTIN", "Invoice Number", "Invoice Date", "Taxable Value", "CGST", "SGST", "Total Value"],
            [GSTIN, "INV-101", "2024-03-01", 10000, 900, 900, 11800],
            [GSTIN, "INV-102", "2024-03-05", 20000, 1800, 1800, 23600],
        ],
        "Run30 Control": [
            ["Run ID", "Execution Date", "Status", "Total Records", "User"],
            ["RUN-30-001", "2024-03-10", "SUCCESS", 2, "admin@example.com"],
        ],
    }
    file_bytes = _create_workbook_bytes(data)

    result = parse_purchase_register(file_bytes, "pr_with_control.xlsx")

    assert result["success"] is True
    assert len(result["records"]) == 2
    assert result["total_rows"] == 2

    # Only Purchase Register should be in sheets_used
    assert len(result["sheets_used"]) == 1
    assert result["sheets_used"][0]["sheet"] == "Purchase Register"

    # Control sheet must be listed in ignored_sheets
    assert "Run30 Control" in result["ignored_sheets"]

    # Ignored sheet message must be present in warnings
    assert any("Ignored non-transactional sheet: Run30 Control" in w for w in result["warnings"])

    # Must NOT emit multiple-sheet combine warning since only 1 sheet was used
    assert not any("Combined" in w for w in result["warnings"])

    # Sheet selection is NOT required
    assert result["requires_sheet_selection"] is False


# ---------------------------------------------------------------------------
# 2. Purchase Register + Summary sheet
# ---------------------------------------------------------------------------

def test_purchase_register_plus_summary_sheet():
    """Summary sheet must be ignored and not combined into transactions."""
    data = {
        "Purchases": [
            ["GSTIN", "Bill No", "Bill Date", "Taxable Amt", "IGST", "Total Value"],
            [GSTIN, "INV-201", "2024-03-02", 50000, 9000, 59000],
        ],
        "Summary": [
            ["Month", "Total Invoices", "Taxable Turnover", "Tax Paid"],
            ["March 2024", 1, 50000, 9000],
        ],
    }
    file_bytes = _create_workbook_bytes(data)

    result = parse_purchase_register(file_bytes, "pr_with_summary.xlsx")

    assert result["success"] is True
    assert len(result["records"]) == 1
    assert len(result["sheets_used"]) == 1
    assert result["sheets_used"][0]["sheet"] == "Purchases"

    # Summary sheet must be in ignored_sheets
    assert "Summary" in result["ignored_sheets"]
    assert any("Ignored non-transactional sheet: Summary" in w for w in result["warnings"])

    # Must NOT emit multiple-sheet combine warning
    assert not any("Combined" in w for w in result["warnings"])
    assert result["requires_sheet_selection"] is False


# ---------------------------------------------------------------------------
# 3. Two compatible Purchase Register sheets
# ---------------------------------------------------------------------------

def test_two_compatible_purchase_register_sheets():
    """Two PR sheets with compatible schemas should auto-combine with warning."""
    data = {
        "PR April": [
            ["GSTIN", "Invoice Number", "Invoice Date", "Taxable Value", "CGST", "SGST", "Total Value"],
            [GSTIN, "INV-APR-01", "2024-04-10", 10000, 900, 900, 11800],
        ],
        "PR May": [
            ["GSTIN", "Invoice Number", "Invoice Date", "Taxable Value", "CGST", "SGST", "Total Value"],
            [GSTIN, "INV-MAY-01", "2024-05-12", 15000, 1350, 1350, 17700],
        ],
    }
    file_bytes = _create_workbook_bytes(data)

    result = parse_purchase_register(file_bytes, "pr_apr_may.xlsx")

    assert result["success"] is True
    assert len(result["records"]) == 2
    assert len(result["sheets_used"]) == 2

    used_names = [s["sheet"] for s in result["sheets_used"]]
    assert "PR April" in used_names
    assert "PR May" in used_names

    # Multi-sheet combine warning must be present and specify only sheets actually combined
    combine_warnings = [w for w in result["warnings"] if "Combined 2 sheets into one purchase register" in w]
    assert len(combine_warnings) == 1
    assert "PR April" in combine_warnings[0]
    assert "PR May" in combine_warnings[0]

    # No ignored sheets
    assert len(result["ignored_sheets"]) == 0
    assert result["requires_sheet_selection"] is False


# ---------------------------------------------------------------------------
# 4. Two incompatible transactional sheets
# ---------------------------------------------------------------------------

def test_two_incompatible_transactional_sheets():
    """Two transactional sheets with incompatible schemas must require user selection."""
    data = {
        "PR Domestic": [
            ["GSTIN", "Invoice Number", "Invoice Date", "Taxable Value", "CGST", "SGST"],
            [GSTIN, "INV-DOM-01", "2024-03-01", 10000, 900, 900],
        ],
        "PR Imports": [
            ["Supplier Name", "Invoice Number", "Invoice Date", "Total Amount"],
            ["Overseas Trading LLC", "INV-IMP-01", "2024-03-02", 75000],
        ],
    }
    file_bytes = _create_workbook_bytes(data)

    # 1. Parse without selection: must detect incompatible schemas and flag sheet selection
    result = parse_purchase_register(file_bytes, "two_incompatible.xlsx")

    assert result["success"] is True
    assert result["requires_sheet_selection"] is True
    assert result["candidate_sheets"] == ["PR Domestic", "PR Imports"]

    # Incompatible sheets must NOT be auto-combined
    assert len(result["sheets_used"]) == 1
    assert result["sheets_used"][0]["sheet"] == "PR Domestic"
    assert len(result["records"]) == 1

    # Warning for differing schemas must be present
    assert any("Multiple valid transactional sheets with differing schemas" in w for w in result["warnings"])

    # 2. Parse with explicit sheet selection: user chooses PR Imports
    result_selected = parse_purchase_register(
        file_bytes, "two_incompatible.xlsx", selected_sheets=["PR Imports"]
    )
    assert result_selected["success"] is True
    assert result_selected["requires_sheet_selection"] is False
    assert len(result_selected["sheets_used"]) == 1
    assert result_selected["sheets_used"][0]["sheet"] == "PR Imports"
    assert result_selected["records"][0]["supplier_name"] == "Overseas Trading LLC"
    assert result_selected["records"][0]["invoice_number"] == "INV-IMP-01"


# ---------------------------------------------------------------------------
# 5. Schema detection unit checks (is_transactional_pr_sheet)
# ---------------------------------------------------------------------------

def test_is_transactional_pr_sheet():
    # Valid mapping
    valid_mapping = {
        "gstin": "GSTIN",
        "invoice_number": "Invoice No",
        "invoice_date": "Date",
        "taxable_amount": "Taxable Value",
        "cgst": "CGST",
    }
    is_valid, reason = is_transactional_pr_sheet(valid_mapping)
    assert is_valid is True
    assert reason == "valid_pr_schema"

    # Missing invoice / document number
    no_inv = dict(valid_mapping)
    del no_inv["invoice_number"]
    is_valid, reason = is_transactional_pr_sheet(no_inv)
    assert is_valid is False
    assert reason == "missing_invoice_number"

    # Minimal transactional sheet with GSTIN + invoice_number (valid)
    minimal_gstin_inv = {
        "gstin": "GSTIN",
        "invoice_number": "Invoice No",
    }
    is_valid, reason = is_transactional_pr_sheet(minimal_gstin_inv)
    assert is_valid is True
    assert reason == "valid_pr_schema"

    # Minimal transactional sheet with invoice_number + amount (valid)
    minimal_inv_amt = {
        "invoice_number": "Invoice No",
        "taxable_amount": "Taxable Value",
    }
    is_valid, reason = is_transactional_pr_sheet(minimal_inv_amt)
    assert is_valid is True
    assert reason == "valid_pr_schema"

    # Non-transactional: only invoice number without supplier or amount (e.g. control sheet with ref no)
    only_inv = {
        "invoice_number": "Invoice No",
        "invoice_date": "Date",
    }
    is_valid, reason = is_transactional_pr_sheet(only_inv)
    assert is_valid is False
    assert reason == "missing_supplier_or_amount"


# ---------------------------------------------------------------------------
# 6. Schema compatibility unit checks (are_sheet_schemas_compatible)
# ---------------------------------------------------------------------------

def test_are_sheet_schemas_compatible():
    schema_a = {
        "gstin": "GSTIN",
        "invoice_number": "Invoice No",
        "invoice_date": "Invoice Date",
        "taxable_amount": "Taxable Value",
        "cgst": "CGST",
        "sgst": "SGST",
    }
    schema_b = {
        "gstin": "Party GSTIN",
        "invoice_number": "Bill No",
        "invoice_date": "Bill Date",
        "taxable_amount": "Base Amount",
        "igst": "IGST",
    }
    # Both have GSTIN, invoice_number, date, taxable_amount, and tax columns -> compatible
    assert are_sheet_schemas_compatible(schema_a, schema_b) is True

    # Incompatible: Schema C has no GSTIN (only supplier name)
    schema_c = {
        "supplier_name": "Vendor",
        "invoice_number": "Bill No",
        "invoice_date": "Bill Date",
        "total_amount": "Total Amount",
    }
    assert are_sheet_schemas_compatible(schema_a, schema_c) is False


# ---------------------------------------------------------------------------
# 7. Wizard check builders
# ---------------------------------------------------------------------------

def test_wizard_multi_sheet_and_selection_checks():
    # Single sheet used: build_multi_sheet_combine_check returns None
    assert build_multi_sheet_combine_check([{"sheet": "PR", "records": 10}]) is None

    # Two sheets used: returns check requiring acknowledgment
    check = build_multi_sheet_combine_check([
        {"sheet": "PR 1", "records": 10},
        {"sheet": "PR 2", "records": 20},
    ])
    assert check is not None
    assert check["id"] == MULTI_SHEET_COMBINE_CHECK_ID
    assert check["requires_acknowledgment"] is True
    assert "PR 1 (10)" in check["detail"]
    assert "PR 2 (20)" in check["detail"]

    # Sheet selection check: None when requires_sheet_selection is False
    assert build_sheet_selection_check(False, ["PR 1", "PR 2"]) is None

    # Sheet selection check: returns blocking check when requires_sheet_selection is True
    sel_check = build_sheet_selection_check(True, ["PR Domestic", "PR Imports"])
    assert sel_check is not None
    assert sel_check["id"] == SHEET_SELECTION_REQUIRED_CHECK_ID
    assert sel_check["requires_acknowledgment"] is True
    assert "PR Domestic" in sel_check["detail"]
    assert "PR Imports" in sel_check["detail"]
