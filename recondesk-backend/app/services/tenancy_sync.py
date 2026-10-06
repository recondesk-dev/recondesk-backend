"""Tenancy synchronization and recovery coordinator for ReconDesk.

Provides distributed synchronization tracking and recovery between Supabase (primary)
and AWS Aurora (secondary replica) across multiple backend processes and containers.

Guarantees:
1. When an Aurora mirror mutation fails, firm owner tenancy is marked as 'sync_pending'
   in shared Redis cache.
2. Subsequent reads (e.g. GET /api/clients) detect pending sync and attempt an inline
   reconciliation from Supabase to Aurora.
3. If Aurora is healthy, reconciliation succeeds, the pending flag is cleared, and Aurora
   returns authoritative data.
4. If Aurora is still down, the repository returns None (migration miss / sync unavailable),
   permitting seamless fallback to Supabase so no client is ever hidden.
5. In the absence of a failed mutation (normal path), authoritative empty results ([])
   remain strictly enforced without querying Supabase (preserving Phase 3D invariants).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.utils.redis_cache import get_redis_client

_log = logging.getLogger("recondesk.aurora.tenancy_sync")

# Key format: tenancy:sync_pending:<firm_owner_id>
_SYNC_PENDING_KEY_PREFIX = "tenancy:sync_pending:"
_SYNC_PENDING_TTL_SECONDS = 86400  # 24 hours

# In-process thread-safe fallback registry for environments where Redis is not configured (e.g. unit tests)
import threading
_local_registry_lock = threading.Lock()
_local_sync_registry: dict[str, dict[str, Any]] = {}


def mark_tenancy_sync_pending(
    user_id: str,
    *,
    action: str = "sync",
    entity_type: str = "tenancy",
    entity_id: str = "",
) -> None:
    """Mark that a tenancy write to Aurora failed for this user/firm and requires synchronization."""
    uid = str(user_id or "").strip()
    if not uid:
        return

    payload = {
        "user_id": uid,
        "action": action,
        "entity_type": entity_type,
        "entity_id": str(entity_id or ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload_str = json.dumps(payload)

    # 1. Distributed Redis key for multi-container synchronization
    r = get_redis_client()
    if r is not None:
        try:
            r.set(f"{_SYNC_PENDING_KEY_PREFIX}{uid}", payload_str, ex=_SYNC_PENDING_TTL_SECONDS)
        except Exception as exc:
            _log.warning("Failed to set tenancy:sync_pending in Redis for %s: %s", uid, type(exc).__name__)

    # 2. Local registry fallback for test runner environments without Redis
    with _local_registry_lock:
        _local_sync_registry[uid] = payload

    _log.info(
        "Tenancy sync marked pending for user_id=%s entity_type=%s entity_id=%s action=%s",
        uid,
        entity_type,
        entity_id,
        action,
    )


def is_tenancy_sync_pending(user_id: str) -> bool:
    """Check if this user/firm has a pending tenancy synchronization failure."""
    uid = str(user_id or "").strip()
    if not uid:
        return False

    r = get_redis_client()
    if r is not None:
        try:
            val = r.get(f"{_SYNC_PENDING_KEY_PREFIX}{uid}")
            if val is not None:
                return True
        except Exception as exc:
            _log.warning("Failed to check tenancy:sync_pending in Redis for %s: %s", uid, type(exc).__name__)

    with _local_registry_lock:
        return uid in _local_sync_registry


def clear_tenancy_sync_pending(user_id: str) -> None:
    """Clear pending tenancy synchronization flag once Aurora replica is synchronized."""
    uid = str(user_id or "").strip()
    if not uid:
        return

    r = get_redis_client()
    if r is not None:
        try:
            r.delete(f"{_SYNC_PENDING_KEY_PREFIX}{uid}")
        except Exception as exc:
            _log.warning("Failed to delete tenancy:sync_pending in Redis for %s: %s", uid, type(exc).__name__)

    with _local_registry_lock:
        _local_sync_registry.pop(uid, None)

    _log.info("Tenancy sync cleared for user_id=%s", uid)


def reconcile_user_tenancy_from_supabase(user_id: str, *, sb=None) -> bool:
    """Reconcile a user's tenancy data (user profile, clients, team members) from Supabase to Aurora.

    Returns:
        True: Aurora replica successfully synchronized and pending flag cleared.
        False: Aurora replica synchronization failed (Aurora down or error); pending flag remains set.
    """
    uid = str(user_id or "").strip()
    if not uid:
        return False

    from app.database import get_supabase
    from app.repositories.tenancy import get_tenancy_repository

    repo = get_tenancy_repository()
    if repo is None:
        _log.warning("Reconciliation skipped: AuroraTenancyRepository unavailable for user_id=%s", uid)
        return False

    client = sb or get_supabase()

    try:
        # 1. Sync UserProfile
        prof_res = client.table("user_profiles").select("*").eq("id", uid).limit(1).execute()
        if prof_res.data:
            repo.upsert_user_profile(prof_res.data[0])

        # 2. Sync ClientGSTIN records for this firm owner or assigned staff
        clients_res = (
            client.table("client_gstins")
            .select("*")
            .eq("firm_owner_id", uid)
            .execute()
        )
        for client_row in clients_res.data or []:
            repo.create_client(client_row)

        staff_clients_res = (
            client.table("client_gstins")
            .select("*")
            .eq("assigned_to", uid)
            .execute()
        )
        for client_row in staff_clients_res.data or []:
            repo.create_client(client_row)

        # 3. Sync TeamMember records for this firm owner or member
        team_res = (
            client.table("team_members")
            .select("*")
            .eq("firm_owner_id", uid)
            .execute()
        )
        for member_row in team_res.data or []:
            repo.create_or_update_team_member(member_row)

        staff_team_res = (
            client.table("team_members")
            .select("*")
            .eq("member_user_id", uid)
            .execute()
        )
        for member_row in staff_team_res.data or []:
            repo.create_or_update_team_member(member_row)

        # Success: clear pending flag
        clear_tenancy_sync_pending(uid)
        _log.info("Successfully reconciled tenancy to Aurora for user_id=%s", uid)
        return True
    except Exception as exc:
        _log.warning(
            "Tenancy reconciliation to Aurora failed for user_id=%s: %s",
            uid,
            type(exc).__name__,
        )
        return False


# ── Aurora Secondary Mirror Operations ────────────────────────────────────────

def mirror_client_create_to_aurora(
    client_row: dict[str, Any],
    firm_owner_id: str,
    *,
    current_user_id: Optional[str] = None,
) -> bool:
    """Secondary mirror for client creation / restoration to Aurora."""
    from app.repositories.tenancy import get_tenancy_repository
    repo = get_tenancy_repository()
    if repo is None:
        return True

    cid = str(client_row.get("id") or "")
    foid = str(firm_owner_id or client_row.get("firm_owner_id") or "").strip()
    try:
        repo.create_client(client_row)
        return True
    except Exception as exc:
        _log.warning(
            "Aurora mirror create_client failed for client_id=%s firm_owner_id=%s: %s",
            cid,
            foid,
            type(exc).__name__,
        )
        if foid:
            mark_tenancy_sync_pending(foid, action="create_client", entity_type="client_gstin", entity_id=cid)
        if current_user_id and current_user_id != foid:
            mark_tenancy_sync_pending(current_user_id, action="create_client", entity_type="client_gstin", entity_id=cid)
        return False


def mirror_client_update_to_aurora(
    client_id: str,
    updates: dict[str, Any],
    firm_owner_id: str,
    *,
    current_user_id: Optional[str] = None,
) -> bool:
    """Secondary mirror for client update / assignment to Aurora."""
    from app.repositories.tenancy import get_tenancy_repository
    repo = get_tenancy_repository()
    if repo is None:
        return True

    cid = str(client_id or "").strip()
    foid = str(firm_owner_id or "").strip()
    try:
        repo.update_client(cid, updates)
        return True
    except Exception as exc:
        _log.warning(
            "Aurora mirror update_client failed for client_id=%s firm_owner_id=%s: %s",
            cid,
            foid,
            type(exc).__name__,
        )
        if foid:
            mark_tenancy_sync_pending(foid, action="update_client", entity_type="client_gstin", entity_id=cid)
        if current_user_id and current_user_id != foid:
            mark_tenancy_sync_pending(current_user_id, action="update_client", entity_type="client_gstin", entity_id=cid)
        return False


def mirror_client_delete_to_aurora(
    client_id: str,
    firm_owner_id: str,
    *,
    current_user_id: Optional[str] = None,
) -> bool:
    """Secondary mirror for client soft deletion to Aurora."""
    from app.repositories.tenancy import get_tenancy_repository
    repo = get_tenancy_repository()
    if repo is None:
        return True

    cid = str(client_id or "").strip()
    foid = str(firm_owner_id or "").strip()
    try:
        repo.soft_delete_client(cid)
        return True
    except Exception as exc:
        _log.warning(
            "Aurora mirror soft_delete_client failed for client_id=%s firm_owner_id=%s: %s",
            cid,
            foid,
            type(exc).__name__,
        )
        if foid:
            mark_tenancy_sync_pending(foid, action="soft_delete_client", entity_type="client_gstin", entity_id=cid)
        if current_user_id and current_user_id != foid:
            mark_tenancy_sync_pending(current_user_id, action="soft_delete_client", entity_type="client_gstin", entity_id=cid)
        return False


def mirror_user_profile_upsert_to_aurora(
    profile_row: dict[str, Any],
    user_id: str,
) -> bool:
    """Secondary mirror for user profile creation / upsert to Aurora."""
    from app.repositories.tenancy import get_tenancy_repository
    repo = get_tenancy_repository()
    if repo is None:
        return True

    uid = str(user_id or profile_row.get("id") or "").strip()
    try:
        repo.upsert_user_profile(profile_row)
        return True
    except Exception as exc:
        _log.warning(
            "Aurora mirror upsert_user_profile failed for user_id=%s: %s",
            uid,
            type(exc).__name__,
        )
        if uid:
            mark_tenancy_sync_pending(uid, action="upsert_profile", entity_type="user_profile", entity_id=uid)
        return False


def mirror_user_profile_update_to_aurora(
    user_id: str,
    fields: dict[str, Any],
) -> bool:
    """Secondary mirror for user profile update to Aurora."""
    from app.repositories.tenancy import get_tenancy_repository
    repo = get_tenancy_repository()
    if repo is None:
        return True

    uid = str(user_id or "").strip()
    try:
        repo.update_user_profile(uid, fields)
        return True
    except Exception as exc:
        _log.warning(
            "Aurora mirror update_user_profile failed for user_id=%s: %s",
            uid,
            type(exc).__name__,
        )
        if uid:
            mark_tenancy_sync_pending(uid, action="update_profile", entity_type="user_profile", entity_id=uid)
        return False


def mirror_team_member_create_to_aurora(
    member_row: dict[str, Any],
    firm_owner_id: str,
) -> bool:
    """Secondary mirror for team invite creation to Aurora."""
    from app.repositories.tenancy import get_tenancy_repository
    repo = get_tenancy_repository()
    if repo is None:
        return True

    mid = str(member_row.get("id") or "")
    foid = str(firm_owner_id or member_row.get("firm_owner_id") or "").strip()
    try:
        repo.create_or_update_team_member(member_row)
        return True
    except Exception as exc:
        _log.warning(
            "Aurora mirror create_team_member failed for member_id=%s firm_owner_id=%s: %s",
            mid,
            foid,
            type(exc).__name__,
        )
        if foid:
            mark_tenancy_sync_pending(foid, action="create_team_member", entity_type="team_member", entity_id=mid)
        return False


def mirror_team_member_update_to_aurora(
    member_id: str,
    updates: dict[str, Any],
    firm_owner_id: str,
) -> bool:
    """Secondary mirror for team member update / acceptance to Aurora."""
    from app.repositories.tenancy import get_tenancy_repository
    repo = get_tenancy_repository()
    if repo is None:
        return True

    mid = str(member_id or "").strip()
    foid = str(firm_owner_id or "").strip()
    try:
        repo.update_team_member(mid, updates)
        return True
    except Exception as exc:
        _log.warning(
            "Aurora mirror update_team_member failed for member_id=%s firm_owner_id=%s: %s",
            mid,
            foid,
            type(exc).__name__,
        )
        if foid:
            mark_tenancy_sync_pending(foid, action="update_team_member", entity_type="team_member", entity_id=mid)
        return False


def mirror_team_member_remove_to_aurora(
    member_id: str,
    firm_owner_id: str,
) -> bool:
    """Secondary mirror for team member removal / deactivation to Aurora."""
    from app.repositories.tenancy import get_tenancy_repository
    repo = get_tenancy_repository()
    if repo is None:
        return True

    mid = str(member_id or "").strip()
    foid = str(firm_owner_id or "").strip()
    try:
        repo.deactivate_team_member(mid)
        return True
    except Exception as exc:
        _log.warning(
            "Aurora mirror deactivate_team_member failed for member_id=%s firm_owner_id=%s: %s",
            mid,
            foid,
            type(exc).__name__,
        )
        if foid:
            mark_tenancy_sync_pending(foid, action="deactivate_team_member", entity_type="team_member", entity_id=mid)
        return False
