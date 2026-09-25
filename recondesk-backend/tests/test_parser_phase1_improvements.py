"""Tests for Phase 1 Parser Hardening & Upload Resilience improvements."""

import io
import json
import zipfile
import pytest

from app.parsers.gstr2b_excel import load_gstr2b_upload_payload
from app.parsers.purchase_register_parser import (
    _safe_cell,
    _normalize_invoice_number_cell,
    parse_purchase_register,
)
from app.services.normalizer import normalize_date
from app.services.reconciliation_import_wizard.wizard_service import run_sanity_gstr2b_json


def test_gstr2b_zip_archive_auto_extraction():
    """Verify that a portal GSTR-2B zip archive is automatically unpacked and parsed."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "returns_052026_gstr2b.json",
            json.dumps({
                "data": {
                    "gstin": "27ISKPK1273H1ZF",
                    "rtnprd": "052026",
                    "b2b": [
                        {
                            "ctin": "27AABCT1332L1ZV",
                            "inv": [
                                {
                                    "inum": "INV-100",
                                    "dt": "20-05-2026",
                                    "val": 1000.0,
                                    "txval": 900.0,
                                    "igst": 0.0,
                                    "cgst": 50.0,
                                    "sgst": 50.0,
                                    "pos": "27",
                                    "rev": "N",
                                    "itcavl": "Y",
                                }
                            ],
                        }
                    ],
                }
            }),
        )

    raw_zip = buf.getvalue()
    payload = load_gstr2b_upload_payload(raw_zip, "GSTR2B_27ISKPK1273H1ZF_052026.zip")
    assert payload["data"]["gstin"] == "27ISKPK1273H1ZF"
    assert len(payload["data"]["b2b"]) == 1

    checks, count = run_sanity_gstr2b_json(raw_zip, filename="GSTR2B_27ISKPK1273H1ZF_052026.zip")
    assert count == 1
    assert checks[0]["status"] == "pass"
    assert "ZIP" in checks[0]["detail"]


def test_gstr2b_zip_multipart_chunk_merge():
    """Verify that multi-part JSON chunks in a portal zip are merged together."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "returns_052026_gstr2b_part1.json",
            json.dumps({
                "data": {
                    "gstin": "27ISKPK1273H1ZF",
                    "rtnprd": "052026",
                    "b2b": [
                        {
                            "ctin": "27AABCT1332L1ZV",
                            "inv": [{"inum": "INV-1", "dt": "20-05-2026", "val": 1000, "txval": 900, "igst": 0, "cgst": 50, "sgst": 50, "pos": "27", "rev": "N", "itcavl": "Y"}],
                        }
                    ],
                }
            }),
        )
        zf.writestr(
            "returns_052026_gstr2b_part2.json",
            json.dumps({
                "data": {
                    "gstin": "27ISKPK1273H1ZF",
                    "rtnprd": "052026",
                    "b2b": [
                        {
                            "ctin": "29ABCDE1234F1Z5",
                            "inv": [{"inum": "INV-2", "dt": "22-05-2026", "val": 2000, "txval": 1800, "igst": 200, "cgst": 0, "sgst": 0, "pos": "29", "rev": "N", "itcavl": "Y"}],
                        }
                    ],
                }
            }),
        )

    raw_zip = buf.getvalue()
    payload = load_gstr2b_upload_payload(raw_zip, "multipart_gstr2b.zip")
    assert len(payload["data"]["b2b"]) == 2
    assert {s["ctin"] for s in payload["data"]["b2b"]} == {"27AABCT1332L1ZV", "29ABCDE1234F1Z5"}


def test_purchase_register_zip_archive_auto_extraction():
    """Verify that Purchase Register zip archives are unpacked and parsed seamlessly."""
    pr_csv = (
        "Supplier GSTIN,Invoice Number,Invoice Date,Taxable Value (Rs),IGST (Rs),CGST (Rs),SGST (Rs)\n"
        "27AABCT1332L1ZV,INV-100,20-05-2026,900,0,50,50\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Purchase_Register_May2026.csv", pr_csv)

    raw_zip = buf.getvalue()
    res = parse_purchase_register(raw_zip, "PR_Export.zip")
    assert res["success"] is True
    assert len(res["records"]) == 1
    assert res["records"][0]["invoice_number"] == "INV-100"


def test_purchase_register_floating_point_and_scientific_invoice_numbers():
    """Verify Excel .0 float strings and scientific notation invoice numbers are sanitized."""
    assert _normalize_invoice_number_cell("12345.0") == "12345"
    assert _normalize_invoice_number_cell("12345.00") == "12345"
    assert _normalize_invoice_number_cell("1.23E+04") == "12300"
    assert _normalize_invoice_number_cell("INV-0012") == "INV12"


def test_purchase_register_safe_cell_unicode_and_formula_errors():
    """Verify invisible unicode chars and Excel formula errors are safely handled."""
    assert _safe_cell("  INV\xa0123\u200b  ") == "INV 123"
    assert _safe_cell("#REF!") is None
    assert _safe_cell("#VALUE!") is None
    assert _safe_cell("#N/A") is None
    assert _safe_cell("#DIV/0!") is None


def test_normalize_date_us_mm_dd_yyyy_fallback():
    """Verify that MM/DD/YYYY dates (e.g. from Zoho/QuickBooks) parse cleanly when month > 12."""
    res1 = normalize_date("05/20/2026")
    assert res1.value.isoformat() == "2026-05-20"
    assert "mm_dd_yyyy_converted" in res1.notes

    res2 = normalize_date("20/05/2026")
    assert res2.value.isoformat() == "2026-05-20"

    res3 = normalize_date("05/20/26")
    assert res3.value.isoformat() == "2026-05-20"
