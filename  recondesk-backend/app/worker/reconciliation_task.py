"""Background reconciliation: batched I/O, single-shot persistence."""

from __future__ import annotations

import calendar
import json
import logging
import os
import traceback
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from supabase import Client

from app.decisions.layer import populate_decisions
from app.services import reconciliation_record_adapter as rec_adapt
from app.services.blocked_credit_checker import check_blocked_credits
from app.services.credit_note_handler import classify_document, net_itc_after_credit_notes
from app.services.reconciliation import (
    ReconState,
    _build_pr_index_by_period,
    build_wrongful_itc_risk,
    process_gstr_records_chunk,
)
from app.constants import RunStatus
from app.services.rule37_tracker import check_rule_37_compliance
from app.worker.celery_app import celery_app
from app.worker.tasks import _json_safe, _supabase, _update_run

_log = logging.getLogger(__name__)

BATCH = 2_000
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
                .range(offset, offset + BATCH - 1)
                .execute()
            )
            rows = r.data or []
            if not rows:
                break
            pkey = _parse_period(mo)
            pdate = date(pkey[0], pkey[1], 1)
            for row in rows:
                by_period[pdate].append(rec_adapt.pr_db_row_to_matcher_row(row))
            if len(rows) < BATCH:
                break
            offset += BATCH
    return {k: v for k, v in by_period.items()}


def _load_pr_current_paged(
    client: Client, run_id: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        r = (
            client.table("pr_records")
            .select("id, record_data")
            .eq("run_id", run_id)
            .range(offset, offset + BATCH - 1)
            .execute()
        )
        rows = r.data or []
        if not rows:
            break
        for row in rows:
            out.append(rec_adapt.pr_db_row_to_matcher_row(row))
        if len(rows) < BATCH:
            break
        offset += BATCH
    return out


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
            .range(offset, offset + BATCH - 1)
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
        if len(rows) < BATCH:
            break
        offset += BATCH
    return (out, raw_by_id)


@celery_app.task(name="worker.execute_reconciliation", max_retries=0)
def execute_reconciliation(run_id: str) -> None:
    if not os.environ.get("REDIS_URL"):
        _log.debug("REDIS_URL not set; using fallback from Settings")

    client = _supabase()
    try:
        run_res = (
            client.table("reconciliation_run")
            .select(
                "id, status, client_gstin_id, period, gstr_records_imported, pr_records_imported"
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

        pr_current = _load_pr_current_paged(client, run_id)
        _update_run(
            client,
            run_id,
            {
                "progress_percent": 10,
                "status_message": "Data loaded",
                "updated_at": _now_iso(),
            },
        )

        months_back = previous_n_calendar_months(period, 6)
        historical = _load_pr_for_historical_periods_paged(
            client, client_gstin_id, run_id, months_back
        )

        gstr_p = gstr_start
        pr_by_period: dict[date, list[dict]] = {gstr_p: list(pr_current)}
        for d0, prs in historical.items():
            k = date(d0.year, d0.month, 1)
            pr_by_period.setdefault(k, []).extend(prs)

        pr_index_by_period = _build_pr_index_by_period(pr_by_period)
        pr_index_current: dict[str, list[dict]] = defaultdict(list)
        for pr_rec in pr_current:
            pr_index_current[str(pr_rec.get("supplier_gstin") or "")].append(
                pr_rec
            )

        gstr_matcher, gstr_raw_by_id = _load_gstr_matcher_and_raw(client, run_id)
        for rec in gstr_matcher:
            if not rec.get("invoice_date"):
                rec["invoice_date"] = gstr_end.isoformat()

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
        n_chunks = max(1, (len(gstr_matcher) + BATCH - 1) // BATCH)
        _update_run(
            client,
            run_id,
            {
                "progress_percent": 30,
                "status_message": "Matching started",
                "updated_at": _now_iso(),
            },
        )
        mid_done = (n_chunks + 1) // 2
        for i in range(0, len(gstr_matcher), BATCH):
            chunk = gstr_matcher[i : i + BATCH]
            process_gstr_records_chunk(
                chunk,
                gstr_p,
                pr_index_current,
                pr_index_by_period,
                state,
            )
            done = i // BATCH + 1
            if done == n_chunks:
                pct = 70
            elif n_chunks > 1 and done == mid_done and done < n_chunks:
                pct = 50
            else:
                pct = min(69, 30 + int(40 * done / n_chunks))
            _update_run(
                client,
                run_id,
                {
                    "progress_percent": pct,
                    "status_message": f"Matching ({min(done, n_chunks)}/{n_chunks} batches)",
                    "updated_at": _now_iso(),
                },
            )

        wrongful_itc = build_wrongful_itc_risk(pr_current, state.matched_pr_ids)
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
        rule37 = check_rule_37_compliance(
            [
                {
                    **p,
                    "id": p["id"],
                    "invoice_date": p.get("invoice_date")
                    or gstr_start.isoformat(),
                }
                for p in pr_current
            ],
            [],
        )
        r37_itc = sum(
            int(r.get("itc_at_risk_paise") or 0) for r in (rule37 or [])
        )
        itc_at_risk_total = r37_itc if r37_itc else itc_missed

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
        _log.warning("DEBUG s175 input sample: %s", gstr_invoices_for_blocked[:2])
        s175 = check_blocked_credits(gstr_invoices_for_blocked)
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
            try:
                client.table("gstr_records").update(
                    {"amount_difference_paise": diff}
                ).eq("id", gid_int).execute()
            except Exception:
                _log.exception(
                    "amount_difference_paise update failed gstr_id=%s", gid
                )
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
        run_summary = {
            "total_records": total_invoices,
            "matched_count": len(state.matched),
            "unmatched_count": len(state.missed_itc) + len(wrongful_itc),
            "itc_at_risk": itc_at_risk_total,
            "wrongful_itc": wrongful_paise,
            "late_itc": late_itc_paise,
            "late_match_count": late_itc,
            "gstr_in_scope": n_gstr,
            "pr_in_scope": n_pr,
            "compliance": {
                "rule37": rule37,
                "section_17_5": s175,
            },
            "decisions": decision_payload,
        }

        payload = _json_safe(
            {
                "engine": {
                    "matched": state.matched,
                    "missed_itc": state.missed_itc,
                    "wrongful_itc_risk": wrongful_itc,
                },
                "compliance": {
                    "rule37": rule37,
                    "section_17_5": s175,
                    "credit_notes": cn_net,
                },
                "decisions": decision_payload,
                "summary": run_summary,
                "meta": {
                    "matching_version": MATCHING_VERSION,
                    "rules_version": RULES_VERSION,
                    "decision_version": DECISION_VERSION,
                },
            }
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
        client.table("reconciliation_results").delete().eq("run_id", run_id).execute()
        res_ins = (
            client.table("reconciliation_results")
            .insert(
                {
                    "run_id": run_id,
                    "payload": payload,
                    "created_at": _now_iso(),
                }
            )
            .execute()
        )
        if res_ins.data is None and getattr(res_ins, "error", None):
            raise RuntimeError(
                f"reconciliation_results insert failed: {res_ins.error}"
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
