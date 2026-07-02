"""GSTR-3B JSON parser.

Parses the official GSTN GSTR-3B JSON format downloaded from the GST portal
into a structured, normalised summary suitable for ITC reconciliation.

Expected top-level shape::

    {
      "gstin": "27AABCM4162G1ZM",
      "ret_period": "052026",
      "data": {
        "itcElg": {
          "itcAvl": [ {"ty": "IMPG", "iamt": 0, "camt": 0, "samt": 0, "csamt": 0}, ... ],
          "itcRev": [ ... ],
          "itcNet": [ ... ],
          "itcInelg": [ ... ]
        },
        "sup_details": {
          "osup_det":      {"txval": 0, "iamt": 0, "camt": 0, "samt": 0, "csamt": 0},
          "osup_zero":     {...},
          "osup_nil_exmp": {...},
          "isup_rev":      {...},
          "osup_nongst":   {...}
        },
        "intr_ltfee": {
          "intr_details": {"iamt": 0, "camt": 0, "samt": 0, "csamt": 0}
        }
      }
    }
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class ParseError(ValueError):
    """Raised when the GSTR-3B JSON cannot be parsed."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_num(val: Any, field: str = "") -> float:
    """Convert a raw portal value to float; None / missing → 0.0."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        logger.warning("gstr3b_parser: non-numeric value for %s: %r", field, val)
        return 0.0


def _sum_rows(rows: list[dict], *, iamt_key: str = "iamt", camt_key: str = "camt",
               samt_key: str = "samt", csamt_key: str = "csamt") -> dict[str, float]:
    """Sum tax components across a list of ITC rows."""
    igst = cgst = sgst = cess = 0.0
    if not isinstance(rows, list):
        logger.warning("gstr3b_parser: expected list for rows, got %s", type(rows).__name__)
        rows = []
        
    for row in rows:
        if not isinstance(row, dict):
            logger.warning("gstr3b_parser: skipping non-dict row: %r", row)
            continue
        igst  += _safe_num(row.get(iamt_key),  f"iamt[{row.get('ty','')}]")
        cgst  += _safe_num(row.get(camt_key),  f"camt[{row.get('ty','')}]")
        sgst  += _safe_num(row.get(samt_key),  f"samt[{row.get('ty','')}]")
        cess  += _safe_num(row.get(csamt_key), f"csamt[{row.get('ty','')}]")
    return {"igst": igst, "cgst": cgst, "sgst": sgst, "cess": cess}


def _parse_ret_period(raw: str) -> str:
    """Convert portal format '052026' → '2026-05'.

    Also accepts '2026-05' (already normalised) and 'MMYYYY' / 'YYYYMM'.
    """
    s = str(raw).strip()
    if len(s) == 6 and s.isdigit():
        mm, yyyy = s[:2], s[2:]
        if 1 <= int(mm) <= 12 and len(yyyy) == 4:
            return f"{yyyy}-{mm}"
        # Try YYYYMM
        yyyy2, mm2 = s[:4], s[4:]
        if 1 <= int(mm2) <= 12:
            return f"{yyyy2}-{mm2}"
    if len(s) == 7 and s[4] == "-":
        return s  # already YYYY-MM
    raise ParseError(f"ret_period has unrecognised format: {s!r}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _get_any(d: dict, *keys: str) -> Any:
    for k in keys:
        if k in d:
            return d[k]
    return None

def parse_gstr3b(raw: Any) -> dict:
    """Parse a decoded GSTR-3B JSON object and return a normalised summary.

    Parameters
    ----------
    raw:
        A ``dict`` (already JSON-decoded) representing the GSTR-3B payload.

    Returns
    -------
    dict with keys:
        ``gstin``, ``ret_period``, ``itc_avl``, ``itc_rev``, ``itc_net``,
        ``itc_inelg``, ``outward_supply``, ``interest_late_fee``

    Raises
    ------
    ParseError
        If ``gstin`` or ``ret_period`` are missing, or required data is absent.
    TypeError
        If *raw* is not a dict.
    """
    if not isinstance(raw, dict):
        raise TypeError(f"GSTR-3B payload must be a dict, got {type(raw).__name__}")

    # 1. Unpack API wrapper if present (e.g. { "status_cd": "1", "data": { ... } })
    if "status_cd" in raw and "data" in raw and isinstance(raw["data"], dict):
        inner = raw["data"]
        if "gstin" not in inner and "gstin" in raw:
            inner["gstin"] = raw["gstin"]
        raw = inner

    # 2. Extract GSTIN and Return Period
    gstin = str(_get_any(raw, "gstin", "GSTIN") or "").strip().upper()
    ret_period_raw = str(_get_any(raw, "ret_period", "rtnprd", "fp", "rtn_prd") or "").strip()

    # Sometimes these are inside the 'data' block if one exists
    data_block = raw.get("data")
    if isinstance(data_block, dict):
        if not gstin:
            gstin = str(_get_any(data_block, "gstin", "GSTIN") or "").strip().upper()
        if not ret_period_raw:
            ret_period_raw = str(_get_any(data_block, "ret_period", "rtnprd", "fp", "rtn_prd") or "").strip()

    if not gstin:
        raise ParseError("Missing required field: gstin")
    if not ret_period_raw:
        raise ParseError("Missing required field: ret_period (or rtnprd/fp/rtn_prd)")

    ret_period = _parse_ret_period(ret_period_raw)

    # 3. Determine where the actual tax data lives
    if isinstance(data_block, dict) and (_get_any(data_block, "itcElg", "itc_elg") or _get_any(data_block, "sup_details")):
        source = data_block
    else:
        source = raw

    # ── ITC eligible section ──────────────────────────────────────────────────
    if "itcElg" not in source and "itc_elg" not in source:
        raise ParseError("Missing required ITC section (itcElg or itc_elg). Unsupported schema.")
        
    itc_elg = _get_any(source, "itcElg", "itc_elg") or {}
    if not isinstance(itc_elg, dict):
        itc_elg = {}

    def _ensure_list(val: Any, field_name: str) -> list[dict]:
        if val == "" or val is None:
            return []
        if isinstance(val, dict):
            return [val]
        if not isinstance(val, list):
            logger.warning("gstr3b_parser: %s is not a list or dict, got %s", field_name, type(val).__name__)
            return []
        return val

    itc_avl_rows   = _ensure_list(_get_any(itc_elg, "itcAvl", "itc_avl"), "itc_avl")
    itc_rev_rows   = _ensure_list(_get_any(itc_elg, "itcRev", "itc_rev"), "itc_rev")
    itc_net_rows   = _ensure_list(_get_any(itc_elg, "itcNet", "itc_net"), "itc_net")
    itc_inelg_rows = _ensure_list(_get_any(itc_elg, "itcInelg", "itc_inelg"), "itc_inelg")

    itc_avl   = _sum_rows(itc_avl_rows)
    itc_rev   = _sum_rows(itc_rev_rows)
    itc_net   = _sum_rows(itc_net_rows)
    itc_inelg = _sum_rows(itc_inelg_rows)

    # ── Outward supplies ──────────────────────────────────────────────────────
    sup_details = _get_any(source, "sup_details") or {}
    if not isinstance(sup_details, dict):
        sup_details = {}

    osup_det = _get_any(sup_details, "osup_det") or {}
    outward_supply = {
        "taxable_value": _safe_num(osup_det.get("txval"), "osup_det.txval"),
        "igst":  _safe_num(osup_det.get("iamt"),  "osup_det.iamt"),
        "cgst":  _safe_num(osup_det.get("camt"),  "osup_det.camt"),
        "sgst":  _safe_num(osup_det.get("samt"),  "osup_det.samt"),
        "cess":  _safe_num(osup_det.get("csamt"), "osup_det.csamt"),
        "total": (
            _safe_num(osup_det.get("txval"), "osup_det.txval")
            + _safe_num(osup_det.get("iamt"),  "osup_det.iamt")
        ),
    }

    # ── Interest and Late Fee ─────────────────────────────────────────────────
    intr_ltfee = _get_any(source, "intr_ltfee", "intr_details") or {}
    if not isinstance(intr_ltfee, dict):
        intr_ltfee = {}

    intr_details = _get_any(intr_ltfee, "intr_details") or intr_ltfee
    interest_late_fee = {
        "igst": _safe_num(intr_details.get("iamt"),  "intr_details.iamt"),
        "cgst": _safe_num(intr_details.get("camt"),  "intr_details.camt"),
        "sgst": _safe_num(intr_details.get("samt"),  "intr_details.samt"),
        "cess": _safe_num(intr_details.get("csamt"), "intr_details.csamt"),
    }

    return {
        "gstin":             gstin,
        "ret_period":        ret_period,          # YYYY-MM
        "ret_period_raw":    ret_period_raw,       # original portal value
        # ITC available (sum of all source rows in itcAvl)
        "itc_avl":           itc_avl,
        # ITC reversed
        "itc_rev":           itc_rev,
        # Net ITC (after reversals, as declared in GSTR-3B)
        "itc_net":           itc_net,
        # Ineligible ITC
        "itc_inelg":         itc_inelg,
        # Outward supply summary from 3.1
        "outward_supply":    outward_supply,
        # Interest / late fee
        "interest_late_fee": interest_late_fee,
    }
