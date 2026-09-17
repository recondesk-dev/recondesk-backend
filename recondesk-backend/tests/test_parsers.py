import pytest

from app.parsers.csv_parser import parse_csv
from app.parsers.excel_parser import parse_excel
from app.parsers.file_router import parse_file


CSV_CONTENT = b"Invoice ID,Amount,Date\n001,1000,2024-01-01\n002,2000,2024-01-02\n"


def test_csv_parser_basic():
    df = parse_csv(CSV_CONTENT)
    assert list(df.columns) == ["invoice_id", "amount", "date"]
    assert len(df) == 2


def test_csv_parser_tab_delimited():
    tsv = b"Invoice ID\tAmount\n001\t1000\n002\t2000\n"
    df = parse_csv(tsv)
    assert "invoice_id" in df.columns
    assert len(df) == 2


def test_file_router_csv():
    df = parse_file(CSV_CONTENT, "invoices.csv")
    assert len(df) == 2


def test_file_router_unsupported():
    with pytest.raises(ValueError, match="Unsupported file type"):
        parse_file(b"data", "file.pdf")


def test_purchase_register_credit_note_signed_taxes():
    from app.parsers.purchase_register_parser import parse_purchase_register
    csv_content = (
        b"GSTIN,Invoice Number,Invoice Date,Invoice Type,Taxable Value,IGST,CGST,SGST,Total Tax,Total Amount\n"
        b"27AACCV1726H1ZE,CN-101,2024-04-15,CREDIT_NOTE,1000,0,90,90,180,1180\n"
    )
    res = parse_purchase_register(csv_content, "pr.csv")
    assert len(res["records"]) == 1
    row = res["records"][0]
    assert row["invoice_type"] == "CREDIT_NOTE"
    assert row["taxable_amount_paise"] == -100_000
    assert row["cgst_paise"] == -9_000
    assert row["sgst_paise"] == -9_000
    assert row["total_tax_paise"] == -18_000
    assert row["total_amount_paise"] == -118_000


def test_purchase_register_leading_zeros_preserved():
    from app.parsers.purchase_register_parser import parse_purchase_register
    csv_content = (
        b"GSTIN,Invoice Number,Invoice Date,Taxable Value,Total Tax\n"
        b"27AACCV1726H1ZE,00123,2024-04-15,1000,180\n"
    )
    res = parse_purchase_register(csv_content, "pr.csv")
    assert len(res["records"]) == 1
    row = res["records"][0]
    assert row["invoice_number"] == "00123"
    assert row["invoice_number_normalized"] == "123"


def test_purchase_register_urp_vendor():
    from app.parsers.purchase_register_parser import parse_purchase_register
    csv_content = (
        b"Supplier GSTIN,Supplier Invoice No.,Supplier Invoice Date,Taxable Amount,Total Amount\n"
        b"URP,LTS/MAY26/003,15-05-2026,12000,14160\n"
        b"URP/RCM,LTS/MAY26/004,16-05-2026,10000,11800\n"
    )
    res = parse_purchase_register(csv_content, "pr.csv")
    assert len(res["records"]) == 2
    assert res["records"][0]["gstin"] == "URP"
    assert res["records"][0]["gstin_valid"] is True
    assert res["records"][1]["gstin"] == "URP"
    assert res["records"][1]["gstin_valid"] is True

