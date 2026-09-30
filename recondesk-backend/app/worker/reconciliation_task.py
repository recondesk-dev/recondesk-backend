"""Background reconciliation: batched I/O, single-shot persistence."""

from __future__ import annotations

import asyncio
import calendar
import json
import logging
import os
import subprocess
import time
import traceback
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from supabase import Client

from app.constants import RunStatus
from app.decisions.layer import populate_decisions, populate_review_decisions
from app.services.matcher import match_gstr_to_pr
from app.services import reconciliation_record_adapter as rec_adapt
from app.services.blocked_credit_checker import check_blocked_credits
from app.services.credit_note_handler import classify_document, net_itc_after_credit_notes
from app.services.amendment_handler import build_effective_gstr_records
from app.services.reconciliation import (
    ReconState,
    _build_pr_index_by_period,
    build_gstr_by_invoice,
    build_pr_by_invoice,
    build_pr_candidate_indices,
    build_wrongful_itc_risk,
    notify_reconciliation_run_completed_email_maybe,
    prepass_gstr2b_duplicates,
    prepass_duplicate_ambiguity,
    process_gstr_records_chunk,
    execute_credit_note_reconciliation,
    execute_phase2_and_3,
    quarantine_pr_notes,
    is_pr_note_quarantine,
    _finalize_reconciliation_result,
)
from app.services.reconciliation_payload_store import (
    build_run_summary_metrics,
    build_stored_results_payload,
    save_reconciliation_results,
)
from uuid import UUID

from app.services.carry_forward import update_invoice_tracking
from app.services.ims_overlay import (
    apply_ims_status_to_matcher_rows,
    apply_ims_status_to_record_data,
    try_fetch_ims_status_map_for_client,
)
from app.services.rule37_tracker import (
    build_payment_records_from_pr,
    check_rule_37_compliance,
    _is_itc_claimed,
    PENDING_VERIFICATION,
)
from app.services.late_filing_tracker import check_late_filing
from app.worker.celery_app import celery_app
from app.worker.tasks import _json_safe, _supabase, _update_run

_log = logging.getLogger(__name__)

BATCH = 500
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
    """True when ``record_data`` lacks both invoice number fields.

    Quarantined credit/debit note rows are not treated as missing-invoice skips —
    they are routed to the Notes bucket instead.
    """
    if not isinstance(record_data, dict):
        return True
    if record_data.get("pr_note_quarantine") or record_data.get("note_number"):
        doc = str(
            record_data.get("document_type")
            or record_data.get("invoice_type")
            or ""
        ).strip().upper()
        if record_data.get("pr_note_quarantine") or doc in {
            "CREDIT_NOTE",
            "DEBIT_NOTE",
        }:
            return False
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
            if isinstance(rd, dict):
                raw_by_id[rid] = rd
            continue
        if isinstance(rd, dict):
            raw_by_id[rid] = rd
        out.append(rec_adapt.pr_db_row_to_matcher_row(row))
    return (out, raw_by_id, skipped_ids, len(rows))


def _build_pr_index_for_matching(
    client: Client, run_id: str
) -> tuple[dict[str, list[dict[str, Any]]], int, int, list[dict[str, Any]]]:
    """Load every PR matcher row for this run (paginate until DB returns no rows).

    Returns
    ``(pr_index, loaded_invoice_matcher_rows, skipped_missing_invoice_count, note_rows)``.
    """
    pr_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    note_rows: list[dict[str, Any]] = []
    offset = 0
    loaded = 0
    skipped_total = 0
    while True:
        pr_chunk, _, skipped, fetched = _load_pr_matcher_and_raw_page(
            client, run_id, offset, CHUNK_SIZE
        )
        if fetched == 0:
            break
        skipped_total += len(skipped)
        for pr_rec in pr_chunk:
            if is_pr_note_quarantine(pr_rec):
                note_rows.append(pr_rec)
            pr_index[str(pr_rec.get("supplier_gstin") or "")].append(pr_rec)
            loaded += 1
        offset += fetched
        if fetched < CHUNK_SIZE:
            break
    if skipped_total:
        _log.warning(
            "skip pr matcher load: %d PR row(s) missing invoice_number (run_id=%s)",
            skipped_total,
            run_id,
        )
    if note_rows:
        _log.info(
            "PR note quarantine candidates: %d row(s) (run_id=%s)",
            len(note_rows),
            run_id,
        )
    return (dict(pr_index), loaded, skipped_total, note_rows)


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
                "match_status": "skipped",
            }
        )
        try:
            pr_match_status_rows.append(
                _build_pr_post_match_upsert_row(
                    pid, run_id, base_rd, "skipped", None
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
    """Classify PR row for ``record_data.match_status`` (does not alter pairing).

    Three distinct outcomes, each backed only by data we actually have:
      * ``matched``       — this PR row was paired with a GSTR-2B record.
      * ``missing_in_2b``  — the supplier GSTIN DOES appear elsewhere in this
        run's GSTR-2B data, but this specific invoice was not found there.
        This is the only case where "this invoice is absent from 2B" is a
        data-backed statement (Bug 3: never conflate "not in PR's matched set"
        with a claim about the supplier's actual GSTR-1 filing status).
      * ``unmatched``      — the supplier GSTIN does not appear in GSTR-2B at
        all for this run, so we cannot even confirm the supplier filed
        anything; a weaker, more honest classification than ``missing_in_2b``.
    """
    pr_id = str(pr_rec["id"])
    if pr_id in matched_pr_ids:
        return "matched"
    gstin = str(pr_rec.get("supplier_gstin") or "").strip()
    if gstin and gstr_by_gstin.get(gstin):
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
    name="worker.run_wizard_job",
    max_retries=0,
    soft_time_limit=900,
    time_limit=960,
)
def run_wizard_job(run_id: str) -> None:
    """
    Full pipeline for the import-wizard flow, executed entirely inside the
    Celery worker — NOT in the web-process thread.  Sequence:

      1. Load the reconciliation_import_runs row.
      2. Import GSTR-2B  (run_import_job).
      3. Import Purchase Register  (run_import_job).
      4. Set reconciliation_run.status → MATCHING.
      5. Run the reconciliation engine  (execute_reconciliation).
      6. Mark wizard run as complete / error.

    Using .apply() (eager execution *inside the worker process*) rather than
    .delay() means the sub-tasks run synchronously within this worker task,
    which is exactly what we want — no extra round-trips through Redis.
    """
    from app.worker.tasks import run_import_job

    _log.info("run_wizard_job: starting run_id=%s", run_id)
    sb = _supabase()

    # ── progress helper ───────────────────────────────────────────────────────
    def _set_wizard_pct(pct: int, msg: str, final_status: str = None) -> None:
        now = _now_iso()
        try:
            wiz_update = {"progress_pct": int(pct), "status_message": msg, "updated_at": now}
            if final_status:
                wiz_update["status"] = final_status
            sb.table("reconciliation_import_runs").update(wiz_update).eq("id", run_id).execute()
        except Exception as exc:
            _log.warning(
                "run_wizard_job: failed to update reconciliation_import_runs progress for run_id=%s: %s",
                run_id,
                exc,
            )
            
        try:
            rec_update = {"progress_percent": pct, "updated_at": now}
            if final_status:
                rec_update["status"] = "COMPLETED" if final_status == "complete" else final_status.upper()
            if msg:
                rec_update["status_message"] = msg
            sb.table("reconciliation_run").update(rec_update).eq("id", run_id).execute()
        except Exception as exc:
            _log.warning(
                "run_wizard_job: failed to update reconciliation_run progress for run_id=%s: %s",
                run_id,
                exc,
            )

    # ── failure helper ────────────────────────────────────────────────────────
    def _fail(detail: str) -> None:
        now = _now_iso()
        msg = (detail or "Processing failed")[:2000]
        # reconciliation_import_runs has error_detail; reconciliation_run does not — write
        # the real exception into status_message (same as execute_reconciliation).
        try:
            sb.table("reconciliation_import_runs").update(
                {
                    "status": "error",
                    "error_detail": msg,
                    "status_message": "Processing failed",
                    "updated_at": now,
                }
            ).eq("id", run_id).execute()
        except Exception as exc:
            _log.warning(
                "run_wizard_job: failed to mark reconciliation_import_runs error run_id=%s: %s",
                run_id,
                exc,
            )
        try:
            sb.table("reconciliation_run").update(
                {
                    "status": "FAILED",
                    "status_message": msg,
                    "updated_at": now,
                }
            ).eq("id", run_id).execute()
        except Exception as exc:
            _log.warning(
                "run_wizard_job: failed to mark reconciliation_run FAILED run_id=%s: %s",
                run_id,
                exc,
            )

    # ── fetch wizard run ──────────────────────────────────────────────────────
    try:
        row_res = sb.table("reconciliation_import_runs").select("*").eq("id", run_id).limit(1).execute()
        if not row_res.data:
            _log.error("run_wizard_job: wizard run %s not found", run_id)
            return
        row = row_res.data[0]
    except Exception as exc:
        _log.exception("run_wizard_job: failed to fetch wizard run %s", run_id)
        _fail(str(exc))
        return

    client_id   = str(row.get("client_id") or "").strip()
    period_raw  = str(row.get("period") or "").strip()
    gstr2b_key  = str(row.get("gstr2b_r2_key") or "").strip()
    pr_key      = str(row.get("pr_r2_key") or "").strip()

    if not all([client_id, period_raw, gstr2b_key, pr_key]):
        err = (
            f"Wizard run missing required fields: client_id={client_id!r} "
            f"period={period_raw!r} gstr2b_r2_key={gstr2b_key!r} "
            f"pr_r2_key={pr_key!r}"
        )
        _log.error("run_wizard_job: %s", err)
        _fail(err)
        return

    # reconciliation_task._parse_period expects "YYYY-MM"; wizard stores "YYYY-MM-DD"
    period = period_raw[:7]
    now = _now_iso()

    try:
        # Ensure the reconciliation_run row exists before run_import_job writes to it.
        existing = (
            sb.table("reconciliation_run")
            .select("id, status")
            .eq("id", run_id)
            .limit(1)
            .execute()
        )
        if not existing.data:
            sb.table("reconciliation_run").insert(
                {
                    "id": run_id,
                    "client_gstin_id": client_id,
                    "period": period,
                    "status": "uploading",
                    "progress_percent": 0,
                    "created_at": now,
                    "updated_at": now,
                }
            ).execute()

        _set_wizard_pct(10, "Loading files…")

        # ── 1. GSTR-2B ───────────────────────────────────────────────────────
        _log.info("run_wizard_job: importing GSTR-2B for run %s", run_id)
        run_import_job.apply(args=[run_id, "gstr2b", gstr2b_key])
        _set_wizard_pct(25, "Parsed GSTR-2B")

        # ── 2. Purchase Register ─────────────────────────────────────────────
        _log.info("run_wizard_job: importing PR for run %s", run_id)
        run_import_job.apply(args=[run_id, "purchase_register", pr_key])
        _set_wizard_pct(40, "Parsed Purchase Register")

        # ── 3. Set MATCHING ──────────────────────────────────────────────────
        _log.info("run_wizard_job: setting MATCHING for run %s", run_id)
        _set_wizard_pct(40, "Matching invoices…", final_status="processing") # Keep wizard status processing
        sb.table("reconciliation_run").update(
            {"status": "MATCHING", "updated_at": _now_iso()}
        ).eq("id", run_id).execute()

        # ── 4. Reconciliation engine ─────────────────────────────────────────
        _log.info("run_wizard_job: running reconciliation engine for run %s", run_id)
        execute_reconciliation.apply(args=[run_id])
        _set_wizard_pct(80, "Running engine")

        # ── 5. Mark wizard run complete ──────────────────────────────────────
        _log.info("run_wizard_job: finalising wizard run %s", run_id)
        _set_wizard_pct(95, "Saving results…")
        
        # After completion: 100
        _set_wizard_pct(100, "Complete", final_status="complete")

        _log.info("run_wizard_job: completed successfully run_id=%s", run_id)

    except Exception as exc:
        _log.exception("run_wizard_job: failed for run_id=%s", run_id)
        _fail(str(exc))
        raise



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

        try:
            git_hash = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
            ).decode("utf-8").strip()
        except Exception:
            git_hash = os.environ.get("RAILWAY_GIT_COMMIT_SHA", "unknown")[:7]

        _log.info("execute_reconciliation: claiming run %s on worker version=%s", run_id, git_hash)

        claimed = (
            client.table("reconciliation_run")
            .update(
                {
                    "status": "PROCESSING",
                    "status_message": f"Initializing (Worker: {git_hash})",
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

        # Soft-fail IMS overlay: enrich matcher rows when GSTN session is live.
        try:
            period_y, period_m = _parse_period(period)
            ims_map = try_fetch_ims_status_map_for_client(
                client,
                client_gstin_id,
                year=period_y,
                month=period_m,
            )
            if ims_map is not None:
                hits = apply_ims_status_to_matcher_rows(gstr_matcher, ims_map)
                apply_ims_status_to_record_data(gstr_raw_by_id, gstr_matcher)
                _log.info(
                    "IMS overlay applied run_id=%s hits=%d map_size=%d",
                    run_id,
                    hits,
                    len(ims_map),
                )
            else:
                for rec in gstr_matcher:
                    rec.setdefault("ims_status", "no_action_taken")
        except Exception as exc:
            _log.warning(
                "IMS overlay soft-fail run_id=%s err=%s", run_id, exc
            )
            for rec in gstr_matcher:
                rec.setdefault("ims_status", "no_action_taken")

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

        # ── GSTR-2B AMENDMENT RESOLUTION ──
        amendment_result = build_effective_gstr_records(gstr_matcher)
        effective_gstr = amendment_result.effective_records
        _log.info(
            "[AMENDMENT] Raw GSTR records: %d | Amendments detected: %d | "
            "Chains: %d | Superseded records removed: %d | Effective GSTR records: %d",
            amendment_result.stats.raw_count,
            amendment_result.stats.amendment_count,
            amendment_result.stats.chains_count,
            amendment_result.stats.superseded_count,
            amendment_result.stats.effective_count,
        )
        gstr_matcher = effective_gstr

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

        pr_index_current, pr_index_loaded, _pr_skipped_at_index, pr_note_rows = (
            _build_pr_index_for_matching(client, run_id)
        )
        if n_pr and pr_index_loaded < n_pr:
            _log.warning(
                "PR index load shortfall: matcher_rows=%d notes=%d pr_records_imported=%d run_id=%s",
                pr_index_loaded,
                len(pr_note_rows),
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
        candidate_indices = build_pr_candidate_indices(pr_index_current)
        pr_total_chunks = max(1, (pr_index_loaded + CHUNK_SIZE - 1) // CHUNK_SIZE)

        # Must run BEFORE the Phase 1 batch loop below: detects duplicate/ambiguous
        # (GSTIN, normalized invoice) groups across the *entire* run so Phase 1's
        # greedy per-batch matching never silently auto-picks one of several
        # equally-plausible pairings (see prepass_duplicate_ambiguity docstring).
        pr_flat_current = [p for prs in pr_index_current.values() for p in prs]
        prepass_gstr2b_duplicates(gstr_matcher, state)
        prepass_duplicate_ambiguity(gstr_matcher, pr_flat_current, state)

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
                candidate_indices=candidate_indices,
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
        chunk_skipped_missing_inv = 0
        _update_run(
            client,
            run_id,
            {
                "progress_percent": 50,
                "status_message": f"Writing PR match status (0/{pr_total_chunks} chunks)…",
                "updated_at": _now_iso(),
            },
        )
        while True:
            chunk_started = time.perf_counter()
            # Heartbeat before DB work so the UI does not sit silently at 50%
            # while the first (often largest) upsert is in flight.
            _update_run(
                client,
                run_id,
                {
                    "progress_percent": min(
                        69, 50 + int(20 * chunk_idx / pr_total_chunks)
                    ),
                    "status_message": (
                        f"Writing PR match status "
                        f"({chunk_idx + 1}/{pr_total_chunks})…"
                    ),
                    "updated_at": _now_iso(),
                },
            )
            pr_chunk, pr_raw_chunk, skipped, fetched = _load_pr_matcher_and_raw_page(
                client, run_id, pr_write_offset, CHUNK_SIZE
            )
            if fetched == 0:
                break

            chunk_skipped_missing_inv += len(skipped)
            _log.info(
                "processing chunk %d offset=%d pr_chunk_size=%d fetched=%d skipped_missing_inv=%d",
                chunk_idx,
                pr_write_offset,
                len(pr_chunk),
                fetched,
                len(skipped),
            )

            tracking_rows, chunk_matched, chunk_written = _write_pr_match_status_chunk(
                client,
                run_id=run_id,
                pr_chunk=pr_chunk,
                pr_raw_by_id=pr_raw_chunk,
                matched_pr_ids=state.consumed_pr_ids,
                gstr_by_gstin=gstr_by_gstin,
                gstr_by_id=gstr_by_id,
                matched=state.clean_matched,
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

        if chunk_skipped_missing_inv:
            _log.warning(
                "PR matching skipped %d row(s) missing invoice_number (run_id=%s)",
                chunk_skipped_missing_inv,
                run_id,
            )

        _phase("matching")
        pr_current, pr_raw_by_id = _load_pr_matcher_and_raw(client, run_id)
        late_itc = sum(
            1
            for m in state.clean_matched
            if m.get("is_late_filing")
        )

        pr_by_id: dict[str, dict] = {str(p["id"]): p for p in pr_current}
        gstr_by_id: dict[str, dict] = {str(x.get("id")): x for x in gstr_matcher}

        # Dedicated bilateral Credit Note (CDNR) & Debit Note reconciliation phase
        execute_credit_note_reconciliation(
            gstr_matcher,
            pr_current,
            state,
        )

        # Orphan resolver: pair GSTIN-typo orphans and collapse duplicate filings so
        # no invoice is counted in both Missed ITC and ITC at Risk (double counting).
        execute_phase2_and_3(
            gstr_matcher,
            pr_current,
            state,
            candidate_indices,
        )

        # Residual quarantine: isolate any PR note rows that did NOT find a match
        # in GSTR-2B, keeping them in unmatched_notes and out of ITC at Risk.
        quarantine_pr_notes(state, pr_current)

        wrongful_itc = build_wrongful_itc_risk(pr_current, state.consumed_pr_ids)

        
        # Calculate financial risk
        wrongful_itc = [
            pr_by_id[pid] for pid in pr_by_id if pid not in state.consumed_pr_ids
        ]
        itc_missed = sum(int(x.get("total_tax_paise") or 0) for x in state.missed_itc)
        wrongful_paise = sum(
            int(x.get("total_tax_paise") or 0) for x in wrongful_itc
        )
        _phase("rule37")
        pr_for_rule37 = []
        # Coverage: of matched ITC-claimed invoices, how many have an explicit
        # PR payment_status (known) vs blank (unverified). Paid invoices count
        # as known even though they are not forwarded to the tracker.
        rule37_claimed_invoice_count = 0
        rule37_payment_status_known_count = 0
        rule37_payment_status_unknown_count = 0
        seen_rule37_pr_ids: set[str] = set()
        candidate_pr_sources: list[Any] = [
            *(m.get("pr_id") for m in state.clean_matched if m.get("pr_id")),
            *(r.get("pr_id") for r in state.review_required if r.get("pr_id")),
            *(w.get("id") or w.get("pr_id") for w in wrongful_itc if (w.get("id") or w.get("pr_id"))),
        ]
        for p_curr in pr_current:
            cid = p_curr.get("id")
            if cid:
                candidate_pr_sources.append(cid)

        for candidate_id in candidate_pr_sources:
            pr_id = str(candidate_id).strip()
            if not pr_id or pr_id in seen_rule37_pr_ids:
                continue
            seen_rule37_pr_ids.add(pr_id)
            p = pr_by_id.get(pr_id)
            if not p:
                continue
            raw = pr_raw_by_id.get(pr_id) or {}
            if not isinstance(raw, dict):
                raw = {}

            # ── BUG 1 FIX: ITC-claimed gate ──────────────────────────────────
            # If the PR's itc_eligibility column says "No"/"Ineligible" etc.,
            # exclude this invoice from Rule 37 entirely — no ITC was claimed
            # so there is nothing to reverse.
            if not _is_itc_claimed(raw):
                continue

            rule37_claimed_invoice_count += 1

            status_str = raw.get("payment_status")
            if isinstance(status_str, str):
                status_str = status_str.strip().lower() or None
            else:
                status_str = None  # BUG 2 FIX: blank/None → do NOT default to "unpaid"

            # Known = explicit payment_status and/or payment_date on the PR.
            # Status still gates Rule 37 routing; payment_date alone counts as
            # coverage signal so CAs see that some payment evidence existed.
            pay_date_raw = raw.get("payment_date")
            has_payment_date = False
            if pay_date_raw is not None and str(pay_date_raw).strip():
                has_payment_date = True

            if status_str or has_payment_date:
                rule37_payment_status_known_count += 1
            else:
                rule37_payment_status_unknown_count += 1

            # Only forward unpaid, partially paid, and blank-status records.
            # Blank status is handled inside check_rule_37_compliance as
            # PENDING_VERIFICATION (not added to itc_at_risk).  Paid / other
            # statuses are skipped here for efficiency.
            if status_str is not None and status_str not in (
                "unpaid", "partially paid", "partial"
            ):
                continue

            pr_for_rule37.append(
                {
                    **p,
                    "id": pr_id,
                    "invoice_date": p.get("invoice_date") or gstr_start.isoformat(),
                    # Pass None through so check_rule_37_compliance routes it to
                    # PENDING_VERIFICATION instead of treating it as "unpaid".
                    "payment_status": status_str,
                    "payment_date": pay_date_raw,
                    # itc_claimed=True here because we already filtered above;
                    # passing explicitly so the gate inside the tracker is a no-op.
                    "itc_claimed": True,
                }
            )
        payment_records = build_payment_records_from_pr(
            pr_current, pr_raw_by_id
        )
        # Batch-level ITC claim period from the import wizard (optional).
        itc_claimed_period: str | None = None
        try:
            ir_res = (
                client.table("reconciliation_import_runs")
                .select("itc_claimed_period")
                .eq("id", run_id)
                .limit(1)
                .execute()
            )
            if ir_res.data:
                raw_icp = ir_res.data[0].get("itc_claimed_period")
                if raw_icp:
                    itc_claimed_period = str(raw_icp).strip()[:7] or None
        except Exception:
            _log.exception(
                "execute_reconciliation: could not load itc_claimed_period for %s",
                run_id,
            )
        rule37_all = check_rule_37_compliance(
            pr_for_rule37,
            payment_records,
            # BUG 4 FIX: evaluate the 180-day threshold at the period end date,
            # not date.today().  Without this, invoices whose 180-day window
            # had NOT yet expired as of the reconciliation period (e.g. Sep 2025)
            # but have since expired in wall-clock time are incorrectly flagged.
            today=gstr_end,
            itc_claimed_period=itc_claimed_period,
        )
        # Split tracker output: at-risk rows go to rule37; pending-verification
        # rows are surfaced separately and excluded from itc_at_risk totals.
        rule37 = [r for r in rule37_all if r.get("status") != PENDING_VERIFICATION]
        rule37_pending_verification = [
            r for r in rule37_all if r.get("status") == PENDING_VERIFICATION
        ]
        rule37_itc_paise = sum(
            int(r.get("itc_at_risk_paise") or 0) for r in rule37
        )
        rule37_pending_paise = sum(
            int(
                r.get("potential_itc_paise")
                if r.get("potential_itc_paise") is not None
                else r.get("total_tax_paise")
                or 0
            )
            for r in rule37_pending_verification
        )
        rule37_coverage = {
            "claimed_invoice_count": rule37_claimed_invoice_count,
            "payment_status_known_count": rule37_payment_status_known_count,
            "payment_status_unknown_count": rule37_payment_status_unknown_count,
        }
        late_filing = check_late_filing(
            state.clean_matched, gstr_raw_by_id, claim_period=period
        )
        # Runs-list "ITC at risk" = missed ITC (GSTR-2B invoices with no PR match).
        itc_at_risk_total = itc_missed

        # Build lookup for matched PR ids to enrich GSTR rows with PR-level ITC eligibility
        matched_gstr_to_pr = {str(m["gstr_id"]): str(m["pr_id"]) for m in state.clean_matched}
        for rev in state.review_required:
            if rev.get("gstr_id") and rev.get("pr_id"):
                matched_gstr_to_pr[str(rev["gstr_id"])] = str(rev["pr_id"])

        invoices_for_blocked: list[dict[str, Any]] = []
        for ggr in gstr_matcher:
            gid = str(ggr.get("id", ""))
            rdg = gstr_raw_by_id.get(gid) or {}
            # Full GSTR-2B record_data (incl. items / nested line HSN) for Section 17(5) checks
            merged: dict[str, Any] = dict(rdg) if isinstance(rdg, dict) else {}
            if ggr.get("invoice_number_normalized") is not None:
                merged["invoice_number"] = ggr.get("invoice_number_normalized")
            if ggr.get("supplier_gstin") is not None:
                merged["supplier_gstin"] = ggr.get("supplier_gstin")
            # Date / tax amounts are required for export columns; matcher rows
            # carry them even when record_data is sparse.
            if ggr.get("invoice_date") is not None and not merged.get("invoice_date"):
                merged["invoice_date"] = ggr.get("invoice_date")
            for amt_key in (
                "taxable_amount_paise",
                "total_tax_paise",
                "igst_paise",
                "cgst_paise",
                "sgst_paise",
            ):
                if ggr.get(amt_key) is not None and merged.get(amt_key) is None:
                    merged[amt_key] = ggr.get(amt_key)
            
            # Merge PR's itc_eligibility, hsn, and purchase_ledger if matched
            matched_pr_id = matched_gstr_to_pr.get(gid)
            if matched_pr_id:
                pr_raw = pr_raw_by_id.get(matched_pr_id) or {}
                if isinstance(pr_raw, dict):
                    if pr_raw.get("itc_eligibility") is not None:
                        merged["itc_eligibility"] = pr_raw.get("itc_eligibility")
                    if pr_raw.get("hsn") is not None:
                        merged["hsn"] = pr_raw.get("hsn")
                    elif (pr_by_id.get(matched_pr_id) or {}).get("hsn") is not None:
                        merged["hsn"] = pr_by_id[matched_pr_id]["hsn"]
                    if pr_raw.get("purchase_ledger") is not None:
                        merged["purchase_ledger"] = pr_raw.get("purchase_ledger")
                    
            invoices_for_blocked.append(merged)

        matched_pr_ids = set(matched_gstr_to_pr.values())
        for pr in pr_current:
            pid = str(pr.get("id", ""))
            if pid not in matched_pr_ids:
                raw_pr = pr_raw_by_id.get(pid) or {}
                pr_merged = dict(raw_pr) if isinstance(raw_pr, dict) else {}
                pr_merged["invoice_number"] = pr.get("invoice_number_normalized") or pr.get("invoice_number")
                pr_merged["supplier_gstin"] = pr.get("supplier_gstin")
                pr_merged["invoice_date"] = pr.get("invoice_date")
                pr_merged["total_tax_paise"] = pr.get("total_tax_paise")
                pr_merged["cgst_paise"] = pr.get("cgst_paise")
                pr_merged["sgst_paise"] = pr.get("sgst_paise")
                pr_merged["igst_paise"] = pr.get("igst_paise")
                if raw_pr.get("itc_eligibility") is not None:
                    pr_merged["itc_eligibility"] = raw_pr["itc_eligibility"]
                if pr.get("hsn") is not None:
                    pr_merged["hsn"] = pr["hsn"]
                elif raw_pr.get("hsn") is not None:
                    pr_merged["hsn"] = raw_pr["hsn"]
                if raw_pr.get("purchase_ledger") is not None:
                    pr_merged["purchase_ledger"] = raw_pr["purchase_ledger"]
                invoices_for_blocked.append(pr_merged)
        s175 = check_blocked_credits(invoices_for_blocked)

        _phase("amount-diff-upsert")
        amount_diff_upsert_rows: list[dict[str, Any]] = []
        amount_diff_ts = _now_iso()
        for m in state.clean_matched:
            gid = str(m.get("gstr_id") or "")
            pid = str(m.get("pr_id") or "")
            ggr = gstr_by_id.get(gid, {})
            pr = pr_by_id.get(pid, {})
            try:
                gid_int = int(gid)
            except (TypeError, ValueError):
                _log.warning("skip amount_difference_paise: invalid gstr_id=%s", gid)
                continue
            # Prefer taxable-value delta for decision templates / export WHAT IS WRONG.
            # Fall back to total_tax delta only when taxable is unavailable on either side.
            g_taxable = ggr.get("taxable_amount_paise")
            p_taxable = pr.get("taxable_amount_paise")
            if g_taxable is not None and p_taxable is not None:
                diff = abs(int(g_taxable) - int(p_taxable))
            else:
                diff = abs(
                    int(ggr.get("total_tax_paise") or 0)
                    - int(pr.get("total_tax_paise") or 0)
                )
            # Attach onto the matched row BEFORE populate_decisions so L2/L3
            # templates receive the real delta (not a missing-key default of 0).
            m["taxable_diff_paise"] = diff
            m["amount_difference_paise"] = diff
            m["gstr_taxable_amount_paise"] = int(g_taxable or 0)
            m["pr_taxable_amount_paise"] = int(p_taxable or 0)
            # Raw invoice strings for L2_NORMALIZED decision text (GSTR ↔ PR).
            g_inv = str(ggr.get("invoice_number") or "").strip()
            p_inv = str(pr.get("invoice_number") or "").strip()
            if g_inv:
                m["gstr_invoice_number"] = g_inv
                m.setdefault("invoice_number", g_inv)
            if p_inv:
                m["pr_invoice_number"] = p_inv
            amount_diff_upsert_rows.append(
                {
                    "id": gid_int,
                    "amount_difference_paise": diff,
                    "match_status": m.get("match_status", "matched"),
                    "match_level": m.get("match_level"),
                    "matched_pr_record_id": pid,
                    "updated_at": amount_diff_ts,
                }
            )
        if amount_diff_upsert_rows:
            _DIFF_BATCH = 200
            for _di in range(0, len(amount_diff_upsert_rows), _DIFF_BATCH):
                _chunk = amount_diff_upsert_rows[_di : _di + _DIFF_BATCH]
                try:
                    client.table("gstr_records").upsert(
                        _chunk,
                        on_conflict="id",
                        returning="minimal",
                    ).execute()
                except Exception:
                    _log.exception(
                        "amount_difference_paise bulk upsert failed (batch %d, size %d)",
                        _di // _DIFF_BATCH,
                        len(_chunk),
                    )

        _phase("carry-forward")
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

        _phase("credit-notes")
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

        _phase("decision-layer")
        merged_rule37 = (rule37 or []) + (late_filing or [])

        # Enrich review-required rows with decision output first so auto-triage
        # can promote rows that already carry decision_* fields.
        state.review_required = populate_review_decisions(state.review_required)

        # Confidence-threshold auto-triage: promote high-confidence Review
        # Required pairs into Matched (tagged auto_approved) so KPI cards
        # reflect the real counts. Threshold comes from firm owner's profile
        # (default 95%). See app.services.auto_approve.
        from app.services.auto_approve import (
            DEFAULT_AUTO_APPROVE_THRESHOLD,
            apply_confidence_auto_approve,
            normalize_confidence_threshold,
        )
        from app.services.firm_access import get_firm_owner_for_client

        auto_approve_threshold = DEFAULT_AUTO_APPROVE_THRESHOLD
        try:
            owner_id = get_firm_owner_for_client(client, client_gstin_id)
            pref_res = (
                client.table("user_profiles")
                .select("auto_approve_confidence_threshold")
                .eq("id", owner_id)
                .limit(1)
                .execute()
            )
            if pref_res.data:
                auto_approve_threshold = normalize_confidence_threshold(
                    pref_res.data[0].get("auto_approve_confidence_threshold")
                )
        except Exception:
            _log.exception(
                "Failed to load auto-approve threshold for client_gstin_id=%s; using default %d",
                client_gstin_id,
                DEFAULT_AUTO_APPROVE_THRESHOLD,
            )

        state.clean_matched, state.review_required, auto_approved_n = (
            apply_confidence_auto_approve(
                state.clean_matched,
                state.review_required,
                auto_approve_threshold,
            )
        )
        if auto_approved_n:
            _log.info(
                "Auto-approved %d review row(s) at threshold %d%% (run_id=%s)",
                auto_approved_n,
                auto_approve_threshold,
                run_id,
            )

        scheme_type = "regular"
        try:
            st_res = (
                client.table("client_gstins")
                .select("scheme_type")
                .eq("id", client_gstin_id)
                .limit(1)
                .execute()
            )
            if st_res.data:
                scheme_type = str(st_res.data[0].get("scheme_type") or "regular").lower().strip()
        except Exception:
            _log.warning("Could not fetch scheme_type for client_gstin_id=%s", client_gstin_id)

        decision_payload = populate_decisions(
            state.clean_matched,
            scheme_type=scheme_type,
            rule37=merged_rule37,
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
        late_itc_paise = sum(int(r.get("amount_paise") or 0) for r in late_filing)
        late_itc = len(late_filing)
        matched_count = len(state.clean_matched)
        missed_itc_count = len(state.missed_itc)
        wrongful_count = len(wrongful_itc)
        gstr_duplicate_count = sum(1 for d in state.duplicate_entries if d.get("side") == "GSTR2B")
        review_gstr_count = sum(1 for r in state.review_required if r.get("gstr_id"))
        review_pr_count = len(state.consumed_pr_ids) - matched_count
        skipped_count = sum(1 for r in pr_current if r.get("match_status") == "skipped")
        unmatched_notes_count = len(state.unmatched_notes)
        gstr_note_count = sum(
            1 for n in state.unmatched_notes if n.get("side") == "GSTR" or n.get("gstr_id")
        )

        assert (
            matched_count
            + missed_itc_count
            + review_gstr_count
            + gstr_duplicate_count
            + gstr_note_count
            == len(gstr_matcher)
        ), (
            f"GSTR Data Loss! Matched:{matched_count} Missed:{missed_itc_count} "
            f"Review:{review_gstr_count} Duplicates:{gstr_duplicate_count} "
            f"Notes:{gstr_note_count} Total:{len(gstr_matcher)}"
        )
        
        assert (
            matched_count
            + wrongful_count
            + review_pr_count
            + skipped_count
            == n_pr
        ), (
            f"PR Data Loss! Matched:{matched_count} Risk:{wrongful_count} "
            f"Review PRs:{review_pr_count} Skipped:{skipped_count} "
            f"Notes:{unmatched_notes_count} Total:{n_pr}"
        )

        matched_itc_paise = 0
        for m in state.clean_matched:
            gid = str(m.get("gstr_id") or "")
            pid = str(m.get("pr_id") or "")
            g = gstr_by_id.get(gid) or {}
            p = pr_by_id.get(pid) or {}
            matched_itc_paise += min(
                int(g.get("total_tax_paise") or 0),
                int(p.get("total_tax_paise") or 0),
            )

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
            rule37_pending_verification_count=len(rule37_pending_verification),
            rule37_pending_verification_paise=rule37_pending_paise,
            rule37_claimed_invoice_count=rule37_claimed_invoice_count,
            rule37_payment_status_known_count=rule37_payment_status_known_count,
            rule37_payment_status_unknown_count=rule37_payment_status_unknown_count,
            skipped_count=skipped_count,
            review_required_count=review_gstr_count,
            duplicate_entry_count=len(state.duplicate_entries),
            unmatched_notes_count=len(state.unmatched_notes),
            matched_itc_paise=matched_itc_paise,
        )
        # Preserve ISD/IMPG detection written at import / GSTR-2B sanity time.
        try:
            prior_rs_res = (
                client.table("reconciliation_run")
                .select("run_summary")
                .eq("id", run_id)
                .limit(1)
                .execute()
            )
            prior_rs = (
                (prior_rs_res.data or [{}])[0].get("run_summary")
                if prior_rs_res.data
                else None
            )
            if isinstance(prior_rs, dict):
                for _k in (
                    "isd_present",
                    "isd_count",
                    "impg_present",
                    "impg_count",
                    "isd_impg_warning",
                ):
                    if _k in prior_rs and prior_rs.get(_k) is not None:
                        run_summary[_k] = prior_rs[_k]
        except Exception:
            _log.exception(
                "execute_reconciliation: could not preserve ISD/IMPG fields for %s",
                run_id,
            )

        valid_review_required = []
        for r in state.review_required:
            gid = r.get("gstr_id")
            pid = r.get("pr_id")
            if not gid and not pid:
                _log.warning(f"Skipping REVIEW_REQUIRED record with missing IDs: {r}")
                continue
            reason = r.get("review_reason") or r.get("reason")
            if not reason:
                _log.warning(f"Skipping REVIEW_REQUIRED record with missing reason: {r}")
                continue
            
            r["reason"] = reason
            gid_valid = gid and str(gid).strip() and str(gid).strip() != "None"
            pid_valid = pid and str(pid).strip() and str(pid).strip() != "None"
            
            if gid_valid and pid_valid:
                # Paired record, keep both IDs, no single "side"
                r["gstr_id"] = gid
                r["id"] = pid
            elif gid_valid:
                r["side"] = "GSTR"
                r["gstr_id"] = gid
            elif pid_valid:
                r["side"] = "PR"
                r["id"] = pid

            valid_review_required.append(r)

        # Finalize first so ims_status (and other finalize mutations) are on
        # state lists before we slim + persist the results payload.
        res_payload = _finalize_reconciliation_result(
            state,
            len(gstr_matcher),
            n_pr,
            pr_current,
            gstr_matcher,
        )
        payload = _json_safe(
            build_stored_results_payload(
                matched=state.clean_matched,
                missed_itc=state.missed_itc,
                wrongful_itc_risk=res_payload.get("wrongful_itc_risk") or wrongful_itc,
                rule37=rule37,
                section_175_warnings=s175,
                credit_note_adjustment=cn_net,
                late_filing=late_filing,
                decision_payload=decision_payload,
                matching_version=MATCHING_VERSION,
                rules_version=RULES_VERSION,
                decision_version=DECISION_VERSION,
                gstin_mismatch=[],
                duplicates=valid_review_required,
                duplicate_entries=list(state.duplicate_entries),
                unmatched_notes=list(state.unmatched_notes),
                rule37_pending_verification=rule37_pending_verification,
                rule37_coverage=rule37_coverage,
                review_required_typo=[],
            )
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(payload, dict):
            payload["amendment_summary"] = {
                "raw_count": amendment_result.stats.raw_count,
                "amendment_count": amendment_result.stats.amendment_count,
                "chains_count": amendment_result.stats.chains_count,
                "superseded_count": amendment_result.stats.superseded_count,
                "effective_count": amendment_result.stats.effective_count,
                "chains": amendment_result.amendment_chains,
            }
        save_reconciliation_results(
            client,
            run_id,
            payload,
            created_at=_now_iso(),
        )

        completion_msg = "Completed"
        if skipped_count > 0:
            completion_msg = (
                f"Completed — {skipped_count} skipped: missing invoice number"
            )
        _update_run(
            client,
            run_id,
            {
                "status": RunStatus.COMPLETED,
                "progress_percent": 100.0,
                "completed_at": _now_iso(),
                "status_message": completion_msg,
                "run_summary": run_summary,
                "matched_count": matched_count + review_gstr_count,
                "unmatched_count": missed_itc_count + wrongful_count,
                "itc_at_risk": itc_at_risk_total,
                "wrongful_itc": wrongful_paise,
                "late_itc": late_itc_paise,
                "matching_version": MATCHING_VERSION,
                "rules_version": RULES_VERSION,
                "decision_version": DECISION_VERSION,
                "updated_at": _now_iso(),
            },
        )
        try:
            from app.services.supplier_compliance_scorecard import refresh_after_run

            refresh_after_run(
                client, run_id=run_id, client_gstin_id=client_gstin_id
            )
        except Exception:
            _log.exception(
                "supplier scorecard refresh failed run_id=%s", run_id
            )
        match_rate = round(len(state.clean_matched) / n_gstr * 100, 2) if n_gstr else 0.0

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
            matched_count=len(state.clean_matched),
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
                "matched_count": len(state.clean_matched),
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
