"""Tests for advanced parser improvements:
- Semicolon-separated, pipe-separated, and tab-separated CSVs
- Multi-row header combination (hierarchical / parent-child headers)
- Merged cell context preservation (supplier name / GSTIN merged once for multiple invoices)
- Multi-line invoice items with merged header cells
- Hindi / Devanagari column headings in CSV and Excel
"""

import io
import pandas as pd
import pytest

from app.parsers.csv_parser import parse_csv
from app.parsers.purchase_register_parser import parse_purchase_register
from app.parsers.sales_register_parser import parse_sales_register


def test_semicolon_delimited_csv_parsing():
    """Verify CSVs with semicolon (;) delimiter auto-detect and parse accurately."""
    csv_content = (
        "Supplier GSTIN;Invoice Number;Invoice Date;Taxable Value;CGST;SGST\n"
        "27AABCT1332L1ZV;INV-001;15-05-2026;10000;900;900\n"
        "27AABCT1332L1ZV;INV-002;16-05-2026;20000;1800;1800\n"
    ).encode("utf-8")

    # Test basic csv_parser
    df = parse_csv(csv_content)
    assert len(df) == 2
    assert "invoice_number" in df.columns
    assert "taxable_value" in df.columns

    # Test purchase register parser
    res = parse_purchase_register(csv_content, "purchases_semicolon.csv")
    assert res["success"] is True
    assert len(res["records"]) == 2
    assert res["records"][0]["invoice_number"] == "INV-001"
    assert res["records"][0]["taxable_amount_paise"] == 1000000
    assert res["records"][1]["invoice_number"] == "INV-002"
    assert res["records"][1]["taxable_amount_paise"] == 2000000


def test_pipe_delimited_csv_parsing():
    """Verify pipe-delimited (|) CSV exports auto-detect and parse."""
    csv_content = (
        "Supplier GSTIN|Invoice Number|Invoice Date|Taxable Value|IGST\n"
        "29ABCDE1234F1Z5|PIPE-99|2026-05-20|50000|9000\n"
    ).encode("utf-8")

    res = parse_purchase_register(csv_content, "pipe_export.csv")
    assert res["success"] is True
    assert len(res["records"]) == 1
    assert res["records"][0]["invoice_number"] == "PIPE-99"
    assert res["records"][0]["igst_paise"] == 900000


def test_hindi_devanagari_headers_csv():
    """Verify Hindi / Devanagari column headings in CSV parse into canonical fields."""
    csv_content = (
        "जीएसटी नंबर,चालान संख्या,चालान दिनांक,कर योग्य मूल्य,केंद्रीय कर,राज्य कर\n"
        "27AABCT1332L1ZV,INV-HINDI-1,10-05-2026,15000,1350,1350\n"
    ).encode("utf-8")

    res = parse_purchase_register(csv_content, "hindi_purchases.csv")
    assert res["success"] is True
    assert len(res["records"]) == 1
    r = res["records"][0]
    assert r["gstin"] == "27AABCT1332L1ZV"
    assert r["invoice_number"] == "INV-HINDI-1"
    assert r["taxable_amount_paise"] == 1500000
    assert r["cgst_paise"] == 135000
    assert r["sgst_paise"] == 135000


def test_multi_row_headers_excel():
    """Verify multi-row headers (Row 0 category, Row 1 specific fields) combine cleanly."""
    raw_data = [
        ["Party Details", "Party Details", "Invoice Details", "Invoice Details", "Tax Amounts", "Tax Amounts", "Tax Amounts"],
        ["GSTIN", "Name", "Number", "Date", "Taxable Value", "CGST", "SGST"],
        ["27AABCT1332L1ZV", "Alpha Traders", "INV-101", "2026-05-01", "10000", "900", "900"],
        ["27AABCT1332L1ZV", "Alpha Traders", "INV-102", "2026-05-02", "20000", "1800", "1800"],
    ]
    df = pd.DataFrame(raw_data)
    buf = io.BytesIO()
    df.to_excel(buf, header=False, index=False)
    content = buf.getvalue()

    res = parse_purchase_register(content, "multi_header.xlsx")
    assert res["success"] is True
    assert len(res["records"]) == 2
    assert res["records"][0]["invoice_number"] == "INV-101"
    assert res["records"][0]["taxable_amount_paise"] == 1000000
    assert res["records"][0]["cgst_paise"] == 90000
    assert res["records"][0]["sgst_paise"] == 90000
    assert res["records"][1]["invoice_number"] == "INV-102"


def test_input_tax_subheaders_combination():
    """Verify 'Input Tax' parent header above 'CGST' and 'SGST' stitches properly."""
    raw_data = [
        ["Supplier GSTIN", "Invoice Number", "Invoice Date", "Taxable Amount", "Input Tax", "Input Tax"],
        ["", "", "", "", "CGST", "SGST"],
        ["27AABCT1332L1ZV", "INV-201", "2026-05-10", "5000", "450", "450"],
    ]
    df = pd.DataFrame(raw_data)
    buf = io.BytesIO()
    df.to_excel(buf, header=False, index=False)
    content = buf.getvalue()

    res = parse_purchase_register(content, "input_tax_headers.xlsx")
    assert res["success"] is True
    assert len(res["records"]) == 1
    r = res["records"][0]
    assert r["invoice_number"] == "INV-201"
    assert r["taxable_amount_paise"] == 500000
    assert r["cgst_paise"] == 45000
    assert r["sgst_paise"] == 45000


def test_merged_cells_supplier_written_once_for_multiple_invoices():
    """Verify supplier name & GSTIN entered once in merged cell is preserved across invoices."""
    raw_data = [
        ["Supplier Name", "Supplier GSTIN", "Invoice No", "Date", "Taxable Value", "Total Amount"],
        # Row 1: Explicit supplier & GSTIN
        ["Tata Steel Ltd", "27AAACT2727Q1ZW", "INV-TS-01", "2026-05-01", 100000, 118000],
        # Rows 2-3: Merged cell blanks for Supplier Name and GSTIN
        [None, None, "INV-TS-02", "2026-05-02", 200000, 236000],
        [None, None, "INV-TS-03", "2026-05-03", 300000, 354000],
        # Row 4: New supplier
        ["Reliance Retail", "27AAAAP1234A1ZP", "INV-RR-01", "2026-05-04", 50000, 59000],
        # Row 5: Merged cell blank for Reliance
        [None, None, "INV-RR-02", "2026-05-05", 70000, 82600],
    ]
    df = pd.DataFrame(raw_data[1:], columns=raw_data[0])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    content = buf.getvalue()

    res = parse_purchase_register(content, "merged_suppliers.xlsx")
    assert res["success"] is True
    assert len(res["records"]) == 5

    # Check Tata Steel invoices
    assert res["records"][0]["invoice_number"] == "INV-TS-01"
    assert res["records"][0]["gstin"] == "27AAACT2727Q1ZW"
    assert res["records"][0]["supplier_name"] == "Tata Steel Ltd"

    assert res["records"][1]["invoice_number"] == "INV-TS-02"
    assert res["records"][1]["gstin"] == "27AAACT2727Q1ZW"
    assert res["records"][1]["supplier_name"] == "Tata Steel Ltd"

    assert res["records"][2]["invoice_number"] == "INV-TS-03"
    assert res["records"][2]["gstin"] == "27AAACT2727Q1ZW"
    assert res["records"][2]["supplier_name"] == "Tata Steel Ltd"

    # Check Reliance invoices
    assert res["records"][3]["invoice_number"] == "INV-RR-01"
    assert res["records"][3]["gstin"] == "27AAAAP1234A1ZP"
    assert res["records"][3]["supplier_name"] == "Reliance Retail"

    assert res["records"][4]["invoice_number"] == "INV-RR-02"
    assert res["records"][4]["gstin"] == "27AAAAP1234A1ZP"
    assert res["records"][4]["supplier_name"] == "Reliance Retail"


def test_merged_cells_multiline_invoice_item_rows():
    """Verify multiline invoice with merged header cells preserves invoice number and supplier."""
    raw_data = [
        ["Supplier GSTIN", "Invoice No", "Date", "Taxable Value", "CGST", "SGST"],
        # Line 1 of INV-MULTI-1
        ["27AABCT1332L1ZV", "INV-MULTI-1", "2026-05-15", 10000, 900, 900],
        # Line 2 of INV-MULTI-1 (blank GSTIN, Inv No, Date because cells were merged in Excel)
        [None, None, None, 5000, 250, 250],
        # Line 1 of INV-MULTI-2
        ["29ABCDE1234F1Z5", "INV-MULTI-2", "2026-05-16", 20000, 1800, 1800],
    ]
    df = pd.DataFrame(raw_data[1:], columns=raw_data[0])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    content = buf.getvalue()

    res = parse_purchase_register(content, "multiline_merged.xlsx")
    assert res["success"] is True
    assert len(res["records"]) == 3

    # Line 1 & Line 2 share INV-MULTI-1
    assert res["records"][0]["invoice_number"] == "INV-MULTI-1"
    assert res["records"][0]["gstin"] == "27AABCT1332L1ZV"
    assert res["records"][0]["taxable_amount_paise"] == 1000000

    assert res["records"][1]["invoice_number"] == "INV-MULTI-1"
    assert res["records"][1]["gstin"] == "27AABCT1332L1ZV"
    assert res["records"][1]["taxable_amount_paise"] == 500000

    assert res["records"][2]["invoice_number"] == "INV-MULTI-2"
    assert res["records"][2]["gstin"] == "29ABCDE1234F1Z5"


def test_sales_register_semicolon_and_multi_header():
    """Verify Sales Register also supports semicolon CSVs and multi-row headers."""
    csv_content = (
        "Customer GSTIN;Invoice Number;Invoice Date;Taxable Value;CGST;SGST\n"
        "27AABCT1332L1ZV;SR-001;15-05-2026;10000;900;900\n"
    ).encode("utf-8")
    sr_res = parse_sales_register(csv_content, "sales_semi.csv")
    assert sr_res["success"] is True
    assert len(sr_res["records"]) == 1
    assert sr_res["records"][0]["invoice_number_raw"] == "SR-001"

    # Multi-row headers in Sales Register
    raw_data = [
        ["Party Details", "Party Details", "Invoice Details", "Invoice Details", "Tax Amounts", "Tax Amounts"],
        ["GSTIN", "Name", "Number", "Date", "Taxable Value", "Integrated Tax"],
        ["27AABCT1332L1ZV", "Client Corp", "SR-100", "2026-05-20", 50000, 9000],
    ]
    df = pd.DataFrame(raw_data)
    buf = io.BytesIO()
    df.to_excel(buf, header=False, index=False)
    sr_excel_res = parse_sales_register(buf.getvalue(), "sales_multi.xlsx")
    assert sr_excel_res["success"] is True
    assert len(sr_excel_res["records"]) == 1
    assert sr_excel_res["records"][0]["invoice_number_raw"] == "SR-100"
    assert sr_excel_res["records"][0]["igst_paise"] == 900000

