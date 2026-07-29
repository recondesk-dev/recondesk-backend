"""Decision layer — enriches reconciliation rows with structured what/why/next decisions."""
from __future__ import annotations

import logging
from typing import Any

from app.services.decision_templates import DecisionOutput, generate_decision

_log = logging.getLogger(__name__)


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
    """Absolute taxable/amount delta in paise for decision templates.

    Clean-matched rows store ``taxable_diff_paise`` (engine) while the worker
    may also attach ``amount_difference_paise``. Prefer either; fall back to
    live abs(GSTR taxable − PR taxable) when both sides are present on the row.
    Never treat a missing key as 0 — that produced the FUZZY export bug
    \"amount differs by ₹0.00\" for every L2 row.
    """
    for key in ("taxable_diff_paise", "amount_difference_paise", "tax_difference_paise"):
        v = row.get(key)
        if v is None:
            continue
        try:
            return abs(int(v))
        except (TypeError, ValueError):
            continue

    g_tax = row.get("gstr_taxable_amount_paise")
    p_tax = row.get("pr_taxable_amount_paise")
    if g_tax is None:
        g_tax = row.get("gstr_taxable_paise")
    if p_tax is None:
        p_tax = row.get("pr_taxable_paise")
    if g_tax is not None and p_tax is not None:
        try:
            return abs(int(g_tax) - int(p_tax))
        except (TypeError, ValueError):
            return None
    return None


def _format_amount_diff_rupees(row: dict[str, Any]) -> str:
    """₹-formatted absolute amount delta for L2/L3 ``{diff}`` placeholders."""
    adiff = _row_amount_diff_paise(row)
    if adiff is None:
        return "₹0.00"
    return f"₹{adiff / 100:,.2f}"


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
        mf = list(dict.fromkeys(ident + amt_meta))
        # Clean-matched L2 is usually a format-variant / normalized-invoice hit
        # with zero financial delta (matcher zero-discrepancy invariant). Claiming
        # "amount differs by ₹0.00" for those rows is a distinct bug from the
        # missing-key → ₹0.00 Path A fix — use the normalized template instead.
        if adiff in (None, 0):
            g_inv, p_inv = "?", "?"
            if pair_np:
                g_inv, p_inv = pair_np[0]
            else:
                g_cand = row.get("gstr_invoice_number") or row.get("invoice_number")
                p_cand = row.get("pr_invoice_number")
                if g_cand not in (None, ""):
                    g_inv = str(g_cand).strip()
                if p_cand not in (None, ""):
                    p_inv = str(p_cand).strip()
            return generate_decision(
                "L2_NORMALIZED",
                confidence="HIGH",
                matched_fields=mf,
                differed_fields=["invoice_number"] if g_inv != p_inv else [],
                normalized_pairs=pair_np or ([(g_inv, p_inv)] if g_inv != "?" and p_inv != "?" else []),
                gstr_invoice=g_inv,
                pr_invoice=p_inv,
            )
        return generate_decision(
            "L2_AMOUNT_DIFF",
            confidence="MEDIUM",
            matched_fields=mf,
            differed_fields=["taxable_amount"],
            normalized_pairs=[],
            diff=_format_amount_diff_rupees(row),
            source_software=source_software,
        )

    if level == 3:
        df = ["taxable_amount"] if adiff not in (None, 0) else []
        mf = list(dict.fromkeys(ident + amt_meta))
        pct = row.get("amount_difference_pct", "?")
        if pct == "?" and adiff not in (None, 0):
            # Best-effort pct when only the absolute delta is known.
            base = None
            for k in ("gstr_taxable_amount_paise", "taxable_amount_paise"):
                if row.get(k) is not None:
                    try:
                        base = abs(int(row[k]))
                        break
                    except (TypeError, ValueError):
                        pass
            if base:
                pct = f"{(adiff / base) * 100:.1f}"
        return generate_decision(
            "L3_AMOUNT_DIFF",
            confidence="MEDIUM",
            matched_fields=mf,
            differed_fields=df,
            normalized_pairs=[],
            diff=_format_amount_diff_rupees(row),
            pct=pct,
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
        status = r.get("status")
        mf = _row_identity_fields(r)
        if r.get("itc_at_risk_paise") is not None:
            mf = list(dict.fromkeys(mf + ["itc_at_risk_paise"]))
            
        if status == "LATE_FILING":
            decision = generate_decision(
                "RULE37_LATE_FILING",
                confidence="HIGH",
                matched_fields=mf,
                differed_fields=[],
                normalized_pairs=[],
                actual_filing_date=r.get("actual_filing_date", "?"),
                due_date=r.get("due_date", "?"),
                itc_amount=f"₹{r.get('itc_at_risk_paise', 0) / 100:,.2f}",
            )
        else:
            days_remaining = r.get("days_remaining")
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
        hsn_raw = w.get("hsn_code")
        hsn = str(hsn_raw).strip() if hsn_raw not in (None, "") else ""
        category = str(
            w.get("category") or w.get("reason") or "Section 17(5) blocked credit"
        ).strip()
        if hsn:
            mf.append("hsn_code")
        if category:
            mf.append("blocked_credit_category")
        # Never pass literal "?" placeholders — missing HSN uses a no-HSN template.
        if hsn:
            decision = generate_decision(
                "BLOCKED_CREDIT",
                confidence="LOW",
                matched_fields=mf,
                differed_fields=[],
                normalized_pairs=[],
                category=category,
                hsn_code=hsn,
            )
        else:
            decision = generate_decision(
                "BLOCKED_CREDIT_NO_HSN",
                confidence="LOW",
                matched_fields=mf,
                differed_fields=[],
                normalized_pairs=[],
                category=category,
            )
        enriched_175.append(_enrich_with_decision(w, decision))

    return {
        "rows": enriched_rows,
        "rule37": enriched_rule37,
        "section_175": enriched_175,
        "credit_note_adjustment": credit_note_adjustment or {},
    }


# ── Review Required decision helpers ─────────────────────────────────────

# Map review_reason strings to the REVIEW_* template keys.
_REVIEW_REASON_TO_TEMPLATE: dict[str, str] = {
    "AMOUNT_MISMATCH": "REVIEW_AMOUNT_MISMATCH",
    "Amount/Date mismatch": "REVIEW_AMOUNT_MISMATCH",
    "GSTIN_MISMATCH": "REVIEW_GSTIN_MISMATCH",
    "DUPLICATE_AMBIGUITY": "REVIEW_DUPLICATE_AMBIGUITY",
    "DUPLICATE_AMBIGUITY_PR": "REVIEW_DUPLICATE_AMBIGUITY",
    "DUPLICATE_CLAIM": "REVIEW_DUPLICATE_AMBIGUITY",
    "DUPLICATE_CLAIM_PR": "REVIEW_DUPLICATE_AMBIGUITY",
    "DUPLICATE_CONFLICT": "REVIEW_DUPLICATE_AMBIGUITY",
    "DUPLICATE_ENTRY": "DUPLICATE_ENTRY",
    "MULTIPLE_CANDIDATES": "REVIEW_MULTIPLE_CANDIDATES",
    "POSSIBLE_MATCH": "REVIEW_POSSIBLE_MATCH",
    "PERIOD_BOUNDARY_DATE_MISMATCH": "REVIEW_PERIOD_BOUNDARY_DATE_MISMATCH",
}


def _decision_for_review_row(row: dict[str, Any]) -> DecisionOutput:
    """Produce a DecisionOutput for a review-required record.

    Falls back to _decision_for_row() when the row carries a numeric
    match_level that the existing templates already handle (levels 2–4).
    For rows with a review_reason, uses the dedicated REVIEW_* templates.
    """
    review_reason = row.get("review_reason") or row.get("reason") or ""
    confidence_score = row.get("confidence_score") or 0
    confidence_pct = int(confidence_score) if confidence_score else 0
    diff_paise = row.get("taxable_diff_paise") or row.get("amount_difference_paise") or 0
    diff_str = f"₹{abs(int(diff_paise)) / 100:,.2f}"
    supplier_gstin = row.get("supplier_gstin") or "?"

    template_key = _REVIEW_REASON_TO_TEMPLATE.get(review_reason, "REVIEW_GENERIC")

    ident = _row_identity_fields(row)
    amt_meta = _amount_fields_present(row)
    mf = list(dict.fromkeys(ident + amt_meta))

    extra_kwargs: dict[str, object] = {}
    if review_reason == "PERIOD_BOUNDARY_DATE_MISMATCH":
        from app.services.matcher import (
            _format_gst_return_period_label,
            _format_invoice_date_label,
        )

        g_date = row.get("gstr_invoice_date")
        p_date = row.get("pr_invoice_date")
        extra_kwargs = {
            "gstr_period": _format_gst_return_period_label(g_date),
            "pr_period": _format_gst_return_period_label(p_date),
            "gstr_date": _format_invoice_date_label(g_date),
            "pr_date": _format_invoice_date_label(p_date),
        }

    return generate_decision(
        template_key,
        confidence="LOW",
        matched_fields=mf,
        differed_fields=[],
        normalized_pairs=[],
        confidence_pct=confidence_pct,
        diff=diff_str,
        supplier_gstin=supplier_gstin,
        review_reason=review_reason,
        **extra_kwargs,
    )


def populate_review_decisions(
    review_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Enrich review-required rows with decision_* fields, in-place and returned."""
    enriched: list[dict[str, Any]] = []
    sample_rule: str | None = None
    for row in review_rows:
        decision = _decision_for_review_row(row)
        enriched.append(_enrich_with_decision(row, decision))
        if sample_rule is None and decision.rule:
            sample_rule = decision.rule
    with_what = sum(1 for r in enriched if r.get("decision_what"))
    _log.info(
        "populate_review_decisions: processed %d rows, %d with decision_what, "
        "sample_decision_rule=%s",
        len(enriched),
        with_what,
        sample_rule or "(none)",
    )
    return enriched
