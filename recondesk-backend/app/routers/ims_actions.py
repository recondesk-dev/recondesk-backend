"""IMS Action panel API — recommendations + confirmed writeback + poll.

GET  /api/reconcile/runs/{run_id}/ims/recommendations
POST /api/reconcile/runs/{run_id}/ims/actions/confirm
GET  /api/reconcile/runs/{run_id}/ims/actions/status

Recommendations never auto-load on the client; confirm never fires without
an explicit CA confirmation body. Phase 4 (post-action 2B sync) is flagged
on the confirm response but not executed here.
"""

from __future__ import annotations

import io
import json
import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth import get_current_active_user
from app.database import get_supabase, get_user_profile
from app.utils.audit import client_display_label, log_audit
from app.ims.ims_offline_export import (
    build_ims_offline_json,
    build_ims_workpaper_excel,
    format_gstn_period,
)
from app.ims.ims_run_service import build_recommendations_for_run
from app.ims.ims_action_store import ImsClaimRpcError, SupabaseImsActionStore
from app.ims.ims_writeback_client import (
    ConfirmedInvoiceAction,
    confirm_ims_actions,
    poll_ims_writeback,
)
from app.services.firm_access import assert_run_accessible
from app.services.gst_fetch.token import ensure_fresh_gstn_token, load_client_gstin
from app.services.sandbox_gst_client import SandboxClientError
from app.services.ims_sync_service import sync_ims_run_overlay
from app.integrations.gstn_error_mapper import gstn_http_exception

_log = logging.getLogger(__name__)

router = APIRouter(redirect_slashes=False)

CaAction = Literal["accept", "reject", "hold"]


class ConfirmInvoiceItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    invoice_id: str
    chosen_action: CaAction
    recommended_action: Optional[str] = None
    section: str = "b2b"
    writeback_payload: Optional[dict[str, Any]] = None
    remarks: Optional[str] = None

    @field_validator("invoice_id", "section")
    @classmethod
    def strip_non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class ConfirmImsActionsRequest(BaseModel):
    """Explicit confirm payload — never inferred from selection alone."""

    model_config = ConfigDict(extra="ignore")

    confirmed: bool = Field(
        ...,
        description="Must be true; server rejects silent/implicit submits.",
    )
    confirmation_summary: str = Field(
        ...,
        description='e.g. "Accepting 47 invoices" — must match count semantics.',
    )
    expected_count: int = Field(..., ge=1)
    invoices: list[ConfirmInvoiceItem]

    @field_validator("confirmation_summary")
    @classmethod
    def strip_summary(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("confirmation_summary is required")
        return v


def _client_row_for_run(sb, run_row: dict[str, Any]) -> dict[str, Any]:
    cgid = str(run_row.get("client_gstin_id") or "").strip()
    if not cgid:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run has no client_gstin_id — cannot load IMS session",
        )
    return load_client_gstin(sb, cgid)


@router.get("/runs/{run_id}/ims/recommendations")
async def get_ims_recommendations(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Load recommendations. Caller must invoke explicitly (never on page open)."""
    sb = get_supabase()
    run_row = assert_run_accessible(sb, run_id, current_user)

    access_token: str | None = None
    buyer_gstin: str | None = None
    try:
        client_row = _client_row_for_run(sb, run_row)
        buyer_gstin = str(client_row.get("gstin") or "").strip() or None
        if client_row.get("gstn_access_token"):
            try:
                access_token = ensure_fresh_gstn_token(sb, client_row)
            except HTTPException:
                # Recommendations can still use stored overlay without live IMS.
                access_token = None
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            pass
        else:
            # Missing client is soft for recommendations — still try payload-only.
            _log.info("IMS recommendations without client session: %s", exc.detail)

    batch = build_recommendations_for_run(
        sb,
        run_id=str(run_row.get("id") or run_id),
        run_row=run_row,
        access_token=access_token,
        buyer_gstin=buyer_gstin,
    )
    return batch.as_dict()


@router.post("/runs/{run_id}/ims/actions/confirm")
async def confirm_ims_actions_route(
    run_id: str,
    body: ConfirmImsActionsRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Write confirmed Accept/Reject/Hold actions to GSTN.

    Requires ``confirmed=true``, matching ``expected_count``, and a
    human-readable ``confirmation_summary``. Overrides are logged distinctly.
    """
    if not body.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="confirmed must be true — IMS writeback refuses implicit submits",
        )
    if len(body.invoices) != body.expected_count:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"expected_count ({body.expected_count}) does not match "
                f"invoices length ({len(body.invoices)})"
            ),
        )
    # Count must appear in the summary string (friction against vague Confirm).
    count_token = str(body.expected_count)
    if count_token not in body.confirmation_summary:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "confirmation_summary must include the invoice count "
                f'(e.g. "Accepting {body.expected_count} invoices")'
            ),
        )

    sb = get_supabase()
    run_row = assert_run_accessible(sb, run_id, current_user)
    client_row = _client_row_for_run(sb, run_row)
    try:
        access_token = ensure_fresh_gstn_token(sb, client_row)
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="GSTN not connected for this client; complete OTP verification first",
        )
    buyer_gstin = str(client_row.get("gstin") or "").strip()
    if not buyer_gstin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client has no GSTIN on file",
        )

    actions = [
        ConfirmedInvoiceAction(
            invoice_id=item.invoice_id,
            chosen_action=item.chosen_action,
            recommended_action=item.recommended_action,
            section=item.section,
            writeback_payload=item.writeback_payload,
            remarks=item.remarks,
        )
        for item in body.invoices
    ]

    _log.info(
        "IMS confirm requested run_id=%s user=%s count=%d summary=%r overrides=%d",
        run_id,
        current_user.get("id"),
        len(actions),
        body.confirmation_summary,
        sum(1 for a in actions if a.overridden),
    )

    period = str(run_row.get("period") or "").strip()
    if not period:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run has no period — cannot idempotently record IMS actions",
        )

    try:
        result = confirm_ims_actions(
            access_token=access_token,
            buyer_gstin=buyer_gstin,
            period=period,
            actions=actions,
            store=SupabaseImsActionStore(sb),
            run_id=str(run_row.get("id") or run_id),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except ImsClaimRpcError as exc:
        # Distinct from lost-race skip — CA must see a real failure and retry.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except SandboxClientError as exc:
        raise gstn_http_exception(exc, context="IMS action confirm") from exc

    payload = result.as_dict()
    payload["run_id"] = str(run_row.get("id") or run_id)
    payload["confirmation_summary"] = body.confirmation_summary
    # Phase 4 hook: after poll confirms GSTN success, trigger post-action
    # GSTR-2B / IMS overlay sync via POST /runs/{run_id}/ims/sync.
    payload["phase4_note"] = (
        "Action writeback registered. Trigger post-action sync via /runs/{run_id}/ims/sync "
        "(phase4_post_action_2b_sync_pending=true)."
    )
    return payload


@router.get("/runs/{run_id}/ims/actions/status")
async def get_ims_action_status(
    run_id: str,
    reference_id: str = Query(..., min_length=1),
    current_user: dict = Depends(get_current_active_user),
):
    """Poll dual-status result. Do not mark success until outcome=confirmed."""
    sb = get_supabase()
    run_row = assert_run_accessible(sb, run_id, current_user)
    client_row = _client_row_for_run(sb, run_row)
    try:
        access_token = ensure_fresh_gstn_token(sb, client_row)
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="GSTN not connected for this client; complete OTP verification first",
        )

    try:
        result = poll_ims_writeback(
            access_token=access_token,
            reference_id=reference_id.strip(),
        )
    except SandboxClientError as exc:
        raise gstn_http_exception(exc, context="IMS action status poll") from exc

    payload = result.as_dict()
    payload["run_id"] = str(run_row.get("id") or run_id)
    return payload


@router.post("/runs/{run_id}/ims/sync")
async def sync_ims_run_route(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Synchronize stored GSTR-2B records and reconciliation results with updated IMS status.

    Executed post-writeback or on-demand by the CA to reflect latest GSTN portal decisions.
    """
    sb = get_supabase()
    run_row = assert_run_accessible(sb, run_id, current_user)

    access_token: str | None = None
    buyer_gstin: str | None = None
    try:
        client_row = _client_row_for_run(sb, run_row)
        buyer_gstin = str(client_row.get("gstin") or "").strip() or None
        if client_row.get("gstn_access_token"):
            try:
                access_token = ensure_fresh_gstn_token(sb, client_row)
            except HTTPException:
                access_token = None
    except HTTPException:
        pass

    try:
        result = sync_ims_run_overlay(
            sb,
            run_id=str(run_row.get("id") or run_id),
            access_token=access_token,
            buyer_gstin=buyer_gstin,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        _log.error("IMS sync failed for run_id=%s: %s", run_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"IMS sync failed: {exc}",
        ) from exc

    return result.as_dict()


class ImsExportRequest(BaseModel):
    """Optional override payload for offline JSON or Excel export."""

    model_config = ConfigDict(extra="ignore")
    invoices: Optional[list[ConfirmInvoiceItem]] = None


def _merge_export_items(
    batch_invoices: list[Any],
    overrides: Optional[list[ConfirmInvoiceItem]],
) -> list[dict[str, Any]]:
    override_map = {item.invoice_id: item for item in (overrides or [])}
    merged: list[dict[str, Any]] = []

    for inv in batch_invoices:
        d = inv.as_dict() if hasattr(inv, "as_dict") else dict(inv)
        inv_id = d.get("invoice_id")
        if inv_id and inv_id in override_map:
            ovr = override_map[inv_id]
            d["chosen_action"] = ovr.chosen_action
            if ovr.section:
                d["section"] = ovr.section
            if ovr.writeback_payload:
                d["writeback_payload"] = ovr.writeback_payload
        merged.append(d)

    batch_ids = {d.get("invoice_id") for d in merged}
    for item in (overrides or []):
        if item.invoice_id not in batch_ids:
            merged.append(
                {
                    "invoice_id": item.invoice_id,
                    "chosen_action": item.chosen_action,
                    "recommended_action": item.recommended_action or item.chosen_action,
                    "section": item.section,
                    "writeback_payload": item.writeback_payload,
                }
            )

    return merged


async def _handle_export_json(
    run_id: str,
    overrides: Optional[list[ConfirmInvoiceItem]],
    current_user: dict,
) -> StreamingResponse:
    sb = get_supabase()
    run_row = assert_run_accessible(sb, run_id, current_user)
    client_row = _client_row_for_run(sb, run_row)

    buyer_gstin = str(client_row.get("gstin") or "").strip()
    period = str(run_row.get("period") or "").strip()
    client_name = str(client_row.get("trade_name") or client_row.get("legal_name") or "Client").strip()

    access_token: str | None = None
    if client_row.get("gstn_access_token"):
        try:
            access_token = ensure_fresh_gstn_token(sb, client_row)
        except Exception:
            access_token = None

    batch = build_recommendations_for_run(
        sb,
        run_id=str(run_row.get("id") or run_id),
        run_row=run_row,
        access_token=access_token,
        buyer_gstin=buyer_gstin,
    )

    items = _merge_export_items(batch.invoices, overrides)
    json_data = build_ims_offline_json(buyer_gstin, period, items)
    json_str = json.dumps(json_data, indent=2)

    fp = format_gstn_period(period)
    filename = f"IMS_Offline_Actions_{buyer_gstin or 'CLIENT'}_{fp}.json"

    label = f"{client_name} ({period})" if period else client_name
    await log_audit(
        sb,
        current_user,
        "RESULT_EXPORTED",
        "ims",
        run_id,
        label,
        {"export_type": "ims_offline_json", "count": len(items)},
    )

    return StreamingResponse(
        io.BytesIO(json_str.encode("utf-8")),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _handle_export_excel(
    run_id: str,
    overrides: Optional[list[ConfirmInvoiceItem]],
    current_user: dict,
) -> StreamingResponse:
    sb = get_supabase()
    run_row = assert_run_accessible(sb, run_id, current_user)
    client_row = _client_row_for_run(sb, run_row)

    buyer_gstin = str(client_row.get("gstin") or "").strip()
    period = str(run_row.get("period") or "").strip()
    client_name = str(client_row.get("trade_name") or client_row.get("legal_name") or "Client").strip()

    uid = str(current_user.get("id") or "")
    prof = get_user_profile(uid) or {}
    firm_name = str(prof.get("firm_name") or "")
    gen_name = str(prof.get("full_name") or "")

    access_token: str | None = None
    if client_row.get("gstn_access_token"):
        try:
            access_token = ensure_fresh_gstn_token(sb, client_row)
        except Exception:
            access_token = None

    batch = build_recommendations_for_run(
        sb,
        run_id=str(run_row.get("id") or run_id),
        run_row=run_row,
        access_token=access_token,
        buyer_gstin=buyer_gstin,
    )

    items = _merge_export_items(batch.invoices, overrides)
    xlsx_bytes, filename = build_ims_workpaper_excel(
        buyer_gstin,
        period,
        items,
        client_name=client_name,
        firm_name=firm_name,
        generated_by=gen_name,
    )

    label = f"{client_name} ({period})" if period else client_name
    await log_audit(
        sb,
        current_user,
        "RESULT_EXPORTED",
        "ims",
        run_id,
        label,
        {"export_type": "ims_action_workpaper", "count": len(items)},
    )

    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/runs/{run_id}/ims/export/json")
async def export_ims_json_post(
    run_id: str,
    body: ImsExportRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Export GST Portal IMS Offline Utility compliant JSON file with current actions."""
    return await _handle_export_json(run_id, body.invoices, current_user)


@router.get("/runs/{run_id}/ims/export/json")
async def export_ims_json_get(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Export default GST Portal IMS Offline Utility compliant JSON file."""
    return await _handle_export_json(run_id, None, current_user)


@router.post("/runs/{run_id}/ims/export/excel")
async def export_ims_excel_post(
    run_id: str,
    body: ImsExportRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Export CA-Grade IMS Action Audit Workpaper (.xlsx) with current actions."""
    return await _handle_export_excel(run_id, body.invoices, current_user)


@router.get("/runs/{run_id}/ims/export/excel")
async def export_ims_excel_get(
    run_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Export default CA-Grade IMS Action Audit Workpaper (.xlsx)."""
    return await _handle_export_excel(run_id, None, current_user)

