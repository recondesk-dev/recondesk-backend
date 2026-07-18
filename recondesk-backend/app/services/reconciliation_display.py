"""Computed display labels for reconciliation runs (not stored in DB)."""

from __future__ import annotations

from typing import Any, Mapping


def get_display_type(run: Mapping[str, Any] | None = None) -> str:
    """Return the UI type label for a purchase reconciliation run.

    Today every row from ``reconciliation_run`` is GSTR-2B vs purchase register.
    Kept centralized so GSTR-1 / GSTR-3B can plug in later without a schema change.
    """
    _ = run  # reserved for future source-based derivation
    return "GSTR-2B"
