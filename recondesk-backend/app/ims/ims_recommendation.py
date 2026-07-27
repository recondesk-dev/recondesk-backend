"""Phase 1 — per-invoice IMS action recommendations for CA review.

Pure recommendation logic. Never writes to GSTN. Output shape is the
contract consumed by the CA Action panel (Phase 3):

  recommended_action, confidence_score, reason_codes, human_readable_why

``hold`` is the CA-facing label for GSTN ``pending`` (park / take no
immediate accept-or-reject decision).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Literal, Mapping, Optional, Sequence

RecommendedAction = Literal["accept", "reject", "hold"]

# Already resolved on IMS — omit from the action queue.
_TERMINAL_IMS = frozenset({"accepted", "rejected"})

# Recon categories that feed recommendations.
_ACTIONABLE_CATEGORIES = frozenset(
    {
        "matched",
        "review_required",
        "missed_itc",
        "wrongful_risk",
        "blocked_credit",
        "gstin_mismatch",
        "duplicate_entry",
    }
)

HIGH_CONFIDENCE_ACCEPT_MIN = 0.85

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
REASON_ALREADY_ACTIONED = "ALREADY_ACTIONED"

REASON_UNAVAILABLE_NO_PAYLOAD = "no_reconcile_payload"
REASON_UNAVAILABLE_NO_INVOICES = "no_ims_candidates"


@dataclass(frozen=True)
class InvoiceRecommendationInput:
    """Minimal invoice context for recommendation (recon + IMS status)."""

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
    """Sandbox writeback section key (lowercase): b2b, cn, …"""
    writeback_payload: Optional[dict[str, Any]] = None
    """Raw IMS entry fields for confirmed writeback (Phase 2)."""


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
    confidence_score: float
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
    """Load-result envelope — mirrors GSTR-3B suggestion available/unavailable."""

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
    """Not wired / missing source — never a confirmed zero."""
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
    """API succeeded and zero invoices need IMS action."""
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


def is_high_confidence_accept(rec: InvoiceRecommendation) -> bool:
    return (
        rec.recommended_action == "accept"
        and rec.confidence_score >= HIGH_CONFIDENCE_ACCEPT_MIN
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

    if inp.is_pending_action_blocked:
        return _rec(
            inp,
            action="hold",
            confidence=0.95,
            codes=(REASON_ACTION_BLOCKED,),
            why=(
                "GSTN has blocked pending action on this invoice "
                "(ispendactblocked). Hold until the block clears — do not Accept or Reject."
            ),
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
                confidence=0.55,
                codes=(REASON_AMOUNT_MISMATCH,),
                why=(
                    "Books and GSTR-2B are linked but tax/taxable amounts differ. "
                    "Hold on IMS until the discrepancy is resolved."
                ),
            )
        conf = 0.92
        if inp.match_confidence is not None and inp.match_confidence >= 0.9:
            conf = min(0.98, 0.90 + float(inp.match_confidence) * 0.08)
        return _rec(
            inp,
            action="accept",
            confidence=conf,
            codes=(REASON_MATCHED_IN_BOOKS,),
            why=(
                "Invoice is matched in the purchase register with no material "
                "amount difference. Accepting on IMS is consistent with books."
            ),
        )

    if category == "matched":
        return _rec(
            inp,
            action="hold",
            confidence=0.55,
            codes=(REASON_AMOUNT_MISMATCH, REASON_NEEDS_REVIEW),
            why=(
                "Linked to books but match status is not clean. "
                "Hold until the CA reviews the discrepancy."
            ),
        )

    if category == "blocked_credit":
        return _rec(
            inp,
            action="reject",
            confidence=0.88,
            codes=(REASON_BLOCKED_ITC,),
            why=(
                "Flagged as blocked ITC (e.g. Section 17(5)). "
                "Rejecting on IMS signals the supplier that credit will not be claimed."
            ),
        )

    if category == "missed_itc":
        return _rec(
            inp,
            action="hold",
            confidence=0.58,
            codes=(REASON_NOT_IN_BOOKS,),
            why=(
                "Present in GSTR-2B but not matched in books. "
                "Hold until the invoice is booked or deliberately left unclaimed."
            ),
        )

    if category == "wrongful_risk":
        return _rec(
            inp,
            action="hold",
            confidence=0.62,
            codes=(REASON_WRONGFUL_ITC_RISK,),
            why=(
                "Purchase-register invoice at ITC risk (not supported by GSTR-2B). "
                "Hold — accepting on IMS is not applicable for PR-only risk rows; "
                "confirm before any reject of related supplier invoices."
            ),
        )

    if category == "gstin_mismatch":
        return _rec(
            inp,
            action="hold",
            confidence=0.48,
            codes=(REASON_GSTIN_MISMATCH,),
            why=(
                "Supplier GSTIN mismatch between books and GSTR-2B. "
                "Hold until the correct party is confirmed."
            ),
        )

    if category == "duplicate_entry":
        return _rec(
            inp,
            action="hold",
            confidence=0.5,
            codes=(REASON_DUPLICATE_AMBIGUITY,),
            why=(
                "Duplicate / ambiguous invoice grouping. "
                "Hold until the CA picks the correct document."
            ),
        )

    if category == "review_required":
        return _rec(
            inp,
            action="hold",
            confidence=0.45,
            codes=(REASON_NEEDS_REVIEW,),
            why=(
                "Queued for Review Required. "
                "Hold on IMS until the match decision is settled."
            ),
        )

    return _rec(
        inp,
        action="hold",
        confidence=0.4,
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
    """Build an available batch from inputs. Empty list → confirmed empty."""
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
    """Coerce loose dict rows (API / tests) into typed inputs."""
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
                match_confidence=_opt_float(row.get("match_confidence")),
                total_tax_diff_paise=int(row.get("total_tax_diff_paise") or 0),
                taxable_value_diff_paise=int(
                    row.get("taxable_value_diff_paise")
                    or row.get("taxable_value_diff")
                    or 0
                ),
                amount_paise=_opt_int(row.get("amount_paise") or row.get("amount")),
                invoice_date=_opt_str(row.get("invoice_date")),
                supplier_name=_opt_str(row.get("supplier_name")),
                is_pending_action_blocked=bool(
                    row.get("is_pending_action_blocked")
                ),
                section=str(row.get("section") or "b2b").strip().lower() or "b2b",
                writeback_payload=wb if isinstance(wb, dict) else None,
            )
        )
    return out


def _rec(
    inp: InvoiceRecommendationInput,
    *,
    action: RecommendedAction,
    confidence: float,
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
        confidence_score=round(float(confidence), 4),
        reason_codes=codes,
        human_readable_why=why,
        amount_paise=inp.amount_paise,
        section=inp.section,
        writeback_payload=inp.writeback_payload,
        match_confidence=inp.match_confidence,
    )


def _opt_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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
