"""PR upload column-mapping API: /api/pr-upload/*."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.auth import get_current_user_id
from app.database import get_supabase
from app.services import client_import_mapping as cim
from app.services.reconciliation_import_wizard import wizard_service as ws

router = APIRouter()
_log = logging.getLogger(__name__)

ALLOWED_EXT = {".csv", ".xlsx", ".xls"}
MAX_BYTES = 20 * 1024 * 1024


class MappingSaveBody(BaseModel):
    mappings: list[cim.MappingItem]


def _assert_access(client_gstin_id: str, user_id: str) -> None:
    sb = get_supabase()
    ws.assert_client_access(sb, client_gstin_id, user_id)


def _ext_ok(filename: str) -> bool:
    dot = filename.rfind(".")
    if dot < 0:
        return False
    return filename[dot:].lower() in ALLOWED_EXT


@router.post("/detect-columns")
async def detect_columns(
    file: UploadFile = File(...),
    client_gstin_id: Optional[str] = Form(None),
    user_id: str = Depends(get_current_user_id),
):
    """Return column headers from the uploaded file (header row only)."""
    if client_gstin_id:
        _assert_access(client_gstin_id, user_id)
    filename = file.filename or "upload.csv"
    if not _ext_ok(filename):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only .csv, .xlsx, and .xls files are accepted",
        )
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File too large (max 20 MB)")
    headers = cim.extract_headers_from_file(content, filename)
    schema_ok = cim.columns_match_expected_schema(headers)
    saved = None
    covers = False
    if client_gstin_id:
        sb = get_supabase()
        saved = cim.get_mappings_or_none(sb, client_gstin_id)
        if saved:
            covers = cim.mapping_covers_headers(saved, headers)

    # Type detection + Tally Export profile hints (Purchase pipeline context).
    from app.parsers.tally_register import inspect_register_file

    detection = inspect_register_file(
        content, filename, expected_type="purchase"
    )
    return {
        "headers": headers,
        "schema_ok": schema_ok,
        "saved_mapping": saved,
        "saved_mapping_covers": covers,
        "register_type_detection": detection.to_dict(),
    }


@router.get("/mapping/{client_gstin_id}")
async def get_mapping(
    client_gstin_id: uuid.UUID,
    user_id: str = Depends(get_current_user_id),
):
    cid = str(client_gstin_id)
    _assert_access(cid, user_id)
    sb = get_supabase()
    rows = cim.get_mappings_or_none(sb, cid)
    return {"mappings": rows}


@router.post("/mapping/{client_gstin_id}")
async def save_mapping(
    client_gstin_id: uuid.UUID,
    body: MappingSaveBody,
    user_id: str = Depends(get_current_user_id),
):
    cid = str(client_gstin_id)
    _assert_access(cid, user_id)
    sb = get_supabase()
    rows = cim.save_mappings(sb, cid, body.mappings)
    return {"mappings": rows}


@router.delete("/mapping/{client_gstin_id}")
async def delete_mapping(
    client_gstin_id: uuid.UUID,
    user_id: str = Depends(get_current_user_id),
):
    cid = str(client_gstin_id)
    _assert_access(cid, user_id)
    sb = get_supabase()
    cim.delete_mappings(sb, cid)
    return {"ok": True}


@router.post("/validate-for-upload")
async def validate_for_upload(
    file: UploadFile = File(...),
    client_gstin_id: str = Form(...),
    user_id: str = Depends(get_current_user_id),
):
    """Check whether upload can proceed without a mapping prompt.

    Returns 200 when schema matches or a saved mapping covers headers.
    Returns 422 with detected headers when mapping is required.
    """
    _assert_access(client_gstin_id, user_id)
    filename = file.filename or "upload.csv"
    if not _ext_ok(filename):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only .csv, .xlsx, and .xls files are accepted",
        )
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File too large (max 20 MB)")
    headers = cim.extract_headers_from_file(content, filename)
    sb = get_supabase()
    saved = cim.get_mappings_or_none(sb, client_gstin_id)
    if saved and cim.mapping_covers_headers(saved, headers):
        return {
            "ok": True,
            "headers": headers,
            "mapping_applied": True,
            "mappings": saved,
        }
    if cim.columns_match_expected_schema(headers):
        return {
            "ok": True,
            "headers": headers,
            "mapping_applied": False,
            "mappings": saved,
        }
    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "message": "Column mapping required",
            "headers": headers,
            "saved_mapping": saved,
            "missing_required": sorted(cim.REQUIRED_TARGET_FIELDS),
            "tax_fields": sorted(cim.TAX_TARGET_FIELDS),
        },
    )
