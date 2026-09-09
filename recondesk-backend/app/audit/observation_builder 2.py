"""Build audit observations from persisted reconciliation outputs.

Read-only aggregation: loads existing GSTR-1 ``result_payload`` or purchase
``reconciliation_results`` payload. Never re-runs the matcher or rule engines.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from supabase import Client

from app.audit.observation_rules import (
    OBSERVATION_RULES,
    RULE37_INTEREST_RATE_PA,
    SEVERITY_RANK,
    get_rule_config,
)
from app.database import get_supabase
from app.services.gstr1_run_store import get_gstr1_run
from app.services import reconciliation_outcomes as ro

_OVERDUE_UNPAID = "OVERDUE_UNPAID"
_G1_3B_TIEOUT = "G1_3B_TIEOUT"
_SOURCE_RULE37 = "RULE37_UNPAID_180"
_SOURCE_BLOCKED = "BLOCKED_ITC_17_5"
_SOURCE_TIEOUT = "GSTR1_VS_3B_LIABILITY_MISMATCH"


def build_observations(run_id: str, *, sb: Client | None = None) -> dict[str, Any] | None:
    """Aggregate rule violations for *run_id* into audit observations.

    Returns ``None`` when neither a GSTR-1 nor a purchase run payload exists.
    """
    client = sb if sb is not None else get_supabase()
    rid = str(run_id).strip()
    if not rid:
        return None

    g1_row = get_gstr1_run(client, rid)
    if g1_row is not None:
        payload = g1_row.get("result_payload")
        if not isinstance(payload, dict):
            payload = {}
        items = _collect_gstr1_items(payload)
        return _assemble(rid, items, run_type="gstr1")

    payload = ro.load_payload(client, rid)
    if not payload:
        return None
    items = _collect_purchase_items(payload)
    return _assemble(rid, items, run_type="purchase")


# ── Collection ───────────────────────────────────────────────────────────────


def _collect_gstr1_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in payload.get("mismatches") or []:
        if not isinstance(raw, dict):
            continue
        rule = str(raw.get("mismatch_type") or "").strip()
        if rule not in OBSERVATION_RULES:
            continue
        items.append(
            {
                "source_rule": rule,
                "decision_why": raw.get("decision_why"),
                "decision_next": raw.get("decision_next"),
                "invoice_id": _invoice_id_from_mismatch(raw),
                "row": raw,
            }
        )

    tie_out = payload.get("tie_out") if isinstance(payload.get("tie_out"), dict) else {}
    for raw in tie_out.get("mismatch_decisions") or []:
        if not isinstance(raw, dict):
            continue
        decision_rule = str(raw.get("decision_rule") or raw.get("rule_id") or "").strip()
        if decision_rule != _G1_3B_TIEOUT:
            continue
        items.append(
            {
                "source_rule": _SOURCE_TIEOUT,
                "decision_why": raw.get("decision_why"),
                "decision_next": raw.get("decision_next"),
                "invoice_id": str(raw.get("field") or "tie_out").strip() or "tie_out",
                "row": raw,
            }
        )
    return items


def _collect_purchase_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    for raw in _merged_rule37_rows(payload):
        if str(raw.get("status") or "").strip() != _OVERDUE_UNPAID:
            continue
        inv = str(raw.get("invoice_number") or "").strip()
        pr_id = str(raw.get("pr_id") or "").strip()
        items.append(
            {
                "source_rule": _SOURCE_RULE37,
                "decision_why": raw.get("decision_why"),
                "decision_next": raw.get("decision_next"),
                "invoice_id": pr_id or inv or "unknown",
                "row": raw,
            }
        )

    for raw in _merged_section175_rows(payload):
        inv = str(raw.get("invoice_number") or raw.get("invoice_no") or "").strip()
        gst = str(raw.get("supplier_gstin") or "").strip()
        items.append(
            {
                "source_rule": _SOURCE_BLOCKED,
                "decision_why": raw.get("decision_why"),
                "decision_next": raw.get("decision_next"),
                "invoice_id": f"{gst}|{inv}" if (gst or inv) else "unknown",
                "row": raw,
            }
        )
    return items


def _merged_rule37_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge decisions.rule37 over compliance.rule37 (decisions carry WHY/NEXT)."""
    dec = payload.get("decisions") if isinstance(payload.get("decisions"), dict) else {}
    comp = payload.get("compliance") if isinstance(payload.get("compliance"), dict) else {}
    merged: dict[str, dict[str, Any]] = {}

    def _key(item: dict[str, Any]) -> str:
        pr = str(item.get("pr_id") or "").strip()
        if pr:
            return f"pr:{pr}"
        inv = str(item.get("invoice_number") or "").strip()
        gst = str(item.get("supplier_gstin") or "").strip()
        return f"{gst}|{inv}"

    for item in list(comp.get("rule37") or []):
        if isinstance(item, dict):
            k = _key(item)
            if k.strip("|"):
                merged[k] = dict(item)
    for item in list(dec.get("rule37") or []):
        if not isinstance(item, dict):
            continue
        k = _key(item)
        if not k.strip("|"):
            continue
        base = merged.get(k, {})
        overlay = {kk: vv for kk, vv in item.items() if vv not in (None, "")}
        merged[k] = {**base, **overlay}
    return list(merged.values())


def _merged_section175_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    dec = payload.get("decisions") if isinstance(payload.get("decisions"), dict) else {}
    comp = payload.get("compliance") if isinstance(payload.get("compliance"), dict) else {}
    dec_list = list(dec.get("section_17_5") or dec.get("section_175") or [])
    comp_list = list(comp.get("section_17_5") or comp.get("section_175") or [])

    def _key(item: dict[str, Any]) -> str:
        inv = str(item.get("invoice_number") or item.get("invoice_no") or "").strip()
        gst = str(item.get("supplier_gstin") or "").strip()
        return f"{gst}|{inv}"

    merged: dict[str, dict[str, Any]] = {}
    for item in comp_list:
        if isinstance(item, dict):
            k = _key(item)
            if k.strip("|"):
                merged[k] = dict(item)
    for item in dec_list:
        if not isinstance(item, dict):
            continue
        k = _key(item)
        if not k.strip("|"):
            continue
        base = merged.get(k, {})
        overlay = {kk: vv for kk, vv in item.items() if vv not in (None, "")}
        merged[k] = {**base, **overlay}
    return list(merged.values())


# ── Impact ───────────────────────────────────────────────────────────────────


def _paise_to_rupees(paise: Any) -> float | None:
    try:
        return round(abs(int(paise)) / 100.0, 2)
    except (TypeError, ValueError):
        return None


def _as_rupees(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(abs(float(value)), 2)
    except (TypeError, ValueError):
        return None


def _tax_amount_rupees(row: dict[str, Any]) -> float | None:
    for key in ("total_tax_paise", "igst_paise"):
        if row.get(key) is not None:
            return _paise_to_rupees(row.get(key))
    for key in ("total_tax", "amount"):
        if row.get(key) is not None:
            return _as_rupees(row.get(key))
    return None


def _tax_differential_rupees(row: dict[str, Any]) -> float | None:
    for key in ("tax_diff_paise", "diff_paise", "taxable_diff_paise"):
        if row.get(key) is not None:
            return _paise_to_rupees(row.get(key))
    sr = row.get("sr_tax_paise")
    g1 = row.get("gstr1_tax_paise")
    if sr is not None and g1 is not None:
        try:
            return round(abs(int(sr) - int(g1)) / 100.0, 2)
        except (TypeError, ValueError):
            pass
    gstr1_p = row.get("gstr1_paise")
    gstr3b_p = row.get("gstr3b_paise")
    if gstr1_p is not None and gstr3b_p is not None:
        try:
            return round(abs(int(gstr1_p) - int(gstr3b_p)) / 100.0, 2)
        except (TypeError, ValueError):
            pass
    return None


def _itc_amount_rupees(row: dict[str, Any]) -> float | None:
    if row.get("estimated_itc_amount") is not None:
        return _as_rupees(row.get("estimated_itc_amount"))
    if row.get("itc_at_risk_paise") is not None:
        return _paise_to_rupees(row.get("itc_at_risk_paise"))
    if row.get("estimated_itc_paise") is not None:
        return _paise_to_rupees(row.get("estimated_itc_paise"))
    if row.get("amount") is not None:
        return _as_rupees(row.get("amount"))
    return _tax_amount_rupees(row)


def _days_overdue(row: dict[str, Any]) -> int:
    """Days past the 180-day deadline. ``days_remaining`` is negative when overdue.

    Used only when ``itc_claimed_period`` is absent — a lower-bound proxy for
    Rule 37(3) interest (which should run from ITC availment until reversal).
    """
    days_remaining = row.get("days_remaining")
    if days_remaining is not None:
        try:
            return max(0, -int(days_remaining))
        except (TypeError, ValueError):
            pass
    return 0


def _gstr3b_claim_date_proxy(itc_claimed_period: str) -> date | None:
    """GSTR-3B due date proxy: 20th of the month following *itc_claimed_period*.

    e.g. ``\"2026-06\"`` / ``\"2026-06-01\"`` → ``2026-07-20``.
    """
    s = str(itc_claimed_period or "").strip()
    if len(s) < 7 or s[4] != "-":
        return None
    try:
        y = int(s[0:4])
        m = int(s[5:7])
        if m < 1 or m > 12:
            return None
    except ValueError:
        return None
    if m == 12:
        return date(y + 1, 1, 20)
    return date(y, m + 1, 20)


def _interest_days_and_source(
    row: dict[str, Any], *, today: date | None = None
) -> tuple[int, bool]:
    """Return ``(days, used_claim_proxy)`` for Rule 37(3) interest.

    When ``itc_claimed_period`` is present, days run from the GSTR-3B due-date
    proxy (20th of following month) to *today*. Otherwise falls back to days past
    the 180-day payment deadline (lower bound).
    """
    period = row.get("itc_claimed_period")
    if period is not None and str(period).strip():
        claim = _gstr3b_claim_date_proxy(str(period))
        if claim is not None:
            as_of = today if today is not None else date.today()
            return max(0, (as_of - claim).days), True
    return _days_overdue(row), False


# Surfaced on RULE37_UNPAID_180 observations when claim period is unknown so the
# ₹ figure is not mistaken for full Rule 37(3) liability.
_RULE37_IMPACT_LOWER_BOUND_NOTE = (
    "Interest calculated from the 180-day due date, not full Rule 37(3) "
    "liability — treat as a lower bound."
)


def _itc_plus_interest_rupees(
    row: dict[str, Any], *, today: date | None = None
) -> float | None:
    itc = _itc_amount_rupees(row)
    if itc is None:
        return None
    days, _ = _interest_days_and_source(row, today=today)
    interest = itc * RULE37_INTEREST_RATE_PA * (days / 365.0)
    return round(itc + interest, 2)


def compute_financial_impact(source_rule: str, row: dict[str, Any]) -> float | None:
    """Compute ₹ financial impact for one violation row."""
    cfg = get_rule_config(source_rule)
    if cfg is None:
        return None
    impact_type = cfg["impact_type"]
    if impact_type == "none":
        return None
    if impact_type == "tax_amount":
        return _tax_amount_rupees(row)
    if impact_type == "tax_differential":
        return _tax_differential_rupees(row)
    if impact_type == "itc_amount":
        return _itc_amount_rupees(row)
    if impact_type == "itc_plus_interest":
        return _itc_plus_interest_rupees(row)
    return None


# ── Assemble ─────────────────────────────────────────────────────────────────


def _invoice_id_from_mismatch(raw: dict[str, Any]) -> str:
    inv = str(raw.get("invoice_number") or "").strip()
    if inv:
        return inv
    # Series / docs-issued rows may use other identity fields
    for key in ("series_prefix", "gap_start", "issue_type", "field"):
        v = str(raw.get(key) or "").strip()
        if v:
            return v
    return "unknown"


def _assemble(
    run_id: str,
    items: list[dict[str, Any]],
    *,
    run_type: str,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[item["source_rule"]].append(item)

    observations: list[dict[str, Any]] = []
    counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    total_impact = 0.0

    for source_rule, group in grouped.items():
        cfg = get_rule_config(source_rule)
        if cfg is None:
            continue
        title = cfg["title"]
        severity = cfg["severity"]
        impacts: list[float] = []
        invoice_ids: list[str] = []
        description = title
        recommendation = title

        for item in group:
            why = str(item.get("decision_why") or "").strip()
            nxt = str(item.get("decision_next") or "").strip()
            if why and description == title:
                description = why
            if nxt and recommendation == title:
                recommendation = nxt
            inv = str(item.get("invoice_id") or "").strip()
            if inv and inv not in invoice_ids:
                invoice_ids.append(inv)
            impact = compute_financial_impact(source_rule, item.get("row") or {})
            if impact is not None:
                impacts.append(impact)

        if cfg["impact_type"] == "none":
            financial_impact: float | None = None
        elif impacts:
            financial_impact = round(sum(impacts), 2)
            total_impact += financial_impact
        else:
            financial_impact = None

        used_claim_proxy = False
        if source_rule == _SOURCE_RULE37:
            used_claim_proxy = any(
                _interest_days_and_source(item.get("row") or {})[1] for item in group
            )
            if not used_claim_proxy:
                # Honest labelling when claim period unknown: deadline-based lower bound.
                description = (
                    f"{description} {_RULE37_IMPACT_LOWER_BOUND_NOTE}".strip()
                    if description
                    else _RULE37_IMPACT_LOWER_BOUND_NOTE
                )

        counts[severity] = counts.get(severity, 0) + 1
        obs: dict[str, Any] = {
            "observation_id": f"{run_id}:{source_rule}",
            "source_rule": source_rule,
            "severity": severity,
            "section_reference": cfg["section_reference"],
            "title": title,
            "description": description,
            "financial_impact": financial_impact,
            "affected_count": len(group),
            "recommendation": recommendation,
        }
        if (
            source_rule == _SOURCE_RULE37
            and financial_impact is not None
            and not used_claim_proxy
        ):
            # Separate from financial_impact so UIs do not treat the ₹ as full liability.
            obs["financial_impact_note"] = _RULE37_IMPACT_LOWER_BOUND_NOTE
        if source_rule == _SOURCE_TIEOUT:
            # Period-level field variances (taxable_value / igst / …), not invoice IDs.
            # Frontend must not use these for invoice lookups or deeplinks.
            obs["linked_fields"] = invoice_ids
        else:
            obs["linked_invoice_ids"] = invoice_ids
        observations.append(obs)

    observations.sort(
        key=lambda o: (
            SEVERITY_RANK.get(str(o["severity"]), 99),
            str(o["source_rule"]),
        )
    )

    return {
        "run_id": run_id,
        "run_type": run_type,
        "summary": {
            "critical_count": counts.get("Critical", 0),
            "high_count": counts.get("High", 0),
            "medium_count": counts.get("Medium", 0),
            "low_count": counts.get("Low", 0),
            "total_financial_impact": round(total_impact, 2),
        },
        "observations": observations,
    }
