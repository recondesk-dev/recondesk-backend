"""Client scoping: runs and notes are allowed when ``reconciliation_run.client_gstin_id``
refers to a *client_gstins* row whose owner (``firm_owner_id`` → ``user_profiles.id``) or
assignee (``assigned_to``) matches the current user. No *user_profiles.firm_id* is used.

Every query against *client_gstins* must filter the owning user with column
``firm_owner_id`` (not ``user_id`` — that name is not on this table).
"""

from __future__ import annotations

import logging
from fastapi import HTTPException, status
from supabase import Client

_log = logging.getLogger("recondesk.firm_access")


def firm_owner_id_for_user(sb: Client, current_user: dict) -> str:
    """The CA principal id that anchors this user's firm (admin = self)."""
    uid = str(current_user.get("id", "")).strip()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing user id",
        )
    return uid


def list_accessible_client_gstin_ids(sb: Client, current_user: dict) -> set[str]:
    """All client_gstin row ids the user may read/update for the API layer."""
    uid = str(current_user.get("id", "")).strip()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing user id",
        )
    # Role resolved synchronously in router when needed; here we branch via profile
    from app.database import get_user_profile  # local import to avoid cycle

    profile = get_user_profile(uid) or {}
    role = (current_user.get("role") or profile.get("role") or "").strip().lower()

    # 1. Dual-read: check Aurora tenancy repository
    try:
        from app.repositories.tenancy import get_tenancy_repository
        repo = get_tenancy_repository()
        if repo is not None:
            aurora_ids = repo.list_accessible_client_gstin_ids(uid, role=role)
            if aurora_ids is not None:
                return aurora_ids
    except Exception as exc:
        _log.warning("Aurora accessible clients lookup failed: %s", type(exc).__name__)

    # 2. Supabase fallback
    if role in ("admin", "owner") or not role:
        r = (
            sb.table("client_gstins")
            .select("id")
            .eq("firm_owner_id", uid)
            .eq("is_active", True)
            .execute()
        )
        return {str(x["id"]).strip() for x in (r.data or []) if x.get("id")}

    r = (
        sb.table("client_gstins")
        .select("id")
        .eq("assigned_to", uid)
        .eq("is_active", True)
        .execute()
    )
    return {str(x["id"]).strip() for x in (r.data or []) if x.get("id")}


def assert_client_gstin_in_firm(
    sb: Client, client_gstin_id: str, firm_owner_id: str
) -> None:
    # 1. Dual-read: check Aurora tenancy repository
    try:
        from app.repositories.tenancy import get_tenancy_repository
        repo = get_tenancy_repository()
        if repo is not None:
            ownership_result = repo.verify_firm_ownership(client_gstin_id, firm_owner_id)
            if ownership_result is True:
                return  # Authorized in Aurora
            elif ownership_result is False:
                # HARD AUTHORIZATION DENIAL: Record exists in Aurora but does not belong to firm_owner_id.
                # MUST NOT FALL THROUGH TO SUPABASE!
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="not allowed for this client",
                )
            # ownership_result is None -> Record not yet in Aurora (infrastructure miss), allow fallback
    except HTTPException:
        raise
    except Exception as exc:
        _log.warning("Aurora verify_firm_ownership failed: %s", type(exc).__name__)

    # 2. Supabase fallback
    res = (
        sb.table("client_gstins")
        .select("id")
        .eq("id", client_gstin_id)
        .eq("firm_owner_id", firm_owner_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not allowed for this client",
        )


def get_firm_owner_for_client(sb: Client, client_gstin_id: str) -> str:
    """Return *user_profiles.id* of the user who owns this client row (``client_gstins.firm_owner_id``)."""
    # 1. Dual-read: check Aurora tenancy repository
    try:
        from app.repositories.tenancy import get_tenancy_repository
        repo = get_tenancy_repository()
        if repo is not None:
            owner_id = repo.get_firm_owner_for_client(client_gstin_id)
            if owner_id:
                return owner_id
    except Exception as exc:
        _log.warning("Aurora get_firm_owner_for_client failed: %s", type(exc).__name__)

    # 2. Supabase fallback
    res = (
        sb.table("client_gstins")
        .select("firm_owner_id")
        .eq("id", str(client_gstin_id).strip())
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="client not found",
        )
    return str(res.data[0].get("firm_owner_id", "")).strip()


def user_can_access_firm(sb: Client, current_user: dict, firm_owner_id: str) -> bool:
    """True if the user is the firm owner or any staff assigned to a client of that firm."""
    uid = str(current_user.get("id", "")).strip()
    if not uid:
        return False
    if uid == firm_owner_id:
        return True

    # 1. Dual-read: check Aurora tenancy repository
    try:
        from app.repositories.tenancy import get_tenancy_repository
        repo = get_tenancy_repository()
        if repo is not None:
            aurora_access = repo.user_can_access_firm(uid, firm_owner_id)
            if aurora_access is True:
                return True
    except Exception as exc:
        _log.warning("Aurora user_can_access_firm failed: %s", type(exc).__name__)

    # 2. Supabase fallback
    r = (
        sb.table("client_gstins")
        .select("id")
        .eq("firm_owner_id", firm_owner_id)
        .eq("assigned_to", uid)
        .limit(1)
        .execute()
    )
    return bool(r.data)


def user_in_same_firm(
    sb: Client, current_user: dict, firm_owner_id: str, client_gstin_id: str | None
) -> bool:
    """True if the user is the firm owner or assigned to the given client row."""
    uid = str(current_user.get("id", "")).strip()
    if uid == firm_owner_id:
        return True
    if not client_gstin_id:
        return False

    # 1. Dual-read: check Aurora tenancy repository
    try:
        from app.repositories.tenancy import get_tenancy_repository
        repo = get_tenancy_repository()
        if repo is not None:
            same_firm_res = repo.user_in_same_firm(uid, firm_owner_id, client_gstin_id)
            if same_firm_res is True:
                return True
            elif same_firm_res is False:
                # Client exists in Aurora and does not match: HARD AUTHORIZATION DENIAL
                # MUST NOT FALL THROUGH TO SUPABASE!
                return False
            # None -> client not in Aurora (infrastructure miss), allow fallback
    except Exception as exc:
        _log.warning("Aurora user_in_same_firm failed: %s", type(exc).__name__)

    # 2. Supabase fallback
    r = (
        sb.table("client_gstins")
        .select("id")
        .eq("id", client_gstin_id)
        .eq("firm_owner_id", firm_owner_id)
        .eq("assigned_to", uid)
        .limit(1)
        .execute()
    )
    return bool(r.data)


def assert_firm_read_notes(
    sb: Client, current_user: dict, firm_owner_id: str, client_gstin_id: str
) -> None:
    """Notes GET: any team member of the firm (owner or staff of the firm)."""
    del client_gstin_id  # scoping: firm is enough for same-firm read
    if user_can_access_firm(sb, current_user, firm_owner_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="not allowed to read these notes",
    )


def assert_run_accessible(sb: Client, run_id: str, current_user: dict) -> dict:
    """Load reconciliation_run; 403 if missing or not in accessible client scope."""
    # 1. Dual-read: check Aurora reconciliation repository first
    try:
        from app.repositories.reconciliation import get_reconciliation_repository
        repo = get_reconciliation_repository()
        if repo is not None:
            aurora_run = repo.get_run(run_id)
            if aurora_run is not None:
                cg = str(aurora_run.get("client_gstin_id", "")).strip()
                allowed = list_accessible_client_gstin_ids(sb, current_user)
                if cg not in allowed:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Access denied",
                    )
                return aurora_run
    except HTTPException:
        raise
    except Exception as exc:
        _log.warning("Aurora assert_run_accessible failed: %s", type(exc).__name__)

    # 2. Supabase fallback
    res = (
        sb.table("reconciliation_run")
        .select(
            "id, client_gstin_id, period, status, is_locked, run_summary, "
            "created_at, completed_at, finalized_at, finalized_by, paid_at"
        )
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    row = res.data[0]
    cg = str(row.get("client_gstin_id", "")).strip()
    allowed = list_accessible_client_gstin_ids(sb, current_user)
    if cg not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return row
