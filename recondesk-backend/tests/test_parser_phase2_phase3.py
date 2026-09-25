import io
import pandas as pd
import pytest

from app.parsers.purchase_register_parser import parse_purchase_register
from app.parsers.sales_register_parser import parse_sales_register
from app.services.normalizer import normalize_amount


def test_parentheses_negative_with_currency():
    """Verify normalize_amount handles accounting negative format with currency symbols."""
    res1 = normalize_amount("(Rs. 5,000.00)")
    assert res1.value == -500000
    assert "parentheses_negative" in res1.notes

    res2 = normalize_amount("(₹ 12,345.50)")
    assert res2.value == -1234550
    assert "parentheses_negative" in res2.notes

    res3 = normalize_amount("Rs. (1,500)")
    assert res3.value == -150000
    assert "parentheses_negative" in res3.notes


def test_credit_note_positive_amount_in_purchase_register():
    """ERP exports with credit notes having positive values must NOT be rejected."""
    df = pd.DataFrame([
        {
            "GSTIN": "27AABCU9603R1ZM",
            "Invoice No": "CN-999",
            "Date": "2026-05-15",
            "Taxable Value": 10000,
            "IGST": 1800,
            "Total Amount": 11800,
        },
        {
            "GSTIN": "27AABCU9603R1ZM",
            "Invoice No": "CRN-888",
            "Date": "2026-05-16",
            "Taxable Value": 5000,
            "IGST": 900,
            "Total Amount": 5900,
        }
    ])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    content = buf.getvalue()

    result = parse_purchase_register(content, "credit_notes.xlsx")
    assert result["skipped_rows"] == 0
    assert len(result["records"]) == 2

    r0 = result["records"][0]
    assert r0["invoice_type"] == "CREDIT_NOTE"
    assert r0["is_credit_note"] is True
    # Amounts should be signed negative for credit notes in PR
    assert r0["taxable_amount_paise"] == -1000000
    assert r0["igst_paise"] == -180000

    r1 = result["records"][1]
    assert r1["invoice_type"] == "CREDIT_NOTE"
    assert r1["is_credit_note"] is True
    assert r1["taxable_amount_paise"] == -500000


def test_negative_amount_auto_promoted_to_credit_note():
    """Invoices with negative amounts in a combined register should be auto-classified as CREDIT_NOTE."""
    df = pd.DataFrame([
        {
            "GSTIN": "27AABCU9603R1ZM",
            "Invoice No": "INV-001",
            "Date": "2026-05-15",
            "Taxable Value": 50000,
            "IGST": 9000,
            "Total Amount": 59000,
        },
        {
            "GSTIN": "27AABCU9603R1ZM",
            "Invoice No": "INV-002",
            "Date": "2026-05-18",
            "Taxable Value": -10000,
            "IGST": -1800,
            "Total Amount": -11800,
        }
    ])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    content = buf.getvalue()

    result = parse_purchase_register(content, "combined_register.xlsx")
    assert result["skipped_rows"] == 0
    assert len(result["records"]) == 2

    inv = result["records"][0]
    assert inv["invoice_type"] == "INVOICE"
    assert inv["is_credit_note"] is False
    assert inv["taxable_amount_paise"] == 5000000

    cn = result["records"][1]
    assert cn["invoice_type"] == "CREDIT_NOTE"
    assert cn["is_credit_note"] is True
    assert cn["taxable_amount_paise"] == -1000000


def test_debit_note_drn_classification():
    """Invoices starting with DRN or DR prefix should be classified as DEBIT_NOTE."""
    df = pd.DataFrame([
        {
            "GSTIN": "27AABCU9603R1ZM",
            "Invoice No": "DRN-101",
            "Date": "2026-05-20",
            "Taxable Value": 15000,
            "IGST": 2700,
            "Total Amount": 17700,
        }
    ])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    content = buf.getvalue()

    result = parse_purchase_register(content, "debit_note.xlsx")
    assert result["skipped_rows"] == 0
    rec = result["records"][0]
    assert rec["invoice_type"] == "DEBIT_NOTE"
    assert rec["is_debit_note"] is True


def test_expanded_column_aliases_purchase_register():
    """Verify that varied ERP column headers are accurately auto-mapped."""
    df = pd.DataFrame([
        {
            "Party TIN": "27AABCU9603R1ZM",
            "Vch Num": "BILL/2026/05",
            "Doc Date": "15-05-2026",
            "Assessable Value (Rs.)": 20000,
            "Integrated GST": 3600,
            "Bill Amt": 23600,
            "Account Name": "ACME Industrial Supplies",
            "Reverse Charge Flag": "No",
        }
    ])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    content = buf.getvalue()

    result = parse_purchase_register(content, "erp_export.xlsx")
    assert result["skipped_rows"] == 0
    assert len(result["records"]) == 1
    rec = result["records"][0]
    assert rec["gstin"] == "27AABCU9603R1ZM"
    assert rec["invoice_number"] == "BILL/2026/05"
    assert rec["invoice_date"] == "2026-05-15"
    assert rec["taxable_amount_paise"] == 2000000
    assert rec["igst_paise"] == 360000
    assert rec["total_amount_paise"] == 2360000
    assert rec["supplier_name"] == "ACME Industrial Supplies"


def test_expanded_column_aliases_sales_register():
    """Verify sales register ERP headers auto-map correctly."""
    df = pd.DataFrame([
        {
            "Buyer GST No": "27AABCU9603R1ZM",
            "Sale Inv No": "SAL-0045",
            "Entry Date": "10/05/2026",
            "Net Sales": 40000,
            "IGST Amt": 7200,
            "Invoice Total Amount": 47200,
            "Client Name": "Reliance Retail Ltd",
        }
    ])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    content = buf.getvalue()

    result = parse_sales_register(content, "sales_export.xlsx")
    assert result["skipped_rows"] == 0
    assert len(result["records"]) == 1
    rec = result["records"][0]
    assert rec["gstin"] == "27AABCU9603R1ZM"
    assert rec["invoice_number"] == "SAL45"
    assert rec["invoice_number_raw"] == "SAL-0045"
    assert rec["taxable_amount_paise"] == 4000000
    assert rec["igst_paise"] == 720000
    assert rec["recipient_name"] == "Reliance Retail Ltd"


def test_accounting_footer_row_skipped():
    """Verify that ledger footer rows (Carried Forward, Closing Balance) are skipped cleanly."""
    df = pd.DataFrame([
        {
            "GSTIN": "27AABCU9603R1ZM",
            "Invoice No": "INV-001",
            "Date": "2026-05-15",
            "Taxable Value": 50000,
            "IGST": 9000,
            "Total Amount": 59000,
        },
        {
            "GSTIN": "Carried Forward",
            "Invoice No": "",
            "Date": "",
            "Taxable Value": 50000,
            "IGST": 9000,
            "Total Amount": 59000,
        },
        {
            "GSTIN": "Closing Balance",
            "Invoice No": "",
            "Date": "",
            "Taxable Value": 50000,
            "IGST": 9000,
            "Total Amount": 59000,
        }
    ])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    content = buf.getvalue()

    result = parse_purchase_register(content, "ledger_with_footers.xlsx")
    # Only 1 real invoice row; 2 summary/footer rows skipped
    assert len(result["records"]) == 1
    assert result["records"][0]["invoice_number"] == "INV-001"
    assert result["skip_reasons"].get("total_or_summary_row", 0) == 2
