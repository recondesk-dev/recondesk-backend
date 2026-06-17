"""Valid status transitions for reconciliation import runs."""

from __future__ import annotations

from typing import FrozenSet

IMPORT_RUN_STATUSES = frozenset(
    {
        "draft",
        "gstr_uploaded",
        "pr_uploaded",
        "pending",
        "processing",
        "complete",
        "error",
        "cancelled",
    }
)

# allowed transitions: from_status -> set of to_status
_TRANSITIONS: dict[str, FrozenSet[str]] = {
    "draft": frozenset({"gstr_uploaded", "cancelled"}),
    "gstr_uploaded": frozenset({"pr_uploaded", "cancelled"}),
    "pr_uploaded": frozenset({"pending", "cancelled"}),
    "pending": frozenset({"processing", "cancelled", "error"}),
    "processing": frozenset({"complete", "error", "cancelled"}),
    "complete": frozenset(),
    "error": frozenset({"cancelled", "pr_uploaded"}),  # Try Again: back to PR step, keep files
    "cancelled": frozenset(),
}


def assert_transition_allowed(from_status: str, to_status: str) -> None:
    if from_status not in IMPORT_RUN_STATUSES or to_status not in IMPORT_RUN_STATUSES:
        raise ValueError("invalid status")
    allowed = _TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        raise ValueError(f"transition {from_status!r} -> {to_status!r} not allowed")


def can_transition(from_status: str, to_status: str) -> bool:
    try:
        assert_transition_allowed(from_status, to_status)
        return True
    except ValueError:
        return False
