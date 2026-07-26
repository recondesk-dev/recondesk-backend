"""First-login product tour + demo client endpoints: ``/api/onboarding``."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.auth import get_current_active_user
from app.database import get_supabase
from app.services.demo_seed import ensure_demo_client_for_user, get_demo_status

router = APIRouter(redirect_slashes=False)
_log = logging.getLogger(__name__)


class DemoEnsureResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client_id: str
    run_id: str | None = None
    created: bool = False
    trade_name: str | None = None
    period: str | None = None
    scenarios: dict[str, str] | None = None


class FirstLoginCompleteResponse(BaseModel):
    success: bool = True
    is_first_login: bool = False


def _seed_demo_safe(user_id: str) -> None:
    try:
        ensure_demo_client_for_user(user_id)
    except Exception:  # noqa: BLE001
        _log.exception("background demo seed failed for user=%s", user_id)


@router.post("/ensure-demo", response_model=DemoEnsureResponse)
async def ensure_demo(
    current_user: dict = Depends(get_current_active_user),
):
    """Idempotently create the demo client + pre-reconciled sample run."""
    uid = str(current_user.get("id", "")).strip()
    if not uid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    try:
        result = ensure_demo_client_for_user(uid)
    except Exception as exc:  # noqa: BLE001
        _log.exception("ensure_demo failed for user=%s", uid)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to prepare demo client: {exc}",
        ) from exc

    client = result.get("client") or {}
    run = result.get("run") or {}
    return DemoEnsureResponse(
        client_id=str(result["client_id"]),
        run_id=str(result["run_id"]) if result.get("run_id") else None,
        created=bool(result.get("created")),
        trade_name=str(client.get("trade_name") or "") or None,
        period=str(run.get("period") or "") or None,
        scenarios=result.get("scenarios"),
    )


@router.patch("/first-login-complete", response_model=FirstLoginCompleteResponse)
async def first_login_complete(
    current_user: dict = Depends(get_current_active_user),
):
    """Mark the product tour as done (``is_first_login = false``)."""
    uid = str(current_user.get("id", "")).strip()
    if not uid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    sb = get_supabase()
    try:
        sb.table("user_profiles").update({"is_first_login": False}).eq("id", uid).execute()
    except Exception as exc:  # noqa: BLE001
        _log.exception("first_login_complete update failed for %s", uid)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile",
        ) from exc
    return FirstLoginCompleteResponse(success=True, is_first_login=False)


@router.get("/demo-status", response_model=DemoEnsureResponse)
async def demo_status(
    current_user: dict = Depends(get_current_active_user),
):
    """Return existing demo client/run without creating one."""
    uid = str(current_user.get("id", "")).strip()
    result = get_demo_status(uid)
    if not result:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No demo client yet")
    client = result.get("client") or {}
    run = result.get("run") or {}
    return DemoEnsureResponse(
        client_id=str(result["client_id"]),
        run_id=str(result["run_id"]) if result.get("run_id") else None,
        created=False,
        trade_name=str(client.get("trade_name") or "") or None,
        period=str(run.get("period") or "") or None,
        scenarios=result.get("scenarios"),
    )


def schedule_demo_seed(background_tasks: BackgroundTasks, user_id: str) -> None:
    """Fire-and-forget demo seed (signup / onboarding-complete hooks)."""
    background_tasks.add_task(_seed_demo_safe, user_id)
