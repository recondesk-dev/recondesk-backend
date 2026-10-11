"""FastAPI router for Phase 3.4 CA Firm Practice Management: `/api/practice`."""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.auth import get_current_active_user
from app.database import get_supabase
from app.routers.clients import _resolve_firm_owner
from app.services.practice_service import (
    bulk_assign_staff,
    bulk_create_tasks,
    bulk_update_task_statuses,
    create_task,
    delete_task,
    ensure_organization_for_gstin,
    get_compliance_calendar,
    get_organization_detail,
    get_partner_governance_dashboard,
    get_task_history,
    get_unified_practice_dashboard,
    list_organizations,
    list_tasks,
    update_organization,
    update_task,
)

router = APIRouter(redirect_slashes=False)
practice_router = router

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request & Response Schemas
# ---------------------------------------------------------------------------

class CreateOrganizationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    gstin: str
    trade_name: Optional[str] = None
    legal_name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None


class UpdateOrganizationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    legal_name: Optional[str] = None
    trade_name: Optional[str] = None
    constitution_of_business: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class CreateTaskRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    category: Optional[str] = "GENERAL_COMPLIANCE"
    organization_id: Optional[str] = None
    client_gstin_id: Optional[str] = None
    period: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = "MEDIUM"
    assignee_id: Optional[str] = None
    due_date: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class UpdateTaskRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Optional[str] = None
    assignee_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None
    notes: Optional[str] = None


class BulkAssignRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client_ids: list[str]
    assigned_to: str
    assignment_role: Optional[str] = "preparer"


class BulkTaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tasks: list[dict[str, Any]]


class BulkTaskStatusRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task_ids: list[str]
    status: str
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# 1. PAN Organizations Endpoints
# ---------------------------------------------------------------------------

@router.get("/organizations")
async def list_organizations_endpoint(
    search: Optional[str] = Query(None, description="Search by legal name, trade name or PAN"),
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """List tenant-scoped legal organizations with associated GSTIN counts and open tasks."""
    sb = get_supabase()
    uid = str(current_user.get("id", "")).strip()
    role = str(current_user.get("role", "")).strip().lower()
    firm_id = _resolve_firm_owner(sb, uid, role=role)

    orgs = list_organizations(sb, firm_id=firm_id, current_user=current_user, search=search)
    return {"organizations": orgs}


@router.post("/organizations")
async def create_or_sync_organization_endpoint(
    body: CreateOrganizationRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Ensure organization exists for the given GSTIN; creates and links if absent."""
    sb = get_supabase()
    uid = str(current_user.get("id", "")).strip()
    role = str(current_user.get("role", "")).strip().lower()
    firm_id = _resolve_firm_owner(sb, uid, role=role)

    org = ensure_organization_for_gstin(
        sb,
        firm_id=firm_id,
        gstin=body.gstin,
        trade_name=body.trade_name,
        legal_name=body.legal_name,
        contact_name=body.contact_name,
        contact_email=body.contact_email,
        contact_phone=body.contact_phone,
    )
    return {"organization": org.to_dict()}


@router.get("/organizations/{org_id}")
async def get_organization_detail_endpoint(
    org_id: str,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Retrieve organization detail with linked GSTINs and active staff tasks."""
    sb = get_supabase()
    uid = str(current_user.get("id", "")).strip()
    role = str(current_user.get("role", "")).strip().lower()
    firm_id = _resolve_firm_owner(sb, uid, role=role)

    org = get_organization_detail(sb, firm_id=firm_id, org_id=org_id, current_user=current_user)
    return {"organization": org}


@router.patch("/organizations/{org_id}")
async def update_organization_endpoint(
    org_id: str,
    body: UpdateOrganizationRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Update organization metadata; requires writer role or above."""
    sb = get_supabase()
    uid = str(current_user.get("id", "")).strip()
    role = str(current_user.get("role", "")).strip().lower()
    firm_id = _resolve_firm_owner(sb, uid, role=role)

    updated = update_organization(
        sb,
        firm_id=firm_id,
        org_id=org_id,
        actor=current_user,
        update_data=body.model_dump(exclude_unset=True),
    )
    return {"organization": updated.to_dict()}


# ---------------------------------------------------------------------------
# 2. Unified Practice Dashboard & Partner Governance
# ---------------------------------------------------------------------------

@router.get("/dashboard")
async def get_practice_dashboard_endpoint(
    period: Optional[str] = Query(None, description="Filing period YYYY-MM"),
    organization_id: Optional[str] = Query(None, description="Filter by organization ID"),
    client_gstin_id: Optional[str] = Query(None, description="Filter by client GSTIN ID"),
    status: Optional[str] = Query(None, description="Filter by actionable stage"),
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Unified CA practice dashboard aggregating organizations, GSTINs, and filing progress."""
    sb = get_supabase()
    uid = str(current_user.get("id", "")).strip()
    role = str(current_user.get("role", "")).strip().lower()
    firm_id = _resolve_firm_owner(sb, uid, role=role)

    data = get_unified_practice_dashboard(
        sb,
        firm_id=firm_id,
        current_user=current_user,
        period=period,
        organization_id=organization_id,
        client_gstin_id=client_gstin_id,
        status_filter=status,
    )
    return data


@router.get("/partner-governance")
async def get_partner_governance_endpoint(
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Partner governance overview: pending maker-checker reviews, client consents, and overrides."""
    sb = get_supabase()
    uid = str(current_user.get("id", "")).strip()
    role = str(current_user.get("role", "")).strip().lower()
    firm_id = _resolve_firm_owner(sb, uid, role=role)

    data = get_partner_governance_dashboard(sb, firm_id=firm_id, current_user=current_user)
    return data


@router.get("/calendar")
async def get_compliance_calendar_endpoint(
    period: Optional[str] = Query(None, description="Filing period YYYY-MM"),
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Upcoming and overdue statutory GST filing deadlines."""
    sb = get_supabase()
    uid = str(current_user.get("id", "")).strip()
    role = str(current_user.get("role", "")).strip().lower()
    firm_id = _resolve_firm_owner(sb, uid, role=role)

    deadlines = get_compliance_calendar(sb, firm_id=firm_id, period=period)
    return {"deadlines": deadlines}


# ---------------------------------------------------------------------------
# 3. Staff Task Management
# ---------------------------------------------------------------------------

@router.get("/tasks")
async def list_tasks_endpoint(
    status: Optional[str] = Query(None, description="Filter by task status"),
    assignee_id: Optional[str] = Query(None, description="Filter by assigned staff"),
    client_gstin_id: Optional[str] = Query(None, description="Filter by client GSTIN ID"),
    organization_id: Optional[str] = Query(None, description="Filter by organization ID"),
    period: Optional[str] = Query(None, description="Filter by period YYYY-MM"),
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """List staff tasks matching optional filters."""
    sb = get_supabase()
    uid = str(current_user.get("id", "")).strip()
    role = str(current_user.get("role", "")).strip().lower()
    firm_id = _resolve_firm_owner(sb, uid, role=role)

    tasks = list_tasks(
        sb,
        firm_id=firm_id,
        current_user=current_user,
        status_filter=status,
        assignee_id=assignee_id,
        client_gstin_id=client_gstin_id,
        organization_id=organization_id,
        period=period,
    )
    return {"tasks": tasks}


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def create_task_endpoint(
    body: CreateTaskRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Create a persistent staff task."""
    sb = get_supabase()
    uid = str(current_user.get("id", "")).strip()
    role = str(current_user.get("role", "")).strip().lower()
    firm_id = _resolve_firm_owner(sb, uid, role=role)

    task = create_task(
        sb,
        firm_id=firm_id,
        actor=current_user,
        title=body.title,
        category=body.category or "GENERAL_COMPLIANCE",
        organization_id=body.organization_id,
        client_gstin_id=body.client_gstin_id,
        period=body.period,
        description=body.description,
        priority=body.priority or "MEDIUM",
        assignee_id=body.assignee_id,
        due_date=body.due_date,
        metadata=body.metadata,
    )
    return {"task": task.to_dict()}


@router.patch("/tasks/{task_id}")
async def update_task_endpoint(
    task_id: str,
    body: UpdateTaskRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Update task status or reassign; enforces role authorities."""
    sb = get_supabase()
    uid = str(current_user.get("id", "")).strip()
    role = str(current_user.get("role", "")).strip().lower()
    firm_id = _resolve_firm_owner(sb, uid, role=role)

    task = update_task(
        sb,
        firm_id=firm_id,
        task_id=task_id,
        actor=current_user,
        update_data=body.model_dump(exclude_unset=True),
    )
    return {"task": task.to_dict()}


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_endpoint(
    task_id: str,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Delete task; restricted to Manager, Partner, and Owner."""
    sb = get_supabase()
    uid = str(current_user.get("id", "")).strip()
    role = str(current_user.get("role", "")).strip().lower()
    firm_id = _resolve_firm_owner(sb, uid, role=role)

    delete_task(sb, firm_id=firm_id, task_id=task_id, actor=current_user)
    return None


@router.get("/tasks/{task_id}/history")
async def get_task_history_endpoint(
    task_id: str,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Retrieve audit history and transitions for a task."""
    sb = get_supabase()
    uid = str(current_user.get("id", "")).strip()
    role = str(current_user.get("role", "")).strip().lower()
    firm_id = _resolve_firm_owner(sb, uid, role=role)

    history = get_task_history(sb, firm_id=firm_id, task_id=task_id)
    return {"history": history}


# ---------------------------------------------------------------------------
# 4. Safe Bulk Operations
# ---------------------------------------------------------------------------

@router.post("/bulk/assign")
async def bulk_assign_endpoint(
    body: BulkAssignRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Assign staff across multiple clients with failure isolation."""
    sb = get_supabase()
    uid = str(current_user.get("id", "")).strip()
    role = str(current_user.get("role", "")).strip().lower()
    firm_id = _resolve_firm_owner(sb, uid, role=role)

    res = bulk_assign_staff(
        sb,
        firm_id=firm_id,
        actor=current_user,
        client_ids=body.client_ids,
        assigned_to=body.assigned_to,
        assignment_role=body.assignment_role or "preparer",
    )
    return res.to_dict()


@router.post("/bulk/tasks")
async def bulk_create_tasks_endpoint(
    body: BulkTaskCreateRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Create tasks in bulk with per-item validation."""
    sb = get_supabase()
    uid = str(current_user.get("id", "")).strip()
    role = str(current_user.get("role", "")).strip().lower()
    firm_id = _resolve_firm_owner(sb, uid, role=role)

    res = bulk_create_tasks(
        sb,
        firm_id=firm_id,
        actor=current_user,
        tasks=body.tasks,
    )
    return res.to_dict()


@router.post("/bulk/tasks/status")
async def bulk_update_task_statuses_endpoint(
    body: BulkTaskStatusRequest,
    current_user: dict[str, Any] = Depends(get_current_active_user),
):
    """Update status across multiple tasks with per-item RBAC."""
    sb = get_supabase()
    uid = str(current_user.get("id", "")).strip()
    role = str(current_user.get("role", "")).strip().lower()
    firm_id = _resolve_firm_owner(sb, uid, role=role)

    res = bulk_update_task_statuses(
        sb,
        firm_id=firm_id,
        actor=current_user,
        task_ids=body.task_ids,
        target_status=body.status,
        notes=body.notes,
    )
    return res.to_dict()
