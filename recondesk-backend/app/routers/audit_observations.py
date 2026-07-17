"""Audit observations API — aggregated rule violations for a reconciliation run."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.audit.observation_builder import build_observations
from app.auth import get_current_active_user
from app.database import get_supabase
from app.services.firm_access import (
    assert_run_accessible,
    list_accessible_client_gstin_ids,
)
from app.services.gstr1_run_store import get_gstr1_run

router = APIRouter(redirect_slashes=False)


def _assert_client_accessible(client_gstin_id: str, current_user: dict) -> None:
    sb = get_supabase()
    allowed = list_accessible_client_gstin_ids(sb, current_user)
    if str(client_gstin_id).strip() not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not allowed for this client",
        )


@router.get(
    "/{run_id}",
    summary="Get audit observations for a reconciliation run",
)
async def get_audit_observations(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Return severity-ranked observations with financial impact for *run_id*.

    Supports both GSTR-1 runs (``gstr1_reconciliation_run``) and purchase runs
    (``reconciliation_results``). Read-only — does not re-run matching.
    """
    rid = str(run_id).strip()
    if not rid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    sb = get_supabase()
    g1_row = get_gstr1_run(sb, rid)
    if g1_row is not None:
        _assert_client_accessible(str(g1_row.get("client_gstin_id", "")), current_user)
    else:
        # Purchase path: assert access (403 if missing/out of scope), then build.
        assert_run_accessible(sb, rid, current_user)

    result = build_observations(rid, sb=sb)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No reconciliation results found for this run",
        )
    return result
