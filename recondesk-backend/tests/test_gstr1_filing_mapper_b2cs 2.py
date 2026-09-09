"""GSTR-1 B2CS filing mapper — SR B2C rows → Sandbox consolidated b2cs[]."""

from __future__ import annotations

import pytest

from app.filing.gstr1_filing_mapper import (
    MissingFilerStateError,
    map_sales_register_to_gstr1_b2cs,
    require_filer_state,
)
from app.filing.gstr1_thresholds import (
    B2CL_CUTOVER_PERIOD,
    B2CL_INVOICE_VALUE_BEFORE_PAISE,
    B2CL_INVOICE_VALUE_FROM_PAISE,
    b2cl_invoice_value_threshold_paise,
)


FILER_MH = "27"  # Maharashtra filer state


def _b2c_sr(**overrides):
    base = {
        "row_number": 2,
        "gstin": None,
        "gstin_valid": False,
        "invoice_type": "B2C",
        "invoice_type_raw": None,
        "invoice_number": "CASH001",
        "invoice_number_normalized": "CASH001",
        "invoice_number_raw": "CASH-001",
        "invoice_date": "2025-04-08",
        "place_of_supply": "27-Maharashtra",
        "reverse_charge": False,
        "taxable_amount_paise": 100000,  # ₹1,000
        "igst_paise": 0,
        "cgst_paise": 9000,
        "sgst_paise": 9000,
        "cess_paise": 0,
        "total_tax_paise": 18000,
        "total_amount_paise": 118000,  # ₹1,180
        "tax_rate": 18.0,
    }
    base.update(overrides)
    return base


def test_threshold_period_aware_constants():
    assert B2CL_CUTOVER_PERIOD == "2024-08"
    assert B2CL_INVOICE_VALUE_BEFORE_PAISE == 25_000_000
    assert B2CL_INVOICE_VALUE_FROM_PAISE == 10_000_000
    assert b2cl_invoice_value_threshold_paise("2024-07") == 25_000_000
    assert b2cl_invoice_value_threshold_paise("2024-08") == 10_000_000
    assert b2cl_invoice_value_threshold_paise("2025-04") == 10_000_000


def test_missing_filer_state_fails_whole_batch():
    with pytest.raises(MissingFilerStateError):
        map_sales_register_to_gstr1_b2cs(
            [_b2c_sr()],
            filer_state="",
            filing_period="2025-04",
        )
    with pytest.raises(MissingFilerStateError):
        require_filer_state(None)
    with pytest.raises(MissingFilerStateError):
        require_filer_state("XX")


def test_happy_path_aggregates_same_pos_rate_bucket():
    """Two INTRA B2C rows at same POS+rate → one b2cs row with summed amounts."""
    rows = [
        _b2c_sr(
            invoice_number_raw="A1",
            taxable_amount_paise=100000,
            cgst_paise=9000,
            sgst_paise=9000,
            total_amount_paise=118000,
        ),
        _b2c_sr(
            invoice_number_raw="A2",
            taxable_amount_paise=200000,
            cgst_paise=18000,
            sgst_paise=18000,
            total_amount_paise=236000,
        ),
        # Different rate → second bucket
        _b2c_sr(
            invoice_number_raw="B1",
            tax_rate=5.0,
            taxable_amount_paise=100000,
            cgst_paise=2500,
            sgst_paise=2500,
            total_amount_paise=105000,
        ),
    ]
    result = map_sales_register_to_gstr1_b2cs(
        rows, filer_state=FILER_MH, filing_period="2025-04",
    )
    assert result.pending_count == 0
    assert result.b2cl_candidates == []
    assert result.skipped_non_b2c == 0
    assert result.threshold_paise == B2CL_INVOICE_VALUE_FROM_PAISE
    assert result.b2cs == [
        {
            "sply_ty": "INTRA",
            "pos": "27",
            "rt": 5.0,
            "typ": "OE",
            "txval": 1000.0,
            "iamt": 0.0,
            "camt": 25.0,
            "samt": 25.0,
            "csamt": 0.0,
        },
        {
            "sply_ty": "INTRA",
            "pos": "27",
            "rt": 18.0,
            "typ": "OE",
            "txval": 3000.0,
            "iamt": 0.0,
            "camt": 270.0,
            "samt": 270.0,
            "csamt": 0.0,
        },
    ]


def test_inter_below_threshold_goes_to_b2cs():
    result = map_sales_register_to_gstr1_b2cs(
        [
            _b2c_sr(
                place_of_supply="07-Delhi",
                taxable_amount_paise=50_000_00,  # ₹50,000
                igst_paise=9_000_00,
                cgst_paise=0,
                sgst_paise=0,
                total_amount_paise=59_000_00,
            )
        ],
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert result.pending_count == 0
    assert result.b2cl_candidates == []
    assert len(result.b2cs) == 1
    assert result.b2cs[0]["sply_ty"] == "INTER"
    assert result.b2cs[0]["pos"] == "07"
    assert result.b2cs[0]["iamt"] == 9000.0


def test_boundary_exactly_at_threshold_is_b2cs_not_b2cl():
    """Invoice value == threshold → B2CS (gate is strictly greater-than)."""
    # Post-cutover threshold = ₹1L; tax must reconcile at 18%.
    exactly = B2CL_INVOICE_VALUE_FROM_PAISE
    txval_paise = int(round(exactly / 1.18))
    igst_paise = exactly - txval_paise
    result = map_sales_register_to_gstr1_b2cs(
        [
            _b2c_sr(
                place_of_supply="07-Delhi",
                taxable_amount_paise=txval_paise,
                igst_paise=igst_paise,
                cgst_paise=0,
                sgst_paise=0,
                total_amount_paise=exactly,
                tax_rate=18.0,
            )
        ],
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert result.pending_count == 0
    assert result.b2cl_candidates == []
    assert len(result.b2cs) == 1
    assert result.b2cs[0]["sply_ty"] == "INTER"

    # One paise over → B2CL candidate
    over = exactly + 1
    tx_over = int(round(over / 1.18))
    igst_over = over - tx_over
    over_result = map_sales_register_to_gstr1_b2cs(
        [
            _b2c_sr(
                place_of_supply="07-Delhi",
                taxable_amount_paise=tx_over,
                igst_paise=igst_over,
                cgst_paise=0,
                sgst_paise=0,
                total_amount_paise=over,
                tax_rate=18.0,
            )
        ],
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert over_result.b2cs == []
    assert len(over_result.b2cl_candidates) == 1
    assert over_result.pending_count == 0


def test_pre_cutover_period_uses_2_5l_threshold():
    """Before 2024-08, ₹2.5L gate — ₹1.5L INTER stays in B2CS."""
    value = 15_000_000  # ₹1.5L — above 1L, below 2.5L
    txval_paise = int(round(value / 1.18))
    igst_paise = value - txval_paise
    result = map_sales_register_to_gstr1_b2cs(
        [
            _b2c_sr(
                place_of_supply="07-Delhi",
                taxable_amount_paise=txval_paise,
                igst_paise=igst_paise,
                cgst_paise=0,
                sgst_paise=0,
                total_amount_paise=value,
                tax_rate=18.0,
            )
        ],
        filer_state=FILER_MH,
        filing_period="2024-07",
    )
    assert result.threshold_paise == B2CL_INVOICE_VALUE_BEFORE_PAISE
    assert result.pending_count == 0
    assert len(result.b2cs) == 1
    assert result.b2cl_candidates == []


def test_pending_review_missing_pos():
    result = map_sales_register_to_gstr1_b2cs(
        [_b2c_sr(place_of_supply=None)],
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert result.b2cs == []
    assert result.pending_count == 1
    assert result.pending_review[0].reason == "missing_or_malformed_pos"


def test_pending_review_malformed_pos():
    result = map_sales_register_to_gstr1_b2cs(
        [_b2c_sr(place_of_supply="Atlantis")],
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert result.pending_review[0].reason == "missing_or_malformed_pos"
    assert result.b2cs == []


def test_pending_review_missing_tax_rate():
    rec = _b2c_sr()
    del rec["tax_rate"]
    result = map_sales_register_to_gstr1_b2cs(
        [rec], filer_state=FILER_MH, filing_period="2025-04",
    )
    assert result.pending_review[0].reason == "missing_tax_rate"
    assert result.b2cs == []


def test_pending_review_missing_invoice_value_for_inter_b2cl_gate():
    rec = _b2c_sr(place_of_supply="07-Delhi")
    rec["total_amount_paise"] = None
    rec["taxable_amount_paise"] = None
    result = map_sales_register_to_gstr1_b2cs(
        [rec], filer_state=FILER_MH, filing_period="2025-04",
    )
    assert result.pending_review[0].reason == "missing_invoice_value_for_b2cl_gate"
    assert result.b2cs == []


def test_pending_review_interstate_flag_conflicts_with_pos():
    result = map_sales_register_to_gstr1_b2cs(
        [
            _b2c_sr(
                place_of_supply="27-Maharashtra",  # INTRA for filer 27
                is_interstate=True,  # conflict
            )
        ],
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert result.pending_review[0].reason == "interstate_flag_conflicts_with_pos"
    assert result.b2cs == []


def test_pending_review_label_vs_numbers_b2cl():
    """Explicit B2C_LARGE but INTRA (or under threshold) → review."""
    result = map_sales_register_to_gstr1_b2cs(
        [
            _b2c_sr(
                invoice_type="B2C_LARGE",
                place_of_supply="27-Maharashtra",
                total_amount_paise=50_000_00,
            )
        ],
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert result.pending_review[0].reason == "label_vs_numbers_b2cl"
    assert result.b2cs == []
    assert result.b2cl_candidates == []


def test_pending_review_label_vs_numbers_b2cs():
    """Explicit B2C_SMALL but INTER value above threshold → review."""
    over = B2CL_INVOICE_VALUE_FROM_PAISE + 1
    result = map_sales_register_to_gstr1_b2cs(
        [
            _b2c_sr(
                invoice_type="B2C_SMALL",
                place_of_supply="07-Delhi",
                taxable_amount_paise=over - 180000,
                igst_paise=180000,
                cgst_paise=0,
                sgst_paise=0,
                total_amount_paise=over,
            )
        ],
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert result.pending_review[0].reason == "label_vs_numbers_b2cs"
    assert result.b2cs == []
    assert result.b2cl_candidates == []


def test_clear_b2cl_candidate_not_in_b2cs_aggregate():
    over = B2CL_INVOICE_VALUE_FROM_PAISE + 100
    result = map_sales_register_to_gstr1_b2cs(
        [
            _b2c_sr(
                invoice_type="B2C_LARGE",
                place_of_supply="07-Delhi",
                taxable_amount_paise=over - 180000,
                igst_paise=180000,
                cgst_paise=0,
                sgst_paise=0,
                total_amount_paise=over,
            ),
            # Clean INTRA still aggregates
            _b2c_sr(invoice_number_raw="KEEP"),
        ],
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert len(result.b2cl_candidates) == 1
    assert result.pending_count == 0
    assert len(result.b2cs) == 1
    assert result.b2cs[0]["sply_ty"] == "INTRA"


def test_missing_pos_excludes_row_does_not_corrupt_bucket():
    """Bad POS must not land in any aggregate; clean sibling still Saves."""
    result = map_sales_register_to_gstr1_b2cs(
        [
            _b2c_sr(invoice_number_raw="GOOD", taxable_amount_paise=100000),
            _b2c_sr(invoice_number_raw="BAD", place_of_supply=""),
        ],
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert result.pending_count == 1
    assert result.pending_review[0].reason == "missing_or_malformed_pos"
    assert len(result.b2cs) == 1
    assert result.b2cs[0]["txval"] == 1000.0


def test_skips_b2b_rows():
    result = map_sales_register_to_gstr1_b2cs(
        [
            {
                "invoice_type": "B2B",
                "gstin": "27AAECO5678G1Z2",
                "gstin_valid": True,
                "place_of_supply": "27-Maharashtra",
                "tax_rate": 18.0,
                "taxable_amount_paise": 100000,
                "total_amount_paise": 118000,
            },
            _b2c_sr(),
        ],
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert result.skipped_non_b2c == 1
    assert len(result.b2cs) == 1


def test_b2cs_tax_amount_inconsistent_with_rate_goes_to_review():
    result = map_sales_register_to_gstr1_b2cs(
        [
            _b2c_sr(
                taxable_amount_paise=100000,
                cgst_paise=1,
                sgst_paise=1,
                igst_paise=0,
                tax_rate=18.0,
            )
        ],
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert result.b2cs == []
    assert result.pending_review[0].reason == "tax_amount_inconsistent_with_rate"
