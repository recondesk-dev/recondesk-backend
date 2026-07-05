"""
Regression guard for the "blank ghost row" bug in build_outcome_rows.

Root cause (see app/services/reconciliation_outcomes.py): _load_gstr_map and
_load_pr_map paginated assuming each `.range(off, off + 1999)` call returns up
to 2,000 rows, and used `len(rows) < 2000` as the "no more data" signal. In
reality Supabase/PostgREST caps every request at 1,000 rows regardless of the
range window requested, so the very first page already satisfied
`len(rows) < 2000` and the loop exited having loaded only the first ~1,000
records -- silently dropping the rest of the run's gstr_records / pr_records
from the lookup maps.

Any Matched / Missed ITC / ITC at Risk / Review Required row whose gstr_id or
pr_id fell outside that truncated first page then rendered with blank
supplier_gstin / invoice_number / invoice_date / amount fields, even though
the category *counts* were unaffected (those come from the complete engine
lists, not the truncated maps).

This test builds a 6,000 GSTR / 6,000 PR synthetic dataset (same category
mix as tests/test_benchmark_6k.py, scaled to comfortably exceed the
1,000-row-per-request cap on both tables), runs it through the real matching
engine, shapes the result exactly like the production stored payload via
build_stored_results_payload, and feeds it through build_outcome_rows against
a fake Supabase client that faithfully reproduces the server's 1,000-row cap
(it truncates every response to at most 1,000 rows regardless of the
requested `.range()` window -- exactly the condition that triggered the real
bug). It asserts that EVERY row in EVERY category has non-blank display
fields, not just that the category counts are correct.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import app.services.reconciliation_outcomes as ro
from app.matching.engine import run_bidirectional_reconciliation
from app.services.matcher import normalize_invoice
from app.services.reconciliation_payload_store import build_stored_results_payload

RUN_ID = "11111111-1111-1111-1111-111111111111"
PERIOD = date(2024, 3, 1)

# Same category mix as tests/test_benchmark_6k.py -- comfortably exceeds the
# 1,000-row-per-request server cap on both the gstr_records and pr_records
# side (6,000 rows each).
N_MATCHED = 4200
N_TYPO = 675
N_AMOUNT_MISMATCH = 675
N_MISSED = 450
N_RISK = 450


def _gstin(i: int) -> str:
    return f"27AABCU{i:04d}R1ZX"


def _gstr_pair(rid: str, gstin: str, inv: str, tax_rupees: int) -> tuple[dict, dict]:
    """Return (matcher-feed dict for the engine, DB row for gstr_records)."""
    taxable_paise = tax_rupees * 100
    tax_paise = int(taxable_paise * 0.18)
    matcher = {
        "id": rid,
        "supplier_gstin": gstin,
        "invoice_number": inv,
        "invoice_number_normalized": normalize_invoice(inv),
        "invoice_date": date(2024, 3, 15),
        "taxable_amount_paise": taxable_paise,
        "total_tax_paise": tax_paise,
        "cgst_paise": tax_paise // 2,
        "sgst_paise": tax_paise - tax_paise // 2,
        "igst_paise": 0,
    }
    db_row = {
        "id": rid,
        "record_data": {
            "supplier_gstin": gstin,
            "supplier_name": f"Vendor {gstin}",
            "invoice_number": inv,
            "invoice_date": "2024-03-15",
            "invoice_value_paise": taxable_paise,
            "cgst_paise": tax_paise // 2,
            "sgst_paise": tax_paise - tax_paise // 2,
            "igst_paise": 0,
        },
    }
    return matcher, db_row


def _pr_pair(rid: str, gstin: str, inv: str, tax_rupees: int) -> tuple[dict, dict]:
    taxable_paise = tax_rupees * 100
    tax_paise = int(taxable_paise * 0.18)
    matcher = {
        "id": rid,
        "supplier_gstin": gstin,
        "invoice_number": inv,
        "invoice_number_normalized": normalize_invoice(inv),
        "invoice_date": date(2024, 3, 15),
        "taxable_amount_paise": taxable_paise,
        "total_tax_paise": tax_paise,
        "cgst_paise": tax_paise // 2,
        "sgst_paise": tax_paise - tax_paise // 2,
        "igst_paise": 0,
    }
    db_row = {
        "id": rid,
        "record_data": {
            "gstin": gstin,
            "supplier_name": f"Vendor {gstin}",
            "invoice_number": inv,
            "invoice_date": "2024-03-15",
            "taxable_amount_paise": taxable_paise,
            "cgst_paise": tax_paise // 2,
            "sgst_paise": tax_paise - tax_paise // 2,
            "igst_paise": 0,
            "total_tax_paise": tax_paise,
        },
    }
    return matcher, db_row


def _build_dataset() -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    gstr_matcher: list[dict] = []
    pr_matcher: list[dict] = []
    gstr_db: list[dict] = []
    pr_db: list[dict] = []
    idx = 0

    for i in range(N_MATCHED):
        gstin = _gstin(idx)
        idx += 1
        inv = f"INV{i}"
        gm, gd = _gstr_pair(f"g_clean_{i}", gstin, inv, 1000)
        pm, pd = _pr_pair(f"p_clean_{i}", gstin, inv, 1000)
        gstr_matcher.append(gm)
        gstr_db.append(gd)
        pr_matcher.append(pm)
        pr_db.append(pd)

    for i in range(N_TYPO):
        gstin = _gstin(idx)
        idx += 1
        gm, gd = _gstr_pair(f"g_rr_typo_{i}", gstin, f"TYPO{i}", 2000)
        pm, pd = _pr_pair(f"p_rr_typo_{i}", gstin, f"TYPO{i}-A", 2000)
        gstr_matcher.append(gm)
        gstr_db.append(gd)
        pr_matcher.append(pm)
        pr_db.append(pd)

    for i in range(N_AMOUNT_MISMATCH):
        gstin = _gstin(idx)
        idx += 1
        inv = f"AMT{i}"
        gm, gd = _gstr_pair(f"g_rr_amt_{i}", gstin, inv, 3000)
        pm, pd = _pr_pair(f"p_rr_amt_{i}", gstin, inv, 3005)  # genuine Rs5 diff
        gstr_matcher.append(gm)
        gstr_db.append(gd)
        pr_matcher.append(pm)
        pr_db.append(pd)

    for i in range(N_MISSED):
        gstin = _gstin(idx)
        idx += 1
        gm, gd = _gstr_pair(f"g_missed_{i}", gstin, f"MISS{i}", 4000)
        gstr_matcher.append(gm)
        gstr_db.append(gd)

    for i in range(N_RISK):
        gstin = _gstin(idx)
        idx += 1
        pm, pd = _pr_pair(f"p_risk_{i}", gstin, f"RISK{i}", 5000)
        pr_matcher.append(pm)
        pr_db.append(pd)

    return gstr_matcher, pr_matcher, gstr_db, pr_db


def _to_valid_review_required(review_required: list[dict]) -> list[dict]:
    """Mirror the exact gstr_id/pr_id -> id/side normalisation performed in
    app/worker/reconciliation_task.py before persisting review_required rows
    as the "duplicates" engine bucket, so this test reproduces the real
    production payload shape rather than an idealised one."""
    out = []
    for r in review_required:
        gid = r.get("gstr_id")
        pid = r.get("pr_id")
        if not gid and not pid:
            continue
        gid_valid = gid and str(gid).strip() and str(gid).strip() != "None"
        pid_valid = pid and str(pid).strip() and str(pid).strip() != "None"
        if gid_valid and pid_valid:
            r["gstr_id"] = gid
            r["id"] = pid
        elif gid_valid:
            r["side"] = "GSTR"
            r["gstr_id"] = gid
        elif pid_valid:
            r["side"] = "PR"
            r["id"] = pid
        out.append(r)
    return out


class _FakeResult:
    def __init__(self, data: list[dict], count: int | None = None):
        self.data = data
        self.count = count


class _FakeTable:
    """Reproduces Supabase/PostgREST's real behaviour of capping every
    response at 1,000 rows, regardless of the `.range()` window requested --
    this is exactly the server behaviour that triggered the original bug."""

    _SERVER_ROW_CAP = 1000

    def __init__(self, rows: list[dict]):
        self._rows = rows
        self._range: tuple[int, int] | None = None
        self._count_mode = False

    def select(self, *_args, count: str | None = None, **_kwargs):
        self._count_mode = count == "exact"
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def range(self, start: int, end: int):
        self._range = (start, end)
        return self

    def execute(self) -> _FakeResult:
        if self._count_mode:
            return _FakeResult(data=[], count=len(self._rows))
        start, end = self._range or (0, len(self._rows) - 1)
        requested = end - start + 1
        capped = min(requested, self._SERVER_ROW_CAP)
        return _FakeResult(data=self._rows[start : start + capped])


class _FakeSupabase:
    def __init__(self, gstr_rows: list[dict], pr_rows: list[dict]):
        self._tables = {"gstr_records": gstr_rows, "pr_records": pr_rows}

    def table(self, name: str) -> _FakeTable:
        return _FakeTable(self._tables[name])


def _run_and_build_outcome_rows():
    gstr_matcher, pr_matcher, gstr_db, pr_db = _build_dataset()
    assert len(gstr_matcher) == N_MATCHED + N_TYPO + N_AMOUNT_MISMATCH + N_MISSED == 6000
    assert len(pr_matcher) == N_MATCHED + N_TYPO + N_AMOUNT_MISMATCH + N_RISK == 6000

    res = run_bidirectional_reconciliation(gstr_matcher, pr_matcher, gstr_period=PERIOD)

    valid_review_required = _to_valid_review_required(list(res["review_required"]))

    payload = build_stored_results_payload(
        matched=res["matched"],
        missed_itc=res["missed_itc"],
        wrongful_itc_risk=res["wrongful_itc_risk"],
        rule37=[],
        section_175_warnings=[],
        credit_note_adjustment={},
        decision_payload={},
        matching_version="test",
        rules_version="test",
        decision_version="test",
        duplicates=valid_review_required,
        review_required_typo=[],
    )

    fake_sb = _FakeSupabase(gstr_db, pr_db)
    rows, cat_counts, _stats = ro.build_outcome_rows(fake_sb, RUN_ID, payload)
    return res, rows, cat_counts


def test_dataset_exceeds_server_page_cap_on_both_sides():
    _gstr_matcher, _pr_matcher, gstr_db, pr_db = _build_dataset()
    assert len(gstr_db) > 1000, "dataset must exceed the 1,000-row server cap to exercise the bug"
    assert len(pr_db) > 1000, "dataset must exceed the 1,000-row server cap to exercise the bug"


def test_loader_maps_contain_every_record_not_just_first_page():
    """Directly proves _load_gstr_map / _load_pr_map no longer truncate to the
    server's first ~1,000-row page."""
    _gstr_matcher, _pr_matcher, gstr_db, pr_db = _build_dataset()
    fake_sb = _FakeSupabase(gstr_db, pr_db)
    gstr_m = ro._load_gstr_map(fake_sb, RUN_ID)
    pr_m = ro._load_pr_map(fake_sb, RUN_ID)
    assert len(gstr_m) == len(gstr_db) == 6000, (
        f"_load_gstr_map only loaded {len(gstr_m)}/{len(gstr_db)} rows -- "
        "pagination is silently truncating past the server's row cap"
    )
    assert len(pr_m) == len(pr_db) == 6000, (
        f"_load_pr_map only loaded {len(pr_m)}/{len(pr_db)} rows -- "
        "pagination is silently truncating past the server's row cap"
    )


def test_category_counts_match_engine_output():
    """Category counts from build_outcome_rows must match the engine's own
    result lengths exactly -- i.e. the pagination fix changes *display data*
    only, never how many rows land in each category. (Exact ground-truth
    ratios like 4200/1350/450/450 are the matcher's own tolerance calibration,
    already covered by tests/test_benchmark_6k.py -- not re-asserted here.)"""
    res, _rows, cat_counts = _run_and_build_outcome_rows()
    assert cat_counts.get("matched") == len(res["matched"])
    assert cat_counts.get("review_required") == len(res["review_required"])
    assert cat_counts.get("missed_itc") == len(res["missed_itc"])
    assert cat_counts.get("wrongful_risk") == len(res["wrongful_itc_risk"])
    # Still confirm we're comfortably testing a large, multi-category dataset.
    assert cat_counts.get("matched", 0) > 1000
    assert (
        cat_counts.get("missed_itc", 0) + cat_counts.get("wrongful_risk", 0)
        > 0
    )


def test_no_row_in_any_category_has_blank_display_fields():
    """The core regression assertion: not just that counts are right, but that
    EVERY SINGLE ROW in every category has real, non-blank supplier_gstin,
    invoice_number, invoice_date, and amount -- zero tolerance for blanks."""
    _res, rows, _cat_counts = _run_and_build_outcome_rows()

    checked_categories = ("matched", "missed_itc", "wrongful_risk", "review_required")
    rows_by_category = {cat: [r for r in rows if r.category == cat] for cat in checked_categories}

    # Sanity: we actually have rows to check in every category.
    for cat in checked_categories:
        assert rows_by_category[cat], f"expected rows in category={cat!r} but found none"

    blank_by_category: dict[str, list[str]] = {cat: [] for cat in checked_categories}
    for cat in checked_categories:
        for r in rows_by_category[cat]:
            is_blank = (
                not (r.supplier_gstin or "").strip()
                or not (r.invoice_number or "").strip()
                or r.invoice_date is None
                or r.amount is None
            )
            if is_blank:
                blank_by_category[cat].append(r.id)

    failures = {cat: ids for cat, ids in blank_by_category.items() if ids}
    assert not failures, (
        "Found rows with blank supplier_gstin/invoice_number/invoice_date/amount "
        f"(pagination truncation regression): "
        f"{ {cat: f'{len(ids)}/{len(rows_by_category[cat])} blank, e.g. {ids[:5]}' for cat, ids in failures.items()} }"
    )
