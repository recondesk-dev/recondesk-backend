"""FastAPI Router for Automated Vendor Follow-up Hub."""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict

from app.auth import get_current_active_user
from app.database import get_supabase
from app.services import vendor_followup_engine as vf_svc
from app.services.firm_access import list_accessible_client_gstin_ids

logger = logging.getLogger(__name__)

router = APIRouter(redirect_slashes=False)
public_router = APIRouter(redirect_slashes=False)


def _assert_client(sb, client_id: str, user_id: str) -> None:
    allowed = list_accessible_client_gstin_ids(sb, {"id": user_id})
    if client_id not in allowed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client GSTIN not found or access denied",
        )


class WhatsAppGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    supplier_gstin: str
    supplier_name: Optional[str] = None
    trade_name: Optional[str] = None
    contact_person: Optional[str] = None
    vendor_phone: Optional[str] = ""
    at_risk_itc_rupees: float = 0.0
    template_type: str = "POLITE_REMINDER"
    custom_template: Optional[str] = None
    portal_url: Optional[str] = None


class EmailGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    supplier_gstin: str
    supplier_name: Optional[str] = None
    trade_name: Optional[str] = None
    contact_person: Optional[str] = None
    at_risk_itc_rupees: float = 0.0
    template_type: str = "POLITE_REMINDER"
    custom_template: Optional[str] = None
    portal_url: Optional[str] = None


class LogDispatchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    supplier_gstin: str
    supplier_name: Optional[str] = None
    vendor_phone: Optional[str] = ""
    vendor_email: Optional[str] = ""
    channel: str = "WHATSAPP"
    template_type: str = "POLITE_REMINDER"
    at_risk_itc_rupees: float = 0.0
    work_item_id: Optional[str] = None
    message_body: Optional[str] = None
    token: Optional[str] = None
    expires_at: Optional[str] = None
    invoices_snapshot: Optional[list[dict[str, Any]]] = None


class GenerateTokenRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    supplier_gstin: str
    supplier_name: Optional[str] = None
    vendor_phone: Optional[str] = ""
    vendor_email: Optional[str] = ""
    at_risk_itc_rupees: float = 0.0
    template_type: str = "POLITE_REMINDER"
    work_item_id: Optional[str] = None
    channel: str = "WHATSAPP"


class UpdateVendorContactRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    vendor_phone: Optional[str] = None
    vendor_email: Optional[str] = None


class VendorPortalResponseRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action: str  # "ALREADY_FILED", "PROMISED_NEXT_CYCLE", "DISPUTED"
    arn_number: Optional[str] = None
    promised_period: Optional[str] = None
    dispute_reason: Optional[str] = None
    attachment_key: Optional[str] = None


@router.get("/clients/{client_id}")
async def list_client_vendor_risk_summaries(
    client_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Fetch high-risk vendor summary list for a client."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, client_id, user_id)

    try:
        vendors = vf_svc.get_vendor_risk_summaries(sb, client_id)
        total_at_risk = round(sum(v["at_risk_itc_rupees"] for v in vendors), 2)
        return {
            "client_gstin_id": client_id,
            "total_high_risk_vendors": len(vendors),
            "total_at_risk_itc_rupees": total_at_risk,
            "vendors": vendors,
        }
    except Exception as exc:
        logger.exception("Failed to fetch vendor risk summaries for client %s: %s", client_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch vendor risk summaries: {exc}",
        ) from exc


@router.post("/clients/{client_id}/generate-whatsapp")
async def generate_whatsapp_link_endpoint(
    client_id: str,
    body: WhatsAppGenerateRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Generate pre-formatted WhatsApp wa.me deep link with encoded message text."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, client_id, user_id)

    return vf_svc.generate_whatsapp_payload(
        supplier_gstin=body.supplier_gstin,
        supplier_name=body.supplier_name,
        trade_name=body.trade_name,
        contact_person=body.contact_person,
        vendor_phone=body.vendor_phone or "",
        at_risk_itc_rupees=body.at_risk_itc_rupees,
        template_type=body.template_type,
        custom_template=body.custom_template,
        portal_url=body.portal_url,
    )


@router.post("/clients/{client_id}/generate-email")
async def generate_email_notice_endpoint(
    client_id: str,
    body: EmailGenerateRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Generate formal HTML vendor email notice payload."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, client_id, user_id)

    return vf_svc.generate_email_template(
        supplier_gstin=body.supplier_gstin,
        supplier_name=body.supplier_name,
        trade_name=body.trade_name,
        contact_person=body.contact_person,
        at_risk_itc_rupees=body.at_risk_itc_rupees,
        template_type=body.template_type,
        custom_template=body.custom_template,
        portal_url=body.portal_url,
    )


@router.post("/clients/{client_id}/generate-token")
async def generate_token_endpoint(
    client_id: str,
    body: GenerateTokenRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Generate or retrieve a secure token for the Tokenized Vendor Action Portal (/v/[token])."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, client_id, user_id)

    return vf_svc.create_or_get_followup_token(
        sb=sb,
        client_gstin_id=client_id,
        supplier_gstin=body.supplier_gstin,
        supplier_name=body.supplier_name,
        vendor_phone=body.vendor_phone or "",
        vendor_email=body.vendor_email or "",
        at_risk_itc_rupees=body.at_risk_itc_rupees,
        work_item_id=body.work_item_id,
        template_type=body.template_type,
        channel=body.channel,
        dispatched_by=user_id,
    )


@router.post("/clients/{client_id}/vendors/{supplier_gstin}/contact")
async def update_vendor_contact_endpoint(
    client_id: str,
    supplier_gstin: str,
    body: UpdateVendorContactRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Persist updated vendor mobile and email into supplier compliance summary & recent logs."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, client_id, user_id)

    return vf_svc.update_vendor_contact_info(
        sb=sb,
        client_gstin_id=client_id,
        supplier_gstin=supplier_gstin,
        vendor_phone=body.vendor_phone,
        vendor_email=body.vendor_email,
    )


@router.post("/clients/{client_id}/dispatch")
async def log_dispatch_endpoint(
    client_id: str,
    body: LogDispatchRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Log follow-up dispatch event into vendor_followup_logs."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, client_id, user_id)

    try:
        logged = vf_svc.log_followup_action(
            sb=sb,
            client_gstin_id=client_id,
            supplier_gstin=body.supplier_gstin,
            supplier_name=body.supplier_name or body.supplier_gstin,
            vendor_phone=body.vendor_phone or "",
            vendor_email=body.vendor_email or "",
            channel=body.channel,
            template_type=body.template_type,
            at_risk_itc_rupees=body.at_risk_itc_rupees,
            dispatched_by=user_id,
            work_item_id=body.work_item_id,
            message_body=body.message_body,
            token=body.token,
            expires_at=body.expires_at,
            invoices_snapshot=body.invoices_snapshot,
        )
        return logged
    except Exception as exc:
        logger.exception("Failed to log vendor follow-up dispatch for client %s: %s", client_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to log follow-up dispatch: {exc}",
        ) from exc


@router.get("/clients/{client_id}/history")
async def fetch_followup_history_endpoint(
    client_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Retrieve follow-up dispatch logs for a client."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")
    _assert_client(sb, client_id, user_id)

    try:
        logs = vf_svc.get_followup_history(sb, client_id)
        return {"client_gstin_id": client_id, "total_logs": len(logs), "logs": logs}
    except Exception as exc:
        logger.exception("Failed to fetch follow-up history for client %s: %s", client_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch follow-up history: {exc}",
        ) from exc


@router.get("/work-items/{work_item_id}/history")
async def fetch_work_item_followup_history_endpoint(
    work_item_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Retrieve follow-up dispatch logs specifically linked to a work item."""
    sb = get_supabase()
    user_id = str(current_user.get("id") or "")

    wi = None
    try:
        from app.repositories.vendor_compliance import get_vendor_compliance_repository
        repo = get_vendor_compliance_repository()
        if repo:
            wi = repo.get_work_item(work_item_id)
    except Exception:
        wi = None

    if not wi:
        wi_res = (
            sb.table("itc_work_items")
            .select("id, client_gstin_id")
            .eq("id", work_item_id)
            .limit(1)
            .execute()
        )
        if not wi_res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Work item not found",
            )
        wi = wi_res.data[0]

    client_id = str(wi["client_gstin_id"])
    _assert_client(sb, client_id, user_id)

    try:
        logs = vf_svc.get_work_item_followup_history(sb, client_id, work_item_id)
        return {
            "work_item_id": work_item_id,
            "client_gstin_id": client_id,
            "total_logs": len(logs),
            "logs": logs,
        }
    except Exception as exc:
        logger.exception("Failed to fetch work item followup history %s: %s", work_item_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch work item followup history: {exc}",
        ) from exc


# ── Public Endpoints for Tokenized Vendor Portal (/v/[token]) ─────────────────

@public_router.get("/{token}")
async def get_vendor_portal_info(token: str):
    """Retrieve vendor portal metadata & missing invoices (Public endpoint - no auth)."""
    sb = get_supabase()
    return vf_svc.get_vendor_portal_data(sb, token)


@public_router.post("/{token}/respond")
async def respond_to_vendor_portal(token: str, body: VendorPortalResponseRequest):
    """Record supplier response: ARN filing confirmation, next cycle promise, or dispute."""
    sb = get_supabase()
    return vf_svc.submit_vendor_portal_response(
        sb=sb,
        token=token,
        action=body.action,
        arn_number=body.arn_number,
        promised_period=body.promised_period,
        dispute_reason=body.dispute_reason,
        attachment_key=body.attachment_key,
    )


@public_router.post("/{token}/upload")
async def upload_vendor_portal_file(token: str, file: UploadFile = File(...)):
    """Upload invoice document copy (PDF/PNG/JPG) for vendor response."""
    sb = get_supabase()
    # verify token exists and is valid
    vf_svc.get_vendor_portal_data(sb, token)

    ALLOWED_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/jpg"}
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF and Image files (PNG, JPG) are allowed.",
        )

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File size exceeds 10 MB limit.",
        )

    import re
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", file.filename or "invoice.pdf")
    storage_key = f"vendor-responses/{token}/{safe_name}"

    try:
        from app.utils.storage import upload_file_raw
        await upload_file_raw(content, storage_key)
    except Exception as exc:
        logger.warning("R2 upload failed, saving fallback reference: %s", exc)
        storage_key = f"local-upload/{token}/{safe_name}"

    return {
        "attachment_key": storage_key,
        "filename": safe_name,
        "file_size": len(content),
    }
