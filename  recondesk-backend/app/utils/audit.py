"""Insert audit log rows; never raise to callers on failure."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from app.database import get_supabase
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


def log_action_sync(
    user_id: Optional[str],
    action: str,
    entity_type: str,
    entity_id: Optional[str],
    metadata: Optional[Mapping[str, Any] | dict] = None,
    *,
    ip_address: Optional[str] = None,
) -> None:
    """Schedule :func:`log_action` from synchronous code (best-effort)."""
    import asyncio

    coro = log_action(
        user_id,
        action,
        entity_type,
        entity_id,
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
) -> None:
    """Insert one row into *audit_logs*. Safe to call from any layer; never raises."""
    try:
        base = _mask_metadata(dict(metadata or {}))
        meta_obj = _redact_gstin_in_strings(base)
        if isinstance(meta_obj, dict):
            try:
                json.dumps(meta_obj)
            except (TypeError, ValueError):
                meta_obj = {"_note": "metadata_not_serializable"}
        row: dict[str, Any] = {
            "user_id": user_id,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "metadata": meta_obj,
            "ip_address": _client_ip_for_insert(ip_address),
            "correlation_id": get_correlation_id(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        client = get_supabase()
        client.table("audit_logs").insert(row).execute()
    except Exception as exc:  # noqa: BLE001
        print(  # noqa: T201
            f"audit log insert failed action={action}: {exc}", file=sys.stderr
        )
