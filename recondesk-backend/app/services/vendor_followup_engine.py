"""Automated Vendor Follow-up & Compliance Escalation Engine.

Detects high-risk vendors (missing GSTR-2B, unfiled GSTR-1, Rule 37 overdue payment risks),
pre-formats 1-click WhatsApp deep links & formal email notices, and tracks dispatch logs.
"""

from __future__ import annotations

import logging
from urllib.parse import quote
from typing import Any, Optional

from supabase import Client

logger = logging.getLogger(__name__)


def _ensure_table_exists(conn: Any) -> None:
    import sqlalchemy as sa
    conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS public.vendor_followup_logs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
                supplier_gstin TEXT NOT NULL,
                supplier_name TEXT,
                vendor_phone TEXT,
                vendor_email TEXT,
                channel TEXT NOT NULL DEFAULT 'WHATSAPP',
                template_type TEXT NOT NULL DEFAULT 'POLITE_REMINDER',
                invoices_count INT NOT NULL DEFAULT 1,
                at_risk_itc_rupees NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
                status TEXT NOT NULL DEFAULT 'SENT',
                notes TEXT,
                dispatched_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
                dispatched_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
                work_item_id UUID REFERENCES public.itc_work_items(id) ON DELETE SET NULL,
                message_body TEXT
            );
            ALTER TABLE public.vendor_followup_logs
                ADD COLUMN IF NOT EXISTS work_item_id UUID REFERENCES public.itc_work_items(id) ON DELETE SET NULL,
                ADD COLUMN IF NOT EXISTS message_body TEXT;
            CREATE INDEX IF NOT EXISTS idx_vendor_followup_client_supplier
                ON public.vendor_followup_logs(client_gstin_id, supplier_gstin);
            CREATE INDEX IF NOT EXISTS idx_vendor_followup_work_item
                ON public.vendor_followup_logs(work_item_id);
            """
        )
    )
    conn.commit()


def get_vendor_risk_summaries(sb: Client, client_gstin_id: str) -> list[dict[str, Any]]:
    """Fetch high-risk vendor summary list for a client with total at-risk ITC."""
    vendor_map: dict[str, dict[str, Any]] = {}

    # 1. Fetch supplier compliance summary for this client's firm
    try:
        res = (
            sb.table("supplier_compliance_summary")
            .select("*")
            .execute()
        )
        for row in res.data or []:
            c_ids = row.get("client_gstin_ids") or []
            if client_gstin_id in c_ids or not c_ids:
                gstin = str(row.get("supplier_gstin_normalized") or "").strip().upper()
                if gstin:
                    vendor_map[gstin] = {
                        "supplier_gstin": gstin,
                        "supplier_name": str(row.get("supplier_trade_name") or gstin).strip(),
                        "vendor_phone": str(row.get("vendor_phone") or "").strip(),
                        "vendor_email": str(row.get("vendor_email") or "").strip(),
                        "total_invoices": int(row.get("total_invoices") or 0),
                        "mismatch_count": int(row.get("mismatch_invoice_count") or 0),
                        "rule37_count": int(row.get("rule37_open_count") or 0),
                        "rule37_at_risk_rupees": round(float(row.get("rule37_at_risk_paise") or 0) / 100.0, 2),
                        "at_risk_itc_rupees": round(float(row.get("rule37_at_risk_paise") or 0) / 100.0, 2),
                        "risk_score": int(row.get("risk_score") or 0),
                        "last_followup_at": None,
                        "followup_count": 0,
                    }
    except Exception as exc:
        logger.warning("Error fetching supplier_compliance_summary: %s", exc)

    # 2. Fetch Rule 37 overdue actions for invoice details
    try:
        r37_res = (
            sb.table("rule37_actions")
            .select("supplier_gstin, supplier_name, invoice_number, at_risk_itc_paise, action_status")
            .eq("client_gstin_id", client_gstin_id)
            .execute()
        )
        for r in r37_res.data or []:
            gstin = str(r.get("supplier_gstin") or "").strip().upper()
            if not gstin:
                continue
            amt = round((float(r.get("at_risk_itc_paise") or 0)) / 100.0, 2)
            if gstin not in vendor_map:
                vendor_map[gstin] = {
                    "supplier_gstin": gstin,
                    "supplier_name": str(r.get("supplier_name") or gstin).strip(),
                    "vendor_phone": "",
                    "vendor_email": "",
                    "total_invoices": 1,
                    "mismatch_count": 1,
                    "rule37_count": 1,
                    "rule37_at_risk_rupees": amt,
                    "at_risk_itc_rupees": amt,
                    "risk_score": 85,
                    "last_followup_at": None,
                    "followup_count": 0,
                }
            else:
                vendor_map[gstin]["rule37_count"] += 1
                vendor_map[gstin]["rule37_at_risk_rupees"] = round(vendor_map[gstin]["rule37_at_risk_rupees"] + amt, 2)
                vendor_map[gstin]["at_risk_itc_rupees"] = round(vendor_map[gstin]["at_risk_itc_rupees"] + amt, 2)
    except Exception as exc:
        logger.warning("Error fetching rule37_actions for vendor follow-up: %s", exc)

    # 3. Attach past follow-up dispatch history
    try:
        logs = get_followup_history(sb, client_gstin_id)
        for log in logs:
            gstin = str(log.get("supplier_gstin") or "").strip().upper()
            if gstin in vendor_map:
                vendor_map[gstin]["followup_count"] += 1
                if not vendor_map[gstin]["last_followup_at"]:
                    vendor_map[gstin]["last_followup_at"] = log.get("dispatched_at")
    except Exception as exc:
        logger.warning("Error attaching follow-up history: %s", exc)

    result = list(vendor_map.values())
    result.sort(key=lambda x: (x["at_risk_itc_rupees"], x["risk_score"]), reverse=True)
    return result


def generate_whatsapp_payload(
    supplier_gstin: str,
    supplier_name: str,
    vendor_phone: str,
    at_risk_itc_rupees: float,
    template_type: str = "POLITE_REMINDER",
) -> dict[str, str]:
    """Generate pre-formatted WhatsApp wa.me deep link with encoded message text."""
    phone_clean = "".join(c for c in vendor_phone if c.isdigit())
    if len(phone_clean) == 10:
        phone_clean = f"91{phone_clean}"

    sname = supplier_name or supplier_gstin

    if template_type == "RULE37_NOTICE":
        message = (
            f"⚠️ *URGENT: Rule 37 Overdue Tax Risk Notice*\n\n"
            f"Dear {sname} ({supplier_gstin}),\n\n"
            f"Our records indicate overdue unpaid invoices older than 180 days with total ITC exposure of *₹{at_risk_itc_rupees:,.2f}*.\n\n"
            f"Under Rule 37 of CGST Rules, failure to reconcile or settle payment will force an immediate ITC reversal with 18% interest.\n\n"
            f"Please share payment clearance confirmation or updated GSTR-1 filing status urgently.\n\n"
            f"— Finance & Tax Team, ReconDesk"
        )
    elif template_type == "FINAL_ESCALATION":
        message = (
            f"🚨 *FINAL NOTICE: Tax Compliance & Payment Escalation*\n\n"
            f"Dear {sname} ({supplier_gstin}),\n\n"
            f"This is a final escalation regarding unfiled GSTR-1 invoices / unpaid bills totaling *₹{at_risk_itc_rupees:,.2f}*.\n\n"
            f"Your GST compliance score has dropped significantly, placing upcoming vendor payments on administrative hold.\n\n"
            f"Please file your pending GSTR-1 immediately to avoid legal recovery and vendor block.\n\n"
            f"— Finance & Audit Desk"
        )
    elif template_type == "MISSING_2B_REQUEST":
        message = (
            f"📄 *URGENT: Invoices Missing from GSTR-2B*\n\n"
            f"Dear {sname} ({supplier_gstin}),\n\n"
            f"Invoices totaling *₹{at_risk_itc_rupees:,.2f}* are booked in our Purchase Register but are missing from your GSTR-1 / our GSTR-2B.\n\n"
            f"Under Section 16(2)(aa) of the CGST Act, our input tax credit is blocked until these appear in GSTR-2B.\n\n"
            f"Kindly upload these invoices in your upcoming GSTR-1 or provide filing confirmation.\n\n"
            f"— Finance & Tax Team, ReconDesk"
        )
    elif template_type == "VALUE_MISMATCH_VERIFICATION":
        message = (
            f"🔍 *Notice: Tax / Value Mismatch Verification*\n\n"
            f"Dear {sname} ({supplier_gstin}),\n\n"
            f"We identified a tax discrepancy of *₹{at_risk_itc_rupees:,.2f}* between our purchase records and your GSTR-1 return.\n\n"
            f"Please verify invoice numbers, taxable values, and GST rates, and issue an amendment or credit/debit note if needed.\n\n"
            f"— Finance & Tax Team, ReconDesk"
        )
    else:
        message = (
            f"📋 *GST Reconciliation & Invoice Follow-Up*\n\n"
            f"Dear {sname} ({supplier_gstin}),\n\n"
            f"This is a gentle reminder regarding pending GSTR-1 filings / invoice reconciliations with total ITC amount of *₹{at_risk_itc_rupees:,.2f}*.\n\n"
            f"Kindly upload these invoices in your upcoming GSTR-1 so we can claim input tax credit smoothly.\n\n"
            f"Thank you for your prompt cooperation!\n\n"
            f"— ReconDesk Automated Tax Hub"
        )

    encoded_msg = quote(message)
    wa_url = f"https://wa.me/{phone_clean}?text={encoded_msg}" if phone_clean else f"https://wa.me/?text={encoded_msg}"

    return {
        "supplier_gstin": supplier_gstin,
        "supplier_name": sname,
        "vendor_phone": phone_clean,
        "template_type": template_type,
        "message_text": message,
        "whatsapp_url": wa_url,
    }


def generate_email_template(
    supplier_gstin: str,
    supplier_name: str,
    at_risk_itc_rupees: float,
    template_type: str = "POLITE_REMINDER",
) -> dict[str, str]:
    """Generate formal HTML vendor email notice payload."""
    sname = supplier_name or supplier_gstin

    if template_type == "RULE37_NOTICE":
        subject = f"URGENT: Rule 37 Overdue Tax Notice for {supplier_gstin} [₹{at_risk_itc_rupees:,.2f}]"
        detail_para = "Our records indicate overdue unpaid invoices older than 180 days with total ITC exposure of <strong>₹" + f"{at_risk_itc_rupees:,.2f}" + "</strong>. Under Rule 37 of CGST Rules, failure to reconcile or settle payment will force an immediate ITC reversal with 18% interest."
    elif template_type == "FINAL_ESCALATION":
        subject = f"Notice: GST Reconciliation - FINAL ESCALATION for {supplier_gstin} [₹{at_risk_itc_rupees:,.2f}]"
        detail_para = "This is a final escalation regarding unfiled GSTR-1 invoices / unpaid bills totaling <strong>₹" + f"{at_risk_itc_rupees:,.2f}" + "</strong>. Your GST compliance score has dropped significantly, placing upcoming vendor payments on administrative hold."
    elif template_type == "MISSING_2B_REQUEST":
        subject = f"Action Required: Invoices Missing from GSTR-2B for {supplier_gstin} [₹{at_risk_itc_rupees:,.2f}]"
        detail_para = "Invoices totaling <strong>₹" + f"{at_risk_itc_rupees:,.2f}" + "</strong> are booked in our purchase records but are missing from your GSTR-1 / our GSTR-2B. Under Section 16(2)(aa) of CGST Act, our input tax credit is blocked until these are furnished."
    elif template_type == "VALUE_MISMATCH_VERIFICATION":
        subject = f"Notice: Tax Value Discrepancy Verification for {supplier_gstin} [₹{at_risk_itc_rupees:,.2f}]"
        detail_para = "We identified a tax discrepancy of <strong>₹" + f"{at_risk_itc_rupees:,.2f}" + "</strong> between our purchase records and your GSTR-1 filing. Kindly reconcile invoice taxable values and GST rates and file amendments if necessary."
    else:
        subject = f"Notice: GST Reconciliation & ITC Compliance for {supplier_gstin} [₹{at_risk_itc_rupees:,.2f}]"
        detail_para = "We are currently conducting our period end GST audit and identified unmatched invoices / Rule 37 payment exposures totaling <strong>₹" + f"{at_risk_itc_rupees:,.2f}" + "</strong>."

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; color: #111827; line-height: 1.6;">
        <h2 style="color: #4f46e5;">GST Compliance & ITC Reconciliation Notice</h2>
        <p>Dear <strong>{sname}</strong> (GSTIN: <code>{supplier_gstin}</code>),</p>
        <p>{detail_para}</p>
        <div style="background-color: #f3f4f6; border-left: 4px solid #4f46e5; padding: 12px 16px; margin: 16px 0; border-radius: 4px;">
            <strong>Template Category:</strong> {template_type.replace('_', ' ').title()}<br/>
            <strong>Total ITC at Stake:</strong> ₹{at_risk_itc_rupees:,.2f}
        </div>
        <p>Kindly verify your GSTR-1 filings and invoice clearance status so we can reconcile input tax credit without statutory exposure.</p>
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;" />
        <p style="font-size: 12px; color: #6b7280;">Automated via ReconDesk Compliance Engine.</p>
    </div>
    """

    return {
        "subject": subject,
        "html_body": html_body,
        "supplier_gstin": supplier_gstin,
    }


def log_followup_action(
    sb: Client,
    client_gstin_id: str,
    supplier_gstin: str,
    supplier_name: str,
    vendor_phone: str,
    vendor_email: str,
    channel: str,
    template_type: str,
    at_risk_itc_rupees: float,
    dispatched_by: Optional[str] = None,
    work_item_id: Optional[str] = None,
    message_body: Optional[str] = None,
) -> dict[str, Any]:
    """Persist follow-up dispatch event into vendor_followup_logs and record timeline event if work_item_id is provided."""
    status_label = "LINK_OPENED" if channel == "WHATSAPP" else "NOTICE_GENERATED"
    payload: dict[str, Any] = {
        "client_gstin_id": client_gstin_id,
        "supplier_gstin": supplier_gstin,
        "supplier_name": supplier_name,
        "vendor_phone": vendor_phone,
        "vendor_email": vendor_email,
        "channel": channel,
        "template_type": template_type,
        "at_risk_itc_rupees": at_risk_itc_rupees,
        "status": status_label,
    }
    if dispatched_by:
        payload["dispatched_by"] = dispatched_by
    if work_item_id:
        payload["work_item_id"] = work_item_id
    if message_body:
        payload["message_body"] = message_body

    created_record = None
    try:
        res = sb.table("vendor_followup_logs").insert(payload).execute()
        if res.data:
            created_record = res.data[0]
    except Exception as exc:
        logger.warning("Supabase insert failed for vendor_followup_logs, using direct SQL fallback: %s", exc)
        try:
            from app.config import get_settings
            import sqlalchemy as sa
            s = get_settings()
            db_url = s.SUPABASE_DATABASE_URL or s.DATABASE_URL
            if db_url:
                eng = sa.create_engine(db_url)
                with eng.connect() as conn:
                    _ensure_table_exists(conn)
                    conn.execute(
                        sa.text(
                            """
                            INSERT INTO public.vendor_followup_logs
                            (client_gstin_id, supplier_gstin, supplier_name, vendor_phone, vendor_email, channel, template_type, at_risk_itc_rupees, status, work_item_id, message_body)
                            VALUES (:cid, :sgstin, :sname, :phone, :email, :chan, :ttype, :amt, :stat, :wid, :mbody)
                            """
                        ),
                        {
                            "cid": client_gstin_id,
                            "sgstin": supplier_gstin,
                            "sname": supplier_name,
                            "phone": vendor_phone,
                            "email": vendor_email,
                            "chan": channel,
                            "ttype": template_type,
                            "amt": at_risk_itc_rupees,
                            "stat": status_label,
                            "wid": work_item_id,
                            "mbody": message_body,
                        },
                    )
                    conn.commit()
                    eng.dispose()
        except Exception as sql_exc:
            logger.error("Direct SQL fallback failed for log_followup_action: %s", sql_exc)

    # If linked to a work item, record COMMUNICATION_DISPATCHED in itc_work_item_events
    if work_item_id:
        try:
            from datetime import datetime, timezone
            ev_payload = {
                "work_item_id": work_item_id,
                "event_type": "COMMUNICATION_DISPATCHED",
                "actor_id": dispatched_by,
                "note": f"Dispatched {template_type.replace('_', ' ')} notice to {supplier_name or supplier_gstin} via {channel}.",
                "metadata": {
                    "channel": channel,
                    "template_type": template_type,
                    "recipient": vendor_email if channel == "EMAIL" else vendor_phone,
                    "at_risk_itc_rupees": at_risk_itc_rupees,
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            sb.table("itc_work_item_events").insert(ev_payload).execute()
        except Exception as ev_exc:
            logger.warning("Failed to record COMMUNICATION_DISPATCHED event for work item %s: %s", work_item_id, ev_exc)

    return created_record or payload


def get_work_item_followup_history(
    sb: Client,
    client_gstin_id: str,
    work_item_id: str,
) -> list[dict[str, Any]]:
    """Retrieve follow-up dispatch history explicitly linked to a work item."""
    try:
        res = (
            sb.table("vendor_followup_logs")
            .select("*")
            .eq("client_gstin_id", client_gstin_id)
            .eq("work_item_id", work_item_id)
            .order("dispatched_at", desc=True)
            .limit(100)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.warning("Failed to fetch work item followup history: %s", exc)
        return []


def get_followup_history(sb: Client, client_gstin_id: str) -> list[dict[str, Any]]:
    """Retrieve follow-up dispatch logs for a client."""
    try:
        res = (
            sb.table("vendor_followup_logs")
            .select("*")
            .eq("client_gstin_id", client_gstin_id)
            .order("dispatched_at", desc=True)
            .limit(100)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.warning("PostgREST query failed for vendor_followup_logs: %s", exc)
        try:
            from app.config import get_settings
            import sqlalchemy as sa
            s = get_settings()
            db_url = s.SUPABASE_DATABASE_URL or s.DATABASE_URL
            if db_url:
                eng = sa.create_engine(db_url)
                with eng.connect() as conn:
                    _ensure_table_exists(conn)
                    res = conn.execute(
                        sa.text(
                            "SELECT * FROM public.vendor_followup_logs WHERE client_gstin_id = :cid ORDER BY dispatched_at DESC LIMIT 100"
                        ),
                        {"cid": client_gstin_id},
                    )
                    rows = [dict(r) for r in res.mappings().all()]
                    eng.dispose()
                    return rows
        except Exception:
            pass
        return []
