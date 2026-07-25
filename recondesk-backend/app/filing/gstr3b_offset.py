"""GSTR-3B Offset Liability body builder + structural equality.

``build_gstr3b_offset_body(details, ledger)`` is the **single** source of truth
used by:

* ``GET …/offset-preview`` (what the CA confirms)
* ``POST …/offset`` stale-check (recompute before Sandbox)

Both paths must call this helper so a confirmation screen cannot drift from
what Offset validates.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping


class Gstr3bOffsetBuildError(ValueError):
    """Cannot derive ``{pdcash, pditc}`` from Get Details + ledger."""


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def _head_tx(row: Mapping[str, Any], head: str) -> int:
    nested = row.get(head)
    if isinstance(nested, Mapping):
        return _as_int(nested.get("tx"))
    return 0


def _cash_tx(cash_bal: Mapping[str, Any], head: str) -> int:
    nested = cash_bal.get(head)
    if isinstance(nested, Mapping):
        return _as_int(nested.get("tx"))
    return 0


def extract_offset_pair(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize to ``{pdcash, pditc}`` only (ignore session/routing fields)."""
    raw = _as_dict(payload)
    pdcash = raw.get("pdcash")
    pditc = raw.get("pditc")
    return {
        "pdcash": copy.deepcopy(pdcash) if isinstance(pdcash, list) else [],
        "pditc": copy.deepcopy(pditc) if isinstance(pditc, Mapping) else {},
    }


def offset_bodies_equal(
    left: Mapping[str, Any] | None,
    right: Mapping[str, Any] | None,
) -> bool:
    """Structural deep-equal on ``{pdcash, pditc}`` only."""
    return extract_offset_pair(left) == extract_offset_pair(right)


def _empty_pditc(*, liab_ldg_id: int, trans_typ: int) -> dict[str, Any]:
    return {
        "liab_ldg_id": liab_ldg_id,
        "trans_typ": trans_typ,
        "i_pdi": 0,
        "i_pdc": 0,
        "i_pds": 0,
        "c_pdi": 0,
        "c_pdc": 0,
        "s_pdi": 0,
        "s_pds": 0,
        "cs_pdcs": 0,
    }


def _empty_pdcash_row(*, liab_ldg_id: int, trans_typ: int) -> dict[str, Any]:
    return {
        "liab_ldg_id": liab_ldg_id,
        "trans_typ": trans_typ,
        "ipd": 0,
        "cpd": 0,
        "spd": 0,
        "cspd": 0,
        "i_intrpd": 0,
        "c_intrpd": 0,
        "s_intrpd": 0,
        "cs_intrpd": 0,
        "c_lfeepd": 0,
        "s_lfeepd": 0,
    }


def _proposed_from_details(details: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return GSTN-proposed ``{pdcash, pditc}`` when Get Details already has them."""
    tx_pmt = _as_dict(details.get("tx_pmt"))
    # Some envelopes nest payment under tx_pmt; others expose at top level.
    pdcash = tx_pmt.get("pdcash")
    pditc = tx_pmt.get("pditc")
    if not isinstance(pdcash, list):
        pdcash = details.get("pdcash")
    if not isinstance(pditc, Mapping):
        pditc = details.get("pditc")
    if isinstance(pdcash, list) and isinstance(pditc, Mapping) and (
        pdcash or pditc
    ):
        return {
            "pdcash": copy.deepcopy(pdcash),
            "pditc": copy.deepcopy(dict(pditc)),
        }
    return None


def _take(available: dict[str, int], key: str, need: int) -> int:
    if need <= 0:
        return 0
    have = max(0, available.get(key, 0))
    used = min(have, need)
    available[key] = have - used
    return used


def _synthesize_from_net_tax_pay(
    details: Mapping[str, Any],
    ledger: Mapping[str, Any],
) -> dict[str, Any]:
    """Build Offset body from ``tx_pmt.net_tax_pay`` + cash/ITC ledger balances.

    Allocation (deterministic, same-head first; IGST ITC may cross to CGST/SGST):
    1. Same-head ITC
    2. IGST ITC → remaining CGST / SGST (split evenly leftover preference CGST)
    3. Remaining tax → electronic cash ledger
    Reverse-charge rows (``trans_typ == 30003``) are cash-only (no ITC).
    """
    tx_pmt = _as_dict(details.get("tx_pmt"))
    net_rows = tx_pmt.get("net_tax_pay")
    if not isinstance(net_rows, list) or not net_rows:
        raise Gstr3bOffsetBuildError(
            "Cannot build GSTR-3B offset body: Get Details has no "
            "tx_pmt.pdcash/pditc and no tx_pmt.net_tax_pay"
        )

    itc_bal = _as_dict(ledger.get("itc_bal"))
    cash_bal = _as_dict(ledger.get("cash_bal"))
    itc_avail = {
        "igst": _as_int(itc_bal.get("igst_bal")),
        "cgst": _as_int(itc_bal.get("cgst_bal")),
        "sgst": _as_int(itc_bal.get("sgst_bal")),
        "cess": _as_int(itc_bal.get("cess_bal")),
    }
    cash_avail = {
        "igst": _cash_tx(cash_bal, "igst"),
        "cgst": _cash_tx(cash_bal, "cgst"),
        "sgst": _cash_tx(cash_bal, "sgst"),
        "cess": _cash_tx(cash_bal, "cess"),
    }

    # Prefer liab_ldg_id from any already-proposed pdcash rows keyed by trans_typ.
    proposed = _proposed_from_details(details)
    liab_by_trans: dict[int, int] = {}
    if proposed:
        for row in proposed["pdcash"]:
            if isinstance(row, Mapping):
                tt = _as_int(row.get("trans_typ"))
                liab_by_trans[tt] = _as_int(row.get("liab_ldg_id"))

    pdcash: list[dict[str, Any]] = []
    pditc: dict[str, Any] | None = None

    for row in net_rows:
        if not isinstance(row, Mapping):
            continue
        trans_typ = _as_int(row.get("trans_typ"))
        liab_id = liab_by_trans.get(trans_typ, _as_int(row.get("liab_ldg_id")))
        i_due = _head_tx(row, "igst")
        c_due = _head_tx(row, "cgst")
        s_due = _head_tx(row, "sgst")
        cs_due = _head_tx(row, "cess")

        i_pdi = i_pdc = i_pds = c_pdi = c_pdc = s_pdi = s_pds = cs_pdcs = 0

        # ITC only on non-RCM (30002). 30003 / others → cash.
        if trans_typ == 30002:
            i_pdi = _take(itc_avail, "igst", i_due)
            i_due -= i_pdi
            c_pdc = _take(itc_avail, "cgst", c_due)
            c_due -= c_pdc
            s_pds = _take(itc_avail, "sgst", s_due)
            s_due -= s_pds
            cs_pdcs = _take(itc_avail, "cess", cs_due)
            cs_due -= cs_pdcs
            # Cross-utilize leftover IGST ITC against CGST then SGST.
            i_pdc = _take(itc_avail, "igst", c_due)
            c_due -= i_pdc
            i_pds = _take(itc_avail, "igst", s_due)
            s_due -= i_pds

            pditc = {
                "liab_ldg_id": liab_id,
                "trans_typ": trans_typ,
                "i_pdi": i_pdi,
                "i_pdc": i_pdc,
                "i_pds": i_pds,
                "c_pdi": c_pdi,
                "c_pdc": c_pdc,
                "s_pdi": s_pdi,
                "s_pds": s_pds,
                "cs_pdcs": cs_pdcs,
            }

        cash_row = _empty_pdcash_row(liab_ldg_id=liab_id, trans_typ=trans_typ)
        cash_row["ipd"] = _take(cash_avail, "igst", i_due)
        cash_row["cpd"] = _take(cash_avail, "cgst", c_due)
        cash_row["spd"] = _take(cash_avail, "sgst", s_due)
        cash_row["cspd"] = _take(cash_avail, "cess", cs_due)
        pdcash.append(cash_row)

    if pditc is None:
        # GSTN still expects a pditc object; use first row's ids when present.
        first = net_rows[0] if isinstance(net_rows[0], Mapping) else {}
        tt = _as_int(first.get("trans_typ")) or 30002
        lid = liab_by_trans.get(tt, _as_int(first.get("liab_ldg_id")))
        pditc = _empty_pditc(liab_ldg_id=lid, trans_typ=tt)

    return {"pdcash": pdcash, "pditc": pditc}


def _cap_pdcash_against_ledger(
    pdcash: list[Any],
    cash_avail: dict[str, int],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in pdcash:
        if not isinstance(row, Mapping):
            continue
        capped = dict(row)
        capped["ipd"] = _take(cash_avail, "igst", _as_int(row.get("ipd")))
        capped["cpd"] = _take(cash_avail, "cgst", _as_int(row.get("cpd")))
        capped["spd"] = _take(cash_avail, "sgst", _as_int(row.get("spd")))
        capped["cspd"] = _take(cash_avail, "cess", _as_int(row.get("cspd")))
        out.append(capped)
    return out


def _cap_pditc_against_ledger(
    pditc: Mapping[str, Any],
    itc_avail: dict[str, int],
) -> dict[str, Any]:
    """Cap ITC utilization fields; IGST pool is shared across i_pdi/i_pdc/i_pds."""
    capped = dict(pditc)
    capped["i_pdi"] = _take(itc_avail, "igst", _as_int(pditc.get("i_pdi")))
    capped["i_pdc"] = _take(itc_avail, "igst", _as_int(pditc.get("i_pdc")))
    capped["i_pds"] = _take(itc_avail, "igst", _as_int(pditc.get("i_pds")))
    capped["c_pdi"] = _take(itc_avail, "cgst", _as_int(pditc.get("c_pdi")))
    capped["c_pdc"] = _take(itc_avail, "cgst", _as_int(pditc.get("c_pdc")))
    capped["s_pdi"] = _take(itc_avail, "sgst", _as_int(pditc.get("s_pdi")))
    capped["s_pds"] = _take(itc_avail, "sgst", _as_int(pditc.get("s_pds")))
    capped["cs_pdcs"] = _take(itc_avail, "cess", _as_int(pditc.get("cs_pdcs")))
    return capped


def _apply_ledger_caps(
    body: Mapping[str, Any],
    ledger: Mapping[str, Any],
) -> dict[str, Any]:
    """Reduce proposed cash/ITC amounts to what the current ledger can fund.

    Ensures ledger balance is part of the confirmation identity: a drop in
    ITC or cash between preview and Offset changes the computed body.
    """
    itc_bal = _as_dict(ledger.get("itc_bal"))
    cash_bal = _as_dict(ledger.get("cash_bal"))
    itc_avail = {
        "igst": _as_int(itc_bal.get("igst_bal")),
        "cgst": _as_int(itc_bal.get("cgst_bal")),
        "sgst": _as_int(itc_bal.get("sgst_bal")),
        "cess": _as_int(itc_bal.get("cess_bal")),
    }
    cash_avail = {
        "igst": _cash_tx(cash_bal, "igst"),
        "cgst": _cash_tx(cash_bal, "cgst"),
        "sgst": _cash_tx(cash_bal, "sgst"),
        "cess": _cash_tx(cash_bal, "cess"),
    }
    pair = extract_offset_pair(body)
    return {
        "pdcash": _cap_pdcash_against_ledger(pair["pdcash"], cash_avail),
        "pditc": _cap_pditc_against_ledger(pair["pditc"], itc_avail)
        if pair["pditc"]
        else _empty_pditc(liab_ldg_id=0, trans_typ=30002),
    }


def build_gstr3b_offset_body(
    details: Mapping[str, Any] | None,
    ledger: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compute the Offset Liability body from Get Details + ledger balance.

    Prefer GSTN-proposed ``tx_pmt.pdcash`` / ``tx_pmt.pditc`` when present
    (typical after a successful Save). Otherwise synthesize from
    ``tx_pmt.net_tax_pay`` using ledger ITC then cash.

    Ledger caps are always applied so both inputs affect the result.
    """
    details_d = _as_dict(details)
    ledger_d = _as_dict(ledger)
    proposed = _proposed_from_details(details_d)
    if proposed is not None:
        return _apply_ledger_caps(proposed, ledger_d)
    synthesized = _synthesize_from_net_tax_pay(details_d, ledger_d)
    return _apply_ledger_caps(synthesized, ledger_d)
