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


def test_normalize_date_native_types():
    from app.services.normalizer import normalize_date
    from datetime import date, datetime
    import pandas as pd

    assert normalize_date(date(2024, 4, 5)).value == date(2024, 4, 5)
    assert normalize_date(datetime(2024, 4, 5, 10, 30)).value == date(2024, 4, 5)
    assert normalize_date(pd.Timestamp("2024-04-05 15:45:00")).value == date(2024, 4, 5)


def test_tally_and_busy_excel_parsing():
    import io, openpyxl
    from app.parsers.purchase_register_parser import parse_purchase_register

    # Tally format: top metadata, header at row 4, data, footer total
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Purchase"
    ws.append(["Company XYZ Limited"])
    ws.append(["GSTIN: 27AABCU9603R1ZX"])
    ws.append(["Date", "Particulars", "Vch Type", "Vch No.", "GSTIN/UIN", "Gross Total", "Taxable Value", "Integrated Tax"])
    ws.append(["05-04-2024", "ABC INFOTECH", "Purchase", "PUR/001", "27AABCU9603R1ZX", 118000, 100000, 18000])
    ws.append(["Total", "", "", "", "", 118000, 100000, 18000])
    bio = io.BytesIO()
    wb.save(bio)

    res = parse_purchase_register(bio.getvalue(), "tally.xlsx")
    assert res["valid_rows"] == 1
    assert res["records"][0]["invoice_number"] == "PUR/001"
    assert res["records"][0]["taxable_amount_paise"] == 10000000


def test_zoho_books_csv_parsing():
    from app.parsers.purchase_register_parser import parse_purchase_register
    zoho_csv = (
        b"Vendor Name,GST Identification Number (GSTIN),Invoice Date,Invoice#,SubTotal,Total,IGST\n"
        b"ALPHA CONSULTING,27AABCU9603R1ZX,2024-04-02,INV-2024-01,150000,177000,27000\n"
    )
    res = parse_purchase_register(zoho_csv, "zoho_bills.csv")
    assert res["valid_rows"] == 1
    assert res["records"][0]["invoice_number"] == "INV-2024-01"
    assert res["records"][0]["gstin"] == "27AABCU9603R1ZX"
    assert res["records"][0]["total_tax_paise"] == 2700000


