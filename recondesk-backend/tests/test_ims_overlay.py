"""Unit tests for IMS overlay helpers."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.ims_overlay import (
    DEFAULT_IMS_STATUS,
    apply_ims_status_to_matcher_rows,
    build_ims_status_map,
    ims_composite_key,
)
from app.services.matcher import normalize_invoice
from app.services.reconciliation_payload_store import (
    slim_duplicates,
    slim_engine_matched,
    slim_missed_itc,
)
from app.services.reconciliation_record_adapter import gstr_db_row_to_matcher_row
from app.services.sandbox_gst_client import (
    _parse_ims_section,
    _unwrap_sandbox_envelope,
)

FIXTURES = (
    Path(__file__).resolve().parent.parent / "test_fixtures" / "sandbox"
)


def _load_fixture_invoices():
    raw = json.loads((FIXTURES / "sample_ims_response.json").read_text(encoding="utf-8"))
    inner = _unwrap_sandbox_envelope(raw)
    sections = inner.get("data") if isinstance(inner, dict) and "data" in inner else inner
    invoices = []
    if isinstance(sections, dict):
        for key in ("b2b", "cn"):
            entries = sections.get(key) or []
            if isinstance(entries, list):
                invoices.extend(_parse_ims_section(key, entries))
    return invoices


def test_ims_composite_key_normalizes_invoice_and_gstin():
    key = ims_composite_key(" 27aabcu9603r1zp ", "INV-2024-001")
    assert key == ("27AABCU9603R1ZP", normalize_invoice("INV-2024-001"))


def test_build_ims_status_map_from_fixture():
    invoices = _load_fixture_invoices()
    status_map = build_ims_status_map(invoices, return_period="112024")
    assert len(status_map) >= 3

    pending_key = ims_composite_key("27AABCU9603R1ZP", "INV2024-001")
    rejected_key = ims_composite_key("07AAACR5055K1ZE", "GST/2024/555")
    assert status_map[pending_key] == "pending"
    assert status_map[rejected_key] == "rejected"


def test_apply_ims_status_to_matcher_rows():
    invoices = _load_fixture_invoices()
    status_map = build_ims_status_map(invoices, return_period="112024")
    rows = [
        {
            "id": "1",
            "supplier_gstin": "27AABCU9603R1ZP",
            "invoice_number": "INV2024-001",
            "invoice_number_normalized": normalize_invoice("INV2024-001"),
        },
        {
            "id": "2",
            "supplier_gstin": "27AAAAA0000A1Z5",
            "invoice_number": "UNKNOWN-1",
            "invoice_number_normalized": normalize_invoice("UNKNOWN-1"),
        },
    ]
    hits = apply_ims_status_to_matcher_rows(rows, status_map)
    assert hits == 1
    assert rows[0]["ims_status"] == "pending"
    assert rows[1]["ims_status"] == DEFAULT_IMS_STATUS


def test_adapter_passes_through_ims_status():
    row = {
        "id": "g1",
        "record_data": {
            "supplier_gstin": "27AABCU9603R1ZP",
            "invoice_number": "INV-1",
            "invoice_number_norm": "INV1",
            "ims_status": "accepted",
            "cgst_paise": 0,
            "sgst_paise": 0,
            "igst_paise": 18000,
            "total_tax_paise": 18000,
        },
    }
    matcher = gstr_db_row_to_matcher_row(row)
    assert matcher["ims_status"] == "accepted"


def test_adapter_defaults_ims_status_when_missing():
    row = {
        "id": "g2",
        "record_data": {
            "supplier_gstin": "27AABCU9603R1ZP",
            "invoice_number": "INV-2",
            "total_tax_paise": 0,
        },
    }
    matcher = gstr_db_row_to_matcher_row(row)
    assert matcher["ims_status"] == "no_action_taken"


def test_slim_keys_preserve_ims_status():
    matched = slim_engine_matched(
        [{"gstr_id": "a", "pr_id": "b", "ims_status": "pending", "noise": 1}]
    )
    missed = slim_missed_itc(
        [
            {
                "gstr_id": "a",
                "supplier_gstin": "27A",
                "invoice_number_normalized": "INV1",
                "ims_status": "rejected",
                "noise": 1,
            }
        ]
    )
    dups = slim_duplicates(
        [
            {
                "gstr_id": "a",
                "id": "p",
                "ims_status": "accepted",
                "reason": "GSTIN_MISMATCH",
                "noise": 1,
            }
        ]
    )
    assert matched[0]["ims_status"] == "pending"
    assert "noise" not in matched[0]
    assert missed[0]["ims_status"] == "rejected"
    assert dups[0]["ims_status"] == "accepted"
