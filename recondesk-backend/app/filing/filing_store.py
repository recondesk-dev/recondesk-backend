"""Persist ``filing_sessions`` / ``filing_runs`` (Supabase)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.filing.sandbox_filing_client import TaxpayerSession

logger = logging.getLogger(__name__)

SESSIONS = "filing_sessions"
RUNS = "filing_runs"


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def create_session(
    sb,
    *,
    firm_id: str,
    gstin: str,
    username: str,
    session: TaxpayerSession,
    client_gstin_id: str | None = None,
) -> dict[str, Any]:
    """Insert an active taxpayer session row; returns the inserted row."""
    payload: dict[str, Any] = {
        "firm_id": firm_id,
        "gstin": gstin.strip().upper(),
        "username": username.strip(),
        "session_token": session.access_token,
        "token_expires_at": _iso(session.token_expires_at),
        "session_expires_at": _iso(session.session_expires_at),
        "status": "active",
        "updated_at": _iso(datetime.now(timezone.utc)),
    }
    if client_gstin_id:
        payload["client_gstin_id"] = client_gstin_id
    res = sb.table(SESSIONS).insert(payload).execute()
    if not res.data:
        raise RuntimeError("filing_sessions insert returned no row")
    return res.data[0]


def update_session_token(
    sb,
    session_id: str,
    session: TaxpayerSession,
) -> dict[str, Any]:
    payload = {
        "session_token": session.access_token,
        "token_expires_at": _iso(session.token_expires_at),
        "session_expires_at": _iso(session.session_expires_at),
        "status": "active",
        "updated_at": _iso(datetime.now(timezone.utc)),
    }
    res = sb.table(SESSIONS).update(payload).eq("id", session_id).execute()
    return (res.data or [payload])[0]


def mark_session_logged_out(sb, session_id: str) -> None:
    """Mark local session logged_out even if Sandbox Logout returned TEC4002."""
    now = _iso(datetime.now(timezone.utc))
    sb.table(SESSIONS).update(
        {
            "status": "logged_out",
            "logged_out_at": now,
            "updated_at": now,
        }
    ).eq("id", session_id).execute()


def get_active_session(
    sb,
    *,
    firm_id: str,
    gstin: str,
) -> dict[str, Any] | None:
    """Latest active session for firm+gstin that is not past token_expires_at."""
    now = datetime.now(timezone.utc).isoformat()
    res = (
        sb.table(SESSIONS)
        .select("*")
        .eq("firm_id", firm_id)
        .eq("gstin", gstin.strip().upper())
        .eq("status", "active")
        .gt("token_expires_at", now)
        .order("token_expires_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def get_session_by_id(sb, session_id: str) -> dict[str, Any] | None:
    res = sb.table(SESSIONS).select("*").eq("id", session_id).limit(1).execute()
    return res.data[0] if res.data else None


def create_run(
    sb,
    *,
    firm_id: str,
    gstin: str,
    period: str,
    return_type: str = "gstr-1",
    status: str = "draft",
    filing_session_id: str | None = None,
    client_gstin_id: str | None = None,
    save_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "firm_id": firm_id,
        "gstin": gstin.strip().upper(),
        "return_type": return_type,
        "period": period,
        "status": status,
        "updated_at": _iso(datetime.now(timezone.utc)),
    }
    if filing_session_id:
        payload["filing_session_id"] = filing_session_id
    if client_gstin_id:
        payload["client_gstin_id"] = client_gstin_id
    if save_payload is not None:
        payload["save_payload"] = save_payload
    res = sb.table(RUNS).insert(payload).execute()
    if not res.data:
        raise RuntimeError("filing_runs insert returned no row")
    return res.data[0]


def update_run(
    sb,
    run_id: str,
    *,
    status: str | None = None,
    reference_id: str | None = None,
    ack_number: str | None = None,
    save_payload: dict[str, Any] | None = None,
    raw_response: Any = None,
    error_code: str | None = None,
    error_message: str | None = None,
    clear_error: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "updated_at": _iso(datetime.now(timezone.utc)),
    }
    if status is not None:
        payload["status"] = status
    if reference_id is not None:
        payload["reference_id"] = reference_id
    if ack_number is not None:
        payload["ack_number"] = ack_number
    if save_payload is not None:
        payload["save_payload"] = save_payload
    if raw_response is not None:
        payload["raw_response"] = raw_response
    if clear_error:
        payload["error_code"] = None
        payload["error_message"] = None
    if error_code is not None:
        payload["error_code"] = error_code
    if error_message is not None:
        payload["error_message"] = error_message
    res = sb.table(RUNS).update(payload).eq("id", run_id).execute()
    return (res.data or [payload])[0]


def get_run(sb, run_id: str) -> dict[str, Any] | None:
    res = sb.table(RUNS).select("*").eq("id", run_id).limit(1).execute()
    return res.data[0] if res.data else None


def mark_run_failed(
    sb,
    run_id: str,
    *,
    error_code: str | None,
    error_message: str,
    raw_response: Any = None,
) -> None:
    update_run(
        sb,
        run_id,
        status="failed",
        error_code=error_code,
        error_message=error_message[:2000],
        raw_response=raw_response,
    )


def apply_save_status_to_run(
    sb,
    run_id: str,
    *,
    return_status,
    envelope: Any = None,
) -> dict[str, Any]:
    """Apply a Save Return Status poll to ``filing_runs``.

    ``P`` → ``saved``; ``ER``/``PE`` → ``save_failed`` (error stored);
    otherwise remain / set ``save_pending``.
    """
    from app.filing.sandbox_filing_client import filing_run_status_after_save_poll

    status, err_cd, err_msg = filing_run_status_after_save_poll(return_status)
    if status == "saved":
        return update_run(
            sb,
            run_id,
            status="saved",
            raw_response=envelope,
            clear_error=True,
        )
    if status == "save_failed":
        return update_run(
            sb,
            run_id,
            status="save_failed",
            error_code=err_cd,
            error_message=(err_msg or "GSTN save failed")[:2000],
            raw_response=envelope,
        )
    return update_run(
        sb,
        run_id,
        status="save_pending",
        raw_response=envelope,
    )
