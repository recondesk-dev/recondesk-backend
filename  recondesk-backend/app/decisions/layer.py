"""Decision layer after compliance — audit-friendly structure for the run result."""

from __future__ import annotations

from typing import Any


def populate_decisions(
    matched_rows: list[dict[str, Any]],
    *,
    rule37: list[dict[str, Any]] | None = None,
    section_175_warnings: list[dict[str, Any]] | None = None,
    credit_note_adjustment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Enrich the reconciliation with rule outcomes (stub-friendly).

    *rule37* / *section_175_warnings* are attached as read-only context for the UI;
    the underlying rules engines stay separate for testability.
    """
    return {
        "rows": list(matched_rows),
        "rule37": list(rule37 or []),
        "section_17_5": list(section_175_warnings or []),
        "credit_note_adjustment": credit_note_adjustment or {},
    }
