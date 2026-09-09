"""Register upload helpers: type detection for Purchase vs Sales (Tally Export).

``POST /api/register-upload/detect-type`` inspects an Excel/CSV register,
classifies it as Purchase (GSTR-2B) or Sales (GSTR-1), returns Tally Export
validation issues and help copy, and lets the CA override when ambiguous.
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.auth import get_current_user_id
from app.parsers.tally_register import (
    TALLY_HELP_COPY,
    inspect_register_file,
)
from app.services.reconciliation_import_wizard import wizard_service as ws
from app.database import get_supabase

router = APIRouter()
_log = logging.getLogger(__name__)

ALLOWED_EXT = {".csv", ".xlsx", ".xls"}
MAX_BYTES = 20 * 1024 * 1024


def _ext_ok(filename: str) -> bool:
    dot = filename.rfind(".")
    if dot < 0:
        return False
    return filename[dot:].lower() in ALLOWED_EXT


def _assert_access(client_gstin_id: str, user_id: str) -> None:
    sb = get_supabase()
    ws.assert_client_access(sb, client_gstin_id, user_id)


@router.post("/detect-type")
async def detect_register_type_endpoint(
    file: UploadFile = File(...),
    expected_type: Optional[Literal["purchase", "sales"]] = Form(None),
    override_type: Optional[Literal["purchase", "sales"]] = Form(None),
    client_gstin_id: Optional[str] = Form(None),
    user_id: str = Depends(get_current_user_id),
):
    """Detect Purchase vs Sales register type and Tally Export quirks.

    - When confident, ``register_type`` is ``purchase`` or ``sales`` and
      ``suggested_pipeline`` is ``gstr2b`` / ``gstr1``.
    - When ambiguous (or low confidence), ``requires_manual_choice`` is true —
      the CA must pick via ``override_type`` on a subsequent call / in the UI.
    - ``override_type`` forces the chosen type while still returning detection
      metadata and validation for that type.
    """
    if client_gstin_id:
        _assert_access(client_gstin_id, user_id)

    filename = file.filename or "upload.xlsx"
    if not _ext_ok(filename):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only .csv, .xlsx, and .xls files are accepted",
        )
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File too large (max 20 MB)")

    detection = inspect_register_file(
        content,
        filename,
        expected_type=expected_type,
    )
    payload = detection.to_dict()

    effective_type = override_type
    if effective_type is None and detection.register_type in ("purchase", "sales"):
        if detection.confidence in ("high", "medium"):
            effective_type = detection.register_type
    if effective_type is None and expected_type and not detection.requires_manual_choice:
        # Soft default only when detection already agrees or is weak.
        if detection.register_type in (expected_type, "ambiguous"):
            effective_type = expected_type

    payload["effective_type"] = effective_type
    payload["override_applied"] = bool(override_type)
    if effective_type:
        payload["suggested_pipeline"] = (
            "gstr2b" if effective_type == "purchase" else "gstr1"
        )
        payload["help_copy"] = TALLY_HELP_COPY[effective_type]
        # Re-validate for the effective type (override may differ from detect).
        from app.parsers.tally_register import validate_tally_export

        payload["validation_issues"] = validate_tally_export(
            register_type=effective_type,
            headers=detection.headers,
            is_tally_export=detection.is_tally_export,
        )

    # Wrong-pipeline hint for the current page.
    pipeline_mismatch = False
    if (
        expected_type
        and detection.register_type in ("purchase", "sales")
        and detection.register_type != expected_type
        and detection.confidence in ("high", "medium")
        and not override_type
    ):
        pipeline_mismatch = True
    payload["pipeline_mismatch"] = pipeline_mismatch

    if expected_type == "purchase":
        payload["context_help_copy"] = TALLY_HELP_COPY["purchase"]
    elif expected_type == "sales":
        payload["context_help_copy"] = TALLY_HELP_COPY["sales"]
    else:
        payload["context_help_copy"] = payload.get("help_copy")

    _log.info(
        "register detect-type file=%s detected=%s conf=%s tally=%s override=%s user=%s",
        filename,
        detection.register_type,
        detection.confidence,
        detection.is_tally_export,
        override_type,
        user_id,
    )
    return payload


@router.get("/help")
async def tally_export_help(
    register_type: Optional[Literal["purchase", "sales"]] = None,
    user_id: str = Depends(get_current_user_id),
):
    """Return short in-app instructions for exporting registers from Tally."""
    _ = user_id
    if register_type:
        return {
            "purchase" if register_type == "purchase" else "sales": TALLY_HELP_COPY[
                register_type
            ],
            "help_copy": TALLY_HELP_COPY[register_type],
        }
    return {
        "purchase": TALLY_HELP_COPY["purchase"],
        "sales": TALLY_HELP_COPY["sales"],
    }
