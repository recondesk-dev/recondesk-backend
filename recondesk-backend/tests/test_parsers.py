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
