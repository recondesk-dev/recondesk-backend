"""Tests for persistent PR column mapping (client_import_mappings)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi import HTTPException

from app.services import client_import_mapping as cim
from app.services.client_import_mapping import MappingItem, TargetField


def _item(src: str, tf: str) -> MappingItem:
    return MappingItem(source_column_name=src, target_field=TargetField(tf))


def _complete_items() -> list[MappingItem]:
    return [
        _item("Party GST", "gstin"),
        _item("Bill No", "invoice_number"),
        _item("Bill Date", "invoice_date"),
        _item("Assessable", "taxable_value"),
        _item("IGST Amt", "igst"),
    ]


# ── Validation ───────────────────────────────────────────────────────────────


def test_validate_mapping_requires_core_and_tax():
    with pytest.raises(HTTPException) as ei:
        cim.validate_mapping_items(
            [
                _item("A", "gstin"),
                _item("B", "invoice_number"),
                _item("C", "invoice_date"),
                _item("D", "taxable_value"),
            ]
        )
    assert ei.value.status_code == 422
    detail = ei.value.detail
    assert detail["missing_tax"] is True


def test_validate_mapping_blocks_partial_required():
    with pytest.raises(HTTPException) as ei:
        cim.validate_mapping_items(
            [
                _item("A", "gstin"),
                _item("B", "invoice_number"),
                _item("C", "igst"),
            ]
        )
    assert ei.value.status_code == 422
    assert "invoice_date" in ei.value.detail["missing_required"]
    assert "taxable_value" in ei.value.detail["missing_required"]


def test_validate_mapping_blocks_duplicate_target():
    with pytest.raises(HTTPException) as ei:
        cim.validate_mapping_items(
            [
                _item("A", "gstin"),
                _item("B", "gstin"),
                _item("C", "invoice_number"),
                _item("D", "invoice_date"),
                _item("E", "taxable_value"),
                _item("F", "igst"),
            ]
        )
    assert ei.value.status_code == 422
    assert "Duplicate target_field" in ei.value.detail["message"]


def test_validate_complete_mapping_ok():
    cim.validate_mapping_items(_complete_items())  # no raise


# ── Save / retrieve (mocked Supabase) ────────────────────────────────────────


class _FakeTable:
    def __init__(self, store: dict[str, list[dict[str, Any]]]):
        self.store = store
        self._eq: dict[str, Any] = {}
        self._op: str | None = None
        self._payload: Any = None

    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def insert(self, rows):
        self._op = "insert"
        self._payload = rows
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, col, val):
        self._eq[col] = val
        return self

    def order(self, *_a, **_k):
        return self

    def execute(self):
        cid = self._eq.get("client_gstin_id")
        if self._op == "delete":
            self.store[cid] = []
            return MagicMock(data=[])
        if self._op == "insert":
            rows = self._payload if isinstance(self._payload, list) else [self._payload]
            existing = self.store.setdefault(cid or rows[0]["client_gstin_id"], [])
            for r in rows:
                existing.append(
                    {
                        "id": f"id-{len(existing)}",
                        **r,
                        "created_at": "2026-07-09T00:00:00Z",
                        "updated_at": "2026-07-09T00:00:00Z",
                    }
                )
            return MagicMock(data=rows)
        # select
        data = list(self.store.get(cid, []))
        data.sort(key=lambda r: r.get("target_field") or "")
        return MagicMock(data=data)


class _FakeSB:
    def __init__(self):
        self.store: dict[str, list[dict[str, Any]]] = {}

    def table(self, name: str):
        assert name == cim.T_MAPPINGS
        return _FakeTable(self.store)


def test_save_and_retrieve_mapping():
    sb = _FakeSB()
    cid = "11111111-1111-1111-1111-111111111111"
    saved = cim.save_mappings(sb, cid, _complete_items())
    assert len(saved) == 5
    assert {r["target_field"] for r in saved} == {
        "gstin",
        "invoice_number",
        "invoice_date",
        "taxable_value",
        "igst",
    }
    got = cim.get_mappings_or_none(sb, cid)
    assert got is not None
    assert len(got) == 5
    assert cim.get_mappings_or_none(sb, "00000000-0000-0000-0000-000000000000") is None


def test_save_replaces_previous_mapping():
    sb = _FakeSB()
    cid = "22222222-2222-2222-2222-222222222222"
    cim.save_mappings(sb, cid, _complete_items())
    updated = cim.save_mappings(
        sb,
        cid,
        [
            _item("GSTIN Col", "gstin"),
            _item("Inv", "invoice_number"),
            _item("Dt", "invoice_date"),
            _item("TV", "taxable_value"),
            _item("CGST Col", "cgst"),
            _item("SGST Col", "sgst"),
        ],
    )
    assert len(updated) == 6
    assert any(r["source_column_name"] == "GSTIN Col" for r in updated)


def test_delete_mapping():
    sb = _FakeSB()
    cid = "33333333-3333-3333-3333-333333333333"
    cim.save_mappings(sb, cid, _complete_items())
    cim.delete_mappings(sb, cid)
    assert cim.get_mappings_or_none(sb, cid) is None


# ── Header / schema / reshape ────────────────────────────────────────────────


def test_columns_match_expected_schema_standard_headers():
    headers = [
        "Supplier GSTIN",
        "Invoice Number",
        "Invoice Date",
        "Taxable Value",
        "IGST",
        "CGST",
        "SGST",
    ]
    assert cim.columns_match_expected_schema(headers) is True


def test_columns_do_not_match_custom_headers():
    headers = ["Party GST", "Bill No", "Bill Date", "Assessable", "IGST Amt"]
    assert cim.columns_match_expected_schema(headers) is False


def test_mapping_covers_headers():
    mappings = [
        {"source_column_name": "Party GST", "target_field": "gstin"},
        {"source_column_name": "Bill No", "target_field": "invoice_number"},
        {"source_column_name": "Bill Date", "target_field": "invoice_date"},
        {"source_column_name": "Assessable", "target_field": "taxable_value"},
        {"source_column_name": "IGST Amt", "target_field": "igst"},
    ]
    headers = ["Party GST", "Bill No", "Bill Date", "Assessable", "IGST Amt", "Extra"]
    assert cim.mapping_covers_headers(mappings, headers) is True
    assert cim.mapping_covers_headers(mappings, ["Party GST", "Bill No"]) is False


def test_partial_mapping_does_not_cover():
    mappings = [
        {"source_column_name": "Party GST", "target_field": "gstin"},
        {"source_column_name": "Bill No", "target_field": "invoice_number"},
    ]
    headers = ["Party GST", "Bill No", "Bill Date", "Assessable", "IGST Amt"]
    assert cim.mapping_covers_headers(mappings, headers) is False


def test_apply_mapping_renames_before_parser():
    df = pd.DataFrame(
        {
            "Party GST": ["29AAACR5055K1Z5"],
            "Bill No": ["INV-1"],
            "Bill Date": ["01-04-2026"],
            "Assessable": ["1000"],
            "IGST Amt": ["180"],
        }
    )
    mappings = [
        {"source_column_name": "Party GST", "target_field": "gstin"},
        {"source_column_name": "Bill No", "target_field": "invoice_number"},
        {"source_column_name": "Bill Date", "target_field": "invoice_date"},
        {"source_column_name": "Assessable", "target_field": "taxable_value"},
        {"source_column_name": "IGST Amt", "target_field": "igst"},
    ]
    out = cim.apply_mapping_to_dataframe(df, mappings)
    assert "Supplier GSTIN" in out.columns
    assert "Invoice Number" in out.columns
    assert "Taxable Value" in out.columns
    assert "IGST" in out.columns
    assert cim.columns_match_expected_schema(list(out.columns)) is True


def test_reshape_then_parse_succeeds():
    from app.parsers.purchase_register_parser import parse_purchase_register

    csv = (
        "Party GST,Bill No,Bill Date,Assessable,IGST Amt\n"
        "29AAACR5055K1Z5,INV-1,01-04-2026,1000,180\n"
    ).encode("utf-8")
    mappings = [
        {"source_column_name": "Party GST", "target_field": "gstin"},
        {"source_column_name": "Bill No", "target_field": "invoice_number"},
        {"source_column_name": "Bill Date", "target_field": "invoice_date"},
        {"source_column_name": "Assessable", "target_field": "taxable_value"},
        {"source_column_name": "IGST Amt", "target_field": "igst"},
    ]
    body, name = cim.reshape_file_with_mapping(csv, "custom.csv", mappings)
    result = parse_purchase_register(body, name)
    assert result["success"] is True
    assert result["valid_rows"] >= 1


def test_upload_without_mapping_custom_headers_needs_mapping():
    """No saved mapping + non-standard headers → schema check fails (422 path)."""
    headers = ["Party GST", "Bill No", "Bill Date", "Assessable", "IGST Amt"]
    assert cim.columns_match_expected_schema(headers) is False
    assert cim.get_mappings_or_none(_FakeSB(), "x") is None


def test_upload_with_existing_mapping_auto_applies():
    headers = ["Party GST", "Bill No", "Bill Date", "Assessable", "IGST Amt"]
    mappings = [
        {"source_column_name": h, "target_field": t}
        for h, t in zip(
            headers,
            ["gstin", "invoice_number", "invoice_date", "taxable_value", "igst"],
        )
    ]
    assert cim.mapping_covers_headers(mappings, headers) is True
    df = pd.DataFrame([{h: "1" for h in headers}])
    reshaped = cim.apply_mapping_to_dataframe(df, mappings)
    assert cim.columns_match_expected_schema(list(reshaped.columns)) is True


def test_broken_mapping_blocks_with_clear_error():
    with pytest.raises(HTTPException) as ei:
        cim.validate_mapping_items(
            [
                _item("Party GST", "gstin"),
                _item("Bill No", "invoice_number"),
                # missing invoice_date, taxable_value, tax
            ]
        )
    assert ei.value.status_code == 422
    detail = ei.value.detail
    assert "Mapping incomplete" in detail["message"]
    assert detail["missing_tax"] is True
    assert "invoice_date" in detail["missing_required"]
