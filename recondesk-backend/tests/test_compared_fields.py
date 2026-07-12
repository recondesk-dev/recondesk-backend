"""Additive compared_fields snapshot — does not change classification outcomes."""

from __future__ import annotations

from datetime import date

from app.services.matcher import (
    _match_gstr_to_pr_pair,
    build_compared_fields,
)


def _pair(**overrides):
    base_g = {
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "INV-001",
        "invoice_number_normalized": "INV001",
        "taxable_amount_paise": 100_000,
        "total_tax_paise": 18_000,
        "igst_paise": 18_000,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "invoice_date": date(2026, 1, 15),
        "supplier_name": "Acme Pvt Ltd",
    }
    base_p = {
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "INV-001",
        "invoice_number_normalized": "INV001",
        "taxable_amount_paise": 100_000,
        "total_tax_paise": 18_000,
        "igst_paise": 18_000,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "invoice_date": date(2026, 1, 15),
        "vendor_name": "Acme Pvt Ltd",
    }
    g = {**base_g, **(overrides.get("g") or {})}
    p = {**base_p, **(overrides.get("p") or {})}
    return g, p


def _by_name(fields):
    return {f["field_name"]: f for f in fields}


def test_l1_exact_match_emits_exact_compared_fields():
    g, p = _pair()
    result = _match_gstr_to_pr_pair(g, p)
    assert result.level == 1
    assert result.matched is True
    fields = _by_name(result.compared_fields)
    assert fields["gstin"]["match_type"] == "exact"
    assert fields["invoice_number"]["match_type"] == "exact"
    assert fields["taxable_amount"]["match_type"] == "exact"
    assert fields["date"]["match_type"] == "exact"
    assert fields["vendor_name"]["match_type"] == "exact"
    assert fields["invoice_number"]["field_score"] is None


def test_fuzzy_invoice_reports_similarity_score():
    g, p = _pair(p={"invoice_number": "INV-002", "invoice_number_normalized": "INV002"})
    fields = _by_name(build_compared_fields(g, p))
    assert fields["invoice_number"]["match_type"] == "fuzzy"
    assert fields["invoice_number"]["field_score"] == 75
    assert fields["gstin"]["match_type"] == "exact"


def test_normalized_invoice_format_variant_is_fuzzy_not_exact():
    """Raw strings differ (INV/001 vs INV001) but normalize equal — must be fuzzy.

    Matched-tab FUZZY rows previously reported Invoice#: exact because
    invoices_effectively_match was treated as raw-exact. That made rationale
    indistinguishable from L1 and hid the only real difference.
    """
    g, p = _pair(
        g={"invoice_number": "INV/001", "invoice_number_normalized": "INV001"},
        p={"invoice_number": "INV001", "invoice_number_normalized": "INV001"},
    )
    result = _match_gstr_to_pr_pair(g, p)
    assert result.level == 2
    assert result.requires_human_review is False
    fields = _by_name(result.compared_fields)
    assert fields["invoice_number"]["match_type"] == "fuzzy"
    assert fields["taxable_amount"]["match_type"] == "exact"
    assert fields["date"]["match_type"] == "exact"


def test_amount_outside_tolerance_is_not_matched():
    g, p = _pair(p={"taxable_amount_paise": 200_000})
    fields = _by_name(build_compared_fields(g, p))
    assert fields["taxable_amount"]["match_type"] == "not_matched"


def test_compared_fields_does_not_change_match_level():
    """Guardrail: attaching compared_fields must not alter L1 classification."""
    g, p = _pair()
    r1 = _match_gstr_to_pr_pair(g, p)
    r2 = _match_gstr_to_pr_pair(g, p)
    assert r1.level == r2.level == 1
    assert r1.matched == r2.matched
    assert r1.requires_human_review == r2.requires_human_review
    assert r1.compared_fields  # present on both
    assert r2.compared_fields
