"""Tests for Problem 14: Mixed Documents & ZIP Archive Batch Processing."""

import io
import zipfile
import pandas as pd
import pytest

from app.parsers.zip_batch_parser import (
    extract_supported_files_from_zip,
    parse_zip_batch,
    parse_zip_to_dataframe,
)
from app.parsers.purchase_register_parser import parse_purchase_register
from app.parsers.sales_register_parser import parse_sales_register
from app.parsers.file_router import parse_file


def _create_sample_excel_bytes(sheet_name: str, records: list[dict]) -> bytes:
    df = pd.DataFrame(records)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return buf.getvalue()


def _create_sample_csv_bytes(records: list[dict]) -> bytes:
    df = pd.DataFrame(records)
    return df.to_csv(index=False).encode("utf-8")


def test_zip_extraction_filters_junk_and_preserves_valid():
    """Verify ZIP extraction skips __MACOSX, .DS_Store, lock files, and non-tabular items."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # Valid files
        zf.writestr("April_2024.xlsx", _create_sample_excel_bytes("PR", [{"Invoice No": "INV-01", "GSTIN": "27ABCDE1234F1Z5"}]))
        zf.writestr("May_2024.csv", "Invoice No,GSTIN\nINV-02,27ABCDE1234F1Z5")
        # Subfolder file
        zf.writestr("Q2/June_2024.xlsx", _create_sample_excel_bytes("PR", [{"Invoice No": "INV-03", "GSTIN": "27ABCDE1234F1Z5"}]))
        # Junk files to ignore
        zf.writestr("__MACOSX/._April_2024.xlsx", b"junk mac resource fork")
        zf.writestr(".DS_Store", b"junk mac ds store")
        zf.writestr("~$April_2024.xlsx", b"office lock file")
        zf.writestr("Thumbs.db", b"windows thumbs db")
        # Non-tabular file
        zf.writestr("invoice_receipt.pdf", b"%PDF-1.4 dummy pdf bytes")

    extracted, warnings = extract_supported_files_from_zip(buf.getvalue())
    names = [name for name, _ in extracted]

    # Valid files should be present in natural sorted order
    assert names == ["April_2024.xlsx", "May_2024.csv", "Q2/June_2024.xlsx"]
    # Check that non-register file generated a warning
    assert any("Skipped non-register file" in w and "invoice_receipt.pdf" in w for w in warnings)


def test_zip_slip_security():
    """Ensure paths with directory traversal ('..') are rejected."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../etc/passwd.csv", "root,0,0")
        zf.writestr("safe.csv", "Invoice No,GSTIN\nINV-SAFE,27ABCDE1234F1Z5")

    extracted, warnings = extract_supported_files_from_zip(buf.getvalue())
    names = [name for name, _ in extracted]
    assert names == ["safe.csv"]
    assert any("Ignored insecure archive path" in w for w in warnings)


def test_parse_purchase_register_with_zip_archive():
    """Verify parse_purchase_register seamlessly ingests a ZIP of multi-month files."""
    month1 = [
        {"Invoice No": "INV-APR-01", "Invoice Date": "2024-04-10", "GSTIN": "27ABCDE1234F1Z5", "Taxable Value": 10000.0, "IGST": 1800.0},
        {"Invoice No": "INV-APR-02", "Invoice Date": "2024-04-20", "GSTIN": "27ABCDE1234F1Z5", "Taxable Value": 20000.0, "IGST": 3600.0},
    ]
    month2 = [
        {"Invoice No": "INV-MAY-01", "Invoice Date": "2024-05-15", "GSTIN": "29XYZAB1234C1Z9", "Taxable Value": 15000.0, "IGST": 2700.0},
    ]

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("01_April_PR.xlsx", _create_sample_excel_bytes("Purchases", month1))
        zf.writestr("02_May_PR.csv", _create_sample_csv_bytes(month2))

    res = parse_purchase_register(zip_buf.getvalue(), "Q1_Purchases.zip")

    assert res["success"] is True
    records = res["records"]
    assert len(records) == 3

    # Check row 1 from April
    assert records[0]["invoice_number"] == "INV-APR-01"
    assert records[0]["source_file"] == "01_April_PR.xlsx"
    assert records[0]["row_number"] == 1
    assert records[0]["taxable_amount_paise"] == 1000000

    # Check row 2 from April
    assert records[1]["invoice_number"] == "INV-APR-02"
    assert records[1]["source_file"] == "01_April_PR.xlsx"
    assert records[1]["row_number"] == 2

    # Check row 3 from May
    assert records[2]["invoice_number"] == "INV-MAY-01"
    assert records[2]["source_file"] == "02_May_PR.csv"
    assert records[2]["row_number"] == 3
    assert records[2]["taxable_amount_paise"] == 1500000

    # Check aggregated metadata
    assert res["total_rows"] == 3
    assert res["valid_rows"] == 3
    assert res["files_processed"] == 2
    assert "01_April_PR.xlsx" in res["source_files"]
    assert "02_May_PR.csv" in res["source_files"]


def test_parse_sales_register_with_zip_archive():
    """Verify parse_sales_register aggregates multiple files within a ZIP archive."""
    sales_q1 = [
        {"Invoice No": "SALE-01", "Invoice Date": "2024-04-05", "Customer GSTIN": "27ABCDE1234F1Z5", "Taxable Value": 50000.0, "IGST": 9000.0},
    ]
    sales_q2 = [
        {"Invoice No": "SALE-02", "Invoice Date": "2024-05-12", "Customer GSTIN": "27ABCDE1234F1Z5", "Taxable Value": 35000.0, "IGST": 6300.0},
    ]

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("Sales_April.xlsx", _create_sample_excel_bytes("Sales", sales_q1))
        zf.writestr("Sales_May.xlsx", _create_sample_excel_bytes("Sales", sales_q2))

    res = parse_sales_register(zip_buf.getvalue(), "Sales_Q1.zip")

    assert res["success"] is True
    records = res["records"]
    assert records[0]["invoice_number_raw"] == "SALE-01"
    assert records[0]["invoice_number"] == "SALE1"
    assert records[0]["source_file"] == "Sales_April.xlsx"
    assert records[1]["invoice_number_raw"] == "SALE-02"
    assert records[1]["invoice_number"] == "SALE2"
    assert records[1]["source_file"] == "Sales_May.xlsx"
    assert res["files_processed"] == 2


def test_file_router_with_zip_archive():
    """Verify parse_file in file_router concatenates all files into a single DataFrame."""
    f1 = [{"ColA": "Val1", "ColB": 10}]
    f2 = [{"ColA": "Val2", "ColB": 20}]

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("file1.csv", _create_sample_csv_bytes(f1))
        zf.writestr("file2.xlsx", _create_sample_excel_bytes("Sheet1", f2))

    df = parse_file(zip_buf.getvalue(), "batch.zip")
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert list(df["cola"]) == ["Val1", "Val2"]


def test_empty_zip_returns_error_gracefully():
    """Verify an empty ZIP returns an error gracefully without throwing unhandled exceptions."""
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("README.txt", "No spreadsheets here.")

    res = parse_purchase_register(zip_buf.getvalue(), "empty.zip")
    assert res["success"] is False
    assert len(res["records"]) == 0
    assert any("No valid .xlsx, .xls, or .csv" in err for err in res["errors"])
