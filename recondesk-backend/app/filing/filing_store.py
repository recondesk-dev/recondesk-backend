"""Persist ``filing_sessions`` / ``filing_runs`` (Supabase)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.filing.sandbox_filing_client import TaxpayerSession

logger = logging.getLogger(__name__)

SESSIONS = "filing_sessions"
RUNS = "filing_runs"

# GSTR-3B: Offset succeeded (or later). Blocks Save + Offset for the period
# across ALL run_ids for (gstin, period, return_type=gstr-3b).
GSTR3B_OFFSET_LOCKED_STATUSES: frozenset[str] = frozenset({
    "offset_complete",
    "evc_pending",
    "filed",
})

RETURN_TYPE_GSTR3B = "gstr-3b"


class Gstr3bPeriodLockedError(Exception):
    """Save/Offset refused because Offset already completed for this period.

    Raised before any Sandbox call. Carries the locking run so callers can
    surface tx_pmt_snapshot / offset_completed_at as proof.
    """

    def __init__(
        self,
        message: str,
        *,
        action: str,
        gstin: str,
        period: str,
        locking_run: dict[str, Any],
    ) -> None:
        super().__init__(message)
        self.action = action
        self.gstin = gstin
        self.period = period
        self.locking_run = locking_run


def find_gstr3b_offset_lock(
    sb,
    *,
    gstin: str,
    period: str,
) -> dict[str, Any] | None:
    """Return any GSTR-3B run that has permanently completed Offset for period.

    Queries by ``(gstin, period, return_type)`` across **all** runs — not the
    current ``run_id``. Used to hard-block a second Save or Offset attempt.
    """
    try:
        from app.repositories.filing_automation import get_filing_automation_repository
        return get_filing_automation_repository().find_gstr3b_offset_lock(
            gstin=gstin,
            period=period,
        )
    except Exception as a_exc:
        logger.warning("Aurora find_gstr3b_offset_lock failed: %s; falling back to Supabase", a_exc)

    g = (gstin or "").strip().upper()
    p = (period or "").strip()
    if not g or not p:
        return None
    res = (
        sb.table(RUNS)
        .select(
            "id, status, offset_completed_at, tx_pmt_snapshot, "
            "offset_payload, reference_id, created_at, updated_at"
        )
        .eq("return_type", RETURN_TYPE_GSTR3B)
        .eq("gstin", g)
        .eq("period", p)
        .in_("status", sorted(GSTR3B_OFFSET_LOCKED_STATUSES))
        .order("offset_completed_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def assert_gstr3b_period_unlocked(
    sb,
    *,
    gstin: str,
    period: str,
    action: str,
) -> None:
    """Hard-block Save or Offset when Offset already completed for the period.

    ``action`` is ``\"save\"`` or ``\"offset\"`` (used in the error message).
    Corrections after Offset must go in a **future** period's return — there
    is no read-only Save path for a locked period.
    """
    action_key = (action or "").strip().lower()
    if action_key not in ("save", "offset"):
        raise ValueError(f"action must be 'save' or 'offset'; got {action!r}")

    locking = find_gstr3b_offset_lock(sb, gstin=gstin, period=period)
    if locking is None:
        return

    g = (gstin or "").strip().upper()
    p = (period or "").strip()
    lock_id = locking.get("id")
    lock_status = locking.get("status")
    completed_at = locking.get("offset_completed_at")
    has_tx_pmt = locking.get("tx_pmt_snapshot") is not None

    if action_key == "save":
        detail = (
            f"GSTR-3B Save is blocked for {g} period {p}: Offset Liability "
            f"already completed (run_id={lock_id}, status={lock_status!r}"
            f"{f', offset_completed_at={completed_at}' if completed_at else ''}). "
            "The return for this period is locked after Offset. Correct any "
            "figures in a future period's GSTR-3B — do not Save again here."
        )
    else:
        detail = (
            f"GSTR-3B Offset Liability is blocked for {g} period {p}: Offset "
            f"already completed (run_id={lock_id}, status={lock_status!r}"
            f"{f', offset_completed_at={completed_at}' if completed_at else ''}). "
            "A second Offset must not be attempted. Proof: post-Offset Get "
            f"Details tx_pmt "
            f"{'is stored on that run' if has_tx_pmt else 'should be re-fetched from GSTN for that run'}. "
            "Handle corrections in a future period's return."
        )
    raise Gstr3bPeriodLockedError(
        detail,
        action=action_key,
        gstin=g,
        period=p,
        locking_run=locking,
    )


def assert_gstr3b_save_allowed(sb, *, gstin: str, period: str) -> None:
    """Refuse a new Save when Offset already completed for (gstin, period)."""
    assert_gstr3b_period_unlocked(
        sb, gstin=gstin, period=period, action="save",
    )


def assert_gstr3b_offset_allowed(sb, *, gstin: str, period: str) -> None:
    """Refuse Offset when any run already reached offset_complete (or later)."""
    assert_gstr3b_period_unlocked(
        sb, gstin=gstin, period=period, action="offset",
    )


def gstr3b_period_locked_detail(exc: Gstr3bPeriodLockedError) -> dict[str, Any]:
    """Structured ``409`` body for FE / CA: which run holds the lock + proof."""
    run = exc.locking_run if isinstance(exc.locking_run, dict) else {}
    return {
        "code": "GSTR3B_PERIOD_LOCKED",
        "action": exc.action,
        "message": str(exc),
        "gstin": exc.gstin,
        "period": exc.period,
        "locking_run": {
            "run_id": run.get("id"),
            "status": run.get("status"),
            "offset_completed_at": run.get("offset_completed_at"),
            "reference_id": run.get("reference_id"),
            "offset_payload": run.get("offset_payload"),
            "tx_pmt_snapshot": run.get("tx_pmt_snapshot"),
        },
    }


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
    try:
        from app.repositories.filing_automation import get_filing_automation_repository
        return get_filing_automation_repository().create_session(
            firm_id=firm_id,
            gstin=gstin,
            username=username,
            session=session,
            client_gstin_id=client_gstin_id,
        )
    except Exception as a_exc:
        logger.warning("Aurora create_session failed: %s; falling back to Supabase", a_exc)

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
    try:
        from app.repositories.filing_automation import get_filing_automation_repository
        res = get_filing_automation_repository().update_session_token(
            session_id=session_id,
            session=session,
        )
        if res is not None:
            return res
    except Exception as a_exc:
        logger.warning("Aurora update_session_token failed: %s; falling back to Supabase", a_exc)

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
    try:
        from app.repositories.filing_automation import get_filing_automation_repository
        get_filing_automation_repository().mark_session_logged_out(session_id=session_id)
        return
    except Exception as a_exc:
        logger.warning("Aurora mark_session_logged_out failed: %s; falling back to Supabase", a_exc)

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
    try:
        from app.repositories.filing_automation import get_filing_automation_repository
        return get_filing_automation_repository().get_active_session(
            firm_id=firm_id,
            gstin=gstin,
        )
    except Exception as a_exc:
        logger.warning("Aurora get_active_session failed: %s; falling back to Supabase", a_exc)

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
    try:
        from app.repositories.filing_automation import get_filing_automation_repository
        return get_filing_automation_repository().get_session_by_id(session_id=session_id)
    except Exception as a_exc:
        logger.warning("Aurora get_session_by_id failed: %s; falling back to Supabase", a_exc)

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
    try:
        from app.repositories.filing_automation import get_filing_automation_repository
        return get_filing_automation_repository().create_run(
            firm_id=firm_id,
            gstin=gstin,
            period=period,
            return_type=return_type,
            status=status,
            filing_session_id=filing_session_id,
            client_gstin_id=client_gstin_id,
            save_payload=save_payload,
        )
    except Exception as a_exc:
        logger.warning("Aurora create_run failed: %s; falling back to Supabase", a_exc)

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
    offset_payload: dict[str, Any] | None = None,
    offset_completed_at: str | None = None,
    tx_pmt_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        from app.repositories.filing_automation import get_filing_automation_repository
        res = get_filing_automation_repository().update_run(
            run_id,
            status=status,
            reference_id=reference_id,
            ack_number=ack_number,
            save_payload=save_payload,
            raw_response=raw_response,
            error_code=error_code,
            error_message=error_message,
            clear_error=clear_error,
            offset_payload=offset_payload,
            offset_completed_at=offset_completed_at,
            tx_pmt_snapshot=tx_pmt_snapshot,
        )
        if res is not None:
            return res
    except Exception as a_exc:
        logger.warning("Aurora update_run failed: %s; falling back to Supabase", a_exc)

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
    if offset_payload is not None:
        payload["offset_payload"] = offset_payload
    if offset_completed_at is not None:
        payload["offset_completed_at"] = offset_completed_at
    if tx_pmt_snapshot is not None:
        payload["tx_pmt_snapshot"] = tx_pmt_snapshot
    res = sb.table(RUNS).update(payload).eq("id", run_id).execute()
    return (res.data or [payload])[0]


def get_run(sb, run_id: str) -> dict[str, Any] | None:
    try:
        from app.repositories.filing_automation import get_filing_automation_repository
        return get_filing_automation_repository().get_run(run_id)
    except Exception as a_exc:
        logger.warning("Aurora get_run failed: %s; falling back to Supabase", a_exc)

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


def apply_offset_status_to_run(
    sb,
    run_id: str,
    *,
    return_status,
    envelope: Any = None,
    offset_payload: dict[str, Any] | None = None,
    tx_pmt_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply an Offset Return Status poll to ``filing_runs``.

    ``P`` → ``offset_complete`` (+ ``offset_completed_at``, optional snapshots);
    ``ER``/``PE`` → ``offset_failed`` (gate stays off — CA may retry);
    otherwise ``offset_pending``.
    """
    from app.filing.sandbox_filing_client import filing_run_status_after_offset_poll

    status, err_cd, err_msg = filing_run_status_after_offset_poll(return_status)
    if status == "offset_complete":
        return update_run(
            sb,
            run_id,
            status="offset_complete",
            raw_response=envelope,
            clear_error=True,
            offset_payload=offset_payload,
            offset_completed_at=_iso(datetime.now(timezone.utc)),
            tx_pmt_snapshot=tx_pmt_snapshot,
        )
    if status == "offset_failed":
        return update_run(
            sb,
            run_id,
            status="offset_failed",
            error_code=err_cd,
            error_message=(err_msg or "GSTN offset failed")[:2000],
            raw_response=envelope,
        )
    return update_run(
        sb,
        run_id,
        status="offset_pending",
        raw_response=envelope,
    )


BATCHES = "filing_batches"
BATCH_ITEMS = "filing_batch_items"


def create_batch(
    sb,
    *,
    firm_id: str,
    created_by: str,
    period: str,
    client_gstin_ids: list[str],
    return_type: str = "gstr-1",
) -> dict[str, Any]:
    """Create a new filing_batches row along with its filing_batch_items."""
    try:
        from app.repositories.filing_automation import get_filing_automation_repository
        return get_filing_automation_repository().create_batch(
            firm_id=firm_id,
            created_by=created_by,
            period=period,
            client_gstin_ids=client_gstin_ids,
            return_type=return_type,
        )
    except Exception as a_exc:
        logger.warning("Aurora create_batch failed: %s; falling back to Supabase", a_exc)

    p = period.strip()
    batch_payload = {
        "firm_id": firm_id,
        "created_by": created_by,
        "return_type": return_type,
        "period": p,
        "status": "pending",
        "total_count": len(client_gstin_ids),
        "updated_at": _iso(datetime.now(timezone.utc)),
    }
    b_res = sb.table(BATCHES).insert(batch_payload).execute()
    if not b_res.data:
        raise RuntimeError("filing_batches insert failed")
    batch = b_res.data[0]
    batch_id = batch["id"]

    # Fetch GSTIN strings for each client_gstin_id
    if client_gstin_ids:
        cg_res = (
            sb.table("client_gstins")
            .select("id, gstin")
            .in_("id", client_gstin_ids)
            .execute()
        )
        gstin_map = {
            str(r["id"]): str(r["gstin"]).strip().upper()
            for r in (cg_res.data or [])
        }

        item_rows = [
            {
                "batch_id": batch_id,
                "client_gstin_id": cid,
                "gstin": gstin_map.get(cid, ""),
                "status": "pending",
                "updated_at": _iso(datetime.now(timezone.utc)),
            }
            for cid in client_gstin_ids
        ]
        sb.table(BATCH_ITEMS).insert(item_rows).execute()

    return get_batch(sb, batch_id) or batch


def get_batch(sb, batch_id: str) -> dict[str, Any] | None:
    try:
        from app.repositories.filing_automation import get_filing_automation_repository
        res = get_filing_automation_repository().get_batch(batch_id)
        if res is not None:
            return res
    except Exception as a_exc:
        logger.warning("Aurora get_batch failed: %s; falling back to Supabase", a_exc)

    try:
        res = sb.table(BATCHES).select("*").eq("id", batch_id).limit(1).execute()
        if not res.data:
            return None
        batch = res.data[0]
        items_res = (
            sb.table(BATCH_ITEMS)
            .select("*, client_gstins(trade_name, legal_name)")
            .eq("batch_id", batch_id)
            .order("created_at")
            .execute()
        )
        batch["items"] = items_res.data or []
        return batch
    except Exception as s_exc:
        logger.warning("Supabase get_batch failed: %s", s_exc)
        return None


def list_batches(sb, firm_id: str, limit: int = 50) -> list[dict[str, Any]]:
    try:
        from app.repositories.filing_automation import get_filing_automation_repository
        return get_filing_automation_repository().list_batches(firm_id, limit=limit)
    except Exception as a_exc:
        logger.warning("Aurora list_batches failed: %s; falling back to Supabase", a_exc)

    res = (
        sb.table(BATCHES)
        .select("*")
        .eq("firm_id", firm_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


def update_batch_item(
    sb,
    item_id: str,
    *,
    status: str | None = None,
    filing_run_id: str | None = None,
    error_code: str | None = None,
    error_detail: str | None = None,
) -> dict[str, Any]:
    try:
        from app.repositories.filing_automation import get_filing_automation_repository
        res = get_filing_automation_repository().update_batch_item(
            item_id,
            status=status,
            filing_run_id=filing_run_id,
            error_code=error_code,
            error_detail=error_detail,
        )
        if res is not None:
            return res
    except Exception as a_exc:
        logger.warning("Aurora update_batch_item failed: %s; falling back to Supabase", a_exc)

    payload: dict[str, Any] = {
        "updated_at": _iso(datetime.now(timezone.utc)),
    }
    if status is not None:
        payload["status"] = status
    if filing_run_id is not None:
        payload["filing_run_id"] = filing_run_id
    if error_code is not None:
        payload["error_code"] = error_code
    if error_detail is not None:
        payload["error_detail"] = error_detail[:2000]

    res = sb.table(BATCH_ITEMS).update(payload).eq("id", item_id).execute()
    return (res.data or [payload])[0]


def recalculate_batch_status(sb, batch_id: str) -> dict[str, Any]:
    """Aggregate item statuses and update filing_batches summary counts & overall status."""
    try:
        from app.repositories.filing_automation import get_filing_automation_repository
        res = get_filing_automation_repository().recalculate_batch_status(batch_id)
        if res is not None:
            return res
    except Exception as a_exc:
        logger.warning("Aurora recalculate_batch_status failed: %s; falling back to Supabase", a_exc)

    items_res = (
        sb.table(BATCH_ITEMS)
        .select("status")
        .eq("batch_id", batch_id)
        .execute()
    )
    items = items_res.data or []
    total = len(items)

    saved_c = sum(1 for i in items if i["status"] == "saved")
    evc_pending_c = sum(1 for i in items if i["status"] == "evc_pending")
    filed_c = sum(1 for i in items if i["status"] == "filed")
    failed_c = sum(1 for i in items if i["status"] == "failed")
    needs_review_c = sum(1 for i in items if i["status"] == "needs_review")
    in_prog_c = sum(1 for i in items if i["status"] in ("in_progress", "pending"))

    if in_prog_c > 0:
        overall_status = "in_progress"
    elif filed_c == total and total > 0:
        overall_status = "completed"
    elif failed_c == total and total > 0:
        overall_status = "failed"
    else:
        overall_status = "partially_completed"

    payload = {
        "status": overall_status,
        "saved_count": saved_c,
        "evc_pending_count": evc_pending_c,
        "filed_count": filed_c,
        "failed_count": failed_c,
        "needs_review_count": needs_review_c,
        "updated_at": _iso(datetime.now(timezone.utc)),
    }
    b_res = sb.table(BATCHES).update(payload).eq("id", batch_id).execute()
    return (b_res.data or [payload])[0]


def update_batch_status(sb, batch_id: str, status: str) -> dict[str, Any]:
    """Update batch status directly (Aurora PRIMARY with Supabase fallback)."""
    try:
        from app.repositories.filing_automation import get_filing_automation_repository
        res = get_filing_automation_repository().update_batch_status(batch_id, status=status)
        if res is not None:
            return res
    except Exception as a_exc:
        logger.warning("Aurora update_batch_status failed: %s; falling back to Supabase", a_exc)

    now = _iso(datetime.now(timezone.utc))
    payload = {
        "status": status,
        "updated_at": now,
    }
    b_res = sb.table(BATCHES).update(payload).eq("id", batch_id).execute()
    return (b_res.data or [payload])[0]


def get_filing_history(sb, *, gstin: str, limit: int = 100) -> list[dict[str, Any]]:
    """Retrieve filing history for a gstin (Aurora PRIMARY with Supabase fallback)."""
    try:
        from app.repositories.filing_automation import get_filing_automation_repository
        return get_filing_automation_repository().get_filing_history(gstin=gstin, limit=limit)
    except Exception as a_exc:
        logger.warning("Aurora get_filing_history failed: %s; falling back to Supabase", a_exc)

    g = (gstin or "").strip().upper()
    runs = (
        sb.table(RUNS)
        .select(
            "id, return_type, period, status, reference_id, arn, filing_method, "
            "created_at, updated_at, offset_completed_at, filed_at"
        )
        .eq("gstin", g)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return runs.data or []


