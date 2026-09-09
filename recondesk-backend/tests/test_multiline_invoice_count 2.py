"""Regression: multi-item GSTR invoices / multi-row PR bookings must count once.

GSTR-2B stores one invoice with multiple ``itms`` (different tax rates) as a
single record with summed amounts. Purchase registers often book the same
invoice as two spreadsheet rows (one per rate). Those must reconcile as
exactly one Matched invoice — not two, and not a DUPLICATE_CLAIM review that
inflates Review Required beyond Total GSTR.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.matching.engine import run_bidirectional_reconciliation
from app.services.matcher import normalize_invoice
from app.services.reconciliation_payload_store import build_stored_results_payload
import app.services.reconciliation_outcomes as ro


GSTIN = "27AABCU1234R1ZX"
INV = "INV-MULTI-1001"
PERIOD = date(2024, 3, 1)
RUN_ID = "22222222-2222-2222-2222-222222222222"


def _gstr_multi_item():
    """One GSTR invoice whose amounts equal the sum of two tax-rate lines."""
    # Line A: taxable 1000 @ 18% → tax 180
    # Line B: taxable 500 @ 18% → tax 90
    taxable = 150_000  # paise
    tax = 27_000
    return {
        "id": "g-multi",
        "supplier_gstin": GSTIN,
        "invoice_number": INV,
        "invoice_number_normalized": normalize_invoice(INV),
        "invoice_date": date(2024, 3, 15),
        "taxable_amount_paise": taxable,
        "total_tax_paise": tax,
        "cgst_paise": tax // 2,
        "sgst_paise": tax - tax // 2,
        "igst_paise": 0,
    }


def _pr_split_rows():
    """Same invoice booked as two PR rows (two tax rates)."""
    return [
        {
            "id": "p-line-a",
            "supplier_gstin": GSTIN,
            "invoice_number": INV,
            "invoice_number_normalized": normalize_invoice(INV),
            "invoice_date": date(2024, 3, 15),
            "taxable_amount_paise": 100_000,
            "total_tax_paise": 18_000,
            "cgst_paise": 9_000,
            "sgst_paise": 9_000,
            "igst_paise": 0,
        },
        {
            "id": "p-line-b",
            "supplier_gstin": GSTIN,
            "invoice_number": INV,
            "invoice_number_normalized": normalize_invoice(INV),
            "invoice_date": date(2024, 3, 15),
            "taxable_amount_paise": 50_000,
            "total_tax_paise": 9_000,
            "cgst_paise": 4_500,
            "sgst_paise": 4_500,
            "igst_paise": 0,
        },
    ]


def test_multiline_pr_split_counts_as_exactly_one_match():
    """1 GSTR (multi-item totals) + 2 PR rows that sum to it → 1 matched, not 2."""
    gstr = [_gstr_multi_item()]
    pr = _pr_split_rows()
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    stats = res["stats"]

    assert stats["total_gstr"] == 1
    assert stats["clean_matched_count"] == 1, (
        f"Expected exactly 1 clean match for multi-line PR split, got "
        f"{stats['clean_matched_count']}; review={stats['review_required_count']} "
        f"reasons={[r.get('review_reason') for r in res['review_required']]}"
    )
    assert stats["review_required_count"] == 0
    assert stats["missed_itc_count"] == 0
    assert (
        stats["clean_matched_count"]
        + stats["review_required_count"]
        + stats["missed_itc_count"]
        == stats["total_gstr"]
    )
    assert len(res["matched"]) == 1
    # Both PR line rows must be consumed (neither left as ITC at Risk)
    assert stats["wrongful_risk_count"] == 0
    assert stats["sanity_passed"] is True


def test_multiline_kpi_sum_equals_total_gstr_via_outcome_rows():
    """API-style KPI cards must not inflate Review by counting PR-side markers.

    Reproduces the production discrepancy where Matched + Review + Missed ITC
    exceeded Total GSTR because PR-anchored DUPLICATE_CLAIM_PR rows were counted
    as review_required outcome rows.
    """
    gstr = [_gstr_multi_item()]
    pr = _pr_split_rows()
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)

    # Shape like the production stored payload (review → engine.duplicates).
    valid_review = []
    for r in res["review_required"]:
        gid = r.get("gstr_id") or ""
        pid = r.get("pr_id") or ""
        entry = dict(r)
        entry["reason"] = r.get("review_reason") or r.get("reason")
        if gid and pid:
            entry["id"] = pid
        elif gid:
            entry["side"] = "GSTR"
        elif pid:
            entry["side"] = "PR"
            entry["id"] = pid
        valid_review.append(entry)

    payload = build_stored_results_payload(
        matched=res["matched"],
        missed_itc=res["missed_itc"],
        wrongful_itc_risk=res["wrongful_itc_risk"],
        rule37=[],
        section_175_warnings=[],
        credit_note_adjustment={},
        late_filing=[],
        decision_payload={},
        matching_version="test",
        rules_version="test",
        decision_version="test",
        gstin_mismatch=[],
        duplicates=valid_review,
        review_required_typo=[],
    )

    g_matcher = gstr[0]
    g_db = {
        "id": "g-multi",
        "record_data": {
            "supplier_gstin": GSTIN,
            "supplier_name": "Multi Vendor",
            "invoice_number": INV,
            "invoice_date": "2024-03-15",
        },
    }
    pr_db = [
        {
            "id": p["id"],
            "record_data": {
                "supplier_gstin": GSTIN,
                "invoice_number": INV,
                "invoice_date": "2024-03-15",
            },
        }
        for p in pr
    ]

    class _FakeTable:
        def __init__(self, rows):
            self._rows = rows

        def select(self, *_a, **_k):
            return self

        def eq(self, *_a, **_k):
            return self

        def range(self, start, end):
            self._page = self._rows[start : end + 1]
            return self

        def execute(self):
            return SimpleNamespace(data=getattr(self, "_page", self._rows))

    class _FakeSB:
        def table(self, name):
            if name == "gstr_records":
                return _FakeTable(
                    [{"id": g_db["id"], "record_data": g_db["record_data"], **{
                        k: g_matcher[k] for k in (
                            "supplier_gstin", "invoice_number", "invoice_number_normalized",
                            "invoice_date", "taxable_amount_paise", "total_tax_paise",
                            "cgst_paise", "sgst_paise", "igst_paise",
                        )
                    }}]
                )
            if name == "pr_records":
                return _FakeTable(
                    [
                        {
                            "id": p["id"],
                            "record_data": pr_db[i]["record_data"],
                            **{
                                k: p[k]
                                for k in (
                                    "supplier_gstin",
                                    "invoice_number",
                                    "invoice_number_normalized",
                                    "invoice_date",
                                    "taxable_amount_paise",
                                    "total_tax_paise",
                                    "cgst_paise",
                                    "sgst_paise",
                                    "igst_paise",
                                )
                            },
                        }
                        for i, p in enumerate(pr)
                    ]
                )
            return _FakeTable([])

    # Monkeypatch loaders used by build_outcome_rows to avoid real DB.
    def _gstr_map(_sb, _rid):
        return {
            "g-multi": {
                "matcher": g_matcher,
                "record_data": g_db["record_data"],
            }
        }

    def _pr_map(_sb, _rid):
        return {
            p["id"]: {"matcher": p, "record_data": pr_db[i]["record_data"]}
            for i, p in enumerate(pr)
        }

    orig_g, orig_p = ro._load_gstr_map, ro._load_pr_map
    ro._load_gstr_map = _gstr_map
    ro._load_pr_map = _pr_map
    try:
        rows, ccounts, _money = ro.build_outcome_rows(_FakeSB(), RUN_ID, payload)
    finally:
        ro._load_gstr_map = orig_g
        ro._load_pr_map = orig_p

    matched_n = sum(1 for r in rows if r.category == "matched")
    # GSTR-anchored review only — PR-side markers must not inflate this KPI.
    review_n = sum(
        1
        for r in rows
        if r.category == "review_required" and not str(r.id).startswith("dp:")
    )
    missed_n = sum(1 for r in rows if r.category == "missed_itc")
    total_gstr = 1

    assert matched_n + review_n + missed_n == total_gstr, (
        f"KPI sum {matched_n}+{review_n}+{missed_n}={matched_n + review_n + missed_n} "
        f"!= Total GSTR {total_gstr}; categories={ccounts}"
    )
    assert matched_n == 1
    assert review_n == 0
