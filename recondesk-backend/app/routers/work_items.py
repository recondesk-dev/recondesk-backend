"""ITC Work Items REST Router.

Exposes endpoints for the Phase 5.2 Exception Work Item Lifecycle Engine:
- Listing and filtering work items
- Status transitions with centralized lifecycle validation
- Staff assignments and reassignments
- Priority override with audit rationale
- Target due dates and SLA tracking
- Operational notes and timeline retrieval
- Structured resolution with maker-checker verification
- Reopening and revalidation hooks
- Bulk actions with per-item status reporting
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth import get_current_active_user
from app.database import get_supabase
from app.services.firm_access import list_accessible_client_gstin_ids
from app.services import itc_work_item_service as wis

_log = logging.getLogger(__name__)

router = APIRouter(tags=["ITC Work Items"])


# Request Models
class StatusTransitionRequest(BaseModel):
    status: str
    note: Optional[str] = None


class AssignmentRequest(BaseModel):
    assigned_to: Optional[str] = None


class PriorityOverrideRequest(BaseModel):
    priority: str
    reason: str


class DueDateRequest(BaseModel):
    due_at: Optional[str] = None


class NoteRequest(BaseModel):
    note: str


class ResolutionRequest(BaseModel):
    resolution_code: str
    resolution_note: str


class DismissRequest(BaseModel):
    reason: str


class ReopenRequest(BaseModel):
    reason: str


class BulkActionRequest(BaseModel):
    action: str  # 'assign' | 'status' | 'priority' | 'due_date'
    work_item_ids: List[str]
    payload: dict[str, Any] = Field(default_factory=dict)


class VendorResponseRequest(BaseModel):
    response_category: str
    contact_channel: Optional[str] = "PHONE"
    contact_person: Optional[str] = None
    promised_date: Optional[str] = None
    notes: Optional[str] = None
    evidence_storage_key: Optional[str] = None
    evidence_filename: Optional[str] = None
    target_status: Optional[str] = None


class ScheduleFollowupRequest(BaseModel):
    due_at: Optional[str] = None
    note: Optional[str] = None


def _parse_uuid(val: str, field_name: str) -> str:
    try:
        return str(UUID(str(val).strip()))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID for {field_name}: {val}",
        )


@router.get("/clients/{client_id}/work-items")
async def list_client_work_items(
    client_id: str,
    period: Optional[str] = None,
    run_id: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[str] = None,
    sla_status: Optional[str] = None,
    exception_type: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_active_user),
):
    """Retrieve filtered and paginated work items for a client."""
    cid = _parse_uuid(client_id, "client_id")
    sb = get_supabase()
    allowed = list_accessible_client_gstin_ids(sb, current_user)
    if cid not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not allowed for this client",
        )

    return wis.list_work_items(
        sb,
        cid,
        period=period,
        run_id=run_id,
        status_filter=status,
        priority_filter=priority,
        assigned_to_filter=assigned_to,
        sla_filter=sla_status,
        exception_type_filter=exception_type,
        search=search,
        page=page,
        page_size=page_size,
        current_user=current_user,
    )


@router.post("/clients/{client_id}/work-items/sync")
async def sync_client_run_work_items(
    client_id: str,
    run_id: str = Query(...),
    current_user: dict = Depends(get_current_active_user),
):
    """Explicitly synchronize exceptions from a reconciliation run into itc_work_items."""
    cid = _parse_uuid(client_id, "client_id")
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    allowed = list_accessible_client_gstin_ids(sb, current_user)
    if cid not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not allowed for this client",
        )

    uid = str(current_user.get("id", ""))
    return wis.sync_work_items_for_run(sb, cid, rid, user_id=uid)


@router.get("/work-items/{work_item_id}")
async def get_work_item_details(
    work_item_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Retrieve full work item details including immutable audit timeline."""
    wid = _parse_uuid(work_item_id, "work_item_id")
    sb = get_supabase()
    return wis.get_work_item(sb, wid, current_user)


@router.post("/work-items/{work_item_id}/status")
async def update_work_item_status(
    work_item_id: str,
    body: StatusTransitionRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Transition work item operational lifecycle status."""
    wid = _parse_uuid(work_item_id, "work_item_id")
    sb = get_supabase()
    return wis.transition_work_item_status(
        sb,
        wid,
        body.status,
        current_user,
        note=body.note,
    )


@router.post("/work-items/{work_item_id}/assign")
async def assign_work_item_owner(
    work_item_id: str,
    body: AssignmentRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Assign or reassign an exception work item."""
    wid = _parse_uuid(work_item_id, "work_item_id")
    sb = get_supabase()
    return wis.assign_work_item(
        sb,
        wid,
        body.assigned_to,
        current_user,
    )


@router.post("/work-items/{work_item_id}/priority")
async def override_work_item_priority(
    work_item_id: str,
    body: PriorityOverrideRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Manually override priority with required CA justification."""
    wid = _parse_uuid(work_item_id, "work_item_id")
    sb = get_supabase()
    return wis.override_work_item_priority(
        sb,
        wid,
        body.priority,
        body.reason,
        current_user,
    )


@router.post("/work-items/{work_item_id}/due-date")
async def set_work_item_target_due_date(
    work_item_id: str,
    body: DueDateRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Set or remove target completion due date."""
    wid = _parse_uuid(work_item_id, "work_item_id")
    sb = get_supabase()
    return wis.set_work_item_due_date(
        sb,
        wid,
        body.due_at,
        current_user,
    )


@router.post("/work-items/{work_item_id}/notes")
async def add_work_item_note(
    work_item_id: str,
    body: NoteRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Add a timestamped comment/note to the activity timeline."""
    wid = _parse_uuid(work_item_id, "work_item_id")
    sb = get_supabase()
    return wis.add_work_item_note(
        sb,
        wid,
        body.note,
        current_user,
    )


@router.post("/work-items/{work_item_id}/resolve")
async def resolve_work_item(
    work_item_id: str,
    body: ResolutionRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Record structured operational resolution with maker-checker guardrails."""
    wid = _parse_uuid(work_item_id, "work_item_id")
    sb = get_supabase()
    return wis.resolve_work_item(
        sb,
        wid,
        body.resolution_code,
        body.resolution_note,
        current_user,
    )


@router.post("/work-items/{work_item_id}/dismiss")
async def dismiss_work_item(
    work_item_id: str,
    body: DismissRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Dismiss a work item with mandatory reason."""
    wid = _parse_uuid(work_item_id, "work_item_id")
    sb = get_supabase()
    return wis.dismiss_work_item(
        sb,
        wid,
        body.reason,
        current_user,
    )


@router.post("/work-items/{work_item_id}/reopen")
async def reopen_work_item(
    work_item_id: str,
    body: ReopenRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Reopen a previously resolved or dismissed work item (Admin/Owner only)."""
    wid = _parse_uuid(work_item_id, "work_item_id")
    sb = get_supabase()
    return wis.reopen_work_item(
        sb,
        wid,
        body.reason,
        current_user,
    )


@router.post("/work-items/{work_item_id}/revalidate")
async def request_work_item_revalidation(
    work_item_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Register revalidation hook for Phase 5.5 without altering reconciliation engines."""
    wid = _parse_uuid(work_item_id, "work_item_id")
    sb = get_supabase()
    return wis.request_work_item_revalidation(
        sb,
        wid,
        current_user,
    )


@router.post("/work-items/bulk-action")
async def execute_bulk_action(
    body: BulkActionRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Execute bulk operation across work items."""
    sb = get_supabase()
    return wis.execute_bulk_action(
        sb,
        body.action,
        body.work_item_ids,
        body.payload,
        current_user,
    )


# Phase 5.3: Vendor Resolution & Communication Endpoints
@router.post("/work-items/{work_item_id}/vendor-response")
async def record_vendor_response_endpoint(
    work_item_id: str,
    body: VendorResponseRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Record structured vendor response into itc_work_item_events and update work item status."""
    wid = _parse_uuid(work_item_id, "work_item_id")
    sb = get_supabase()
    return wis.record_vendor_response(
        sb,
        wid,
        body.model_dump(),
        current_user,
    )


@router.get("/work-items/{work_item_id}/vendor-profile")
async def get_work_item_vendor_profile_endpoint(
    work_item_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Fetch vendor compliance scorecard metrics and open work items summary for a work item."""
    wid = _parse_uuid(work_item_id, "work_item_id")
    sb = get_supabase()
    return wis.get_work_item_vendor_profile(
        sb,
        wid,
        current_user,
    )


@router.post("/work-items/{work_item_id}/schedule-followup")
async def schedule_work_item_followup_endpoint(
    work_item_id: str,
    body: ScheduleFollowupRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Schedule follow-up due date for a work item."""
    wid = _parse_uuid(work_item_id, "work_item_id")
    sb = get_supabase()
    return wis.schedule_work_item_followup(
        sb,
        wid,
        body.due_at,
        body.note,
        current_user,
    )
