"""GSTR-3B filing payload mapper and system figure helpers.

Ensures GSTN system-calculated fields (such as late fees computed by GSTN for
late-filed periods) are preserved unchanged in the Save payload and never zeroed out.
"""

from __future__ import annotations

from typing import Any, Mapping


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

    def _clean_num(val: Any) -> int | float:
        if val is None or val == "":
            return 0
        try:
            n = float(val)
            return int(n) if n.is_integer() else n
        except (TypeError, ValueError):
            return 0

    return {
        "camt": _clean_num(camt_raw),
        "samt": _clean_num(samt_raw),
    }


def apply_system_late_fee_to_save_body(
    save_body: Mapping[str, Any],
    details_data: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Ensure ltfee_details in save_body retains GSTN's system-calculated late fee.

    If GSTN system has a nonzero late fee (e.g. camt: 150, samt: 150), pass it through
    unchanged in ltfee_details. If GSTN system is zero (on-time period), zero passes through as-is.
    """
    out = dict(save_body)
    sys_ltfee = extract_system_late_fee(details_data)

    intr_ltfee = dict(out.get("intr_ltfee") or {})
    intr_ltfee["ltfee_details"] = {
        "camt": sys_ltfee["camt"],
        "samt": sys_ltfee["samt"],
    }
    out["intr_ltfee"] = intr_ltfee
    return out
