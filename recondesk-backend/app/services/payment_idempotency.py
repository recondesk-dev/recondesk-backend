"""Idempotent Razorpay order creation using idempotency_keys table."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from supabase import Client

from app.database import get_supabase


def _table_ready(sb: Client) -> bool:
    try:
        sb.table("idempotency_keys").select("id").limit(0).execute()
    except Exception:
        return False
    return True


def lookup_idempotent_response(
    idempotency_key: str, user_id: str
) -> Optional[dict[str, Any]]:
    if not (idempotency_key or "").strip():
        return None
    sb = get_supabase()
    if not _table_ready(sb):
        return None
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    r = (
        sb.table("idempotency_keys")
        .select("response, created_at")
        .eq("idempotency_key", idempotency_key.strip()[:300])
        .eq("user_id", user_id)
        .gte("created_at", since)
        .limit(1)
        .execute()
    )
    if not r.data:
        return None
    row = r.data[0]
    resp = row.get("response")
    if isinstance(resp, dict):
        return dict(resp)
    if isinstance(resp, str):
        try:
            return json.loads(resp)
        except json.JSONDecodeError:
            return None
    return None


def store_idempotent_response(
    idempotency_key: str, user_id: str, response_obj: dict[str, Any]
) -> None:
    sb = get_supabase()
    if not _table_ready(sb):
        return
    row = {
        "idempotency_key": idempotency_key.strip()[:300],
        "user_id": user_id,
        "response": response_obj,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        sb.table("idempotency_keys").insert(row).execute()
    except Exception:
        pass
