"""GSTR-3B overall badge must not use 'any overclaim wins'."""

from __future__ import annotations

from app.routers.reconciliation_api import _gstr3b_row_to_response
from app.services.gstr3b_reconciliation import (
    MATCHED,
    MIXED,
    OVERCLAIMED,
    UNDERCLAIMED,
    _overall_status,
)


def test_overall_status_mixed_when_heads_disagree():
    assert (
        _overall_status(UNDERCLAIMED, OVERCLAIMED, OVERCLAIMED) == MIXED
    )
    assert _overall_status(OVERCLAIMED, UNDERCLAIMED, MATCHED) == MIXED


def test_overall_status_unanimous_directions():
    assert _overall_status(OVERCLAIMED, OVERCLAIMED, MATCHED) == OVERCLAIMED
    assert _overall_status(UNDERCLAIMED, MATCHED, UNDERCLAIMED) == UNDERCLAIMED
    assert _overall_status(MATCHED, MATCHED, MATCHED) == MATCHED


def test_row_to_response_uses_mixed_and_net_total_status():
    """June-style case: IGST underclaimed, CGST/SGST overclaimed, net underclaimed."""
    row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "run_id": "22222222-2222-2222-2222-222222222222",
        "client_gstin": "27ISKPK1273H1ZF",
        "tax_period": "2026-06",
        # Stale stored badge — must be recomputed to MIXED on read.
        "overall_status": "OVERCLAIMED",
        "gstr2b_igst_available": 180840.70,
        "gstr2b_cgst_available": 2662.61,
        "gstr2b_sgst_available": 2662.61,
        "gstr3b_igst_claimed": 73021.53,
        "gstr3b_cgst_claimed": 54766.15,
        "gstr3b_sgst_claimed": 54766.15,
        "igst_difference": -107819.17,
        "cgst_difference": 52103.54,
        "sgst_difference": 52103.54,
        "igst_status": "UNDERCLAIMED",
        "cgst_status": "OVERCLAIMED",
        "sgst_status": "OVERCLAIMED",
        "outward_supply_total": 0,
        "uploaded_at": "2026-07-21T00:00:00+00:00",
    }
    resp = _gstr3b_row_to_response(row)
    assert resp.overall_status == MIXED
    assert resp.total.difference == -3612.09
    assert resp.total.status == UNDERCLAIMED
