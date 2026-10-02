"""GSTR-9C ITC FY rollup — practical annual aggregation of existing 2B/3B data.

Not an official GSTR-9C Table 8 / GSTN filing replica. Does not re-run matching.
Uses latest COMPLETED/FINAL reconciliation_run per period and optional
gstr3b_reconciliation claimed ITC (sparse).
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Literal, Optional

from supabase import Client

from app.constants import RunStatus

_log = logging.getLogger(__name__)

_RUN_STATUSES = (RunStatus.COMPLETED, RunStatus.FINAL)
_FY_RE = re.compile(r"^(\d{4})-(\d{2})$")

MonthStatus = Literal["both", "run_only", "missing"]

_MONTH_SHORT = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

DISCLAIMER = (
    "Internal practical rollup of existing GSTR-2B reconciliations and uploaded "
    "GSTR-3B claimed ITC. Not an official GSTR-9C Table 8 / GSTN filing replica."
)


def parse_fy_label(fy: str) -> tuple[int, int]:
    """Parse ``YYYY-YY`` (e.g. ``2025-26``) → (start_year, end_year)."""
    raw = (fy or "").strip()
    m = _FY_RE.match(raw)
    if not m:
        raise ValueError("fy must be YYYY-YY (e.g. 2025-26)")
    start = int(m.group(1))
    end_yy = int(m.group(2))
    expected_yy = (start + 1) % 100
    if end_yy != expected_yy:
        raise ValueError("fy end year must be start year + 1 (e.g. 2025-26)")
    return start, start + 1


def format_fy_label(start_year: int) -> str:
    end = start_year + 1
    return f"{start_year}-{end % 100:02d}"


def default_fy_label(today: Optional[date] = None) -> str:
    """Indian FY: April–March. On/after 1 Apr → FY starting this calendar year."""
    d = today or date.today()
    start = d.year if d.month >= 4 else d.year - 1
    return format_fy_label(start)


def fy_periods(start_year: int) -> list[str]:
    """Return 12 ``YYYY-MM`` periods for FY starting ``start_year``-04."""
    periods: list[str] = []
    for month in range(4, 13):
        periods.append(f"{start_year}-{month:02d}")
    end_year = start_year + 1
    for month in range(1, 4):
        periods.append(f"{end_year}-{month:02d}")
    return periods


def period_month_label(period: str) -> str:
    parts = (period or "").split("-")
    if len(parts) != 2:
        return period or ""
    try:
        year = int(parts[0])
        month = int(parts[1])
    except ValueError:
        return period
    if month < 1 or month > 12:
        return period
    return f"{_MONTH_SHORT[month - 1]} {year}"


def normalize_period_yyyy_mm(raw: Any) -> str:
    """Normalize run/3B period strings to ``YYYY-MM``.

    Accepts ``YYYY-MM``, ``YYYY-MM-DD``, and portal ``MMYYYY`` / ``YYYYMM``.
    Returns ``""`` when unparseable.
    """
    s = str(raw or "").strip()
    if not s:
        return ""
    if len(s) >= 7 and s[4] == "-":
        # YYYY-MM or YYYY-MM-DD
        try:
            year = int(s[0:4])
            month = int(s[5:7])
        except ValueError:
            return ""
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"
        return ""
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 6:
        yyyy, mm = int(digits[:4]), int(digits[4:6])
        if yyyy >= 2000 and 1 <= mm <= 12:
            return f"{yyyy:04d}-{mm:02d}"
        mm2, yyyy2 = int(digits[:2]), int(digits[2:])
        if 1 <= mm2 <= 12 and yyyy2 >= 2000:
            return f"{yyyy2:04d}-{mm2:02d}"
    return ""


def periods_match_yyyy_mm(a: Any, b: Any) -> bool:
    """True when both values normalize to the same ``YYYY-MM`` tax period.

    Used by GSTR-3B upload to accept run periods stored as ``YYYY-MM-DD``
    against portal ``ret_period`` values like ``YYYY-MM`` / ``MMYYYY``.
    """
    na = normalize_period_yyyy_mm(a)
    nb = normalize_period_yyyy_mm(b)
    if na and nb:
        return na == nb
    return str(a or "").strip() == str(b or "").strip()


def _safe_int(val: Any, default: int = 0) -> int:
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return default


def _safe_rupees(val: Any) -> float:
    if val is None or val == "":
        return 0.0
    try:
        return round(float(val), 2)
    except (TypeError, ValueError):
        return 0.0


def paise_to_rupees(paise: int) -> float:
    return round(float(paise) / 100.0, 2)


def extract_matched_itc_paise(run_summary: Any) -> int:
    if not isinstance(run_summary, dict):
        return 0
    return _safe_int(run_summary.get("matched_itc_paise"), 0)


def extract_risk_paise(run_summary: Any) -> dict[str, int]:
    rs = run_summary if isinstance(run_summary, dict) else {}
    itc_at_risk = rs.get("itc_at_risk")
    if itc_at_risk is None:
        itc_at_risk = rs.get("missed_itc_paise")
    return {
        "missed_itc_paise": _safe_int(rs.get("missed_itc_paise"), 0),
        "itc_at_risk_paise": _safe_int(itc_at_risk, 0),
        "wrongful_itc_paise": _safe_int(rs.get("wrongful_itc"), 0),
    }


def extract_claimed_itc_rupees(g3b_row: Optional[dict[str, Any]]) -> dict[str, float]:
    if not g3b_row:
        return {
            "igst": 0.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "total": 0.0,
        }
    igst = _safe_rupees(g3b_row.get("gstr3b_igst_claimed"))
    cgst = _safe_rupees(g3b_row.get("gstr3b_cgst_claimed"))
    sgst = _safe_rupees(g3b_row.get("gstr3b_sgst_claimed"))
    return {
        "igst": igst,
        "cgst": cgst,
        "sgst": sgst,
        "total": round(igst + cgst + sgst, 2),
    }


def classify_month(
    *,
    has_run: bool,
    has_gstr3b: bool,
) -> MonthStatus:
    if has_run and has_gstr3b:
        return "both"
    if has_run:
        return "run_only"
    return "missing"


def assemble_fy_rollup(
    *,
    client_gstin_id: str,
    gstin: str,
    trade_name: Optional[str],
    fy: str,
    runs_by_period: dict[str, dict[str, Any]],
    g3b_by_run_id: dict[str, dict[str, Any]],
    g3b_by_period: Optional[dict[str, dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Pure assembly of the FY rollup response from prefetched rows.

    Claimed ITC resolution order per month:
    1. ``gstr3b_reconciliation`` row for the selected run_id (preferred)
    2. Else latest 3B upload for the same ``YYYY-MM`` tax period (fallback)

    The fallback matters when a newer COMPLETED run exists for the period but
    GSTR-3B was uploaded against an earlier run — without it, May-style months
    incorrectly show as ``run_only`` and drop out of annual variance.
    """
    start_year, _end = parse_fy_label(fy)
    periods = fy_periods(start_year)
    by_period = g3b_by_period or {}

    months: list[dict[str, Any]] = []
    matched_total_paise = 0
    claimed_total_rupees = 0.0
    variance_matched_paise = 0
    variance_claimed_rupees = 0.0
    months_with_both = 0
    months_with_run = 0
    months_missing = 0
    months_run_only = 0

    for period in periods:
        run = runs_by_period.get(period)
        has_run = run is not None
        run_id = str(run.get("id") or "").strip() if run else ""
        g3b = None
        if run_id:
            g3b = g3b_by_run_id.get(run_id)
        if g3b is None:
            g3b = by_period.get(period)
        has_gstr3b = g3b is not None
        status = classify_month(has_run=has_run, has_gstr3b=has_gstr3b)

        matched_paise = 0
        risk = {
            "missed_itc_paise": 0,
            "itc_at_risk_paise": 0,
            "wrongful_itc_paise": 0,
        }
        run_status = None
        if run:
            months_with_run += 1
            matched_paise = extract_matched_itc_paise(run.get("run_summary"))
            risk = extract_risk_paise(run.get("run_summary"))
            run_status = str(run.get("status") or "") or None
            matched_total_paise += matched_paise

        claimed = extract_claimed_itc_rupees(g3b if has_gstr3b else None)
        if has_gstr3b:
            claimed_total_rupees = round(claimed_total_rupees + claimed["total"], 2)

        variance_rupees: Optional[float] = None
        included_in_variance = status == "both"
        if included_in_variance:
            months_with_both += 1
            variance_matched_paise += matched_paise
            variance_claimed_rupees = round(
                variance_claimed_rupees + claimed["total"], 2
            )
            variance_rupees = round(
                paise_to_rupees(matched_paise) - claimed["total"], 2
            )
        elif status == "run_only":
            months_run_only += 1
        else:
            months_missing += 1

        months.append(
            {
                "period": period,
                "month_label": period_month_label(period),
                "status": status,
                "run_id": run_id or None,
                "run_status": run_status,
                "matched_itc_paise": matched_paise if has_run else None,
                "matched_itc_rupees": paise_to_rupees(matched_paise) if has_run else None,
                "claimed_itc_rupees": claimed["total"] if has_gstr3b else None,
                "claimed_igst_rupees": claimed["igst"] if has_gstr3b else None,
                "claimed_cgst_rupees": claimed["cgst"] if has_gstr3b else None,
                "claimed_sgst_rupees": claimed["sgst"] if has_gstr3b else None,
                "variance_rupees": variance_rupees,
                "included_in_variance": included_in_variance,
                "missed_itc_paise": risk["missed_itc_paise"] if has_run else None,
                "itc_at_risk_paise": risk["itc_at_risk_paise"] if has_run else None,
                "wrongful_itc_paise": risk["wrongful_itc_paise"] if has_run else None,
            }
        )

    is_complete = months_with_both == 12
    variance_available = months_with_both > 0
    variance_total: Optional[float] = None
    if variance_available:
        variance_total = round(
            paise_to_rupees(variance_matched_paise) - variance_claimed_rupees, 2
        )

    if is_complete:
        partial_label = "Complete — 12 of 12 months"
    elif variance_available:
        partial_label = f"Partial — {months_with_both} of 12 months"
    else:
        partial_label = "No variance available — 0 of 12 months have both 2B + 3B"

    return {
        "client_gstin_id": client_gstin_id,
        "gstin": gstin,
        "trade_name": trade_name,
        "fy": format_fy_label(start_year),
        "disclaimer": DISCLAIMER,
        "is_complete": is_complete,
        "variance_available": variance_available,
        "months_with_both": months_with_both,
        "months_with_run": months_with_run,
        "months_run_only": months_run_only,
        "months_missing": months_missing,
        "months": months,
        "totals": {
            "matched_itc_paise": matched_total_paise,
            "matched_itc_rupees": paise_to_rupees(matched_total_paise),
            "claimed_itc_rupees": round(claimed_total_rupees, 2),
            "variance_matched_itc_rupees": paise_to_rupees(variance_matched_paise),
            "variance_claimed_itc_rupees": round(variance_claimed_rupees, 2),
            "variance_rupees": variance_total,
            "months_in_variance": months_with_both,
            "partial_label": partial_label,
        },
    }


def select_latest_runs_with_summary(
    sb: Client, client_gstin_id: str
) -> list[dict[str, Any]]:
    """Latest COMPLETED/FINAL run per period, including run_summary."""
    r = (
        sb.table("reconciliation_run")
        .select(
            "id, client_gstin_id, period, status, completed_at, created_at, run_summary"
        )
        .eq("client_gstin_id", client_gstin_id)
        .in_("status", list(_RUN_STATUSES))
        .order("completed_at", desc=True)
        .limit(500)
        .execute()
    )
    best: dict[str, dict[str, Any]] = {}
    for row in r.data or []:
        period = normalize_period_yyyy_mm(row.get("period"))
        if not period or period in best:
            continue
        # Store with normalized period so FY month keys always match.
        row = dict(row)
        row["period"] = period
        best[period] = row
    return list(best.values())


def _get_gstr3b_repo():
    try:
        from app.repositories import get_gstr3b_repository
        return get_gstr3b_repository()
    except Exception:
        return None


def fetch_gstr3b_for_run_ids(
    sb: Client, run_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """Latest gstr3b_reconciliation row per run_id (Aurora PRIMARY)."""
    if not run_ids:
        return {}
    repo = _get_gstr3b_repo()
    if repo:
        try:
            return repo.fetch_latest_gstr3b_for_runs(run_ids)
        except Exception:
            _log.warning("Aurora fetch_latest_gstr3b_for_runs failed, trying fallback", exc_info=True)

    out: dict[str, dict[str, Any]] = {}
    if not sb:
        return out
    for i in range(0, len(run_ids), 50):
        chunk = run_ids[i : i + 50]
        res = (
            sb.table("gstr3b_reconciliation")
            .select(
                "id, run_id, tax_period, uploaded_at, "
                "gstr3b_igst_claimed, gstr3b_cgst_claimed, gstr3b_sgst_claimed"
            )
            .in_("run_id", chunk)
            .order("uploaded_at", desc=True)
            .execute()
        )
        for row in res.data or []:
            rid = str(row.get("run_id") or "").strip()
            if not rid or rid in out:
                continue
            out[rid] = row
    return out


def fetch_gstr3b_by_period_for_gstin(
    sb: Client,
    *,
    gstin: str,
    periods: set[str],
) -> dict[str, dict[str, Any]]:
    """Latest GSTR-3B upload per ``YYYY-MM`` tax period for a client GSTIN (Aurora PRIMARY).

    Used as a fallback when the selected latest 2B run for a month does not
    itself have a ``gstr3b_reconciliation`` row (3B uploaded on an older run).
    """
    gstin_n = (gstin or "").strip().upper()
    if not gstin_n or not periods:
        return {}
    repo = _get_gstr3b_repo()
    if repo:
        try:
            return repo.fetch_gstr3b_by_period_for_gstin(gstin=gstin_n, periods=periods, limit=200)
        except Exception:
            _log.warning("Aurora fetch_gstr3b_by_period_for_gstin failed, trying fallback", exc_info=True)

    out: dict[str, dict[str, Any]] = {}
    if not sb:
        return out
    res = (
        sb.table("gstr3b_reconciliation")
        .select(
            "id, run_id, tax_period, uploaded_at, "
            "gstr3b_igst_claimed, gstr3b_cgst_claimed, gstr3b_sgst_claimed"
        )
        .eq("client_gstin", gstin_n)
        .order("uploaded_at", desc=True)
        .limit(200)
        .execute()
    )
    for row in res.data or []:
        period = normalize_period_yyyy_mm(row.get("tax_period"))
        if not period or period not in periods or period in out:
            continue
        out[period] = row
    return out


def build_gstr9c_itc_fy_rollup(
    sb: Client,
    *,
    client_gstin_id: str,
    fy: str,
) -> dict[str, Any]:
    """Load client + runs + 3B rows and assemble the FY rollup."""
    start_year, _ = parse_fy_label(fy)
    fy_label = format_fy_label(start_year)
    periods = set(fy_periods(start_year))

    cg = (
        sb.table("client_gstins")
        .select("id, gstin, trade_name, legal_name")
        .eq("id", client_gstin_id)
        .limit(1)
        .execute()
    )
    if not cg.data:
        raise LookupError("client not found")
    client_row = cg.data[0]
    gstin = str(client_row.get("gstin") or "").strip()
    trade_name = (
        str(client_row.get("trade_name") or "").strip()
        or str(client_row.get("legal_name") or "").strip()
        or None
    )

    runs = select_latest_runs_with_summary(sb, client_gstin_id)
    runs_by_period: dict[str, dict[str, Any]] = {}
    for run in runs:
        period = normalize_period_yyyy_mm(run.get("period"))
        if period in periods:
            runs_by_period[period] = run

    run_ids = [
        str(r.get("id") or "").strip()
        for r in runs_by_period.values()
        if r.get("id")
    ]
    g3b_by_run_id = fetch_gstr3b_for_run_ids(sb, run_ids)
    g3b_by_period = fetch_gstr3b_by_period_for_gstin(
        sb, gstin=gstin, periods=periods
    )

    return assemble_fy_rollup(
        client_gstin_id=client_gstin_id,
        gstin=gstin,
        trade_name=trade_name,
        fy=fy_label,
        runs_by_period=runs_by_period,
        g3b_by_run_id=g3b_by_run_id,
        g3b_by_period=g3b_by_period,
    )
