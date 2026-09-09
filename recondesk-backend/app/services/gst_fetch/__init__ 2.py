"""GSTR-1 / GSTR-2A / GSTR-3B auto-fetch (Sandbox GSP), parallel to GSTR-2B."""

from __future__ import annotations

from typing import Any, Literal

from app.services.gst_fetch import gstr1, gstr2a, gstr3b
from app.services.gst_fetch._http import SectionResult

ReturnType = Literal["gstr1", "gstr2a", "gstr3b"]
VALID_RETURN_TYPES: tuple[str, ...] = ("gstr1", "gstr2a", "gstr3b")


def dry_run_count(
    return_type: str,
    *,
    include_amendments: bool = False,
    include_isd: bool = False,
) -> int:
    """How many billed Sandbox sub-endpoint calls a fetch will make."""
    rt = str(return_type).strip().lower()
    if rt == "gstr3b":
        return len(gstr3b.sections_for_fetch())
    if rt == "gstr1":
        return len(gstr1.sections_for_fetch(include_amendments=include_amendments))
    if rt == "gstr2a":
        return len(gstr2a.sections_for_fetch(include_isd=include_isd))
    raise ValueError(f"unsupported return_type: {return_type!r}")


def fetch_outcomes(
    return_type: str,
    gstin: str,
    year: str,
    month: str,
    token: str,
    *,
    include_amendments: bool = False,
    include_isd: bool = False,
) -> list[SectionResult]:
    """Dispatch to the return-type module; returns per-section outcomes."""
    rt = str(return_type).strip().lower()
    if rt == "gstr1":
        return gstr1.fetch_outcomes(
            gstin, year, month, token, include_amendments=include_amendments
        )
    if rt == "gstr2a":
        return gstr2a.fetch_outcomes(
            gstin, year, month, token, include_isd=include_isd
        )
    if rt == "gstr3b":
        return gstr3b.fetch_outcomes(gstin, year, month, token)
    raise ValueError(f"unsupported return_type: {return_type!r}")


def fetch(
    return_type: str,
    gstin: str,
    year: str,
    month: str,
    token: str,
    *,
    include_amendments: bool = False,
    include_isd: bool = False,
) -> dict[str, Any]:
    """Convenience: merged successful section payloads for ``return_type``."""
    from app.services.gst_fetch._http import merged_from_results

    return merged_from_results(
        fetch_outcomes(
            return_type,
            gstin,
            year,
            month,
            token,
            include_amendments=include_amendments,
            include_isd=include_isd,
        )
    )
