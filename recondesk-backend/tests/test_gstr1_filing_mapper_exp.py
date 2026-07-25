"""GSTR-1 EXP filing mapper — SR records → Sandbox exp[]."""

from __future__ import annotations

from app.filing.gstr1_filing_mapper import (
    EXP_TYP_WPAY,
    EXP_TYP_WOPAY,
    INV_TYP_SEZWP,
    map_sales_register_to_gstr1_b2b,
    map_sales_register_to_gstr1_exp,
    resolve_exp_typ_from_sr,
)


def _exp_sr(**overrides):
    """Genuine export row with all three shipping fields (WPAY, 18% IGST)."""
    base = {
        "row_number": 2,
        "gstin": None,
        "gstin_valid": False,
        "invoice_type": "EXPORT",
        "invoice_type_raw": "Export",
        "invoice_number": "EXP202526001",
        "invoice_number_normalized": "EXP202526001",
        "invoice_number_raw": "EXP/2025-26/001",
        "invoice_date": "2025-04-15",
        "place_of_supply": "96-Foreign Country",
        "reverse_charge": False,
        "taxable_amount_paise": 100_000_00,
        "igst_paise": 18_000_00,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": None,
        "total_tax_paise": 18_000_00,
        "total_amount_paise": 118_000_00,
        "tax_rate": 18.0,
        "export_type": "WPAY",
        "export_type_raw": "WPAY",
        "shipping_bill_number": "7896542",
        "shipping_bill_date": "2025-04-20",
        "shipping_port_code": "INBOM1",
    }
    base.update(overrides)
    return base


def _wopay_sr(**overrides):
    return _exp_sr(
        invoice_number_raw="EXP/2025-26/002",
        export_type="WOPAY",
        export_type_raw="WOPAY",
        taxable_amount_paise=50_000_00,
        igst_paise=0,
        total_tax_paise=0,
        total_amount_paise=50_000_00,
        tax_rate=0.0,
        shipping_bill_number="1234567",
        shipping_port_code="INMAA1",
        **overrides,
    )


# ---------------------------------------------------------------------------
# resolve_exp_typ
# ---------------------------------------------------------------------------


def test_resolve_exp_typ_explicit_text_preferred_over_tax():
    # Text WPAY even if we also pass matching IGST — reason is text.
    r = resolve_exp_typ_from_sr(
        export_type_raw="WPAY", igst_paise=18_000_00,
    )
    assert r.needs_review is False
    assert r.exp_typ == EXP_TYP_WPAY
    assert r.reason == "explicit_export_type_text"


def test_resolve_exp_typ_tax_fallback_only_when_text_absent():
    r = resolve_exp_typ_from_sr(igst_paise=18_000_00)
    assert r.exp_typ == EXP_TYP_WPAY
    assert r.reason == "igst_presence_fallback"

    r0 = resolve_exp_typ_from_sr(igst_paise=0)
    assert r0.exp_typ == EXP_TYP_WOPAY
    assert r0.reason == "igst_presence_fallback"


def test_resolve_exp_typ_signal_conflict_never_picks_silently():
    # Text WPAY + zero IGST
    r = resolve_exp_typ_from_sr(export_type_raw="WPAY", igst_paise=0)
    assert r.needs_review is True
    assert r.exp_typ is None
    assert r.reason == "export_typ_signal_conflict"

    # Text WOPAY + paid IGST
    r2 = resolve_exp_typ_from_sr(export_type_raw="WOPAY", igst_paise=18_000_00)
    assert r2.needs_review is True
    assert r2.reason == "export_typ_signal_conflict"


def test_resolve_exp_typ_unrecognised_and_unresolved():
    r = resolve_exp_typ_from_sr(export_type_raw="mystery-export-mode")
    assert r.reason == "unrecognised_export_type_raw"

    r2 = resolve_exp_typ_from_sr(igst_paise=None)
    assert r2.reason == "export_typ_unresolved"


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_happy_path_wpay_and_wopay_grouped():
    result = map_sales_register_to_gstr1_exp([_exp_sr(), _wopay_sr()])
    assert result.pending_count == 0
    assert result.save_invoice_count == 2
    assert result.skipped_non_exp == 0

    assert [g["exp_typ"] for g in result.exp] == [EXP_TYP_WPAY, EXP_TYP_WOPAY]

    wpay_inv = result.exp[0]["inv"][0]
    assert wpay_inv["inum"] == "EXP/2025-26/001"
    assert wpay_inv["idt"] == "15-04-2025"
    assert wpay_inv["val"] == 118_000.0
    assert wpay_inv["sbpcode"] == "INBOM1"
    assert wpay_inv["sbnum"] == "7896542"
    assert wpay_inv["sbdt"] == "20-04-2025"
    assert wpay_inv["itms"][0] == {
        "txval": 100_000.0,
        "rt": 18.0,
        "iamt": 18_000.0,
        "csamt": 0.0,
    }
    assert "camt" not in wpay_inv["itms"][0]
    assert "samt" not in wpay_inv["itms"][0]

    wopay_inv = result.exp[1]["inv"][0]
    assert wopay_inv["inum"] == "EXP/2025-26/002"
    assert wopay_inv["itms"][0]["rt"] == 0.0
    assert wopay_inv["itms"][0]["iamt"] == 0.0


def test_happy_path_tax_fallback_when_export_type_column_absent():
    rec = _exp_sr()
    del rec["export_type"]
    del rec["export_type_raw"]
    result = map_sales_register_to_gstr1_exp([rec])
    assert result.pending_count == 0
    assert result.exp[0]["exp_typ"] == EXP_TYP_WPAY


def test_never_uses_normalized_invoice_number_for_inum():
    result = map_sales_register_to_gstr1_exp([
        _exp_sr(
            invoice_number="EXP202526001",
            invoice_number_normalized="EXP202526001",
            invoice_number_raw="exp/2025-26/001",
        )
    ])
    assert result.exp[0]["inv"][0]["inum"] == "exp/2025-26/001"


# ---------------------------------------------------------------------------
# B2B-SEZ exclusion (standalone — not via B2B-first orchestration)
# ---------------------------------------------------------------------------


def test_b2b_sez_excluded_standalone_without_running_b2b_first():
    """SEZ-to-registered must not land in exp[] even if EXP is called alone."""
    sez = _exp_sr(
        gstin="27AABCS2345L1Z8",
        gstin_valid=True,
        invoice_type="EXPORT",  # recon lump category
        invoice_type_raw="SEZ with payment",
        export_type="WPAY",
        export_type_raw="WPAY",
        place_of_supply="27-Maharashtra",
        invoice_number_raw="SEZ-001",
    )
    result = map_sales_register_to_gstr1_exp([sez])
    assert result.exp == []
    assert result.skipped_non_exp == 0
    assert result.pending_count == 1
    assert result.pending_review[0].reason == "already_routed_b2b_sez"
    assert result.pending_review[0].suggested_table == "b2b"
    assert result.pending_review[0].proposed_inv_typ == INV_TYP_SEZWP


def test_b2b_sez_same_row_goes_to_b2b_review_not_exp_save():
    """Cross-check: B2B mapper also peels the same shape (orchestration-safe)."""
    sez = _exp_sr(
        gstin="27AABCS2345L1Z8",
        gstin_valid=True,
        invoice_type="EXPORT",
        invoice_type_raw="SEZ with payment",
        export_type_raw="WPAY",
        place_of_supply="27-Maharashtra",
        invoice_number_raw="SEZ-001",
        # B2B needs POS + tax reconcile for Save path; review before that.
        taxable_amount_paise=200_000,
        igst_paise=0,
        cgst_paise=0,
        sgst_paise=0,
        total_amount_paise=200_000,
        tax_rate=0.0,
    )
    b2b = map_sales_register_to_gstr1_b2b([sez])
    exp = map_sales_register_to_gstr1_exp([sez])
    assert b2b.save_invoice_count == 0
    assert any(
        p.suggested_table == "b2b" for p in b2b.pending_review
    )
    assert exp.exp == []
    assert exp.pending_review[0].reason == "already_routed_b2b_sez"


# ---------------------------------------------------------------------------
# Review reasons
# ---------------------------------------------------------------------------


def test_export_with_recipient_gstin_review():
    rec = _exp_sr(
        gstin="27AAECO5678G1Z2",
        gstin_valid=True,
        invoice_type_raw="Export",  # not SEZ/DE
        place_of_supply="96-Foreign Country",
    )
    result = map_sales_register_to_gstr1_exp([rec])
    assert result.exp == []
    assert result.pending_review[0].reason == "export_with_recipient_gstin"


def test_missing_inum():
    result = map_sales_register_to_gstr1_exp([
        _exp_sr(invoice_number_raw=None, invoice_number=None),
    ])
    assert result.pending_review[0].reason == "missing_inum"


def test_missing_idt():
    result = map_sales_register_to_gstr1_exp([_exp_sr(invoice_date=None)])
    assert result.pending_review[0].reason == "missing_idt"


def test_missing_val():
    result = map_sales_register_to_gstr1_exp([
        _exp_sr(
            total_amount_paise=None,
            taxable_amount_paise=None,
            total_tax_paise=None,
            igst_paise=None,
            cgst_paise=None,
            sgst_paise=None,
            cess_paise=None,
        )
    ])
    assert result.pending_review[0].reason == "missing_val"


def test_missing_shipping_bill_details_each_field():
    for field in (
        "shipping_bill_number",
        "shipping_bill_date",
        "shipping_port_code",
    ):
        rec = _exp_sr(**{field: None})
        result = map_sales_register_to_gstr1_exp([rec])
        assert result.exp == []
        assert result.pending_review[0].reason == "missing_shipping_bill_details", field


def test_invalid_shipping_bill_date():
    result = map_sales_register_to_gstr1_exp([
        _exp_sr(shipping_bill_date="not-a-date"),
    ])
    assert result.pending_review[0].reason == "invalid_shipping_bill_date"


def test_export_has_cgst_or_sgst():
    result = map_sales_register_to_gstr1_exp([
        _exp_sr(cgst_paise=9_000_00, sgst_paise=9_000_00, igst_paise=0),
    ])
    assert result.pending_review[0].reason == "export_has_cgst_or_sgst"


def test_export_typ_signal_conflict_in_mapper():
    result = map_sales_register_to_gstr1_exp([
        _exp_sr(export_type_raw="WPAY", igst_paise=0, tax_rate=0.0),
    ])
    assert result.pending_review[0].reason == "export_typ_signal_conflict"


def test_unrecognised_export_type_raw():
    result = map_sales_register_to_gstr1_exp([
        _exp_sr(export_type="weird", export_type_raw="weird"),
    ])
    assert result.pending_review[0].reason == "unrecognised_export_type_raw"


def test_export_typ_unresolved_when_no_text_and_no_igst():
    rec = _exp_sr(igst_paise=None)
    del rec["export_type"]
    del rec["export_type_raw"]
    result = map_sales_register_to_gstr1_exp([rec])
    assert result.pending_review[0].reason == "export_typ_unresolved"


def test_missing_tax_rate():
    result = map_sales_register_to_gstr1_exp([_exp_sr(tax_rate=None)])
    assert result.pending_review[0].reason == "missing_tax_rate"


def test_missing_taxable_value():
    result = map_sales_register_to_gstr1_exp([
        _exp_sr(taxable_amount_paise=None, total_amount_paise=118_000_00),
    ])
    assert result.pending_review[0].reason == "missing_taxable_value"


def test_tax_amount_inconsistent_with_rate_reuses_shared_gate():
    # 18% of 100000 = 18000; claim 5000 IGST → fail ±₹1 gate
    result = map_sales_register_to_gstr1_exp([
        _exp_sr(igst_paise=5_000_00, total_amount_paise=105_000_00),
    ])
    assert result.pending_review[0].reason == "tax_amount_inconsistent_with_rate"


def test_skipped_non_exp_regular_b2b():
    result = map_sales_register_to_gstr1_exp([
        {
            "gstin": "27AAECO5678G1Z2",
            "gstin_valid": True,
            "invoice_type": "B2B",
            "invoice_type_raw": "Tax Invoice",
            "invoice_number_raw": "B2B-1",
            "invoice_date": "2025-04-01",
            "place_of_supply": "27-Maharashtra",
            "taxable_amount_paise": 100_000,
            "igst_paise": 0,
            "cgst_paise": 9_000,
            "sgst_paise": 9_000,
            "total_amount_paise": 118_000,
            "tax_rate": 18.0,
        }
    ])
    assert result.exp == []
    assert result.pending_count == 0
    assert result.skipped_non_exp == 1


def test_credit_note_skipped_not_exp():
    result = map_sales_register_to_gstr1_exp([
        _exp_sr(invoice_type="CREDIT_NOTE", invoice_type_raw="Credit Note"),
    ])
    assert result.exp == []
    assert result.skipped_non_exp == 1


def test_clear_rows_save_while_review_rows_excluded():
    good = _exp_sr()
    bad = _exp_sr(
        invoice_number_raw="EXP-BAD",
        shipping_bill_number=None,
    )
    result = map_sales_register_to_gstr1_exp([good, bad])
    assert result.save_invoice_count == 1
    assert result.pending_count == 1
    assert result.exp[0]["inv"][0]["inum"] == "EXP/2025-26/001"
    assert result.pending_review[0].reason == "missing_shipping_bill_details"
