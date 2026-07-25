"""GSTR-1 B2CS netting — second pass over (pos, rt) buckets."""

from __future__ import annotations

from app.filing.gstr1_filing_mapper import (
    B2CSNetCandidate,
    apply_b2cs_netting,
    build_netted_b2cs_save,
    map_sales_register_to_gstr1_b2cs,
)


FILER_MH = "27"


def _b2c_sr(**overrides):
    base = {
        "gstin": None,
        "gstin_valid": False,
        "invoice_type": "B2C",
        "invoice_type_raw": None,
        "invoice_number_raw": "CASH-001",
        "invoice_date": "2025-04-08",
        "place_of_supply": "27-Maharashtra",
        "taxable_amount_paise": 100_000,  # ₹1,000
        "igst_paise": 0,
        "cgst_paise": 9_000,
        "sgst_paise": 9_000,
        "cess_paise": 0,
        "total_amount_paise": 118_000,
        "tax_rate": 18.0,
    }
    base.update(overrides)
    return base


def _net_cand(
    *,
    ntty: str = "C",
    pos: str = "27",
    sply_ty: str = "INTRA",
    tax_rate: float = 18.0,
    taxable_paise: int = 50_000,
    cgst_paise: int = 4_500,
    sgst_paise: int = 4_500,
    igst_paise: int = 0,
    cess_paise: int = 0,
    nt_num: str = "CN-NET-1",
) -> B2CSNetCandidate:
    rec = {
        "invoice_number_raw": nt_num,
        "invoice_type": "CREDIT_NOTE" if ntty == "C" else "DEBIT_NOTE",
        "place_of_supply": f"{pos}-State",
        "taxable_amount_paise": taxable_paise,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "igst_paise": igst_paise,
        "cess_paise": cess_paise,
        "tax_rate": tax_rate,
    }
    return B2CSNetCandidate(
        record=rec,
        nt_num=nt_num,
        ntty=ntty,
        pos=pos,
        sply_ty=sply_ty,
        val_paise=taxable_paise + cgst_paise + sgst_paise + igst_paise + cess_paise,
        tax_rate=tax_rate,
        taxable_amount_paise=taxable_paise,
        igst_paise=igst_paise,
        cgst_paise=cgst_paise,
        sgst_paise=sgst_paise,
        cess_paise=cess_paise,
        reason="intra",
    )


def test_unaffected_when_no_net_candidates():
    """Existing B2CS buckets unchanged when candidates list is empty."""
    gross = map_sales_register_to_gstr1_b2cs(
        [_b2c_sr()], filer_state=FILER_MH, filing_period="2025-04",
    )
    netted = apply_b2cs_netting(gross.b2cs, [], filer_state=FILER_MH)
    assert netted.pending_count == 0
    assert netted.applied_candidate_count == 0
    assert netted.b2cs == gross.b2cs


def test_cn_subtracts_from_existing_bucket():
    gross = map_sales_register_to_gstr1_b2cs(
        [_b2c_sr()], filer_state=FILER_MH, filing_period="2025-04",
    )
    assert gross.b2cs[0]["txval"] == 1000.0
    assert gross.b2cs[0]["camt"] == 90.0

    netted = apply_b2cs_netting(
        gross.b2cs,
        [_net_cand(ntty="C", taxable_paise=50_000, cgst_paise=4_500, sgst_paise=4_500)],
        filer_state=FILER_MH,
    )
    assert netted.pending_count == 0
    assert netted.applied_candidate_count == 1
    assert len(netted.b2cs) == 1
    row = netted.b2cs[0]
    assert row["txval"] == 500.0
    assert row["camt"] == 45.0
    assert row["samt"] == 45.0
    assert row["iamt"] == 0.0


def test_dn_creates_bucket_with_no_gross_b2cs_invoice():
    """Bucket exists only because of netting (DN add, no matching B2CS sale)."""
    cand = _net_cand(
        ntty="D",
        nt_num="DN-ONLY",
        taxable_paise=200_000,
        cgst_paise=18_000,
        sgst_paise=18_000,
    )
    netted = apply_b2cs_netting([], [cand], filer_state=FILER_MH)
    assert netted.pending_count == 0
    assert netted.applied_candidate_count == 1
    assert len(netted.b2cs) == 1
    row = netted.b2cs[0]
    assert row["pos"] == "27"
    assert row["rt"] == 18.0
    assert row["sply_ty"] == "INTRA"
    assert row["txval"] == 2000.0
    assert row["camt"] == 180.0
    assert row["samt"] == 180.0


def test_negative_net_bucket_goes_to_review_not_save():
    """GSTN Table 7 is a net figure — negative buckets are not Saved."""
    # Gross ₹1,000; CN ₹2,000 → net -₹1,000
    gross = map_sales_register_to_gstr1_b2cs(
        [_b2c_sr()], filer_state=FILER_MH, filing_period="2025-04",
    )
    cand = _net_cand(
        ntty="C",
        taxable_paise=200_000,
        cgst_paise=18_000,
        sgst_paise=18_000,
    )
    netted = apply_b2cs_netting(gross.b2cs, [cand], filer_state=FILER_MH)
    assert netted.b2cs == []
    assert netted.applied_candidate_count == 1
    assert netted.pending_count == 1
    assert netted.pending_review[0].reason == "b2cs_net_negative_bucket"
    assert netted.pending_review[0].record["net_txval"] == -1000.0


def test_cn_only_bucket_is_negative_review():
    """No gross invoices + CN alone → negative → review (not a Save row)."""
    netted = apply_b2cs_netting(
        [],
        [_net_cand(ntty="C")],
        filer_state=FILER_MH,
    )
    assert netted.b2cs == []
    assert netted.pending_review[0].reason == "b2cs_net_negative_bucket"


def test_exact_zero_net_omitted_quietly():
    """CN that exactly cancels the bucket → omit zero row, no review."""
    gross = map_sales_register_to_gstr1_b2cs(
        [_b2c_sr()], filer_state=FILER_MH, filing_period="2025-04",
    )
    cand = _net_cand(
        ntty="C",
        taxable_paise=100_000,
        cgst_paise=9_000,
        sgst_paise=9_000,
    )
    netted = apply_b2cs_netting(gross.b2cs, [cand], filer_state=FILER_MH)
    assert netted.b2cs == []
    assert netted.omitted_zero_buckets == 1
    assert netted.pending_count == 0


def test_small_positive_residual_after_netting_is_saved():
    gross = map_sales_register_to_gstr1_b2cs(
        [_b2c_sr()], filer_state=FILER_MH, filing_period="2025-04",
    )
    # Leave ₹10 taxable residual
    cand = _net_cand(
        ntty="C",
        taxable_paise=99_000,
        cgst_paise=8_910,
        sgst_paise=8_910,
    )
    netted = apply_b2cs_netting(gross.b2cs, [cand], filer_state=FILER_MH)
    assert netted.pending_count == 0
    assert len(netted.b2cs) == 1
    assert abs(netted.b2cs[0]["txval"] - 10.0) < 0.01


def test_build_netted_b2cs_save_composes_both_passes():
    gross, netted = build_netted_b2cs_save(
        [_b2c_sr()],
        [_net_cand(ntty="C", taxable_paise=50_000, cgst_paise=4_500, sgst_paise=4_500)],
        filer_state=FILER_MH,
        filing_period="2025-04",
    )
    assert gross.b2cs[0]["txval"] == 1000.0  # pre-net
    assert netted.b2cs[0]["txval"] == 500.0  # post-net


def test_unaffected_sibling_bucket_when_netting_other_pos_rate():
    """Netting one bucket must not touch another (pos, rt)."""
    rows = [
        _b2c_sr(invoice_number_raw="A", tax_rate=18.0),
        _b2c_sr(
            invoice_number_raw="B",
            tax_rate=5.0,
            taxable_amount_paise=100_000,
            cgst_paise=2_500,
            sgst_paise=2_500,
            total_amount_paise=105_000,
        ),
    ]
    gross = map_sales_register_to_gstr1_b2cs(
        rows, filer_state=FILER_MH, filing_period="2025-04",
    )
    assert len(gross.b2cs) == 2
    netted = apply_b2cs_netting(
        gross.b2cs,
        [_net_cand(ntty="C", tax_rate=18.0, taxable_paise=50_000,
                   cgst_paise=4_500, sgst_paise=4_500)],
        filer_state=FILER_MH,
    )
    by_rt = {r["rt"]: r for r in netted.b2cs}
    assert by_rt[18.0]["txval"] == 500.0
    assert by_rt[5.0]["txval"] == 1000.0
    assert by_rt[5.0]["camt"] == 25.0
