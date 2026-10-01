"""Confidence-threshold auto-triage for Review Required → Matched.

Promotes high-confidence review_required pairs into clean_matched at the end
of a reconciliation run so KPI counts reflect the triage (not a client-only hide).

Status model choice: promote into Matched with ``auto_approved=True`` and
``match_status_text="Auto-Approved"`` rather than a separate bucket. That keeps
the invariant Matched + Review + Missed ITC = total GSTR, updates KPI cards, and
lets the Matched tab show an Auto-Approved badge without a new tab.
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)

DEFAULT_AUTO_APPROVE_THRESHOLD = 95


def normalize_confidence_threshold(raw: Any, default: int = DEFAULT_AUTO_APPROVE_THRESHOLD) -> int:
    """Clamp threshold to 0–100 integer percent."""
    try:
        val = int(float(raw))
    except (TypeError, ValueError):
        return default
    return max(0, min(100, val))


def _row_confidence_score(row: dict[str, Any]) -> float:
    """Prefer matcher ``confidence_score`` (0–100); fall back to match_confidence*100."""
    score = row.get("confidence_score")
    if score is not None:
        try:
            return float(score)
        except (TypeError, ValueError):
            pass
    mc = row.get("match_confidence")
    if mc is not None:
        try:
            v = float(mc)
            return v * 100.0 if v <= 1.0 else v
        except (TypeError, ValueError):
            pass
    return 0.0


def apply_confidence_auto_approve(
    clean_matched: list[dict[str, Any]],
    review_required: list[dict[str, Any]],
    threshold: int = DEFAULT_AUTO_APPROVE_THRESHOLD,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Move review rows with confidence >= threshold into clean_matched.

    PR-only marker rows (no gstr_id) are never auto-approved — they are not part
    of the Review Required KPI count.

    Returns (clean_matched, review_required, promoted_count).
    """
    threshold = normalize_confidence_threshold(threshold)
    kept: list[dict[str, Any]] = []
    promoted: list[dict[str, Any]] = []

    for row in review_required:
        gid = str(row.get("gstr_id") or "").strip()
        if not gid or gid == "None":
            kept.append(row)
            continue

        if _row_confidence_score(row) >= threshold:
            approved = dict(row)
            approved["match_status"] = "matched"
            approved["match_status_text"] = "Auto-Approved"
            approved["auto_approved"] = True
            # Preserve original review reason for audit trail.
            if approved.get("review_reason") or approved.get("reason"):
                approved["auto_approve_from_review_reason"] = (
                    approved.get("review_reason") or approved.get("reason")
                )
            if approved.get("match_level") in (0, None):
                approved["match_level"] = 1 if _row_confidence_score(row) == 100 else 2
            promoted.append(approved)
        else:
            kept.append(row)

    if promoted:
        _log.info(
            "Auto-approved %d review row(s) at confidence threshold %d%%",
            len(promoted),
            threshold,
        )

    return clean_matched + promoted, kept, len(promoted)
