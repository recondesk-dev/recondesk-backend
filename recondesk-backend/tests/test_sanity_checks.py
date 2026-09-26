"""Tests for ``app.services.sanity`` — one deliberate failure mode per case where applicable."""

import datetime
import io

import pandas as pd

from app.parsers.purchase_register_parser import detect_column_mapping, parse_purchase_register
from app.services.sanity import SanityCheck, detect_duplicates, run_import_sanity
from app.utils.test_helpers import make_valid_test_gstin


def _gst(i: int = 0) -> str:
    return make_valid_test_gstin(i)


def _base(**kwargs):
    r = {
        "gstin": _gst(0),
        "invoice_number_normalized": "INV-1",
        "invoice_date": "2020-06-01",
        "taxable_amount_paise": 100_000,
        "total_tax_paise": 18_000,
        "cgst_paise": 9_000,
        "sgst_paise": 9_000,
        "igst_paise": 0,
        "tax_rate": 18,
        "document_type": "INVOICE",
    }
    r.update(kwargs)
    return r


def _by_name(checks: list[SanityCheck], name: str) -> SanityCheck:
    for c in checks:
        if c.name == name:
            return c
    raise AssertionError(f"missing check {name!r}")


def test_row_count_passes_when_actual_equals_expected():
    rows = [_base(invoice_number_normalized=f"INV-{i}") for i in range(3)]
    checks = run_import_sanity(rows, expected_count=3, source_type="csv")
    c = _by_name(checks, "Row Count")
    assert c.passed is True
    assert c.severity == "info"


def test_row_count_fails_when_counts_differ():
    rows = [_base()]
    checks = run_import_sanity(rows, expected_count=2, source_type="csv")
    c = _by_name(checks, "Row Count")
    assert c.passed is False
    assert c.severity == "error"


def test_gstin_validity_passes_for_valid_gstin():
    checks = run_import_sanity([_base()], expected_count=1, source_type="x")
    c = _by_name(checks, "GSTIN Validity")
    assert c.passed is True


def test_gstin_validity_fails_for_invalid_gstin():
    bad = _base(gstin="INVALID")
    checks = run_import_sanity([bad], expected_count=1, source_type="x")
    c = _by_name(checks, "GSTIN Validity")
    assert c.passed is False
    assert len(c.affected_records) >= 1


# ── PR-specific GSTIN behaviour ──────────────────────────────────────────────

def test_pr_malformed_gstin_is_warning_not_error():
    """Malformed (but non-blank) supplier GSTINs in a PR must be warnings so the run is not blocked."""
    bad = _base(gstin="27AAAPZ1234A1Z5EXTRA")  # too long → invalid format
    checks = run_import_sanity([bad], expected_count=1, source_type="purchase_register")
    c = _by_name(checks, "GSTIN Validity")
    assert c.passed is False
    assert c.severity == "warning"
    assert len(c.affected_records) >= 1


def test_pr_blank_gstin_is_error():
    """A completely blank supplier GSTIN in a PR must still be an error — the row is meaningless."""
    blank = _base(gstin="")
    checks = run_import_sanity([blank], expected_count=1, source_type="purchase_register")
    c = _by_name(checks, "GSTIN Validity")
    assert c.passed is False
    assert c.severity == "error"


def test_pr_valid_gstin_passes():
    checks = run_import_sanity([_base()], expected_count=1, source_type="purchase_register")
    c = _by_name(checks, "GSTIN Validity")
    assert c.passed is True
    assert c.severity == "info"


# ── PR parser: malformed GSTIN rows must be INCLUDED, not skipped ─────────────

def _csv_bytes(**row_overrides) -> bytes:
    """Return a minimal CSV purchase-register with one data row."""
    defaults = {
        "Supplier GSTIN": "27AAAPZ1234A1Z5",
        "Supplier Name": "Test Vendor",
        "Invoice Number": "INV-001",
        "Invoice Date": "01/04/2024",
        "Taxable Amount": "10000",
        "IGST": "0",
        "CGST": "900",
        "SGST": "900",
        "Total Invoice Value": "11800",
    }
    defaults.update(row_overrides)
    df = pd.DataFrame([defaults])
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode()


def test_parser_includes_row_with_malformed_gstin():
    """A row with an invalid (but non-blank) supplier GSTIN must be kept in records.

    Previously the parser added 'invalid GSTIN' to row_errors, causing the row to
    be silently dropped. If all rows were invalid, valid_rows=0 → success=False →
    run_import_job raised → wizard showed 'error' and blocked the Start button.
    """
    csv_data = _csv_bytes(**{"Supplier GSTIN": "BADINVALIDGSTIN"})
    result = parse_purchase_register(csv_data, "test.csv")
    assert result["success"] is True, f"Parse failed unexpectedly: {result['errors']}"
    assert len(result["records"]) == 1, "Row with malformed GSTIN must be kept"
    rec = result["records"][0]
    assert rec["gstin_valid"] is False
    assert rec["gstin"] == "BADINVALIDGSTIN"


def test_parser_handles_row_with_blank_gstin():
    """A row with a blank supplier GSTIN is imported with gstin=None (unregistered vendor / EDU data)."""
    csv_data = _csv_bytes(**{"Supplier GSTIN": ""})
    result = parse_purchase_register(csv_data, "test.csv")
    assert len(result["records"]) == 1
    assert result["records"][0]["gstin"] is None


def test_parser_keeps_conflicting_duplicate_invoices():
    """Duplicate invoice numbers with different amounts are flagged but kept."""
    rows = [
        {
            "Supplier GSTIN": "27AAAPZ1234A1Z5",
            "Supplier Name": "Test Vendor",
            "Invoice Number": "DUP-001",
            "Invoice Date": "13/05/2026",
            "Taxable Amount": "10000",
            "IGST": "0",
            "CGST": "900",
            "SGST": "900",
            "Total Invoice Value": "11800",
        },
        {
            "Supplier GSTIN": "27AAAPZ1234A1Z5",
            "Supplier Name": "Test Vendor",
            "Invoice Number": "DUP-001",
            "Invoice Date": "14/05/2026",
            "Taxable Amount": "20000",
            "IGST": "0",
            "CGST": "1800",
            "SGST": "1800",
            "Total Invoice Value": "23600",
        },
    ]
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    result = parse_purchase_register(buf.getvalue().encode(), "dup.csv")
    assert result["success"] is True
    assert len(result["records"]) == 2
    assert any("conflicting duplicate" in e for e in result["errors"])
    assert result.get("skipped_rows", 0) == 0


def test_parser_reads_payment_status_unpaid():
    rows = [
        {
            "Supplier GSTIN": "27AAAPZ1234A1Z5",
            "Supplier Name": "Test Vendor",
            "Invoice Number": "INV-012",
            "Invoice Date": "30/10/2025",
            "Taxable Amount": "15000",
            "IGST": "0",
            "CGST": "1350",
            "SGST": "1350",
            "Total Invoice Value": "17700",
            "Payment Status": "Unpaid",
        },
    ]
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    result = parse_purchase_register(buf.getvalue().encode(), "rule37.csv")
    assert result["success"] is True
    rec = result["records"][0]
    assert rec.get("payment_status") == "unpaid"
    assert "payment_date" not in rec


def test_parser_preserves_decimal_amounts_as_true_paise():
    csv_data = _csv_bytes(
        **{
            "Taxable Amount": "134595.94",
            "CGST": "3364.90",
            "SGST": "3364.90",
            "IGST": "0.00",
            "Total Invoice Value": "141325.74",
        }
    )
    result = parse_purchase_register(csv_data, "decimal.csv")
    assert result["success"] is True, result["errors"]
    rec = result["records"][0]
    assert rec["taxable_amount_paise"] == 13_459_594
    assert rec["cgst_paise"] == 336_490
    assert rec["sgst_paise"] == 336_490
    assert rec["igst_paise"] == 0
    assert rec["total_amount_paise"] == 14_132_574


def test_total_amount_mapping_prefers_invoice_value_over_total_itc():
    df = pd.DataFrame(
        columns=[
            "Supplier GSTIN",
            "Invoice Number",
            "Taxable Amount",
            "Total ITC",
            "Invoice Value",
        ]
    )
    mapping = detect_column_mapping(df)
    assert mapping["total_amount"] == "Invoice Value"


def test_tax_math_passes_within_500_paise_tolerance():
    # 100000 * 18 / 100 = 18000; off by 500 is still ok
    r = _base(total_tax_paise=18_500, tax_rate=18)
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "Tax Math")
    assert c.passed is True


def test_tax_math_fails_beyond_tolerance():
    r = _base(total_tax_paise=19_000, tax_rate=18)  # diff 1000 > 500
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "Tax Math")
    assert c.passed is False


def test_tax_math_passes_when_tax_rate_missing_skipped():
    r = _base()
    del r["tax_rate"]
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "Tax Math")
    assert c.passed is True


def test_tax_math_passes_using_cgst_sgst_igst_without_total_tax_paise():
    r = _base()
    del r["total_tax_paise"]
    r["cgst_paise"] = 9_000
    r["sgst_paise"] = 9_000
    r["igst_paise"] = 0
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "Tax Math")
    assert c.passed is True


def test_cgst_igst_conflict_detects_both_positive():
    # Tax total still matches rate math; components are intentionally inconsistent with CGST+IGST both > 0
    r = _base(cgst_paise=100, igst_paise=100, sgst_paise=0, total_tax_paise=18_000)
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "CGST/IGST Conflict")
    assert c.passed is False


def test_cgst_igst_conflict_detects_short_keys_cgst_igst():
    """Records may use cgst/igst instead of cgst_paise/igst_paise (e.g. raw GSTR-style fields)."""
    r = _base(cgst_paise=0, igst_paise=0, sgst_paise=0, total_tax_paise=18_000)
    del r["cgst_paise"]
    del r["igst_paise"]
    r["cgst"] = 900
    r["igst"] = 1800
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "CGST/IGST Conflict")
    assert c.passed is False
    assert len(c.affected_records) == 1


def test_cgst_igst_no_conflict_when_only_igst():
    r = _base(cgst_paise=0, sgst_paise=0, igst_paise=18_000, total_tax_paise=18_000)
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "CGST/IGST Conflict")
    assert c.passed is True


def test_future_date_fails():
    future = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    r = _base(invoice_date=future)
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "Future Date")
    assert c.passed is False
    assert len(c.affected_records) >= 1


def test_zero_taxable_amount_flagged():
    r = _base(taxable_amount_paise=0, total_tax_paise=0, cgst_paise=0, sgst_paise=0, tax_rate=0)
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "Zero Amount")
    assert c.passed is False
    assert c.severity == "warning"


def test_negative_tax_flagged():
    r = _base(cgst_paise=-100, sgst_paise=9_100, igst_paise=0, total_tax_paise=18_000)
    checks = run_import_sanity([r], expected_count=1, source_type="x")
    c = _by_name(checks, "Negative Tax")
    assert c.passed is False


def test_duplicates_within_batch_second_row_flagged():
    a = _base(invoice_number_normalized="DUP")
    b = _base(invoice_number_normalized="DUP")
    res = detect_duplicates([a, b])
    assert res["has_duplicates"] is True
    assert len(res["within_batch"]) == 1
    assert len(res["clean_records"]) == 1


def test_duplicates_against_existing_history():
    hist = [_base(invoice_number_normalized="H1")]
    incoming = [_base(invoice_number_normalized="H1")]
    res = detect_duplicates(incoming, existing_records=hist)
    assert res["has_duplicates"] is True
    assert len(res["against_history"]) == 1
    assert res["clean_records"] == []


def test_detect_duplicates_never_drops_rows_partition():
    """Every input row appears exactly once across clean, within_batch, and against_history."""
    e1 = _base(invoice_number_normalized="E1")
    e2 = _base(invoice_number_normalized="E2")
    hist = [e1]
    incoming = [e1, e2, e2]
    res = detect_duplicates(incoming, existing_records=hist)
    all_out = res["clean_records"] + res["within_batch"] + res["against_history"]
    assert len(all_out) == len(incoming)
    assert len(res["against_history"]) == 1
    assert len(res["clean_records"]) == 1
    assert len(res["within_batch"]) == 1


def test_pr_supplier_gstin_orientation_flags_taxpayer_gstin():
    """If PR rows have supplier GSTIN matching the client's own GSTIN, flag as warning."""
    client_gstin = "27ISKPK1273H1ZF"
    rows = [_base(gstin=client_gstin) for _ in range(10)]
    checks = run_import_sanity(
        rows,
        expected_count=10,
        source_type="purchase_register",
        client_gstin=client_gstin,
    )
    c = _by_name(checks, "Supplier GSTIN Orientation")
    assert c is not None
    assert c.passed is False
    assert c.severity == "warning"
    assert "inverted" in c.detail


def test_pr_supplier_gstin_orientation_passes_for_vendors():
    """If PR rows have supplier GSTIN different from client's GSTIN, check passes."""
    client_gstin = "27ISKPK1273H1ZF"
    rows = [_base(gstin="29AACST1001A1Z1") for _ in range(10)]
    checks = run_import_sanity(
        rows,
        expected_count=10,
        source_type="purchase_register",
        client_gstin=client_gstin,
    )
    c = _by_name(checks, "Supplier GSTIN Orientation")
    assert c is not None
    assert c.passed is True
    assert c.severity == "info"


def test_pr_column_inversion_auto_correction():
    """If CSV has monochromatic client GSTIN under 'supplier_gstin' and multiple vendor GSTINs under 'customer_gstin', auto-remap."""
    csv_text = (
        "supplier_gstin,customer_gstin,invoice_number,invoice_date,taxable_value,igst,cgst,sgst\n"
        "27ISKPK1273H1ZF,29AACST1001A1Z1,INV-001,2026-08-01,10000,1800,0,0\n"
        "27ISKPK1273H1ZF,06AADKT1002A1Z2,INV-002,2026-08-02,12000,2160,0,0\n"
        "27ISKPK1273H1ZF,24AAMPN1003A1Z3,INV-003,2026-08-03,15000,2700,0,0\n"
    )
    res = parse_purchase_register(csv_text.encode("utf-8"), "test_inverted.csv", client_gstin="27ISKPK1273H1ZF")
    assert res["success"] is True
    records = res["records"]
    assert len(records) == 3
    # Supplier GSTIN should be auto-remapped to the vendors from customer_gstin
    assert records[0]["gstin"] == "29AACST1001A1Z1"
    assert records[1]["gstin"] == "06AADKT1002A1Z2"
    assert records[2]["gstin"] == "24AAMPN1003A1Z3"


def test_period_date_alignment_passes_when_dates_match_target():
    rows = [
        _base(invoice_number_normalized=f"INV-{i}", invoice_date="2024-09-15")
        for i in range(10)
    ]
    checks = run_import_sanity(
        rows,
        expected_count=10,
        source_type="purchase_register",
        target_period="09-2024",
    )
    c = _by_name(checks, "Period Date Alignment")
    assert c.passed is True
    assert c.severity == "info"
    assert "align with selected return period September 2024" in c.detail


def test_period_date_alignment_fails_when_dates_belong_to_different_month():
    # 9 out of 10 rows in July 2024, but target period is September 2024
    rows = [
        _base(invoice_number_normalized=f"INV-{i}", invoice_date="2024-07-20")
        for i in range(9)
    ] + [_base(invoice_number_normalized="INV-9", invoice_date="2024-09-05")]
    checks = run_import_sanity(
        rows,
        expected_count=10,
        source_type="purchase_register",
        target_period="2024-09",
    )
    c = _by_name(checks, "Period Date Alignment")
    assert c.passed is False
    assert c.severity == "warning"
    assert "90.0% of invoices (9 of 10) belong to a different tax period" in c.detail
    assert "Dominant period in file: July 2024" in c.detail
    assert len(c.affected_records) > 0

