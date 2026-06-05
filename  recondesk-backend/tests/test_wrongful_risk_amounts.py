"""Wrongful ITC risk totals sum taxable_amount_paise, not total_tax_paise."""

from app.routers.reconciliation_api import (
    _paise_to_rupees,
    _wrongful_risk_taxable_paise,
)


def test_wrongful_risk_taxable_paise_prefers_taxable_over_total_tax():
    w = {"taxable_amount_paise": 10_000_000, "total_tax_paise": 184_712}
    assert _wrongful_risk_taxable_paise(w) == 10_000_000


def test_wrongful_risk_taxable_paise_falls_back_to_matcher_taxable():
    w = {"taxable_amount_paise": None, "total_tax_paise": 184_712}
    mt = {"taxable_amount_paise": 5_050_000}
    assert _wrongful_risk_taxable_paise(w, mt) == 5_050_000


def test_paise_to_rupees_keeps_fractional_rupees():
    assert _paise_to_rupees(184_712) == 1847.12
    assert _paise_to_rupees(50) == 0.5
