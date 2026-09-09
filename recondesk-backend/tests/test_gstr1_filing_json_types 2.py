"""GSTN Save JSON types (int vs float) + counterparty GSTIN checksum."""

from __future__ import annotations

import json
import re

import pytest

from app.filing.gstr1_filing_mapper import (
    _gstn_finalize_amounts,
    _gstn_json_number,
    _validated_counterparty_gstin,
    map_sales_register_to_gstr1_b2b,
    map_sales_register_to_gstr1_b2cs,
)
from app.rules.gstr1_mismatch_rules import gstin_format_ok
from app.services.normalizer import NormalizationError, normalize_gstin


def _wire(obj) -> str:
    """Serialize exactly as httpx/json would on the wire."""
    return json.dumps(obj, separators=(",", ":"))


def _b2b_rec(**overrides):
    base = {
        "row_number": 2,
        "gstin": "27AAECO5678G1Z2",
        "gstin_valid": True,
        "invoice_type": "B2B",
        "invoice_type_raw": None,
        "invoice_number": "RDPROBE001",
        "invoice_number_normalized": "RDPROBE001",
        "invoice_number_raw": "RDPROBE001",
        "invoice_date": "2026-07-15",
        "place_of_supply": "27-Maharashtra",
        "reverse_charge": False,
        "taxable_amount_paise": 100000,
        "igst_paise": 0,
        "cgst_paise": 9000,
        "sgst_paise": 9000,
        "cess_paise": 0,
        "total_tax_paise": 18000,
        "total_amount_paise": 118000,
        "tax_rate": 18.0,  # float upstream — must still emit JSON int
    }
    base.update(overrides)
    return base


def test_gstn_json_number_whole_becomes_int_fraction_stays_float():
    assert _gstn_json_number(18.0) == 18
    assert isinstance(_gstn_json_number(18.0), int)
    assert _gstn_json_number(0.0) == 0
    assert isinstance(_gstn_json_number(0.0), int)
    assert _gstn_json_number(1000.5) == 1000.5
    assert isinstance(_gstn_json_number(1000.5), float)
    assert _gstn_json_number(0.25) == 0.25


def test_b2b_save_rt_and_csamt_are_json_integers_not_floats():
    """Wire JSON must not contain ``"rt":18.0`` / ``"csamt":0.0`` for wholes."""
    result = map_sales_register_to_gstr1_b2b([_b2b_rec()])
    assert result.save_invoice_count == 1
    inv = result.b2b[0]["inv"][0]
    det = inv["itms"][0]["itm_det"]

    assert isinstance(det["rt"], int)
    assert isinstance(det["csamt"], int)
    assert isinstance(inv["itms"][0]["num"], int)

    wire = _wire(result.b2b)
    # Explicit decimal-point check — isinstance alone can hide float/int drift.
    assert re.search(r'"rt":\d+\.', wire) is None, wire
    assert re.search(r'"csamt":\d+\.', wire) is None, wire
    assert '"rt":18' in wire
    assert '"csamt":0' in wire


def test_b2cs_save_rt_csamt_json_integer_types():
    rec = {
        "row_number": 3,
        "gstin": None,
        "gstin_valid": False,
        "invoice_type": "B2C",
        "invoice_number_raw": "B2C-1",
        "invoice_date": "2026-07-10",
        "place_of_supply": "27",
        "taxable_amount_paise": 50000,
        "igst_paise": 0,
        "cgst_paise": 4500,
        "sgst_paise": 4500,
        "cess_paise": 0,
        "total_amount_paise": 59000,
        "tax_rate": 18.0,
    }
    result = map_sales_register_to_gstr1_b2cs([rec], filer_state="27", filing_period="2026-07")
    assert result.bucket_count == 1
    row = result.b2cs[0]
    assert isinstance(row["rt"], int)
    assert isinstance(row["csamt"], int)
    wire = _wire(result.b2cs)
    assert re.search(r'"rt":\d+\.', wire) is None, wire
    assert re.search(r'"csamt":\d+\.', wire) is None, wire


def test_finalize_preserves_fractional_rate_as_float_in_json():
    frag = _gstn_finalize_amounts({"rt": 0.25, "csamt": 1.5, "txval": 100.0})
    assert frag["rt"] == 0.25
    assert isinstance(frag["rt"], float)
    assert frag["csamt"] == 1.5
    assert isinstance(frag["txval"], int)  # 100.0 → 100
    wire = _wire(frag)
    assert '"rt":0.25' in wire
    assert '"txval":100' in wire
    assert '"txval":100.0' not in wire


def test_g1m7_gstin_format_ok_is_regex_only_not_checksum():
    """Document why filing must not reuse gstin_format_ok for Save ctin."""
    bad = "27AABCU9603R1ZM"  # format OK, check digit wrong (should be N)
    assert gstin_format_ok(bad) is True
    with pytest.raises(NormalizationError) as ei:
        normalize_gstin(bad)
    assert ei.value.reason == "invalid_checksum"
    assert _validated_counterparty_gstin(bad) is None
    assert _validated_counterparty_gstin("27AABCU9603R1ZN") == "27AABCU9603R1ZN"


def test_b2b_rejects_checksum_invalid_ctin_even_if_gstin_valid_flag_true():
    """Mapper re-validates check digit; cannot trust gstin_valid alone."""
    rec = _b2b_rec(gstin="27AABCU9603R1ZM", gstin_valid=True)
    result = map_sales_register_to_gstr1_b2b([rec])
    assert result.save_invoice_count == 0
    assert result.skipped_non_b2b == 1
