"""Decision layer — enriches reconciliation rows with structured what/why/next decisions."""

from __future__ import annotations

from typing import Any

from app.services.decision_templates import DecisionOutput, generate_decision


def _decision_for_row(row: dict[str, Any]) -> DecisionOutput:
    """
    Select and populate the correct decision template for a reconciliation row.
    Reads existing fields already set by matcher.py — does not re-run matching.
    """
    level = row.get("match_level") or row.get("level")
    mismatch_type = row.get("mismatch_type", "")
    supplier_gstin = row.get("supplier_gstin", "?")
    source_software = row.get("source_software", "your accounting software")
    itc_amount = row.get("itc_amount") or row.get("total_tax_paise", 0)
    if isinstance(itc_amount, int):
        itc_amount = f"₹{itc_amount / 100:,.2f}"

    # Missed ITC — in GSTR-2B but not in PR
    if row.get("is_missed_itc") or mismatch_type == "MISSED_ITC":
        return generate_decision(
            "MISSED_ITC",
            source_software=source_software,
            itc_amount=itc_amount,
        )

    # Wrongful ITC — in PR but not in GSTR-2B
    if row.get("is_wrongful_itc") or mismatch_type == "WRONGFUL_ITC":
        return generate_decision(
            "WRONGFUL_ITC",
            supplier_gstin=supplier_gstin,
            itc_amount=itc_amount,
        )

    # Late filing
    if row.get("is_late_filing"):
        return generate_decision(
            "LATE_FILING",
            original_period=row.get("original_period", "?"),
            gstr_period=row.get("gstr_period", "?"),
            late_months=row.get("late_months", "?"),
        )

    # Level-based decisions
    if level == 1:
        return generate_decision("L1_EXACT")

    if level == 2:
        diff = row.get("amount_difference_display") or f"₹{abs(row.get('amount_difference_paise', 0)) / 100:,.2f}"
        return generate_decision(
            "L2_AMOUNT_DIFF",
            diff=diff,
            source_software=source_software,
        )

    if level == 3:
        diff = row.get("amount_difference_display") or f"₹{abs(row.get('amount_difference_paise', 0)) / 100:,.2f}"
        pct = row.get("amount_difference_pct") or "?"
        return generate_decision(
            "L3_AMOUNT_DIFF",
            diff=diff,
            pct=pct,
            source_software=source_software,
        )

    if level == 4:
        return generate_decision(
            "L4_INVOICE_NUM",
            source_software=source_software,
        )

    if level == 5:
        distance = row.get("invoice_distance") or "?"
        return generate_decision(
            "L5_PROBABLE",
            distance=distance,
        )

    return generate_decision("L1_EXACT")


def populate_decisions(
    matched_rows: list[dict[str, Any]],
    *,
    rule37: list[dict[str, Any]] | None = None,
    section_175_warnings: list[dict[str, Any]] | None = None,
    credit_note_adjustment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Enrich each reconciliation row with decision fields.
    Attaches decision_what, decision_why, decision_next to every row.
    Does not modify matching results — read-only enrichment only.
    """
    enriched_rows = []
    for row in matched_rows:
        decision = _decision_for_row(row)
        enriched = {
            **row,
            "decision_what": decision.what,
            "decision_why": decision.why,
            "decision_next": decision.next,
        }
        enriched_rows.append(enriched)

    # Enrich rule37 rows
    enriched_rule37 = []
    for r in (rule37 or []):
        days_remaining = r.get("days_remaining")
        if days_remaining is not None and days_remaining <= 0:
            decision = generate_decision(
                "RULE37_OVERDUE",
                itc_amount=r.get("itc_amount", "?"),
            )
        else:
            decision = generate_decision(
                "RULE37_WARNING",
                days_remaining=days_remaining or "?",
                deadline_date=r.get("deadline_date", "?"),
                supplier_gstin=r.get("supplier_gstin", "?"),
                itc_amount=r.get("itc_amount", "?"),
            )
        enriched_rule37.append({
            **r,
            "decision_what": decision.what,
            "decision_why": decision.why,
            "decision_next": decision.next,
        })

    # Enrich section 17(5) warnings
    enriched_175 = []
    for w in (section_175_warnings or []):
        decision = generate_decision(
            "BLOCKED_CREDIT",
            category=w.get("category", "?"),
            hsn_code=w.get("hsn_code", "?"),
        )
        enriched_175.append({
            **w,
            "decision_what": decision.what,
            "decision_why": decision.why,
            "decision_next": decision.next,
        })

    return {
        "rows": enriched_rows,
        "rule37": enriched_rule37,
        "section_17_5": enriched_175,
        "credit_note_adjustment": credit_note_adjustment or {},
    }
