"""Import wizard API: /api/runs, /api/uploads/signed-url."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth import get_current_user_id
from app.utils.redis_cache import invalidate_user_dashboard
from app.config import settings
from app.database import get_supabase, get_user_profile
from app.routers.import_router import (
    _gstin_norm_for_compare,
    _gstr2b_buyer_gstin_from_raw,
)
from app.services.billing_gate import check_run_access, consume_run_credit, sync_billing_credits
from app.services.firm_access import get_firm_owner_for_client
from app.services.reconciliation_import_wizard import wizard_service as ws
from app.utils.audit import client_display_label, log_audit, resolve_firm_id

router = APIRouter()
_log = logging.getLogger(__name__)


def _actor(user_id: str) -> dict:
    prof = get_user_profile(user_id) or {}
    actor = {**prof, "id": user_id}
    actor["firm_id"] = resolve_firm_id(get_supabase(), actor)
    return actor


# ── Models ────────────────────────────────────────────────────────────────────


class CreateRunBody(BaseModel):
    client_id: uuid.UUID
    period: str  # YYYY-MM-DD (first of month) or YYYY-MM


class Gstr2bCompleteBody(BaseModel):
    r2_key: str
    file_name: str
    file_size: int
    file_hash: str


class PrCompleteBody(BaseModel):
    r2_key: str
    file_name: str
    file_size: int
    file_hash: str
    # Optional GSTR-3B claim period for this PR batch (YYYY-MM or YYYY-MM-01).
    itc_claimed_period: Optional[str] = None


class WarningAckBody(BaseModel):
    check_id: str
    check_label: str


class MappingConfirmBody(BaseModel):
    field: str
    detected_column: Optional[str] = None
    confidence: str
    method: str  # manual | auto


class PatchRunBody(BaseModel):
    current_step: Optional[int] = None
    column_mapping: Optional[list[dict[str, Any]]] = None
    sanity_check_results: Optional[list[dict[str, Any]]] = None
    itc_claimed_period: Optional[str] = None  # YYYY-MM / YYYY-MM-01; empty string clears


def _parse_period(p: str) -> str:
    p = p.strip()
    if len(p) == 7 and p[4] == "-":
        y, m = p.split("-", 1)
        return f"{y}-{m}-01"
    if len(p) >= 10:
        return p[:10]
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid period")


def _period_date_iso(period: str) -> str:
    return _parse_period(period)


def _optional_period_or_clear(raw: Optional[str]) -> str | None:
    """Parse optional period; empty/whitespace clears the column (returns None)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    return _period_date_iso(s)


def _pg_unique_violation(exc: BaseException) -> bool:
    code = getattr(exc, "code", None)
    parts: list[str] = [str(exc).lower()]
    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        parts.append(str(cause).lower())
        code = code or getattr(cause, "code", None)
    msg = " ".join(parts)
    return (
        code == "23505"
        or "23505" in msg
        or "duplicate key" in msg
        or "unique constraint" in msg
    )


@router.post("/runs")
async def create_run(
    body: CreateRunBody,
    user_id: str = Depends(get_current_user_id),
):
    sb = get_supabase()
    ws.assert_client_access(sb, str(body.client_id), user_id)
    period_iso = _period_date_iso(body.period)
    row = {
        "client_id": str(body.client_id),
        "firm_owner_id": user_id,
        "period": period_iso,
        "status": "draft",
        "current_step": 1,
        "created_by": user_id,
    }
    try:
        res = sb.table(ws.T_RUNS).insert(row).execute()
    except Exception as exc:  # noqa: BLE001
        if _pg_unique_violation(exc):
            existing_q = (
                sb.table(ws.T_RUNS)
                .select("*")
                .eq("client_id", str(body.client_id))
                .eq("period", period_iso)
                .limit(1)
                .execute()
            )
            if existing_q.data:
                ex = existing_q.data[0]
                ws.assert_client_access(sb, ex["client_id"], user_id)
                return ex
        raise
    data = res.data[0]
    ws.audit(sb, data["id"], user_id, "run_created", {"period": period_iso})
    invalidate_user_dashboard(user_id)
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=data)


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, user_id: str = Depends(get_current_user_id)):
    sb = get_supabase()
    r = ws.fetch_run(sb, str(run_id))
    ws.assert_client_access(sb, r["client_id"], user_id)
    return r


@router.patch("/runs/{run_id}")
async def patch_run(
    run_id: uuid.UUID,
    body: PatchRunBody,
    user_id: str = Depends(get_current_user_id),
):
    sb = get_supabase()
    r = ws.fetch_run(sb, str(run_id))
    ws.assert_client_access(sb, r["client_id"], user_id)
    patch: dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if body.current_step is not None:
        if body.current_step < 1 or body.current_step > 4:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid step")
        patch["current_step"] = body.current_step
    if body.column_mapping is not None:
        patch["column_mapping"] = body.column_mapping
    if body.sanity_check_results is not None:
        patch["sanity_check_results"] = body.sanity_check_results
    if body.itc_claimed_period is not None:
        # Explicit empty string clears; non-empty must be a valid period.
        if str(body.itc_claimed_period).strip() == "":
            patch["itc_claimed_period"] = None
        else:
            patch["itc_claimed_period"] = _optional_period_or_clear(
                body.itc_claimed_period
            )
    sb.table(ws.T_RUNS).update(patch).eq("id", str(run_id)).execute()
    ws.audit(sb, str(run_id), user_id, "run_updated", patch)
    return ws.fetch_run(sb, str(run_id))


@router.get("/uploads/signed-url")
async def signed_upload_url(
    type: str = Query(..., alias="type", description="gstr2b or purchase_register"),
    run_id: uuid.UUID = Query(...),
    file_name: str = Query("upload.json"),
    content_type: str = Query("application/octet-stream"),
    user_id: str = Depends(get_current_user_id),
):
    sb = get_supabase()
    r = ws.fetch_run(sb, str(run_id))
    ws.assert_client_access(sb, r["client_id"], user_id)
    t = type.lower().strip()
    if t == "gstr2b":
        # Allow replace while still on the GSTR-2B step (failed sanity / wrong file).
        if r["status"] not in ("draft", "gstr_uploaded"):
            raise HTTPException(status.HTTP_409_CONFLICT, "GSTR-2B upload not allowed in this state")
        ext = ".json"
        key = f"import-wizard/{run_id}/gstr2b{ext}"
        ct = "application/json"
    elif t in ("purchase_register", "pr"):
        if r["status"] != "gstr_uploaded":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Purchase register upload requires GSTR-2B step complete",
            )
        ext = (file_name.rsplit(".", 1)[-1] if "." in file_name else "csv").lower()
        if ext not in ("csv", "xlsx", "xls"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid extension")
        key = f"import-wizard/{run_id}/pr_{uuid.uuid4().hex[:8]}.{ext}"
        ct = content_type if content_type else (
            "text/csv" if ext == "csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid type")
    url = ws.presign_put(key, ct)
    return {"upload_url": url, "key": key, "method": "PUT", "headers": {"Content-Type": ct}}


@router.post("/runs/{run_id}/uploads/gstr2b/complete")
async def gstr2b_upload_complete(
    run_id: uuid.UUID,
    body: Gstr2bCompleteBody,
    user_id: str = Depends(get_current_user_id),
):
    sb = get_supabase()
    r = ws.fetch_run(sb, str(run_id))
    ws.assert_client_access(sb, r["client_id"], user_id)
    if r["status"] not in ("draft", "gstr_uploaded"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Run is not awaiting GSTR-2B upload")
    if body.file_size > ws.MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File too large")
    size = ws.verify_r2_sha256(body.r2_key, body.file_hash)

    _gstr2_obj = ws._r2().get_object(Bucket=settings.R2_BUCKET_NAME, Key=body.r2_key)
    gstr2_raw = _gstr2_obj["Body"].read()
    file_gstin_raw = _gstr2b_buyer_gstin_from_raw(gstr2_raw) or ""
    cg_res = (
        sb.table("client_gstins")
        .select("gstin")
        .eq("id", str(r["client_id"]))
        .limit(1)
        .execute()
    )
    client_gstin_raw = ""
    if cg_res.data and cg_res.data[0].get("gstin") is not None:
        client_gstin_raw = str(cg_res.data[0]["gstin"]).strip()
    if client_gstin_raw and file_gstin_raw:
        if _gstin_norm_for_compare(file_gstin_raw) != _gstin_norm_for_compare(
            client_gstin_raw
        ):
            return JSONResponse(
                status_code=200,
                content={
                    "sanity_check_results": [
                        {
                            "name": "GSTIN match",
                            "status": "ERROR",
                            "message": (
                                f"GSTIN in file ({file_gstin_raw}) does not match "
                                f"client GSTIN ({client_gstin_raw}). Upload the correct file."
                            ),
                        }
                    ]
                },
            )

    file_patch = {
        "gstr2b_r2_key": body.r2_key,
        "gstr2b_file_name": body.file_name,
        "gstr2b_file_size": size,
        "gstr2b_file_hash": body.file_hash.lower(),
        "gstr2b_uploaded_at": datetime.now(timezone.utc).isoformat(),
        # Clear prior sanity so re-upload re-runs checks on the new bytes.
        "sanity_check_results": None,
        "gstr2b_record_count": 0,
        "current_step": 2,
    }
    if r["status"] == "draft":
        ws.transition_run(
            sb,
            str(run_id),
            user_id,
            "gstr_uploaded",
            extra_patch=file_patch,
            audit_event="gstr2b_uploaded",
            audit_detail={"file_size": size, "file_hash": body.file_hash},
        )
    else:
        # Already on GSTR-2B step — replace file in place (no status transition).
        sb.table(ws.T_RUNS).update(
            {**file_patch, "updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", str(run_id)).execute()
        ws.audit(
            sb,
            str(run_id),
            user_id,
            "gstr2b_replaced",
            {"file_size": size, "file_hash": body.file_hash},
        )
    await log_audit(
        sb,
        _actor(user_id),
        "FILE_UPLOADED",
        "file",
        str(run_id),
        body.file_name,
        {"file_type": "gstr2b", "replaced": r["status"] == "gstr_uploaded"},
    )
    return ws.fetch_run(sb, str(run_id))


@router.post("/runs/{run_id}/uploads/purchase-register/complete")
async def pr_upload_complete(
    run_id: uuid.UUID,
    body: PrCompleteBody,
    user_id: str = Depends(get_current_user_id),
):
    sb = get_supabase()
    r = ws.fetch_run(sb, str(run_id))
    ws.assert_client_access(sb, r["client_id"], user_id)
    if r["status"] != "gstr_uploaded":
        raise HTTPException(status.HTTP_409_CONFLICT, "Purchase register upload not allowed")
    if body.file_size > ws.MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File too large")
    size = ws.verify_r2_sha256(body.r2_key, body.file_hash)
    extra: dict[str, Any] = {
        "pr_r2_key": body.r2_key,
        "pr_file_name": body.file_name,
        "pr_file_size": size,
        "pr_file_hash": body.file_hash.lower(),
        "pr_uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    if body.itc_claimed_period is not None:
        if str(body.itc_claimed_period).strip() == "":
            extra["itc_claimed_period"] = None
        else:
            extra["itc_claimed_period"] = _optional_period_or_clear(
                body.itc_claimed_period
            )
    ws.transition_run(
        sb,
        str(run_id),
        user_id,
        "pr_uploaded",
        extra_patch=extra,
        audit_event="pr_uploaded",
        audit_detail={"file_size": size, "file_hash": body.file_hash},
    )
    await log_audit(
        sb,
        _actor(user_id),
        "FILE_UPLOADED",
        "file",
        str(run_id),
        body.file_name,
        {"file_type": "purchase_register"},
    )
    return ws.fetch_run(sb, str(run_id))


@router.post("/runs/{run_id}/sanity-check/gstr2b")
async def sanity_check_gstr2b(
    run_id: uuid.UUID,
    user_id: str = Depends(get_current_user_id),
):
    sb = get_supabase()
    r = ws.fetch_run(sb, str(run_id))
    ws.assert_client_access(sb, r["client_id"], user_id)
    if r["status"] != "gstr_uploaded":
        raise HTTPException(status.HTTP_409_CONFLICT, "Sanity check requires GSTR-2B uploaded (gstr_uploaded)")
    key = r.get("gstr2b_r2_key")
    if not key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "GSTR-2B file not uploaded")
    c = ws._r2()
    obj = c.get_object(Bucket=settings.R2_BUCKET_NAME, Key=key)
    raw = obj["Body"].read()
    checks, record_count = ws.run_sanity_gstr2b_json(raw)
    checks = ws.preserve_check_acknowledgments(
        r.get("sanity_check_results"), checks
    )

    sb.table(ws.T_RUNS).update(
        {
            "sanity_check_results": checks,
            "gstr2b_record_count": record_count,
            "current_step": 2,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", str(run_id)).execute()
    ws.audit(sb, str(run_id), user_id, "sanity_check_gstr2b", {"checks": checks})
    return {"checks": checks}


@router.post("/runs/{run_id}/warnings/acknowledge")
async def acknowledge_warning(
    run_id: uuid.UUID,
    body: WarningAckBody,
    user_id: str = Depends(get_current_user_id),
):
    sb = get_supabase()
    r = ws.fetch_run(sb, str(run_id))
    ws.assert_client_access(sb, r["client_id"], user_id)
    results = list(r.get("sanity_check_results") or [])
    for item in results:
        if isinstance(item, dict) and str(item.get("id")) == str(body.check_id):
            item["acknowledged"] = True
            break
    sb.table(ws.T_RUNS).update(
        {
            "sanity_check_results": results,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", str(run_id)).execute()
    ws.audit(
        sb,
        str(run_id),
        user_id,
        "warning_acknowledged",
        {"check_id": body.check_id, "check_label": body.check_label},
    )
    return {"ok": True}


@router.post("/runs/{run_id}/mapping/confirm")
async def confirm_mapping(
    run_id: uuid.UUID,
    body: MappingConfirmBody,
    user_id: str = Depends(get_current_user_id),
):
    sb = get_supabase()
    r = ws.fetch_run(sb, str(run_id))
    ws.assert_client_access(sb, r["client_id"], user_id)
    ws.audit(
        sb,
        str(run_id),
        user_id,
        "mapping_confirmed",
        {
            "field": body.field,
            "detected_column": body.detected_column,
            "confidence": body.confidence,
            "method": body.method,
        },
    )
    return {"ok": True}


@router.post("/runs/{run_id}/detect-columns")
async def detect_columns(
    run_id: uuid.UUID,
    user_id: str = Depends(get_current_user_id),
):
    sb = get_supabase()
    r = ws.fetch_run(sb, str(run_id))
    ws.assert_client_access(sb, r["client_id"], user_id)
    if r["status"] != "pr_uploaded":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Column detection requires purchase register upload (pr_uploaded)",
        )
    checks = r.get("sanity_check_results") or []
    for item in checks:
        if isinstance(item, dict) and item.get("status") == "error":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Resolve GSTR-2B sanity errors before column detection",
            )
    if ws.blocking_acknowledgments_pending(checks):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Acknowledge high-risk warnings before continuing.",
        )
    pr_key = r.get("pr_r2_key")
    pr_name = r.get("pr_file_name") or "file.csv"
    if not pr_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Purchase register not uploaded")
    (
        columns,
        all_headers,
        pr_rows,
        parse_warnings,
        missing_invoice_count,
        sheets_used,
    ) = ws.detect_pr_columns_from_r2(pr_key, pr_name)

    from app.services import client_import_mapping as cim

    client_id = str(r["client_id"])
    saved = cim.get_mappings_or_none(sb, client_id)
    saved_covers = bool(saved and cim.mapping_covers_headers(saved, all_headers))
    if saved_covers and saved:
        # Prefer persisted client mapping over auto-detect for this upload.
        columns = cim.mapping_rows_to_wizard_columns(saved, all_headers)

    missing_check = ws.build_missing_invoice_number_check(
        missing_invoice_count, parse_warnings
    )
    pr_parse_warning = missing_check["detail"] if missing_check else None

    multi_check = ws.build_multi_sheet_combine_check(sheets_used)
    sanity_results = list(r.get("sanity_check_results") or [])
    sanity_results = ws.upsert_sanity_check(
        sanity_results,
        multi_check,
        check_id=ws.MULTI_SHEET_COMBINE_CHECK_ID,
    )
    sanity_results = ws.upsert_sanity_check(
        sanity_results,
        missing_check,
        check_id=ws.MISSING_INVOICE_CHECK_ID,
    )

    sb.table(ws.T_RUNS).update(
        {
            "column_mapping": columns,
            "pr_column_headers": all_headers,
            "pr_record_count": pr_rows,
            "sanity_check_results": sanity_results,
            "current_step": 3,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", str(run_id)).execute()
    ws.audit(
        sb,
        str(run_id),
        user_id,
        "detect_columns",
        {
            "headers": len(all_headers),
            "sheets_used": len(sheets_used or []),
            "multi_sheet_combine": bool(multi_check),
            "missing_invoice_number": int(missing_invoice_count or 0),
        },
    )
    return {
        "columns": columns,
        "all_headers": all_headers,
        "saved_mapping": saved,
        "saved_mapping_covers": saved_covers,
        "schema_ok": cim.columns_match_expected_schema(all_headers),
        "pr_record_count": pr_rows,
        "pr_parse_warning": pr_parse_warning,
        "missing_invoice_number_count": missing_invoice_count,
        "multi_sheet_combine": multi_check,
        "missing_invoice_number": missing_check,
        "sanity_check_results": sanity_results,
    }


def _validate_start_mapping(mapping: list[dict[str, Any]]) -> None:
    by_field = {m.get("standard_field"): m for m in mapping}
    for req in ("gstin", "invoice_number", "invoice_date", "taxable_value"):
        col = by_field.get(req)
        if not col or not col.get("detected_column"):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"column_mapping must include {req}",
            )
        if col.get("confidence") in ("low", "not_found") and not col.get("confirmed"):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Confirm or fix mapping for {req}",
            )
    tax_ok = any(
        (by_field.get(t) or {}).get("detected_column")
        for t in ("cgst", "sgst", "igst", "cess", "total_tax")
    )
    if not tax_ok:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "column_mapping must include at least one tax field "
            "(cgst, sgst, igst, cess, or total_tax)",
        )
    for col in mapping:
        if not col.get("detected_column"):
            continue
        if col.get("confidence") == "low" and not col.get("confirmed"):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "All low-confidence columns must be confirmed",
            )


@router.post("/runs/{run_id}/start")
async def start_reconciliation(
    run_id: uuid.UUID,
    user_id: str = Depends(get_current_user_id),
):
    sb = get_supabase()
    r = ws.fetch_run(sb, str(run_id))
    ws.assert_client_access(sb, r["client_id"], user_id)
    if r["status"] != "pr_uploaded":
        raise HTTPException(status.HTTP_409_CONFLICT, "Run is not ready to start")
    mapping = r.get("column_mapping")
    if not mapping or not isinstance(mapping, list):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "column_mapping required")
    _validate_start_mapping(mapping)
    if ws.blocking_acknowledgments_pending(r.get("sanity_check_results")):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Acknowledge high-risk warnings before starting reconciliation.",
        )
    if ws.another_processing_run(sb, r["client_id"], r["period"], str(run_id)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A reconciliation is already running for this period.",
        )
    firm_owner = get_firm_owner_for_client(sb, str(r["client_id"]))
    await sync_billing_credits(firm_owner)
    rec = (
        sb.table("reconciliation_run")
        .select("id, paid_at")
        .eq("id", str(run_id))
        .limit(1)
        .execute()
    )
    if not (rec.data and rec.data[0].get("paid_at")):
        gate = await check_run_access(firm_owner)
        if not gate.get("allowed"):
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "message": "No reconciliation runs available. Purchase a plan or use a free run.",
                    "billing": gate,
                },
            )
        now = datetime.now(timezone.utc).isoformat()
        try:
            await consume_run_credit(firm_owner)
        except Exception as exc:
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                detail="No reconciliation runs available.",
            ) from exc
        period = str(r.get("period") or "")[:7]
        if rec.data:
            sb.table("reconciliation_run").update({"paid_at": now}).eq("id", str(run_id)).execute()
        else:
            sb.table("reconciliation_run").insert(
                {
                    "id": str(run_id),
                    "client_gstin_id": str(r["client_id"]),
                    "period": period,
                    "status": "uploading",
                    "progress_percent": 0,
                    "paid_at": now,
                    "created_at": now,
                    "updated_at": now,
                }
            ).execute()
    gstr_n = int(r.get("gstr2b_record_count") or 0)
    pr_n = int(r.get("pr_record_count") or 0)
    ws.transition_run(
        sb,
        str(run_id),
        user_id,
        "pending",
        audit_event="run_queued",
        audit_detail={},
    )
    ws.transition_run(
        sb,
        str(run_id),
        user_id,
        "processing",
        extra_patch={"progress_pct": 0, "status_message": "Starting…"},
        audit_event="run_started",
        audit_detail={"gstr2b_record_count": gstr_n, "pr_record_count": pr_n},
    )
    client_name = client_display_label(sb, str(r["client_id"]))
    period = str(r.get("period") or "")
    entity_label = f"{client_name} ({period})" if period else client_name
    await log_audit(
        sb,
        _actor(user_id),
        "RECON_STARTED",
        "reconciliation",
        str(run_id),
        entity_label,
        {"gstr2b_record_count": gstr_n, "pr_record_count": pr_n},
    )
    # Run the full pipeline in a thread pool so the event loop stays responsive.
    # This blocks until the engine finishes or errors — Railway timeout is
    # extended via --timeout-keep-alive 300 in the Procfile.
    try:
        await asyncio.to_thread(ws.run_processing_job_sync, str(run_id))
    except Exception:
        _log.exception("run_processing_job_sync failed for run_id=%s", run_id)
        try:
            ws.transition_run(
                sb,
                str(run_id),
                user_id,
                "error",
                extra_patch={"status_message": "Internal error during processing. Please retry or contact support."},
                audit_event="run_error",
                audit_detail={},
            )
        except Exception:
            _log.exception("failed to mark run %s as errored after processing failure", run_id)
    invalidate_user_dashboard(user_id)
    return ws.fetch_run(sb, str(run_id))


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: uuid.UUID, user_id: str = Depends(get_current_user_id)):
    sb = get_supabase()
    r = ws.fetch_run(sb, str(run_id))
    ws.assert_client_access(sb, r["client_id"], user_id)
    st = r["status"]
    if st not in ("draft", "gstr_uploaded", "pr_uploaded", "pending", "processing"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Run cannot be cancelled")
    keys = [k for k in (r.get("gstr2b_r2_key"), r.get("pr_r2_key")) if k]
    ws.delete_r2_keys(keys)
    ws.transition_run(
        sb,
        str(run_id),
        user_id,
        "cancelled",
        extra_patch={"current_step": r.get("current_step", 1)},
        audit_event="run_cancelled",
        audit_detail={"cancelled_at_step": r.get("current_step")},
    )
    return ws.fetch_run(sb, str(run_id))


@router.get("/runs/{run_id}/status")
async def poll_status(run_id: uuid.UUID, user_id: str = Depends(get_current_user_id)):
    sb = get_supabase()
    r = ws.fetch_run(sb, str(run_id))
    ws.assert_client_access(sb, r["client_id"], user_id)

    status = r["status"]
    wizard_pct = int(r.get("progress_pct") or 0)
    message = r.get("status_message") or ""

    # Map "error" → "failed" for frontend compatibility.
    if status == "error":
        status = "failed"

    return {
        "status": status,
        "progress_pct": wizard_pct,
        "message": message,
    }



@router.post("/runs/{run_id}/retry")
async def retry_after_error(run_id: uuid.UUID, user_id: str = Depends(get_current_user_id)):
    sb = get_supabase()
    r = ws.fetch_run(sb, str(run_id))
    ws.assert_client_access(sb, r["client_id"], user_id)
    if r["status"] != "error":
        raise HTTPException(status.HTTP_409_CONFLICT, "Run is not in error state")
    ws.transition_run(
        sb,
        str(run_id),
        user_id,
        "pr_uploaded",
        extra_patch={
            "error_detail": None,
            "progress_pct": 0,
            "status_message": None,
        },
        audit_event="run_retry",
        audit_detail={},
    )
    return ws.fetch_run(sb, str(run_id))
