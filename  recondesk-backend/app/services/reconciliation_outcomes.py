"""Build API-facing reconciliation stats and invoice rows from run payload + DB rows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, List, Optional, Tuple, TypeVar

from supabase import Client

from app.constants import ChangeReason, DecisionNext, DecisionWhat, DecisionWhy
from app.services import reconciliation_record_adapter as rec_adapt
from app.services.credit_note_handler import classify_document
from app.services.matcher import TOTAL_TOLERANCE_PAISE, match_gstr_to_pr

# Rule 37 statuses that surface as “warnings / flag”
RULE37_CONCERNS = frozenset(
    {
        "PAID_LATE",
        "OVERDUE_UNPAID",
        "WARNING_30_DAYS",
        "WARNING_60_DAYS",
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


def _load_gstr_map(sb: Client, run_id: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    off = 0
    while True:
        r = (
            sb.table("gstr_records")
            .select("id, record_data")
            .eq("run_id", run_id)
            .range(off, off + 1999)
            .execute()
        )
        rows = r.data or []
        for row in rows:
            out[str(row["id"])] = {
                "matcher": rec_adapt.gstr_db_row_to_matcher_row(row),
                "record_data": row.get("record_data") or {},
            }
        if len(rows) < 2000:
            break
        off += 2000
    return out


def _load_pr_map(sb: Client, run_id: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    off = 0
    while True:
        r = (
            sb.table("pr_records")
            .select("id, record_data")
            .eq("run_id", run_id)
            .range(off, off + 1999)
            .execute()
        )
        rows = r.data or []
        for row in rows:
            out[str(row["id"])] = {
                "matcher": rec_adapt.pr_db_row_to_matcher_row(row),
                "record_data": row.get("record_data") or {},
            }
        if len(rows) < 2000:
            break
        off += 2000
    return out


@dataclass
class OutcomeRow:
    """Single invoice line for the public API (before pagination)."""

    id: str
    category: str
    supplier_gstin: str
    supplier_name: Optional[str]
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
    is_credit_note: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "supplier_gstin": self.supplier_gstin,
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
            "is_credit_note": self.is_credit_note,
        }


def _mr_to_decisions(
    g: dict[str, Any], p: dict[str, Any]
) -> tuple[str, str, str, int, int, int, int, int, str]:
    """Return enums + diffs; match_status MATCHED or MISMATCHED."""
    mr = match_gstr_to_pr(g, [p])
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
    if mr is None:
        return (
            DecisionWhat.MISMATCH_AMOUNT,
            DecisionWhy.GSTR_AMOUNT_HIGHER,
            DecisionNext.FOLLOW_UP_SUPPLIER,
            tvd,
            igd,
            cgd,
            sgd,
            ttd,
            "MISMATCHED",
        )
    d_what = DecisionWhat.MISMATCH_AMOUNT
    d_why = (
        DecisionWhy.GSTR_AMOUNT_HIGHER
        if g_tt > p_tt
        else DecisionWhy.BOOKS_AMOUNT_HIGHER
    )
    d_next = (
        DecisionNext.FOLLOW_UP_SUPPLIER
        if (abs(tvd) > TOTAL_TOLERANCE_PAISE or abs(ttd) > TOTAL_TOLERANCE_PAISE)
        else DecisionNext.NO_ACTION
    )
    st = "MATCHED" if (abs(tvd) <= TOTAL_TOLERANCE_PAISE and abs(ttd) <= TOTAL_TOLERANCE_PAISE) else "MISMATCHED"
    if abs(tvd) >= abs(ttd) and abs(tvd) > TOTAL_TOLERANCE_PAISE:
        d_what = DecisionWhat.MISMATCH_TAXABLE_VALUE
    if st == "MATCHED":
        d_next = DecisionNext.NO_ACTION
    return (d_what, d_why, d_next, tvd, igd, cgd, sgd, ttd, st)


def _rule37_index(rule37: list[dict]) -> dict[str, dict]:
    return {str(x.get("pr_id")): x for x in rule37 if x.get("pr_id") is not None}


def _blocked_index(blocked: list[dict]) -> set[str]:
    s: set[str] = set()
    for x in blocked:
        k = str(x.get("invoice_id", "")) or str(x.get("gstr_id", ""))
        if k:
            s.add(k)
    return s


def build_outcome_rows(
    sb: Client,
    run_id: str,
    payload: dict[str, Any],
) -> tuple[list[OutcomeRow], dict[str, int], dict[str, Any]]:
    """Load maps, merge engine+compliance, return rows + category counts + money stats."""
    engine = payload.get("engine") or {}
    comp = payload.get("compliance") or {}
    gstr_m = _load_gstr_map(sb, run_id)
    pr_m = _load_pr_map(sb, run_id)
    r37x = _rule37_index(list(comp.get("rule37") or []))
    s175 = list(comp.get("section_17_5") or comp.get("section_175") or [])
    blocked_by_gstr = _blocked_index(s175)

    rows: list[OutcomeRow] = []

    for pid, pr in pr_m.items():
        m = pr["matcher"]
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
                    is_credit_note=True,
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
        bflag = (g_id in blocked_by_gstr) or (str(m0.get("id", g_id)) in blocked_by_gstr)
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
                is_credit_note=False,
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
                is_credit_note=False,
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
                is_credit_note=False,
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
                is_credit_note=False,
            )
        )

    for b in s175:
        gid = str(b.get("invoice_id") or b.get("gstr_id") or "")
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
                is_credit_note=False,
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
    ]}
    for r in rows:
        ccounts[r.category] = ccounts.get(r.category, 0) + 1

    n_g = len(gstr_m)
    n_p = len(pr_m)
    total_invoices = n_g + n_p
    mis_n = len(
        [r for r in rows if r.category == "matched" and r.match_status == "MISMATCHED"]
    )
    # In 2B not in books = missed_itc; in books not in 2B = wrongful_risk
    missing_in_books = ccounts.get("missed_itc", 0)
    missing_in_2b = ccounts.get("wrongful_risk", 0)

    total_itc_gstr = sum(
        int((x.get("matcher") or {}).get("total_tax_paise") or 0)
        for x in gstr_m.values()
    )
    itc_missed = sum(
        int(x.get("total_tax_paise") or 0) for x in (engine.get("missed_itc") or [])
    )
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
    return rows, ccounts, {
        "total_invoices": total_invoices,
        "matched_count": len(engine.get("matched") or []),
        "mismatched_count": mis_n,
        "missing_in_2b_count": missing_in_2b,
        "missing_in_books_count": missing_in_books,
        "rule37_warnings_count": r37_warn_n,
        "blocked_credit_count": ccounts.get("blocked_credit", 0),
        **money,
    }


load_gstr_map = _load_gstr_map
load_pr_map = _load_pr_map


def load_payload(sb: Client, run_id: str) -> dict[str, Any]:
    r = (
        sb.table("reconciliation_results")
        .select("payload")
        .eq("run_id", run_id)
        .limit(1)
        .execute()
    )
    if not r.data:
        return {}
    p = r.data[0].get("payload")
    return p if isinstance(p, dict) else {}


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
