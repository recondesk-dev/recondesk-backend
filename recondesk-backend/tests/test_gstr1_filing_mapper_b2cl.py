"""GSTR-1 B2CL filing mapper — b2cl_candidates → Sandbox b2cl[]."""

from __future__ import annotations

import pytest

from app.filing.gstr1_filing_mapper import (
    MissingFilerStateError,
    map_sales_register_to_gstr1_b2cl,
    map_sales_register_to_gstr1_b2cs,
)
from app.filing.gstr1_thresholds import B2CL_INVOICE_VALUE_FROM_PAISE


FILER_MH = "27"


def _b2cl_candidate(**overrides):
    """INTER B2C row already above post-cutover ₹1L threshold (hand-off shape)."""
    over = B2CL_INVOICE_VALUE_FROM_PAISE + 100  # ₹1,00,001.00
    # 18% of taxable; choose taxable so IGST reconciles and total = over
    # val = txval + igst => igst = txval * 0.18 => val = txval * 1.18
    # over = txval * 1.18 => txval = over / 1.18
    txval_paise = int(round(over / 1.18))
    igst_paise = over - txval_paise
    base = {
        "row_number": 10,
        "gstin": None,
        "gstin_valid": False,
        "invoice_type": "B2C_LARGE",
        "invoice_type_raw": "B2C Large",
        "invoice_number": "B2CL001",
        "invoice_number_normalized": "B2CL001",
        "invoice_number_raw": "B2CL-001",
        "invoice_date": "2025-04-08",
        "place_of_supply": "07-Delhi",
        "reverse_charge": False,
        "taxable_amount_paise": txval_paise,
        "igst_paise": igst_paise,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": None,  # absent → csamt 0
        "total_tax_paise": igst_paise,
        "total_amount_paise": over,
        "tax_rate": 18.0,
    }
    base.update(overrides)
    return base


def test_missing_filer_state_fails_whole_batch():
    with pytest.raises(MissingFilerStateError):
        map_sales_register_to_gstr1_b2cl([_b2cl_candidate()], filer_state="")


def test_happy_path_groups_by_pos_csamt_defaults_zero():
    c1 = _b2cl_candidate(invoice_number_raw="INV-A")
    c2 = _b2cl_candidate(
        invoice_number_raw="INV-B",
        place_of_supply="06-Haryana",
        cess_paise=500,  # ₹5 cess
    )
    # Keep tax consistent for c2: leave igst as computed for 18% on same txval
    result = map_sales_register_to_gstr1_b2cl([c1, c2], filer_state=FILER_MH)
    assert result.pending_count == 0
    assert result.save_invoice_count == 2
    assert {g["pos"] for g in result.b2cl} == {"06", "07"}

    by_pos = {g["pos"]: g for g in result.b2cl}
    inv_a = by_pos["07"]["inv"][0]
    assert inv_a["inum"] == "INV-A"
    assert inv_a["idt"] == "08-04-2025"
    assert inv_a["itms"][0]["itm_det"]["csamt"] == 0.0  # absent cess → 0
    assert "camt" not in inv_a["itms"][0]["itm_det"]
    assert "samt" not in inv_a["itms"][0]["itm_det"]

    inv_b = by_pos["06"]["inv"][0]
    assert inv_b["itms"][0]["itm_det"]["csamt"] == 5.0


def test_handoff_from_b2cs_without_rederiving_threshold():
    """Same invoice identity flows B2CS candidates → B2CL Save."""
    over = B2CL_INVOICE_VALUE_FROM_PAISE + 1
    txval_paise = int(round(over / 1.18))
    igst_paise = over - txval_paise
    sr_row = {
        "gstin": None,
        "gstin_valid": False,
        "invoice_type": "B2C",
        "invoice_type_raw": None,
        "invoice_number_raw": "HAND-OFF-99",
        "invoice_date": "2025-04-15",
        "place_of_supply": "07-Delhi",
        "taxable_amount_paise": txval_paise,
        "igst_paise": igst_paise,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
        "total_amount_paise": over,
        "tax_rate": 18.0,
    }
    # At exactly threshold → B2CS, not candidate
    exact = B2CL_INVOICE_VALUE_FROM_PAISE
    tx_exact = int(round(exact / 1.18))
    igst_exact = exact - tx_exact
    boundary_row = {
        **sr_row,
        "invoice_number_raw": "AT-THRESHOLD",
        "taxable_amount_paise": tx_exact,
        "igst_paise": igst_exact,
        "total_amount_paise": exact,
    }

    b2cs = map_sales_register_to_gstr1_b2cs(
        [sr_row, boundary_row],
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert len(b2cs.b2cl_candidates) == 1
    assert b2cs.b2cl_candidates[0]["invoice_number_raw"] == "HAND-OFF-99"
    # Boundary stayed in B2CS aggregate (INTER ≤ threshold), not candidates.
    assert all(
        c.get("invoice_number_raw") != "AT-THRESHOLD"
        for c in b2cs.b2cl_candidates
    )
    assert any(bucket["pos"] == "07" for bucket in b2cs.b2cs)

    b2cl = map_sales_register_to_gstr1_b2cl(
        b2cs.b2cl_candidates, filer_state=FILER_MH,
    )
    assert b2cl.pending_count == 0
    assert b2cl.save_invoice_count == 1
    assert b2cl.b2cl[0]["inv"][0]["inum"] == "HAND-OFF-99"
    assert (
        b2cl.b2cl[0]["inv"][0]["inum"]
        == b2cs.b2cl_candidates[0]["invoice_number_raw"]
    )


def test_pending_missing_inum():
    rec = _b2cl_candidate(invoice_number_raw=None)
    result = map_sales_register_to_gstr1_b2cl([rec], filer_state=FILER_MH)
    assert result.pending_review[0].reason == "missing_inum"
    assert result.b2cl == []


def test_pending_missing_idt():
    rec = _b2cl_candidate(invoice_date=None)
    result = map_sales_register_to_gstr1_b2cl([rec], filer_state=FILER_MH)
    assert result.pending_review[0].reason == "missing_or_invalid_idt"


def test_pending_missing_tax_rate():
    rec = _b2cl_candidate()
    del rec["tax_rate"]
    result = map_sales_register_to_gstr1_b2cl([rec], filer_state=FILER_MH)
    assert result.pending_review[0].reason == "missing_tax_rate"


def test_pending_missing_taxable_value():
    rec = _b2cl_candidate(taxable_amount_paise=None)
    result = map_sales_register_to_gstr1_b2cl([rec], filer_state=FILER_MH)
    assert result.pending_review[0].reason == "missing_taxable_value"


def test_pending_missing_invoice_value():
    rec = _b2cl_candidate(total_amount_paise=None)
    result = map_sales_register_to_gstr1_b2cl([rec], filer_state=FILER_MH)
    assert result.pending_review[0].reason == "missing_invoice_value"
    assert result.b2cl == []


def test_pending_malformed_pos():
    rec = _b2cl_candidate(place_of_supply="Nowhere")
    result = map_sales_register_to_gstr1_b2cl([rec], filer_state=FILER_MH)
    assert result.pending_review[0].reason == "missing_or_malformed_pos"


def test_pending_pos_not_interstate():
    rec = _b2cl_candidate(place_of_supply="27-Maharashtra")
    result = map_sales_register_to_gstr1_b2cl([rec], filer_state=FILER_MH)
    assert result.pending_review[0].reason == "b2cl_pos_not_interstate"


def test_pending_tax_amount_inconsistent_with_rate():
    rec = _b2cl_candidate(
        taxable_amount_paise=10_000_000,  # ₹1,00,000
        igst_paise=1_000_00,  # ₹1,000 but 18% would be ₹18,000
        total_amount_paise=10_100_000,
        tax_rate=18.0,
    )
    result = map_sales_register_to_gstr1_b2cl([rec], filer_state=FILER_MH)
    assert result.pending_review[0].reason == "tax_amount_inconsistent_with_rate"
    assert result.b2cl == []


def test_tax_consistency_within_one_rupee_tolerance_passes():
    """±₹1 rounding from paise conversion still Saves."""
    rec = _b2cl_candidate(
        taxable_amount_paise=10_000_000,  # ₹100000
        igst_paise=1_800_099,  # ₹18000.99 — within ₹1 of 18000
        total_amount_paise=11_800_099,
        tax_rate=18.0,
    )
    result = map_sales_register_to_gstr1_b2cl([rec], filer_state=FILER_MH)
    assert result.pending_count == 0
    assert result.save_invoice_count == 1
