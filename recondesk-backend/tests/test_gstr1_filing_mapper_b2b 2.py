"""GSTR-1 B2B filing mapper — SR records → Sandbox Save shape."""

from __future__ import annotations

import io

from openpyxl import Workbook

from app.filing.gstr1_filing_mapper import (
    INV_TYP_DE,
    INV_TYP_R,
    INV_TYP_SEZWP,
    map_sales_register_to_gstr1_b2b,
    resolve_inv_typ_from_sr_raw,
)
from app.parsers.sales_register_parser import parse_sales_register


def _xlsx_bytes(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sales Register"
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _b2b_sr(**overrides):
    base = {
        "row_number": 2,
        "gstin": "06AACVV3456J1Z3",
        "gstin_valid": True,
        "invoice_type": "B2B",
        "invoice_type_raw": None,
        "invoice_number": "RD2025261034",
        "invoice_number_normalized": "RD2025261034",
        "invoice_number_raw": "RD/2025-26/1034",
        "invoice_date": "2025-04-08",
        "place_of_supply": "06-Haryana",
        "reverse_charge": False,
        "taxable_amount_paise": 22047832,
        "igst_paise": 1102392,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
        "total_tax_paise": 1102392,
        "total_amount_paise": 23150224,
        "tax_rate": 5.0,
    }
    base.update(overrides)
    return base


def test_resolve_inv_typ_inferred_r_when_b2b_and_no_type_column():
    r = resolve_inv_typ_from_sr_raw(
        invoice_type_raw=None,
        export_type_raw=None,
        invoice_type="B2B",
    )
    assert r.inv_typ == INV_TYP_R
    assert r.needs_review is False


def test_resolve_inv_typ_sezwp_needs_review():
    r = resolve_inv_typ_from_sr_raw(
        invoice_type_raw="SEZ with payment",
        invoice_type="EXPORT",
    )
    assert r.inv_typ == INV_TYP_SEZWP
    assert r.needs_review is True


def test_resolve_inv_typ_deemed_export_needs_review():
    r = resolve_inv_typ_from_sr_raw(
        invoice_type_raw="Deemed Export",
        invoice_type="EXPORT",
    )
    assert r.inv_typ == INV_TYP_DE
    assert r.needs_review is True


def test_resolve_inv_typ_ambiguous_sez_needs_review():
    r = resolve_inv_typ_from_sr_raw(
        invoice_type_raw="SEZ",
        invoice_type="EXPORT",
    )
    assert r.inv_typ is None
    assert r.needs_review is True
    assert r.reason == "ambiguous_sez_or_export_wording"


def test_map_b2b_clear_r_uses_invoice_number_raw_and_sandbox_shape():
    result = map_sales_register_to_gstr1_b2b([_b2b_sr()])
    assert result.pending_count == 0
    assert result.save_invoice_count == 1
    assert result.b2b == [
        {
            "ctin": "06AACVV3456J1Z3",
            "inv": [
                {
                    "inum": "RD/2025-26/1034",
                    "idt": "08-04-2025",
                    "val": 231502.24,
                    "pos": "06",
                    "rchrg": "N",
                    "inv_typ": "R",
                    "itms": [
                        {
                            "num": 1,
                            "itm_det": {
                                "rt": 5,
                                "txval": 220478.32,
                                "iamt": 11023.92,
                                "camt": 0,
                                "samt": 0,
                                "csamt": 0,
                            },
                        }
                    ],
                }
            ],
        }
    ]


def test_map_b2b_per_invoice_review_does_not_block_batch():
    """497 clear-R proceed; non-R / ambiguous sit in pending_review only."""
    clear = [_b2b_sr(row_number=i, invoice_number_raw=f"INV-{i}") for i in range(5)]
    review_rows = [
        _b2b_sr(
            row_number=100,
            invoice_number_raw="SEZ-1",
            invoice_type="EXPORT",
            invoice_type_raw="SEZ with payment",
        ),
        _b2b_sr(
            row_number=101,
            invoice_number_raw="AMB-1",
            invoice_type_raw="SEZ",
        ),
        _b2b_sr(
            row_number=102,
            invoice_number_raw="DE-1",
            invoice_type="EXPORT",
            invoice_type_raw="Deemed Export",
        ),
    ]
    result = map_sales_register_to_gstr1_b2b(clear + review_rows)
    assert result.save_invoice_count == 5
    assert result.pending_count == 3
    saved_inums = {
        inv["inum"]
        for group in result.b2b
        for inv in group["inv"]
    }
    assert saved_inums == {f"INV-{i}" for i in range(5)}
    pending_inums = {
        (p.record.get("invoice_number_raw") or p.record.get("invoice_number"))
        for p in result.pending_review
    }
    assert pending_inums == {"SEZ-1", "AMB-1", "DE-1"}
    # Non-R never appears in Save payload.
    for group in result.b2b:
        for inv in group["inv"]:
            assert inv["inv_typ"] == "R"


def test_map_b2b_never_uses_normalized_invoice_number_for_inum():
    result = map_sales_register_to_gstr1_b2b([
        _b2b_sr(
            invoice_number="RD2025261034",
            invoice_number_normalized="RD2025261034",
            invoice_number_raw="rd/2025-26/1034",
        )
    ])
    assert result.b2b[0]["inv"][0]["inum"] == "rd/2025-26/1034"


def test_map_b2b_tax_amount_inconsistent_with_rate_goes_to_review():
    """Gap closed: B2B also gates txval×rate vs stated GST (±₹1)."""
    result = map_sales_register_to_gstr1_b2b([
        _b2b_sr(
            taxable_amount_paise=22047832,
            igst_paise=1,  # absurd vs 5% of taxable
            cgst_paise=0,
            sgst_paise=0,
            tax_rate=5.0,
        )
    ])
    assert result.save_invoice_count == 0
    assert result.pending_count == 1
    assert result.pending_review[0].reason == "tax_amount_inconsistent_with_rate"


def test_sr_without_invoice_type_column_maps_b2b_as_r_not_pending_review():
    """End-to-end: workbook has NO Invoice Type / supply-type column at all.

    Most real Sales Registers look like this. The parser still classifies rows
    with a valid recipient GSTIN as ``invoice_type == \"B2B\"`` and leaves
    ``invoice_type_raw`` as ``None``. The mapper's intentional policy for that
    case is ``inv_typ = R`` via ``inferred_b2b_no_type_column`` — *not*
    ``pending_review``.

    Consequence: for typical books exports, R is the practical default for
    nearly every B2B invoice. Review is reserved for rows that *do* carry
    SEZ / deemed-export / ambiguous type text (or EXPORT+SEZ with GSTIN).

    Historical skip note (not inv_typ policy): an earlier draft of this test
    used GSTINs with invalid check digits (``07AABCN6789S1ZD``,
    ``29AABCS2345L1Z4``). The parser set ``gstin_valid=False``
    (``normalize_gstin`` → ``invalid_checksum``); the mapper then counted them
    as ``skipped_non_b2b`` because ``gstin_ok`` requires ``gstin_valid``.
    That was test-data corruption, not \"no type column → review\".
    Both GSTINs below have valid check digits so both rows enter the B2B path.
    """
    # Checksum-valid GSTINs (15th char matches normalizer check digit).
    gstin_mh = "27AAECO5678G1Z2"
    gstin_dl = "07AABCN6789S1ZD"

    rows = [
        [
            "Invoice Date",
            "Invoice No",
            "Customer Name",
            "GSTIN",
            "Place of Supply",
            "Taxable Value (₹)",
            "CGST (₹)",
            "SGST (₹)",
            "IGST (₹)",
            "Invoice Value (₹)",
            "Tax Rate (%)",
        ],
        # No "Invoice Type" / "Supply Type" / "Export Type" columns anywhere.
        [
            "2025-04-01",
            "RD/2025-26/1001",
            "Buyer One",
            gstin_mh,
            "Maharashtra",
            1000,
            90,
            90,
            0,
            1180,
            18,
        ],
        [
            "2025-04-02",
            "RD/2025-26/1002",
            "Buyer Two",
            gstin_dl,
            "Delhi",
            2000,
            0,
            0,
            360,
            2360,
            18,
        ],
    ]
    parsed = parse_sales_register(_xlsx_bytes(rows), "sr_no_type_col.xlsx")
    assert parsed["success"] is True
    detected = parsed.get("detected_columns") or {}
    assert "invoice_type" not in detected, (
        "fixture must omit the type column entirely — not merely blank cells"
    )
    assert "export_type" not in detected

    records = parsed["records"]
    assert len(records) == 2
    by_inum = {r["invoice_number_raw"]: r for r in records}
    assert set(by_inum) == {"RD/2025-26/1001", "RD/2025-26/1002"}

    for inum, expected_gstin in (
        ("RD/2025-26/1001", gstin_mh),
        ("RD/2025-26/1002", gstin_dl),
    ):
        rec = by_inum[inum]
        assert rec["gstin"] == expected_gstin
        assert rec["gstin_valid"] is True, (
            f"{inum}: parser must accept checksum-valid GSTIN; "
            f"got gstin_valid={rec['gstin_valid']!r} (skip was previously "
            f"caused by invalid_checksum test data, not inv_typ policy)"
        )
        assert rec["invoice_type"] == "B2B"
        assert rec["invoice_type_raw"] is None
        assert rec.get("export_type") is None
        assert rec.get("export_type_raw") is None

        # Policy under test: no type info → assume R (not pending_review).
        resolution = resolve_inv_typ_from_sr_raw(
            invoice_type_raw=rec.get("invoice_type_raw"),
            export_type_raw=rec.get("export_type_raw"),
            invoice_type=rec.get("invoice_type"),
        )
        assert resolution.inv_typ == INV_TYP_R
        assert resolution.needs_review is False
        assert resolution.reason == "inferred_b2b_no_type_column"

    result = map_sales_register_to_gstr1_b2b(records)
    assert result.skipped_non_b2b == 0
    assert result.pending_count == 0
    assert result.save_invoice_count == 2
    assert {g["ctin"] for g in result.b2b} == {gstin_mh, gstin_dl}
    saved = {
        inv["inum"]: inv
        for group in result.b2b
        for inv in group["inv"]
    }
    assert set(saved) == {"RD/2025-26/1001", "RD/2025-26/1002"}
    assert all(inv["inv_typ"] == "R" for inv in saved.values())
