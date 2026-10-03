"""Books-to-E-Invoice Verification Service — per-invoice and batch live lookups against IRP."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status

from app.services.reconciliation_import_wizard import wizard_service as ws
from app.services.sandbox_einvoice_client import (
    EinvoiceAuthError,
    EinvoiceDownError,
    einvoice_client,
)
from app.utils.crypto import decrypt_string, encrypt_string

import uuid

logger = logging.getLogger(__name__)


def _is_gstin_str(s: str) -> bool:
    s = s.strip()
    return len(s) == 15 and s[:2].isdigit()


def _resolve_client_gstin_id(sb: Any, client_id_or_gstin: str) -> str:
    s = (client_id_or_gstin or "").strip()
    if not s or not _is_gstin_str(s):
        return s
    try:
        res = (
            sb.table("client_gstins")
            .select("id")
            .eq("gstin", s.upper())
            .limit(1)
            .execute()
        )
        if res.data and res.data[0].get("id"):
            return str(res.data[0]["id"])
    except Exception as exc:
        logger.warning("Failed to resolve client GSTIN %s to UUID: %s", s, exc)
    return s


def _assert_access(sb: Any, client_gstin_id: str, user_id: Any) -> None:
    uid = getattr(user_id, "id", user_id)
    resolved_id = _resolve_client_gstin_id(sb, client_gstin_id)
    ws.assert_client_access(sb, resolved_id, str(uid or "").strip())


def get_client_credentials(sb: Any, client_gstin_id: str) -> dict[str, Any] | None:
    """Fetch client e-Invoice credentials row, trying Aurora primary first."""
    resolved_id = _resolve_client_gstin_id(sb, client_gstin_id)
    try:
        from app.repositories.integrations import get_integrations_repository
        repo = get_integrations_repository()
        row = repo.get_client_einvoice_credential(resolved_id)
        if row:
            return row
    except Exception as a_exc:
        logger.warning("Aurora get_client_einvoice_credential failed, attempting Supabase fallback: %s", a_exc)

    try:
        res = (
            sb.table("client_einvoice_credentials")
            .select("*")
            .eq("client_gstin_id", resolved_id)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]
    except Exception as exc:
        logger.warning("Supabase get_client_credentials fallback failed: %s", exc)
    return None


def upsert_client_credentials(
    sb: Any,
    client_gstin_id: str,
    username: str,
    password: str,
    user_id: str,
) -> dict[str, Any]:
    """Store or update encrypted e-Invoice credentials for a client GSTIN."""
    resolved_id = _resolve_client_gstin_id(sb, client_gstin_id)
    _assert_access(sb, resolved_id, user_id)
    enc_password = encrypt_string(password.strip())

    aurora_row = None
    try:
        from app.repositories.integrations import get_integrations_repository
        repo = get_integrations_repository()
        aurora_row = repo.upsert_client_einvoice_credential(
            client_gstin_id=resolved_id,
            einvoice_username=username.strip(),
            einvoice_password=enc_password,
        )
    except Exception as a_exc:
        logger.warning("Aurora upsert_client_einvoice_credential failed, falling back to Supabase: %s", a_exc)

    if aurora_row:
        up_at = aurora_row.get("updated_at")
        if hasattr(up_at, "isoformat"):
            up_at = up_at.isoformat()
        return {
            "id": str(aurora_row.get("id")),
            "client_gstin_id": str(aurora_row.get("client_gstin_id")),
            "einvoice_username": aurora_row.get("einvoice_username"),
            "has_credentials": True,
            "updated_at": up_at,
        }

    # Fallback to Supabase
    existing = get_client_credentials(sb, resolved_id)
    now_iso = datetime.now(timezone.utc).isoformat()
    payload = {
        "client_gstin_id": resolved_id,
        "einvoice_username": username.strip(),
        "einvoice_password": enc_password,
        "updated_at": now_iso,
    }

    if existing:
        res = (
            sb.table("client_einvoice_credentials")
            .update(payload)
            .eq("id", existing["id"])
            .execute()
        )
    else:
        payload["created_at"] = now_iso
        res = sb.table("client_einvoice_credentials").insert(payload).execute()

    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to save e-Invoice credentials")

    row = res.data[0]
    return {
        "id": row.get("id"),
        "client_gstin_id": row.get("client_gstin_id"),
        "einvoice_username": row.get("einvoice_username"),
        "has_credentials": True,
        "updated_at": row.get("updated_at"),
    }


def get_valid_session_token(sb: Any, creds_row: dict[str, Any], gstin: str) -> str:
    """Obtain a valid IRP session token, refreshing via Auth API if expired or missing."""
    token = creds_row.get("session_token")
    expiry_str = creds_row.get("session_token_expiry")

    is_valid = False
    if token and expiry_str:
        try:
            exp_dt = datetime.fromisoformat(str(expiry_str).replace("Z", "+00:00"))
            if exp_dt > datetime.now(timezone.utc):
                is_valid = True
        except Exception:
            is_valid = False

    if is_valid and token:
        return str(token)

    username = creds_row["einvoice_username"]
    password = decrypt_string(creds_row["einvoice_password"])

    auth_res = einvoice_client.authenticate_einvoice(gstin, username, password)
    new_token = auth_res["session_token"]
    expiry = auth_res["token_expiry"]

    if isinstance(expiry, int):
        exp_iso = datetime.fromtimestamp(expiry, tz=timezone.utc).isoformat()
    else:
        exp_iso = str(expiry)

    # Cache token in DB (Aurora primary first)
    aurora_cached = False
    try:
        from app.repositories.integrations import get_integrations_repository
        repo = get_integrations_repository()
        client_gstin_id = creds_row.get("client_gstin_id")
        if client_gstin_id:
            exp_datetime = datetime.fromisoformat(exp_iso.replace("Z", "+00:00")) if isinstance(exp_iso, str) else exp_iso
            repo.update_client_einvoice_token(
                client_gstin_id=client_gstin_id,
                session_token=new_token,
                session_token_expiry=exp_datetime,
            )
            aurora_cached = True
    except Exception as a_exc:
        logger.warning("Aurora update_client_einvoice_token failed: %s", a_exc)

    if not aurora_cached and creds_row.get("id"):
        try:
            sb.table("client_einvoice_credentials").update(
                {
                    "session_token": new_token,
                    "session_token_expiry": exp_iso,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            ).eq("id", creds_row["id"]).execute()
        except Exception:
            pass

    return new_token


def verify_irn_missing_row(
    sb: Any,
    result_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Verify a single IRN_MISSING row against IRP e-Invoice API.

    - Upgrades category to MATCHED if found on IRP.
    - Updates verification_source to 'irp_verified_missing' if confirmed missing (404).
    - Raises error on API/auth failure without modifying row.
    """
    row = None
    try:
        from app.repositories.integrations import get_integrations_repository
        repo = get_integrations_repository()
        row = repo.get_einvoice_recon_result_by_id(result_id)
    except Exception as a_exc:
        logger.warning("Aurora lookup of einvoice_recon_results failed: %s", a_exc)

    if not row:
        res = (
            sb.table("einvoice_recon_results")
            .select("*")
            .eq("id", result_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"E-Invoice result record not found: {result_id}")
        row = res.data[0]
    client_id = row.get("client_gstin_id")
    _assert_access(sb, client_id, user_id)

    if row.get("category") != "IRN_MISSING":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Only IRN_MISSING rows can be verified on IRP. Current category: {row.get('category')}",
        )

    creds = get_client_credentials(sb, client_id)
    if not creds:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "e-Invoice credentials not configured for this client. Add credentials in Settings.",
        )

    # Fetch client GSTIN string
    cg_res = sb.table("client_gstins").select("gstin").eq("id", client_id).limit(1).execute()
    if not cg_res.data or not cg_res.data[0].get("gstin"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client GSTIN record not found")

    gstin = cg_res.data[0]["gstin"]
    session_token = get_valid_session_token(sb, creds, gstin)

    inv_num = str(row.get("invoice_number") or "").strip()
    details = row.get("details") or {}
    inv_date = str(details.get("invoice_date") or row.get("period") or "").strip()

    raw_doc_type = str(
        details.get("doc_type")
        or details.get("document_type")
        or details.get("invoice_type")
        or row.get("doc_type")
        or ""
    ).strip().upper()

    if any(k in raw_doc_type for k in ("CREDIT", "CRN", "CDN", "C_N", "CN")):
        doc_type = "CRN"
    elif any(k in raw_doc_type for k in ("DEBIT", "DBN", "DN", "D_N")):
        doc_type = "DBN"
    else:
        doc_type = "INV"

    try:
        irp_data = einvoice_client.get_einvoice_by_doc(
            session_token=session_token,
            gstin=gstin,
            doc_number=inv_num,
            doc_date=inv_date,
            doc_type=doc_type,
        )
    except EinvoiceAuthError as exc:

        # Session token might have expired server-side, invalidate cached token and retry once
        logger.warning("Session token invalid, re-authenticating: %s", exc)
        creds["session_token"] = None
        session_token = get_valid_session_token(sb, creds, gstin)
        irp_data = einvoice_client.get_einvoice_by_doc(
            session_token=session_token,
            gstin=gstin,
            doc_number=inv_num,
            doc_date=inv_date,
            doc_type=doc_type,
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    updated_fields: dict[str, Any] = {
        "verified_at": now_iso,
    }

    if irp_data is not None:
        # Upgraded to MATCHED!
        updated_fields["category"] = "MATCHED"
        updated_fields["irn"] = str(irp_data.get("irn") or irp_data.get("Irn") or "").strip()
        updated_fields["irn_status"] = str(irp_data.get("status") or irp_data.get("IrnStatus") or "Active").strip()
        updated_fields["verification_source"] = "irp_live_lookup"

        # Update details json
        updated_details = dict(details)
        updated_details["ack_number"] = str(irp_data.get("ack_no") or irp_data.get("AckNo") or "").strip()
        updated_details["ack_date"] = str(irp_data.get("ack_date") or irp_data.get("AckDt") or "").strip()
        updated_details["decision_what"] = "Verified on IRP — Active IRN found"
        updated_details["decision_why"] = f"Invoice {inv_num} was missing in uploaded report but confirmed active on IRP live lookup."
        updated_details["decision_next"] = "No action required. Live IRN verified."
        updated_details["decision_rule"] = "EINVOICE_VERIFIED_IRP"
        updated_details["verification_source"] = "irp_live_lookup"
        updated_fields["details"] = updated_details
    else:
        # Confirmed missing from IRP
        updated_fields["verification_source"] = "irp_verified_missing"
        updated_details = dict(details)
        updated_details["decision_why"] = f"Invoice {inv_num} confirmed missing on IRP live portal lookup."
        updated_details["verification_source"] = "irp_verified_missing"
        updated_fields["details"] = updated_details

    res_row = None
    try:
        from app.repositories.integrations import get_integrations_repository
        repo = get_integrations_repository()
        res_row = repo.update_einvoice_recon_result(result_id, updated_fields)
    except Exception as a_exc:
        logger.warning("Aurora update of einvoice_recon_results failed: %s", a_exc)

    if not res_row:
        up_res = (
            sb.table("einvoice_recon_results")
            .update(updated_fields)
            .eq("id", result_id)
            .execute()
        )
        if not up_res.data:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to update verification status")
        res_row = up_res.data[0]
    return {
        "id": res_row.get("id"),
        "invoice_number": res_row.get("invoice_number"),
        "category": res_row.get("category"),
        "irn": res_row.get("irn"),
        "irn_status": res_row.get("irn_status"),
        "verification_source": res_row.get("verification_source"),
        "verified_at": res_row.get("verified_at"),
        "details": res_row.get("details"),
    }


def verify_irn_missing_batch(
    sb: Any,
    result_ids: list[str],
    user_id: str,
) -> dict[str, Any]:
    """Verify multiple IRN_MISSING rows sequentially with rate limiting."""
    verified_count = 0
    matched_upgrades = 0
    errors: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    for idx, rid in enumerate(result_ids):
        if idx > 0:
            time.sleep(1.0)  # 1 request per second rate limit

        try:
            res_item = verify_irn_missing_row(sb, rid, user_id)
            verified_count += 1
            if res_item.get("category") == "MATCHED":
                matched_upgrades += 1
            results.append(res_item)
        except Exception as exc:
            logger.warning("Batch verification failed for result_id %s: %s", rid, exc)
            errors.append({"result_id": rid, "error": str(exc)})

    return {
        "total_requested": len(result_ids),
        "verified_count": verified_count,
        "matched_upgrades": matched_upgrades,
        "errors_count": len(errors),
        "results": results,
        "errors": errors,
    }
