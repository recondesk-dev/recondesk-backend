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
        "inward_sup": {
          "isup_details": [ {"ty": "GST", "inter": 0, "intra": 0}, ... ]
        },
        "intr_ltfee": {
          "intr_details": {"iamt": 0, "camt": 0, "samt": 0, "csamt": 0},
          "ltfee_details": {"camt": 0, "samt": 0}
        }
      }
    }

Missing optional blocks/keys default to zeros — never a parse failure.
``outward_supply`` (3.1(a)) and lump ``itc_net`` / ``itc_avl`` sums keep their
existing semantics; newer fields are additive.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Canonical ITC-available source codes (Table 4A).
_ITC_AVL_TYPES: tuple[str, ...] = ("IMPG", "IMPS", "ISRC", "ISD", "OTH")

# Portal / offline-tool labels → canonical ty.
_ITC_TY_ALIASES: dict[str, str] = {
    "ALL OTHER ITC": "OTH",
    "ALL OTHER": "OTH",
    "OTHER": "OTH",
    "OTH": "OTH",
    "IMPG": "IMPG",
    "IMPS": "IMPS",
    "ISRC": "ISRC",
    "ISD": "ISD",
}


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


def _zero_tax_heads() -> dict[str, float]:
    return {"igst": 0.0, "cgst": 0.0, "sgst": 0.0, "cess": 0.0}


def _parse_supply_row(row: Any, label: str) -> dict[str, float]:
    """Parse a Table 3.1 supply object; missing/invalid → zeros."""
    if not isinstance(row, dict):
        return {
            "taxable_value": 0.0,
            "igst": 0.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
        }
    return {
        "taxable_value": _safe_num(row.get("txval"), f"{label}.txval"),
        "igst":  _safe_num(row.get("iamt"),  f"{label}.iamt"),
        "cgst":  _safe_num(row.get("camt"),  f"{label}.camt"),
        "sgst":  _safe_num(row.get("samt"),  f"{label}.samt"),
        "cess":  _safe_num(row.get("csamt"), f"{label}.csamt"),
    }


def _normalize_itc_ty(raw: Any) -> str:
    """Map portal ty labels to canonical IMPG/IMPS/ISRC/ISD/OTH."""
    s = str(raw or "").strip()
    if not s:
        return "OTH"
    key = s.upper()
    if key in _ITC_TY_ALIASES:
        return _ITC_TY_ALIASES[key]
    # Fuzzy: "All other ITC" with odd spacing/punctuation
    compact = " ".join(key.replace("_", " ").split())
    if compact in _ITC_TY_ALIASES:
        return _ITC_TY_ALIASES[compact]
    if "OTHER" in compact and "ITC" in compact:
        return "OTH"
    if key in _ITC_AVL_TYPES:
        return key
    logger.warning("gstr3b_parser: unknown itcAvl ty %r, mapping to OTH", raw)
    return "OTH"


def _breakdown_itc_avl(rows: list[dict]) -> dict[str, dict[str, float]]:
    """Sum itcAvl rows by normalised source ty. Always includes all 5 keys."""
    out: dict[str, dict[str, float]] = {ty: _zero_tax_heads() for ty in _ITC_AVL_TYPES}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ty = _normalize_itc_ty(row.get("ty"))
        bucket = out.setdefault(ty, _zero_tax_heads())
        bucket["igst"] += _safe_num(row.get("iamt"), f"itcAvl[{ty}].iamt")
        bucket["cgst"] += _safe_num(row.get("camt"), f"itcAvl[{ty}].camt")
        bucket["sgst"] += _safe_num(row.get("samt"), f"itcAvl[{ty}].samt")
        bucket["cess"] += _safe_num(row.get("csamt"), f"itcAvl[{ty}].csamt")
    # Round for stable floats
    for ty, heads in out.items():
        out[ty] = {k: round(v, 2) for k, v in heads.items()}
    return out


def _parse_inward_sup(raw: Any) -> list[dict[str, Any]]:
    """Parse Table 5 inward exempt/nil/non-GST; missing → []."""
    if not isinstance(raw, dict):
        return []
    details = raw.get("isup_details") or raw.get("isupDetails") or []
    if isinstance(details, dict):
        details = [details]
    if not isinstance(details, list):
        return []
    out: list[dict[str, Any]] = []
    for row in details:
        if not isinstance(row, dict):
            continue
        out.append({
            "ty": str(row.get("ty") or "").strip().upper() or "GST",
            "inter": _safe_num(row.get("inter"), "inward_sup.inter"),
            "intra": _safe_num(row.get("intra"), "inward_sup.intra"),
        })
    return out


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
        ``itc_inelg``, ``itc_avl_by_source``, ``outward_supply``,
        ``osup_zero``, ``osup_nil_exmp``, ``isup_rev``, ``osup_nongst``,
        ``inward_sup``, ``interest_late_fee``, ``late_fee``

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
    itc_avl_by_source = _breakdown_itc_avl(itc_avl_rows)

    # ── Outward supplies (Table 3.1) ──────────────────────────────────────────
    sup_details = _get_any(source, "sup_details") or {}
    if not isinstance(sup_details, dict):
        sup_details = {}

    osup_det = _get_any(sup_details, "osup_det") or {}
    if not isinstance(osup_det, dict):
        osup_det = {}
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

    # Additive 3.1(b–e) — omitted keys → zeros
    osup_zero     = _parse_supply_row(_get_any(sup_details, "osup_zero"), "osup_zero")
    osup_nil_exmp = _parse_supply_row(_get_any(sup_details, "osup_nil_exmp"), "osup_nil_exmp")
    isup_rev      = _parse_supply_row(_get_any(sup_details, "isup_rev"), "isup_rev")
    osup_nongst   = _parse_supply_row(_get_any(sup_details, "osup_nongst"), "osup_nongst")

    # ── Table 5 inward exempt / nil / non-GST ─────────────────────────────────
    inward_sup = _parse_inward_sup(_get_any(source, "inward_sup"))

    # ── Interest and Late Fee (Table 5.1) ─────────────────────────────────────
    intr_ltfee = _get_any(source, "intr_ltfee") or {}
    if not isinstance(intr_ltfee, dict):
        intr_ltfee = {}

    # Prefer nested intr_details; only fall back to the block itself when it
    # looks like a flat interest object (has tax keys, no ltfee_details).
    nested_intr = _get_any(intr_ltfee, "intr_details")
    if isinstance(nested_intr, dict):
        intr_details = nested_intr
    elif any(k in intr_ltfee for k in ("iamt", "camt", "samt", "csamt")) and "ltfee_details" not in intr_ltfee:
        intr_details = intr_ltfee
    else:
        intr_details = {}

    interest_late_fee = {
        "igst": _safe_num(intr_details.get("iamt"),  "intr_details.iamt"),
        "cgst": _safe_num(intr_details.get("camt"),  "intr_details.camt"),
        "sgst": _safe_num(intr_details.get("samt"),  "intr_details.samt"),
        "cess": _safe_num(intr_details.get("csamt"), "intr_details.csamt"),
    }

    ltfee_raw = _get_any(intr_ltfee, "ltfee_details") or {}
    if not isinstance(ltfee_raw, dict):
        ltfee_raw = {}
    late_fee = {
        "cgst": _safe_num(ltfee_raw.get("camt"), "ltfee_details.camt"),
        "sgst": _safe_num(ltfee_raw.get("samt"), "ltfee_details.samt"),
        # Portal late fee is CGST+SGST only; keep igst/cess for shape consistency
        "igst": _safe_num(ltfee_raw.get("iamt"), "ltfee_details.iamt"),
        "cess": _safe_num(ltfee_raw.get("csamt"), "ltfee_details.csamt"),
    }

    return {
        "gstin":             gstin,
        "ret_period":        ret_period,          # YYYY-MM
        "ret_period_raw":    ret_period_raw,       # original portal value
        # ITC available (sum of all source rows in itcAvl) — unchanged semantics
        "itc_avl":           itc_avl,
        # ITC reversed
        "itc_rev":           itc_rev,
        # Net ITC (after reversals, as declared in GSTR-3B) — unchanged semantics
        "itc_net":           itc_net,
        # Ineligible ITC
        "itc_inelg":         itc_inelg,
        # Additive: Table 4A by source
        "itc_avl_by_source": itc_avl_by_source,
        # Outward supply summary from 3.1(a) — unchanged semantics
        "outward_supply":    outward_supply,
        # Additive: Table 3.1(b–e)
        "osup_zero":         osup_zero,
        "osup_nil_exmp":     osup_nil_exmp,
        "isup_rev":          isup_rev,
        "osup_nongst":       osup_nongst,
        # Additive: Table 5
        "inward_sup":        inward_sup,
        # Interest (existing key; still wired)
        "interest_late_fee": interest_late_fee,
        # Additive: late fee only
        "late_fee":          late_fee,
    }
