"""GSTR-2A fetch via Sandbox GSP API (multi-section)."""

from __future__ import annotations

from typing import Any

from app.services.gst_fetch._http import (
    SectionResult,
    get_section,
    merged_from_results,
)

# Always fetched for CA recon.
CORE_SECTIONS = ("b2b", "cdna")
# Optional ISD / TCS — billed extra; default off (low priority for recon).
OPTIONAL_SECTIONS = ("isd", "tcs")


def sections_for_fetch(*, include_isd: bool = False) -> tuple[str, ...]:
    if include_isd:
        return CORE_SECTIONS + OPTIONAL_SECTIONS
    return CORE_SECTIONS


def fetch_outcomes(
    gstin: str,
    year: str,
    month: str,
    token: str,
    *,
    include_isd: bool = False,
) -> list[SectionResult]:
    """Fetch each GSTR-2A sub-endpoint; continue on per-section failures."""
    _ = gstin
    year_s = str(year).strip()
    month_s = str(month).strip().zfill(2)
    results: list[SectionResult] = []
    for section in sections_for_fetch(include_isd=include_isd):
        path = f"/gst/compliance/tax-payer/gstrs/gstr-2a/{section}/{year_s}/{month_s}"
        results.append(get_section(path, token=token, section=section))
    return results


def fetch(
    gstin: str,
    year: str,
    month: str,
    token: str,
    *,
    include_isd: bool = False,
) -> dict[str, Any]:
    """Fetch GSTR-2A sections and merge successful payloads into one dict."""
    return merged_from_results(
        fetch_outcomes(
            gstin,
            year,
            month,
            token,
            include_isd=include_isd,
        )
    )
