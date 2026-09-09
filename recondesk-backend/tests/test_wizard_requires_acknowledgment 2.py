"""Generic ``requires_acknowledgment`` gate for high-risk wizard warnings.

Blocking checks (must ack before Continue/Start):
  - multi_sheet_combine
  - missing_invoice_number
  - records (GSTR 0 parsed)

Informational (no ack required): partial GSTR skips with parsed>0, etc.
"""

from __future__ import annotations

import io
import json

import pandas as pd

from app.parsers.purchase_register_parser import parse_purchase_register
from app.services.reconciliation_import_wizard.wizard_service import (
    MISSING_INVOICE_CHECK_ID,
    MULTI_SHEET_COMBINE_CHECK_ID,
    blocking_acknowledgments_pending,
    build_missing_invoice_number_check,
    build_multi_sheet_combine_check,
    preserve_check_acknowledgments,
    run_sanity_gstr2b_json,
    unacknowledged_blocking_checks,
    upsert_sanity_check,
)


def _xlsx_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)
    return buf.getvalue()


def _sheet(inv: str | None, gstin: str = "27AABCU9603R1ZM") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Invoice Date": ["01-04-2026"],
            "GSTIN": [gstin],
            "Invoice Number": [inv if inv is not None else ""],
            "Taxable Amount": [1000.0],
            "CGST": [90.0],
            "SGST": [90.0],
            "IGST": [0.0],
        }
    )


def test_blocking_acknowledgments_pending_uses_flag_not_hardcoded_id():
    checks = [
        {
            "id": "anything",
            "status": "warning",
            "requires_acknowledgment": True,
            "acknowledged": False,
        }
    ]
    assert blocking_acknowledgments_pending(checks) is True
    assert len(unacknowledged_blocking_checks(checks)) == 1

    checks[0]["acknowledged"] = True
    assert blocking_acknowledgments_pending(checks) is False

    # Informational warning without the flag must not block.
    assert (
        blocking_acknowledgments_pending(
            [
                {
                    "id": "records",
                    "status": "warning",
                    "requires_acknowledgment": False,
                    "acknowledged": False,
                }
            ]
        )
        is False
    )


def test_multi_sheet_check_sets_requires_acknowledgment():
    check = build_multi_sheet_combine_check(
        [{"sheet": "A", "records": 1}, {"sheet": "B", "records": 1}]
    )
    assert check is not None
    assert check["id"] == MULTI_SHEET_COMBINE_CHECK_ID
    assert check["requires_acknowledgment"] is True
    assert check["acknowledged"] is False
    assert blocking_acknowledgments_pending([check]) is True


def test_missing_invoice_check_sets_requires_acknowledgment():
    check = build_missing_invoice_number_check(
        3, ["3 purchase register row(s) missing invoice number"]
    )
    assert check is not None
    assert check["id"] == MISSING_INVOICE_CHECK_ID
    assert check["requires_acknowledgment"] is True
    assert "3 skipped: missing invoice number" in check["detail"]
    assert blocking_acknowledgments_pending([check]) is True
    assert build_missing_invoice_number_check(0, []) is None


def test_gstr_zero_parsed_with_skips_requires_acknowledgment():
    """Portal CDNR with unknown note type → 0 parsed, N skipped → must ack."""
    # Build a CDNR-only payload that yields unknown_note_type skips (ntty=X).
    payload = json.dumps(
        {
            "data": {
                "gstin": "27AABCU9603R1ZM",
                "rtnprd": "042024",
                "cdnr": [
                    {
                        "ctin": "29AABCU9603R1ZN",
                        "inv": [
                            {
                                "ntnum": f"CN-{i}",
                                "dt": "01-04-2024",
                                "val": 100,
                                "ntty": "X",
                                "pos": "27",
                                "rev": "N",
                                "itcavl": "Y",
                            }
                            for i in range(3)
                        ],
                    }
                ],
            }
        }
    ).encode()
    checks, count = run_sanity_gstr2b_json(payload)
    assert count == 0
    records = next(c for c in checks if c["id"] == "records")
    assert records["status"] == "warning"
    assert records["requires_acknowledgment"] is True
    assert "skipped" in records["detail"].lower()
    assert blocking_acknowledgments_pending(checks) is True


def test_gstr_partial_skips_with_parsed_do_not_require_acknowledgment():
    """Some skipped but parsed > 0 stays informational (pass + skip text)."""
    payload = json.dumps(
        {
            "data": {
                "gstin": "27AABCU9603R1ZM",
                "rtnprd": "042024",
                "b2b": [
                    {
                        "ctin": "29AABCU9603R1ZN",
                        "inv": [
                            {
                                "inum": "INV-OK",
                                "dt": "01-04-2024",
                                "val": 1000,
                                "pos": "27",
                                "rev": "N",
                                "itcavl": "Y",
                            },
                            {
                                "inum": "INV-BAD",
                                "dt": None,
                                "val": 1000,
                                "pos": "27",
                                "rev": "N",
                                "itcavl": "Y",
                            },
                        ],
                    }
                ],
            }
        }
    ).encode()
    checks, count = run_sanity_gstr2b_json(payload)
    assert count == 1
    records = next(c for c in checks if c["id"] == "records")
    assert records["status"] == "pass"
    assert records.get("requires_acknowledgment") is not True
    assert blocking_acknowledgments_pending(checks) is False


def test_upsert_preserves_ack_across_rebuild():
    prior = [
        {
            "id": MISSING_INVOICE_CHECK_ID,
            "status": "warning",
            "requires_acknowledgment": True,
            "acknowledged": True,
            "detail": "old",
        }
    ]
    rebuilt = build_missing_invoice_number_check(2, [])
    out = upsert_sanity_check(prior, rebuilt, check_id=MISSING_INVOICE_CHECK_ID)
    row = next(c for c in out if c["id"] == MISSING_INVOICE_CHECK_ID)
    assert row["acknowledged"] is True
    assert row["requires_acknowledgment"] is True


def test_preserve_check_acknowledgments_on_gstr_rerun():
    prior = [
        {
            "id": "records",
            "status": "warning",
            "requires_acknowledgment": True,
            "acknowledged": True,
            "detail": "old",
        }
    ]
    fresh = [
        {
            "id": "json_parse",
            "status": "pass",
            "detail": "",
            "affected_records": [],
        },
        {
            "id": "records",
            "status": "warning",
            "requires_acknowledgment": True,
            "acknowledged": False,
            "detail": "new",
            "affected_records": [],
        },
    ]
    merged = preserve_check_acknowledgments(prior, fresh)
    records = next(c for c in merged if c["id"] == "records")
    assert records["acknowledged"] is True
    assert records["detail"] == "new"


def test_detect_columns_style_upsert_of_both_pr_checks():
    sheets = [
        {"sheet": "Apr", "records": 1},
        {"sheet": "May", "records": 1},
    ]
    multi = build_multi_sheet_combine_check(sheets)
    missing = build_missing_invoice_number_check(1, ["missing invoice"])
    sanity: list = []
    sanity = upsert_sanity_check(sanity, multi)
    sanity = upsert_sanity_check(
        sanity, missing, check_id=MISSING_INVOICE_CHECK_ID
    )
    assert blocking_acknowledgments_pending(sanity) is True
    assert {c["id"] for c in unacknowledged_blocking_checks(sanity)} == {
        MULTI_SHEET_COMBINE_CHECK_ID,
        MISSING_INVOICE_CHECK_ID,
    }
    for c in sanity:
        c["acknowledged"] = True
    assert blocking_acknowledgments_pending(sanity) is False


def test_multi_sheet_parse_still_emits_combine_warning():
    raw = _xlsx_bytes({"Apr": _sheet("INV-1"), "May": _sheet("INV-2", "29AABCU9603R1ZN")})
    result = parse_purchase_register(raw, "multi.xlsx")
    assert len(result.get("sheets_used") or []) == 2
    assert "Combined 2 sheets" in " ".join(result.get("warnings") or [])
