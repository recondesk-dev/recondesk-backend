"""GSTR-1 CDNUR filing mapper — cdnur_candidates → Sandbox cdnur[]."""

from __future__ import annotations

import pytest

from app.filing.gstr1_filing_mapper import (
    MissingFilerStateError,
    map_sales_register_to_gstr1_cdnr,
    map_sales_register_to_gstr1_cdnur,
)
from app.filing.gstr1_thresholds import (
    B2CL_INVOICE_VALUE_FROM_PAISE,
    b2cl_invoice_value_threshold_paise,
)


FILER_MH = "27"


def _ur_note(**overrides):
    """Unregistered INTER note above post-cutover ₹1L (CDNUR B2CL shape)."""
    over = B2CL_INVOICE_VALUE_FROM_PAISE + 100
    txval_paise = int(round(over / 1.18))
    igst_paise = over - txval_paise
    base = {
        "gstin": None,
        "gstin_valid": False,
        "invoice_type": "CREDIT_NOTE",
        "invoice_type_raw": None,
        "invoice_number_raw": "CN-UR-001",
        "invoice_date": "2025-04-08",
        "place_of_supply": "07-Delhi",
        "taxable_amount_paise": -txval_paise,
        "igst_paise": -igst_paise,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": None,
        "total_amount_paise": -over,
        "tax_rate": 18.0,
    }
    base.update(overrides)
    return base


def test_missing_filer_state_fails_whole_batch():
    with pytest.raises(MissingFilerStateError):
        map_sales_register_to_gstr1_cdnur(
            [_ur_note()],
            filer_state="",
            filing_period="2025-04",
        )


def test_happy_path_b2cl_typ_from_cdnr_handoff():
    cdnr = map_sales_register_to_gstr1_cdnr([_ur_note()], filer_state=FILER_MH)
    assert len(cdnr.cdnur_candidates) == 1

    result = map_sales_register_to_gstr1_cdnur(
        cdnr.cdnur_candidates,
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert result.pending_count == 0
    assert result.b2cs_net_candidates == []
    assert result.threshold_paise == B2CL_INVOICE_VALUE_FROM_PAISE
    assert result.threshold_paise == b2cl_invoice_value_threshold_paise("2025-04")
    assert result.save_note_count == 1
    note = result.cdnur[0]
    assert note["typ"] == "B2CL"
    assert note["ntty"] == "C"
    assert note["nt_num"] == "CN-UR-001"
    assert note["nt_dt"] == "08-04-2025"
    assert note["pos"] == "07"
    assert note["itms"][0]["itm_det"]["csamt"] == 0.0
    assert "camt" not in note["itms"][0]["itm_det"]


def test_intra_routes_to_b2cs_net_candidates_not_cdnur():
    rec = _ur_note(
        place_of_supply="27-Maharashtra",
        invoice_number_raw="CN-INTRA",
        # INTRA amounts — still need reconciling tax for net snapshot
        taxable_amount_paise=-100_000,
        cgst_paise=-9_000,
        sgst_paise=-9_000,
        igst_paise=0,
        total_amount_paise=-118_000,
    )
    result = map_sales_register_to_gstr1_cdnur(
        [rec], filer_state=FILER_MH, filing_period="2025-04",
    )
    assert result.cdnur == []
    assert len(result.b2cs_net_candidates) == 1
    net = result.b2cs_net_candidates[0]
    assert net.reason == "intra"
    assert net.sply_ty == "INTRA"
    assert net.nt_num == "CN-INTRA"
    assert net.pos == "27"
    assert net.ntty == "C"
    assert net.val_paise == 118_000
    assert net.tax_rate == 18.0
    assert net.taxable_amount_paise == 100_000
    assert net.cgst_paise == 9_000
    assert net.sgst_paise == 9_000
    assert net.igst_paise == 0
    assert net.record is rec  # original SR row retained


def test_inter_at_or_below_threshold_routes_to_b2cs_net():
    exact = B2CL_INVOICE_VALUE_FROM_PAISE
    txval = int(round(exact / 1.18))
    igst = exact - txval
    rec = _ur_note(
        invoice_number_raw="CN-AT-THR",
        taxable_amount_paise=txval,
        igst_paise=igst,
        total_amount_paise=exact,
    )
    result = map_sales_register_to_gstr1_cdnur(
        [rec], filer_state=FILER_MH, filing_period="2025-04",
    )
    assert result.cdnur == []
    assert len(result.b2cs_net_candidates) == 1
    assert result.b2cs_net_candidates[0].reason == "inter_at_or_below_threshold"
    assert result.b2cs_net_candidates[0].sply_ty == "INTER"
    assert result.b2cs_net_candidates[0].val_paise == exact


def test_threshold_boundary_plus_one_is_cdnur_b2cl():
    over = B2CL_INVOICE_VALUE_FROM_PAISE + 1
    txval = int(round(over / 1.18))
    igst = over - txval
    result = map_sales_register_to_gstr1_cdnur(
        [
            _ur_note(
                taxable_amount_paise=txval,
                igst_paise=igst,
                total_amount_paise=over,
            )
        ],
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert result.b2cs_net_candidates == []
    assert result.save_note_count == 1
    assert result.cdnur[0]["typ"] == "B2CL"


def test_export_signal_deferred_to_review():
    result = map_sales_register_to_gstr1_cdnur(
        [
            _ur_note(
                place_of_supply="96-Foreign Country",
                invoice_number_raw="CN-EXP",
            )
        ],
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert result.cdnur == []
    assert result.b2cs_net_candidates == []
    assert result.pending_review[0].reason == "cdnur_export_typ_needs_review"

    result2 = map_sales_register_to_gstr1_cdnur(
        [
            _ur_note(
                shipping_bill_number="SB-1",
                invoice_number_raw="CN-SB",
            )
        ],
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert result2.pending_review[0].reason == "cdnur_export_typ_needs_review"


def test_pending_missing_fields():
    assert (
        map_sales_register_to_gstr1_cdnur(
            [_ur_note(invoice_number_raw=None)],
            filer_state=FILER_MH,
            filing_period="2025-04",
        ).pending_review[0].reason
        == "missing_nt_num"
    )
    assert (
        map_sales_register_to_gstr1_cdnur(
            [_ur_note(invoice_date=None)],
            filer_state=FILER_MH,
            filing_period="2025-04",
        ).pending_review[0].reason
        == "missing_or_invalid_nt_dt"
    )
    assert (
        map_sales_register_to_gstr1_cdnur(
            [_ur_note(place_of_supply=None)],
            filer_state=FILER_MH,
            filing_period="2025-04",
        ).pending_review[0].reason
        == "missing_or_malformed_pos"
    )
    rec = _ur_note()
    del rec["tax_rate"]
    assert (
        map_sales_register_to_gstr1_cdnur(
            [rec], filer_state=FILER_MH, filing_period="2025-04",
        ).pending_review[0].reason
        == "missing_tax_rate"
    )
    assert (
        map_sales_register_to_gstr1_cdnur(
            [_ur_note(taxable_amount_paise=None)],
            filer_state=FILER_MH,
            filing_period="2025-04",
        ).pending_review[0].reason
        == "missing_taxable_value"
    )
    assert (
        map_sales_register_to_gstr1_cdnur(
            [_ur_note(total_amount_paise=None)],
            filer_state=FILER_MH,
            filing_period="2025-04",
        ).pending_review[0].reason
        == "missing_invoice_value_for_b2cl_gate"
    )


def test_pending_tax_amount_inconsistent_with_rate():
    result = map_sales_register_to_gstr1_cdnur(
        [
            _ur_note(
                taxable_amount_paise=10_000_000,
                igst_paise=1_000,
                total_amount_paise=B2CL_INVOICE_VALUE_FROM_PAISE + 100,
                tax_rate=18.0,
            )
        ],
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert result.pending_review[0].reason == "tax_amount_inconsistent_with_rate"
    assert result.cdnur == []


def test_b2cs_net_candidates_consumed_by_apply_b2cs_netting():
    """CDNUR hand-off fields are enough for the second-pass netting step."""
    from app.filing.gstr1_filing_mapper import apply_b2cs_netting

    result = map_sales_register_to_gstr1_cdnur(
        [
            _ur_note(
                place_of_supply="27-Maharashtra",
                invoice_number_raw="GAP-1",
                taxable_amount_paise=100_000,
                cgst_paise=9_000,
                sgst_paise=9_000,
                igst_paise=0,
                total_amount_paise=118_000,
            )
        ],
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert result.cdnur == []
    assert len(result.b2cs_net_candidates) == 1
    net = result.b2cs_net_candidates[0]
    for attr in (
        "nt_num", "ntty", "pos", "sply_ty", "val_paise", "tax_rate",
        "taxable_amount_paise", "igst_paise", "cgst_paise", "sgst_paise",
        "cess_paise", "record", "reason",
    ):
        assert hasattr(net, attr)

    # CN alone → negative bucket → review (not silent Save of negatives).
    netted = apply_b2cs_netting([], result.b2cs_net_candidates, filer_state=FILER_MH)
    assert netted.b2cs == []
    assert netted.applied_candidate_count == 1
    assert netted.pending_review[0].reason == "b2cs_net_negative_bucket"
