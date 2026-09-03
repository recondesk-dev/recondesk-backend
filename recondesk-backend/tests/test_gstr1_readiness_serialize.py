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


def test_b2cs_net_negative_bucket_serialization_and_accounting():
    # 1 gross B2CS invoice for ₹1,000 + 1 unregistered CN for ₹2,000 -> net -₹1,000
    b2c_row = {
        "row_number": 1,
        "gstin": None,
        "gstin_valid": False,
        "invoice_type": "B2C",
        "invoice_type_raw": None,
        "invoice_number_raw": "B2C-1",
        "invoice_date": "2025-04-05",
        "place_of_supply": "27-Maharashtra",
        "taxable_amount_paise": 100_000,
        "cgst_paise": 9_000,
        "sgst_paise": 9_000,
        "igst_paise": 0,
        "cess_paise": 0,
        "total_amount_paise": 118_000,
        "tax_rate": 18.0,
    }
    cn_row = {
        "row_number": 2,
        "gstin": None,
        "gstin_valid": False,
        "invoice_type": "CREDIT_NOTE",
        "invoice_type_raw": "Credit Note",
        "invoice_number_raw": "CN-1",
        "invoice_date": "2025-04-10",
        "place_of_supply": "27-Maharashtra",
        "taxable_amount_paise": 200_000,
        "cgst_paise": 18_000,
        "sgst_paise": 18_000,
        "igst_paise": 0,
        "cess_paise": 0,
        "total_amount_paise": 236_000,
        "tax_rate": 18.0,
        "note_type": "C",
    }

    mapped = map_sales_register_to_gstr1(
        [b2c_row, cn_row],
        filer_state="27",
        filing_period="2025-04",
    )
    # Row accounting: neither should be counted as saved; both accounted as pending
    acct = mapped.row_accounting
    assert acct.total_rows == 2
    assert acct.saved == 0
    assert acct.pending_review == 2
    assert acct.sums_to_total

    payload = serialize_gstr1_readiness(mapped)
    assert payload["pending_review_count"] == 1
    item = payload["pending_review"][0]
    assert item["reason"] == "b2cs_net_negative_bucket"
    assert item["decision_needed"] == "net_negative_adjustment"
    ctx = item["context"]
    assert ctx["is_aggregate_bucket"] is True
    assert ctx["place_of_supply"] == "27"
    assert ctx["tax_rate"] == 18.0
    assert ctx["taxable_amount_paise"] == -100_000
    assert ctx["contributing_record_count"] == 2
    assert any("net negative" in a for a in payload["filing_readiness"]["advisory"])
