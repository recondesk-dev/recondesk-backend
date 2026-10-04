"""Idempotent Razorpay order creation using idempotency_keys table (Aurora Primary)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from supabase import Client

from app.database import get_supabase
from app.repositories.payments_credits import get_payments_credits_repository

_log = logging.getLogger("recondesk.payment_idempotency")


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

    # 1. Aurora PostgreSQL Primary
    try:
        repo = get_payments_credits_repository()
        since_dt = datetime.now(timezone.utc) - timedelta(hours=24)
        rec = repo.get_idempotency_response(
            idempotency_key=idempotency_key.strip()[:300],
            user_id=user_id,
            since=since_dt,
        )
        if rec and rec.get("response"):
            resp = rec["response"]
            if isinstance(resp, dict):
                return dict(resp)
            if isinstance(resp, str):
                try:
                    return json.loads(resp)
                except json.JSONDecodeError:
                    return None
            return None
    except Exception as exc:
        _log.warning("Aurora lookup_idempotent_response failed, trying Supabase fallback: %s", exc)

    # 2. Supabase Fallback (Temporary non-blocking)
    try:
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
    except Exception as exc:
        _log.warning("Supabase fallback lookup_idempotent_response failed: %s", exc)

    return None


def store_idempotent_response(
    idempotency_key: str, user_id: str, response_obj: dict[str, Any]
) -> None:
    if not (idempotency_key or "").strip():
        return

    # 1. Aurora PostgreSQL Primary
    try:
        repo = get_payments_credits_repository()
        repo.save_idempotency_response(
            idempotency_key=idempotency_key.strip()[:300],
            user_id=user_id,
            response=response_obj,
        )
        return
    except Exception as exc:
        _log.warning("Aurora store_idempotent_response failed, trying Supabase fallback: %s", exc)

    # 2. Supabase Fallback (Temporary non-blocking)
    try:
        sb = get_supabase()
        if not _table_ready(sb):
            return
        row = {
            "idempotency_key": idempotency_key.strip()[:300],
            "user_id": user_id,
            "response": response_obj,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        sb.table("idempotency_keys").insert(row).execute()
    except Exception as exc:
        _log.warning("Supabase fallback store_idempotent_response failed: %s", exc)
