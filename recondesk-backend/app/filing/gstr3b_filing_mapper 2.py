"""GSTR-3B filing payload mapper and system figure helpers.

Ensures GSTN system-calculated fields (such as late fees computed by GSTN for
late-filed periods) are preserved unchanged in the Save payload and never zeroed out.
"""

from __future__ import annotations

from typing import Any, Mapping


def _clean_num(val: Any) -> int | float:
    if val is None or val == "":
        return 0
    try:
        n = float(val)
        return int(n) if n.is_integer() else n
    except (TypeError, ValueError):
        return 0


def extract_system_late_fee(details_data: Mapping[str, Any] | None) -> dict[str, int | float]:
    """Extract GSTN system-calculated late fee ({camt, samt}) from Get Details response.

    Returns dict with 'camt' and 'samt' (int or float).
    Defaults to {'camt': 0, 'samt': 0} if not present or missing.
    """
    if not isinstance(details_data, dict):
        return {"camt": 0, "samt": 0}

    intr_ltfee = details_data.get("intr_ltfee")
    if not isinstance(intr_ltfee, dict):
        return {"camt": 0, "samt": 0}

    ltfee_raw = intr_ltfee.get("ltfee_details")
    if not isinstance(ltfee_raw, dict):
        return {"camt": 0, "samt": 0}

    camt_raw = ltfee_raw.get("camt")
    samt_raw = ltfee_raw.get("samt")

    return {
        "camt": _clean_num(camt_raw),
        "samt": _clean_num(samt_raw),
    }


def normalize_gstr3b_save_body(
    save_body: Mapping[str, Any],
    details_data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Sanitize and format save_body for GSTN GSTR-3B Save API.

    1. Ensures itc_elg.itc_net is formatted as a single object {iamt, camt, samt, csamt}
       rather than an array of typed rows [ { ty: "", ... } ]. GSTN rejects itc_net as an array with RT-3BGC-9003.
    2. Ensures intr_ltfee.ltfee_details retains GSTN's system-calculated late fee from Get Details.
    """
    out = dict(save_body)

    # 1. Normalize itc_net in itc_elg
    itc_elg = dict(out.get("itc_elg") or {})
    if "itc_net" in itc_elg:
        itc_net_raw = itc_elg["itc_net"]
        if isinstance(itc_net_raw, list):
            first = itc_net_raw[0] if itc_net_raw and isinstance(itc_net_raw[0], dict) else {}
            itc_elg["itc_net"] = {
                "iamt": _clean_num(first.get("iamt")),
                "camt": _clean_num(first.get("camt")),
                "samt": _clean_num(first.get("samt")),
                "csamt": _clean_num(first.get("csamt")),
            }
        elif not isinstance(itc_net_raw, dict):
            itc_elg["itc_net"] = {"iamt": 0, "camt": 0, "samt": 0, "csamt": 0}
        out["itc_elg"] = itc_elg

    # 2. Overlay system late fee
    sys_ltfee = extract_system_late_fee(details_data)
    intr_ltfee = dict(out.get("intr_ltfee") or {})
    intr_ltfee["ltfee_details"] = {
        "camt": sys_ltfee["camt"],
        "samt": sys_ltfee["samt"],
    }
    out["intr_ltfee"] = intr_ltfee

    return out


def apply_system_late_fee_to_save_body(
    save_body: Mapping[str, Any],
    details_data: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return normalize_gstr3b_save_body(save_body, details_data)
