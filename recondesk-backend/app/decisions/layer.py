"""Decision layer — enriches reconciliation rows with structured what/why/next decisions."""
from __future__ import annotations
from typing import Any

from app.services.decision_templates import DecisionOutput, generate_decision


def _row_identity_fields(row: dict[str, Any]) -> list[str]:
    """Field names known present on *row* (no inference beyond non-empty keys)."""
    out: list[str] = []
    if row.get("supplier_gstin"):
        out.append("gstin")
    inv = row.get("invoice_number_normalized")
    if inv is None or str(inv).strip() == "":
        inv = row.get("invoice_number")
    if inv not in (None, ""):
        out.append("invoice_number")
    if row.get("invoice_date") not in (None, ""):
        out.append("invoice_date")
    return out


def _row_amount_diff_paise(row: dict[str, Any]) -> int | None:
    v = row.get("amount_difference_paise")
    if v is None:
        return None
    try:
        return abs(int(v))
    except (TypeError, ValueError):
        return None


def _row_invoice_normalized_pairs(row: dict[str, Any]) -> list[tuple[str, str]]:
    key_pairs = (
        ("gstr_invoice_number", "pr_invoice_number"),
        ("g_invoice_number", "p_invoice_number"),
        ("invoice_number_gstr", "invoice_number_pr"),
    )
    for ak, bk in key_pairs:
        a, b = row.get(ak), row.get(bk)
        if a not in (None, "") and b not in (None, ""):
            return [(str(a).strip(), str(b).strip())]
    return []


def _amount_fields_present(row: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if row.get("taxable_amount_paise") is not None:
        out.append("taxable_amount")
    if row.get("total_tax_paise") is not None:
        out.append("total_tax")
    return out


def _decision_for_row(row: dict[str, Any]) -> DecisionOutput:
    level = row.get("match_level") or row.get("level")
    mismatch_type = row.get("mismatch_type", "")
    supplier_gstin = row.get("supplier_gstin", "?")
    source_software = row.get("source_software", "your accounting software")
    itc_amount = row.get("itc_amount") or row.get("total_tax_paise", 0)
    if isinstance(itc_amount, int):
        itc_amount = f"₹{itc_amount / 100:,.2f}"

    if row.get("is_missed_itc") or mismatch_type == "MISSED_ITC":
        return generate_decision(
            "MISSED_ITC",
            confidence="MEDIUM",
            matched_fields=_row_identity_fields(row),
            differed_fields=[],
            normalized_pairs=[],
            source_software=source_software,
            itc_amount=itc_amount,
        )

    if row.get("is_wrongful_itc") or mismatch_type == "WRONGFUL_ITC":
        return generate_decision(
            "WRONGFUL_ITC",
            confidence="MEDIUM",
            matched_fields=_row_identity_fields(row),
            differed_fields=[],
            normalized_pairs=[],
            supplier_gstin=supplier_gstin,
            itc_amount=itc_amount,
        )

    if row.get("is_late_filing"):
        return generate_decision(
            "LATE_FILING",
            confidence="MEDIUM",
            matched_fields=_row_identity_fields(row),
            differed_fields=[],
            normalized_pairs=[],
            original_period=row.get("original_period", "?"),
            gstr_period=row.get("gstr_period", "?"),
            late_months=row.get("late_months", "?"),
        )

    ident = _row_identity_fields(row)
    amt_meta = _amount_fields_present(row)
    adiff = _row_amount_diff_paise(row)
    pair_np = _row_invoice_normalized_pairs(row)

    if level == 1:
        mf = list(dict.fromkeys(ident + amt_meta))
        return generate_decision(
            "L1_EXACT",
            confidence="HIGH",
            matched_fields=mf,
            differed_fields=[],
            normalized_pairs=[],
        )

    if level == 2:
        df = ["taxable_amount"] if adiff not in (None, 0) else []
        mf = list(dict.fromkeys(ident + amt_meta))
        return generate_decision(
            "L2_AMOUNT_DIFF",
            confidence="MEDIUM",
            matched_fields=mf,
            differed_fields=df,
            normalized_pairs=[],
            diff=f"₹{abs(row.get('amount_difference_paise', 0)) / 100:,.2f}",
            source_software=source_software,
        )

    if level == 3:
        df = ["taxable_amount"] if adiff not in (None, 0) else []
        mf = list(dict.fromkeys(ident + amt_meta))
        return generate_decision(
            "L3_AMOUNT_DIFF",
            confidence="MEDIUM",
            matched_fields=mf,
            differed_fields=df,
            normalized_pairs=[],
            diff=f"₹{abs(row.get('amount_difference_paise', 0)) / 100:,.2f}",
            pct=row.get("amount_difference_pct", "?"),
            source_software=source_software,
            supplier_gstin=supplier_gstin,
        )

    if level == 4:
        mf = ["gstin"] if row.get("supplier_gstin") else []
        mf.extend(x for x in amt_meta if x not in mf)
        if row.get("invoice_date") not in (None, "") and "invoice_date" not in mf:
            mf.append("invoice_date")
        return generate_decision(
            "L4_INVOICE_NUM",
            confidence="LOW",
            matched_fields=list(dict.fromkeys(mf)),
            differed_fields=["invoice_number"],
            normalized_pairs=pair_np or [],
            source_software=source_software,
        )

    if level == 5:
        mf = ["gstin"] if row.get("supplier_gstin") else []
        mf.extend(x for x in amt_meta if x not in mf)
        return generate_decision(
            "L5_PROBABLE",
            confidence="LOW",
            matched_fields=list(dict.fromkeys(mf)),
            differed_fields=["invoice_number"],
            normalized_pairs=pair_np or [],
            distance=row.get("invoice_distance", "?"),
        )

    mf = list(dict.fromkeys(ident + amt_meta))
    return generate_decision(
        "L1_EXACT",
        confidence="HIGH",
        matched_fields=mf,
        differed_fields=[],
        normalized_pairs=[],
    )


def _enrich_with_decision(row: dict[str, Any], decision: DecisionOutput) -> dict[str, Any]:
    return {
        **row,
        "decision_what": decision.what,
        "decision_why": decision.why,
        "decision_next": decision.next,
        "decision_rule": decision.rule,
        "decision_confidence": decision.confidence,
        "decision_matched_fields": list(decision.matched_fields),
        "decision_differed_fields": list(decision.differed_fields),
        "decision_normalized_pairs": [list(p) for p in decision.normalized_pairs],
    }


def populate_decisions(
    matched_rows: list[dict[str, Any]],
    *,
    rule37: list[dict[str, Any]] | None = None,
    section_175_warnings: list[dict[str, Any]] | None = None,
    credit_note_adjustment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    enriched_rows = []
    for row in matched_rows:
        decision = _decision_for_row(row)
        enriched_rows.append(_enrich_with_decision(row, decision))

    enriched_rule37 = []
    for r in rule37 or []:
        days_remaining = r.get("days_remaining")
        mf = _row_identity_fields(r)
        if r.get("itc_at_risk_paise") is not None:
            mf = list(dict.fromkeys(mf + ["itc_at_risk_paise"]))
        if days_remaining is not None and days_remaining <= 0:
            decision = generate_decision(
                "RULE37_OVERDUE",
                confidence="HIGH",
                matched_fields=mf,
                differed_fields=[],
                normalized_pairs=[],
                itc_amount=f"₹{r.get('itc_at_risk_paise', 0) / 100:,.2f}",
            )
        else:
            decision = generate_decision(
                "RULE37_WARNING",
                confidence="MEDIUM",
                matched_fields=mf,
                differed_fields=[],
                normalized_pairs=[],
                days_remaining=days_remaining or "?",
                deadline_date=r.get("deadline", "?"),
                supplier_gstin=r.get("supplier_gstin", "?"),
                itc_amount=f"₹{r.get('itc_at_risk_paise', 0) / 100:,.2f}",
            )
        enriched_rule37.append(_enrich_with_decision(r, decision))

    enriched_175 = []
    for w in section_175_warnings or []:
        mf = []
        if w.get("supplier_gstin"):
            mf.append("gstin")
        if w.get("hsn_code") not in (None, ""):
            mf.append("hsn_code")
        if w.get("category") not in (None, ""):
            mf.append("blocked_credit_category")
        decision = generate_decision(
            "BLOCKED_CREDIT",
            confidence="LOW",
            matched_fields=mf,
            differed_fields=[],
            normalized_pairs=[],
            category=w.get("category", "?"),
            hsn_code=w.get("hsn_code", "?"),
        )
        enriched_175.append(_enrich_with_decision(w, decision))

    return {
        "rows": enriched_rows,
        "rule37": enriched_rule37,
        "section_175": enriched_175,
        "credit_note_adjustment": credit_note_adjustment or {},
    }
