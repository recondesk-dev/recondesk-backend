"""Adversarial amendment scenarios beyond the basic G1M11 happy path."""

from __future__ import annotations

from app.reconciliation.gstr1_vs_3b import aggregate_gstr1
from app.rules.gstr1_mismatch_rules import (
    MismatchSeverity,
    detect_amendments,
)


def _sr(
    *,
    inv: str = "INV/001",
    taxable: int = 100000,
    igst: int = 18000,
    gstin: str = "27AAECS4567P1Z9",
    invoice_type: str = "B2B",
    rate: float = 18.0,
) -> dict:
    return {
        "invoice_number": inv,
        "invoice_number_normalized": inv.replace("/", "").replace("-", ""),
        "invoice_type": invoice_type,
        "document_type": invoice_type,
        "gstin": gstin,
        "taxable_amount_paise": taxable,
        "igst_paise": igst,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "total_tax_paise": igst,
        "rate": rate,
    }


def _g1(
    *,
    inv: str = "INV/001",
    taxable: int = 100000,
    igst: int = 18000,
    gstin: str = "27AAECS4567P1Z9",
    invoice_type: str = "B2B",
    section: str = "b2b",
    rate: float = 18.0,
    is_amendment: bool = False,
    oinum: str | None = None,
) -> dict:
    rec = {
        "invoice_number": inv,
        "invoice_number_normalized": inv.replace("/", "").replace("-", ""),
        "invoice_type": invoice_type,
        "section": section,
        "gstin": gstin,
        "recipient_gstin": gstin,
        "taxable_amount_paise": taxable,
        "igst_paise": igst,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "total_tax_paise": igst,
        "rate": rate,
    }
    if is_amendment:
        rec["is_amendment"] = True
    if oinum:
        rec["original_invoice_number"] = oinum
        rec["oinum"] = oinum
    return rec


def test_oinum_links_filed_amendment_when_inum_changed():
    """Filed b2ba may use a new inum; oinum must still silence amendment_missing."""
    results = detect_amendments(
        [_sr(inv="RD/001", taxable=200000, igst=36000)],
        [_g1(inv="RD/001", taxable=100000, igst=18000)],
        prior_provided=True,
        current_amendment_records=[
            _g1(
                inv="RD/001-A",
                taxable=200000,
                igst=36000,
                section="b2ba",
                is_amendment=True,
                oinum="RD/001",
            )
        ],
    )
    assert results == []


def test_rate_only_change_is_medium_amendment_missing():
    results = detect_amendments(
        [_sr(inv="RD/001", taxable=100000, igst=18000, rate=18.0)],
        [_g1(inv="RD/001", taxable=100000, igst=18000, rate=12.0)],
        prior_provided=True,
    )
    assert len(results) == 1
    assert results[0].details["issue_type"] == "amendment_missing"
    assert results[0].details["differed_fields"] == ["gst_rate"]
    assert results[0].severity == MismatchSeverity.MEDIUM


def test_tolerance_boundary_paise():
    # Δ ₹0.50 — within ₹1 tolerance
    assert (
        detect_amendments(
            [_sr(inv="X", taxable=100050, igst=18009)],
            [_g1(inv="X", taxable=100000, igst=18000)],
            prior_provided=True,
        )
        == []
    )
    # Δ ₹1.01 — must flag
    flagged = detect_amendments(
        [_sr(inv="X", taxable=100101, igst=18018)],
        [_g1(inv="X", taxable=100000, igst=18000)],
        prior_provided=True,
    )
    assert len(flagged) == 1
    assert "taxable_amount" in flagged[0].details["differed_fields"]


def test_aggregate_does_not_double_count_b2b_and_b2ba_same_invoice():
    """Same logical invoice in b2b + b2ba must use revised value only."""
    records = [
        _g1(inv="RD/001", taxable=100000, igst=18000, section="b2b"),
        _g1(
            inv="RD/001-A",
            taxable=200000,
            igst=36000,
            section="b2ba",
            is_amendment=True,
            oinum="RD/001",
        ),
        _g1(inv="RD/002", taxable=50000, igst=9000, section="b2b"),
    ]
    agg = aggregate_gstr1(records)
    # Old bug: 100000+200000+50000 = 350000. Correct: 200000+50000 = 250000.
    assert agg.taxable_value_paise == 250000
    assert agg.igst_paise == 45000
    assert agg.record_count == 2


def test_cdnra_supersedes_cdnr_for_same_note():
    records = [
        _g1(
            inv="CN/001",
            taxable=40000,
            igst=7200,
            section="cdnr",
            invoice_type="CREDIT_NOTE",
        ),
        _g1(
            inv="CN/001",
            taxable=50000,
            igst=9000,
            section="cdnra",
            invoice_type="CREDIT_NOTE",
            is_amendment=True,
        ),
    ]
    agg = aggregate_gstr1(records)
    # CDN sign is negative; only amended 50000 should apply.
    assert agg.taxable_value_paise == -50000
    assert agg.igst_paise == -9000
