"""Unit tests for GSTR-3B filing payload mapper and system figure helpers."""

from __future__ import annotations

from app.filing.gstr3b_filing_mapper import (
    apply_system_late_fee_to_save_body,
    extract_system_late_fee,
)


def test_extract_system_late_fee_handles_nonzero_and_zero():
    # Nonzero late fee (late-filed period)
    details_late = {
        "intr_ltfee": {
            "ltfee_details": {
                "camt": 150.0,
                "samt": 150.0,
            }
        }
    }
    assert extract_system_late_fee(details_late) == {"camt": 150, "samt": 150}

    # Zero late fee (on-time period)
    details_ontime = {
        "intr_ltfee": {
            "ltfee_details": {
                "camt": 0.0,
                "samt": 0.0,
            }
        }
    }
    assert extract_system_late_fee(details_ontime) == {"camt": 0, "samt": 0}

    # Missing or empty details
    assert extract_system_late_fee(None) == {"camt": 0, "samt": 0}
    assert extract_system_late_fee({}) == {"camt": 0, "samt": 0}


def test_apply_system_late_fee_preserves_nonzero_late_fee():
    """Reproduces original bug: save_body has zero late fee but GSTN system has nonzero late fee.

    The mapper must preserve GSTN's system late fee in ltfee_details and not zero it out.
    """
    save_body_from_form = {
        "gstin": "27ISKPK1273H1ZF",
        "ret_period": "062026",
        "intr_ltfee": {
            "intr_details": {"iamt": 0, "camt": 0, "samt": 0, "csamt": 0},
            "ltfee_details": {"camt": 0, "samt": 0},  # Form submitted zero
        },
    }
    details_data_from_gstn = {
        "intr_ltfee": {
            "ltfee_details": {
                "camt": 150.0,
                "samt": 150.0,
            }
        }
    }

    result = apply_system_late_fee_to_save_body(save_body_from_form, details_data_from_gstn)
    assert result["intr_ltfee"]["ltfee_details"] == {"camt": 150, "samt": 150}


def test_apply_system_late_fee_preserves_zero_late_fee_for_ontime():
    """On-time filing period where GSTN system late fee is zero: zero passes through as-is."""
    save_body_from_form = {
        "gstin": "27ISKPK1273H1ZF",
        "ret_period": "062026",
        "intr_ltfee": {
            "intr_details": {"iamt": 0, "camt": 0, "samt": 0, "csamt": 0},
            "ltfee_details": {"camt": 0, "samt": 0},
        },
    }
    details_data_from_gstn = {
        "intr_ltfee": {
            "ltfee_details": {
                "camt": 0.0,
                "samt": 0.0,
            }
        }
    }

    result = apply_system_late_fee_to_save_body(save_body_from_form, details_data_from_gstn)
    assert result["intr_ltfee"]["ltfee_details"] == {"camt": 0, "samt": 0}
