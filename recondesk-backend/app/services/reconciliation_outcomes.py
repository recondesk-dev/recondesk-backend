"""Build API-facing reconciliation stats and invoice rows from run payload + DB rows."""

from __future__ import annotations

import json
import re
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, List, Optional, Tuple, TypeVar

from supabase import Client

from app.constants import ChangeReason, DecisionNext, DecisionWhat, DecisionWhy
from app.services import reconciliation_record_adapter as rec_adapt
from app.services.credit_note_handler import classify_document
from app.services.matcher import TOTAL_TOLERANCE_PAISE, match_gstr_to_pr

# Request-scoped memo so one HTTP handler does not re-page GSTR/PR maps /
# payload / outcome rows when multiple builders run in the same call.
_request_load_cache: ContextVar[dict[str, Any] | None] = ContextVar(
    "recon_request_load_cache", default=None
)

# Short process-level memo so parallel /summary + /matched on the same worker
# share one GSTR/PR page scan instead of two. Bounded + TTL to limit RAM.
_process_map_cache: dict[str, tuple[float, Any]] = {}
_process_map_locks: dict[str, threading.Lock] = {}
_process_map_guard = threading.Lock()
_PROCESS_MAP_TTL_SECONDS = 90.0
_PROCESS_MAP_MAX_ENTRIES = 6


def _req_cache() -> dict[str, Any]:
    c = _request_load_cache.get()
    if c is None:
        c = {}
        _request_load_cache.set(c)
    return c


def clear_request_load_cache() -> None:
    """Reset memo (tests / long-lived workers)."""
    _request_load_cache.set(None)


def clear_process_maps_for_run(run_id: str) -> None:
    """Drop process-level GSTR/PR maps after mutations / re-import."""
    rid = str(run_id).strip()
    if not rid:
        return
    with _process_map_guard:
        _process_map_cache.pop(f"gstr:{rid}", None)
        _process_map_cache.pop(f"pr:{rid}", None)


def _process_map_lock(key: str) -> threading.Lock:
    with _process_map_guard:
        lock = _process_map_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _process_map_locks[key] = lock
        return lock


def _process_map_get(key: str) -> Any | None:
    now = time.monotonic()
    with _process_map_guard:
        hit = _process_map_cache.get(key)
        if hit is None:
            return None
        ts, value = hit
        if now - ts > _PROCESS_MAP_TTL_SECONDS:
            _process_map_cache.pop(key, None)
            return None
        return value


def _process_map_set(key: str, value: Any) -> None:
    now = time.monotonic()
    with _process_map_guard:
        _process_map_cache[key] = (now, value)
        if len(_process_map_cache) <= _PROCESS_MAP_MAX_ENTRIES:
            return
        oldest_key = min(_process_map_cache.items(), key=lambda kv: kv[1][0])[0]
        _process_map_cache.pop(oldest_key, None)

# Rule 37 statuses that surface as “warnings / flag”
RULE37_CONCERNS = frozenset(
    {
        "PAID_LATE",
        "OVERDUE_UNPAID",
        "WARNING_30_DAYS",
        "WARNING_60_DAYS",
        "LATE_FILING",
    }
)
_RULE37_CONCERNS = RULE37_CONCERNS

GSTIN_RE = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
)


def is_valid_gstin(g: str) -> bool:
    return bool(GSTIN_RE.match((g or "").strip().upper()))


def parse_optional_date(s: Any) -> Optional[date]:
    if s is None or s == "":
        return None
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if isinstance(s, datetime):
        return s.date()
    t = str(s).strip()
    if not t:
        return None
    if "T" in t:
        t = t[:10]
    try:
        return date.fromisoformat(t[:10])
    except (ValueError, TypeError):
        return None


def _gstr_name(rd: dict[str, Any]) -> Optional[str]:
    for k in ("supplier_name", "trade_name", "legal_name", "ctin_name"):
        v = rd.get(k)
        if v and str(v).strip():
            return str(v).strip()
    return None


# Supabase/PostgREST silently caps every request at 1,000 rows regardless of the
# `.range()` window requested (e.g. `.range(0, 1999)` still only returns 1,000 rows).
# Previously this loop requested 2,000-row pages and treated `len(rows) < 2000` as
# "no more data" — since the server never returns more than 1,000, that condition
# was true after the very first page, silently truncating the map to the first
# ~1,000 records on any run with more gstr/pr records than that. This left the
# majority of Matched / Missed ITC / ITC at Risk / Review Required rows with blank
# supplier_gstin / invoice_number / invoice_date / amount fields on larger runs.
#
# Fix: request pages at the server's actual page size, advance the offset by the
# number of rows *actually returned* (not an assumed constant), and terminate
# against the table's real total row count for this run rather than guessing
# end-of-data from a page-size comparison that the server may not honour.
_DB_PAGE_SIZE = 1000


def _load_gstr_map(sb: Client, run_id: str) -> dict[str, dict[str, Any]]:
    cache = _req_cache()
    ck = f"gstr:{run_id}"
    hit = cache.get(ck)
    if hit is not None:
        return hit

    proc_hit = _process_map_get(ck)
    if proc_hit is not None:
        cache[ck] = proc_hit
        return proc_hit

    with _process_map_lock(ck):
        proc_hit = _process_map_get(ck)
        if proc_hit is not None:
            cache[ck] = proc_hit
            return proc_hit

        out: dict[str, dict[str, Any]] = {}
        count_res = (
            sb.table("gstr_records")
            .select("id", count="exact")
            .eq("run_id", run_id)
            .limit(1)
            .execute()
        )
        total = count_res.count or 0
        off = 0
        while len(out) < total:
            r = (
                sb.table("gstr_records")
                .select("id, record_data")
                .eq("run_id", run_id)
                .range(off, off + _DB_PAGE_SIZE - 1)
                .execute()
            )
            rows = r.data or []
            if not rows:
                break
            for row in rows:
                out[str(row["id"])] = {
                    "matcher": rec_adapt.gstr_db_row_to_matcher_row(row),
                    "record_data": row.get("record_data") or {},
                }
            off += len(rows)
        _process_map_set(ck, out)
        cache[ck] = out
        return out


def _load_pr_map(sb: Client, run_id: str) -> dict[str, dict[str, Any]]:
    cache = _req_cache()
    ck = f"pr:{run_id}"
    hit = cache.get(ck)
    if hit is not None:
        return hit

    proc_hit = _process_map_get(ck)
    if proc_hit is not None:
        cache[ck] = proc_hit
        return proc_hit

    with _process_map_lock(ck):
        proc_hit = _process_map_get(ck)
        if proc_hit is not None:
            cache[ck] = proc_hit
            return proc_hit

        out: dict[str, dict[str, Any]] = {}
        count_res = (
            sb.table("pr_records")
            .select("id", count="exact")
            .eq("run_id", run_id)
            .limit(1)
            .execute()
        )
        total = count_res.count or 0
        off = 0
        while len(out) < total:
            r = (
                sb.table("pr_records")
                .select("id, record_data")
                .eq("run_id", run_id)
                .range(off, off + _DB_PAGE_SIZE - 1)
                .execute()
            )
            rows = r.data or []
            if not rows:
                break
            for row in rows:
                out[str(row["id"])] = {
                    "matcher": rec_adapt.pr_db_row_to_matcher_row(row),
                    "record_data": row.get("record_data") or {},
                }
            off += len(rows)
        _process_map_set(ck, out)
        cache[ck] = out
        return out


@dataclass(kw_only=True)
class OutcomeRow:
    """Single invoice line for the public API (before pagination)."""

    id: str
    category: str
    supplier_gstin: str
    pr_supplier_gstin: Optional[str] = None
    gstr_supplier_gstin: Optional[str] = None
    supplier_name: Optional[str] = None
    invoice_number: str
    invoice_date: Optional[str]
    match_status: str
    taxable_value_diff: int
    igst_diff: int
    cgst_diff: int
    sgst_diff: int
    total_tax_diff_paise: int
    decision_what: str
    decision_why: str
    decision_next: str
    rule37_flag: bool
    blocked_credit_flag: bool
    late_filing_flag: bool
    is_credit_note: bool
    amount: Optional[int]
    matched_pr_id: Optional[str] = None
    match_confidence: Optional[float] = None
    compared_fields: Optional[list[dict[str, Any]]] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "supplier_gstin": self.supplier_gstin,
            "pr_supplier_gstin": self.pr_supplier_gstin,
            "gstr_supplier_gstin": self.gstr_supplier_gstin,
            "supplier_name": self.supplier_name,
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date,
            "match_status": self.match_status,
            "taxable_value_diff": self.taxable_value_diff,
            "igst_diff": self.igst_diff,
            "cgst_diff": self.cgst_diff,
            "sgst_diff": self.sgst_diff,
            "total_tax_diff_paise": self.total_tax_diff_paise,
            "decision_what": self.decision_what,
            "decision_why": self.decision_why,
            "decision_next": self.decision_next,
            "rule37_flag": self.rule37_flag,
            "blocked_credit_flag": self.blocked_credit_flag,
            "late_filing_flag": self.late_filing_flag,
            "is_credit_note": self.is_credit_note,
            "amount": self.amount,
            "matched_pr_id": self.matched_pr_id,
            "match_confidence": self.match_confidence,
            "compared_fields": self.compared_fields,
        }


def _mr_to_decisions(
    g: dict[str, Any], p: dict[str, Any]
) -> tuple[str, str, str, int, int, int, int, int, str]:
    """Return decision enums + diffs; derive match_status from financial diffs only.

    Bug-1d fix: the old implementation called match_gstr_to_pr(g, [p]) on the
    API read path, creating a second independent classification that could overwrite
    the engine's decision.  If the live call returned a different result (e.g. the
    engine matched a pair as L1 but the live call returned L3 due to a re-normalised
    invoice), the OutcomeRow.match_status was set to MISMATCHED, causing the row to
    be routed to the Review Required tab instead of Matched.  Fixed by computing
    match_status purely from financial diffs — the same numeric threshold the engine
    uses — without re-invoking the matcher.
    """
    tg, tp = int(g.get("taxable_amount_paise") or 0), int(
        p.get("taxable_amount_paise") or 0
    )
    g_ig, g_cg, g_sg = (
        int(g.get("igst_paise") or 0),
        int(g.get("cgst_paise") or 0),
        int(g.get("sgst_paise") or 0),
    )
    p_ig, p_cg, p_sg = (
        int(p.get("igst_paise") or 0),
        int(p.get("cgst_paise") or 0),
        int(p.get("sgst_paise") or 0),
    )
    tvd = tg - tp
    igd, cgd, sgd = g_ig - p_ig, g_cg - p_cg, g_sg - p_sg
    g_tt = int(g.get("total_tax_paise") or 0)
    p_tt = int(p.get("total_tax_paise") or 0)
    ttd = g_tt - p_tt
    # match_status is MATCHED when both taxable and total-tax diffs are within
    # rounding tolerance.  This is the only classification used here; the engine
    # payload is authoritative for whether the pair is in the Matched vs Review
    # Required bucket.
    st = "MATCHED" if (abs(tvd) <= TOTAL_TOLERANCE_PAISE and abs(ttd) <= TOTAL_TOLERANCE_PAISE) else "MISMATCHED"
    if g_tt > p_tt:
        d_why = DecisionWhy.GSTR_AMOUNT_HIGHER
    else:
        d_why = DecisionWhy.BOOKS_AMOUNT_HIGHER
    if abs(tvd) > TOTAL_TOLERANCE_PAISE or abs(ttd) > TOTAL_TOLERANCE_PAISE:
        d_next = DecisionNext.FOLLOW_UP_SUPPLIER
        if abs(tvd) >= abs(ttd):
            d_what = DecisionWhat.MISMATCH_TAXABLE_VALUE
        else:
            d_what = DecisionWhat.MISMATCH_AMOUNT
    else:
        d_what = DecisionWhat.MISMATCH_AMOUNT
        d_next = DecisionNext.NO_ACTION
    return (d_what, d_why, d_next, tvd, igd, cgd, sgd, ttd, st)


def _sum_itc_paise_with_fallback(
    itc_list: list[dict[str, Any]],
    gstr_m: dict[str, dict[str, Any]],
) -> int:
    """Sum total_tax_paise from engine missed_itc rows with DB-fallback for zeroes.

    Bug-2 fix: the engine slims missed_itc rows to _MISSED_ITC_KEYS before
    serialisation.  If total_tax_paise was None at serialisation time it is stored
    as 0 (int cast in execute_phase2_and_3).  On read-back the engine list has 0
    but the DB matcher row has the real amount, producing a discrepancy between
    the KPI card (which called a bare sum()) and the tab (which had a DB fallback).
    This helper is used in both places so they always agree.
    """
    total = 0
    for item in itc_list:
        amt = int(item.get("total_tax_paise") or 0)
        if amt == 0:
            gid = str(item.get("gstr_id") or "")
            cell = gstr_m.get(gid) or {}
            amt = int((cell.get("matcher") or {}).get("total_tax_paise") or 0)
        total += amt
    return total


def _rule37_index(rule37: list[dict]) -> dict[str, dict]:
    return {str(x.get("pr_id")): x for x in rule37 if x.get("pr_id") is not None}


def _blocked_pair(x: dict[str, Any]) -> tuple[str, str]:
    sg = str(x.get("supplier_gstin") or "").strip().upper()
    inv = str(x.get("invoice_number") or "").strip()
    return (sg, inv)


def _blocked_index(blocked: list[dict]) -> set[tuple[str, str]]:
    """Keys match (supplier_gstin, invoice_number) from Section 17(5) warnings."""
    s: set[tuple[str, str]] = set()
    for x in blocked:
        pair = _blocked_pair(x)
        if pair[0]:
            s.add(pair)
    return s


def _opt_int(v: Any) -> Optional[int]:
    if v is None or str(v).strip() == "":
        return None
    try:
        return int(float(str(v).strip()))
    except ValueError:
        return None


def build_outcome_rows(
    sb: Client,
    run_id: str,
    payload: dict[str, Any],
) -> tuple[list[OutcomeRow], dict[str, int], dict[str, Any]]:
    """Load maps, merge engine+compliance, return rows + category counts + money stats."""
    cache = _req_cache()
    # Same payload object within one request → reuse full outcome build.
    ck = f"outcomes:{run_id}:{id(payload)}"
    hit = cache.get(ck)
    if hit is not None:
        return hit

    engine = payload.get("engine") or {}
    comp = payload.get("compliance") or {}
    gstr_m = _load_gstr_map(sb, run_id)
    pr_m = _load_pr_map(sb, run_id)
    r37x = _rule37_index(list(comp.get("rule37") or []))
    s175 = list(comp.get("section_17_5") or comp.get("section_175") or [])
    blocked_by_gstr = _blocked_index(s175)

    late_filing = comp.get("late_filing") or []
    late_filing_by_gstr = {str(r.get("gstr_id", "")): r for r in late_filing if isinstance(r, dict)}

    rows: list[OutcomeRow] = []

    # Exclude quarantined PR notes from the legacy credit_notes category —
    # they belong in unmatched_notes only.
    for pid, pr in pr_m.items():
        m = pr["matcher"]
        rd = pr.get("record_data") or {}
        if m.get("pr_note_quarantine") or rd.get("pr_note_quarantine"):
            continue
        is_cn = (
            classify_document(
                {
                    "invoice_number_normalized": str(
                        m.get("invoice_number_normalized") or ""
                    ),
                    "taxable_amount_paise": int(m.get("taxable_amount_paise") or 0),
                }
            )
            == "CREDIT_NOTE"
        )
        if is_cn:
            invn = str(m.get("invoice_number_normalized") or "")
            invd = m.get("invoice_date")
            r37r = r37x.get(str(pid), {})
            r37f = (r37r.get("status") or "") in _RULE37_CONCERNS
            rows.append(
                OutcomeRow(
                    id=f"cn:{pid}",
                    category="credit_notes",
                    supplier_gstin=str(m.get("supplier_gstin") or ""),
                    supplier_name=None,
                    invoice_number=invn,
                    invoice_date=str(invd) if invd else None,
                    match_status="CREDIT_NOTE",
                    taxable_value_diff=0,
                    igst_diff=0,
                    cgst_diff=0,
                    sgst_diff=0,
                    total_tax_diff_paise=0,
                    decision_what=DecisionWhat.CREDIT_NOTE_ADJ,
                    decision_why=DecisionWhy.SUPPLIER_AMENDED,
                    decision_next=DecisionNext.NO_ACTION,
                    rule37_flag=r37f,
                    blocked_credit_flag=False,
                    late_filing_flag=False,
                    is_credit_note=True,
                    amount=_opt_int(m.get("total_tax_paise")),
                )
            )

    for m0 in list(engine.get("matched") or []):
        g_id, p_id = str(m0.get("gstr_id", "")), str(m0.get("pr_id", ""))
        gcell = gstr_m.get(g_id) or {}
        pcell = pr_m.get(p_id) or {}
        g, p = gcell.get("matcher") or {}, pcell.get("matcher") or {}
        g_rd = gcell.get("record_data") or {}
        sname = _gstr_name(g_rd) if g_rd else None
        invn = str(g.get("invoice_number_normalized") or p.get("invoice_number_normalized") or "")
        invd = g.get("invoice_date") or p.get("invoice_date")
        d_what, d_why, d_next, tvd, igd, cgd, sgd, ttd, mst = _mr_to_decisions(g, p)
        r37r = r37x.get(p_id, {})
        r37f = (r37r.get("status") or "") in _RULE37_CONCERNS
        _bpair = (
            str(g.get("supplier_gstin") or p.get("supplier_gstin") or "").strip().upper(),
            str(
                g.get("invoice_number_normalized")
                or p.get("invoice_number_normalized")
                or ""
            ).strip(),
        )
        bflag = _bpair in blocked_by_gstr
        lf_flag = g_id in late_filing_by_gstr
        rows.append(
            OutcomeRow(
                id=f"pm:{g_id}",
                category="matched",
                supplier_gstin=str(g.get("supplier_gstin") or p.get("supplier_gstin") or ""),
                supplier_name=sname,
                invoice_number=invn,
                invoice_date=str(invd) if invd else None,
                match_status=mst,
                taxable_value_diff=tvd,
                igst_diff=igd,
                cgst_diff=cgd,
                sgst_diff=sgd,
                total_tax_diff_paise=ttd,
                decision_what=d_what,
                decision_why=d_why,
                decision_next=d_next,
                rule37_flag=r37f,
                blocked_credit_flag=bflag,
                late_filing_flag=lf_flag,
                is_credit_note=False,
                amount=_opt_int(g.get("total_tax_paise")) if _opt_int(g.get("total_tax_paise")) is not None else _opt_int(p.get("total_tax_paise")),
                match_confidence=m0.get("match_confidence"),
                compared_fields=m0.get("compared_fields"),
            )
        )

    for mi in list(engine.get("missed_itc") or []):
        gid = str(mi.get("gstr_id", ""))
        gcell = gstr_m.get(gid) or {}
        g = gcell.get("matcher") or {}
        g_rd = gcell.get("record_data") or {}
        invn = str(
            mi.get("invoice_number_normalized")
            or g.get("invoice_number_normalized")
            or ""
        )
        invd = mi.get("invoice_date") or g.get("invoice_date")
        
        amt = _opt_int(mi.get("total_tax_paise"))
        if amt is None:
            amt = _opt_int(g.get("total_tax_paise"))

        rows.append(
            OutcomeRow(
                id=f"mi:{gid}",
                category="missed_itc",
                supplier_gstin=str(mi.get("supplier_gstin") or g.get("supplier_gstin") or ""),
                supplier_name=_gstr_name(g_rd),
                invoice_number=invn,
                invoice_date=str(invd) if invd else None,
                match_status="UNMATCHED",
                taxable_value_diff=0,
                igst_diff=0,
                cgst_diff=0,
                sgst_diff=0,
                total_tax_diff_paise=0,
                decision_what=DecisionWhat.MISSING_IN_BOOKS,
                decision_why=DecisionWhy.INVOICE_NOT_BOOKED,
                decision_next=DecisionNext.CLAIM_MISSED_ITC,
                rule37_flag=False,
                blocked_credit_flag=False,
                late_filing_flag=False,
                is_credit_note=False,
                amount=amt,
            )
        )

    for wr in list(engine.get("wrongful_itc_risk") or []):
        pid = str(wr.get("id", ""))
        pcell = pr_m.get(pid) or {}
        p = pcell.get("matcher") or {}
        rd = pcell.get("record_data") or {}
        invn = str(wr.get("invoice_number_normalized") or p.get("invoice_number_normalized") or "")
        invd = wr.get("invoice_date") or p.get("invoice_date")
        r37r = r37x.get(pid, {})
        r37f = (r37r.get("status") or "") in _RULE37_CONCERNS
        rows.append(
            OutcomeRow(
                id=f"wr:{pid}",
                category="wrongful_risk",
                supplier_gstin=str(wr.get("supplier_gstin") or p.get("supplier_gstin") or ""),
                supplier_name=None,
                invoice_number=invn,
                invoice_date=str(invd) if invd else None,
                match_status="UNMATCHED",
                taxable_value_diff=0,
                igst_diff=0,
                cgst_diff=0,
                sgst_diff=0,
                total_tax_diff_paise=0,
                decision_what=DecisionWhat.MISSING_IN_2B,
                decision_why=DecisionWhy.INVOICE_NOT_FILED,
                decision_next=DecisionNext.REVERSE_ITC,
                rule37_flag=r37f,
                blocked_credit_flag=False,
                late_filing_flag=False,
                is_credit_note=False,
                amount=_opt_int(wr.get("total_tax_paise")),
            )
        )

    for gm in list(engine.get("gstin_mismatch") or []):
        pid = str(gm.get("pr_id", ""))
        pcell = pr_m.get(pid) or {}
        p = pcell.get("matcher") or {}
        invn = str(
            gm.get("invoice_number_normalized")
            or p.get("invoice_number_normalized")
            or ""
        )
        invd = gm.get("invoice_date") or p.get("invoice_date")
        rows.append(
            OutcomeRow(
                id=f"gm:{pid}",
                category="gstin_mismatch",
                supplier_gstin=str(
                    gm.get("pr_supplier_gstin") or p.get("supplier_gstin") or ""
                ),
                pr_supplier_gstin=gm.get("pr_supplier_gstin"),
                gstr_supplier_gstin=gm.get("gstr_supplier_gstin"),
                supplier_name=None,
                invoice_number=invn,
                invoice_date=str(invd) if invd else None,
                match_status="REVIEW_REQUIRED",
                taxable_value_diff=0,
                igst_diff=0,
                cgst_diff=0,
                sgst_diff=0,
                total_tax_diff_paise=0,
                decision_what="Supplier GSTIN mismatch (possible typo)",
                decision_why=str(gm.get("reason") or "GSTIN_MISMATCH"),
                decision_next=(
                    "Correct the supplier GSTIN in the purchase register to match "
                    "GSTR-2B, then re-run. Do not claim ITC until it matches."
                ),
                rule37_flag=False,
                blocked_credit_flag=False,
                late_filing_flag=False,
                is_credit_note=False,
                amount=_opt_int(gm.get("total_tax_paise")),
            )
        )
    for dup in list(engine.get("duplicates") or []):
        side = dup.get("side")
        if not side:
            # Paired record
            gid = str(dup.get("gstr_id", ""))
            pid = str(dup.get("id", ""))
            g_cell = gstr_m.get(gid) or {}
            p_cell = pr_m.get(pid) or {}
            m_rec = g_cell.get("matcher") or p_cell.get("matcher") or {}
            sname = _gstr_name(g_cell.get("record_data") or {}) if g_cell.get("record_data") else None
            cid = f"rrp:{gid}-{pid}"
        elif side == "GSTR":
            rid = str(dup.get("gstr_id", ""))
            cell = gstr_m.get(rid) or {}
            m_rec = cell.get("matcher") or {}
            sname = _gstr_name(cell.get("record_data") or {}) if cell.get("record_data") else None
            cid = f"dg:{rid}"
        else:
            rid = str(dup.get("id", ""))
            cell = pr_m.get(rid) or {}
            m_rec = cell.get("matcher") or {}
            sname = None
            cid = f"dp:{rid}"
        
        invn = str(dup.get("invoice_number_normalized") or m_rec.get("invoice_number_normalized") or "")
        invd = dup.get("invoice_date") or m_rec.get("invoice_date")
        reason = str(dup.get("reason") or "DUPLICATE_CONFLICT")
        
        d_what = reason.replace("_", " ").title() if reason else "Manual Review Required"
        d_next = "Manual review required to verify correct pairing."
        
        rows.append(
            OutcomeRow(
                id=cid,
                category="review_required",
                supplier_gstin=str(dup.get("supplier_gstin") or m_rec.get("supplier_gstin") or ""),
                supplier_name=sname,
                invoice_number=invn,
                invoice_date=str(invd) if invd else None,
                match_status="REVIEW_REQUIRED",
                taxable_value_diff=0,
                igst_diff=0,
                cgst_diff=0,
                sgst_diff=0,
                total_tax_diff_paise=0,
                decision_what=d_what,
                decision_why=reason,
                decision_next=d_next,
                rule37_flag=False,
                blocked_credit_flag=False,
                late_filing_flag=False,
                is_credit_note=False,
                amount=_opt_int(dup.get("total_tax_paise")) if _opt_int(dup.get("total_tax_paise")) is not None else _opt_int(m_rec.get("total_tax_paise")),
                match_confidence=dup.get("match_confidence"),
                compared_fields=dup.get("compared_fields"),
            )
        )

    for de in list(engine.get("duplicate_entries") or []):
        pid = str(de.get("id") or "")
        pcell = pr_m.get(pid) or {}
        m_rec = pcell.get("matcher") or {}
        invn = str(
            de.get("invoice_number_normalized")
            or m_rec.get("invoice_number_normalized")
            or ""
        )
        invd = de.get("invoice_date") or m_rec.get("invoice_date")
        matched_pr_id = str(de.get("matched_pr_id") or "").strip() or None
        rows.append(
            OutcomeRow(
                id=f"de:{pid}",
                category="duplicate_entry",
                supplier_gstin=str(
                    de.get("supplier_gstin") or m_rec.get("supplier_gstin") or ""
                ),
                supplier_name=None,
                invoice_number=invn,
                invoice_date=str(invd) if invd else None,
                match_status="DUPLICATE_ENTRY",
                taxable_value_diff=0,
                igst_diff=0,
                cgst_diff=0,
                sgst_diff=0,
                total_tax_diff_paise=0,
                decision_what="Duplicate Entry — same invoice booked twice in books",
                decision_why=(
                    "Identical GSTIN + invoice appears more than once in the "
                    "purchase register"
                    + (
                        f"; canonical match is PR {matched_pr_id}"
                        if matched_pr_id
                        else ""
                    )
                ),
                decision_next=(
                    "Remove or mark the extra purchase-register row. Do not treat "
                    "this as missing from GSTR-2B or reverse ITC for it."
                ),
                rule37_flag=False,
                blocked_credit_flag=False,
                late_filing_flag=False,
                is_credit_note=False,
                amount=_opt_int(de.get("total_tax_paise"))
                if _opt_int(de.get("total_tax_paise")) is not None
                else _opt_int(m_rec.get("total_tax_paise")),
                matched_pr_id=matched_pr_id,
            )
        )

    for note in list(engine.get("unmatched_notes") or []):
        pid = str(note.get("id") or "")
        pcell = pr_m.get(pid) or {}
        m_rec = pcell.get("matcher") or {}
        rd = pcell.get("record_data") or {}
        note_no = str(
            note.get("note_number")
            or m_rec.get("note_number")
            or rd.get("note_number")
            or ""
        )
        invd = note.get("invoice_date") or m_rec.get("invoice_date")
        doc = str(
            note.get("document_type")
            or m_rec.get("doc_type")
            or rd.get("document_type")
            or "DEBIT_NOTE"
        ).strip().upper()
        amt = _opt_int(note.get("note_amount_paise"))
        if amt is None:
            amt = _opt_int(m_rec.get("note_amount_paise"))
        if amt is None:
            amt = _opt_int(rd.get("note_amount_paise"))
        rows.append(
            OutcomeRow(
                id=f"un:{pid}",
                category="unmatched_notes",
                supplier_gstin=str(
                    note.get("supplier_gstin")
                    or m_rec.get("supplier_gstin")
                    or ""
                ),
                supplier_name=(
                    str(note.get("supplier_name") or "").strip()
                    or str(rd.get("supplier_name") or "").strip()
                    or None
                ),
                invoice_number=note_no,
                invoice_date=str(invd) if invd else None,
                match_status=doc if doc in {"CREDIT_NOTE", "DEBIT_NOTE"} else "NOTE_NOT_MATCHED",
                taxable_value_diff=0,
                igst_diff=0,
                cgst_diff=0,
                sgst_diff=0,
                total_tax_diff_paise=0,
                decision_what="Notes — Not Matched",
                decision_why=(
                    f"{doc.replace('_', ' ').title()} from purchase register "
                    "(value adjustment). Full credit/debit note matching against "
                    "GSTR-2B note[] is not implemented yet."
                ),
                decision_next=(
                    "Review manually if needed. Do not treat as unclaimed ITC "
                    "or reverse ITC for this row."
                ),
                rule37_flag=False,
                blocked_credit_flag=False,
                late_filing_flag=False,
                is_credit_note=(doc == "CREDIT_NOTE"),
                amount=amt,
            )
        )

    for typo in list(engine.get("review_required_typo") or []):
        rid = str(typo.get("pr_id", ""))
        gstr_id = str(typo.get("gstr_id", ""))
        cell = pr_m.get(rid) or {}
        m_rec = cell.get("matcher") or {}
        invn = str(typo.get("gstr_raw_invoice") or m_rec.get("invoice_number_normalized") or "")
        invd = m_rec.get("invoice_date")
        reason = str(typo.get("reason") or "Invoice Number Typos / Mismatch")
        rows.append(
            OutcomeRow(
                id=f"rtp:{rid}-{gstr_id}",
                category="review_required",
                supplier_gstin=str(m_rec.get("supplier_gstin") or ""),
                supplier_name=None,
                invoice_number=invn,
                invoice_date=str(invd) if invd else None,
                match_status="REVIEW_REQUIRED",
                taxable_value_diff=0,
                igst_diff=0,
                cgst_diff=0,
                sgst_diff=0,
                total_tax_diff_paise=0,
                decision_what="Invoice Number Typo / Mismatch",
                decision_why=reason,
                decision_next="Manual review required to confirm if these are the same invoice.",
                rule37_flag=False,
                blocked_credit_flag=False,
                late_filing_flag=bool(typo.get("is_late_filing")),
                is_credit_note=False,
                amount=_opt_int(m_rec.get("total_tax_paise")),
                match_confidence=typo.get("match_confidence"),
                compared_fields=typo.get("compared_fields"),
            )
        )

    for pr_id, rrow in r37x.items():
        if (rrow.get("status") or "") not in _RULE37_CONCERNS:
            continue
        if any(x.id == f"r37:{pr_id}" for x in rows):
            continue
        pcell = pr_m.get(str(pr_id)) or {}
        p = pcell.get("matcher") or {}
        invn = str(rrow.get("invoice_number") or p.get("invoice_number_normalized") or "")
        invd = rrow.get("invoice_date") or p.get("invoice_date")
        rows.append(
            OutcomeRow(
                id=f"r37:{pr_id}",
                category="rule37_warnings",
                supplier_gstin=str(rrow.get("supplier_gstin") or p.get("supplier_gstin") or ""),
                supplier_name=None,
                invoice_number=invn,
                invoice_date=str(invd) if invd else None,
                match_status="RULE37",
                taxable_value_diff=0,
                igst_diff=0,
                cgst_diff=0,
                sgst_diff=0,
                total_tax_diff_paise=0,
                decision_what=DecisionWhat.RULE37_BREACH,
                decision_why=(
                    DecisionWhy.PAYMENT_NOT_MADE
                    if (rrow.get("status") or "") == "OVERDUE_UNPAID"
                    else DecisionWhy.SUPPLIER_AMENDED
                ),
                decision_next=DecisionNext.FOLLOW_UP_SUPPLIER,
                rule37_flag=True,
                blocked_credit_flag=False,
                late_filing_flag=False,
                is_credit_note=False,
                amount=_opt_int(rrow.get("itc_at_risk_paise")),
            )
        )

    for b in s175:
        bpair = _blocked_pair(b)
        gid = ""
        for candidate_id, gcell in gstr_m.items():
            gm = gcell.get("matcher") or {}
            gpair = (
                str(gm.get("supplier_gstin") or "").strip().upper(),
                str(gm.get("invoice_number_normalized") or "").strip(),
            )
            if gpair == bpair:
                gid = str(candidate_id)
                break
        if not gid:
            continue
        if any(
            x.id == f"bc:{gid}" and x.category == "blocked_credit" for x in rows
        ):
            continue
        gcell = gstr_m.get(gid) or {}
        g = gcell.get("matcher") or {}
        g_rd = gcell.get("record_data") or {}
        invn = str(b.get("invoice_number") or g.get("invoice_number_normalized") or "")
        invd = g.get("invoice_date")
        rows.append(
            OutcomeRow(
                id=f"bc:{gid}",
                category="blocked_credit",
                supplier_gstin=str(b.get("supplier_gstin") or g.get("supplier_gstin") or ""),
                supplier_name=_gstr_name(g_rd) if g_rd else None,
                invoice_number=invn,
                invoice_date=str(invd) if invd else None,
                match_status="ADVISORY",
                taxable_value_diff=0,
                igst_diff=0,
                cgst_diff=0,
                sgst_diff=0,
                total_tax_diff_paise=0,
                decision_what=DecisionWhat.BLOCKED_CREDIT,
                decision_why=DecisionWhy.INELIGIBLE_SECTION_17_5,
                decision_next=DecisionNext.NO_ACTION,
                rule37_flag=False,
                blocked_credit_flag=True,
                late_filing_flag=False,
                is_credit_note=False,
                amount=_opt_int(g.get("total_tax_paise")),
            )
        )

    # --- Counts
    ccounts: dict[str, int] = {k: 0 for k in [
        "matched",
        "missed_itc",
        "wrongful_risk",
        "rule37_warnings",
        "blocked_credit",
        "credit_notes",
        "gstin_mismatch",
        "review_required",
        "duplicate_entry",
        "unmatched_notes",
    ]}
    for r in rows:
        ccounts[r.category] = ccounts.get(r.category, 0) + 1

    n_g = len(gstr_m)
    n_p = len(pr_m)
    total_invoices = n_g + n_p
    # In 2B not in books = missed_itc; in books not in 2B = wrongful_risk
    missing_in_books = ccounts.get("missed_itc", 0)
    missing_in_2b = ccounts.get("wrongful_risk", 0)

    total_itc_gstr = sum(
        int((x.get("matcher") or {}).get("total_tax_paise") or 0)
        for x in gstr_m.values()
    )
    itc_missed = _sum_itc_paise_with_fallback(engine.get("missed_itc") or [], gstr_m)
    w_risk = sum(int(x.get("total_tax_paise") or 0) for x in (engine.get("wrongful_itc_risk") or []))


    matched_itc = 0
    for m0 in engine.get("matched") or []:
        g_id, p_id = str(m0.get("gstr_id", "")), str(m0.get("pr_id", ""))
        g = (gstr_m.get(g_id) or {}).get("matcher") or {}
        p = (pr_m.get(p_id) or {}).get("matcher") or {}
        matched_itc += min(
            int(g.get("total_tax_paise") or 0), int(p.get("total_tax_paise") or 0)
        )

    if n_g:
        mrp = round(100.0 * (len(engine.get("matched") or [])) / n_g, 2)
    else:
        mrp = 0.0
    net_claim = matched_itc - w_risk
    cnote_adj = (comp.get("credit_note_adjustment") or {}) if isinstance(
        comp.get("credit_note_adjustment"), dict
    ) else {}
    if isinstance(cnote_adj, dict) and cnote_adj.get("net_itc_paise") is not None:
        # Prefer engine-computed net where present
        try:
            net_claim = int(cnote_adj["net_itc_paise"])
        except (TypeError, ValueError):
            pass

    money = {
        "total_itc_in_gstr_paise": total_itc_gstr,
        "matched_itc_paise": matched_itc,
        "missed_itc_paise": itc_missed,
        "wrongful_risk_paise": w_risk,
        "net_claimable_itc_paise": max(net_claim, 0) if net_claim is not None else 0,
        "match_rate_percent": mrp,
    }

    r37_warn_n = len(
        [
            x
            for x in (comp.get("rule37") or [])
            if (x.get("status") or "") in _RULE37_CONCERNS
        ]
    )
    result = (
        rows,
        ccounts,
        {
            "total_invoices": total_invoices,
            "matched_count": len(engine.get("matched") or []),
            "missing_in_2b_count": missing_in_2b,
            "missing_in_books_count": missing_in_books,
            "rule37_warnings_count": r37_warn_n,
            "blocked_credit_count": ccounts.get("blocked_credit", 0),
            "late_filing_count": len(late_filing),
            **money,
        },
    )
    cache[ck] = result
    return result


load_gstr_map = _load_gstr_map
load_pr_map = _load_pr_map


import gzip
import base64

def _decode_if_compressed(data: Any) -> Any:
    if isinstance(data, str) and not data.strip().startswith(("{", "[")):
        try:
            return json.loads(gzip.decompress(base64.b64decode(data)).decode("utf-8"))
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to decompress payload: {e}")
            pass
    return data

def _merge_payload_blobs(record_data: Any, payload: Any) -> dict[str, Any]:
    payload = _decode_if_compressed(payload)
    if isinstance(payload, dict) and payload:
        return payload
    if isinstance(payload, str) and payload.strip().startswith(("{", "[")):
        try:
            d = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            d = None
        if isinstance(d, dict) and d:
            return d
            
    record_data = _decode_if_compressed(record_data)
    if isinstance(record_data, dict) and record_data:
        return record_data
    if isinstance(record_data, str) and record_data.strip().startswith(("{", "[")):
        try:
            d = json.loads(record_data)
        except (json.JSONDecodeError, TypeError):
            return {}
        return d if isinstance(d, dict) else {}
    return {}


def load_payload(sb: Client, run_id: str) -> dict[str, Any]:
    cache = _req_cache()
    ck = f"payload:{run_id}"
    hit = cache.get(ck)
    if hit is not None:
        return hit
    r = (
        sb.table("reconciliation_results")
        .select("record_data, payload")
        .eq("run_id", run_id)
        .limit(1)
        .execute()
    )
    if not r.data:
        out: dict[str, Any] = {}
    else:
        row = r.data[0]
        out = _merge_payload_blobs(row.get("record_data"), row.get("payload"))
    cache[ck] = out
    return out


def matched_itc_paise_from_payload(
    sb: Client, run_id: str, payload: dict[str, Any] | None = None
) -> int:
    """Sum matched ITC (paise) from engine pairs — used to backfill run_summary."""
    p = payload if isinstance(payload, dict) else load_payload(sb, run_id)
    if not p:
        return 0
    engine = p.get("engine") or {}
    if not isinstance(engine, dict):
        return 0
    gstr_m = load_gstr_map(sb, run_id)
    pr_m = load_pr_map(sb, run_id)
    matched_itc = 0
    for m0 in engine.get("matched") or []:
        if not isinstance(m0, dict):
            continue
        g_id, p_id = str(m0.get("gstr_id", "")), str(m0.get("pr_id", ""))
        g = (gstr_m.get(g_id) or {}).get("matcher") or {}
        pr = (pr_m.get(p_id) or {}).get("matcher") or {}
        matched_itc += min(
            int(g.get("total_tax_paise") or 0), int(pr.get("total_tax_paise") or 0)
        )
    return int(matched_itc)


def filter_invoices(
    rows: list[OutcomeRow],
    category: str,
    supplier_gstin: str | None,
    invoice_search: str | None,
    min_amount_paise: int | None,
    max_amount_paise: int | None,
    date_from: date | None,
    date_to: date | None,
) -> list[OutcomeRow]:
    out = [x for x in rows if x.category == category]
    if supplier_gstin:
        sg = supplier_gstin.strip().upper()
        out = [x for x in out if (x.supplier_gstin or "").upper() == sg]
    if invoice_search:
        q = invoice_search.strip().lower()
        out = [x for x in out if q in (x.invoice_number or "").lower()]
    if min_amount_paise is not None:
        out = [
            x
            for x in out
            if abs(int(x.total_tax_diff_paise)) >= min_amount_paise
        ]
    if max_amount_paise is not None:
        out = [
            x
            for x in out
            if abs(int(x.total_tax_diff_paise)) <= max_amount_paise
        ]
    if date_from is not None:
        out = [
            x
            for x in out
            if parse_optional_date(x.invoice_date)
            and parse_optional_date(x.invoice_date) >= date_from
        ]
    if date_to is not None:
        out = [
            x
            for x in out
            if parse_optional_date(x.invoice_date)
            and parse_optional_date(x.invoice_date) <= date_to
        ]
    return out


TItem = TypeVar("TItem")


def paginate(items: List[TItem], page: int, page_size: int) -> Tuple[List[TItem], int]:
    total = len(items)
    p = max(1, page)
    ps = min(200, max(1, page_size))
    start = (p - 1) * ps
    return items[start : start + ps], total


# Match confidence badge thresholds (same as step-1 UI): ≥90% high, ≥75% medium.
CONFIDENCE_HIGH_MIN = 0.90
CONFIDENCE_MEDIUM_MIN = 0.75


def _normalize_match_confidence(raw: Any) -> Optional[float]:
    """Return similarity in [0, 1], or None when absent / unparsable."""
    if raw is None:
        return None
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return None
    # Tolerate accidental 0–100 storage without changing engine writes.
    if score > 1.0:
        score = score / 100.0
    return score


def confidence_bucket(match_confidence: Any, *, linked: bool) -> str:
    """Map a per-invoice score to high / medium / low / unmatched.

    Linked rows with no fuzzy score (L1–L4 exact) count as high. Unmatched
    invoices are never folded into low confidence.
    """
    if not linked:
        return "unmatched"
    score = _normalize_match_confidence(match_confidence)
    if score is None:
        return "high"
    if score >= CONFIDENCE_HIGH_MIN:
        return "high"
    if score >= CONFIDENCE_MEDIUM_MIN:
        return "medium"
    return "low"


def build_confidence_summary(
    run_id: str,
    outcome_rows: list[OutcomeRow],
) -> dict[str, Any]:
    """Aggregate run-level confidence buckets from outcome rows (read-only).

    Counts GSTR-side invoices only: matched + review_required (excluding PR
    marker ``dp:`` rows) + missed_itc. Buckets always sum to ``total_invoices``.
    """
    high = medium = low = unmatched = 0
    for row in outcome_rows:
        cat = row.category
        rid = str(row.id)
        if cat == "matched":
            bucket = confidence_bucket(row.match_confidence, linked=True)
        elif cat == "review_required":
            if rid.startswith("dp:"):
                continue
            bucket = confidence_bucket(row.match_confidence, linked=True)
        elif cat == "missed_itc":
            bucket = "unmatched"
        else:
            continue

        if bucket == "high":
            high += 1
        elif bucket == "medium":
            medium += 1
        elif bucket == "low":
            low += 1
        else:
            unmatched += 1

    total = high + medium + low + unmatched
    return {
        "run_id": str(run_id),
        "total_invoices": total,
        "high_confidence": high,
        "medium_confidence": medium,
        "low_confidence": low,
        "unmatched": unmatched,
    }


def _abs_tax_components(ig: int, cg: int, sg: int) -> int:
    return abs(int(ig)) + abs(int(cg)) + abs(int(sg))


def compare_runs_simple(
    pl1: dict[str, Any],
    pl2: dict[str, Any],
    g1: dict[str, dict], g2: dict[str, dict], p1: dict[str, dict], p2: dict[str, dict],
    period: str, client_gstin: str, run1_id: str, run2_id: str,
) -> dict[str, Any]:
    def status_and_components(
        k: tuple[str, str], eng: dict, gmap: dict, pmap: dict
    ) -> tuple[str, int, int, int, int]:
        gst, inv = k
        for m in eng.get("matched") or []:
            gid, _pid = str(m.get("gstr_id", "")), str(m.get("pr_id", ""))
            g = (gmap.get(gid) or {}).get("matcher") or {}
            if g.get("supplier_gstin", "").upper() == gst and (
                (g.get("invoice_number_normalized") or "").lower() == inv
            ):
                return (
                    "MATCHED",
                    int(g.get("total_tax_paise") or 0),
                    int(g.get("igst_paise") or 0),
                    int(g.get("cgst_paise") or 0),
                    int(g.get("sgst_paise") or 0),
                )
        for m in eng.get("missed_itc") or []:
            gid = str(m.get("gstr_id", ""))
            g = (gmap.get(gid) or {}).get("matcher") or {}
            if g.get("supplier_gstin", "").upper() == gst and (
                (g.get("invoice_number_normalized") or "").lower() == inv
            ):
                tt = int(m.get("total_tax_paise") or g.get("total_tax_paise") or 0)
                return (
                    "NON_MATCHED",
                    tt,
                    int(g.get("igst_paise") or 0),
                    int(g.get("cgst_paise") or 0),
                    int(g.get("sgst_paise") or 0),
                )
        for m in eng.get("wrongful_itc_risk") or []:
            pid = str(m.get("id", ""))
            p = (pmap.get(pid) or {}).get("matcher") or {}
            if p.get("supplier_gstin", "").upper() == gst and (
                (p.get("invoice_number_normalized") or "").lower() == inv
            ):
                tt = int(m.get("total_tax_paise") or p.get("total_tax_paise") or 0)
                return (
                    "NON_MATCHED",
                    tt,
                    int(p.get("igst_paise") or 0),
                    int(p.get("cgst_paise") or 0),
                    int(p.get("sgst_paise") or 0),
                )
        return "UNKNOWN", 0, 0, 0, 0

    def reason_amount_changed(
        t1: int, t2: int, ig1: int, cg1: int, sg1: int, ig2: int, cg2: int, sg2: int
    ) -> str:
        a1, a2 = _abs_tax_components(ig1, cg1, sg1), _abs_tax_components(ig2, cg2, sg2)
        if a2 < a1:
            return ChangeReason.BOOKS_CORRECTED
        if a2 > a1:
            return ChangeReason.SUPPLIER_AMENDED
        if t2 < t1:
            return ChangeReason.BOOKS_CORRECTED
        if t2 > t1:
            return ChangeReason.SUPPLIER_AMENDED
        return ChangeReason.UNKNOWN

    e1, e2 = pl1.get("engine") or {}, pl2.get("engine") or {}
    keys: set[tuple[str, str]] = set()
    for m in e1.get("matched") or []:
        gid = str(m.get("gstr_id", ""))
        g = (g1.get(gid) or {}).get("matcher") or {}
        keys.add(
            (
                str(g.get("supplier_gstin", "")).upper(),
                (g.get("invoice_number_normalized") or "").lower(),
            )
        )
    for m in e1.get("missed_itc") or []:
        gid = str(m.get("gstr_id", ""))
        g = (g1.get(gid) or {}).get("matcher") or {}
        keys.add(
            (str(g.get("supplier_gstin", "")).upper(), (g.get("invoice_number_normalized") or "").lower())
        )
    for m in e1.get("wrongful_itc_risk") or []:
        pid = str(m.get("id", ""))
        p = (p1.get(pid) or {}).get("matcher") or {}
        keys.add(
            (str(p.get("supplier_gstin", "")).upper(), (p.get("invoice_number_normalized") or "").lower())
        )
    for m in e2.get("matched") or []:
        gid = str(m.get("gstr_id", ""))
        g = (g2.get(gid) or {}).get("matcher") or {}
        keys.add(
            (str(g.get("supplier_gstin", "")).upper(), (g.get("invoice_number_normalized") or "").lower())
        )
    for m in e2.get("missed_itc") or []:
        gid = str(m.get("gstr_id", ""))
        g = (g2.get(gid) or {}).get("matcher") or {}
        keys.add(
            (str(g.get("supplier_gstin", "")).upper(), (g.get("invoice_number_normalized") or "").lower())
        )
    for m in e2.get("wrongful_itc_risk") or []:
        pid = str(m.get("id", ""))
        p = (p2.get(pid) or {}).get("matcher") or {}
        keys.add(
            (str(p.get("supplier_gstin", "")).upper(), (p.get("invoice_number_normalized") or "").lower())
        )

    new_matched = 0
    newly_unmatched = 0
    amount_changed = 0
    itc_net = 0
    out_rows: list[dict] = []
    for k0 in keys:
        s1, t1, ig1, cg1, sg1 = status_and_components(k0, e1, g1, p1)
        s2, t2, ig2, cg2, sg2 = status_and_components(k0, e2, g2, p2)
        m1 = s1 == "MATCHED"
        m2 = s2 == "MATCHED"
        if s1 == "UNKNOWN" and s2 == "UNKNOWN":
            continue
        ch = t2 - t1
        if (not m1) and m2:
            new_matched += 1
            cr = (
                ChangeReason.NEW_INVOICE_ADDED
                if t1 == 0 and t2
                else ChangeReason.BOOKS_CORRECTED
            )
            out_rows.append(
                {
                    "invoice_number": k0[1],
                    "supplier_gstin": k0[0],
                    "run1_status": s1,
                    "run2_status": s2,
                    "run1_total_tax_paise": t1,
                    "run2_total_tax_paise": t2,
                    "tax_change_paise": ch,
                    "change_type": "newly_matched",
                    "change_reason": cr,
                }
            )
            itc_net += ch
        elif m1 and (not m2):
            newly_unmatched += 1
            cr = (
                ChangeReason.INVOICE_REMOVED
                if t2 == 0
                else ChangeReason.SUPPLIER_AMENDED
            )
            out_rows.append(
                {
                    "invoice_number": k0[1],
                    "supplier_gstin": k0[0],
                    "run1_status": s1,
                    "run2_status": s2,
                    "run1_total_tax_paise": t1,
                    "run2_total_tax_paise": t2,
                    "tax_change_paise": ch,
                    "change_type": "newly_unmatched",
                    "change_reason": cr,
                }
            )
            itc_net += ch
        elif m1 and m2 and t1 != t2:
            amount_changed += 1
            itc_net += ch
            cr = reason_amount_changed(t1, t2, ig1, cg1, sg1, ig2, cg2, sg2)
            out_rows.append(
                {
                    "invoice_number": k0[1],
                    "supplier_gstin": k0[0],
                    "run1_status": s1,
                    "run2_status": s2,
                    "run1_total_tax_paise": t1,
                    "run2_total_tax_paise": t2,
                    "tax_change_paise": ch,
                    "change_type": "amount_changed",
                    "change_reason": cr,
                }
            )
        elif (not m1) and (not m2) and t1 != t2 and s1 == s2:
            amount_changed += 1
            itc_net += ch
            if t2 < t1 and s1 == "NON_MATCHED":
                cr = ChangeReason.PAYMENT_MADE
            else:
                cr = reason_amount_changed(
                    t1, t2, ig1, cg1, sg1, ig2, cg2, sg2
                )
            out_rows.append(
                {
                    "invoice_number": k0[1],
                    "supplier_gstin": k0[0],
                    "run1_status": s1,
                    "run2_status": s2,
                    "run1_total_tax_paise": t1,
                    "run2_total_tax_paise": t2,
                    "tax_change_paise": ch,
                    "change_type": "amount_changed",
                    "change_reason": cr,
                }
            )
    improvement = new_matched > newly_unmatched
    rupee = itc_net / 100.0
    sign = "improved" if itc_net >= 0 else "decreased"
    summ = (
        f"{new_matched} invoices newly matched; {newly_unmatched} no longer match; "
        f"{amount_changed} amount changes; net ITC {sign} by ₹{abs(rupee):,.0f} vs previous run"
    )
    return {
        "run_id_1": run1_id,
        "run_id_2": run2_id,
        "period": period,
        "client_gstin": client_gstin,
        "new_matched_count": new_matched,
        "newly_unmatched_count": newly_unmatched,
        "amount_changed_count": amount_changed,
        "itc_difference_paise": itc_net,
        "improvement": improvement,
        "summary": summ,
        "invoices": out_rows,
    }
