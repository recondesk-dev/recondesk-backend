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


def test_fiscal_series_invoices_not_misclassified_as_notes():
    """Verify that invoices with series prefixes like DR/..., CR/..., DN/..., CN/... are parsed as INVOICE."""
    df = pd.DataFrame([
        {
            "GSTIN": "27TGMMX1218P9Z3",
            "Invoice No": "DR/2025-3256",
            "Date": "2026-09-21",
            "Taxable Value": 112157.26,
            "CGST": 6729.44,
            "SGST": 6729.44,
            "Total Amount": 125616.14,
        },
        {
            "GSTIN": "33RXCBI1148Y3ZP",
            "Invoice No": "CR/2026-2999",
            "Date": "2026-08-18",
            "Taxable Value": 467372.65,
            "IGST": 84127.08,
            "Total Amount": 551499.73,
        },
        {
            "GSTIN": "33MPOWK1297N2Z6",
            "Invoice No": "DN/2025-7769",
            "Date": "2026-05-22",
            "Taxable Value": 406413.71,
            "IGST": 73154.47,
            "Total Amount": 479568.18,
        },
        {
            "GSTIN": "08CZGUR9795K5ZJ",
            "Invoice No": "CN/2025-8433",
            "Date": "2026-08-10",
            "Taxable Value": 269231.47,
            "IGST": 13461.57,
            "Total Amount": 282693.04,
        },
    ])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    content = buf.getvalue()

    result = parse_purchase_register(content, "purchase_register.xlsx")
    assert result["skipped_rows"] == 0
    assert len(result["records"]) == 4

    for r in result["records"]:
        assert r["invoice_type"] == "INVOICE", f"Expected INVOICE for {r['invoice_number']}, got {r['invoice_type']}"
        assert r["is_credit_note"] is False
        assert r["is_debit_note"] is False
        assert r["taxable_amount_paise"] > 0


def test_note_in_b2b_routed_to_review_required():
    """Verify that credit/debit notes misfiled in B2B table are linked and routed to Review Required."""
    from app.services.matcher import match_gstr_to_pr

    # 1. DBN in B2B table -> Review Required (DOC_TYPE_NOTE_IN_B2B)
    gstr_dbn = {
        "id": "gstr_1",
        "supplier_gstin": "36HTUAB6544W8ZK",
        "invoice_number": "DBN20261488",
        "invoice_number_raw": "DBN/2026-1488",
        "invoice_date": "2026-04-15",
        "taxable_amount_paise": 28683078,
        "total_tax_paise": 5162954,
        "section": "b2b",
        "doc_type": "INVOICE",
    }
    pr_dbn = {
        "id": "pr_1",
        "supplier_gstin": "36HTUAB6544W8ZK",
        "invoice_number": "DBN20261488",
        "invoice_number_raw": "DBN/2026-1488",
        "invoice_date": "2026-04-15",
        "taxable_amount_paise": 28683078,
        "total_tax_paise": 5162954,
        "doc_type": "INVOICE",
    }
    res = match_gstr_to_pr(gstr_dbn, [pr_dbn])
    assert res is not None
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.review_reason == "DOC_TYPE_NOTE_IN_B2B"

    # 2. CBN in B2B table -> Review Required (DOC_TYPE_NOTE_IN_B2B)
    gstr_cbn = {
        "id": "gstr_2",
        "supplier_gstin": "33IHTTJ8007S9ZA",
        "invoice_number": "CBN20251489",
        "invoice_number_raw": "CBN/2025-1489",
        "invoice_date": "2026-07-07",
        "taxable_amount_paise": 33574409,
        "total_tax_paise": 4028929,
        "section": "b2b",
        "doc_type": "INVOICE",
    }
    pr_cbn = {
        "id": "pr_2",
        "supplier_gstin": "33IHTTJ8007S9ZA",
        "invoice_number": "CBN20251489",
        "invoice_number_raw": "CBN/2025-1489",
        "invoice_date": "2026-07-07",
        "taxable_amount_paise": 33574409,
        "total_tax_paise": 4028929,
        "doc_type": "INVOICE",
    }
    res_cbn = match_gstr_to_pr(gstr_cbn, [pr_cbn])
    assert res_cbn is not None
    assert res_cbn.matched is True
    assert res_cbn.requires_human_review is True
    assert res_cbn.review_reason == "DOC_TYPE_NOTE_IN_B2B"

    # 3. Regular fiscal series like CR/2026-2999 must remain clean L1 match
    gstr_cr = {
        "id": "gstr_3",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "CR20262999",
        "invoice_number_raw": "CR/2026-2999",
        "invoice_date": "2026-05-15",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "section": "b2b",
        "doc_type": "INVOICE",
    }
    pr_cr = {
        "id": "pr_3",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "CR20262999",
        "invoice_number_raw": "CR/2026-2999",
        "invoice_date": "2026-05-15",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "doc_type": "INVOICE",
    }
    res_cr = match_gstr_to_pr(gstr_cr, [pr_cr])
    assert res_cr is not None
    assert res_cr.matched is True
    assert res_cr.requires_human_review is False
    assert res_cr.level == 1

