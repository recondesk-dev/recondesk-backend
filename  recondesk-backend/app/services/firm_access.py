"""Client scoping: runs and notes are allowed when ``reconciliation_run.client_gstin_id``
refers to a *client_gstins* row whose owner (``firm_owner_id`` → ``user_profiles.id``) or
assignee (``assigned_to``) matches the current user. No *user_profiles.firm_id* is used.

Every query against *client_gstins* must filter the owning user with column
``firm_owner_id`` (not ``user_id`` — that name is not on this table).
"""

from __future__ import annotations

from fastapi import HTTPException, status
from supabase import Client


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
    role = (profile.get("role") or "staff").strip().lower()

    if role == "admin":
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
    """Load reconciliation_run; 404 / 403 if not in accessible client scope."""
    res = (
        sb.table("reconciliation_run")
        .select(
            "id, client_gstin_id, period, status, is_locked, run_summary, "
            "created_at, completed_at, finalized_at, finalized_by"
        )
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="run not found",
        )
    row = res.data[0]
    cg = str(row.get("client_gstin_id", "")).strip()
    allowed = list_accessible_client_gstin_ids(sb, current_user)
    if cg not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="run not accessible for your account",
        )
    return row
