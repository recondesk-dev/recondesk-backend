"""Decision templates for GST reconciliation mismatches."""
from __future__ import annotations
import re
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class DecisionOutput:
    what: str
    why: str
    next: str
    rule: str  # e.g. "L3_AMOUNT_DIFF"
    confidence: str  # "HIGH" | "MEDIUM" | "LOW"
    matched_fields: tuple[str, ...]  # e.g. ("gstin", "invoice_date")
    differed_fields: tuple[str, ...]  # e.g. ("taxable_amount",)
    normalized_pairs: tuple[tuple[str, str], ...]  # e.g. (("INV-001", "INV/001"),)


TEMPLATES: dict[str, dict[str, str]] = {
    "L1_EXACT": {
        "what": "Exact match found",
        "why": "Invoice number, amount, and date all match within rounding tolerance",
        "next": "No action required. ITC can be claimed as filed.",
    },
    "L2_AMOUNT_DIFF": {
        "what": "Invoice matched but amount differs by {diff}",
        "why": "Likely rounding difference in {source_software} export or supplier revised the invoice",
        "next": "Verify taxable value with supplier invoice copy. If confirmed, update purchase register.",
    },
    "L3_AMOUNT_DIFF": {
        "what": "Invoice matched but amount differs by {diff} ({pct}%)",
        "why": "Supplier filed a different taxable value than what was recorded in {source_software}",
        "next": "Request revised invoice or debit/credit note from {supplier_gstin}. Do not claim full ITC until resolved.",
    },
    "L4_INVOICE_NUM": {
        "what": "Same supplier and amount but invoice numbers do not match",
        "why": "Invoice number format difference between supplier system and {source_software}",
        "next": "Compare physical invoice against GSTR-2B entry. Correct purchase register if supplier number is authoritative.",
    },
    "L5_PROBABLE": {
        "what": "Probable match -- GSTIN and amount similar but invoice number differs by {distance} characters",
        "why": "Possible data entry error or abbreviation difference",
        "next": "Verify with physical invoice. If same transaction, correct the invoice number in purchase register.",
    },
    "MISSED_ITC": {
        "what": "Invoice in GSTR-2B not recorded in purchase register",
        "why": "Invoice not entered in {source_software} or entered under a different GSTIN",
        "next": "Locate physical invoice. If genuine, add to purchase register and claim ITC of {itc_amount}.",
    },
    "WRONGFUL_ITC": {
        "what": "Invoice in purchase register but supplier has not filed GSTR-1",
        "why": "Supplier missed filing or filed under wrong GSTIN. ITC of {itc_amount} is at risk.",
        "next": "Contact {supplier_gstin} immediately. Do not claim this ITC in GSTR-3B until it appears in GSTR-2B.",
    },
    "RULE37_OVERDUE": {
        "what": "Invoice unpaid beyond 180 days -- ITC reversal is now mandatory",
        "why": "Section 16(2) with Rule 37 requires ITC reversal if supplier unpaid after 180 days",
        "next": "Reverse ITC of {itc_amount} in next GSTR-3B. Pay supplier immediately or face 24% interest.",
    },
    "RULE37_WARNING": {
        "what": "Supplier payment due in {days_remaining} days ({deadline_date})",
        "why": "Section 16(2) limits ITC if consideration not paid within 180 days",
        "next": "Pay supplier by {deadline_date} or face {itc_amount} ITC reversal",
    },
    "RULE37_LATE_FILING": {
        "what": "Supplier filed GSTR-1 late (actual filing: {actual_filing_date}, due: {due_date})",
        "why": "GSTR-1 filed after the statutory due date (11th of following month)",
        "next": "Evaluate supplier compliance. {itc_amount} ITC at risk due to late filing.",
    },
    "BLOCKED_CREDIT": {
        "what": "Invoice may be under Section 17(5) blocked credit: {category}",
        "why": "HSN {hsn_code} commonly associated with {category} -- ineligible for ITC",
        "next": "Verify end-use with client. If business use exempted from 17(5), document the exception before claiming.",
    },
    "LATE_FILING": {
        "what": "Invoice dated {original_period} appeared in {gstr_period} GSTR-2B ({late_months} months late)",
        "why": "Supplier filed this invoice late with the GST portal",
        "next": "ITC can still be claimed as the invoice is now in GSTR-2B. Verify the purchase register entry matches.",
    },
}

_FALLBACK = DecisionOutput(
    what="Mismatch detected",
    why="Unable to determine specific reason",
    next="Review manually with CA before claiming ITC.",
    rule="UNKNOWN",
    confidence="LOW",
    matched_fields=(),
    differed_fields=(),
    normalized_pairs=(),
)


def _safe_format(template: str, **kwargs: object) -> str:
    try:
        return template.format(**kwargs)
    except KeyError:
        return re.sub(r"\{[^}]+\}", "?", template)


def _as_tuple_strs(fields: Sequence[str] | None) -> tuple[str, ...]:
    if not fields:
        return ()
    return tuple(dict.fromkeys(str(x) for x in fields if x))


def _as_pairs(pairs: Sequence[tuple[str, str]] | None) -> tuple[tuple[str, str], ...]:
    if not pairs:
        return ()
    out: list[tuple[str, str]] = []
    for item in pairs:
        if len(item) != 2:
            continue
        out.append((str(item[0]), str(item[1])))
    return tuple(out)


def generate_decision(
    template_key: str,
    *,
    confidence: str = "LOW",
    matched_fields: Sequence[str] | None = None,
    differed_fields: Sequence[str] | None = None,
    normalized_pairs: Sequence[tuple[str, str]] | None = None,
    **kwargs: object,
) -> DecisionOutput:
    """Render *template_key*. Diagnostic kwargs are not forwarded to str.format.

    ``rule`` is always set to *template_key* for known templates; unknown keys keep
    *template_key* as ``rule`` for traceability.
    """
    mf = _as_tuple_strs(list(matched_fields) if matched_fields is not None else None)
    df = _as_tuple_strs(list(differed_fields) if differed_fields is not None else None)
    np = _as_pairs(list(normalized_pairs) if normalized_pairs is not None else None)

    tmpl = TEMPLATES.get(template_key)
    if tmpl is None:
        return DecisionOutput(
            what=_FALLBACK.what,
            why=_FALLBACK.why,
            next=_FALLBACK.next,
            rule=template_key,
            confidence=confidence,
            matched_fields=mf,
            differed_fields=df,
            normalized_pairs=np,
        )
    return DecisionOutput(
        what=_safe_format(tmpl["what"], **kwargs),
        why=_safe_format(tmpl["why"], **kwargs),
        next=_safe_format(tmpl["next"], **kwargs),
        rule=template_key,
        confidence=confidence,
        matched_fields=mf,
        differed_fields=df,
        normalized_pairs=np,
    )
