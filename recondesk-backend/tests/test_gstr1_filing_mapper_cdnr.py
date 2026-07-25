"""GSTR-1 CDNR filing mapper — SR credit/debit notes → Sandbox cdnr[]."""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from app.filing.gstr1_filing_mapper import (
    MissingFilerStateError,
    map_sales_register_to_gstr1_cdnr,
    resolve_ntty_from_sr,
)
from app.parsers.sales_register_parser import parse_sales_register


FILER_MH = "27"
GSTIN_OK = "27AAECO5678G1Z2"


def _xlsx_bytes(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cdn_sr(**overrides):
    """Registered credit note with tax reconciling at 18%."""
    base = {
        "row_number": 2,
        "gstin": GSTIN_OK,
        "gstin_valid": True,
        "invoice_type": "CREDIT_NOTE",
        "invoice_type_raw": None,
        "invoice_number": "CN0042",
        "invoice_number_normalized": "CN0042",
        "invoice_number_raw": "CN/2025-26/0042",
        "invoice_date": "2025-04-08",
        "place_of_supply": "27-Maharashtra",
        "reverse_charge": False,
        "taxable_amount_paise": -1_000_000,  # SR often negative for CN
        "igst_paise": 0,
        "cgst_paise": -90_000,
        "sgst_paise": -90_000,
        "cess_paise": None,
        "total_tax_paise": -180_000,
        "total_amount_paise": -1_180_000,
        "tax_rate": 18.0,
    }
    base.update(overrides)
    return base


def test_missing_filer_state_fails_whole_batch():
    with pytest.raises(MissingFilerStateError):
        map_sales_register_to_gstr1_cdnr([_cdn_sr()], filer_state="")


def test_happy_path_credit_and_debit_grouped_by_ctin():
    credit = _cdn_sr()
    debit = _cdn_sr(
        invoice_type="DEBIT_NOTE",
        invoice_type_raw=None,
        invoice_number_raw="DN/2025-26/0007",
        taxable_amount_paise=500_000,
        cgst_paise=45_000,
        sgst_paise=45_000,
        igst_paise=0,
        total_amount_paise=590_000,
    )
    other_ctin = _cdn_sr(
        gstin="07AABCN6789S1ZD",
        invoice_number_raw="CN-OTHER",
        place_of_supply="07-Delhi",
        taxable_amount_paise=1_000_000,
        igst_paise=180_000,
        cgst_paise=0,
        sgst_paise=0,
        total_amount_paise=1_180_000,
    )
    result = map_sales_register_to_gstr1_cdnr(
        [credit, debit, other_ctin], filer_state=FILER_MH,
    )
    assert result.pending_count == 0
    assert result.cdnur_candidates == []
    assert result.save_note_count == 3
    assert {g["ctin"] for g in result.cdnr} == {GSTIN_OK, "07AABCN6789S1ZD"}

    by_ctin = {g["ctin"]: g for g in result.cdnr}
    nt_types = {n["ntty"] for n in by_ctin[GSTIN_OK]["nt"]}
    assert nt_types == {"C", "D"}
    cn = next(n for n in by_ctin[GSTIN_OK]["nt"] if n["ntty"] == "C")
    assert cn["nt_num"] == "CN/2025-26/0042"
    assert cn["nt_dt"] == "08-04-2025"
    assert cn["inv_typ"] == "R"
    assert cn["val"] == 11800.0  # abs of negative SR amount
    assert cn["itms"][0]["itm_det"]["txval"] == 10000.0
    assert cn["itms"][0]["itm_det"]["csamt"] == 0.0


def test_cdnur_candidates_hand_off_without_valid_gstin():
    result = map_sales_register_to_gstr1_cdnr(
        [
            _cdn_sr(gstin=None, gstin_valid=False, invoice_number_raw="CN-UR"),
            _cdn_sr(invoice_number_raw="CN-REG"),
        ],
        filer_state=FILER_MH,
    )
    assert len(result.cdnur_candidates) == 1
    assert result.cdnur_candidates[0]["invoice_number_raw"] == "CN-UR"
    assert result.save_note_count == 1
    assert result.cdnr[0]["nt"][0]["nt_num"] == "CN-REG"


def test_ntty_label_conflict():
    result = map_sales_register_to_gstr1_cdnr(
        [
            _cdn_sr(
                invoice_type="CREDIT_NOTE",
                invoice_type_raw="Debit Note",
            )
        ],
        filer_state=FILER_MH,
    )
    assert result.pending_review[0].reason == "ntty_label_conflict"
    assert result.cdnr == []


def test_ntty_ambiguous_raw():
    result = map_sales_register_to_gstr1_cdnr(
        [
            _cdn_sr(
                invoice_type="CREDIT_NOTE",
                invoice_type_raw="adjustment voucher",
            )
        ],
        filer_state=FILER_MH,
    )
    assert result.pending_review[0].reason == "ntty_ambiguous_raw"


def test_ntty_unclassified_unreachable_via_sr_classifier():
    """Real SR: unambiguous CN/DN raw text always becomes CREDIT_NOTE/DEBIT_NOTE.

    ``ntty_unclassified`` is therefore dead on ``parse_sales_register`` output
    (kept only as a defensive branch for hand-edited records). This test
    proves the classifier agreement rather than inventing a synthetic
    derived≠raw mismatch.
    """
    rows = [
        [
            "Invoice Date",
            "Invoice No",
            "Customer Name",
            "GSTIN",
            "Place of Supply",
            "Invoice Type",
            "Taxable Value (₹)",
            "CGST (₹)",
            "SGST (₹)",
            "IGST (₹)",
            "Invoice Value (₹)",
            "Tax Rate (%)",
        ],
        [
            "2025-04-01",
            "CN/100",
            "Buyer",
            GSTIN_OK,
            "Maharashtra",
            "Credit Note",
            -1000,
            -90,
            -90,
            0,
            -1180,
            18,
        ],
        [
            "2025-04-02",
            "DN/200",
            "Buyer",
            GSTIN_OK,
            "Maharashtra",
            "Debit Note",
            500,
            45,
            45,
            0,
            590,
            18,
        ],
    ]
    parsed = parse_sales_register(_xlsx_bytes(rows), "cdn_types.xlsx")
    assert parsed["success"] is True
    by_raw = {r["invoice_type_raw"]: r for r in parsed["records"]}
    assert by_raw["Credit Note"]["invoice_type"] == "CREDIT_NOTE"
    assert by_raw["Debit Note"]["invoice_type"] == "DEBIT_NOTE"

    result = map_sales_register_to_gstr1_cdnr(
        parsed["records"], filer_state=FILER_MH,
    )
    assert all(p.reason != "ntty_unclassified" for p in result.pending_review)
    # Blank-column path not used here (raw present); both should Save as C/D.
    assert result.save_note_count == 2
    assert {n["ntty"] for g in result.cdnr for n in g["nt"]} == {"C", "D"}


def test_resolve_ntty_blank_raw_follows_derived():
    assert resolve_ntty_from_sr(
        invoice_type="CREDIT_NOTE", invoice_type_raw=None,
    ).ntty == "C"
    assert resolve_ntty_from_sr(
        invoice_type="DEBIT_NOTE", invoice_type_raw="",
    ).ntty == "D"


def test_inv_typ_non_r_goes_to_review_reusing_b2b_resolver():
    result = map_sales_register_to_gstr1_cdnr(
        [
            _cdn_sr(invoice_type_raw="SEZ with payment"),
        ],
        filer_state=FILER_MH,
    )
    assert result.pending_count == 1
    assert result.pending_review[0].reason == "non_r_inv_typ:SEZWP"
    assert result.pending_review[0].proposed_inv_typ == "SEZWP"


def test_inv_typ_blank_raw_on_credit_note_defaults_to_r():
    result = map_sales_register_to_gstr1_cdnr(
        [_cdn_sr(invoice_type_raw=None)],
        filer_state=FILER_MH,
    )
    assert result.pending_count == 0
    assert result.cdnr[0]["nt"][0]["inv_typ"] == "R"


def test_pending_missing_nt_num():
    result = map_sales_register_to_gstr1_cdnr(
        [_cdn_sr(invoice_number_raw=None)],
        filer_state=FILER_MH,
    )
    assert result.pending_review[0].reason == "missing_nt_num"


def test_pending_missing_nt_dt():
    result = map_sales_register_to_gstr1_cdnr(
        [_cdn_sr(invoice_date=None)],
        filer_state=FILER_MH,
    )
    assert result.pending_review[0].reason == "missing_or_invalid_nt_dt"


def test_pending_missing_pos():
    result = map_sales_register_to_gstr1_cdnr(
        [_cdn_sr(place_of_supply=None)],
        filer_state=FILER_MH,
    )
    assert result.pending_review[0].reason == "missing_or_malformed_pos"


def test_pending_missing_tax_rate():
    rec = _cdn_sr()
    del rec["tax_rate"]
    result = map_sales_register_to_gstr1_cdnr([rec], filer_state=FILER_MH)
    assert result.pending_review[0].reason == "missing_tax_rate"


def test_pending_missing_taxable_and_value():
    assert (
        map_sales_register_to_gstr1_cdnr(
            [_cdn_sr(taxable_amount_paise=None)],
            filer_state=FILER_MH,
        ).pending_review[0].reason
        == "missing_taxable_value"
    )
    assert (
        map_sales_register_to_gstr1_cdnr(
            [_cdn_sr(total_amount_paise=None)],
            filer_state=FILER_MH,
        ).pending_review[0].reason
        == "missing_invoice_value"
    )


def test_pending_tax_amount_inconsistent_with_rate():
    result = map_sales_register_to_gstr1_cdnr(
        [
            _cdn_sr(
                taxable_amount_paise=1_000_000,
                cgst_paise=1,
                sgst_paise=1,
                igst_paise=0,
                total_amount_paise=1_000_002,
                tax_rate=18.0,
            )
        ],
        filer_state=FILER_MH,
    )
    assert result.pending_review[0].reason == "tax_amount_inconsistent_with_rate"


def test_pending_interstate_flag_conflict():
    result = map_sales_register_to_gstr1_cdnr(
        [
            _cdn_sr(
                place_of_supply="27-Maharashtra",
                is_interstate=True,
            )
        ],
        filer_state=FILER_MH,
    )
    assert result.pending_review[0].reason == "interstate_flag_conflicts_with_pos"


def test_skips_non_note_rows():
    result = map_sales_register_to_gstr1_cdnr(
        [
            {
                "invoice_type": "B2B",
                "gstin": GSTIN_OK,
                "gstin_valid": True,
                "invoice_number_raw": "INV-1",
                "invoice_date": "2025-04-01",
                "place_of_supply": "27-Maharashtra",
                "tax_rate": 18.0,
                "taxable_amount_paise": 100000,
                "total_amount_paise": 118000,
                "cgst_paise": 9000,
                "sgst_paise": 9000,
                "igst_paise": 0,
            },
            _cdn_sr(),
        ],
        filer_state=FILER_MH,
    )
    assert result.skipped_non_cdn == 1
    assert result.save_note_count == 1
