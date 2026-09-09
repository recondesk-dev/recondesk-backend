"""Wrongful ITC risk totals sum total_tax_paise (ITC), not taxable_amount_paise."""

import io

import openpyxl
import pytest

from app.parsers.purchase_register_parser import parse_purchase_register
from app.routers.reconciliation_api import (
    _paise_to_rupees,
    _wrongful_risk_itc_paise,
    _wrongful_risk_taxable_paise,
)
from app.services.reconciliation import build_wrongful_itc_risk


def test_wrongful_risk_itc_paise_prefers_total_tax_over_taxable():
    w = {"total_tax_paise": 184_712, "taxable_amount_paise": 10_000_000}
    assert _wrongful_risk_itc_paise(w) == 184_712


def test_wrongful_risk_itc_paise_falls_back_to_matcher_total_tax():
    w = {"total_tax_paise": None, "taxable_amount_paise": 10_000_000}
    mt = {"total_tax_paise": 5_050}
    assert _wrongful_risk_itc_paise(w, mt) == 5_050


def test_wrongful_risk_taxable_paise_prefers_taxable_over_total_tax():
    w = {"taxable_amount_paise": 10_000_000, "total_tax_paise": 184_712}
    assert _wrongful_risk_taxable_paise(w) == 10_000_000


def test_paise_to_rupees_keeps_fractional_rupees():
    assert _paise_to_rupees(184_712) == 1847.12
    assert _paise_to_rupees(50) == 0.5


# ---------------------------------------------------------------------------
# Regression: credit note total_tax_paise sign bug
# Bug: normalize_dataframe_to_canonical_schema used _amount_int_unsigned (abs)
# for total_tax_paise, making credit notes contribute a POSITIVE tax amount.
# This overstated ITC at Risk by 2× the sum of credit note amounts.
# Fix: negate total_tax_paise for CREDIT_NOTE rows after invoice_type is set.
# ---------------------------------------------------------------------------

def _make_pr_xlsx(rows: list[dict]) -> bytes:
    """Build a minimal in-memory PR Excel file from a list of row dicts."""
    wb = openpyxl.Workbook()
    ws = wb.active
    headers = [
        "GSTIN", "Invoice Number", "Invoice Date",
        "Taxable Amount", "IGST", "CGST", "SGST", "Total Tax",
    ]
    ws.append(headers)
    for r in rows:
        ws.append([
            r.get("gstin", "27ABCDE1234F1Z5"),
            r.get("invoice_number", "INV001"),
            r.get("invoice_date", "01-04-2025"),
            r.get("taxable_amount", 10000),
            r.get("igst", 0),
            r.get("cgst", 900),
            r.get("sgst", 900),
            r.get("total_tax", 1800),
        ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_credit_note_total_tax_paise_is_negative():
    """Credit note rows must have negative total_tax_paise after parsing."""
    xlsx = _make_pr_xlsx([
        {
            "invoice_number": "CN/2025/001",
            "taxable_amount": -10000,
            "igst": 0, "cgst": 900, "sgst": 900, "total_tax": 1800,
        }
    ])
    result = parse_purchase_register(xlsx, "test.xlsx")
    assert result["success"], result["errors"]
    rec = result["records"][0]
    assert rec["invoice_type"] == "CREDIT_NOTE"
    # total_tax_paise must be negative so ITC-at-risk sum subtracts it
    assert rec["total_tax_paise"] is not None
    assert rec["total_tax_paise"] < 0, (
        f"Expected negative total_tax_paise for credit note, got {rec['total_tax_paise']}"
    )


def test_itc_at_risk_subtracts_credit_notes():
    """
    PR-only ITC at Risk = invoices + debit notes - credit notes.
    Regression: before the fix, credit notes were added (not subtracted)
    because abs() stripped their sign, causing 2× overstatement.

    Amounts: the PR parser converts rupee cell values to paise (×100).
      2 invoices: taxable=1000, total_tax=18 rupees → 100000 and 1800 paise each
      1 credit note: taxable=-1000 rupees → total_tax negated → -1800 paise
      Expected net ITC at risk = 1800 + 1800 - 1800 = 1800 paise
    """
    xlsx = _make_pr_xlsx([
        {"invoice_number": "INV/2025/001", "taxable_amount": 1000,
         "igst": 0, "cgst": 9, "sgst": 9, "total_tax": 18},
        {"invoice_number": "INV/2025/002", "taxable_amount": 1000,
         "igst": 0, "cgst": 9, "sgst": 9, "total_tax": 18},
        {"invoice_number": "CN/2025/001",  "taxable_amount": -1000,
         "igst": 0, "cgst": 9, "sgst": 9, "total_tax": 18},
    ])
    result = parse_purchase_register(xlsx, "test.xlsx")
    assert result["success"], result["errors"]

    # Simulate what reconciliation_task does: build matcher rows from records
    pr_records = []
    for i, rec in enumerate(result["records"]):
        pr_records.append({
            "id": str(i),
            "supplier_gstin": rec.get("gstin", ""),
            "invoice_number_normalized": rec.get("invoice_number_normalized", ""),
            "invoice_date": rec.get("invoice_date"),
            "taxable_amount_paise": rec.get("taxable_amount_paise") or 0,
            "total_tax_paise": rec.get("total_tax_paise") or 0,
        })

    # All 3 are unmatched (no PR ids in matched set)
    wrongful = build_wrongful_itc_risk(pr_records, matched_pr_ids=set())

    total_wrongful_paise = sum(int(x.get("total_tax_paise") or 0) for x in wrongful)
    # 18 rupees × 100 = 1800 paise per invoice; credit note = -1800 paise
    # invoices: +1800 + 1800 = 3600; credit note: -1800 → net = 1800 paise
    assert total_wrongful_paise == 1800, (
        f"Expected 1800 paise ITC at risk (credit note subtracts), got {total_wrongful_paise}. "
        "Bug: credit note may be adding instead of subtracting (abs() sign stripping)."
    )
