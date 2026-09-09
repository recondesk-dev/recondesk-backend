"""Unit tests for GSTR-3B draft suggestion builders (read-side only)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.filing.gstr3b_suggestions import (
    REASON_NO_GSTR1_AGGREGATE,
    REASON_NO_GSTR1_RUN,
    REASON_NO_GSTR2B_RECORDS,
    REASON_NO_GSTR2B_RUN,
    load_itc_oth_suggestion,
    load_osup_det_suggestion,
    osup_det_from_gstr1_aggregate,
    suggest_itc_oth_from_gstr2b_records,
    suggest_osup_det_from_gstr1_records,
)
from app.reconciliation.gstr1_vs_3b import GSTR1Aggregate, aggregate_gstr1


def test_osup_det_from_aggregate_converts_paise_to_rupees():
    agg = GSTR1Aggregate(
        taxable_value_paise=100_50,
        igst_paise=18_00,
        cgst_paise=9_00,
        sgst_paise=9_00,
        cess_paise=50,
        record_count=2,
    )
    assert osup_det_from_gstr1_aggregate(agg) == {
        "txval": 100.5,
        "iamt": 18.0,
        "camt": 9.0,
        "samt": 9.0,
        "csamt": 0.5,
    }


def test_suggest_osup_det_uses_aggregate_gstr1_not_zero_rated():
    records = [
        {
            "section": "b2b",
            "taxable_amount_paise": 100_000,
            "igst_paise": 18_000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
        },
        {
            "section": "exp",  # zero-rated — excluded from 3.1(a)
            "taxable_amount_paise": 50_000,
            "igst_paise": 0,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
        },
        {
            "section": "cdnr",
            "taxable_amount_paise": 10_000,
            "igst_paise": 1_800,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
        },
    ]
    # Sanity: same as aggregate_gstr1 defaults used for 3.1(a).
    agg = aggregate_gstr1(records, include_cdn=True, include_zero_rated=False)
    out = suggest_osup_det_from_gstr1_records(records)
    assert out["available"] is True
    assert out["record_count"] == agg.record_count
    assert out["osup_det"] == osup_det_from_gstr1_aggregate(agg)
    assert out["osup_det"]["txval"] == 900.0  # 1000 - 100 CDN
    assert out["osup_det"]["iamt"] == 162.0


def test_suggest_osup_det_unavailable_when_no_records():
    out = suggest_osup_det_from_gstr1_records([])
    assert out["available"] is False
    assert out["reason"] == REASON_NO_GSTR1_AGGREGATE


def test_suggest_itc_oth_uses_accumulate_gstr2b_available_itc():
    records = [
        {
            "doc_type": "INVOICE",
            "itc_available": True,
            "items": [{"igst_paise": 10_000, "cgst_paise": 5_000, "sgst_paise": 5_000}],
        },
        {
            "doc_type": "CREDIT_NOTE",
            "itc_available": True,
            "items": [{"igst_paise": 2_000, "cgst_paise": 0, "sgst_paise": 0}],
        },
        {
            "doc_type": "INVOICE",
            "itc_available": False,  # skipped
            "items": [{"igst_paise": 99_000, "cgst_paise": 0, "sgst_paise": 0}],
        },
    ]
    out = suggest_itc_oth_from_gstr2b_records(records)
    assert out["available"] is True
    assert out["iamt"] == 80.0
    assert out["camt"] == 50.0
    assert out["samt"] == 50.0
    assert out["csamt"] == 0.0
    assert out["record_count"] == 3


def test_suggest_itc_oth_unavailable_when_empty():
    out = suggest_itc_oth_from_gstr2b_records([])
    assert out["available"] is False
    assert out["reason"] == REASON_NO_GSTR2B_RECORDS


def test_load_osup_det_from_stored_tie_out():
    sb = MagicMock()
    run = {
        "id": "g1-run-1",
        "period": "2026-05-01",
        "result_payload": {
            "tie_out": {
                "gstr1_record_count": 4,
                "gstr1": {
                    "taxable_value_paise": 200_00,
                    "igst_paise": 0,
                    "cgst_paise": 18_00,
                    "sgst_paise": 18_00,
                    "cess_paise": 0,
                    "record_count": 4,
                },
            }
        },
    }
    q = MagicMock()
    sb.table.return_value = q
    q.select.return_value = q
    q.eq.return_value = q
    q.order.return_value = q
    q.limit.return_value = q
    q.execute.return_value = MagicMock(data=[run])

    out = load_osup_det_suggestion(
        sb, client_gstin_id="client-1", period="2026-05",
    )
    assert out["available"] is True
    assert out["run_id"] == "g1-run-1"
    assert out["osup_det"] == {
        "txval": 200.0,
        "iamt": 0.0,
        "camt": 18.0,
        "samt": 18.0,
        "csamt": 0.0,
    }


def test_load_osup_det_missing_run():
    sb = MagicMock()
    q = MagicMock()
    sb.table.return_value = q
    q.select.return_value = q
    q.eq.return_value = q
    q.order.return_value = q
    q.limit.return_value = q
    q.execute.return_value = MagicMock(data=[])

    out = load_osup_det_suggestion(
        sb, client_gstin_id="client-1", period="2026-05",
    )
    assert out["available"] is False
    assert out["reason"] == REASON_NO_GSTR1_RUN


def test_load_itc_oth_from_gstr_records():
    sb = MagicMock()

    def table(name: str):
        t = MagicMock()
        t.select.return_value = t
        t.eq.return_value = t
        t.in_.return_value = t
        t.order.return_value = t
        t.limit.return_value = t
        t.range.return_value = t
        if name == "reconciliation_run":
            t.execute.return_value = MagicMock(
                data=[
                    {
                        "id": "run-2b",
                        "period": "2026-05",
                        "status": "COMPLETED",
                    }
                ]
            )
        else:
            t.execute.return_value = MagicMock(
                data=[
                    {
                        "record_data": {
                            "doc_type": "INVOICE",
                            "itc_available": True,
                            "igst_paise": 25_000,
                            "cgst_paise": 0,
                            "sgst_paise": 0,
                            "items": [],
                        }
                    }
                ]
            )
        return t

    sb.table.side_effect = table
    out = load_itc_oth_suggestion(
        sb, client_gstin_id="client-1", period="2026-05",
    )
    assert out["available"] is True
    assert out["run_id"] == "run-2b"
    assert out["iamt"] == 250.0
    assert out["camt"] == 0.0


def test_load_itc_oth_missing_run():
    sb = MagicMock()
    q = MagicMock()
    sb.table.return_value = q
    q.select.return_value = q
    q.eq.return_value = q
    q.in_.return_value = q
    q.order.return_value = q
    q.limit.return_value = q
    q.execute.return_value = MagicMock(data=[])

    out = load_itc_oth_suggestion(
        sb, client_gstin_id="client-1", period="2026-05",
    )
    assert out["available"] is False
    assert out["reason"] == REASON_NO_GSTR2B_RUN
