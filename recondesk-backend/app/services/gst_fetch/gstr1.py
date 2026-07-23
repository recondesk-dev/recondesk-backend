"""GSTR-1 fetch via Sandbox GSP API (multi-section)."""

from __future__ import annotations

from typing import Any

from app.services.gst_fetch._http import (
    SectionResult,
    get_section,
    merged_from_results,
)

# Always fetched for recon.
CORE_SECTIONS = ("b2b", "b2cl", "b2cs", "summary")
# Optional amendments — billed extra calls; default off.
AMENDMENT_SECTIONS = ("b2ba", "b2cla", "b2csa", "cdnra")


def sections_for_fetch(*, include_amendments: bool = False) -> tuple[str, ...]:
    if include_amendments:
        return CORE_SECTIONS + AMENDMENT_SECTIONS
    return CORE_SECTIONS


def fetch_outcomes(
    gstin: str,
    year: str,
    month: str,
    token: str,
    *,
    include_amendments: bool = False,
) -> list[SectionResult]:
    """Fetch each GSTR-1 sub-endpoint; continue on per-section failures."""
    _ = gstin  # session-scoped; kept for call-site parity / logging
    year_s = str(year).strip()
    month_s = str(month).strip().zfill(2)
    results: list[SectionResult] = []
    for section in sections_for_fetch(include_amendments=include_amendments):
        path = f"/gst/compliance/tax-payer/gstrs/gstr-1/{section}/{year_s}/{month_s}"
        results.append(get_section(path, token=token, section=section))
    return results


def fetch(
    gstin: str,
    year: str,
    month: str,
    token: str,
    *,
    include_amendments: bool = False,
) -> dict[str, Any]:
    """Fetch GSTR-1 sections and merge successful payloads into one dict."""
    return merged_from_results(
        fetch_outcomes(
            gstin,
            year,
            month,
            token,
            include_amendments=include_amendments,
        )
    )
