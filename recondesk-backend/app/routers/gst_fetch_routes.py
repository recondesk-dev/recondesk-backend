"""POST /api/fetch/{return_type} — GSTR-1 / 2A / 3B Sandbox auto-fetch."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, field_validator

from app.auth import get_current_active_user
from app.database import get_supabase
from app.services.firm_access import list_accessible_client_gstin_ids
from app.services.gst_fetch import VALID_RETURN_TYPES, dry_run_count, fetch_outcomes
from app.services.gst_fetch._http import period_path_segment
from app.services.gst_fetch.token import ensure_fresh_gstn_token, load_client_gstin
from app.services.r2_service import upload_file_to_r2

router = APIRouter(redirect_slashes=False)
_log = logging.getLogger(__name__)

ReturnTypePath = Literal["gstr1", "gstr2a", "gstr3b"]
_PERIOD_RE = re.compile(r"^(\d{4})-(\d{1,2})$")


class FetchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client_id: str
    period: str

    @field_validator("client_id", "period")
    @classmethod
    def strip_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


def _assert_client_access(sb, current_user: dict, client_id: str) -> None:
    allowed = list_accessible_client_gstin_ids(sb, current_user)
    if client_id not in allowed:
        _log.warning("GST fetch access denied: client_id=%s", client_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not allowed for this client",
        )


def parse_period(period: str) -> tuple[str, str]:
    """Parse ``YYYY-MM`` or ``YYYY-M`` into (year, month_zero_padded)."""
    m = _PERIOD_RE.match(period.strip())
    if not m:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="period must be YYYY-MM (e.g. 2026-06)",
        )
    year, month = m.group(1), m.group(2)
    month_i = int(month)
    if month_i < 1 or month_i > 12:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="period month must be 1–12",
        )
    return year, f"{month_i:02d}"


def _r2_key(gstin: str, return_type: str, year: str, month: str, section: str) -> str:
    return f"{gstin}/{return_type}/{period_path_segment(year, month)}/{section}.json"


def _log_section_row(
    sb,
    *,
    client_id: str,
    gstin: str,
    return_type: str,
    period: str,
    section: str,
    status_value: str,
    error_message: str | None,
) -> None:
    row = {
        "client_id": client_id,
        "gstin": gstin,
        "return_type": return_type,
        "period": period,
        "section": section,
        "status": status_value,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "error_message": error_message,
    }
    aurora_saved = False
    try:
        from app.repositories.integrations import get_integrations_repository
        repo = get_integrations_repository()
        repo.insert_gst_fetch_log(row)
        aurora_saved = True
    except Exception as a_exc:
        _log.warning("Aurora insert_gst_fetch_log failed, attempting Supabase fallback: %s", a_exc)

    if not aurora_saved:
        try:
            sb.table("gst_fetch_log").insert(row).execute()
        except Exception:
            _log.exception(
                "gst_fetch_log insert failed client_id=%s section=%s",
                client_id,
                section,
            )


@router.post("/{return_type}")
async def fetch_gst_return(
    return_type: ReturnTypePath,
    body: FetchRequest,
    include_amendments: bool = Query(False),
    include_isd: bool = Query(False),
    current_user: dict = Depends(get_current_active_user),
):
    """Fetch GSTR-1, GSTR-2A, or GSTR-3B for a connected client GSTIN session.

    Uploads each successful section JSON to R2 and writes per-section rows to
    ``gst_fetch_log``. Partial section failures do not abort the run.
    """
    rt = str(return_type).strip().lower()
    if rt not in VALID_RETURN_TYPES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"return_type must be one of {', '.join(VALID_RETURN_TYPES)}",
        )

    year, month = parse_period(body.period)
    period_norm = f"{year}-{month}"
    cid = body.client_id.strip()

    sb = get_supabase()
    _assert_client_access(sb, current_user, cid)

    client_row = load_client_gstin(sb, cid)
    gstin = str(client_row.get("gstin") or "").strip()
    if not gstin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client has no GSTIN on file",
        )

    # Refresh when near/past expiry; 409 only if refresh itself fails.
    access_token = await asyncio.to_thread(ensure_fresh_gstn_token, sb, client_row)

    planned_calls = dry_run_count(
        rt,
        include_amendments=include_amendments,
        include_isd=include_isd,
    )
    _log.info(
        "GST fetch starting return_type=%s client_id=%s gstin=%s period=%s "
        "planned_api_calls=%s include_amendments=%s include_isd=%s",
        rt,
        cid,
        gstin,
        period_norm,
        planned_calls,
        include_amendments,
        include_isd,
    )

    outcomes = await asyncio.to_thread(
        fetch_outcomes,
        rt,
        gstin,
        year,
        month,
        access_token,
        include_amendments=include_amendments,
        include_isd=include_isd,
    )

    sections_ok: list[str] = []
    sections_failed: list[dict[str, str]] = []
    r2_keys: dict[str, str] = {}
    merged: dict[str, Any] = {}

    for outcome in outcomes:
        if outcome.status == "success" and outcome.data is not None:
            key = _r2_key(gstin, rt, year, month, outcome.section)
            try:
                payload = json.dumps(outcome.data, ensure_ascii=False, default=str).encode(
                    "utf-8"
                )
                await asyncio.to_thread(
                    upload_file_to_r2,
                    payload,
                    key,
                    "application/json",
                )
                r2_keys[outcome.section] = key
            except Exception as exc:
                _log.exception(
                    "R2 upload failed gstin=%s section=%s key=%s",
                    gstin,
                    outcome.section,
                    key,
                )
                _log_section_row(
                    sb,
                    client_id=cid,
                    gstin=gstin,
                    return_type=rt,
                    period=period_norm,
                    section=outcome.section,
                    status_value="error",
                    error_message=f"R2 upload failed: {exc}",
                )
                sections_failed.append(
                    {"section": outcome.section, "error": f"R2 upload failed: {exc}"}
                )
                continue

            merged[outcome.section] = outcome.data
            sections_ok.append(outcome.section)
            _log_section_row(
                sb,
                client_id=cid,
                gstin=gstin,
                return_type=rt,
                period=period_norm,
                section=outcome.section,
                status_value="success",
                error_message=None,
            )
        else:
            err = outcome.error_message or "unknown error"
            sections_failed.append({"section": outcome.section, "error": err})
            _log_section_row(
                sb,
                client_id=cid,
                gstin=gstin,
                return_type=rt,
                period=period_norm,
                section=outcome.section,
                status_value="error",
                error_message=err,
            )

    return {
        "return_type": rt,
        "client_id": cid,
        "gstin": gstin,
        "period": period_norm,
        "planned_api_calls": planned_calls,
        "sections_ok": sections_ok,
        "sections_failed": sections_failed,
        "r2_keys": r2_keys,
        "data": merged,
    }
