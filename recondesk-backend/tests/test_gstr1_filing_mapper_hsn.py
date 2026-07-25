"""GSTR-1 HSN filing mapper — SR → Sandbox hsn.hsn_b2b / hsn.hsn_b2c."""

from __future__ import annotations

import pytest

from app.filing.gstr1_external_input import TABLE_HSN
from app.filing.gstr1_filing_mapper import map_sales_register_to_gstr1_hsn


GSTIN_OK = "27AAECO5678G1Z2"
PERIOD = "2025-04"


def _goods_b2b(**overrides):
    base = {
        "gstin": GSTIN_OK,
        "gstin_valid": True,
        "invoice_type": "B2B",
        "invoice_number_raw": "G-001",
        "invoice_date": "2025-04-08",
        "place_of_supply": "27-Maharashtra",
        "hsn": "87089900",
        "uqc": "NOS",
        "qty": 2,
        "taxable_amount_paise": 100_000_00,  # ₹100,000
        "igst_paise": 0,
        "cgst_paise": 9_000_00,
        "sgst_paise": 9_000_00,
        "cess_paise": 0,
        "total_amount_paise": 118_000_00,
        "tax_rate": 18.0,
    }
    base.update(overrides)
    return base


def _svc_b2c(**overrides):
    base = {
        "gstin": None,
        "gstin_valid": False,
        "invoice_type": "B2C",
        "invoice_number_raw": "S-001",
        "invoice_date": "2025-04-08",
        "place_of_supply": "27-Maharashtra",
        "hsn": "998314",
        # no uqc/qty — services default NA/0
        "taxable_amount_paise": 10_000_00,
        "igst_paise": 0,
        "cgst_paise": 900_00,
        "sgst_paise": 900_00,
        "cess_paise": 0,
        "total_amount_paise": 11_800_00,
        "tax_rate": 18.0,
    }
    base.update(overrides)
    return base


def test_happy_path_mixed_goods_services_aggregates_by_hsn_uqc_rt():
    rows = [
        _goods_b2b(invoice_number_raw="G-1", qty=2),
        _goods_b2b(
            invoice_number_raw="G-2",
            qty=3,
            taxable_amount_paise=50_000_00,
            cgst_paise=4_500_00,
            sgst_paise=4_500_00,
            total_amount_paise=59_000_00,
        ),
        # Same HSN+UQC+rt → one B2B bucket
        _svc_b2c(invoice_number_raw="S-1"),
        _svc_b2c(
            invoice_number_raw="S-2",
            hsn="998314",
            taxable_amount_paise=5_000_00,
            cgst_paise=450_00,
            sgst_paise=450_00,
            total_amount_paise=5_900_00,
        ),
        # Different rate → separate bucket
        _goods_b2b(
            invoice_number_raw="G-5",
            tax_rate=5.0,
            hsn="87089900",
            uqc="NOS",
            qty=1,
            taxable_amount_paise=20_000_00,
            cgst_paise=500_00,
            sgst_paise=500_00,
            total_amount_paise=21_000_00,
        ),
    ]
    result = map_sales_register_to_gstr1_hsn(rows, filing_period=PERIOD)
    assert result.needs_external_input is None
    assert result.pending_count == 0
    assert result.blocked_by_external_input is False

    b2b = result.hsn["hsn_b2b"]
    b2c = result.hsn["hsn_b2c"]
    assert len(b2b) == 2  # 18% and 5%
    assert len(b2c) == 1

    by_rt = {r["rt"]: r for r in b2b}
    assert by_rt[18.0]["hsn_sc"] == "87089900"
    assert by_rt[18.0]["uqc"] == "NOS"
    assert by_rt[18.0]["qty"] == 5.0  # 2+3
    assert by_rt[18.0]["txval"] == 150_000.0
    assert by_rt[18.0]["camt"] == 13_500.0
    assert by_rt[18.0]["samt"] == 13_500.0
    assert by_rt[18.0]["iamt"] == 0.0
    assert by_rt[18.0]["num"] in {1, 2}

    assert by_rt[5.0]["txval"] == 20_000.0
    assert by_rt[5.0]["qty"] == 1.0

    svc = b2c[0]
    assert svc["hsn_sc"] == "998314"
    assert svc["uqc"] == "NA"
    assert svc["qty"] == 0.0
    assert svc["txval"] == 15_000.0
    assert svc["camt"] == 1_350.0
    assert svc["num"] == 1


def test_malformed_hsn_goes_to_pending_review_not_external():
    good = _goods_b2b()
    bad = _goods_b2b(invoice_number_raw="BAD", hsn="87AB")
    result = map_sales_register_to_gstr1_hsn([good, bad], filing_period=PERIOD)
    assert result.needs_external_input is None
    assert result.save_row_count == 1
    assert result.pending_count == 1
    assert result.pending_review[0].reason == "malformed_hsn_code"


def test_missing_hsn_on_goods_line_blocks_whole_table():
    good = _goods_b2b()
    missing = _goods_b2b(invoice_number_raw="NO-HSN", hsn=None)
    # even with uqc/qty present, missing HSN blocks all
    result = map_sales_register_to_gstr1_hsn([good, missing], filing_period=PERIOD)
    assert result.hsn == {"hsn_b2b": [], "hsn_b2c": []}
    assert result.save_row_count == 0
    assert result.blocked_by_external_input is True
    gap = result.needs_external_input
    assert gap is not None
    assert gap.table == TABLE_HSN
    assert gap.filing_period == PERIOD
    assert gap.reason == "sr_lacks_hsn_code"
    assert result.coverage_gap_line_count == 1
    assert result.taxable_line_count == 2


def test_goods_missing_uqc_qty_blocks_whole_table():
    row = _goods_b2b()
    del row["uqc"]
    del row["qty"]
    result = map_sales_register_to_gstr1_hsn([row], filing_period=PERIOD)
    assert result.save_row_count == 0
    assert result.needs_external_input is not None
    assert result.needs_external_input.reason == "sr_lacks_uqc_qty"
    assert result.needs_external_input.missing_fields == ("uqc", "qty")


def test_services_only_missing_uqc_qty_saves_with_na_zero_defaults():
    """Services-only period: well-formed SAC, no uqc/qty → Save with NA/0."""
    rows = [
        _svc_b2c(invoice_number_raw="S-A"),
        _svc_b2c(invoice_number_raw="S-B", hsn="998399"),
    ]
    result = map_sales_register_to_gstr1_hsn(rows, filing_period=PERIOD)
    assert result.needs_external_input is None
    assert result.pending_count == 0
    assert result.save_row_count == 2
    for row in result.hsn["hsn_b2c"]:
        assert row["uqc"] == "NA"
        assert row["qty"] == 0.0


def test_tax_amount_inconsistent_with_rate_reused():
    bad = _goods_b2b(igst_paise=0, cgst_paise=1_000_00, sgst_paise=1_000_00)
    # 18% of 100000 = 18000; claimed 2000 → fail
    good = _svc_b2c()
    result = map_sales_register_to_gstr1_hsn([bad, good], filing_period=PERIOD)
    # goods line reviewed; services still Save (no coverage gap)
    assert result.needs_external_input is None
    assert any(
        p.reason == "tax_amount_inconsistent_with_rate" for p in result.pending_review
    )
    assert result.save_row_count == 1
    assert result.hsn["hsn_b2c"][0]["hsn_sc"] == "998314"


def test_nil_rated_skipped():
    result = map_sales_register_to_gstr1_hsn(
        [{
            "invoice_type": "NIL_RATED",
            "hsn": "1001",
            "taxable_amount_paise": 0,
            "tax_rate": 0.0,
        }],
        filing_period=PERIOD,
    )
    assert result.taxable_line_count == 0
    assert result.skipped_non_hsn == 1
    assert result.save_row_count == 0


def test_wrong_digit_count_malformed():
    result = map_sales_register_to_gstr1_hsn(
        [_goods_b2b(hsn="870")],  # 3 digits
        filing_period=PERIOD,
    )
    assert result.pending_review[0].reason == "malformed_hsn_code"
    assert result.needs_external_input is None


def test_filing_period_required_format():
    with pytest.raises(ValueError, match="YYYY-MM"):
        map_sales_register_to_gstr1_hsn([_goods_b2b()], filing_period="04-2025")
