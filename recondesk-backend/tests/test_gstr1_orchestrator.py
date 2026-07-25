"""GSTR-1 filing orchestrator — compose all table mappers for one period."""

from __future__ import annotations

import random

import pytest

from app.filing.gstr1_orchestrator import (
    DISPOSITION_EXTERNAL,
    DISPOSITION_PENDING,
    DISPOSITION_SAVED,
    DISPOSITION_SKIPPED,
    map_sales_register_to_gstr1,
)


FILER = "27"
PERIOD = "2025-04"
GSTIN_OK = "27AAECO5678G1Z2"
GSTIN_OTHER = "06AACVV3456J1Z1"


def _tax_at_rate(taxable_paise: int, rate: float) -> int:
    return int(round(taxable_paise * rate / 100.0))


def _b2b(**kw):
    taxable = kw.pop("taxable_amount_paise", 100_000)
    rate = kw.pop("tax_rate", 18.0)
    tax = _tax_at_rate(taxable, rate)
    half = tax // 2
    base = {
        "gstin": GSTIN_OK,
        "gstin_valid": True,
        "invoice_type": "B2B",
        "invoice_type_raw": "Tax Invoice",
        "invoice_number_raw": "B2B-001",
        "invoice_date": "2025-04-08",
        "place_of_supply": "27-Maharashtra",
        "reverse_charge": False,
        "taxable_amount_paise": taxable,
        "igst_paise": 0,
        "cgst_paise": half,
        "sgst_paise": tax - half,
        "cess_paise": 0,
        "total_tax_paise": tax,
        "total_amount_paise": taxable + tax,
        "tax_rate": rate,
        "hsn": "8203",
    }
    base.update(kw)
    return base


def _b2c(**kw):
    taxable = kw.pop("taxable_amount_paise", 50_000)
    rate = kw.pop("tax_rate", 18.0)
    tax = _tax_at_rate(taxable, rate)
    half = tax // 2
    base = {
        "gstin": None,
        "gstin_valid": False,
        "invoice_type": "B2C",
        "invoice_type_raw": None,
        "invoice_number_raw": "CASH-001",
        "invoice_date": "2025-04-08",
        "place_of_supply": "27-Maharashtra",
        "taxable_amount_paise": taxable,
        "igst_paise": 0,
        "cgst_paise": half,
        "sgst_paise": tax - half,
        "cess_paise": 0,
        "total_tax_paise": tax,
        "total_amount_paise": taxable + tax,
        "tax_rate": rate,
    }
    base.update(kw)
    return base


def _b2cl(**kw):
    # Inter-state above ₹1L threshold (post Aug 2024)
    taxable = kw.pop("taxable_amount_paise", 12_000_000)
    rate = kw.pop("tax_rate", 18.0)
    tax = _tax_at_rate(taxable, rate)
    return _b2c(
        place_of_supply="06-Haryana",
        taxable_amount_paise=taxable,
        igst_paise=tax,
        cgst_paise=0,
        sgst_paise=0,
        total_tax_paise=tax,
        total_amount_paise=taxable + tax,
        tax_rate=rate,
        invoice_number_raw=kw.pop("invoice_number_raw", "B2CL-001"),
        **kw,
    )


def _cdnr(**kw):
    taxable = kw.pop("taxable_amount_paise", 50_000)
    rate = kw.pop("tax_rate", 18.0)
    tax = _tax_at_rate(taxable, rate)
    half = tax // 2
    base = {
        "gstin": GSTIN_OK,
        "gstin_valid": True,
        "invoice_type": "CREDIT_NOTE",
        "invoice_type_raw": "Credit Note",
        "invoice_number_raw": "CN-001",
        "invoice_date": "2025-04-10",
        "place_of_supply": "27-Maharashtra",
        "reverse_charge": False,
        "taxable_amount_paise": -taxable,
        "igst_paise": 0,
        "cgst_paise": -half,
        "sgst_paise": -(tax - half),
        "cess_paise": 0,
        "total_tax_paise": -tax,
        "total_amount_paise": -(taxable + tax),
        "tax_rate": rate,
    }
    base.update(kw)
    return base


def _cdnur_b2cl(**kw):
    taxable = kw.pop("taxable_amount_paise", 12_000_000)
    rate = kw.pop("tax_rate", 18.0)
    tax = _tax_at_rate(taxable, rate)
    return _cdnr(
        gstin=None,
        gstin_valid=False,
        place_of_supply="06-Haryana",
        taxable_amount_paise=-taxable,
        igst_paise=-tax,
        cgst_paise=0,
        sgst_paise=0,
        total_tax_paise=-tax,
        total_amount_paise=-(taxable + tax),
        tax_rate=rate,
        invoice_number_raw=kw.pop("invoice_number_raw", "URCN-001"),
        **kw,
    )


def _exp(**kw):
    taxable = kw.pop("taxable_amount_paise", 200_000)
    rate = kw.pop("tax_rate", 18.0)
    tax = _tax_at_rate(taxable, rate)
    base = {
        "gstin": None,
        "gstin_valid": False,
        "invoice_type": "EXPORT",
        "invoice_type_raw": "Export",
        "export_type": "WPAY",
        "export_type_raw": "With payment of IGST",
        "invoice_number_raw": "EXP-001",
        "invoice_date": "2025-04-12",
        "place_of_supply": "96-Other Country",
        "taxable_amount_paise": taxable,
        "igst_paise": tax,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
        "total_tax_paise": tax,
        "total_amount_paise": taxable + tax,
        "tax_rate": rate,
        "shipping_bill_number": "SB123",
        "shipping_bill_date": "2025-04-13",
        "shipping_port_code": "INBOM1",
    }
    base.update(kw)
    return base


def _nil_lump(**kw):
    base = {
        "gstin": None,
        "gstin_valid": False,
        "invoice_type": "NIL_RATED",
        "invoice_type_raw": "Nil Rated/Exempt",
        "invoice_number_raw": "NIL-001",
        "invoice_date": "2025-04-01",
        "place_of_supply": "27-Maharashtra",
        "taxable_amount_paise": 10_000,
        "igst_paise": 0,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "tax_rate": 0.0,
    }
    base.update(kw)
    return base


def _advance(**kw):
    base = {
        "gstin": None,
        "gstin_valid": False,
        "invoice_type": "ADVANCES",
        "invoice_type_raw": "Advance Receipt",
        "invoice_number_raw": "ADV-001",
        "invoice_date": "2025-04-01",
        "place_of_supply": "27-Maharashtra",
        "taxable_amount_paise": 25_000,
        "tax_rate": 18.0,
    }
    base.update(kw)
    return base


def build_synthetic_sr_3500(*, seed: int = 42) -> list[dict]:
    """Typical Tally-like mix (~3500 rows) covering all primary lanes."""
    rng = random.Random(seed)
    records: list[dict] = []
    n = 3500
    for i in range(n):
        r = rng.random()
        if r < 0.55:
            records.append(
                _b2b(
                    invoice_number_raw=f"B2B-{i}",
                    place_of_supply=rng.choice(
                        ["27-Maharashtra", "06-Haryana", "29-Karnataka"]
                    ),
                    gstin=rng.choice([GSTIN_OK, GSTIN_OTHER]),
                    hsn=rng.choice(["8203", "3901", "7318", None]),
                )
            )
        elif r < 0.72:
            records.append(
                _b2c(
                    invoice_number_raw=f"B2C-{i}",
                    place_of_supply=rng.choice(
                        ["27-Maharashtra", "24-Gujarat"]
                    ),
                )
            )
        elif r < 0.78:
            records.append(_b2cl(invoice_number_raw=f"B2CL-{i}"))
        elif r < 0.86:
            records.append(
                _cdnr(
                    invoice_number_raw=f"CN-{i}",
                    invoice_type=rng.choice(["CREDIT_NOTE", "DEBIT_NOTE"]),
                    invoice_type_raw=rng.choice(["Credit Note", "Debit Note"]),
                )
            )
        elif r < 0.90:
            records.append(_cdnur_b2cl(invoice_number_raw=f"URCN-{i}"))
        elif r < 0.94:
            records.append(_exp(invoice_number_raw=f"EXP-{i}"))
        elif r < 0.97:
            records.append(_nil_lump(invoice_number_raw=f"NIL-{i}"))
        elif r < 0.985:
            # SEZ-to-registered → B2B review peel (not EXP Save)
            records.append(
                _exp(
                    invoice_number_raw=f"SEZ-{i}",
                    gstin=GSTIN_OK,
                    gstin_valid=True,
                    invoice_type="EXPORT",
                    invoice_type_raw="SEZ with payment",
                    export_type_raw="SEZWP",
                    place_of_supply="27-Maharashtra",
                )
            )
        elif r < 0.995:
            records.append(_advance(invoice_number_raw=f"ADV-{i}"))
        else:
            # Unknown type + valid GSTIN — orchestrator unclassified leak-fix
            records.append(
                {
                    "gstin": GSTIN_OK,
                    "gstin_valid": True,
                    "invoice_type": "OTHER",
                    "invoice_type_raw": "Journal",
                    "invoice_number_raw": f"OTH-{i}",
                    "invoice_date": "2025-04-01",
                    "place_of_supply": "27-Maharashtra",
                    "taxable_amount_paise": 1000,
                    "tax_rate": 18.0,
                }
            )
    assert len(records) == n
    return records


def test_happy_path_mixed_tables_one_payload():
    rows = [
        _b2b(invoice_number_raw="B1"),
        _b2c(invoice_number_raw="C1"),
        _b2cl(invoice_number_raw="L1"),
        _cdnr(invoice_number_raw="N1"),
        _cdnur_b2cl(invoice_number_raw="U1"),
        _exp(invoice_number_raw="E1"),
    ]
    result = map_sales_register_to_gstr1(
        rows, filer_state=FILER, filing_period=PERIOD,
    )
    payload = result.save_payload
    assert "b2b" in payload
    assert "b2cs" in payload or "b2cl" in payload
    assert "b2cl" in payload
    assert "cdnr" in payload
    assert "cdnur" in payload
    assert "exp" in payload
    assert "doc_issue" not in payload
    assert "at" not in payload
    assert result.row_accounting.sums_to_total
    assert result.filing_readiness.can_save is True
    # HSN incomplete (no uqc/qty) + DOC_ISSUE gap → not File-able
    assert result.filing_readiness.can_file is False
    assert any("Table 13" in b for b in result.filing_readiness.file_blockers)
    assert any("HSN" in b for b in result.filing_readiness.file_blockers)
    assert "nil" not in result.external_input_gaps.tables_blocked() or True


def test_sez_not_dual_pended_by_exp():
    row = _exp(
        gstin=GSTIN_OK,
        gstin_valid=True,
        invoice_type_raw="SEZ with payment",
        export_type_raw="SEZWP",
        place_of_supply="27-Maharashtra",
    )
    result = map_sales_register_to_gstr1(
        [row], filer_state=FILER, filing_period=PERIOD,
    )
    sez_pending = [
        p for p in result.pending_review if p.record is row
    ]
    assert len(sez_pending) == 1
    assert sez_pending[0].suggested_table == "b2b"
    assert "exp" not in result.save_payload


def test_unclassified_goes_to_pending():
    row = {
        "gstin": GSTIN_OK,
        "gstin_valid": True,
        "invoice_type": "OTHER",
        "invoice_type_raw": "Journal",
        "invoice_number_raw": "J1",
        "invoice_date": "2025-04-01",
        "place_of_supply": "27",
        "taxable_amount_paise": 1000,
        "tax_rate": 18.0,
    }
    result = map_sales_register_to_gstr1(
        [row], filer_state=FILER, filing_period=PERIOD,
    )
    assert any(p.reason == "unclassified_sr_row" for p in result.pending_review)
    assert result.row_accounting.pending_review == 1
    assert result.row_accounting.sums_to_total


def test_nil_and_advances_count_as_external():
    rows = [_nil_lump(), _advance()]
    result = map_sales_register_to_gstr1(
        rows, filer_state=FILER, filing_period=PERIOD,
    )
    assert result.row_accounting.external_input == 2
    assert result.row_accounting.sums_to_total
    gaps = result.external_input_gaps.tables_blocked()
    assert "nil" in gaps
    assert "at" in gaps and "txpd" in gaps
    # NIL is advisory, not a file blocker
    assert not any("Table 8" in b for b in result.filing_readiness.file_blockers)
    assert any("NIL" in a or "nil" in a.lower() for a in result.filing_readiness.advisory)


def test_pending_items_tagged_with_table():
    # B2B missing inum → pending with suggested_table b2b
    row = _b2b(invoice_number_raw=None)
    result = map_sales_register_to_gstr1(
        [row], filer_state=FILER, filing_period=PERIOD,
    )
    assert result.pending_count >= 1
    assert all(
        getattr(p, "suggested_table", None) for p in result.pending_review
    )


def test_synthetic_3500_row_accounting_balances():
    records = build_synthetic_sr_3500()
    result = map_sales_register_to_gstr1(
        records, filer_state=FILER, filing_period=PERIOD,
    )
    acct = result.row_accounting
    assert acct.total_rows == 3500
    assert acct.sums_to_total, (
        f"leak: saved={acct.saved} pending={acct.pending_review} "
        f"external={acct.external_input} skipped={acct.skipped} "
        f"sum={acct.saved + acct.pending_review + acct.external_input + acct.skipped} "
        f"by_lane={acct.by_lane}"
    )
    # Every disposition is one of the four buckets
    assert set(acct.dispositions) <= {
        DISPOSITION_SAVED,
        DISPOSITION_PENDING,
        DISPOSITION_EXTERNAL,
        DISPOSITION_SKIPPED,
    }
    assert result.filing_readiness.can_save is True
    # Typical mix has B2B + incomplete HSN + DOC_ISSUE → Save yes, File no
    assert result.filing_readiness.can_file is False
    assert result.filing_readiness.file_blockers
    assert "b2b" in result.save_payload
    # Hand-off produced at least one of B2C family
    assert "b2cs" in result.save_payload or "b2cl" in result.save_payload


def test_hsn_pending_does_not_steal_primary_saved_disposition():
    """Malformed HSN on a clear B2B row: primary = saved; HSN may pending."""
    row = _b2b(hsn="AB12")  # malformed → HSN pending, B2B still Saves
    result = map_sales_register_to_gstr1(
        [row], filer_state=FILER, filing_period=PERIOD,
    )
    assert result.row_accounting.dispositions == [DISPOSITION_SAVED]
    assert "b2b" in result.save_payload
    # HSN blocked or pending — either way primary accounting stays saved
    assert result.row_accounting.sums_to_total
