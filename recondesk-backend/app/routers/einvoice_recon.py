"""Books-to-E-Invoice Reconciliation API router — /api/einvoice-recon/*."""

from __future__ import annotations

import io
import json
import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.auth import get_current_active_user, get_current_user_id
from app.database import get_supabase
from app.parsers.einvoice_report import parse_einvoice_report, ParseError
from app.services.einvoice_recon import reconcile_books_vs_einvoice
from app.services.reconciliation_import_wizard import wizard_service as ws
from app.services.reconciliation_record_adapter import pr_db_row_to_matcher_row

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_EXT = {".csv", ".xlsx", ".xls"}
MAX_BYTES = 20 * 1024 * 1024


class RunEinvoiceReconBody(BaseModel):
    client_id: str = Field(..., description="Client GSTIN ID (UUID)")
    period: str = Field(..., description="Tax period in YYYY-MM or MMYYYY format")
    e_invoice_applicable: bool = Field(True, description="Whether e-invoicing is mandated for client")
    einvoice_records: Optional[list[dict[str, Any]]] = Field(None, description="Pre-parsed e-invoice records if provided directly")


def _assert_access(client_gstin_id: str, user_id: str) -> None:
    sb = get_supabase()
    ws.assert_client_access(sb, client_gstin_id, user_id)


def _ext_ok(filename: str) -> bool:
    dot = filename.rfind(".")
    if dot < 0:
        return False
    return filename[dot:].lower() in ALLOWED_EXT


def _normalize_period(period: str) -> str:
    s = period.strip().replace("-", "").replace("/", "")
    if len(s) == 6 and s.isdigit():
        if s.startswith(("20", "19")):
            # YYYYMM -> MMYYYY
            return f"{s[4:]}{s[:4]}"
        else:
            # MMYYYY
            return s
    return period.strip()


def _fetch_books_records_for_period(client_id: str, period: str) -> list[dict[str, Any]]:
    """Fetch existing purchase register / books records for the given client and period."""
    sb = get_supabase()
    norm_period = _normalize_period(period)
    alt_period = f"{norm_period[2:]}-{norm_period[:2]}" if len(norm_period) == 6 else period

    # Query pr_records table
    res = (
        sb.table("pr_records")
        .select("id, record_data")
        .eq("client_gstin_id", client_id)
        .in_("period", [norm_period, period, alt_period])
        .execute()
    )

    rows = res.data or []
    if not rows:
        # Fallback query without period filter if only client_gstin_id matches (e.g. single run client)
        res_all = (
            sb.table("pr_records")
            .select("id, record_data")
            .eq("client_gstin_id", client_id)
            .limit(500)
            .execute()
        )
        rows = res_all.data or []

    books_records = []
    for r in rows:
        books_records.append(pr_db_row_to_matcher_row(r))

    return books_records


@router.post("/upload")
async def upload_einvoice_report(
    file: UploadFile = File(...),
    client_id: str = Form(...),
    period: str = Form(...),
    user_id: str = Depends(get_current_user_id),
):
    """Upload and parse an E-Invoice export report (.xlsx / .csv)."""
    _assert_access(client_id, user_id)
    filename = file.filename or "einvoice_report.xlsx"
    if not _ext_ok(filename):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only .csv, .xlsx, and .xls files are accepted for e-invoice reports.",
        )

    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File size exceeds 20 MB limit.")

    try:
        df_einv = parse_einvoice_report(content, filename)
    except ParseError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error parsing e-invoice report")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to parse e-invoice report: {exc}") from exc

    records = df_einv.to_dict(orient="records")
    return {
        "status": "success",
        "client_id": client_id,
        "period": period,
        "total_records_parsed": len(records),
        "records": records,
    }


@router.post("/run")
async def run_einvoice_recon(
    body: Optional[RunEinvoiceReconBody] = None,
    file: Optional[UploadFile] = File(None),
    client_id: Optional[str] = Form(None),
    period: Optional[str] = Form(None),
    e_invoice_applicable: Optional[bool] = Form(True),
    user_id: str = Depends(get_current_user_id),
):
    """Trigger E-Invoice reconciliation against books/PR data for client + period.
    Accepts JSON body or multipart Form data with optional direct file upload.
    """
    cid = (body.client_id if body else client_id) or ""
    prd = (body.period if body else period) or ""
    is_app = (body.e_invoice_applicable if body else e_invoice_applicable) if (body or e_invoice_applicable is not None) else True

    if not cid or not prd:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Both client_id and period are required.")

    _assert_access(cid, user_id)

    try:
        if body and body.einvoice_records:
            einv_records = body.einvoice_records
        elif file is not None:
            filename = file.filename or "einvoice_report.xlsx"
            if not _ext_ok(filename):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only .csv, .xlsx, and .xls files are accepted.")
            content = await file.read()
            df_einv = parse_einvoice_report(content, filename)
            einv_records = df_einv.to_dict(orient="records")

        # Fetch existing books data
        books_records = _fetch_books_records_for_period(cid, prd)

        # Perform reconciliation
        recon_output = reconcile_books_vs_einvoice(
            books_records=books_records,
            einvoice_records=einv_records,
            e_invoice_applicable=is_app,
        )

        results = recon_output["results"]
        summary = recon_output["summary"]

        run_id = str(uuid.uuid4())
        sb = get_supabase()

        # Persist results in DB
        db_rows = []
        for r in results:
            db_rows.append(
                {
                    "run_id": run_id,
                    "client_gstin_id": cid,
                    "period": prd,
                    "invoice_number": r.get("invoice_number", ""),
                    "irn": r.get("irn"),
                    "irn_status": r.get("irn_status"),
                    "category": r.get("category", "UNMATCHED"),
                    "book_value": r.get("book_value", 0.0),
                    "einvoice_value": r.get("einvoice_value", 0.0),
                    "details": {
                        "gstin": r.get("gstin"),
                        "invoice_date": r.get("invoice_date"),
                        "doc_type": r.get("doc_type") or r.get("document_type") or r.get("invoice_type"),
                        "value_difference": r.get("value_difference"),
                        "ack_number": r.get("ack_number"),
                        "ack_date": r.get("ack_date"),
                        "decision_what": r.get("decision_what"),
                        "decision_why": r.get("decision_why"),
                        "decision_next": r.get("decision_next"),
                        "decision_rule": r.get("decision_rule"),
                    },
                }
            )

        if db_rows:
            aurora_inserted = False
            try:
                from app.repositories.integrations import get_integrations_repository
                repo = get_integrations_repository()
                repo.insert_einvoice_recon_results(db_rows)
                aurora_inserted = True
            except Exception as a_exc:
                logger.warning("Aurora insert einvoice_recon_results failed, falling back to Supabase: %s", a_exc)

            if not aurora_inserted:
                try:
                    sb.table("einvoice_recon_results").insert(db_rows).execute()
                except Exception as exc:
                    logger.warning("Failed to insert einvoice_recon_results into Supabase: %s", exc)

        return {
            "status": "COMPLETED",
            "run_id": run_id,
            "client_id": cid,
            "period": prd,
            "books_records_count": len(books_records),
            "einvoice_records_count": len(einv_records),
            "summary": summary,
            "results": results,
        }
    except ParseError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected error in run_einvoice_recon for client_id=%s, period=%s", cid, prd)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"E-Invoice reconciliation failed: {exc}",
        ) from exc


@router.get("/results/{run_id}")
async def get_einvoice_recon_results(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Retrieve categorized E-Invoice reconciliation results for a run_id."""
    rows = None
    try:
        from app.repositories.integrations import get_integrations_repository
        repo = get_integrations_repository()
        aurora_rows = repo.get_einvoice_recon_results_by_run_or_client(run_id)
        if aurora_rows:
            rows = aurora_rows
    except Exception as a_exc:
        logger.warning("Aurora query of einvoice_recon_results failed, falling back to Supabase: %s", a_exc)

    if rows is None:
        sb = get_supabase()
        res = (
            sb.table("einvoice_recon_results")
            .select("*")
            .eq("run_id", run_id)
            .execute()
        )
        rows = res.data or []
        if not rows:
            # Check if run_id is actually an id or client_gstin_id
            res_by_client = (
                sb.table("einvoice_recon_results")
                .select("*")
                .eq("client_gstin_id", run_id)
                .order("created_at", desc=True)
                .limit(200)
                .execute()
            )
            rows = res_by_client.data or []

    if not rows:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No E-Invoice reconciliation results found for run_id: {run_id}",
        )

    # Verify access to client_gstin_id
    client_id = rows[0].get("client_gstin_id")
    if client_id:
        _assert_access(client_id, user_id)

    formatted_results = []
    for r in rows:
        details = r.get("details") or {}
        formatted_results.append(
            {
                "id": r.get("id"),
                "run_id": r.get("run_id"),
                "invoice_number": r.get("invoice_number"),
                "irn": r.get("irn"),
                "irn_status": r.get("irn_status"),
                "category": r.get("category"),
                "book_value": float(r.get("book_value") or 0.0),
                "einvoice_value": float(r.get("einvoice_value") or 0.0),
                "gstin": details.get("gstin", ""),
                "invoice_date": details.get("invoice_date"),
                "value_difference": float(details.get("value_difference") or 0.0),
                "ack_number": details.get("ack_number"),
                "ack_date": details.get("ack_date"),
                "decision_what": details.get("decision_what"),
                "decision_why": details.get("decision_why"),
                "decision_next": details.get("decision_next"),
                "decision_rule": details.get("decision_rule"),
                "verification_source": r.get("verification_source") or details.get("verification_source"),
                "verified_at": r.get("verified_at"),
                "created_at": r.get("created_at"),
            }
        )

    summary = {
        "total_records": len(formatted_results),
        "matched_count": sum(1 for r in formatted_results if r["category"] == "MATCHED"),
        "irn_missing_count": sum(1 for r in formatted_results if r["category"] == "IRN_MISSING"),
        "irn_cancelled_count": sum(1 for r in formatted_results if r["category"] == "IRN_CANCELLED"),
        "extra_irn_count": sum(1 for r in formatted_results if r["category"] == "EXTRA_IRN"),
        "value_mismatch_count": sum(1 for r in formatted_results if r["category"] == "VALUE_MISMATCH"),
    }

    return {
        "run_id": run_id,
        "client_id": client_id,
        "period": rows[0].get("period"),
        "summary": summary,
        "results": formatted_results,
    }


class SaveCredentialsBody(BaseModel):
    username: str = Field(..., description="e-Invoice portal username")
    password: str = Field(..., description="e-Invoice portal password")


class BatchVerifyBody(BaseModel):
    result_ids: list[str] = Field(..., description="List of result_ids to verify")


@router.get("/credentials/{client_id}")
async def get_credentials_status(
    client_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Check if e-Invoice portal credentials exist for a client GSTIN."""
    sb = get_supabase()
    _assert_access(client_id, user_id)

    row = None
    try:
        from app.repositories.integrations import get_integrations_repository
        repo = get_integrations_repository()
        row = repo.get_client_einvoice_credential(client_id)
    except Exception as a_exc:
        logger.warning("Aurora get_client_einvoice_credential failed: %s", a_exc)

    if not row:
        res = (
            sb.table("client_einvoice_credentials")
            .select("id, client_gstin_id, einvoice_username, updated_at")
            .eq("client_gstin_id", client_id)
            .limit(1)
            .execute()
        )
        if res.data:
            row = res.data[0]

    if row:
        up_at = row.get("updated_at")
        if hasattr(up_at, "isoformat"):
            up_at = up_at.isoformat()
        return {
            "has_credentials": True,
            "username": row.get("einvoice_username"),
            "updated_at": up_at,
        }

    return {"has_credentials": False, "username": None, "updated_at": None}


@router.post("/credentials/{client_id}")
async def save_credentials(
    client_id: str,
    body: SaveCredentialsBody,
    user_id: str = Depends(get_current_user_id),
):
    """Store or update encrypted e-Invoice credentials for a client GSTIN."""
    sb = get_supabase()
    from app.services.einvoice_verification import upsert_client_credentials

    try:
        return upsert_client_credentials(
            sb=sb,
            client_gstin_id=client_id,
            username=body.username,
            password=body.password,
            user_id=user_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to save e-Invoice credentials for client_id=%s", client_id)
        if "policy" in str(exc).lower() or "not allowed" in str(exc).lower() or "relation" in str(exc).lower():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Database table 'client_einvoice_credentials' not found in Supabase. Please apply the SQL migration script in Supabase SQL Editor.",
            ) from exc
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save credentials: {exc}",
        ) from exc


@router.post("/results/{result_id}/verify")
async def verify_single_result(
    result_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Trigger live IRP verification for a single IRN_MISSING result record."""
    sb = get_supabase()
    from app.services.einvoice_verification import verify_irn_missing_row

    try:
        return verify_irn_missing_row(sb=sb, result_id=result_id, user_id=user_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to verify result_id=%s on IRP", result_id)
        if "policy" in str(exc).lower() or "not allowed" in str(exc).lower() or "relation" in str(exc).lower():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Database table 'client_einvoice_credentials' not found in Supabase. Please apply the SQL migration script in Supabase SQL Editor.",
            ) from exc
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Live IRP verification failed: {exc}",
        ) from exc


@router.post("/results/batch-verify")
async def verify_batch_results(
    body: BatchVerifyBody,
    user_id: str = Depends(get_current_user_id),
):
    """Trigger sequential live IRP verification for a batch of IRN_MISSING records."""
    sb = get_supabase()
    from app.services.einvoice_verification import verify_irn_missing_batch

    try:
        return verify_irn_missing_batch(sb=sb, result_ids=body.result_ids, user_id=user_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to batch verify results on IRP")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch verification failed: {exc}",
        ) from exc

