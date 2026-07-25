"""GSTR-1 NIL filing mapper — SR → Sandbox nil.inv[]."""

from __future__ import annotations

import pytest

from app.filing.gstr1_external_input import TABLE_NIL
from app.filing.gstr1_filing_mapper import (
    MissingFilerStateError,
    TAX_RATE_AMOUNT_TOLERANCE_RUPEES,
    map_sales_register_to_gstr1_nil,
    resolve_nil_amount_column_from_sr_raw,
)


FILER_MH = "27"
PERIOD = "2025-04"
GSTIN_OK = "27AAECO5678G1Z2"


def _nil_sr(**overrides):
    base = {
        "gstin": None,
        "gstin_valid": False,
        "invoice_type": "NIL_RATED",
        "invoice_type_raw": "Nil Rated",
        "invoice_number_raw": "NIL-1",
        "invoice_date": "2025-04-08",
        "place_of_supply": "27-Maharashtra",
        "taxable_amount_paise": 10_000_00,
        "igst_paise": 0,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
        "total_amount_paise": 10_000_00,
        "tax_rate": 0.0,
    }
    base.update(overrides)
    return base


def test_resolve_explicit_columns():
    assert resolve_nil_amount_column_from_sr_raw(
        invoice_type="NIL_RATED", invoice_type_raw="Nil Rated",
    )[0] == "nil_amt"
    assert resolve_nil_amount_column_from_sr_raw(
        invoice_type="NIL_RATED", invoice_type_raw="Exempted",
    )[0] == "expt_amt"
    assert resolve_nil_amount_column_from_sr_raw(
        invoice_type="NIL_RATED", invoice_type_raw="Non-GST",
    )[0] == "ngsup_amt"


def test_resolve_lump_and_ambiguous():
    col, reason = resolve_nil_amount_column_from_sr_raw(
        invoice_type="NIL_RATED", invoice_type_raw="Nil Rated/Exempt",
    )
    assert col is None and reason == "lump_nil_exempt_non_gst"

    col2, reason2 = resolve_nil_amount_column_from_sr_raw(
        invoice_type="NIL_RATED", invoice_type_raw=None,
    )
    assert col2 is None and reason2 == "lump_nil_exempt_non_gst"

    col3, reason3 = resolve_nil_amount_column_from_sr_raw(
        invoice_type="NIL_RATED", invoice_type_raw="Exempt Nil Rated",
    )
    assert col3 is None and reason3 == "nil_bucket_ambiguous"


def test_happy_path_all_four_sply_ty_and_three_columns():
    rows = [
        # INTRB2C nil
        _nil_sr(
            invoice_number_raw="N1",
            invoice_type_raw="Nil Rated",
            place_of_supply="27-Maharashtra",
            taxable_amount_paise=1_000_00,
        ),
        # INTRB2B exempt
        _nil_sr(
            invoice_number_raw="E1",
            invoice_type_raw="Exempt",
            gstin=GSTIN_OK,
            gstin_valid=True,
            place_of_supply="27-Maharashtra",
            taxable_amount_paise=2_000_00,
        ),
        # INTERB2C non-GST
        _nil_sr(
            invoice_number_raw="G1",
            invoice_type_raw="Non-GST",
            place_of_supply="07-Delhi",
            taxable_amount_paise=3_000_00,
        ),
        # INTERB2B nil
        _nil_sr(
            invoice_number_raw="N2",
            invoice_type_raw="Nil Rated",
            gstin=GSTIN_OK,
            gstin_valid=True,
            place_of_supply="07-Delhi",
            taxable_amount_paise=4_000_00,
        ),
        # Second INTRB2C nil → same bucket
        _nil_sr(
            invoice_number_raw="N3",
            invoice_type_raw="Nil Rated",
            place_of_supply="27-Maharashtra",
            taxable_amount_paise=500_00,
        ),
    ]
    result = map_sales_register_to_gstr1_nil(
        rows, filer_state=FILER_MH, filing_period=PERIOD,
    )
    assert result.needs_external_input is None
    assert result.pending_count == 0
    assert result.nil is not None
    by_ty = {r["sply_ty"]: r for r in result.nil["inv"]}
    assert set(by_ty) == {"INTRB2C", "INTRB2B", "INTERB2C", "INTERB2B"}
    assert by_ty["INTRB2C"]["nil_amt"] == 1_500.0
    assert by_ty["INTRB2C"]["expt_amt"] == 0.0
    assert by_ty["INTRB2B"]["expt_amt"] == 2_000.0
    assert by_ty["INTERB2C"]["ngsup_amt"] == 3_000.0
    assert by_ty["INTERB2B"]["nil_amt"] == 4_000.0


def test_lump_row_blocks_whole_table():
    rows = [
        _nil_sr(invoice_type_raw="Nil Rated"),
        _nil_sr(invoice_number_raw="LUMP", invoice_type_raw="Nil Rated/Exempt"),
    ]
    result = map_sales_register_to_gstr1_nil(
        rows, filer_state=FILER_MH, filing_period=PERIOD,
    )
    assert result.nil is None
    assert result.blocked_by_external_input is True
    assert result.needs_external_input is not None
    assert result.needs_external_input.table == TABLE_NIL
    assert result.needs_external_input.reason == "sr_lumps_nil_exempt_non_gst"
    assert result.lump_line_count == 1


def test_mixed_clear_and_lump_blocks_whole_table():
    rows = [
        _nil_sr(invoice_type_raw="Exempt", taxable_amount_paise=5_000_00),
        _nil_sr(invoice_number_raw="L", invoice_type_raw=None),  # derived lump
    ]
    result = map_sales_register_to_gstr1_nil(
        rows, filer_state=FILER_MH, filing_period=PERIOD,
    )
    assert result.nil is None
    assert result.needs_external_input is not None
    assert result.lump_line_count == 1


def test_ambiguous_raw_pending_review_blocks_save():
    rows = [
        _nil_sr(invoice_type_raw="Nil Rated"),
        _nil_sr(
            invoice_number_raw="AMB",
            invoice_type_raw="Exempt Nil Rated",
        ),
    ]
    result = map_sales_register_to_gstr1_nil(
        rows, filer_state=FILER_MH, filing_period=PERIOD,
    )
    assert result.nil is None
    assert result.needs_external_input is None
    assert result.pending_count == 1
    assert result.pending_review[0].reason == "nil_bucket_ambiguous"


def test_missing_filer_state_fails_whole_call():
    with pytest.raises(MissingFilerStateError):
        map_sales_register_to_gstr1_nil(
            [_nil_sr()], filer_state="", filing_period=PERIOD,
        )


def test_no_nil_class_rows_omits_cleanly():
    result = map_sales_register_to_gstr1_nil(
        [{
            "invoice_type": "B2B",
            "invoice_type_raw": "Tax Invoice",
            "gstin": GSTIN_OK,
            "gstin_valid": True,
            "place_of_supply": "27-Maharashtra",
            "taxable_amount_paise": 100_000,
            "igst_paise": 0,
            "cgst_paise": 9_000,
            "sgst_paise": 9_000,
            "tax_rate": 18.0,
        }],
        filer_state=FILER_MH,
        filing_period=PERIOD,
    )
    assert result.nil is None
    assert result.needs_external_input is None
    assert result.nil_class_line_count == 0
    assert result.skipped_non_nil == 1


def test_nil_row_has_gst_uses_shared_tolerance_not_strict_zero():
    # Within ±₹1 → OK
    ok = _nil_sr(
        invoice_type_raw="Nil Rated",
        cgst_paise=50,  # ₹0.50
        sgst_paise=40,  # ₹0.40 → total ₹0.90 ≤ ₹1
    )
    # Above ±₹1 → review
    bad = _nil_sr(
        invoice_number_raw="TAXED",
        invoice_type_raw="Exempt",
        cgst_paise=100_00,  # ₹100
        sgst_paise=100_00,
    )
    result = map_sales_register_to_gstr1_nil(
        [ok, bad], filer_state=FILER_MH, filing_period=PERIOD,
    )
    assert result.needs_external_input is None
    # bad held in review; ok still unambiguous → Save proceeds for ok
    assert any(p.reason == "nil_row_has_gst" for p in result.pending_review)
    assert result.save_row_count == 1
    assert result.nil["inv"][0]["nil_amt"] == 10_000.0

    # Boundary: exactly ₹1.01 should flag
    over = _nil_sr(
        invoice_type_raw="Nil Rated",
        cgst_paise=int((TAX_RATE_AMOUNT_TOLERANCE_RUPEES + 0.01) * 100),
        sgst_paise=0,
    )
    r2 = map_sales_register_to_gstr1_nil(
        [over], filer_state=FILER_MH, filing_period=PERIOD,
    )
    assert r2.pending_review[0].reason == "nil_row_has_gst"
    assert r2.nil is None  # no clear_valid left
