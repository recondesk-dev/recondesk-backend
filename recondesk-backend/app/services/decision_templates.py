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
    "L1_CREDIT_NOTE_EXACT": {
        "what": "Exact match found for Credit/Debit Note",
        "why": "Credit/Debit note details and amounts align between GSTR-2B CDNR and purchase register",
        "next": "Reduce/reverse ITC in GSTR-3B Table 4(B)(2) as required under Section 34(2). Do not claim as domestic inward ITC.",
    },
    "L1_RCM_EXACT": {
        "what": "Exact match found (Reverse Charge / RCM)",
        "why": "Inward supply liable to reverse charge under Section 9(3)/9(4) matches between GSTR-2B and books",
        "next": "Discharge tax liability in cash under GSTR-3B Table 3.1(d), then claim corresponding ITC in Table 4(A)(3). Electronic credit ledger cannot be used for RCM tax payment.",
    },
    "L2_NORMALIZED": {
        "what": "Normalized invoice match: {gstr_invoice} ↔ {pr_invoice}",
        "why": (
            "Invoice numbers match after normalization or format variant "
            "({gstr_invoice} vs {pr_invoice}); amounts and dates align"
        ),
        "next": "No action required — formatting differs, amounts align",
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
    "COMPOSITION_SCHEME_NO_ITC": {
        "what": "Composition Scheme — Ineligible for ITC",
        "why": (
            "Taxpayers registered under the Composition Scheme (Section 10) pay tax at a flat rate "
            "and are legally prohibited from claiming Input Tax Credit on purchases under Section 10(4)."
        ),
        "next": "No ITC can be claimed. Treat total invoice value as purchase expense/cost.",
    },
    "MISSED_ITC": {
        "what": "Available in 2B but Missing in Books",
        "why": "Invoice not entered in {source_software} or entered under a different GSTIN",
        "next": "Locate physical invoice. If genuine, add to purchase register and claim ITC of {itc_amount}.",
    },
    "MISSED_ITC_CREDIT_NOTE": {
        "what": "Credit Note in 2B but Missing in Books",
        "why": "Supplier issued a Credit Note of {itc_amount} in GSTR-2B CDNR that is not recorded in {source_software}",
        "next": "Record credit note in purchase register and reduce/reverse ITC of {itc_amount} in GSTR-3B Table 4(B)(2) to prevent Section 50 interest.",
    },
    "MISSED_ITC_RCM": {
        "what": "RCM Inward Supply in 2B but Missing in Books",
        "why": "Inward supply liable to reverse charge appears in GSTR-2B Table 4(A)(3) but is not recorded in {source_software}",
        "next": "Book in purchase register. Discharge tax in cash under Table 3.1(d) and avail ITC under Table 4(A)(3) of GSTR-3B.",
    },
    "WRONGFUL_ITC": {
        # Bug-3 fix: The old label asserted "Supplier Has Not Filed" as a fact, but
        # PR-only records carry no supplier filing-status signal (supfildt is on the
        # GSTR side, not available here).  The engine cannot determine whether the
        # supplier hasn't filed, filed under the wrong GSTIN, or whether the invoice
        # was booked in the PR by mistake.  Use a neutral, data-backed description.
        "what": "Invoice not reflected in GSTR-2B",
        "why": (
            "This invoice from your purchase register does not appear in your GSTR-2B "
            "for this period. The supplier may not have filed GSTR-1, may have filed "
            "under a different GSTIN or period, or the invoice may need verification. "
            "ITC of {itc_amount} cannot be claimed until it appears in GSTR-2B."
        ),
        "next": "Contact {supplier_gstin} to confirm filing status. Do not claim this ITC in GSTR-3B until it appears in GSTR-2B.",
    },
    "WRONGFUL_ITC_CREDIT_NOTE": {
        "what": "Credit Note in Books but not reflected in GSTR-2B",
        "why": (
            "Credit note recorded in {source_software} does not appear in supplier's GSTR-1 (CDNR table). "
            "Supplier may not have filed or reported it under a different return period."
        ),
        "next": "Follow up with {supplier_gstin} to confirm filing of Credit Note in GSTR-1 Table 9B.",
    },
    "WRONGFUL_ITC_GSTIN_TYPO": {
        # Bug-3 fix: These records have an invoice number that IS present in
        # GSTR-2B, but under a different supplier GSTIN than recorded in the PR.
        # This is a data-entry error in the purchase register, NOT a supplier
        # non-filing issue. CAs should correct their books, not chase the supplier.
        "what": "Invoice not matched in GSTR-2B due to GSTIN mismatch in purchase register",
        "why": (
            "GSTIN in purchase register does not match GSTR-2B. The invoice appears "
            "in GSTR-2B under a different supplier GSTIN than what is recorded in your "
            "purchase register. This is likely a data-entry error in your books — not a "
            "supplier filing failure. ITC of {itc_amount} cannot be claimed until the "
            "purchase register is corrected."
        ),
        "next": (
            "Check the supplier GSTIN on the physical invoice and correct your purchase "
            "register. Once corrected, re-run reconciliation."
        ),
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
    "RULE37A_NON_FILER": {
        "what": "ITC unavailable in GSTR-2B (Supplier GSTR-3B Non-Filer / Rule 37A)",
        "why": (
            "GSTR-2B marks ITC Availability as 'No'. Supplier has not filed GSTR-3B "
            "for the said period (Rule 37A risk). Ineligible to claim ITC until supplier files return."
        ),
        "next": (
            "Hold on IMS and do not claim in GSTR-3B. Follow up with {supplier_gstin} to file GSTR-3B. "
            "Claiming prior to filing triggers mandatory reversal under Rule 37A."
        ),
    },
    "ITC_NOT_AVAILABLE": {
        "what": "ITC marked unavailable in GSTR-2B: {reason}",
        "why": "GSTR-2B explicitly marks ITC Availability as 'No' ({reason}). Ineligible for input tax credit.",
        "next": "Do not claim ITC in GSTR-3B. Verify ineligibility reason ({reason}) with supplier.",
    },
    "BLOCKED_CREDIT": {
        "what": "Invoice may be under Section 17(5) blocked credit: {category}",
        "why": "HSN {hsn_code} commonly associated with {category} -- ineligible for ITC",
        "next": "Verify end-use with client. If business use exempted from 17(5), document the exception before claiming.",
    },
    "BLOCKED_CREDIT_NO_HSN": {
        "what": "Invoice may be under Section 17(5) blocked credit: {category}",
        "why": "{category} — ineligible for ITC pending verification",
        "next": "Verify end-use with client. If business use exempted from 17(5), document the exception before claiming.",
    },
    "LATE_FILING": {
        "what": "Invoice dated {original_period} appeared in {gstr_period} GSTR-2B ({late_months} months late)",
        "why": "Supplier filed this invoice late with the GST portal",
        "next": "ITC can still be claimed as the invoice is now in GSTR-2B. Verify the purchase register entry matches.",
    },
    # ── Review Required templates ──────────────────────────────────────────
    "REVIEW_AMOUNT_MISMATCH": {
        "what": "Verify manually — {confidence_pct}% confidence, discrepancy of {diff}",
        "why": "Invoice matched on identity fields but the taxable amount differs beyond auto-accept threshold",
        "next": "Compare physical invoice with GSTR-2B entry. Reconcile the {diff} difference with supplier before claiming ITC.",
    },
    "REVIEW_DATE_MISMATCH": {
        "what": "Verify manually — {confidence_pct}% confidence, invoice date differs",
        "why": "Invoice matched on GSTIN, invoice number, and amount, but the dates differ between GSTR-2B and purchase register",
        "next": "Compare physical invoice date with GSTR-2B entry. If dates differ across GST return periods, this may affect the period in which ITC can be claimed.",
    },
    "REVIEW_GSTIN_MISMATCH": {
        "what": "GSTIN mismatch — verify supplier identity",
        "why": "Invoice number and amount match a purchase register entry but the supplier GSTIN differs",
        "next": "Confirm correct GSTIN with supplier {supplier_gstin}. Update purchase register if supplier migrated or amended their GSTIN.",
    },
    "REVIEW_DUPLICATE_AMBIGUITY": {
        "what": "Duplicate invoice — multiple entries found",
        "why": "The same invoice appears more than once; the system cannot determine which is the original",
        "next": "Identify the correct entry and remove or mark the duplicate(s). Do not claim ITC on duplicate bookings.",
    },
    "DUPLICATE_ENTRY": {
        "what": "Duplicate Entry — same invoice booked twice in books",
        "why": "Identical GSTIN + invoice appears more than once in the purchase register",
        "next": "Remove or mark the extra purchase-register row. Do not treat this as missing from GSTR-2B.",
    },
    "GSTR2B_DUPLICATE_ENTRY": {
        "what": "Duplicate Entry in GSTR-2B — same invoice reported twice by portal",
        "why": "This invoice appears more than once in your GSTR-2B. Only one copy has been matched to your purchase register. The extra copy is likely a portal duplicate (late-filed amendment re-reporting, IMS sync, or GSTN portal bug).",
        "next": "No action required. Do not treat this as a missing invoice or chase the supplier — the matched entry already covers this ITC claim.",
    },
    "REVIEW_MULTIPLE_CANDIDATES": {
        "what": "Multiple matching candidates — manual selection required",
        "why": "More than one purchase register entry could match this GSTR-2B invoice",
        "next": "Review all candidates and confirm the correct match. Mark the others as duplicates or separate transactions.",
    },
    "REVIEW_POSSIBLE_MATCH": {
        "what": "Possible match — {confidence_pct}% confidence",
        "why": "Partial field overlap detected but confidence is below the auto-match threshold",
        "next": "Verify with physical invoice. If the same transaction, correct the mismatched fields in the purchase register.",
    },
    "REVIEW_PERIOD_BOUNDARY_DATE_MISMATCH": {
        "what": "Invoice date crosses GST return period boundary",
        "why": (
            "GSTR-2B date {gstr_date} falls in {gstr_period}; purchase register "
            "date {pr_date} falls in {pr_period}. Dates are in different filing "
            "periods — claiming ITC in the wrong period is a compliance risk, not "
            "merely a data-entry variance."
        ),
        "next": (
            "Confirm which return period this supply belongs to. Align the "
            "purchase register date with the correct period before claiming ITC "
            "in GSTR-3B."
        ),
    },
    "REVIEW_DOC_TYPE_NOTE_IN_B2B": {
        "what": "Potential Credit/Debit Note misfiled in B2B table",
        "why": "Invoice number prefix or document type indicates a Credit Note (CBN/CRN) or Debit Note (DBN/DRN) filed under the B2B invoice table instead of the CDNR table.",
        "next": "Verify document nature with supplier. If this is a Credit Note, ensure ITC is reversed in GSTR-3B Table 4(B)(2); do not claim as domestic inward ITC.",
    },
    "REVIEW_GENERIC": {
        "what": "Review required — {confidence_pct}% confidence",
        "why": "This record requires human verification ({review_reason})",
        "next": "Examine GSTR-2B and purchase register entries side by side. Resolve discrepancies before filing GSTR-3B.",
    },
    # ── E-Invoice Reconciliation templates ────────────────────────────────────
    "EINVOICE_IRN_MISSING": {
        "what": "Invoice raised in books but not registered on IRP",
        "why": "Invoice was recorded in books, but no corresponding active IRN was found on the E-Invoice portal (likely IRN generation failure, portal timeout, or manual skip)",
        "next": "Regenerate IRN before the 30-day reporting window closes, or the invoice cannot legally be reported in GSTR-1.",
    },
    "EINVOICE_CANCELLED_MISMATCH": {
        "what": "IRN cancelled on IRP but invoice remains active in books",
        "why": "IRN status is Cancelled on the portal, but accounting software reflects an active transaction without reversal",
        "next": "Verify cancellation status with recipient and issue credit note or cancel invoice in books.",
    },
    "EINVOICE_VALUE_MISMATCH": {
        "what": "E-Invoice IRN matched but invoice value differs by {diff}",
        "why": "Value registered on IRP ({einvoice_val}) differs from value in books ({book_val})",
        "next": "Verify against signed e-invoice JSON/PDF and amend books or issue debit/credit note.",
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
