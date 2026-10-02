"""Tally Bridge sync API: `/api/tally-sync`.

Local agent authenticates with a firm-scoped API key (``tally_bridge_keys``).
Dashboard endpoints use the normal Supabase JWT via ``get_current_active_user``.

POST /outstanding accepts:
  - ``outstanding``: Bills Payable rows (pending due) — unpaid truth only
  - ``payments``: Payment Agst Ref allocations — only settle path
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
from uuid import uuid4

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator

from app.auth import get_current_active_user
from app.config import get_settings
from app.database import get_supabase
from app.services.tally_bridge_sync import (
    apply_tally_bridge_sync,
    generate_tally_bridge_api_key,
)
from app.utils.audit import resolve_firm_id

router = APIRouter()
_log = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)


def _get_compliance_repo():
    """Return Aurora compliance repo or None."""
    try:
        from app.repositories.compliance import get_compliance_repository
        return get_compliance_repository()
    except Exception:
        return None

_AGENT_PATH = (
    Path(__file__).resolve().parents[2] / "tally_bridge" / "tally_bridge_agent.py"
)
_CONFIG_EXAMPLE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tally_bridge"
    / "tally_bridge.config.example.json"
)
_EXE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tally_bridge"
    / "dist"
    / "ReconDeskTallyBridge.exe"
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


class TallyLedgerRow(BaseModel):
    name: str = Field(..., min_length=1)
    parent_group: str = ""
    gstin: str = ""
    state: str = ""
    opening_balance: Optional[float] = None
    closing_balance: Optional[float] = None


class TallyBridgeSyncBody(BaseModel):
    company_name: str = ""
    synced_at: Optional[str] = None
    outstanding: list[TallyOutstandingRow] = Field(default_factory=list)
    payments: list[TallyPaymentRow] = Field(default_factory=list)
    ledgers: list[TallyLedgerRow] = Field(default_factory=list)


class TallyKeyCreateBody(BaseModel):
    company_name: str = Field(default="", max_length=200)


# Native Tally header order — matches TALLY_PURCHASE_ALIASES primary aliases.
# purchase_register_parser.py recognises all of these via its alias map.
_PR_HEADERS: List[str] = [
    "GSTIN/UIN",
    "Party's A/c Name",
    "Inv No.",
    "Inv Date",
    "Taxable Amt",
    "IGST Amt",
    "CGST Amt",
    "SGST Amt",
    "Gross Total",
]

_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class TallyPurchaseRegisterBody(BaseModel):
    client_gstin_id: str = Field(..., min_length=1)
    period: str = Field(..., min_length=7, max_length=7)  # YYYY-MM
    company_name: str = ""
    rows: List[dict] = Field(default_factory=list)

    @field_validator("period")
    @classmethod
    def _validate_period(cls, v: str) -> str:
        if not _PERIOD_RE.match(v):
            raise ValueError("period must be YYYY-MM")
        return v


def _s3_client():
    from app.services.storage_service import get_storage_service
    return get_storage_service().get_s3_client()


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
    ledgers = [r.model_dump() for r in body.ledgers]
    sb = get_supabase()
    try:
        result = apply_tally_bridge_sync(
            sb,
            account_id=account_id,
            outstanding=outstanding,
            payments=payments,
            ledgers=ledgers,
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


@router.post("/purchase-register")
async def tally_sync_purchase_register(
    body: TallyPurchaseRegisterBody,
    key_row: dict[str, Any] = Depends(require_tally_bridge_key),
):
    """Receive a parsed Purchase Register from the local Tally Bridge agent.

    Builds an .xlsx from the raw Tally rows (native header names that
    purchase_register_parser.py already understands), uploads to R2, and
    dispatches the existing run_import_job task with file_type
    'purchase_register'.  Deduplication mirrors the GSTR-2B find-or-create
    pattern in app/routers/import_router.py.
    """
    account_id = str(key_row.get("account_id") or "").strip()
    if not account_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="api key missing account_id",
        )

    cg = str(body.client_gstin_id).strip()
    period_norm = str(body.period).strip()

    # ── 1. Ownership check ────────────────────────────────────────────────
    sb = get_supabase()
    try:
        cg_res = (
            sb.table("client_gstins")
            .select("id, firm_owner_id")
            .eq("id", cg)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        _log.exception("client_gstins lookup failed cg=%s", cg)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="database error",
        ) from exc
    if not cg_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="client_gstin_id not found",
        )
    firm_owner = str(cg_res.data[0].get("firm_owner_id") or "").strip()
    if firm_owner != account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="client_gstin_id does not belong to this api key",
        )

    # ── 2. Build .xlsx from rows ──────────────────────────────────────────
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(_PR_HEADERS)
    for row in body.rows:
        ws.append([str(row.get(h, "")) for h in _PR_HEADERS])
    buf = io.BytesIO()
    wb.save(buf)
    xlsx_bytes = buf.getvalue()

    # ── 3. Deduplicate on (client_gstin_id, period, file_hash, file_type) ─
    file_hash = hashlib.sha256(xlsx_bytes).hexdigest()
    ts = int(datetime.now(timezone.utc).timestamp())
    r2_key = f"uploads/{cg}/{period_norm}/tally_pr_{ts}.xlsx"

    dup = (
        sb.table("reconciliation_run")
        .select("id, status")
        .eq("client_gstin_id", cg)
        .eq("period", period_norm)
        .eq("file_hash", file_hash)
        .eq("file_type", "purchase_register")
        .limit(1)
        .execute()
    )
    now = datetime.now(timezone.utc).isoformat()
    if dup.data:
        row_d = dup.data[0]
        prev_status = (row_d.get("status") or "").strip().lower()
        if prev_status not in ("failed",):
            # Already queued / importing / complete — short-circuit.
            return {"run_id": row_d["id"], "status": prev_status or "queued"}
        run_id = row_d["id"]
        sb.table("reconciliation_run").update(
            {
                "r2_key": r2_key,
                "status": "uploading",
                "progress_percent": 0,
                "status_message": None,
                "updated_at": now,
            }
        ).eq("id", run_id).execute()
    else:
        run_id = str(uuid4())
        sb.table("reconciliation_run").insert(
            {
                "id": run_id,
                "client_gstin_id": cg,
                "period": period_norm,
                "file_type": "purchase_register",
                "file_hash": file_hash,
                "r2_key": r2_key,
                "status": "uploading",
                "progress_percent": 0,
                "created_at": now,
                "updated_at": now,
            }
        ).execute()

    # ── 4. Upload xlsx to S3 ──────────────────────────────────────────────
    try:
        from app.services.storage_service import get_storage_service
        get_storage_service().upload_bytes(
            body=xlsx_bytes,
            key=r2_key,
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
        sb.table("reconciliation_run").update(
            {"status": "queued", "updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", run_id).execute()
    except Exception as exc:
        _log.exception("R2 upload failed run_id=%s r2_key=%s", run_id, r2_key)
        sb.table("reconciliation_run").update(
            {
                "status": "failed",
                "status_message": str(exc),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", run_id).execute()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="R2 upload failed",
        ) from exc

    # ── 5. Dispatch import job ────────────────────────────────────────────
    try:
        from app.worker.tasks import run_import_job

        if get_settings().import_use_celery:
            from app.worker.celery_app import celery_app

            try:
                celery_app.send_task(
                    "worker.run_import_job",
                    args=[run_id, "purchase_register", r2_key],
                )
            except Exception as celery_exc:
                _log.warning(
                    "Celery enqueue failed; running synchronously: %s", celery_exc
                )
                run_import_job.apply(args=[run_id, "purchase_register", r2_key])
        else:
            run_import_job.apply(args=[run_id, "purchase_register", r2_key])
    except Exception:
        # Don't 500 the agent — run is already queued in DB.
        _log.exception("import job dispatch failed run_id=%s", run_id)

    # ── 6. Update last_synced_at on the bridge key ────────────────────────
    if len(body.rows) > 0:
        try:
            sb.table("tally_bridge_keys").update(
                {"last_synced_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", str(key_row.get("id"))).execute()
        except Exception:
            pass

    return {"run_id": run_id, "status": "importing"}


class TallySalesRegisterBody(BaseModel):
    client_gstin_id: str = Field(..., min_length=1)
    period: str = Field(..., min_length=7, max_length=7)  # YYYY-MM
    company_name: str = ""
    rows: List[dict] = Field(default_factory=list)

    @field_validator("period")
    @classmethod
    def _validate_period(cls, v: str) -> str:
        if not _PERIOD_RE.match(v):
            raise ValueError("period must be YYYY-MM")
        return v


@router.post("/sales-register")
def tally_sync_sales_register(
    body: TallySalesRegisterBody,
    key_row: dict[str, Any] = Depends(require_tally_bridge_key),
):
    """Receive a parsed Sales Register from the local Tally Bridge agent.

    Builds an .xlsx from the raw Tally rows (native header names), uploads to R2,
    and dispatches the existing run_import_job task with file_type 'sales_register'.
    """
    account_id = str(key_row.get("account_id") or "").strip()
    if not account_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="api key missing account_id",
        )

    cg = str(body.client_gstin_id).strip()
    period_norm = str(body.period).strip()

    # ── 1. Ownership check ────────────────────────────────────────────────
    sb = get_supabase()
    try:
        cg_res = (
            sb.table("client_gstins")
            .select("id, firm_owner_id")
            .eq("id", cg)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        _log.exception("client_gstins lookup failed cg=%s", cg)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="database error",
        ) from exc
    if not cg_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="client_gstin_id not found",
        )
    firm_owner = str(cg_res.data[0].get("firm_owner_id") or "").strip()
    if firm_owner != account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="client_gstin_id does not belong to this api key",
        )

    # ── 2. Build .xlsx from rows ──────────────────────────────────────────
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(_PR_HEADERS)
    for row in body.rows:
        ws.append([str(row.get(h, "")) for h in _PR_HEADERS])
    buf = io.BytesIO()
    wb.save(buf)
    xlsx_bytes = buf.getvalue()

    # ── 3. Deduplicate on (client_gstin_id, period, file_hash, file_type) ─
    file_hash = hashlib.sha256(xlsx_bytes).hexdigest()
    ts = int(datetime.now(timezone.utc).timestamp())
    r2_key = f"uploads/{cg}/{period_norm}/tally_sr_{ts}.xlsx"

    dup = (
        sb.table("reconciliation_run")
        .select("id, status")
        .eq("client_gstin_id", cg)
        .eq("period", period_norm)
        .eq("file_hash", file_hash)
        .eq("file_type", "sales_register")
        .limit(1)
        .execute()
    )
    now = datetime.now(timezone.utc).isoformat()
    if dup.data:
        row_d = dup.data[0]
        prev_status = (row_d.get("status") or "").strip().lower()
        if prev_status not in ("failed",):
            return {"run_id": row_d["id"], "status": prev_status or "queued"}
        run_id = row_d["id"]
        sb.table("reconciliation_run").update(
            {
                "r2_key": r2_key,
                "status": "uploading",
                "progress_percent": 0,
                "status_message": None,
                "updated_at": now,
            }
        ).eq("id", run_id).execute()
    else:
        run_id = str(uuid4())
        sb.table("reconciliation_run").insert(
            {
                "id": run_id,
                "client_gstin_id": cg,
                "period": period_norm,
                "file_type": "sales_register",
                "file_hash": file_hash,
                "r2_key": r2_key,
                "status": "uploading",
                "progress_percent": 0,
                "created_at": now,
                "updated_at": now,
            }
        ).execute()

    # ── 4. Upload xlsx to S3 ──────────────────────────────────────────────
    try:
        from app.services.storage_service import get_storage_service
        get_storage_service().upload_bytes(
            body=xlsx_bytes,
            key=r2_key,
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
        sb.table("reconciliation_run").update(
            {"status": "queued", "updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", run_id).execute()
    except Exception as exc:
        _log.exception("R2 upload failed run_id=%s r2_key=%s", run_id, r2_key)
        sb.table("reconciliation_run").update(
            {
                "status": "failed",
                "status_message": str(exc),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", run_id).execute()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="R2 upload failed",
        ) from exc

    # ── 5. Dispatch import job ────────────────────────────────────────────
    try:
        from app.worker.tasks import run_import_job

        if get_settings().import_use_celery:
            from app.worker.celery_app import celery_app

            try:
                celery_app.send_task(
                    "worker.run_import_job",
                    args=[run_id, "sales_register", r2_key],
                )
            except Exception as celery_exc:
                _log.warning(
                    "Celery enqueue failed; running synchronously: %s", celery_exc
                )
                run_import_job.apply(args=[run_id, "sales_register", r2_key])
        else:
            run_import_job.apply(args=[run_id, "sales_register", r2_key])
    except Exception:
        _log.exception("import job dispatch failed run_id=%s", run_id)

    # ── 6. Update last_synced_at on the bridge key ────────────────────────
    if len(body.rows) > 0:
        try:
            sb.table("tally_bridge_keys").update(
                {"last_synced_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", str(key_row.get("id"))).execute()
        except Exception:
            pass

    return {"run_id": run_id, "status": "importing"}


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


@router.get("/agent-exe")
async def tally_bridge_download_agent_exe(
    current_user: dict = Depends(get_current_active_user),
):
    """Download the Windows one-file agent (.exe), or redirect to published URL."""
    _ = current_user
    if _EXE_PATH.is_file():
        return FileResponse(
            path=str(_EXE_PATH),
            filename="ReconDeskTallyBridge.exe",
            media_type="application/octet-stream",
        )
    redirect_url = (os.environ.get("TALLY_BRIDGE_EXE_URL") or "").strip()
    if redirect_url:
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=(
            "Windows agent not published yet. "
            "Build via GitHub Actions (build-tally-bridge) and place "
            "ReconDeskTallyBridge.exe under tally_bridge/dist/, "
            "or set TALLY_BRIDGE_EXE_URL to a Release/CDN URL."
        ),
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


class TallyReviewResolveBody(BaseModel):
    status: str = Field(..., pattern="^(resolved|rejected|approve|reject)$")
    amount_paid: Optional[float] = None


@router.post("/review/{action_id}/resolve")
async def tally_bridge_resolve_review(
    action_id: str,
    body: TallyReviewResolveBody,
    current_user: dict = Depends(get_current_active_user),
):
    """CA approves (-> resolved) or rejects (-> rejected) a weak party-match row.

    Approving executes full Rule 37 settlement (calculating payment coverage
    and remaining unpaid amount against invoice amount via _upsert_rule37_action),
    making it 100% equivalent in effect to auto-settle and Mark as Settled.
    """
    account_id = _account_id_for_user(current_user)
    sb = get_supabase()

    # Aurora primary read
    repo = _get_compliance_repo()
    row: Optional[dict[str, Any]] = None
    if repo is not None:
        row = repo.get_rule37_action_by_id(action_id)

    # Supabase fallback read (only when Aurora unavailable or row not in Aurora)
    if not row:
        res = (
            sb.table("rule37_actions")
            .select("*")
            .eq("id", action_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Review action not found",
            )
        row = res.data[0]

    if str(row.get("user_id") or "") != account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized access to review item",
        )

    target_status = "resolved" if body.status in ("resolved", "approve") else "rejected"
    run_id = str(row["run_id"])
    record_hash = str(row["record_hash"])
    record_id = f"r37:{record_hash}" if not record_hash.startswith("r37:") else record_hash

    if target_status == "rejected":
        from app.routers.reconciliation_api import _upsert_rule37_action

        _upsert_rule37_action(
            sb,
            run_id=run_id,
            record_id=record_id,
            status_value="rejected",
            user_id=account_id,
            source=str(row.get("source") or "tally_bridge"),
            settled_date=row.get("settled_date"),
            review_metadata=row.get("review_metadata"),
        )
        return {
            "ok": True,
            "action_id": action_id,
            "status": "rejected",
            "payment_coverage": None,
        }

    # Approving -> execute full settlement logic
    from app.routers.reconciliation_api import (
        _build_rule37_rows,
        _notes_count_for_run,
        _payload_or_404,
        _rule37_payment_coverage,
        _upsert_rule37_action,
    )

    amount_paid = (
        round(float(body.amount_paid), 2)
        if body.amount_paid is not None
        else round(float(row.get("amount_paid") or 0.0), 2)
    )

    # Fetch invoice amount from run payload/warnings to calculate remaining & coverage
    invoice_amount = 0.0
    try:
        p = _payload_or_404(sb, run_id)
        notes = _notes_count_for_run(sb, run_id)
        for r in _build_rule37_rows(sb, run_id, p, notes):
            rec_id_clean = str(r.get("id") or "").replace("r37:", "")
            if rec_id_clean == record_hash.replace("r37:", ""):
                invoice_amount = float(r.get("invoice_amount") or r.get("amount") or 0)
                break
    except Exception:
        _log.warning(
            "Could not resolve invoice_amount for run_id=%s record_hash=%s",
            run_id,
            record_hash,
        )

    total_settled = amount_paid
    remaining_unpaid = (
        round(max(invoice_amount - total_settled, 0.0), 2)
        if invoice_amount > 0
        else 0.0
    )
    coverage = (
        _rule37_payment_coverage(total_settled, invoice_amount)
        if invoice_amount > 0
        else "full"
    )

    _upsert_rule37_action(
        sb,
        run_id=run_id,
        record_id=record_id,
        status_value="resolved",
        user_id=account_id,
        amount_paid=amount_paid,
        tds_deducted=0.0,
        tds_confirmed=False,
        total_settled=total_settled,
        remaining_unpaid_amount=remaining_unpaid,
        payment_coverage=coverage,
        source="tally_bridge_manual_confirmation",
        settled_date=row.get("settled_date"),
        review_metadata=row.get("review_metadata"),
    )

    return {
        "ok": True,
        "action_id": action_id,
        "status": "resolved",
        "amount_paid": amount_paid,
        "total_settled": total_settled,
        "remaining_unpaid_amount": remaining_unpaid,
        "payment_coverage": coverage,
    }
