"""Insert-only audit log rows; never raise to callers on failure."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from supabase import Client

from app.database import get_supabase, get_user_profile, resolve_user_role
from app.utils.context import get_correlation_id

logger = logging.getLogger(__name__)

_SENSITIVE_KEYS = frozenset(
    {
        "gstin",
        "pan",
        "email",
        "phone",
        "token",
        "password",
    }
)

_GSTIN_RE = re.compile(
    r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b", re.IGNORECASE
)


def _mask_metadata(meta: Any) -> Any:
    if isinstance(meta, dict):
        out: dict[str, Any] = {}
        for k, v in meta.items():
            key = str(k)
            if key.lower() in _SENSITIVE_KEYS:
                out[key] = "[REDACTED]"
            elif isinstance(v, (dict, Mapping)):
                out[key] = _mask_metadata(dict(v))
            elif isinstance(v, list):
                out[key] = [
                    _mask_metadata(x) if isinstance(x, (dict, list)) else x for x in v
                ]
            else:
                out[key] = v
        return out
    if isinstance(meta, list):
        return [
            _mask_metadata(x) if isinstance(x, (dict, list)) else x for x in meta
        ]
    return meta


def _client_ip_for_insert(ip_address: Optional[str]) -> Optional[str]:
    if not ip_address:
        return None
    if len(ip_address) > 128:
        return ip_address[:128]
    return ip_address


def _redact_gstin_in_strings(obj: Any) -> Any:
    if isinstance(obj, str):
        return _GSTIN_RE.sub("[REDACTED_GSTIN]", obj)
    if isinstance(obj, dict):
        return {k: _redact_gstin_in_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_gstin_in_strings(x) for x in obj]
    return obj


def _staff_firm_owner_id(db: Any = None, uid: Optional[str] = None) -> Optional[str]:
    """Firm owner id for a staff member via team membership / client assignment.

    There is no ``user_profiles.firm_id`` column in this codebase; the firm anchor
    for staff is ``team_members.firm_owner_id`` (or ``client_gstins.assigned_to``).
    """
    # Support both _staff_firm_owner_id(db, uid) and _staff_firm_owner_id(uid)
    if uid is None and db is not None and isinstance(db, str):
        uid = db
        db = None

    target_uid = str(uid or "").strip()
    if not target_uid:
        return None

    # 1. Phase 3C: Try Aurora tenancy repository first
    try:
        from app.repositories.tenancy import get_tenancy_repository
        repo = get_tenancy_repository()
        if repo is not None:
            owner_id = repo.get_firm_owner_id_for_user(target_uid)
            if owner_id is not None:
                return owner_id
    except Exception:
        pass

    # 2. Supabase fallback
    client = db or get_supabase()
    try:
        tm = (
            client.table("team_members")
            .select("firm_owner_id")
            .eq("member_user_id", target_uid)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if tm.data and tm.data[0].get("firm_owner_id"):
            return str(tm.data[0]["firm_owner_id"])
        cg = (
            client.table("client_gstins")
            .select("firm_owner_id")
            .eq("assigned_to", target_uid)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if cg.data and cg.data[0].get("firm_owner_id"):
            return str(cg.data[0]["firm_owner_id"])
    except Exception:
        pass
    return None


def resolve_firm_id(db: Any = None, user: Any = None) -> Optional[str]:
    """Resolve the workspace owner id (firm anchor) for the acting user.

    Precedence:
      1. Explicit ``user['firm_id']`` when present.
      2. Aurora tenancy repository resolution for user id.
      3. role == 'admin' → the user's own id.
      4. role == 'staff' → firm owner via team membership / client assignment.
      5. On any failure → log and return ``None`` (row still inserts).
    """
    # Support both resolve_firm_id(db, user) and resolve_firm_id(user_or_uid)
    if user is None and db is not None and not hasattr(db, "table"):
        user = db
        db = None

    explicit = ""
    uid = ""
    if isinstance(user, (Mapping, dict)):
        explicit = str(user.get("firm_id") or "").strip()
        if explicit:
            return explicit
        uid = str(user.get("id", "") or "").strip()
    elif isinstance(user, str):
        uid = user.strip()

    if not uid:
        logger.warning("audit firm_id unresolved: user context has no id")
        return None

    # 1. Phase 3C: Try Aurora tenancy repository first
    try:
        from app.repositories.tenancy import get_tenancy_repository
        repo = get_tenancy_repository()
        if repo is not None:
            owner_id = repo.get_firm_owner_id_for_user(uid)
            if owner_id is not None:
                return owner_id
    except Exception:
        pass

    client = db or get_supabase()
    role = str(user.get("role") if isinstance(user, (Mapping, dict)) else "" or "").strip().lower()
    if not role:
        try:
            email = user.get("email") if isinstance(user, (Mapping, dict)) else None
            role = resolve_user_role(
                role,
                user_id=uid,
                email=email,
                client=client,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("audit role resolution failed for user_id=%s: %s", uid, exc)
            role = ""

    # 2. Admin owns the firm.
    if role in ("admin", "owner"):
        return uid

    # 3. Staff → derive the firm owner.
    try:
        owner = _staff_firm_owner_id(client, uid)
        if owner:
            return owner
    except Exception as exc:  # noqa: BLE001
        logger.warning("audit firm_id resolution failed for user_id=%s: %s", uid, exc)
        return None

    # 4. Could not resolve; keep firm_id null rather than crash.
    logger.warning("audit firm_id unresolved for user_id=%s role=%s", uid, role or "?")
    return None


def client_display_label(db: Client, client_gstin_id: str) -> str:
    """Human-readable client name for audit entity_label."""
    try:
        r = (
            db.table("client_gstins")
            .select("trade_name, legal_name, gstin")
            .eq("id", client_gstin_id)
            .limit(1)
            .execute()
        )
        if r.data:
            row = r.data[0]
            return (
                str(row.get("trade_name") or "").strip()
                or str(row.get("legal_name") or "").strip()
                or str(row.get("gstin") or "").strip()
                or "Client"
            )
    except Exception:
        pass
    return "Client"


def actor_user_for_run(db: Client, run_id: str) -> Optional[dict[str, Any]]:
    """Best-effort actor profile for background jobs (import wizard created_by)."""
    try:
        from app.repositories.wizard import get_wizard_repository
        w_repo = get_wizard_repository()
        uid = ""
        if w_repo is not None:
            r = w_repo.get_run(run_id)
            if r and r.get("created_by"):
                uid = str(r["created_by"]).strip()

        if not uid:
            imp = (
                db.table("reconciliation_import_runs")
                .select("created_by")
                .eq("id", run_id)
                .limit(1)
                .execute()
            )
            if imp.data:
                uid = str(imp.data[0].get("created_by") or "").strip()
        if not uid:
            run = (
                db.table("reconciliation_run")
                .select("finalized_by")
                .eq("id", run_id)
                .limit(1)
                .execute()
            )
            if run.data:
                uid = str(run.data[0].get("finalized_by") or "").strip()
        if not uid:
            return None
        prof = get_user_profile(uid) or {}
        actor = {**prof, "id": uid}
        actor["firm_id"] = resolve_firm_id(db, actor)
        return actor
    except Exception:
        return None


async def log_audit(
    db: Client,
    user: Mapping[str, Any] | dict,
    action: str,
    entity_type: str,
    entity_id: Optional[str],
    entity_label: Optional[str] = None,
    metadata: Optional[Mapping[str, Any] | dict] = None,
    *,
    ip_address: Optional[str] = None,
) -> None:
    """Insert one row into *audit_logs*. Safe to call from any layer; never raises."""
    try:
        uid = str(user.get("id", "") or "").strip() or None
        full_name = str(user.get("full_name") or "").strip()
        email = str(user.get("email") or "").strip()
        role = str(user.get("role") or "").strip().lower()

        # Enrich from the profile when the caller passed a thin user context
        # (e.g. the log_action wrappers), so user_name/role are never silently null.
        if uid and (not full_name or not role or not email):
            prof = get_user_profile(uid) or {}
            full_name = full_name or str(prof.get("full_name") or "").strip()
            email = email or str(prof.get("email") or "").strip()
            if not role:
                role = str(prof.get("role") or "").strip().lower()

        if uid and not role:
            try:
                role = resolve_user_role(
                    None,
                    user_id=uid,
                    email=email or None,
                    client=db,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("audit role resolution failed for user_id=%s: %s", uid, exc)
                role = ""

        # 1. user_name → full_name, else email, else Unknown
        user_name = full_name or email or "Unknown"
        # 2/3. role + firm_id resolved from the enriched context
        enriched_user = {**user, "role": role, "email": email or user.get("email")}
        firm_id = resolve_firm_id(db, enriched_user)

        base = _mask_metadata(dict(metadata or {}))
        meta_obj = _redact_gstin_in_strings(base)
        if isinstance(meta_obj, dict):
            try:
                json.dumps(meta_obj)
            except (TypeError, ValueError):
                meta_obj = {"_note": "metadata_not_serializable"}

        row: dict[str, Any] = {
            "firm_id": firm_id,
            "user_id": uid,
            "user_name": user_name,
            "role": role or None,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_label": entity_label,
            "metadata": meta_obj,
            "ip_address": _client_ip_for_insert(ip_address),
            "correlation_id": get_correlation_id(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        db.table("audit_logs").insert(row).execute()
    except Exception as exc:  # noqa: BLE001
        print(  # noqa: T201
            f"audit log insert failed action={action}: {exc}", file=sys.stderr
        )


def log_audit_sync(
    db: Client,
    user: Mapping[str, Any] | dict,
    action: str,
    entity_type: str,
    entity_id: Optional[str],
    entity_label: Optional[str] = None,
    metadata: Optional[Mapping[str, Any] | dict] = None,
    *,
    ip_address: Optional[str] = None,
) -> None:
    """Schedule :func:`log_audit` from synchronous code (best-effort)."""
    import asyncio

    coro = log_audit(
        db,
        user,
        action,
        entity_type,
        entity_id,
        entity_label,
        metadata,
        ip_address=ip_address,
    )

    try:
        asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        try:
            asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            print(f"audit sync log failed: {exc}", file=sys.stderr)  # noqa: T201


async def log_action(
    user_id: Optional[str],
    action: str,
    entity_type: str,
    entity_id: Optional[str],
    metadata: Optional[Mapping[str, Any] | dict] = None,
    *,
    ip_address: Optional[str] = None,
    entity_label: Optional[str] = None,
) -> None:
    """Backward-compatible wrapper around :func:`log_audit`."""
    user: dict[str, Any] = {"id": user_id}
    if user_id:
        prof = get_user_profile(user_id)
        if prof:
            user = {**prof, "id": user_id}
    try:
        sb = get_supabase()
    except Exception as exc:
        logger.warning("Supabase client unavailable for audit logging action=%s: %s", action, exc)
        return
    await log_audit(
        sb,
        user,
        action,
        entity_type,
        entity_id,
        entity_label,
        metadata,
        ip_address=ip_address,
    )


def log_action_sync(
    user_id: Optional[str],
    action: str,
    entity_type: str,
    entity_id: Optional[str],
    metadata: Optional[Mapping[str, Any] | dict] = None,
    *,
    ip_address: Optional[str] = None,
    entity_label: Optional[str] = None,
) -> None:
    """Backward-compatible sync wrapper around :func:`log_audit`."""
    user: dict[str, Any] = {"id": user_id}
    if user_id:
        prof = get_user_profile(user_id)
        if prof:
            user = {**prof, "id": user_id}
    try:
        sb = get_supabase()
    except Exception as exc:
        logger.warning("Supabase client unavailable for sync audit logging action=%s: %s", action, exc)
        return
    log_audit_sync(
        sb,
        user,
        action,
        entity_type,
        entity_id,
        entity_label,
        metadata,
        ip_address=ip_address,
    )
