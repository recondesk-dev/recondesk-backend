"""Background reconciliation: batched I/O, single-shot persistence."""

from __future__ import annotations

import asyncio
import calendar
import json
import logging
import os
import time
import traceback
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from supabase import Client

from app.constants import RunStatus
from app.decisions.layer import populate_decisions
from app.services.matcher import match_gstr_to_pr
from app.services import reconciliation_record_adapter as rec_adapt
from app.services.blocked_credit_checker import check_blocked_credits
from app.services.credit_note_handler import classify_document, net_itc_after_credit_notes
from app.services.reconciliation import (
    ReconState,
    _build_pr_index_by_period,
    build_gstr_by_invoice,
    build_pr_by_invoice,
    build_wrongful_itc_risk,
    notify_reconciliation_run_completed_email_maybe,
    process_gstr_records_chunk,
)
from app.services.reconciliation_payload_store import (
    build_run_summary_metrics,
    build_stored_results_payload,
    save_reconciliation_results,
)
from uuid import UUID

from app.services.carry_forward import update_invoice_tracking
from app.services.rule37_tracker import (
    build_payment_records_from_pr,
    check_rule_37_compliance,
)
from app.worker.celery_app import celery_app
from app.worker.tasks import _json_safe, _supabase, _update_run

_log = logging.getLogger(__name__)

BATCH = 2_000
CHUNK_SIZE = 500
# Supabase/PostgREST caps each ``.range()`` response (~1000 rows). Never request
# more than CHUNK_SIZE in one query or pagination stops early and drops records.
DB_PAGE_SIZE = CHUNK_SIZE
RULES_VERSION = "1.0.0"
DECISION_VERSION = "1.0.0"
MATCHING_VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_period(period: str) -> tuple[int, int]:
    y, m = (int(x) for x in period.strip().split("-", 1))
    return (y, m)


def gstr_period_start_and_end(period: str) -> tuple[date, date]:
    y, m = _parse_period(period)
    last = calendar.monthrange(y, m)[1]
    return (date(y, m, 1), date(y, m, last))


def previous_n_calendar_months(period: str, n: int) -> list[str]:
    """``period`` = YYYY-MM. Returns *n* prior month strings (not including *period*)."""
    y, m = _parse_period(period)
    out: list[str] = []
    for _ in range(n):
        if m == 1:
            m = 12
            y -= 1
        else:
            m -= 1
        out.append(f"{y:04d}-{m:02d}")
    return out


def _count_rows(client: Client, table: str, run_id: str) -> int:
    r = (
        client.table(table)
        .select("id", count="exact")
        .eq("run_id", run_id)
        .limit(0)
        .execute()
    )
    return int(r.count) if r.count is not None else 0


def _load_pr_for_historical_periods_paged(
    client: Client,
    client_gstin_id: str,
    run_id: str,
    months: list[str],
) -> dict[date, list[dict]]:
    """Batched read of *matcher* PR rows for prior *months* (other runs, same client)."""
    if not months:
        return {}
    by_period: dict[date, list[dict]] = defaultdict(list)
    for mo in months:
        offset = 0
        while True:
            r = (
                client.table("pr_records")
                .select("id, record_data, period, run_id")
                .eq("client_gstin_id", client_gstin_id)
                .eq("period", mo)
                .neq("run_id", run_id)
                .order("id")
                .range(offset, offset + DB_PAGE_SIZE - 1)
                .execute()
            )
            rows = r.data or []
            if not rows:
                break
            pkey = _parse_period(mo)
            pdate = date(pkey[0], pkey[1], 1)
            for row in rows:
                by_period[pdate].append(rec_adapt.pr_db_row_to_matcher_row(row))
            offset += len(rows)
            if len(rows) < DB_PAGE_SIZE:
                break
    return {k: v for k, v in by_period.items()}


def _load_pr_matcher_and_raw(
    client: Client, run_id: str
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Matcher rows for the engine plus *id* → *record_data* for post-match upserts."""
    out: list[dict[str, Any]] = []
    raw_by_id: dict[str, dict[str, Any]] = {}
    offset = 0
    while True:
        r = (
            client.table("pr_records")
            .select("id, record_data")
            .eq("run_id", run_id)
            .order("id")
            .range(offset, offset + DB_PAGE_SIZE - 1)
            .execute()
        )
        rows = r.data or []
        if not rows:
            break
        for row in rows:
            rid = str(row.get("id", ""))
            rd = row.get("record_data")
            if isinstance(rd, dict):
                raw_by_id[rid] = rd
            out.append(rec_adapt.pr_db_row_to_matcher_row(row))
        offset += len(rows)
        if len(rows) < DB_PAGE_SIZE:
            break
    return (out, raw_by_id)


def _pr_record_data_missing_invoice_number(record_data: object) -> bool:
    """True when ``record_data`` lacks both invoice number fields."""
    if not isinstance(record_data, dict):
        return True
    return not (
        record_data.get("invoice_number")
        or record_data.get("invoice_number_normalized")
    )


def _load_pr_matcher_and_raw_page(
    client: Client, run_id: str, offset: int, limit: int
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], set[str], int]:
    """Load one page of PR matcher rows + raw ``record_data`` for chunked processing.

    Returns ``(matcher_rows, raw_by_id, skipped_ids, db_rows_fetched)``. Pagination
    callers must advance *offset* by ``db_rows_fetched``, not ``len(matcher_rows)``,
    so invoice-less rows do not cause duplicate/missing pages.
    """
    out: list[dict[str, Any]] = []
    raw_by_id: dict[str, dict[str, Any]] = {}
    skipped_ids: set[str] = set()
    r = (
        client.table("pr_records")
        .select("id, record_data")
        .eq("run_id", run_id)
        .order("id")
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = r.data or []
    for row in rows:
        rid = str(row.get("id", ""))
        rd = row.get("record_data")
        if _pr_record_data_missing_invoice_number(rd):
            skipped_ids.add(rid)
            _log.warning(
                "skip pr matcher load: record_data missing invoice_number for pr id=%s",
                rid,
            )
            if isinstance(rd, dict):
                raw_by_id[rid] = rd
            continue
        if isinstance(rd, dict):
            raw_by_id[rid] = rd
        out.append(rec_adapt.pr_db_row_to_matcher_row(row))
    return (out, raw_by_id, skipped_ids, len(rows))


def _build_pr_index_for_matching(
    client: Client, run_id: str
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    """Load every PR matcher row for this run (paginate until DB returns no rows)."""
    pr_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    offset = 0
    loaded = 0
    while True:
        pr_chunk, _, _skipped, fetched = _load_pr_matcher_and_raw_page(
            client, run_id, offset, CHUNK_SIZE
        )
        if fetched == 0:
            break
        for pr_rec in pr_chunk:
            pr_index[str(pr_rec.get("supplier_gstin") or "")].append(pr_rec)
            loaded += 1
        offset += fetched
        if fetched < CHUNK_SIZE:
            break
    return (dict(pr_index), loaded)


def _write_pr_match_status_chunk(
    client: Client,
    *,
    run_id: str,
    pr_chunk: list[dict[str, Any]],
    pr_raw_by_id: dict[str, dict[str, Any]],
    matched_pr_ids: set[str],
    gstr_by_gstin: dict[str, list[dict[str, Any]]],
    gstr_by_id: dict[str, dict[str, Any]],
    matched: list[dict[str, Any]],
    skipped_pr_ids: set[str] | None = None,
    chunk_idx: int | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    """Build and upsert match fields for one PR chunk; returns tracking rows + counts."""
    skipped_pr_ids = skipped_pr_ids or set()
    engine_meta_by_pr_id = _matched_engine_meta_by_pr_id(
        matched,
        gstr_by_id,
        {str(p["id"]): p for p in pr_chunk},
    )
    pr_match_status_rows: list[dict[str, Any]] = []
    pr_rows_for_tracking: list[dict[str, Any]] = []
    chunk_matched = 0
    for pr_rec in pr_chunk:
        pid = str(pr_rec["id"])
        base_rd = pr_raw_by_id.get(pid)
        match_st = _pr_match_status_for_record(
            pr_rec, matched_pr_ids, gstr_by_gstin
        )
        if match_st == "matched":
            chunk_matched += 1
        engine_meta = engine_meta_by_pr_id.get(pid)
        rd = base_rd if isinstance(base_rd, dict) else {}
        pr_rows_for_tracking.append(
            {
                "invoice_number": rd.get("invoice_number")
                or rd.get("invoice_number_normalized")
                or pr_rec.get("invoice_number_normalized"),
                "supplier_gstin": rd.get("gstin") or pr_rec.get("supplier_gstin"),
                "taxable_amount": rd.get("taxable_amount_paise")
                or pr_rec.get("taxable_amount_paise"),
                "match_status": match_st,
            }
        )
        try:
            pr_match_status_rows.append(
                _build_pr_post_match_upsert_row(
                    pid, run_id, base_rd, match_st, engine_meta
                )
            )
        except (TypeError, ValueError):
            _log.warning(
                "skip pr record_data match_status: invalid pr id=%s", pid
            )
            continue
    for pid in skipped_pr_ids:
        base_rd = pr_raw_by_id.get(pid)
        rd = base_rd if isinstance(base_rd, dict) else {}
        pr_rows_for_tracking.append(
            {
                "invoice_number": rd.get("invoice_number")
                or rd.get("invoice_number_normalized"),
                "supplier_gstin": rd.get("gstin") or rd.get("supplier_gstin"),
                "taxable_amount": rd.get("taxable_amount_paise"),
                "match_status": "unmatched",
            }
        )
        try:
            pr_match_status_rows.append(
                _build_pr_post_match_upsert_row(
                    pid, run_id, base_rd, "unmatched", None
                )
            )
        except (TypeError, ValueError):
            _log.warning(
                "skip pr record_data match_status: invalid pr id=%s", pid
            )
            continue
    if pr_match_status_rows:
        for i in range(0, len(pr_match_status_rows), BATCH):
            chunk = pr_match_status_rows[i : i + BATCH]
            try:
                client.table("pr_records").upsert(
                    chunk,
                    on_conflict="id",
                    returning="minimal",
                ).execute()
            except Exception:
                _log.exception("pr_records match_status bulk upsert failed")
    if chunk_idx is not None:
        _log.info(
            "wrote chunk %d match_status for %d rows",
            chunk_idx,
            len(pr_match_status_rows),
        )
    return (pr_rows_for_tracking, chunk_matched, len(pr_match_status_rows))


def _pr_match_status_for_record(
    pr_rec: dict[str, Any],
    matched_pr_ids: set[str],
    gstr_by_gstin: dict[str, list[dict[str, Any]]],
) -> str:
    """Classify PR row for ``record_data.match_status`` (does not alter pairing)."""
    pr_id = str(pr_rec["id"])
    if pr_id in matched_pr_ids:
        return "matched"
    gstin = str(pr_rec.get("supplier_gstin") or "")
    for gstr_rec in gstr_by_gstin.get(gstin, ()):
        if match_gstr_to_pr(gstr_rec, [pr_rec]) is not None:
            return "missing_in_2b"
    return "unmatched"


def _matched_engine_meta_by_pr_id(
    matched: list[dict[str, Any]],
    gstr_by_id: dict[str, dict[str, Any]],
    pr_by_id: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Map PR id → engine metadata (match_level, vendor_similarity_score) for persistence."""
    out: dict[str, dict[str, Any]] = {}
    for m in matched:
        pid = str(m.get("pr_id") or "")
        if not pid:
            continue
        gid = str(m.get("gstr_id") or "")
        ggr = gstr_by_id.get(gid, {})
        pr = pr_by_id.get(pid, {})
        meta: dict[str, Any] = {}
        if ggr and pr:
            mr = match_gstr_to_pr(ggr, [pr])
            if mr is not None:
                meta["match_level"] = mr.level
        vss = m.get("vendor_similarity_score")
        if vss is not None:
            meta["vendor_similarity_score"] = vss
        if meta:
            out[pid] = meta
    return out


def _build_pr_post_match_upsert_row(
    pr_id: str,
    run_id: str,
    base_record_data: dict[str, Any] | None,
    match_status: str,
    engine_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build ``pr_records`` upsert payload with JSONB + top-level match fields."""
    merged_rd = dict(base_record_data) if isinstance(base_record_data, dict) else {}
    merged_rd["match_status"] = match_status
    meta = engine_meta or {}
    if "match_level" in meta:
        merged_rd["match_level"] = meta["match_level"]
    if meta.get("vendor_similarity_score") is not None:
        merged_rd["vendor_similarity_score"] = meta["vendor_similarity_score"]

    row: dict[str, Any] = {
        # pr_id is a UUID string — do NOT cast to int
        "id": pr_id,
        "run_id": run_id,
        "record_data": _json_safe(merged_rd),
        "match_status": match_status,
    }
    if "match_level" in meta:
        row["match_level"] = meta["match_level"]
    return row


def _load_gstr_matcher_and_raw(
    client: Client, run_id: str
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Batched read of GSTR lines; returns matcher rows + *id* → *record_data* for compliance."""
    out: list[dict[str, Any]] = []
    raw_by_id: dict[str, dict[str, Any]] = {}
    offset = 0
    while True:
        r = (
            client.table("gstr_records")
            .select("id, record_data")
            .eq("run_id", run_id)
            .order("id")
            .range(offset, offset + DB_PAGE_SIZE - 1)
            .execute()
        )
        rows = r.data or []
        if not rows:
            break
        for row in rows:
            rid = str(row.get("id", ""))
            rd = row.get("record_data")
            if isinstance(rd, dict):
                raw_by_id[rid] = rd
            out.append(rec_adapt.gstr_db_row_to_matcher_row(row))
        offset += len(rows)
        if len(rows) < DB_PAGE_SIZE:
            break
    return (out, raw_by_id)


@celery_app.task(
    name="worker.execute_reconciliation",
    max_retries=0,
    soft_time_limit=600,
    time_limit=660,
)
def execute_reconciliation(run_id: str) -> None:
    _t: dict[str, float] = {"start": time.perf_counter()}

    def _phase(name: str) -> None:
        now = time.perf_counter()
        prev_name = list(_t.keys())[-1]
        elapsed = now - _t[prev_name]
        total = now - _t["start"]
        _log.info("[PERF] %s=%.3fs total=%.3fs", name, elapsed, total)
        _t[name] = now

    if not os.environ.get("REDIS_URL"):
        _log.debug("REDIS_URL not set; using fallback from Settings")

    client = _supabase()
    try:
        run_res = (
            client.table("reconciliation_run")
            .select(
                "id, status, client_gstin_id, period, gstr_records_imported, pr_records_imported, created_at"
            )
            .eq("id", run_id)
            .limit(1)
            .execute()
        )
        if not run_res.data:
            _log.error("execute_reconciliation: run %s not found", run_id)
            return
        run = run_res.data[0]
        st = (run.get("status") or "").strip().upper()
        if st in ("COMPLETED", "FAILED", "FINAL"):
            _log.warning("execute_reconciliation: run %s already terminal (%s)", run_id, st)
            return
        if st != "MATCHING":
            _log.warning("execute_reconciliation: run %s not in MATCHING (got %s)", run_id, st)
            return

        claimed = (
            client.table("reconciliation_run")
            .update(
                {
                    "status": "PROCESSING",
                    "status_message": "Initializing",
                    "progress_percent": 2,
                    "updated_at": _now_iso(),
                }
            )
            .eq("id", run_id)
            .eq("status", "MATCHING")
            .execute()
        )
        if not claimed.data:
            _log.warning(
                "execute_reconciliation: lost claim for %s (duplicate worker?)", run_id
            )
            return

        client_gstin_id = str(run.get("client_gstin_id", "")).strip()
        period = str(run.get("period", "")).strip()
        gstr_start, gstr_end = gstr_period_start_and_end(period)
        _update_run(
            client,
            run_id,
            {
                "gstr_period_end": gstr_end.isoformat(),
                "updated_at": _now_iso(),
            },
        )

        n_gstr = int(run.get("gstr_records_imported") or 0)
        n_pr = int(run.get("pr_records_imported") or 0)

        months_back = previous_n_calendar_months(period, 6)
        historical = _load_pr_for_historical_periods_paged(
            client, client_gstin_id, run_id, months_back
        )

        gstr_p = gstr_start
        pr_index_by_period = _build_pr_index_by_period(dict(historical))

        gstr_matcher, gstr_raw_by_id = _load_gstr_matcher_and_raw(client, run_id)
        _log.info(
            "[PERF] gstr_count=%d pr_count=%d",
            len(gstr_matcher),
            n_pr,
        )
        _update_run(
            client,
            run_id,
            {
                "progress_percent": 10,
                "status_message": "Data loaded",
                "updated_at": _now_iso(),
            },
        )
        _phase("file_load")
        for rec in gstr_matcher:
            if not rec.get("invoice_date"):
                rec["invoice_date"] = gstr_end.isoformat()
        _phase("normalization")

        _update_run(
            client,
            run_id,
            {
                "progress_percent": 20,
                "status_message": "Preprocessing complete",
                "updated_at": _now_iso(),
            },
        )

        state = ReconState()
        gstr_by_gstin: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for ggr in gstr_matcher:
            gstr_by_gstin[str(ggr.get("supplier_gstin") or "")].append(ggr)
        gstr_by_invoice = build_gstr_by_invoice(gstr_matcher)
        gstr_by_id: dict[str, dict] = {str(x.get("id")): x for x in gstr_matcher}

        pr_index_current, pr_index_loaded = _build_pr_index_for_matching(
            client, run_id
        )
        if n_pr and pr_index_loaded < n_pr:
            _log.warning(
                "PR index load shortfall: matcher_rows=%d pr_records_imported=%d run_id=%s",
                pr_index_loaded,
                n_pr,
                run_id,
            )
        elif n_pr and pr_index_loaded > n_pr:
            _log.warning(
                "PR index load exceeds metadata: matcher_rows=%d pr_records_imported=%d run_id=%s",
                pr_index_loaded,
                n_pr,
                run_id,
            )
        if len(gstr_matcher) != n_gstr:
            _log.warning(
                "GSTR load count mismatch: loaded=%d gstr_records_imported=%d run_id=%s",
                len(gstr_matcher),
                n_gstr,
                run_id,
            )
        _log.info(
            "[PERF] pr_index_loaded=%d pr_records_imported=%d gstr_loaded=%d",
            pr_index_loaded,
            n_pr,
            len(gstr_matcher),
        )
        pr_by_invoice = build_pr_by_invoice(pr_index_current)
        pr_total_chunks = max(1, (pr_index_loaded + CHUNK_SIZE - 1) // CHUNK_SIZE)

        n_gstr_chunks = max(1, (len(gstr_matcher) + BATCH - 1) // BATCH)
        _update_run(
            client,
            run_id,
            {
                "progress_percent": 25,
                "status_message": "Matching started",
                "updated_at": _now_iso(),
            },
        )
        mid_done = (n_gstr_chunks + 1) // 2
        for i in range(0, len(gstr_matcher), BATCH):
            gstr_batch = gstr_matcher[i : i + BATCH]
            process_gstr_records_chunk(
                gstr_batch,
                gstr_p,
                pr_index_current,
                pr_index_by_period,
                state,
                gstr_by_invoice=gstr_by_invoice,
                pr_by_invoice=pr_by_invoice,
            )
            done = i // BATCH + 1
            if done == n_gstr_chunks:
                pct = 50
            elif n_gstr_chunks > 1 and done == mid_done and done < n_gstr_chunks:
                pct = 38
            else:
                pct = min(49, 25 + int(25 * done / n_gstr_chunks))
            _update_run(
                client,
                run_id,
                {
                    "progress_percent": pct,
                    "status_message": f"Matching ({min(done, n_gstr_chunks)}/{n_gstr_chunks} batches)",
                    "updated_at": _now_iso(),
                },
            )

        pr_rows_for_tracking: list[dict[str, Any]] = []
        pr_write_offset = 0
        chunk_idx = 0
        while True:
            chunk_started = time.perf_counter()
            pr_chunk, pr_raw_chunk, skipped, fetched = _load_pr_matcher_and_raw_page(
                client, run_id, pr_write_offset, CHUNK_SIZE
            )
            if fetched == 0:
                break

            _log.info(
                "processing chunk %d offset=%d pr_chunk_size=%d fetched=%d",
                chunk_idx,
                pr_write_offset,
                len(pr_chunk),
                fetched,
            )

            tracking_rows, chunk_matched, chunk_written = _write_pr_match_status_chunk(
                client,
                run_id=run_id,
                pr_chunk=pr_chunk,
                pr_raw_by_id=pr_raw_chunk,
                matched_pr_ids=state.matched_pr_ids,
                gstr_by_gstin=gstr_by_gstin,
                gstr_by_id=gstr_by_id,
                matched=state.matched,
                skipped_pr_ids=skipped,
                chunk_idx=chunk_idx,
            )
            pr_rows_for_tracking.extend(tracking_rows)

            chunk_num = chunk_idx + 1
            pct = int(100 * chunk_num / pr_total_chunks)
            elapsed = time.perf_counter() - chunk_started
            _log.info(
                "chunk %d/%d completed in %.2fs matched=%d written=%d",
                chunk_num,
                pr_total_chunks,
                elapsed,
                chunk_matched,
                chunk_written,
            )
            _update_run(
                client,
                run_id,
                {
                    "progress_percent": min(70, 50 + int(20 * chunk_num / pr_total_chunks)),
                    "status_message": f"PR chunk {chunk_num}/{pr_total_chunks} complete ({pct}%)",
                    "updated_at": _now_iso(),
                },
            )
            pr_write_offset += fetched
            chunk_idx += 1
            if fetched < CHUNK_SIZE:
                break

        _phase("matching")
        pr_current, pr_raw_by_id = _load_pr_matcher_and_raw(client, run_id)
        wrongful_itc = build_wrongful_itc_risk(pr_current, state.matched_pr_ids)
        _log.info(
            "classification summary run=%s: matched=%d missed_itc(2B-not-in-books)=%d "
            "wrongful_risk(PR-not-in-2B)=%d total_pr_loaded=%d",
            run_id,
            len(state.matched),
            len(state.missed_itc),
            len(wrongful_itc),
            len(pr_current),
        )
        late_itc = sum(
            1
            for m in state.matched
            if m.get("is_late_filing")
        )
        itc_missed = sum(int(x.get("total_tax_paise") or 0) for x in state.missed_itc)
        wrongful_paise = sum(
            int(x.get("total_tax_paise") or 0) for x in wrongful_itc
        )

        pr_by_id: dict[str, dict] = {str(p["id"]): p for p in pr_current}
        gstr_by_id: dict[str, dict] = {str(x.get("id")): x for x in gstr_matcher}
        # Rule 37 only applies to invoices whose ITC was actually claimed, i.e. PR
        # rows matched to GSTR-2B. Unmatched PR rows surface as wrongful-ITC risk,
        # not Rule 37, and must never be flagged here.
        matched_pr_ids = {str(x) for x in state.matched_pr_ids}
        pr_for_rule37 = [
            {
                **p,
                "id": str(p["id"]),
                "invoice_date": p.get("invoice_date")
                or gstr_start.isoformat(),
            }
            for p in pr_current
            if str(p["id"]) in matched_pr_ids
        ]
        payment_records = build_payment_records_from_pr(
            pr_current, pr_raw_by_id
        )
        rule37 = check_rule_37_compliance(
            pr_for_rule37,
            payment_records,
        )
        rule37_itc_paise = sum(
            int(r.get("itc_at_risk_paise") or 0) for r in (rule37 or [])
        )
        # Runs-list "ITC at risk" = missed ITC (GSTR-2B invoices with no PR match).
        itc_at_risk_total = itc_missed

        gstr_invoices_for_blocked: list[dict[str, Any]] = []
        for ggr in gstr_matcher:
            gid = str(ggr.get("id", ""))
            rdg = gstr_raw_by_id.get(gid) or {}
            # Full GSTR-2B record_data (incl. items / nested line HSN) for Section 17(5) checks
            merged: dict[str, Any] = dict(rdg) if isinstance(rdg, dict) else {}
            if ggr.get("invoice_number_normalized") is not None:
                merged["invoice_number"] = ggr.get("invoice_number_normalized")
            if ggr.get("supplier_gstin") is not None:
                merged["supplier_gstin"] = ggr.get("supplier_gstin")
            gstr_invoices_for_blocked.append(merged)
        s175 = check_blocked_credits(gstr_invoices_for_blocked)
        amount_diff_upsert_rows: list[dict[str, Any]] = []
        amount_diff_ts = _now_iso()
        for m in state.matched:
            gid = str(m.get("gstr_id") or "")
            pid = str(m.get("pr_id") or "")
            ggr = gstr_by_id.get(gid, {})
            pr = pr_by_id.get(pid, {})
            try:
                gid_int = int(gid)
            except (TypeError, ValueError):
                _log.warning("skip amount_difference_paise: invalid gstr_id=%s", gid)
                continue
            diff = int(ggr.get("total_tax_paise") or 0) - int(
                pr.get("total_tax_paise") or 0
            )
            amount_diff_upsert_rows.append(
                {
                    "id": gid_int,
                    "amount_difference_paise": diff,
                    "updated_at": amount_diff_ts,
                }
            )
        if amount_diff_upsert_rows:
            try:
                client.table("gstr_records").upsert(
                    amount_diff_upsert_rows,
                    on_conflict="id",
                    returning="minimal",
                ).execute()
            except Exception:
                _log.exception("amount_difference_paise bulk upsert failed")

        try:
            carry_forward_summary = asyncio.run(
                update_invoice_tracking(
                    client_gstin_id=UUID(client_gstin_id),
                    run_id=UUID(run_id),
                    pr_records=pr_rows_for_tracking,
                )
            )
            _log.info("Carry-forward summary: %s", carry_forward_summary)
        except Exception:
            _log.exception("carry_forward failed run_id=%s", run_id)

        credit_rows = [
            {**p, "doc_kind": classify_document(p)}
            for p in pr_current
        ]
        cnotes = [r for r in credit_rows if r.get("doc_kind") == "CREDIT_NOTE"]
        invs = [r for r in credit_rows if r.get("doc_kind") == "INVOICE"]
        cn_net = net_itc_after_credit_notes(
            [
                {
                    "id": r["id"],
                    "total_tax_paise": int(r.get("total_tax_paise") or 0),
                }
                for r in invs
            ],
            [
                {
                    "reference_invoice_id": r.get("reference_invoice_id"),
                    "total_tax_paise": int(r.get("total_tax_paise") or 0),
                }
                for r in cnotes
            ],
        )

        _update_run(
            client,
            run_id,
            {
                "progress_percent": 75,
                "status_message": "Compliance checks complete",
                "updated_at": _now_iso(),
            },
        )

        decision_payload = populate_decisions(
            state.matched,
            rule37=rule37,
            section_175_warnings=s175,
            credit_note_adjustment=cn_net,
        )
        _update_run(
            client,
            run_id,
            {
                "progress_percent": 85,
                "status_message": "Decision layer applied",
                "decision_version": DECISION_VERSION,
                "rules_version": RULES_VERSION,
                "updated_at": _now_iso(),
            },
        )

        total_invoices = n_gstr + n_pr
        late_itc_paise = sum(
            int(
                gstr_by_id.get(str(m.get("gstr_id")), {}).get("total_tax_paise")
                or 0
            )
            for m in state.matched
            if m.get("is_late_filing")
        )
        matched_count = len(state.matched)
        missed_itc_count = len(state.missed_itc)
        wrongful_count = len(wrongful_itc)
        run_summary = build_run_summary_metrics(
            n_gstr=n_gstr,
            n_pr=n_pr,
            matched_count=matched_count,
            missed_itc_count=missed_itc_count,
            wrongful_count=wrongful_count,
            itc_missed=itc_missed,
            wrongful_paise=wrongful_paise,
            rule37_itc_paise=rule37_itc_paise,
            itc_at_risk_total=itc_at_risk_total,
            late_itc_paise=late_itc_paise,
            late_match_count=late_itc,
        )

        payload = _json_safe(
            build_stored_results_payload(
                matched=state.matched,
                missed_itc=state.missed_itc,
                wrongful_itc_risk=wrongful_itc,
                rule37=rule37,
                section_175_warnings=s175,
                credit_note_adjustment=cn_net,
                decision_payload=decision_payload,
                matching_version=MATCHING_VERSION,
                rules_version=RULES_VERSION,
                decision_version=DECISION_VERSION,
            )
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
        save_reconciliation_results(
            client,
            run_id,
            payload,
            created_at=_now_iso(),
        )

        _update_run(
            client,
            run_id,
            {
                "status": RunStatus.COMPLETED,
                "progress_percent": 100.0,
                "completed_at": _now_iso(),
                "status_message": "Completed",
                "run_summary": run_summary,
                "matching_version": MATCHING_VERSION,
                "rules_version": RULES_VERSION,
                "decision_version": DECISION_VERSION,
                "updated_at": _now_iso(),
            },
        )
        match_rate = round(len(state.matched) / n_gstr * 100, 2) if n_gstr else 0.0

        to_email = ""
        full_nm = ""
        created_by = ""  # reconciliation_run has no created_by column; notifications disabled

        client_display_name = "Client"
        cg_row = (
            client.table("client_gstins")
            .select("trade_name, legal_name, gstin")
            .eq("id", client_gstin_id)
            .limit(1)
            .execute()
        )
        if cg_row.data:
            r0 = cg_row.data[0]
            client_display_name = (
                str(r0.get("trade_name") or "").strip()
                or str(r0.get("legal_name") or "").strip()
                or str(r0.get("gstin") or "").strip()
                or "Client"
            )

        notify_reconciliation_run_completed_email_maybe(
            client,
            run_id=run_id,
            actor_user_id=created_by or None,
            to_email=to_email,
            full_name=full_nm,
            client_name=client_display_name,
            period=period,
            matched_count=len(state.matched),
            missed_itc_amount_paise=itc_missed,
            wrongful_risk_amount_paise=wrongful_paise,
            match_rate_percent=match_rate,
        )

        from app.utils.audit import actor_user_for_run, log_audit_sync

        actor = actor_user_for_run(client, run_id) or {"id": None, "full_name": "System"}
        # Anchor firm scoping to the client's owner when the actor can't supply it
        # (e.g. legacy runs with no created_by/finalized_by).
        if not actor.get("firm_id"):
            try:
                from app.services.firm_access import get_firm_owner_for_client

                actor["firm_id"] = get_firm_owner_for_client(client, client_gstin_id)
            except Exception:
                _log.warning("RECON_COMPLETED firm_id unresolved run_id=%s", run_id)
        entity_label = (
            f"{client_display_name} ({period})" if period else client_display_name
        )
        log_audit_sync(
            client,
            actor,
            "RECON_COMPLETED",
            "reconciliation",
            run_id,
            entity_label,
            {
                "matched_count": len(state.matched),
                "match_rate_percent": match_rate,
            },
        )

        _phase("db_writes")
    except Exception as exc:
        _log.exception("execute_reconciliation failed run_id=%s", run_id)
        _log.error("%s", traceback.format_exc())
        try:
            client.table("reconciliation_results").delete().eq("run_id", run_id).execute()
        except Exception:
            _log.exception("cleanup reconciliation_results failed")
        _update_run(
            client,
            run_id,
            {
                "status": "FAILED",
                "status_message": str(exc)[:2000],
                "updated_at": _now_iso(),
            },
        )
        raise
