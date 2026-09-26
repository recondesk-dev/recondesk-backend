"""Phase 1 — per-invoice IMS action recommendations for CA review.

Consumes real reconcile outcome fields (and optional compliance enrichment
passed by ``ims_run_service``):

* ``match_confidence`` — fuzzy L-tier score from the matcher (0–1), or absent
  for exact L1–L4 links that never write a fuzzy score
* ``rule37_flag`` / ``rule37_days_remaining`` — Rule 37 breach + day count
* ``blocked_credit_flag`` / ``blocked_credit_category`` — Section 17(5)

Never invents confidence constants. Never writes to GSTN.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Literal, Mapping, Optional, Sequence

# Align with ``reconciliation_outcomes.CONFIDENCE_HIGH_MIN`` (≥90%).
CONFIDENCE_HIGH_MIN = 0.90

RecommendedAction = Literal["accept", "reject", "hold"]

_TERMINAL_IMS = frozenset({"accepted", "rejected"})

_ACTIONABLE_CATEGORIES = frozenset(
    {
        "matched",
        "review_required",
        "missed_itc",
        "wrongful_risk",
        "blocked_credit",
        "gstin_mismatch",
        "duplicate_entry",
        "rule37_warnings",
    }
)

REASON_MATCHED_IN_BOOKS = "MATCHED_IN_BOOKS"
REASON_AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
REASON_NEEDS_REVIEW = "NEEDS_REVIEW"
REASON_NOT_IN_BOOKS = "NOT_IN_BOOKS"
REASON_WRONGFUL_ITC_RISK = "WRONGFUL_ITC_RISK"
REASON_BLOCKED_ITC = "BLOCKED_ITC"
REASON_GSTIN_MISMATCH = "GSTIN_MISMATCH"
REASON_DUPLICATE_AMBIGUITY = "DUPLICATE_AMBIGUITY"
REASON_ACTION_BLOCKED = "ACTION_BLOCKED"
REASON_INSUFFICIENT_SIGNAL = "INSUFFICIENT_SIGNAL"
REASON_RULE37_BREACH = "RULE37_BREACH"
REASON_RULE37A_NON_FILER = "RULE37A_NON_FILER"
REASON_UNLINKED_CREDIT_NOTE = "UNLINKED_CREDIT_NOTE"
REASON_LOW_MATCH_CONFIDENCE = "LOW_MATCH_CONFIDENCE"
REASON_NO_MATCH_CONFIDENCE = "NO_MATCH_CONFIDENCE"
REASON_RCM_FLAG_CONFLICT = "RCM_FLAG_CONFLICT"
REASON_TAX_HEAD_MISMATCH = "TAX_HEAD_MISMATCH"

ConfidenceSource = Literal[
    "matcher_fuzzy",
    "matcher_exact_no_fuzzy_score",
    "unavailable",
]


@dataclass(frozen=True)
class InvoiceRecommendationInput:
    """Invoice context for recommendation (outcome row + optional compliance)."""

    invoice_id: str
    supplier_gstin: str
    invoice_number: str
    category: str
    ims_status: str = "no_action_taken"
    match_status: str = ""
    match_confidence: Optional[float] = None
    total_tax_diff_paise: int = 0
    taxable_value_diff_paise: int = 0
    amount_paise: Optional[int] = None
    invoice_date: Optional[str] = None
    supplier_name: Optional[str] = None
    is_pending_action_blocked: bool = False
    section: str = "b2b"
    writeback_payload: Optional[dict[str, Any]] = None
    # Real flags / enrichment from outcome + compliance (not category labels alone)
    rule37_flag: bool = False
    rule37a_flag: bool = False
    blocked_credit_flag: bool = False
    rule37_days_remaining: Optional[int] = None
    rule37_status: Optional[str] = None
    blocked_credit_category: Optional[str] = None
    blocked_credit_reason: Optional[str] = None
    pr_supplier_gstin: Optional[str] = None
    gstr_supplier_gstin: Optional[str] = None
    review_reason: Optional[str] = None


@dataclass(frozen=True)
class InvoiceRecommendation:
    invoice_id: str
    supplier_gstin: str
    invoice_number: str
    invoice_date: Optional[str]
    supplier_name: Optional[str]
    category: str
    ims_status: str
    recommended_action: RecommendedAction
    confidence_score: Optional[float]
    confidence_source: ConfidenceSource
    reason_codes: tuple[str, ...]
    human_readable_why: str
    amount_paise: Optional[int] = None
    section: str = "b2b"
    writeback_payload: Optional[dict[str, Any]] = None
    match_confidence: Optional[float] = None

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["reason_codes"] = list(self.reason_codes)
        return d


@dataclass
class RecommendationBatch:
    available: bool
    reason: Optional[str] = None
    invoices: list[InvoiceRecommendation] = field(default_factory=list)
    run_id: Optional[str] = None
    period: Optional[str] = None
    gstin: Optional[str] = None
    high_confidence_accept_count: int = 0
    source: str = "reconcile_ims_overlay"

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "run_id": self.run_id,
            "period": self.period,
            "gstin": self.gstin,
            "source": self.source,
            "high_confidence_accept_count": self.high_confidence_accept_count,
            "invoice_count": len(self.invoices),
            "invoices": [inv.as_dict() for inv in self.invoices],
        }


def unavailable(reason: str, *, run_id: str | None = None) -> RecommendationBatch:
    return RecommendationBatch(
        available=False,
        reason=reason,
        run_id=run_id,
        invoices=[],
        high_confidence_accept_count=0,
    )


def confirmed_empty(
    *,
    run_id: str | None = None,
    period: str | None = None,
    gstin: str | None = None,
    source: str = "reconcile_ims_overlay",
) -> RecommendationBatch:
    return RecommendationBatch(
        available=True,
        reason=None,
        run_id=run_id,
        period=period,
        gstin=gstin,
        invoices=[],
        high_confidence_accept_count=0,
        source=source,
    )


def normalize_match_confidence(raw: Any) -> Optional[float]:
    """Return similarity in [0, 1], or None when absent / unparsable."""
    if raw is None or raw == "":
        return None
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return None
    if score > 1.0:
        score = score / 100.0
    if score < 0.0:
        return None
    return score


def resolve_confidence(
    inp: InvoiceRecommendationInput,
) -> tuple[Optional[float], ConfidenceSource]:
    """Read real matcher confidence; never invent a constant.

    Linked exact tiers (L1–L4) often omit ``match_confidence`` — same
    convention as ``confidence_bucket`` in reconciliation_outcomes.
    """
    score = normalize_match_confidence(inp.match_confidence)
    if score is not None:
        return round(score, 4), "matcher_fuzzy"
    category = (inp.category or "").strip().lower()
    match_status = (inp.match_status or "").strip().upper()
    if category == "matched" and match_status in ("", "MATCHED", "EXACT", "CLEAN"):
        return None, "matcher_exact_no_fuzzy_score"
    return None, "unavailable"


def is_high_confidence_accept(rec: InvoiceRecommendation) -> bool:
    if rec.recommended_action != "accept":
        return False
    if rec.confidence_score is not None:
        return rec.confidence_score >= CONFIDENCE_HIGH_MIN
    return rec.confidence_source == "matcher_exact_no_fuzzy_score"


def _accept_confidence_ok(
    score: Optional[float], source: ConfidenceSource
) -> bool:
    if source == "matcher_fuzzy" and score is not None:
        return score >= CONFIDENCE_HIGH_MIN
    if source == "matcher_exact_no_fuzzy_score":
        return True
    return False


def _rule37_why(inp: InvoiceRecommendationInput) -> str:
    days = inp.rule37_days_remaining
    status = (inp.rule37_status or "").strip() or "concern"
    if days is None:
        return (
            f"Active Rule 37 flag on this invoice (status={status}). "
            "Day-count is not present on this recommendation input — Hold until "
            "payment / Rule 37 status is cleared."
        )
    if days < 0:
        overdue = abs(int(days))
        return (
            f"Rule 37 breach: {overdue} day{'s' if overdue != 1 else ''} past the "
            f"180-day payment deadline (days_remaining={days}, status={status}). "
            "Hold on IMS until payment / ITC reversal is resolved."
        )
    until = int(days)
    elapsed = 180 - until
    return (
        f"Rule 37: {elapsed} days since invoice / payment clock, "
        f"{until} day{'s' if until != 1 else ''} until the 180-day deadline "
        f"(status={status}). Hold on IMS until payment is confirmed."
    )


def recommend_invoice(
    inp: InvoiceRecommendationInput,
) -> Optional[InvoiceRecommendation]:
    """Return a recommendation, or ``None`` when the invoice should be skipped."""
    ims = (inp.ims_status or "no_action_taken").strip().lower()
    if ims in _TERMINAL_IMS:
        return None

    category = (inp.category or "").strip().lower()
    if category and category not in _ACTIONABLE_CATEGORIES:
        return None

    score, conf_source = resolve_confidence(inp)

    if inp.is_pending_action_blocked:
        return _rec(
            inp,
            action="hold",
            score=score,
            conf_source=conf_source,
            codes=(REASON_ACTION_BLOCKED,),
            why=(
                "GSTN has blocked pending action on this invoice "
                "(ispendactblocked). Hold until the block clears — do not Accept or Reject."
            ),
        )

    # Active 17(5) → Reject, citing real category/reason when enriched.
    if inp.blocked_credit_flag or category == "blocked_credit":
        cat_line = (inp.blocked_credit_category or "").strip()
        reason_line = (inp.blocked_credit_reason or "").strip()
        if cat_line and reason_line and reason_line != cat_line:
            why = (
                f"Section 17(5) blocked-credit determination: {cat_line}. "
                f"{reason_line} Rejecting on IMS signals the supplier that "
                "credit will not be claimed."
            )
        elif cat_line:
            why = (
                f"Section 17(5) blocked-credit determination: {cat_line}. "
                "Rejecting on IMS signals the supplier that credit will not be claimed."
            )
        elif reason_line:
            why = (
                f"Section 17(5) blocked credit: {reason_line}. "
                "Rejecting on IMS signals the supplier that credit will not be claimed."
            )
        else:
            why = (
                "blocked_credit_flag is set on this reconcile outcome, but no "
                "Section 17(5) sub-clause/category was attached to the recommendation "
                "input. Reject pending CA confirmation of the specific 17(5) ground."
            )
        return _rec(
            inp,
            action="reject",
            score=score,
            conf_source=conf_source,
            codes=(REASON_BLOCKED_ITC,),
            why=why,
        )

    # Active Rule 37A → Hold (supplier GSTR-3B non-filing risk)
    if inp.rule37a_flag or (category == "rule37_warnings" and inp.match_status == "RULE37A"):
        return _rec(
            inp,
            action="hold",
            score=score,
            conf_source=conf_source,
            codes=(REASON_RULE37A_NON_FILER,),
            why=(
                "Supplier has not filed GSTR-3B for the tax period (Rule 37A risk). "
                "Hold on IMS until supplier files GSTR-3B to prevent mandatory ITC reversal."
            ),
        )

    # Active Rule 37 → Hold with real day-count when enriched.
    if inp.rule37_flag or category == "rule37_warnings":
        return _rec(
            inp,
            action="hold",
            score=score,
            conf_source=conf_source,
            codes=(REASON_RULE37_BREACH,),
            why=_rule37_why(inp),
        )

    match_status = (inp.match_status or "").strip().upper()
    has_amount_diff = abs(int(inp.total_tax_diff_paise or 0)) > 0 or abs(
        int(inp.taxable_value_diff_paise or 0)
    ) > 0

    if category == "matched" and match_status in ("", "MATCHED", "EXACT", "CLEAN"):
        if has_amount_diff:
            return _rec(
                inp,
                action="hold",
                score=score,
                conf_source=conf_source,
                codes=(REASON_AMOUNT_MISMATCH,),
                why=(
                    "Books and GSTR-2B are linked but tax/taxable amounts differ "
                    f"(tax_diff_paise={inp.total_tax_diff_paise}, "
                    f"taxable_diff_paise={inp.taxable_value_diff_paise}). "
                    "Hold on IMS until the discrepancy is resolved."
                ),
            )
        if not _accept_confidence_ok(score, conf_source):
            if conf_source == "matcher_fuzzy" and score is not None:
                return _rec(
                    inp,
                    action="hold",
                    score=score,
                    conf_source=conf_source,
                    codes=(REASON_LOW_MATCH_CONFIDENCE,),
                    why=(
                        f"Matcher confidence is {score:.0%} "
                        f"(below {CONFIDENCE_HIGH_MIN:.0%} high threshold). "
                        "Hold — ACCEPT requires high matcher confidence and no "
                        "Rule 37 / 17(5) flags."
                    ),
                )
            return _rec(
                inp,
                action="hold",
                score=score,
                conf_source=conf_source,
                codes=(REASON_NO_MATCH_CONFIDENCE,),
                why=(
                    "No matcher confidence score on this row and it is not an "
                    "exact linked match eligible for ACCEPT. Hold for manual review."
                ),
            )
        # ACCEPT: high fuzzy score OR exact link with no fuzzy score; flags already cleared.
        if conf_source == "matcher_exact_no_fuzzy_score":
            why = (
                "Invoice is matched in books with no material amount difference, "
                "no active Rule 37 flag, and no active Section 17(5) flag. "
                "Matcher left match_confidence blank (typical of exact L1–L4 tiers) "
                "— confidence_score is not fabricated; ACCEPT uses the exact-link "
                "convention from reconcile confidence bucketing."
            )
        else:
            why = (
                f"Invoice is matched in books (matcher confidence {score:.0%}), "
                "with no material amount difference, no active Rule 37 flag, and "
                "no active Section 17(5) flag. Accepting on IMS is consistent with books."
            )
        return _rec(
            inp,
            action="accept",
            score=score,
            conf_source=conf_source,
            codes=(REASON_MATCHED_IN_BOOKS,),
            why=why,
        )

    if category == "matched":
        return _rec(
            inp,
            action="hold",
            score=score,
            conf_source=conf_source,
            codes=(REASON_AMOUNT_MISMATCH, REASON_NEEDS_REVIEW),
            why=(
                f"Linked to books but match_status={match_status!r} is not clean. "
                "Hold until the CA reviews the discrepancy."
            ),
        )

    if category == "missed_itc":
        sec = (inp.section or "").strip().lower()
        if sec in ("cn", "cna", "cdnr"):
            return _rec(
                inp,
                action="hold",
                score=score,
                conf_source=conf_source,
                codes=(REASON_UNLINKED_CREDIT_NOTE,),
                why=(
                    "Supplier Credit Note is present on IMS/GSTR-2B but unlinked in Purchase Register. "
                    "Hold on IMS until the Credit Note is booked in accounting to prevent premature ITC reduction."
                ),
            )
        return _rec(
            inp,
            action="hold",
            score=score,
            conf_source=conf_source,
            codes=(REASON_NOT_IN_BOOKS,),
            why=(
                "Present in GSTR-2B but not matched in books "
                "(no matcher confidence on unmatched rows). "
                "Hold until the invoice is booked or deliberately left unclaimed."
            ),
        )

    if category == "wrongful_risk":
        return _rec(
            inp,
            action="hold",
            score=score,
            conf_source=conf_source,
            codes=(REASON_WRONGFUL_ITC_RISK,),
            why=(
                "Purchase-register invoice at ITC risk (not supported by GSTR-2B). "
                "Hold — accepting on IMS is not applicable for PR-only risk rows."
            ),
        )

    if category == "gstin_mismatch":
        pr_g = (inp.pr_supplier_gstin or "").strip().upper()
        gstr_g = (inp.gstr_supplier_gstin or "").strip().upper()
        if pr_g and gstr_g and pr_g != gstr_g:
            why = (
                f"Computed GSTIN mismatch: PR={pr_g} vs GSTR-2B={gstr_g}. "
                "Hold until the correct party is confirmed."
            )
        else:
            why = (
                "Category gstin_mismatch without both PR and GSTR GSTIN values "
                "on the recommendation input. Hold for manual review."
            )
        return _rec(
            inp,
            action="hold",
            score=score,
            conf_source=conf_source,
            codes=(REASON_GSTIN_MISMATCH,),
            why=why,
        )

    if category == "duplicate_entry":
        return _rec(
            inp,
            action="hold",
            score=score,
            conf_source=conf_source,
            codes=(REASON_DUPLICATE_AMBIGUITY,),
            why=(
                "Duplicate / ambiguous invoice grouping. "
                "Hold until the CA picks the correct document."
            ),
        )

    if category == "review_required":
        rev_reason = str(inp.review_reason or inp.match_status or "").strip().upper()
        if rev_reason in ("RCM_FLAG_CONFLICT", "RCM_CONFLICT"):
            return _rec(
                inp,
                action="hold",
                score=score,
                conf_source=conf_source,
                codes=(REASON_RCM_FLAG_CONFLICT, REASON_NEEDS_REVIEW),
                why=(
                    "Reverse charge treatment conflict: GSTR-2B reverse-charge indicator contradicts "
                    "the Purchase Register. Hold on IMS until RCM applicability under Section 9(3)/9(4) "
                    "is verified to prevent incorrect Table 3.1(d) / 4(A)(3) tax reporting."
                ),
            )
        if rev_reason in ("TAX_HEAD_MISMATCH", "TAX_HEADS_MISMATCH"):
            return _rec(
                inp,
                action="hold",
                score=score,
                conf_source=conf_source,
                codes=(REASON_TAX_HEAD_MISMATCH, REASON_NEEDS_REVIEW),
                why=(
                    "Tax head allocation mismatch: GSTR-2B and Purchase Register allocate tax to different "
                    "heads (IGST vs CGST+SGST or cess discrepancy) despite matching total tax. "
                    "Hold on IMS until Place of Supply is verified and supplier issues a Section 34 Credit Note or amendment."
                ),
            )
        conf_bit = (
            f" Matcher confidence={score:.0%}."
            if score is not None
            else " No matcher confidence on this review row."
        )
        return _rec(
            inp,
            action="hold",
            score=score,
            conf_source=conf_source,
            codes=(REASON_NEEDS_REVIEW,),
            why=(
                "Queued for Review Required."
                + conf_bit
                + " Hold on IMS until the match decision is settled."
            ),
        )

    return _rec(
        inp,
        action="hold",
        score=score,
        conf_source=conf_source,
        codes=(REASON_INSUFFICIENT_SIGNAL,),
        why=(
            "Insufficient reconcile signal to recommend Accept or Reject. "
            "Hold and review manually."
        ),
    )


def recommend_batch(
    inputs: Sequence[InvoiceRecommendationInput],
    *,
    run_id: str | None = None,
    period: str | None = None,
    gstin: str | None = None,
    source: str = "reconcile_ims_overlay",
) -> RecommendationBatch:
    invoices: list[InvoiceRecommendation] = []
    for inp in inputs:
        rec = recommend_invoice(inp)
        if rec is not None:
            invoices.append(rec)

    high = sum(1 for r in invoices if is_high_confidence_accept(r))
    return RecommendationBatch(
        available=True,
        reason=None,
        invoices=invoices,
        run_id=run_id,
        period=period,
        gstin=gstin,
        high_confidence_accept_count=high,
        source=source,
    )


def inputs_from_mapping(rows: Iterable[Mapping[str, Any]]) -> list[InvoiceRecommendationInput]:
    out: list[InvoiceRecommendationInput] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        inv_id = str(row.get("invoice_id") or row.get("id") or "").strip()
        gstin = str(row.get("supplier_gstin") or "").strip().upper()
        inum = str(row.get("invoice_number") or "").strip()
        if not inv_id or not gstin or not inum:
            continue
        wb = row.get("writeback_payload")
        out.append(
            InvoiceRecommendationInput(
                invoice_id=inv_id,
                supplier_gstin=gstin,
                invoice_number=inum,
                category=str(row.get("category") or "").strip().lower(),
                ims_status=str(row.get("ims_status") or "no_action_taken")
                .strip()
                .lower(),
                match_status=str(row.get("match_status") or ""),
                match_confidence=normalize_match_confidence(row.get("match_confidence")),
                total_tax_diff_paise=int(row.get("total_tax_diff_paise") or 0),
                taxable_value_diff_paise=int(
                    row.get("taxable_value_diff_paise")
                    or row.get("taxable_value_diff")
                    or 0
                ),
                amount_paise=_opt_int(row.get("amount_paise") or row.get("amount")),
                invoice_date=_opt_str(row.get("invoice_date")),
                supplier_name=_opt_str(row.get("supplier_name")),
                is_pending_action_blocked=bool(row.get("is_pending_action_blocked")),
                section=str(row.get("section") or "b2b").strip().lower() or "b2b",
                writeback_payload=wb if isinstance(wb, dict) else None,
                rule37_flag=bool(row.get("rule37_flag")),
                blocked_credit_flag=bool(row.get("blocked_credit_flag")),
                rule37_days_remaining=_opt_int(row.get("rule37_days_remaining")),
                rule37_status=_opt_str(row.get("rule37_status")),
                blocked_credit_category=_opt_str(row.get("blocked_credit_category")),
                blocked_credit_reason=_opt_str(row.get("blocked_credit_reason")),
                pr_supplier_gstin=_opt_str(row.get("pr_supplier_gstin")),
                gstr_supplier_gstin=_opt_str(row.get("gstr_supplier_gstin")),
            )
        )
    return out


def _rec(
    inp: InvoiceRecommendationInput,
    *,
    action: RecommendedAction,
    score: Optional[float],
    conf_source: ConfidenceSource,
    codes: tuple[str, ...],
    why: str,
) -> InvoiceRecommendation:
    return InvoiceRecommendation(
        invoice_id=inp.invoice_id,
        supplier_gstin=inp.supplier_gstin,
        invoice_number=inp.invoice_number,
        invoice_date=inp.invoice_date,
        supplier_name=inp.supplier_name,
        category=inp.category,
        ims_status=inp.ims_status,
        recommended_action=action,
        confidence_score=score,
        confidence_source=conf_source,
        reason_codes=codes,
        human_readable_why=why,
        amount_paise=inp.amount_paise,
        section=inp.section,
        writeback_payload=inp.writeback_payload,
        match_confidence=score if conf_source == "matcher_fuzzy" else (
            normalize_match_confidence(inp.match_confidence)
        ),
    )


def _opt_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _opt_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


# Back-compat alias used by older tests / callers
HIGH_CONFIDENCE_ACCEPT_MIN = CONFIDENCE_HIGH_MIN
