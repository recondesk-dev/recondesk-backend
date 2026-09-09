"""GSTR-3B reconciliation service.

Compares ITC available in GSTR-2B (from a completed reconciliation run)
against ITC actually claimed in the uploaded GSTR-3B, and flags
over-claiming or under-claiming per tax head.

Also computes an additive DRC-01C (Rule 88D) threshold check when claimed
ITC exceeds available ITC by both the Council-recommended percentage and
absolute amount.
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

MATCHED     = "MATCHED"
OVERCLAIMED = "OVERCLAIMED"
UNDERCLAIMED = "UNDERCLAIMED"
MIXED       = "MIXED"  # some heads overclaimed, others underclaimed

# DRC-01C / Rule 88D — 50th GST Council (para 4.35): intimation where the
# difference (ITC availed in GSTR-3B − ITC available in GSTR-2B) is
# **more than 20% as well as more than ₹25 lakh**. Both conditions required.
# Rule 88D says "such amount and such percentage as may be recommended by
# the Council"; these figures are not separately notified (no "prescribed"
# language) but are the Council recommendation the portal follows.
DRC01C_EXCESS_PCT_THRESHOLD: float = 20.0
DRC01C_EXCESS_AMOUNT_THRESHOLD: float = 2_500_000.0  # ₹25 lakh

DRC01C_CLEAR = "CLEAR"                 # not overclaimed
DRC01C_BELOW_THRESHOLD = "BELOW_THRESHOLD"  # overclaimed but under dual threshold
DRC01C_TRIGGER = "DRC01C_TRIGGER"      # both % and ₹ thresholds exceeded


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _head_status(gstr2b_val: float, gstr3b_val: float) -> str:
    diff = round(gstr3b_val - gstr2b_val, 2)
    if diff == 0:
        return MATCHED
    if diff > 0:
        return OVERCLAIMED
    return UNDERCLAIMED


def _overall_status(igst_s: str, cgst_s: str, sgst_s: str) -> str:
    """Badge for the GSTR-3B summary header.

    Uses per-head direction, not "any overclaim wins". When IGST/CGST/SGST
    disagree (some overclaimed, some underclaimed), return MIXED so the badge
    does not contradict a net underclaim / overclaim on the total row.
    """
    statuses = {igst_s, cgst_s, sgst_s} - {MATCHED}
    if not statuses:
        return MATCHED
    if statuses == {OVERCLAIMED}:
        return OVERCLAIMED
    if statuses == {UNDERCLAIMED}:
        return UNDERCLAIMED
    if OVERCLAIMED in statuses and UNDERCLAIMED in statuses:
        return MIXED
    # Unknown / legacy head statuses — fall back conservatively.
    if OVERCLAIMED in statuses:
        return OVERCLAIMED
    if UNDERCLAIMED in statuses:
        return UNDERCLAIMED
    return MATCHED


def _paise_to_rupees(paise: Any) -> float:
    """Convert paise to rupees WITHOUT rounding.

    Callers that sum multiple rows must apply round(..., 2) once on the
    final accumulated total, not per-row, to avoid cumulative drift.
    """
    try:
        return float(paise) / 100.0
    except (TypeError, ValueError):
        return 0.0


def _safe_float(val: Any) -> float:
    try:
        return round(float(val or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def compute_drc01c_threshold(
    claimed_total: float,
    available_total: float,
    *,
    pct_threshold: float = DRC01C_EXCESS_PCT_THRESHOLD,
    amount_threshold: float = DRC01C_EXCESS_AMOUNT_THRESHOLD,
) -> dict[str, Any]:
    """Rule 88D / DRC-01C dual-threshold check (additive; does not alter head status).

    excess_amount = claimed − available (positive = overclaim).
    excess_pct    = (excess_amount / available) × 100 when available > 0.

    Trigger when excess_amount > amount_threshold **and** excess_pct > pct_threshold.
    When available is 0 and claimed > 0, percentage is treated as exceeding the
    pct threshold (division by zero); the absolute ₹ gate still applies.
    """
    claimed = _safe_float(claimed_total)
    available = _safe_float(available_total)
    excess_amount = round(claimed - available, 2)

    if excess_amount <= 0:
        return {
            "threshold_status": DRC01C_CLEAR,
            "excess_amount": excess_amount,
            "excess_pct": 0.0 if available > 0 else None,
            "pct_threshold": pct_threshold,
            "amount_threshold": amount_threshold,
            "triggers_drc01c": False,
        }

    if available > 0:
        excess_pct = round((excess_amount / available) * 100.0, 4)
        pct_exceeded = excess_pct > pct_threshold
    else:
        # Available ITC is zero but something was claimed — % is unbounded.
        excess_pct = None
        pct_exceeded = True

    amount_exceeded = excess_amount > amount_threshold
    triggers = bool(pct_exceeded and amount_exceeded)

    return {
        "threshold_status": DRC01C_TRIGGER if triggers else DRC01C_BELOW_THRESHOLD,
        "excess_amount": excess_amount,
        "excess_pct": excess_pct,
        "pct_threshold": pct_threshold,
        "amount_threshold": amount_threshold,
        "triggers_drc01c": triggers,
    }


# ---------------------------------------------------------------------------
# GSTR-2B ITC extraction from run payload
# ---------------------------------------------------------------------------

def _record_tax_heads_rupees(rd: dict[str, Any]) -> tuple[float, float, float]:
    """Sum IGST/CGST/SGST from line items, else invoice-level paise on the record."""
    items = rd.get("items")
    if isinstance(items, list) and items:
        igst = cgst = sgst = 0.0
        for item in items:
            if not isinstance(item, dict):
                continue
            igst += _paise_to_rupees(item.get("igst_paise") or 0)
            cgst += _paise_to_rupees(item.get("cgst_paise") or 0)
            sgst += _paise_to_rupees(item.get("sgst_paise") or 0)
        return igst, cgst, sgst
    return (
        _paise_to_rupees(rd.get("igst_paise") or 0),
        _paise_to_rupees(rd.get("cgst_paise") or 0),
        _paise_to_rupees(rd.get("sgst_paise") or 0),
    )


def accumulate_gstr2b_available_itc(
    records: list[dict[str, Any]],
) -> dict[str, float]:
    """Pure aggregation of GSTR-2B *available* ITC from parsed ``record_data`` rows.

    Rules (adversarial / compliance-correct):
    - Skip invoices with ``itc_available is False`` (``itcavl=N``).
    - Missing ``itc_available`` is treated as eligible (legacy rows).
    - ``CREDIT_NOTE`` taxes reduce available ITC (portal stores positive amounts).
    - Prefer line-item taxes; fall back to invoice-level ``*_paise`` on the record.
    """
    igst_total = cgst_total = sgst_total = 0.0
    for rd in records:
        if not isinstance(rd, dict):
            continue
        if rd.get("itc_available") is False:
            continue
        sign = -1.0 if str(rd.get("doc_type") or "").strip().upper() == "CREDIT_NOTE" else 1.0
        igst, cgst, sgst = _record_tax_heads_rupees(rd)
        igst_total += sign * igst
        cgst_total += sign * cgst
        sgst_total += sign * sgst
    return {
        "igst": round(igst_total, 2),
        "cgst": round(cgst_total, 2),
        "sgst": round(sgst_total, 2),
    }


def _extract_gstr2b_itc(sb, run_id: str) -> dict[str, float]:
    """Derive total GSTR-2B available ITC directly from the database rows."""
    offset = 0
    chunk_size = 1000
    has_data = False
    record_datas: list[dict[str, Any]] = []

    while True:
        try:
            recs = (
                sb.table("gstr_records")
                .select("record_data")
                .eq("run_id", run_id)
                .range(offset, offset + chunk_size - 1)
                .execute()
            )
        except Exception:
            _log.exception("gstr3b_recon: gstr_records fetch failed run_id=%s", run_id)
            break

        rows = recs.data or []
        if not rows:
            break

        has_data = True
        for row in rows:
            if not isinstance(row, dict):
                continue
            rd = row.get("record_data")
            if isinstance(rd, dict):
                record_datas.append(rd)

        if len(rows) < chunk_size:
            break
        offset += chunk_size

    totals = accumulate_gstr2b_available_itc(record_datas)
    totals["_has_data"] = has_data
    return totals


# ---------------------------------------------------------------------------
# Public reconciliation function
# ---------------------------------------------------------------------------

def reconcile_gstr3b(
    run_id: str,
    gstr3b_data: dict,
    client_gstin: str,
    *,
    sb,
) -> dict[str, Any]:
    """Compare GSTR-2B available ITC against GSTR-3B claimed ITC.

    Parameters
    ----------
    run_id:
        UUID of the reconciliation run.
    gstr3b_data:
        Parsed output from :func:`app.parsers.gstr3b_parser.parse_gstr3b`.
    client_gstin:
        The client's GSTIN (for validation / audit).
    sb:
        Supabase client instance.

    Returns
    -------
    dict with structure::

        {
          "igst":  {"gstr2b": float, "gstr3b": float, "difference": float, "status": str},
          "cgst":  {...},
          "sgst":  {...},
          "total": {...},
          "outward_supply": {"taxable_value": float, "igst": float, "total": float},
          "tax_period":      str,   # YYYY-MM
          "overall_status":  str,
          "drc01c": {
            "threshold_status": str,
            "excess_amount": float,
            "excess_pct": float | None,
            "pct_threshold": float,
            "amount_threshold": float,
            "triggers_drc01c": bool,
          },
        }
    """
    # -- GSTR-2B side: extract from run payload
    gstr2b_itc = _extract_gstr2b_itc(sb, run_id)
    g2b_igst = gstr2b_itc["igst"]
    g2b_cgst = gstr2b_itc["cgst"]
    g2b_sgst = gstr2b_itc["sgst"]

    # -- GSTR-3B side: net ITC after reversals (what was actually claimed)
    itc_net = gstr3b_data.get("itc_net")
    if not isinstance(itc_net, dict):
        itc_net = {}
    g3b_has_data = bool(itc_net)

    g3b_igst = _safe_float(itc_net.get("igst"))
    g3b_cgst = _safe_float(itc_net.get("cgst"))
    g3b_sgst = _safe_float(itc_net.get("sgst"))

    # -- Per-head difference (positive = overclaimed, negative = underclaimed)
    diff_igst = round(g3b_igst - g2b_igst, 2)
    diff_cgst = round(g3b_cgst - g2b_cgst, 2)
    diff_sgst = round(g3b_sgst - g2b_sgst, 2)

    status_igst = _head_status(g2b_igst, g3b_igst)
    status_cgst = _head_status(g2b_cgst, g3b_cgst)
    status_sgst = _head_status(g2b_sgst, g3b_sgst)
    overall = _overall_status(status_igst, status_cgst, status_sgst)

    if overall == "MATCHED" and not gstr2b_itc.get("_has_data") and not g3b_has_data:
        overall = "UNSUPPORTED_SCHEMA_OR_NO_DATA"

    # -- Totals
    g2b_total = round(g2b_igst + g2b_cgst + g2b_sgst, 2)
    g3b_total = round(g3b_igst + g3b_cgst + g3b_sgst, 2)
    diff_total = round(g3b_total - g2b_total, 2)

    outward = gstr3b_data.get("outward_supply")
    if not isinstance(outward, dict):
        outward = {}

    drc01c = compute_drc01c_threshold(g3b_total, g2b_total)

    return {
        "igst": {
            "gstr2b":     g2b_igst,
            "gstr3b":     g3b_igst,
            "difference": diff_igst,
            "status":     status_igst,
        },
        "cgst": {
            "gstr2b":     g2b_cgst,
            "gstr3b":     g3b_cgst,
            "difference": diff_cgst,
            "status":     status_cgst,
        },
        "sgst": {
            "gstr2b":     g2b_sgst,
            "gstr3b":     g3b_sgst,
            "difference": diff_sgst,
            "status":     status_sgst,
        },
        "total": {
            "gstr2b":     g2b_total,
            "gstr3b":     g3b_total,
            "difference": diff_total,
            "status":     _head_status(g2b_total, g3b_total),
        },
        "outward_supply": {
            "taxable_value": _safe_float(outward.get("taxable_value")),
            "igst":          _safe_float(outward.get("igst")),
            "total":         _safe_float(outward.get("total")),
        },
        "tax_period":    gstr3b_data.get("ret_period", ""),
        "overall_status": overall,
        "drc01c": drc01c,
    }
