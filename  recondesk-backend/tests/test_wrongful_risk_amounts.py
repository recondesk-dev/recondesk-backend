"""ITC at risk amounts use total_tax_paise (ITC), not taxable_amount_paise."""

from app.routers.reconciliation_api import (
    _paise_to_rupees,
    _wrongful_itc_paise,
)


def test_wrongful_itc_paise_prefers_total_tax_over_taxable():
    w = {"total_tax_paise": 184_712, "taxable_amount_paise": 10_000_000}
    assert _wrongful_itc_paise(w) == 184_712


def test_wrongful_itc_paise_falls_back_to_matcher_total_tax():
    w = {"total_tax_paise": None, "taxable_amount_paise": 10_000_000}
    mt = {"total_tax_paise": 5_050}
    assert _wrongful_itc_paise(w, mt) == 5_050


def test_paise_to_rupees_keeps_fractional_rupees():
    assert _paise_to_rupees(184_712) == 1847.12
    assert _paise_to_rupees(50) == 0.5
