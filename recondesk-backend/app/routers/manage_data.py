"""Manage raw import files (GSTR-2B / PR) for firm admins — `/api/v1/manage-data`."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import get_current_active_user
from app.config import settings
from app.database import get_supabase, get_user_profile
from app.services.reconciliation_import_wizard import wizard_service as ws

_log = logging.getLogger(__name__)
router = APIRouter()

FileType = Literal["gstr2b", "pr"]

_DELETABLE_RUN_STATUSES = frozenset({"completed", "complete", "failed", "error"})

_FILE_META: dict[FileType, dict[str, str]] = {
    "gstr2b": {
        "key_col": "gstr2b_r2_key",
        "deleted_col": "gstr2b_deleted_at",
    },
    "pr": {
        "key_col": "pr_r2_key",
        "deleted_col": "pr_deleted_at",
    },
}


class ManageDataFileInfo(BaseModel):
    name: str | None = None
    size: int | None = None
    uploaded_at: str | None = None
    deleted_at: str | None = None
    is_deleted: bool = False


class ManageDataRow(BaseModel):
    run_id: str
    client_gstin_id: str
    client_name: str
    gstin: str
    period: str | None = None
    status: str
    created_at: str | None = None
    gstr2b: ManageDataFileInfo
    pr: ManageDataFileInfo


class DownloadUrlResponse(BaseModel):
    download_url: str


class DeleteFileResponse(BaseModel):
    ok: bool = True
    run_id: str
    file_type: FileType


def _parse_uuid(s: str, name: str = "id") -> str:
    try:
        return str(UUID(s.strip()))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid {name}",
        ) from exc


def _assert_firm_admin(current_user: dict) -> str:
    """Admin-only feature — staff receive 403."""
    uid = str(current_user.get("id", ""))
    prof = get_user_profile(uid) or {}
    role = (prof.get("role") or "staff").lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return uid


def _assert_run_deletable_for_file_delete(run_row: dict) -> None:
    """Only terminal run statuses may have raw files removed."""
    normalized = str(run_row.get("status") or "").strip().lower()
    if normalized in _DELETABLE_RUN_STATUSES:
        return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Cannot delete file while reconciliation is in progress",
    )


def _file_info(import_row: dict[str, Any] | None, prefix: str) -> ManageDataFileInfo:
    if not import_row:
        return ManageDataFileInfo()
    deleted_at = import_row.get(f"{prefix}_deleted_at")
    return ManageDataFileInfo(
        name=import_row.get(f"{prefix}_file_name"),
        size=import_row.get(f"{prefix}_file_size"),
        uploaded_at=import_row.get(f"{prefix}_uploaded_at"),
        deleted_at=deleted_at,
        is_deleted=bool(deleted_at),
    )


def _presign_get(key: str, expires: int = 300) -> str:
    from app.services.storage_service import get_storage_service
    return get_storage_service().generate_presigned_download_url(key, expires_in=expires)


def _assert_run_owned_by_admin(sb, run_id: str, admin_id: str) -> tuple[dict, dict | None]:
    run_res = (
        sb.table("reconciliation_run")
        .select("id, client_gstin_id, period, status, created_at")
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    if not run_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    run_row = run_res.data[0]

    cg_id = str(run_row.get("client_gstin_id") or "")
    client_res = (
        sb.table("client_gstins")
        .select("id, firm_owner_id, gstin, trade_name, legal_name")
        .eq("id", cg_id)
        .limit(1)
        .execute()
    )
    if not client_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client not found")
    client_row = client_res.data[0]
    if str(client_row.get("firm_owner_id", "")) != admin_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not allowed for this client",
        )

    import_res = (
        sb.table("reconciliation_import_runs")
        .select(
            "id, gstr2b_r2_key, gstr2b_file_name, gstr2b_file_size, gstr2b_uploaded_at, "
            "gstr2b_deleted_at, pr_r2_key, pr_file_name, pr_file_size, pr_uploaded_at, "
            "pr_deleted_at"
        )
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    import_row = import_res.data[0] if import_res.data else None
    return run_row, import_row


@router.get("", response_model=list[ManageDataRow])
async def list_manage_data(
    current_user: dict = Depends(get_current_active_user),
):
    admin_id = _assert_firm_admin(current_user)
    sb = get_supabase()

    clients_res = (
        sb.table("client_gstins")
        .select("id, gstin, trade_name, legal_name")
        .eq("firm_owner_id", admin_id)
        .eq("is_active", True)
        .limit(500)
        .execute()
    )
    clients = list(clients_res.data or [])
    if not clients:
        return []

    client_ids = [str(c["id"]) for c in clients]
    client_by_id = {str(c["id"]): c for c in clients}

    runs_res = (
        sb.table("reconciliation_run")
        .select("id, client_gstin_id, period, status, created_at")
        .in_("client_gstin_id", client_ids)
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )
    runs = list(runs_res.data or [])
    if not runs:
        return []

    run_ids = [str(r["id"]) for r in runs]
    import_res = (
        sb.table("reconciliation_import_runs")
        .select(
            "id, gstr2b_r2_key, gstr2b_file_name, gstr2b_file_size, gstr2b_uploaded_at, "
            "gstr2b_deleted_at, pr_r2_key, pr_file_name, pr_file_size, pr_uploaded_at, "
            "pr_deleted_at"
        )
        .in_("id", run_ids)
        .execute()
    )
    import_by_id = {str(row["id"]): row for row in (import_res.data or [])}

    out: list[ManageDataRow] = []
    for run in runs:
        rid = str(run["id"])
        cg_id = str(run.get("client_gstin_id") or "")
        client = client_by_id.get(cg_id, {})
        import_row = import_by_id.get(rid)
        client_name = (
            str(client.get("trade_name") or "").strip()
            or str(client.get("legal_name") or "").strip()
            or str(client.get("gstin") or "").strip()
            or "Client"
        )
        out.append(
            ManageDataRow(
                run_id=rid,
                client_gstin_id=cg_id,
                client_name=client_name,
                gstin=str(client.get("gstin") or ""),
                period=run.get("period"),
                status=str(run.get("status") or ""),
                created_at=run.get("created_at"),
                gstr2b=_file_info(import_row, "gstr2b"),
                pr=_file_info(import_row, "pr"),
            )
        )
    return out


@router.delete("/{run_id}/{file_type}", response_model=DeleteFileResponse)
async def delete_manage_data_file(
    run_id: str,
    file_type: FileType,
    current_user: dict = Depends(get_current_active_user),
):
    admin_id = _assert_firm_admin(current_user)
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    run_row, import_row = _assert_run_owned_by_admin(sb, rid, admin_id)

    if not import_row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import files not found for this run")

    _assert_run_deletable_for_file_delete(run_row)

    meta = _FILE_META[file_type]
    key_col = meta["key_col"]
    deleted_col = meta["deleted_col"]
    r2_key = import_row.get(key_col)
    if import_row.get(deleted_col):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File already deleted",
        )
    if not r2_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found for this run")

    ws.delete_r2_keys([r2_key])
    now = datetime.now(timezone.utc).isoformat()
    sb.table("reconciliation_import_runs").update({deleted_col: now}).eq("id", rid).execute()

    _log.info(
        "manage_data: deleted %s file for run %s (admin=%s)",
        file_type,
        rid,
        admin_id,
    )
    return DeleteFileResponse(run_id=rid, file_type=file_type)


@router.get("/{run_id}/{file_type}/download", response_model=DownloadUrlResponse)
async def download_manage_data_file(
    run_id: str,
    file_type: FileType,
    current_user: dict = Depends(get_current_active_user),
):
    admin_id = _assert_firm_admin(current_user)
    rid = _parse_uuid(run_id, "run_id")
    sb = get_supabase()
    _run_row, import_row = _assert_run_owned_by_admin(sb, rid, admin_id)

    if not import_row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import files not found for this run")

    meta = _FILE_META[file_type]
    key_col = meta["key_col"]
    deleted_col = meta["deleted_col"]
    if import_row.get(deleted_col):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File has been deleted")
    r2_key = import_row.get(key_col)
    if not r2_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found for this run")

    url = _presign_get(r2_key, expires=300)
    return DownloadUrlResponse(download_url=url)
