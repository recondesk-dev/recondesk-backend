"""Debit/credit note sheets must not be misclassified as blank invoices.

A PR workbook with a ``Debit Notes`` sheet (Date, Note No, Party, GSTIN,
Amount, Reason) should parse as ``document_type: DEBIT_NOTE`` with
``note_number`` populated, and those rows must stay out of ITC at Risk and
Matched after reconciliation.
"""
from __future__ import annotations

import io
from datetime import date

import openpyxl

from app.matching.engine import run_bidirectional_reconciliation
from app.parsers.purchase_register_parser import parse_purchase_register
from app.services.matcher import normalize_invoice


GSTIN = "27AABCU1234R1ZX"


def _make_pr_with_debit_notes_sheet() -> bytes:
    wb = openpyxl.Workbook()

    inv = wb.active
    inv.title = "Invoices"
    inv.append(
        [
            "GSTIN",
            "Invoice Number",
            "Invoice Date",
            "Taxable Amount",
            "CGST",
            "SGST",
            "Total Tax",
        ]
    )
    inv.append([GSTIN, "INV-1001", "15-03-2024", 10000, 900, 900, 1800])

    notes = wb.create_sheet("Debit Notes")
    notes.append(["Date", "Note No", "Party", "GSTIN", "Amount", "Reason"])
    notes.append(
        ["10-03-2024", "DN-5001", "Acme Supplies", GSTIN, 5000, "Price difference"]
    )
    notes.append(
        ["12-03-2024", "DN-5002", "Acme Supplies", GSTIN, 2500, "Qty short"]
    )

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_debit_notes_sheet_parses_as_debit_note_not_invoice():
    result = parse_purchase_register(
        _make_pr_with_debit_notes_sheet(), "pr_with_notes.xlsx"
    )
    assert result["success"], result["errors"]

    notes = [r for r in result["records"] if r.get("pr_note_quarantine")]
    invoices = [r for r in result["records"] if not r.get("pr_note_quarantine")]

    assert len(notes) == 2, f"expected 2 note rows, got {len(notes)}"
    assert len(invoices) == 1

    for n in notes:
        assert n["document_type"] == "DEBIT_NOTE"
        assert n["invoice_type"] == "DEBIT_NOTE"
        assert n.get("note_number"), "note_number must be populated"
        assert n.get("invoice_number") in (None, "")
        assert n.get("note_amount_paise") is not None
        assert n.get("total_tax_paise") in (None, 0)
        assert n.get("pr_note_quarantine") is True

    assert {n["note_number"] for n in notes} == {"DN-5001", "DN-5002"}
    # Amount 5000 / 2500 rupees → paise
    by_no = {n["note_number"]: n for n in notes}
    assert by_no["DN-5001"]["note_amount_paise"] == 500_000
    assert by_no["DN-5002"]["note_amount_paise"] == 250_000


def test_debit_notes_excluded_from_itc_at_risk_and_matched():
    parsed = parse_purchase_register(
        _make_pr_with_debit_notes_sheet(), "pr_with_notes.xlsx"
    )
    assert parsed["success"], parsed["errors"]

    pr_records = []
    for i, rec in enumerate(parsed["records"]):
        pr_records.append(
            {
                "id": f"p{i}",
                "supplier_gstin": rec.get("gstin") or "",
                "invoice_number": rec.get("invoice_number") or "",
                "invoice_number_normalized": normalize_invoice(
                    rec.get("invoice_number_normalized")
                    or rec.get("invoice_number")
                ),
                "invoice_date": date(2024, 3, 15),
                "taxable_amount_paise": int(rec.get("taxable_amount_paise") or 0),
                "total_tax_paise": int(rec.get("total_tax_paise") or 0),
                "cgst_paise": int(rec.get("cgst_paise") or 0),
                "sgst_paise": int(rec.get("sgst_paise") or 0),
                "igst_paise": int(rec.get("igst_paise") or 0),
                "document_type": rec.get("document_type"),
                "invoice_type": rec.get("invoice_type"),
                "doc_type": rec.get("document_type"),
                "note_number": rec.get("note_number"),
                "note_amount_paise": rec.get("note_amount_paise"),
                "pr_note_quarantine": bool(rec.get("pr_note_quarantine")),
            }
        )

    # Matching GSTR for the invoice only — notes have no 2B counterpart.
    gstr = [
        {
            "id": "g1",
            "supplier_gstin": GSTIN,
            "invoice_number": "INV-1001",
            "invoice_number_normalized": normalize_invoice("INV-1001"),
            "invoice_date": date(2024, 3, 15),
            "taxable_amount_paise": 1_000_000,
            "total_tax_paise": 180_000,
            "cgst_paise": 90_000,
            "sgst_paise": 90_000,
            "igst_paise": 0,
        }
    ]

    res = run_bidirectional_reconciliation(gstr, pr_records, gstr_period=date(2024, 3, 1))

    note_ids = {p["id"] for p in pr_records if p.get("pr_note_quarantine")}
    assert len(note_ids) == 2

    unmatched = res.get("unmatched_notes") or []
    assert len(unmatched) == 2
    assert {n["id"] for n in unmatched} == note_ids
    for n in unmatched:
        assert n["document_type"] == "DEBIT_NOTE"
        assert n.get("note_number")

    risk_ids = {str(w["id"]) for w in res.get("wrongful_itc_risk") or []}
    matched_pr_ids = {str(m["pr_id"]) for m in res.get("matched") or []}
    review_pr_ids = {
        str(m.get("pr_id") or m.get("id") or "")
        for m in res.get("review_required") or []
    }

    assert note_ids.isdisjoint(risk_ids), (
        f"Note rows leaked into ITC at Risk: {note_ids & risk_ids}"
    )
    assert note_ids.isdisjoint(matched_pr_ids), (
        f"Note rows leaked into Matched: {note_ids & matched_pr_ids}"
    )
    assert note_ids.isdisjoint(review_pr_ids), (
        f"Note rows leaked into Review Required: {note_ids & review_pr_ids}"
    )

    stats = res.get("stats") or {}
    assert stats.get("unmatched_notes_count") == 2
    assert len(res.get("matched") or []) == 1
