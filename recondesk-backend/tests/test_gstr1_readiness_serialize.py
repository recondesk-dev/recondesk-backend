"""Readiness API serialization shape (orchestrator → frontend contract)."""

from __future__ import annotations

from app.filing.gstr1_orchestrator import (
    map_sales_register_to_gstr1,
    serialize_gstr1_readiness,
)


def _sr(**overrides):
    base = {
        "row_number": 2,
        "gstin": "06AACVV3456J1Z3",
        "gstin_valid": True,
        "invoice_type": "B2B",
        "invoice_type_raw": "SEZ with payment",
        "invoice_number": "RD1",
        "invoice_number_raw": "RD/1",
        "invoice_date": "2025-04-08",
        "place_of_supply": "06-Haryana",
        "taxable_amount_paise": 10000,
        "igst_paise": 1800,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "cess_paise": 0,
        "total_tax_paise": 1800,
        "total_amount_paise": 11800,
        "tax_rate": 18.0,
    }
    base.update(overrides)
    return base


def test_serialize_gstr1_readiness_shape():
    mapped = map_sales_register_to_gstr1(
        [_sr()],
        filer_state="27",
        filing_period="2025-04",
    )
    payload = serialize_gstr1_readiness(mapped)

    assert payload["filing_period"] == "2025-04"
    assert payload["filer_state"] == "27"
    fr = payload["filing_readiness"]
    assert set(fr) >= {
        "can_save",
        "can_file",
        "summary",
        "save_blockers",
        "file_blockers",
        "advisory",
    }
    assert isinstance(fr["can_save"], bool)
    assert isinstance(fr["can_file"], bool)
    assert isinstance(payload["pending_review"], list)
    assert isinstance(payload["pending_review_by_table"], dict)
    assert isinstance(payload["external_input_gaps"], list)
    assert "save_section_keys" in payload
    assert "row_accounting" in payload

    # Non-R inv_typ text → pending with CA decision context
    assert payload["pending_review_count"] >= 1
    item = payload["pending_review"][0]
    assert item["decision_needed"] in {
        "inv_typ",
        "ntty",
        "exp_typ",
        "table_classification",
    }
    assert "context" in item
    assert "invoice_number_raw" in item["context"] or "invoice_number" in item["context"]
