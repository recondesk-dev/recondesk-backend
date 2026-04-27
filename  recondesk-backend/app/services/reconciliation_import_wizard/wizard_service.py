"""Persistence and domain logic for the import wizard."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import time
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import boto3
import pandas as pd
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import HTTPException, status
from supabase import Client

from app.config import settings
from app.database import get_supabase
from app.services.reconciliation_import_wizard import state_machine

_log = logging.getLogger(__name__)

T_RUNS = "reconciliation_import_runs"
T_AUDIT = "reconciliation_import_run_audit_log"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

STANDARD_FIELDS = [
    "gstin",
    "invoice_number",
    "invoice_date",
    "taxable_value",
    "total_tax",
    "supplier_name",
]


def _r2():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def audit(sb: Client, run_id: str, user_id: str, event: str, detail: Optional[dict] = None) -> None:
    sb.table(T_AUDIT).insert(
        {
            "run_id": run_id,
            "user_id": user_id,
            "event": event,
            "detail": detail or {},
        }
    ).execute()


def transition_run(
    sb: Client,
    run_id: str,
    user_id: str,
    new_status: str,
    *,
    extra_patch: Optional[dict] = None,
    audit_event: Optional[str] = None,
    audit_detail: Optional[dict] = None,
) -> dict:
    row = (
        sb.table(T_RUNS)
        .select("*")
        .eq("id", run_id)
        .single()
        .execute()
    ).data
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    old = row["status"]
    try:
        state_machine.assert_transition_allowed(old, new_status)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    patch = {"status": new_status, "updated_at": datetime.now(timezone.utc).isoformat()}
    if extra_patch:
        patch.update(extra_patch)
    res = sb.table(T_RUNS).update(patch).eq("id", run_id).execute()
    data = (res.data or [row])[0]
    audit(
        sb,
        run_id,
        user_id,
        audit_event or f"status_{new_status}",
        {"from": old, "to": new_status, **(audit_detail or {})},
    )
    return data


def delete_r2_keys(keys: list[str]) -> None:
    if not keys:
        return
    c = _r2()
    for k in keys:
        if not k:
            continue
        try:
            c.delete_object(Bucket=settings.R2_BUCKET_NAME, Key=k)
        except ClientError as e:
            _log.warning("R2 delete failed %s: %s", k, e)


def verify_r2_sha256(key: str, expected_hex: str, max_bytes: int = MAX_UPLOAD_BYTES) -> int:
    c = _r2()
    try:
        o = c.get_object(Bucket=settings.R2_BUCKET_NAME, Key=key)
    except ClientError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Object not found in storage") from e
    body = o["Body"].read()
    if len(body) > max_bytes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File too large")
    digest = hashlib.sha256(body).hexdigest()
    if digest.lower() != (expected_hex or "").lower():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File hash mismatch")
    return len(body)


def presign_put(key: str, content_type: str, expires: int = 3600) -> str:
    c = _r2()
    return c.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.R2_BUCKET_NAME,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=expires,
    )


def fetch_run(sb: Client, run_id: str) -> dict:
    r = sb.table(T_RUNS).select("*").eq("id", run_id).single().execute()
    if not r.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return r.data


def assert_client_access(sb: Client, client_id: str, user_id: str) -> dict:
    c = (
        sb.table("client_gstins")
        .select("id, firm_owner_id, gstin, trade_name")
        .eq("id", client_id)
        .single()
        .execute()
    ).data
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client not found")
    if str(c.get("firm_owner_id")) != str(user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied")
    return c


def another_processing_run(sb: Client, client_id: str, period_iso: str, exclude_run_id: str) -> bool:
    q = (
        sb.table(T_RUNS)
        .select("id")
        .eq("client_id", client_id)
        .eq("period", period_iso)
        .eq("status", "processing")
        .neq("id", exclude_run_id)
        .limit(1)
        .execute()
    )
    return bool(q.data)


def run_sanity_gstr2b_json(raw: bytes) -> tuple[list[dict[str, Any]], int]:
    """Return checks list per API contract and parsed top-level record count."""
    checks: list[dict[str, Any]] = []
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        checks.append(
            {
                "id": "json_parse",
                "label": "Valid JSON",
                "status": "error",
                "detail": "File is not valid JSON.",
                "affected_records": [],
            }
        )
        return checks, 0

    checks.append(
        {
            "id": "json_parse",
            "label": "Valid JSON",
            "status": "pass",
            "detail": "",
            "affected_records": [],
        }
    )

    # Minimal structure probe (portal exports vary)
    if isinstance(data, dict):
        b2b = data.get("data") or data.get("b2b") or data
        rows = b2b if isinstance(b2b, list) else []
    elif isinstance(data, list):
        rows = data
    else:
        rows = []

    record_count = len(rows) if rows else 0

    if not rows:
        checks.append(
            {
                "id": "records",
                "label": "Records present",
                "status": "warning",
                "detail": "No B2B records found in expected shape; verify portal export.",
                "affected_records": [],
            }
        )
    else:
        checks.append(
            {
                "id": "records",
                "label": "Records present",
                "status": "pass",
                "detail": f"{record_count} top-level entries parsed.",
                "affected_records": [],
            }
        )

    return checks, record_count


def _read_pr_dataframe(raw: bytes, filename: str) -> pd.DataFrame:
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else "csv"
    bio = io.BytesIO(raw)
    if ext == "csv":
        return pd.read_csv(bio, dtype=str)
    if ext == "xls":
        try:
            return pd.read_excel(bio, dtype=str, engine="xlrd")
        except Exception:  # noqa: BLE001
            return pd.read_excel(bio, dtype=str, engine="openpyxl")
    return pd.read_excel(bio, dtype=str, engine="openpyxl")


def detect_pr_columns_from_r2(key: str, filename: str) -> tuple[list[dict], list[str], int]:
    c = _r2()
    o = c.get_object(Bucket=settings.R2_BUCKET_NAME, Key=key)
    raw = o["Body"].read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File too large")
    df_full = _read_pr_dataframe(raw, filename)
    row_count = int(len(df_full))
    df = df_full.head(50)
    headers = [str(h).strip() for h in df.columns.tolist()]
    columns_out: list[dict[str, Any]] = []

    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    header_norms = {h: norm(h) for h in headers}

    synonyms = {
        "gstin": ["gstin", "gst", "suppliergstin", "ctin", "vendorgstin"],
        "invoice_number": ["invoiceno", "invoice_no", "invoicenumber", "docno", "documentno"],
        "invoice_date": ["invoicedate", "date", "documentdate"],
        "taxable_value": ["taxable", "taxableval", "taxablevalue", "assessable"],
        "total_tax": ["tax", "totaltax", "igst", "taxamount"],
        "supplier_name": ["supplier", "vendor", "tradename", "suppliername"],
    }

    for field in STANDARD_FIELDS:
        detected: Optional[str] = None
        confidence = "not_found"
        syns = synonyms.get(field, [field.replace("_", "")])
        for h in headers:
            hn = header_norms.get(h, "")
            for syn in syns:
                if syn in hn or hn in syn:
                    detected = h
                    confidence = "high"
                    break
            if detected:
                break
        samples: list[str] = []
        if detected and detected in df.columns:
            ser = df[detected].dropna().head(3)
            samples = [str(x) for x in ser.tolist()]
        columns_out.append(
            {
                "standard_field": field,
                "detected_column": detected,
                "confidence": confidence,
                "sample_values": samples,
                "confirmed": confidence == "high",
            }
        )

    return columns_out, headers, row_count


def schedule_processing_job(run_id: str) -> None:
    """Background progress simulation; replace with Celery reconciliation task."""

    def _work() -> None:
        sb = get_supabase()
        row = fetch_run(sb, run_id)
        actor = str(row.get("created_by") or row.get("firm_owner_id") or "")
        if not actor:
            actor = "00000000-0000-0000-0000-000000000000"
        steps = [
            (15, "Reading GSTR-2B…"),
            (40, "Reading purchase register…"),
            (70, "Matching invoices…"),
            (95, "Finalising…"),
            (100, "Complete"),
        ]
        try:
            for pct, msg in steps:
                time.sleep(1.5)
                sb.table(T_RUNS).update(
                    {
                        "progress_pct": pct,
                        "status_message": msg,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                ).eq("id", run_id).execute()
            transition_run(
                sb,
                run_id,
                actor,
                "complete",
                extra_patch={
                    "progress_pct": 100,
                    "status_message": "Complete",
                },
                audit_event="processing_complete",
                audit_detail={},
            )
        except Exception as e:  # noqa: BLE001
            _log.exception("wizard job failed")
            try:
                row2 = fetch_run(sb, run_id)
                actor2 = str(row2.get("created_by") or row2.get("firm_owner_id") or actor)
                transition_run(
                    sb,
                    run_id,
                    actor2,
                    "error",
                    extra_patch={
                        "error_detail": str(e),
                        "status_message": "Processing failed",
                    },
                    audit_event="processing_error",
                    audit_detail={"error": str(e)},
                )
            except Exception:  # noqa: BLE001
                try:
                    sb.table(T_RUNS).update(
                        {
                            "status": "error",
                            "error_detail": str(e),
                            "status_message": "Processing failed",
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }
                    ).eq("id", run_id).execute()
                except Exception:  # noqa: BLE001
                    pass

    import threading

    t = threading.Thread(target=_work, daemon=True)
    t.start()
