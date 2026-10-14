"""Firm-scoped vendor compliance scorecard — precomputed summary.

Refresh strategy (safe at scale):
  - On run complete: rebuild *this client's* contribution from its latest run
    per period only, then roll up affected suppliers into the firm summary.
  - Daily (throttled): full rebuild for drift correction.

Recomputing firm-wide counters for every shared supplier on each run would
decompress all firm payloads (e.g. 30+ clients × N periods) per completion —
too heavy. Per-client contribution + rollup stays O(client periods).

Checksum-valid GSTINs only (``normalize_gstin``). Invalid/typo GSTINs are
excluded, never silently merged. No non-filer signal is claimed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Optional

from supabase import Client

from app.constants import RunStatus
from app.services.firm_access import get_firm_owner_for_client
from app.services.normalizer import NormalizationError, normalize_gstin
from app.services.reconciliation_outcomes import load_payload

_log = logging.getLogger(__name__)

_OPEN_RULE37 = frozenset(
    {
        "OVERDUE_UNPAID",
        "WARNING_30_DAYS",
        "WARNING_60_DAYS",
        "PENDING_VERIFICATION",
    }
)

_MISMATCH_BUCKETS = (
    "missed_itc",
    "wrongful_itc_risk",
    "gstin_mismatch",
    "duplicates",
    "duplicate_entries",
    "review_required_typo",
)

_RUN_STATUSES = (RunStatus.COMPLETED, RunStatus.FINAL)

_SCORECARD_MIN_INTERVAL = timedelta(hours=24)
_last_rebuild_at: datetime | None = None

SIGNAL_NOTES = {
    "pr_only_count": (
        "Invoices in books but not in GSTR-2B (PR_ONLY). "
        "Not a non-filer determination."
    ),
    "quarterly_filer_flag": (
        "Supplier marked quarterly filer on at least one GSTR-2B invoice "
        "(QUARTERLY_FILER risk)."
    ),
    "late_filing_rate": (
        "Share of invoices flagged via supplier GSTR-1 filing date "
        "(supfildt) after the due date."
    ),
    "non_filer": (
        "No non-filer / Rule 37A signal is computed. "
        "Use PR_ONLY, QUARTERLY_FILER, and late_filing proxies only."
    ),
}


@dataclass
class SupplierClientCounters:
    supplier_gstin: str
    trade_name: str = ""
    invoice_keys: set[str] = field(default_factory=set)
    mismatch_keys: set[str] = field(default_factory=set)
    rule37_open_count: int = 0
    rule37_at_risk_paise: int = 0
    rule37a_risk_count: int = 0
    rule37a_risk_paise: int = 0
    section_17_5_count: int = 0
    late_filing_count: int = 0
    pr_only_count: int = 0
    quarterly_filer_flag: bool = False

    def merge(self, other: "SupplierClientCounters") -> None:
        if other.trade_name and (
            not self.trade_name or len(other.trade_name) > len(self.trade_name)
        ):
            self.trade_name = other.trade_name
        self.invoice_keys |= other.invoice_keys
        self.mismatch_keys |= other.mismatch_keys
        self.rule37_open_count += other.rule37_open_count
        self.rule37_at_risk_paise += other.rule37_at_risk_paise
        self.rule37a_risk_count += other.rule37a_risk_count
        self.rule37a_risk_paise += other.rule37a_risk_paise
        self.section_17_5_count += other.section_17_5_count
        self.late_filing_count += other.late_filing_count
        self.pr_only_count += other.pr_only_count
        self.quarterly_filer_flag = (
            self.quarterly_filer_flag or other.quarterly_filer_flag
        )


def try_normalize_supplier_gstin(raw: Any) -> Optional[str]:
    """Return checksum-valid normalized GSTIN, or None (exclude from scorecard)."""
    try:
        return normalize_gstin(raw)
    except NormalizationError:
        return None
    except Exception:
        return None


def compute_risk_score(
    *,
    rule37_open_count: int,
    section_17_5_count: int,
    mismatch_rate: float,
    late_filing_rate: float,
    quarterly_filer_flag: bool,
    pr_only_count: int,
    rule37a_risk_count: int = 0,
) -> int:
    score = (
        rule37_open_count * 10
        + rule37a_risk_count * 15
        + section_17_5_count * 5
        + int(mismatch_rate * 40)
        + int(late_filing_rate * 20)
        + (15 if quarterly_filer_flag else 0)
        + min(int(pr_only_count), 10)
    )
    return max(0, min(100, score))


def compute_risk_tier(score: int) -> str:
    """Classify supplier compliance risk score (0-100) into actionable risk tiers."""
    if score <= 25:
        return "LOW_RISK"
    if score <= 50:
        return "MEDIUM_RISK"
    if score <= 75:
        return "HIGH_RISK"
    return "CRITICAL_RISK"


def _rate(numer: int, denom: int) -> Decimal:
    if denom <= 0:
        return Decimal("0.0000")
    return (Decimal(numer) / Decimal(denom)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def _invoice_key(gstin: str, invoice_number: Any, invoice_date: Any) -> str:
    inv = str(invoice_number or "").strip().upper()
    idt = str(invoice_date or "").strip()[:10]
    return f"{gstin}|{inv}|{idt}"


def _gstin_from_row(row: dict[str, Any], *keys: str) -> Optional[str]:
    for k in keys:
        g = try_normalize_supplier_gstin(row.get(k))
        if g:
            return g
    return None


def _ensure_counter(
    by_gstin: dict[str, SupplierClientCounters], gstin: str
) -> SupplierClientCounters:
    c = by_gstin.get(gstin)
    if c is None:
        c = SupplierClientCounters(supplier_gstin=gstin)
        by_gstin[gstin] = c
    return c


def extract_supplier_counters_from_payload(
    payload: dict[str, Any],
    *,
    record_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, SupplierClientCounters]:
    """Pure extract: payload (+ optional pr/gstr id index) → per-supplier counters.

    ``record_index`` maps ``pr:<id>`` / ``gstr:<id>`` →
    ``{supplier_gstin, invoice_number, invoice_date, supplier_name}``.
    Needed because slimmed ``engine.matched`` omits supplier_gstin.
    """
    by_gstin: dict[str, SupplierClientCounters] = {}
    engine = payload.get("engine") if isinstance(payload.get("engine"), dict) else {}
    comp = (
        payload.get("compliance") if isinstance(payload.get("compliance"), dict) else {}
    )
    idx = record_index or {}

    def _resolve_from_ids(row: dict[str, Any]) -> tuple[Optional[str], str, str, str]:
        for side, key in (("gstr", "gstr_id"), ("pr", "pr_id"), ("pr", "id")):
            rid = str(row.get(key) or "").strip()
            if not rid:
                continue
            meta = idx.get(f"{side}:{rid}")
            if not meta:
                continue
            g = try_normalize_supplier_gstin(meta.get("supplier_gstin"))
            if not g:
                continue
            return (
                g,
                str(meta.get("invoice_number") or "").strip(),
                str(meta.get("invoice_date") or "").strip()[:10],
                str(meta.get("supplier_name") or "").strip(),
            )
        return None, "", "", ""

    # Matched (need id lookup for GSTIN)
    for row in engine.get("matched") or []:
        if not isinstance(row, dict):
            continue
        g = _gstin_from_row(row, "supplier_gstin", "gstr_supplier_gstin", "pr_supplier_gstin")
        inv = str(
            row.get("invoice_number_normalized") or row.get("invoice_number") or ""
        ).strip()
        idt = str(row.get("invoice_date") or "").strip()[:10]
        name = str(row.get("supplier_name") or "").strip()
        if not g:
            g, inv2, idt2, name2 = _resolve_from_ids(row)
            inv = inv or inv2
            idt = idt or idt2
            name = name or name2
        if not g:
            continue
        if not inv and not idt:
            # Stable fallback so matched rows still count once
            gid = str(row.get("gstr_id") or row.get("pr_id") or "").strip()
            inv = f"id:{gid}" if gid else "unknown"
        c = _ensure_counter(by_gstin, g)
        if name:
            c.trade_name = name
        c.invoice_keys.add(_invoice_key(g, inv, idt))

    # Mismatch buckets
    for bucket in _MISMATCH_BUCKETS:
        for row in engine.get(bucket) or []:
            if not isinstance(row, dict):
                continue
            candidates: list[str] = []
            if bucket == "gstin_mismatch":
                for k in ("gstr_supplier_gstin", "pr_supplier_gstin", "supplier_gstin"):
                    gg = try_normalize_supplier_gstin(row.get(k))
                    if gg and gg not in candidates:
                        candidates.append(gg)
            else:
                g = _gstin_from_row(
                    row,
                    "supplier_gstin",
                    "gstr_supplier_gstin",
                    "pr_supplier_gstin",
                )
                if not g:
                    g, _, _, _ = _resolve_from_ids(row)
                if g:
                    candidates.append(g)
            inv = str(
                row.get("invoice_number_normalized") or row.get("invoice_number") or ""
            ).strip()
            idt = str(row.get("invoice_date") or "").strip()[:10]
            risk_reason = str(row.get("risk_reason") or "").strip().upper()
            for g in candidates:
                c = _ensure_counter(by_gstin, g)
                key = _invoice_key(g, inv or row.get("id") or row.get("gstr_id"), idt)
                c.invoice_keys.add(key)
                c.mismatch_keys.add(key)
                if bucket == "wrongful_itc_risk":
                    if risk_reason == "PR_ONLY":
                        c.pr_only_count += 1
                    elif risk_reason == "QUARTERLY_FILER":
                        c.quarterly_filer_flag = True

    # Rule 37 (status-only open set; settlements not required for MVP)
    for key in ("rule37", "rule37_pending_verification"):
        for row in comp.get(key) or []:
            if not isinstance(row, dict):
                continue
            st = str(row.get("status") or "").strip().upper()
            if st not in _OPEN_RULE37:
                continue
            g = _gstin_from_row(row, "supplier_gstin")
            if not g:
                continue
            c = _ensure_counter(by_gstin, g)
            inv = str(row.get("invoice_number") or "").strip()
            idt = str(row.get("invoice_date") or "").strip()[:10]
            c.invoice_keys.add(_invoice_key(g, inv or row.get("pr_id"), idt))
            c.rule37_open_count += 1
            at_risk = row.get("itc_at_risk_paise")
            if at_risk is None:
                at_risk = row.get("potential_itc_paise")
            try:
                c.rule37_at_risk_paise += int(at_risk or 0)
            except (TypeError, ValueError):
                pass

    for row in comp.get("section_17_5") or []:
        if not isinstance(row, dict):
            continue
        g = _gstin_from_row(row, "supplier_gstin")
        if not g:
            continue
        c = _ensure_counter(by_gstin, g)
        inv = str(row.get("invoice_number") or "").strip()
        idt = str(row.get("invoice_date") or "").strip()[:10]
        c.invoice_keys.add(_invoice_key(g, inv, idt))
        c.section_17_5_count += 1
        name = str(row.get("supplier_name") or "").strip()
        if name:
            c.trade_name = name

    for row in comp.get("late_filing") or []:
        if not isinstance(row, dict):
            continue
        g = _gstin_from_row(row, "supplier_gstin")
        if not g:
            continue
        c = _ensure_counter(by_gstin, g)
        inv = str(
            row.get("invoice_number") or row.get("invoice_number_normalized") or ""
        ).strip()
        idt = str(row.get("invoice_date") or "").strip()[:10]
        c.invoice_keys.add(_invoice_key(g, inv, idt))
        c.late_filing_count += 1

    return by_gstin


def counters_to_row_dict(
    c: SupplierClientCounters,
    *,
    firm_owner_id: str,
    client_gstin_id: str,
    now_iso: str,
) -> dict[str, Any]:
    return {
        "firm_owner_id": firm_owner_id,
        "supplier_gstin_normalized": c.supplier_gstin,
        "client_gstin_id": client_gstin_id,
        "supplier_trade_name": c.trade_name or "",
        "total_invoices": len(c.invoice_keys),
        "mismatch_invoice_count": len(c.mismatch_keys),
        "rule37_open_count": int(c.rule37_open_count),
        "rule37_at_risk_paise": int(c.rule37_at_risk_paise),
        "section_17_5_count": int(c.section_17_5_count),
        "late_filing_count": int(c.late_filing_count),
        "pr_only_count": int(c.pr_only_count),
        "quarterly_filer_flag": bool(c.quarterly_filer_flag),
        "last_updated_at": now_iso,
    }


def rollup_client_rows(client_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll per-client contribution rows into one firm summary dict (no ids)."""
    if not client_rows:
        return {}
    gstin = str(client_rows[0].get("supplier_gstin_normalized") or "").strip()
    trade = ""
    client_ids: list[str] = []
    total_invoices = 0
    mismatch_invoice_count = 0
    rule37_open_count = 0
    rule37_at_risk_paise = 0
    section_17_5_count = 0
    late_filing_count = 0
    pr_only_count = 0
    quarterly = False
    import uuid
    for row in client_rows:
        cid_raw = row.get("client_gstin_id")
        if cid_raw:
            cid_str = str(cid_raw).strip()
            try:
                norm_uuid = str(uuid.UUID(cid_str))
                if norm_uuid not in client_ids:
                    client_ids.append(norm_uuid)
            except (ValueError, AttributeError):
                if cid_str and cid_str not in client_ids:
                    client_ids.append(cid_str)
        tn = str(row.get("supplier_trade_name") or "").strip()
        if tn and (not trade or len(tn) > len(trade)):
            trade = tn
        total_invoices += int(row.get("total_invoices") or 0)
        mismatch_invoice_count += int(row.get("mismatch_invoice_count") or 0)
        rule37_open_count += int(row.get("rule37_open_count") or 0)
        rule37_at_risk_paise += int(row.get("rule37_at_risk_paise") or 0)
        section_17_5_count += int(row.get("section_17_5_count") or 0)
        late_filing_count += int(row.get("late_filing_count") or 0)
        pr_only_count += int(row.get("pr_only_count") or 0)
        quarterly = quarterly or bool(row.get("quarterly_filer_flag"))

    mm_rate = _rate(mismatch_invoice_count, total_invoices)
    late_rate = _rate(late_filing_count, total_invoices)
    risk = compute_risk_score(
        rule37_open_count=rule37_open_count,
        section_17_5_count=section_17_5_count,
        mismatch_rate=float(mm_rate),
        late_filing_rate=float(late_rate),
        quarterly_filer_flag=quarterly,
        pr_only_count=pr_only_count,
    )
    return {
        "supplier_gstin_normalized": gstin,
        "supplier_trade_name": trade,
        "client_gstin_ids": client_ids,
        "clients_touched_count": len(client_ids),
        "total_invoices": total_invoices,
        "mismatch_invoice_count": mismatch_invoice_count,
        "mismatch_rate": float(mm_rate),
        "rule37_open_count": rule37_open_count,
        "rule37_at_risk_paise": rule37_at_risk_paise,
        "section_17_5_count": section_17_5_count,
        "late_filing_count": late_filing_count,
        "late_filing_rate": float(late_rate),
        "pr_only_count": pr_only_count,
        "quarterly_filer_flag": quarterly,
        "risk_score": risk,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _meta_from_record_data(rd: dict[str, Any], *, side: str) -> dict[str, Any]:
    if side == "pr":
        gstin = rd.get("gstin") or rd.get("supplier_gstin")
        name = rd.get("supplier_name") or rd.get("party_name") or ""
    else:
        gstin = (
            rd.get("supplier_gstin_norm")
            or rd.get("supplier_gstin")
            or rd.get("gstin")
        )
        name = rd.get("supplier_name") or ""
    return {
        "supplier_gstin": gstin,
        "invoice_number": rd.get("invoice_number_normalized")
        or rd.get("invoice_number")
        or "",
        "invoice_date": rd.get("invoice_date") or "",
        "supplier_name": str(name or "").strip(),
    }


def build_record_index_for_run(sb: Client, run_id: str) -> dict[str, dict[str, Any]]:
    """Map pr:/gstr: ids → supplier metadata for matched-row GSTIN resolution."""
    out: dict[str, dict[str, Any]] = {}
    for table, prefix in (("pr_records", "pr"), ("gstr_records", "gstr")):
        offset = 0
        batch = 1000
        while True:
            r = (
                sb.table(table)
                .select("id, record_data")
                .eq("run_id", run_id)
                .range(offset, offset + batch - 1)
                .execute()
            )
            rows = r.data or []
            for row in rows:
                rid = str(row.get("id") or "").strip()
                rd = row.get("record_data") if isinstance(row.get("record_data"), dict) else {}
                if rid:
                    out[f"{prefix}:{rid}"] = _meta_from_record_data(rd, side=prefix)
            if len(rows) < batch:
                break
            offset += batch
    return out


def select_latest_runs_for_client(
    sb: Client, client_gstin_id: str
) -> list[dict[str, Any]]:
    """Latest COMPLETED/FINAL run per period for one client."""
    r = (
        sb.table("reconciliation_run")
        .select("id, client_gstin_id, period, status, completed_at, created_at")
        .eq("client_gstin_id", client_gstin_id)
        .in_("status", list(_RUN_STATUSES))
        .order("completed_at", desc=True)
        .limit(500)
        .execute()
    )
    best: dict[str, dict[str, Any]] = {}
    for row in r.data or []:
        period = str(row.get("period") or "").strip() or "_none_"
        if period in best:
            continue
        best[period] = row
    return list(best.values())


def select_latest_runs_for_firm(
    sb: Client, firm_owner_id: str
) -> list[dict[str, Any]]:
    clients = (
        sb.table("client_gstins")
        .select("id")
        .eq("firm_owner_id", firm_owner_id)
        .execute()
    )
    client_ids = [str(x["id"]) for x in (clients.data or []) if x.get("id")]
    out: list[dict[str, Any]] = []
    for i in range(0, len(client_ids), 50):
        chunk = client_ids[i : i + 50]
        r = (
            sb.table("reconciliation_run")
            .select("id, client_gstin_id, period, status, completed_at, created_at")
            .in_("client_gstin_id", chunk)
            .in_("status", list(_RUN_STATUSES))
            .order("completed_at", desc=True)
            .limit(2000)
            .execute()
        )
        best: dict[tuple[str, str], dict[str, Any]] = {}
        for row in r.data or []:
            cid = str(row.get("client_gstin_id") or "").strip()
            period = str(row.get("period") or "").strip() or "_none_"
            key = (cid, period)
            if key in best:
                continue
            best[key] = row
        out.extend(best.values())
    return out


def _compute_client_supplier_counters(
    sb: Client, client_gstin_id: str
) -> dict[str, SupplierClientCounters]:
    merged: dict[str, SupplierClientCounters] = {}
    for run in select_latest_runs_for_client(sb, client_gstin_id):
        rid = str(run.get("id") or "").strip()
        if not rid:
            continue
        try:
            payload = load_payload(sb, rid)
        except Exception:
            _log.exception("scorecard: load_payload failed run_id=%s", rid)
            continue
        if not payload:
            continue
        try:
            idx = build_record_index_for_run(sb, rid)
        except Exception:
            _log.exception("scorecard: record index failed run_id=%s", rid)
            idx = {}
        extracted = extract_supplier_counters_from_payload(payload, record_index=idx)
        for gstin, counters in extracted.items():
            cur = merged.get(gstin)
            if cur is None:
                merged[gstin] = counters
            else:
                cur.merge(counters)
    return merged


def _replace_client_contributions(
    sb: Client,
    *,
    firm_owner_id: str,
    client_gstin_id: str,
    counters: dict[str, SupplierClientCounters],
) -> set[str]:
    """Replace by_client rows for this client. Returns old∪new supplier GSTINs."""
    prior = (
        sb.table("supplier_compliance_by_client")
        .select("supplier_gstin_normalized")
        .eq("firm_owner_id", firm_owner_id)
        .eq("client_gstin_id", client_gstin_id)
        .execute()
    )
    affected = {
        str(x.get("supplier_gstin_normalized") or "").strip()
        for x in (prior.data or [])
        if x.get("supplier_gstin_normalized")
    }
    affected |= set(counters.keys())

    sb.table("supplier_compliance_by_client").delete().eq(
        "firm_owner_id", firm_owner_id
    ).eq("client_gstin_id", client_gstin_id).execute()

    now = _now_iso()
    rows = [
        counters_to_row_dict(
            c, firm_owner_id=firm_owner_id, client_gstin_id=client_gstin_id, now_iso=now
        )
        for c in counters.values()
    ]
    for i in range(0, len(rows), 200):
        chunk = rows[i : i + 200]
        if chunk:
            sb.table("supplier_compliance_by_client").insert(chunk).execute()
    return {g for g in affected if g}


def _rollup_suppliers(
    sb: Client, *, firm_owner_id: str, supplier_gstins: Iterable[str]
) -> None:
    now = _now_iso()
    for gstin in supplier_gstins:
        if not gstin:
            continue
        r = (
            sb.table("supplier_compliance_by_client")
            .select("*")
            .eq("firm_owner_id", firm_owner_id)
            .eq("supplier_gstin_normalized", gstin)
            .execute()
        )
        rows = r.data or []
        if not rows:
            sb.table("supplier_compliance_summary").delete().eq(
                "firm_owner_id", firm_owner_id
            ).eq("supplier_gstin_normalized", gstin).execute()
            continue
        rolled = rollup_client_rows(rows)
        rolled["firm_owner_id"] = firm_owner_id
        rolled["last_updated_at"] = now
        sb.table("supplier_compliance_summary").delete().eq(
            "firm_owner_id", firm_owner_id
        ).eq("supplier_gstin_normalized", gstin).execute()
        sb.table("supplier_compliance_summary").insert(rolled).execute()


def refresh_after_run(
    sb: Client, *, run_id: str, client_gstin_id: str
) -> None:
    """Incremental: rebuild this client's contributions, roll up affected suppliers."""
    del run_id  # universe is latest-per-period for the client, not a single run
    cid = str(client_gstin_id).strip()
    if not cid:
        return
    try:
        firm_owner_id = get_firm_owner_for_client(sb, cid)
    except Exception:
        _log.exception("scorecard: firm owner unresolved client=%s", cid)
        return
    if not firm_owner_id:
        return

    counters = _compute_client_supplier_counters(sb, cid)
    affected = _replace_client_contributions(
        sb,
        firm_owner_id=firm_owner_id,
        client_gstin_id=cid,
        counters=counters,
    )
    _rollup_suppliers(sb, firm_owner_id=firm_owner_id, supplier_gstins=affected)
    _log.info(
        "scorecard refresh client=%s firm=%s suppliers=%s",
        cid,
        firm_owner_id,
        len(affected),
    )


def rebuild_firm(sb: Client, firm_owner_id: str) -> None:
    """Full rebuild of by_client + summary for one firm."""
    fid = str(firm_owner_id).strip()
    if not fid:
        return
    clients = (
        sb.table("client_gstins")
        .select("id")
        .eq("firm_owner_id", fid)
        .execute()
    )
    client_ids = [str(x["id"]) for x in (clients.data or []) if x.get("id")]
    all_suppliers: set[str] = set()
    for cid in client_ids:
        counters = _compute_client_supplier_counters(sb, cid)
        affected = _replace_client_contributions(
            sb, firm_owner_id=fid, client_gstin_id=cid, counters=counters
        )
        all_suppliers |= affected

    # Drop stale summary rows for this firm
    existing = (
        sb.table("supplier_compliance_summary")
        .select("supplier_gstin_normalized")
        .eq("firm_owner_id", fid)
        .execute()
    )
    stale = {
        str(x.get("supplier_gstin_normalized") or "").strip()
        for x in (existing.data or [])
    } - all_suppliers
    for g in stale:
        sb.table("supplier_compliance_summary").delete().eq(
            "firm_owner_id", fid
        ).eq("supplier_gstin_normalized", g).execute()

    _rollup_suppliers(sb, firm_owner_id=fid, supplier_gstins=all_suppliers)
    _log.info(
        "scorecard rebuild_firm firm=%s clients=%s suppliers=%s",
        fid,
        len(client_ids),
        len(all_suppliers),
    )


def list_firm_owner_ids_with_clients(sb: Client) -> list[str]:
    r = sb.table("client_gstins").select("firm_owner_id").execute()
    seen: set[str] = set()
    out: list[str] = []
    for row in r.data or []:
        fid = str(row.get("firm_owner_id") or "").strip()
        if fid and fid not in seen:
            seen.add(fid)
            out.append(fid)
    return out


async def run_scorecard_daily_rebuild() -> None:
    """Throttled full rebuild (call from stuck_job_detector loop)."""
    global _last_rebuild_at
    now = datetime.now(timezone.utc)
    if _last_rebuild_at is not None and (now - _last_rebuild_at) < _SCORECARD_MIN_INTERVAL:
        return
    from app.database import get_supabase

    sb = get_supabase()
    firms = list_firm_owner_ids_with_clients(sb)
    for fid in firms:
        try:
            rebuild_firm(sb, fid)
        except Exception:
            _log.exception("scorecard daily rebuild failed firm=%s", fid)
    _last_rebuild_at = now
    _log.info("scorecard daily rebuild complete firms=%s", len(firms))
