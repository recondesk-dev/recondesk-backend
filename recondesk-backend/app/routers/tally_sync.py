"""Tally Bridge sync API: `/api/tally-sync`.

Local agent authenticates with a firm-scoped API key (``tally_bridge_keys``).
Dashboard endpoints use the normal Supabase JWT via ``get_current_active_user``.

POST /outstanding accepts:
  - ``outstanding``: Bills Payable rows (pending due) — unpaid truth only
  - ``payments``: Payment Agst Ref allocations — only settle path
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.auth import get_current_active_user
from app.database import get_supabase
from app.services.tally_bridge_sync import (
    apply_tally_bridge_sync,
    generate_tally_bridge_api_key,
)
from app.utils.audit import resolve_firm_id

router = APIRouter()
_log = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)

_AGENT_PATH = (
    Path(__file__).resolve().parents[2] / "tally_bridge" / "tally_bridge_agent.py"
)
_CONFIG_EXAMPLE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tally_bridge"
    / "tally_bridge.config.example.json"
)


class TallyOutstandingRow(BaseModel):
    party: str = ""
    bill_ref: str = Field(..., min_length=1)
    bill_date: Optional[str] = None
    amount: Optional[float] = None  # remaining due (pending), never amount paid


class TallyPaymentRow(BaseModel):
    party: str = ""
    bill_ref: str = Field(..., min_length=1)
    amount: Optional[float] = None  # Agst Ref allocation = amount paid
    payment_date: Optional[str] = None
    voucher_number: str = ""
    voucher_type: str = ""


class TallyBridgeSyncBody(BaseModel):
    company_name: str = ""
    synced_at: Optional[str] = None
    outstanding: list[TallyOutstandingRow] = Field(default_factory=list)
    payments: list[TallyPaymentRow] = Field(default_factory=list)


class TallyKeyCreateBody(BaseModel):
    company_name: str = Field(default="", max_length=200)


def _account_id_for_user(user: dict) -> str:
    firm_id = str(user.get("firm_id") or "").strip()
    if firm_id:
        return firm_id
    resolved = resolve_firm_id(get_supabase(), user)
    if resolved:
        return resolved
    uid = str(user.get("id") or "").strip()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing user id",
        )
    return uid


def _lookup_bridge_key(api_key: str) -> dict[str, Any]:
    sb = get_supabase()
    try:
        res = (
            sb.table("tally_bridge_keys")
            .select("id, api_key, account_id, company_name, last_synced_at, revoked_at")
            .eq("api_key", api_key)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        _log.exception("tally_bridge_keys lookup failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="tally bridge key lookup failed",
        ) from exc
    rows = res.data or []
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid api key",
        )
    row = rows[0]
    if row.get("revoked_at"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="api key revoked",
        )
    return row


async def require_tally_bridge_key(
    creds: Optional[HTTPAuthorizationCredentials] = Security(_bearer),
) -> dict[str, Any]:
    if creds is None or not str(creds.credentials or "").strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer api key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _lookup_bridge_key(str(creds.credentials).strip())


@router.post("/outstanding")
async def tally_sync_outstanding(
    body: TallyBridgeSyncBody,
    key_row: dict[str, Any] = Depends(require_tally_bridge_key),
):
    """Receive Bills Payable + Payment Agst Ref rows; settle only from payments."""
    account_id = str(key_row.get("account_id") or "").strip()
    if not account_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="api key missing account_id",
        )
    company = (body.company_name or key_row.get("company_name") or "").strip()
    outstanding = [r.model_dump() for r in body.outstanding]
    payments = [r.model_dump() for r in body.payments]
    sb = get_supabase()
    try:
        result = apply_tally_bridge_sync(
            sb,
            account_id=account_id,
            outstanding=outstanding,
            payments=payments,
            company_name=company or str(key_row.get("company_name") or ""),
            key_id=str(key_row.get("id") or "") or None,
        )
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("tally bridge sync failed account_id=%s", account_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="tally sync failed",
        ) from exc
    return {"ok": True, **result}


@router.get("/status")
async def tally_bridge_status(
    current_user: dict = Depends(get_current_active_user),
):
    """Dashboard: last sync + whether a key exists for this firm."""
    account_id = _account_id_for_user(current_user)
    sb = get_supabase()
    try:
        res = (
            sb.table("tally_bridge_keys")
            .select("id, company_name, last_synced_at, created_at, revoked_at")
            .eq("account_id", account_id)
            .is_("revoked_at", "null")
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )
    except Exception as exc:
        _log.exception("tally_bridge status failed account_id=%s", account_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed to load tally bridge status",
        ) from exc
    rows = res.data or []
    latest = rows[0] if rows else None
    return {
        "account_id": account_id,
        "has_key": bool(rows),
        "keys": [
            {
                "id": r.get("id"),
                "company_name": r.get("company_name") or "",
                "last_synced_at": r.get("last_synced_at"),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ],
        "last_synced_at": (latest or {}).get("last_synced_at"),
    }


@router.post("/keys")
async def tally_bridge_create_key(
    body: TallyKeyCreateBody,
    current_user: dict = Depends(get_current_active_user),
):
    """Generate a new Tally Bridge API key for the current firm account."""
    account_id = _account_id_for_user(current_user)
    api_key = generate_tally_bridge_api_key()
    company_name = (body.company_name or "").strip()
    payload = {
        "api_key": api_key,
        "account_id": account_id,
        "company_name": company_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    sb = get_supabase()
    try:
        res = sb.table("tally_bridge_keys").insert(payload).execute()
    except Exception as exc:
        _log.exception("tally_bridge_keys insert failed account_id=%s", account_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed to create api key",
        ) from exc
    row = (res.data or [payload])[0]
    return {
        "id": row.get("id"),
        "api_key": api_key,
        "account_id": account_id,
        "company_name": company_name,
        "created_at": row.get("created_at") or payload["created_at"],
        "last_synced_at": None,
    }


@router.get("/agent")
async def tally_bridge_download_agent(
    current_user: dict = Depends(get_current_active_user),
):
    """Download the local agent script (auth required)."""
    _ = current_user  # auth gate
    if not _AGENT_PATH.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="agent script not found on server",
        )
    return FileResponse(
        path=str(_AGENT_PATH),
        filename="tally_bridge_agent.py",
        media_type="text/x-python",
    )


@router.get("/agent-config-example")
async def tally_bridge_download_config_example(
    current_user: dict = Depends(get_current_active_user),
):
    _ = current_user
    if not _CONFIG_EXAMPLE_PATH.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="config example not found on server",
        )
    return FileResponse(
        path=str(_CONFIG_EXAMPLE_PATH),
        filename="tally_bridge.config.example.json",
        media_type="application/json",
    )
