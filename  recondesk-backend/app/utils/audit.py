"""Insert-only audit log rows; never raise to callers on failure."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from supabase import Client

from app.database import get_supabase, get_user_profile, resolve_user_role
from app.utils.context import get_correlation_id

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


def resolve_firm_id(db: Client, user: Mapping[str, Any] | dict) -> Optional[str]:
    """Return workspace owner id (firm anchor) for the acting user."""
    uid = str(user.get("id", "") or "").strip()
    if not uid:
        return None
    role = str(user.get("role") or "").strip().lower()
    if not role:
        role = resolve_user_role(
            user.get("role"),
            user_id=uid,
            email=user.get("email"),
            client=db,
        )
    if role == "admin":
        return uid
    try:
        tm = (
            db.table("team_members")
            .select("firm_owner_id")
            .eq("member_user_id", uid)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if tm.data and tm.data[0].get("firm_owner_id"):
            return str(tm.data[0]["firm_owner_id"])
        cg = (
            db.table("client_gstins")
            .select("firm_owner_id")
            .eq("assigned_to", uid)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if cg.data and cg.data[0].get("firm_owner_id"):
            return str(cg.data[0]["firm_owner_id"])
    except Exception:
        pass
    return uid


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
        imp = (
            db.table("reconciliation_import_runs")
            .select("created_by")
            .eq("id", run_id)
            .limit(1)
            .execute()
        )
        uid = ""
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
        return {**prof, "id": uid}
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
        role = str(user.get("role") or "").strip().lower()
        if uid and not role:
            role = resolve_user_role(
                user.get("role"),
                user_id=uid,
                email=user.get("email"),
                client=db,
            )
        user_name = str(user.get("full_name") or user.get("email") or "Unknown").strip()
        firm_id = str(user.get("firm_id") or "").strip() or resolve_firm_id(db, user)

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
    await log_audit(
        get_supabase(),
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
    log_audit_sync(
        get_supabase(),
        user,
        action,
        entity_type,
        entity_id,
        entity_label,
        metadata,
        ip_address=ip_address,
    )
