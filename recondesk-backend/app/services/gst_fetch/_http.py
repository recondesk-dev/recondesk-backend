"""Shared Sandbox GSP HTTP helpers for GSTR-1 / 2A / 3B fetches."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.integrations.gstn_error_mapper import map_gstn_error
from app.integrations.gstr2b_autofetch import SandboxGstnError

BASE_URL = "https://api.sandbox.co.in"
API_KEY = os.getenv("SANDBOX_API_KEY")

_log = logging.getLogger(__name__)

SectionStatus = Literal["success", "error"]


@dataclass
class SectionResult:
    section: str
    status: SectionStatus
    data: dict[str, Any] | None = None
    error_message: str | None = None
    error_cd: str | None = None


def _gstn_business_error(envelope: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (error_cd, message) when Sandbox/GSTN reports a business failure.

    GSTN often returns HTTP 200 with ``status_cd: "0"`` and an ``error`` object
    (e.g. ``error_cd: "RET11416"``). Also treat ``status_cd: "2"`` as no-data.
    """
    data = envelope.get("data")
    if not isinstance(data, dict):
        return None, None

    err = data.get("error")
    if isinstance(err, dict):
        cd = err.get("error_cd") or err.get("code")
        msg = err.get("message") or err.get("error_msg") or err.get("msg")
        if cd or msg:
            return (
                str(cd).strip() if cd else None,
                str(msg).strip() if msg else "GSTN business error",
            )

    status_cd = str(data.get("status_cd", "")).strip()
    if status_cd in ("0", "2"):
        return status_cd, f"GSTN status_cd={status_cd} (no data / failure)"
    return None, None


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


def get_section(
    path: str,
    *,
    token: str,
    section: str,
    timeout: float = 60.0,
) -> SectionResult:
    """GET one Sandbox sub-endpoint with a single retry on transient failures."""
    url = f"{BASE_URL}{path}"
    headers = {
        "authorization": token,
        "x-api-key": API_KEY,
        "x-api-version": "1.0.0",
    }
    last_exc: BaseException | None = None

    for attempt in range(2):
        try:
            _log.info("Sandbox GET %s section=%s attempt=%s", url, section, attempt + 1)
            r = httpx.get(url, headers=headers, timeout=timeout)
            r.raise_for_status()
            envelope = r.json()
            if not isinstance(envelope, dict):
                return SectionResult(
                    section=section,
                    status="error",
                    error_message=map_gstn_error("Unexpected GST portal response"),
                )

            err_cd, err_msg = _gstn_business_error(envelope)
            if err_msg:
                # GSTN-side / no-data — do not retry.
                return SectionResult(
                    section=section,
                    status="error",
                    error_cd=err_cd,
                    error_message=map_gstn_error(err_msg, error_code=err_cd),
                )

            data = envelope.get("data")
            if data is None:
                return SectionResult(
                    section=section,
                    status="error",
                    error_message=map_gstn_error("GST portal response missing data"),
                )
            if not isinstance(data, dict):
                # Some endpoints may return a list; wrap for uniform storage.
                data = {"value": data}

            return SectionResult(section=section, status="success", data=data)

        except Exception as exc:
            last_exc = exc
            if attempt == 0 and _is_transient(exc):
                _log.warning(
                    "Transient error section=%s; retrying once: %s",
                    section,
                    exc,
                )
                time.sleep(0.4)
                continue
            break

    assert last_exc is not None
    if isinstance(last_exc, httpx.HTTPStatusError):
        return SectionResult(
            section=section,
            status="error",
            error_message=map_gstn_error(last_exc),
        )
    if isinstance(last_exc, SandboxGstnError):
        return SectionResult(
            section=section,
            status="error",
            error_cd=last_exc.error_cd,
            error_message=map_gstn_error(last_exc.message, error_code=last_exc.error_cd),
        )
    return SectionResult(
        section=section,
        status="error",
        error_message=map_gstn_error(last_exc),
    )


def merged_from_results(results: list[SectionResult]) -> dict[str, Any]:
    """Build the public fetch() dict: successful sections only, keyed by section."""
    out: dict[str, Any] = {}
    for r in results:
        if r.status == "success" and r.data is not None:
            out[r.section] = r.data
    return out


def period_path_segment(year: str, month: str) -> str:
    return f"{str(year).strip()}-{str(month).strip().zfill(2)}"
