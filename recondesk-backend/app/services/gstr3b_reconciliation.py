"""GSTR-3B reconciliation service.

Compares ITC available in GSTR-2B (from a completed reconciliation run)
against ITC actually claimed in the uploaded GSTR-3B, and flags
over-claiming or under-claiming per tax head.
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
    statuses = {igst_s, cgst_s, sgst_s}
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


# ---------------------------------------------------------------------------
# GSTR-2B ITC extraction from run payload
# ---------------------------------------------------------------------------

def _extract_gstr2b_itc(sb, run_id: str) -> dict[str, float]:
    """Derive GSTR-2B available ITC from the reconciliation run.

    Reads ``reconciliation_results.payload`` and sums IGST/CGST/SGST across
    matched + missed ITC (= total eligible ITC in GSTR-2B for the period).

    Values in the engine payload are stored in **paise** for matched/risk rows
    and in ``total_tax_paise`` per record.  We decompose them using the
    igst/cgst/sgst breakdown stored in each gstr_record's ``record_data``.

    Returns rupee floats keyed ``igst``, ``cgst``, ``sgst``.
    """
    # 1. Fetch payload
    try:
        res = (
            sb.table("reconciliation_results")
            .select("payload")
            .eq("run_id", run_id)
            .single()
            .execute()
        )
    except Exception:
        _log.exception("gstr3b_recon: failed to load reconciliation_results run_id=%s", run_id)
        return {"igst": 0.0, "cgst": 0.0, "sgst": 0.0}

    payload: dict = (res.data or {}).get("payload") or {}
    engine: dict  = payload.get("engine") or {}

    # 2. Collect gstr record IDs that appear in matched + missed ITC
    gstr_ids: set[str] = set()
    for m in engine.get("matched") or []:
        gid = str(m.get("gstr_id") or "").strip()
        if gid:
            gstr_ids.add(gid)
    for m in engine.get("missed_itc") or []:
        gid = str(m.get("gstr_id") or "").strip()
        if gid:
            gstr_ids.add(gid)

    if not gstr_ids:
        return {"igst": 0.0, "cgst": 0.0, "sgst": 0.0}

    # 3. Fetch gstr_records for those IDs (paginated in chunks of 200)
    igst_total = cgst_total = sgst_total = 0.0
    ids_list = list(gstr_ids)
    chunk_size = 200
    for i in range(0, len(ids_list), chunk_size):
        chunk = ids_list[i : i + chunk_size]
        try:
            recs = (
                sb.table("gstr_records")
                .select("id, record_data")
                .in_("id", chunk)
                .execute()
            )
        except Exception:
            _log.exception("gstr3b_recon: gstr_records fetch failed run_id=%s", run_id)
            continue
        for row in recs.data or []:
            rd: dict = row.get("record_data") or {}
            # Items hold paise values; sum across all items per record
            for item in rd.get("items") or []:
                igst_total += _paise_to_rupees(item.get("igst_paise") or 0)
                cgst_total += _paise_to_rupees(item.get("cgst_paise") or 0)
                sgst_total += _paise_to_rupees(item.get("sgst_paise") or 0)

    return {
        # round() applied once on the accumulated sum, not per-row, to avoid
        # cumulative drift from summing multiple round(paise/100, 2) values.
        "igst": round(igst_total, 2),
        "cgst": round(cgst_total, 2),
        "sgst": round(sgst_total, 2),
    }


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
        }
    """
    # -- GSTR-2B side: extract from run payload
    gstr2b_itc = _extract_gstr2b_itc(sb, run_id)
    g2b_igst = gstr2b_itc["igst"]
    g2b_cgst = gstr2b_itc["cgst"]
    g2b_sgst = gstr2b_itc["sgst"]

    # -- GSTR-3B side: net ITC after reversals (what was actually claimed)
    itc_net: dict = gstr3b_data.get("itc_net") or {}
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

    # -- Totals
    g2b_total = round(g2b_igst + g2b_cgst + g2b_sgst, 2)
    g3b_total = round(g3b_igst + g3b_cgst + g3b_sgst, 2)
    diff_total = round(g3b_total - g2b_total, 2)

    outward: dict = gstr3b_data.get("outward_supply") or {}

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
            "status":     _overall_status(status_igst, status_cgst, status_sgst),
        },
        "outward_supply": {
            "taxable_value": _safe_float(outward.get("taxable_value")),
            "igst":          _safe_float(outward.get("igst")),
            "total":         _safe_float(outward.get("total")),
        },
        "tax_period":    gstr3b_data.get("ret_period", ""),
        "overall_status": overall,
    }
