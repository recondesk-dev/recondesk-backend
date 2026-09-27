"""Tests for Problem 15: Damaged & Truncated Files Resilient Recovery."""

import io
import pandas as pd
import pytest

from app.parsers.resilient_recovery import (
    sanitize_csv_bytes,
    infer_columns_by_content,
)
from app.parsers.csv_parser import parse_csv
from app.parsers.purchase_register_parser import parse_purchase_register
from app.parsers.sales_register_parser import parse_sales_register


class TestSanitizeCsvBytes:
    def test_strips_null_bytes(self):
        corrupted = b"Invoice No,Date,GSTIN,Amount\x00\nINV-001\x00,2024-01-15\x00,27AABCU9603R1ZM,1000.00\n"
        clean, warnings = sanitize_csv_bytes(corrupted)
        assert "\x00" not in clean
        assert "INV-001,2024-01-15,27AABCU9603R1ZM,1000.00" in clean
        assert any("null bytes" in w.lower() for w in warnings)

    def test_repairs_unclosed_trailing_quote(self):
        # File was truncated mid-download, leaving an unclosed double-quote on the last cell
        corrupted = (
            b'Invoice No,Date,GSTIN,Amount,Note\n'
            b'INV-100,2024-01-10,27AABCU9603R1ZM,500.00,"Normal note"\n'
            b'INV-101,2024-01-11,27AABCU9603R1ZM,600.00,"Cut off here'
        )
        clean, warnings = sanitize_csv_bytes(corrupted)
        assert clean.count('"') % 2 == 0
        assert any("unclosed quote" in w.lower() or "unmatched quote" in w.lower() for w in warnings)

    def test_discards_truncated_trailing_partial_line(self):
        # Last line was cut off mid-stream with missing fields
        corrupted = (
            b"Invoice No,Date,GSTIN,Taxable,CGST,SGST,Total\n"
            b"INV-1,2024-01-10,27AABCU9603R1ZM,1000,90,90,1180\n"
            b"INV-2,2024-01-11,27AABCU9603R1ZM,2000,180,180,2360\n"
            b"INV-3,2024-01-1"  # Cut off mid-date
        )
        clean, warnings = sanitize_csv_bytes(corrupted)
        lines = [line.strip() for line in clean.split("\n") if line.strip()]
        assert len(lines) == 3  # Header + 2 valid rows
        assert "INV-3" not in clean
        assert any("truncated partial trailing line" in w.lower() for w in warnings)

    def test_latin1_encoding_fallback(self):
        # Byte 0xE9 is é in Latin-1, invalid in strict UTF-8
        latin1_bytes = "Invoice No,Date,GSTIN,Supplier,Amount\nINV-01,2024-01-10,27AABCU9603R1ZM,Caf\xe9 Supplies,150.00\n".encode("latin-1")
        clean, warnings = sanitize_csv_bytes(latin1_bytes)
        assert "Café Supplies" in clean or "Caf" in clean


class TestInferColumnsByContent:
    def test_headerless_dataframe_detected_at_row_zero(self):
        data = [
            ["INV-001", "2024-01-15", "27AABCU9603R1ZM", "Acme Corp", "10000.00", "900.00", "900.00", "11800.00"],
            ["INV-002", "2024-01-16", "27AABCU9603R1ZM", "Acme Corp", "20000.00", "1800.00", "1800.00", "23600.00"],
            ["INV-003", "2024-01-17", "29BABCU9603R1ZN", "Beta Corp", "5000.00", "450.00", "450.00", "5900.00"],
        ]
        df = pd.DataFrame(data)
        mapping, start_row = infer_columns_by_content(df, mode="purchase")

        assert start_row == 0  # Row 0 was already valid data
        assert mapping["invoice_number"] == "0"
        assert mapping["invoice_date"] == "1"
        assert mapping["gstin"] == "2"
        assert mapping["supplier_name"] == "3"
        assert mapping["taxable_amount"] == "4"
        assert mapping["cgst"] == "5"
        assert mapping["sgst"] == "6"
        assert mapping["total_amount"] == "7"

    def test_corrupted_header_row_detected_at_row_one(self):
        data = [
            ["???", "###", "UNKNOWN_COL", "BAD_LABEL", "N/A", "N/A", "N/A", "N/A"],  # Corrupted headers
            ["INV-101", "2024-02-01", "27AABCU9603R1ZM", "Delta Ltd", "15000.00", "1350.00", "1350.00", "17700.00"],
            ["INV-102", "2024-02-02", "27AABCU9603R1ZM", "Delta Ltd", "25000.00", "2250.00", "2250.00", "29500.00"],
        ]
        df = pd.DataFrame(data)
        mapping, start_row = infer_columns_by_content(df, mode="purchase")

        assert start_row == 1  # Row 0 was corrupted header, data starts at 1
        assert mapping["invoice_number"] == "0"
        assert mapping["invoice_date"] == "1"
        assert mapping["gstin"] == "2"
        assert mapping["taxable_amount"] == "4"
        assert mapping["cgst"] == "5"
        assert mapping["sgst"] == "6"
        assert mapping["total_amount"] == "7"

    def test_client_gstin_filter(self):
        # Client GSTIN is repeated across all rows in Col 2, vendor GSTIN in Col 3
        client_gstin = "27AABCU9603R1ZM"
        data = [
            ["INV-201", "2024-03-01", client_gstin, "33AABCU9603R1ZP", "8000.00"],
            ["INV-202", "2024-03-02", client_gstin, "33AABCU9603R1ZP", "12000.00"],
            ["INV-203", "2024-03-03", client_gstin, "07AABCU9603R1ZQ", "15000.00"],
        ]
        df = pd.DataFrame(data)
        mapping, start_row = infer_columns_by_content(df, client_gstin=client_gstin, mode="purchase")

        assert mapping["gstin"] == "3"  # Selected vendor GSTIN, ignored client's own


class TestCsvParserResilience:
    def test_parse_csv_with_null_bytes_and_unclosed_quote(self):
        raw_csv = (
            b"invoice_no,invoice_date,amount\x00\n"
            b"INV-1,2024-01-01,1000\n"
            b'INV-2,2024-01-02,"2000\n'  # Unclosed quote
        )
        df = parse_csv(raw_csv)
        assert len(df) == 2
        assert "invoice_no" in df.columns
        assert df["invoice_no"].tolist() == ["INV-1", "INV-2"]


class TestPurchaseRegisterResilience:
    def test_parse_pr_damaged_csv_with_null_bytes_and_truncated_tail(self):
        csv_bytes = (
            b"Invoice Number,Invoice Date,Supplier GSTIN,Supplier Name,Taxable Value,CGST,SGST,Total\x00 Amount\n"
            b"INV-901\x00,2024-01-10,27AABCU9603R1ZM,Alpha Supplies,10000.00,900.00,900.00,11800.00\n"
            b"INV-902,2024-01-11\x00,27AABCU9603R1ZM,Alpha Supplies,20000.00,1800.00,1800.00,23600.00\n"
            b"INV-903,2024-01-12,27AAB"  # Truncated partial line
        )
        res = parse_purchase_register(csv_bytes, "damaged_purchases.csv")
        assert res["success"] is True
        assert len(res["records"]) == 2
        assert res["records"][0]["invoice_number"] == "INV-901"
        assert res["records"][1]["invoice_number"] == "INV-902"
        assert any("null bytes" in w.lower() for w in res["warnings"])
        assert any("truncated" in w.lower() for w in res["warnings"])

    def test_parse_pr_headerless_csv(self):
        # CSV without any header row (starts directly with invoice records)
        csv_bytes = (
            b"INV-001,2024-01-15,27AABCU9603R1ZM,Acme Corp,10000.00,900.00,900.00,11800.00\n"
            b"INV-002,2024-01-16,27AABCU9603R1ZM,Acme Corp,20000.00,1800.00,1800.00,23600.00\n"
            b"INV-003,2024-01-17,29BABCU9603R1ZN,Beta Corp,5000.00,450.00,450.00,5900.00\n"
        )
        res = parse_purchase_register(csv_bytes, "headerless_purchases.csv")
        assert res["success"] is True
        assert len(res["records"]) == 3
        inv_nums = [r["invoice_number"] for r in res["records"]]
        assert inv_nums == ["INV-001", "INV-002", "INV-003"]
        assert res["records"][0]["gstin"] == "27AABCU9603R1ZM"
        assert res["records"][0]["taxable_amount_paise"] == 1000000

    def test_parse_pr_garbled_headers_csv(self):
        # CSV with unrecognized headers
        csv_bytes = (
            b"COL_ALPHA,COL_BETA,COL_GAMMA,COL_DELTA,COL_EPSILON,COL_ZETA,COL_ETA,COL_THETA\n"
            b"INV-101,2024-02-01,27AABCU9603R1ZM,Delta Ltd,15000.00,1350.00,1350.00,17700.00\n"
            b"INV-102,2024-02-02,27AABCU9603R1ZM,Delta Ltd,25000.00,2250.00,2250.00,29500.00\n"
        )
        res = parse_purchase_register(csv_bytes, "garbled_headers.csv")
        assert res["success"] is True
        assert len(res["records"]) == 2
        assert res["records"][0]["invoice_number"] == "INV-101"
        assert res["records"][1]["invoice_number"] == "INV-102"
        assert res["records"][0]["taxable_amount_paise"] == 1500000


class TestSalesRegisterResilience:
    def test_parse_sr_headerless_csv(self):
        csv_bytes = (
            b"SINV-501,2024-03-01,27AABCU9603R1ZM,Buyer One,12000.00,1080.00,1080.00,14160.00\n"
            b"SINV-502,2024-03-02,27AABCU9603R1ZM,Buyer One,18000.00,1620.00,1620.00,21240.00\n"
        )
        res = parse_sales_register(csv_bytes, "headerless_sales.csv")
        assert res["success"] is True
        assert len(res["records"]) == 2
        assert res["records"][0]["invoice_number_raw"] == "SINV-501"
        assert res["records"][0]["invoice_number"] == "SINV501"
        assert res["records"][1]["invoice_number_raw"] == "SINV-502"
        assert res["records"][0]["gstin"] == "27AABCU9603R1ZM"
        assert res["records"][0]["taxable_amount_paise"] == 1200000

    def test_parse_sr_damaged_null_bytes(self):
        csv_bytes = (
            b"Invoice Number,Invoice Date,Customer GSTIN,Customer Name,Taxable Value,Total Amount\x00\n"
            b"SINV-701\x00,2024-03-10,27AABCU9603R1ZM,Customer A,30000.00,35400.00\n"
            b"SINV-702,2024-03-11,27AABCU9603R1ZM,Customer A,40000.00,47200.00\n"
        )
        res = parse_sales_register(csv_bytes, "damaged_sales.csv")
        assert res["success"] is True
        assert len(res["records"]) == 2
        assert res["records"][0]["invoice_number_raw"] == "SINV-701"
        assert res["records"][0]["invoice_number"] == "SINV701"
        assert any("null bytes" in w.lower() for w in res["warnings"])
