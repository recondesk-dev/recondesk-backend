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


from app.services.reconciliation_outcomes import load_payload

# ---------------------------------------------------------------------------
# GSTR-2B ITC extraction from run payload
# ---------------------------------------------------------------------------

def _extract_gstr2b_itc(sb, run_id: str) -> dict[str, float]:
    """Derive total GSTR-2B available ITC directly from the database rows."""
    igst_total = cgst_total = sgst_total = 0.0
    offset = 0
    chunk_size = 1000
    has_data = False
    
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
            if not isinstance(rd, dict):
                continue
                
            items = rd.get("items")
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        igst_total += _paise_to_rupees(item.get("igst_paise") or 0)
                        cgst_total += _paise_to_rupees(item.get("cgst_paise") or 0)
                        sgst_total += _paise_to_rupees(item.get("sgst_paise") or 0)
                        
        if len(rows) < chunk_size:
            break
        offset += chunk_size

    return {
        "igst": round(igst_total, 2),
        "cgst": round(cgst_total, 2),
        "sgst": round(sgst_total, 2),
        "_has_data": has_data
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
