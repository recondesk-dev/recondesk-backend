"""GSTR-3B fetch via Sandbox GSP API (single endpoint)."""

from __future__ import annotations

from typing import Any

from app.services.gst_fetch._http import (
    SectionResult,
    get_section,
    merged_from_results,
)

SECTION = "gstr3b"


def sections_for_fetch() -> tuple[str, ...]:
    return (SECTION,)


def fetch_outcomes(
    gstin: str,
    year: str,
    month: str,
    token: str,
) -> list[SectionResult]:
    """Fetch GSTR-3B for the period (one billed API call)."""
    _ = gstin
    year_s = str(year).strip()
    month_s = str(month).strip().zfill(2)
    path = f"/gst/compliance/tax-payer/gstrs/gstr-3b/{year_s}/{month_s}"
    return [get_section(path, token=token, section=SECTION)]


def fetch(
    gstin: str,
    year: str,
    month: str,
    token: str,
) -> dict[str, Any]:
    """Fetch GSTR-3B and return ``{"gstr3b": <payload>}`` on success."""
    return merged_from_results(fetch_outcomes(gstin, year, month, token))
