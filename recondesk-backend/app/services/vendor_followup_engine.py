"""Automated Vendor Follow-up & Compliance Escalation Engine.

Detects high-risk vendors (missing GSTR-2B, unfiled GSTR-1, Rule 37 overdue payment risks),
pre-formats 1-click WhatsApp deep links & formal email notices, and tracks dispatch logs.
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from typing import Any, Optional

from fastapi import HTTPException, status
from supabase import Client

logger = logging.getLogger(__name__)


def _get_compliance_repo():
    """Return Aurora compliance repo or None."""
    try:
        from app.repositories.compliance import get_compliance_repository
        return get_compliance_repository()
    except Exception:
        return None


# Standard sanitization fallbacks for missing vendor master tokens
DEFAULT_CONTACT_FALLBACK = "Accounts Payable Team"
DEFAULT_SUPPLIER_NAME_FALLBACK = "Valued Supplier"


def resolve_supplier_display_name(
    supplier_name: Optional[str] = None,
    trade_name: Optional[str] = None,
    supplier_gstin: str = "",
) -> str:
    """Resolve a clean, professional supplier display name avoiding duplicate GSTIN salutations."""
    gstin_clean = (supplier_gstin or "").strip().upper()

    t_clean = str(trade_name or "").strip()
    if t_clean and t_clean.upper() != gstin_clean:
        return t_clean

    s_clean = str(supplier_name or "").strip()
    if s_clean and s_clean.upper() != gstin_clean:
        return s_clean

    return DEFAULT_SUPPLIER_NAME_FALLBACK


def resolve_contact_salutation(
    supplier_name: Optional[str] = None,
    trade_name: Optional[str] = None,
    contact_person: Optional[str] = None,
    supplier_gstin: str = "",
) -> str:
    """Resolve a professional greeting line for email/WhatsApp follow-ups.

    Hierarchy:
    1. If contact person present: 'Dear {contact_person} ({display_name})'
    2. If display name present: 'Dear {display_name} ({gstin})'
    3. If only GSTIN available: 'Dear Valued Supplier ({gstin})'
    """
    gstin_clean = (supplier_gstin or "").strip().upper()
    display_name = resolve_supplier_display_name(supplier_name, trade_name, supplier_gstin)
    contact_clean = str(contact_person or "").strip()

    if contact_clean:
        if display_name != DEFAULT_SUPPLIER_NAME_FALLBACK:
            return f"Dear {contact_clean} ({display_name})"
        if gstin_clean:
            return f"Dear {contact_clean} ({gstin_clean})"
        return f"Dear {contact_clean}"

    if display_name != DEFAULT_SUPPLIER_NAME_FALLBACK:
        return f"Dear {display_name} ({gstin_clean})" if gstin_clean else f"Dear {display_name}"

    return f"Dear Valued Supplier ({gstin_clean})" if gstin_clean else "Dear Valued Supplier"


def sanitize_template_tokens(
    template_text: str,
    context: dict[str, Any],
) -> str:
    """Replace standard template placeholders with sanitized vendor master tokens or safe fallbacks.

    Tokens handled:
    - {supplier_contact}, {contact_person} -> contact_person or 'Accounts Payable Team'
    - {supplier_trade_name}, {trade_name}  -> trade_name or supplier_name or 'Valued Supplier'
    - {supplier_name}, {legal_name}        -> supplier_name or trade_name or 'Valued Supplier'
    - {supplier_gstin}                     -> normalized 15-character uppercase GSTIN
    - {at_risk_itc}, {at_risk_itc_rupees}  -> formatted INR currency string
    - {company_name}, {client_name}        -> client / company name or 'Finance & Tax Team'
    """
    if not template_text:
        return ""

    supplier_gstin = (context.get("supplier_gstin") or "").strip().upper()

    contact_person = str(context.get("contact_person") or context.get("supplier_contact") or "").strip()
    contact_val = contact_person if contact_person else DEFAULT_CONTACT_FALLBACK

    trade_name = str(context.get("trade_name") or context.get("supplier_trade_name") or "").strip()
    supplier_name = str(context.get("supplier_name") or context.get("legal_name") or "").strip()

    # Apply display name resolution hierarchy
    trade_name_val = trade_name if (trade_name and trade_name.upper() != supplier_gstin) else ""
    supplier_name_val = supplier_name if (supplier_name and supplier_name.upper() != supplier_gstin) else ""

    if not trade_name_val:
        trade_name_val = supplier_name_val or DEFAULT_SUPPLIER_NAME_FALLBACK
    if not supplier_name_val:
        supplier_name_val = trade_name_val or DEFAULT_SUPPLIER_NAME_FALLBACK

    # Format at-risk ITC amount
    amt = context.get("at_risk_itc_rupees", 0.0)
    try:
        amt_float = float(amt or 0.0)
        formatted_num = f"{amt_float:,.2f}"
        formatted_amt = f"₹{amt_float:,.2f}"
    except (ValueError, TypeError):
        formatted_num = str(amt)
        formatted_amt = str(amt)

    company_val = str(context.get("company_name") or context.get("client_name") or "Finance & Tax Team").strip()

    replacements = {
        "{supplier_contact}": contact_val,
        "{contact_person}": contact_val,
        "{supplier_trade_name}": trade_name_val,
        "{trade_name}": trade_name_val,
        "{supplier_name}": supplier_name_val,
        "{legal_name}": supplier_name_val,
        "{supplier_gstin}": supplier_gstin or "—",
        "₹{at_risk_itc}": formatted_amt,
        "₹{at_risk_itc_rupees}": formatted_amt,
        "{at_risk_itc}": formatted_amt,
        "{at_risk_itc_rupees}": formatted_num,
        "{company_name}": company_val,
        "{client_name}": company_val,
    }

    result = template_text
    for token, val in replacements.items():
        # Case-insensitive replacement of token
        pattern = re.compile(re.escape(token), re.IGNORECASE)
        result = pattern.sub(val, result)

    # Clean any accidental double currency symbol
    result = result.replace("₹₹", "₹")

    # Scrub any lingering unmapped {token} placeholders to avoid bracket leaks in sent text
    result = re.sub(r"\{[a-zA-Z0-9_-]+\}", "", result)
    return result


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
                message_body TEXT,
                token TEXT UNIQUE,
                viewed_at TIMESTAMPTZ,
                arn_number TEXT,
                promised_period TEXT,
                dispute_reason TEXT,
                attachment_key TEXT,
                expires_at TIMESTAMPTZ,
                invoices_snapshot JSONB,
                response_action TEXT,
                responded_at TIMESTAMPTZ
            );
            ALTER TABLE public.vendor_followup_logs
                ADD COLUMN IF NOT EXISTS work_item_id UUID REFERENCES public.itc_work_items(id) ON DELETE SET NULL,
                ADD COLUMN IF NOT EXISTS message_body TEXT,
                ADD COLUMN IF NOT EXISTS token TEXT UNIQUE,
                ADD COLUMN IF NOT EXISTS viewed_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS arn_number TEXT,
                ADD COLUMN IF NOT EXISTS promised_period TEXT,
                ADD COLUMN IF NOT EXISTS dispute_reason TEXT,
                ADD COLUMN IF NOT EXISTS attachment_key TEXT,
                ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS invoices_snapshot JSONB,
                ADD COLUMN IF NOT EXISTS response_action TEXT,
                ADD COLUMN IF NOT EXISTS responded_at TIMESTAMPTZ;
            CREATE INDEX IF NOT EXISTS idx_vendor_followup_client_supplier
                ON public.vendor_followup_logs(client_gstin_id, supplier_gstin);
            CREATE INDEX IF NOT EXISTS idx_vendor_followup_work_item
                ON public.vendor_followup_logs(work_item_id);
            CREATE INDEX IF NOT EXISTS idx_vendor_followup_token
                ON public.vendor_followup_logs(token);
            """
        )
    )
    conn.commit()


def is_promise_period_overdue(promised_period: Optional[str], dispatched_at: Optional[str] = None) -> bool:
    """Determine if a vendor's committed filing cycle or return deadline has passed.
    Under GST Law, GSTR-1 for return period M is due on the 11th of month M+1.
    If the 11th of month M+1 has passed, or if the promise period is in the past, the promise is broken.
    """
    now = datetime.now(timezone.utc)
    if not promised_period or not str(promised_period).strip():
        if dispatched_at:
            try:
                disp_dt = datetime.fromisoformat(str(dispatched_at).replace("Z", "+00:00"))
                return (now - disp_dt).days > 35
            except Exception:
                pass
        return False

    text = str(promised_period).strip().lower()

    months = {
        "january": 1, "jan": 1,
        "february": 2, "feb": 2,
        "march": 3, "mar": 3,
        "april": 4, "apr": 4,
        "may": 5,
        "june": 6, "jun": 6,
        "july": 7, "jul": 7,
        "august": 8, "aug": 8,
        "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10,
        "november": 11, "nov": 11,
        "december": 12, "dec": 12,
    }

    year_match = re.search(r"\b(20[2-3][0-9])\b", text)
    year = int(year_match.group(1)) if year_match else now.year

    target_month = None
    for m_name, m_num in months.items():
        if re.search(rf"\b{m_name}\b", text):
            target_month = m_num
            break

    if not target_month:
        iso_match = re.search(r"(\d{4})-(\d{2})", text)
        if iso_match:
            year = int(iso_match.group(1))
            target_month = int(iso_match.group(2))
        else:
            alt_match = re.search(r"(\d{2})-(\d{4})", text)
            if alt_match:
                target_month = int(alt_match.group(1))
                year = int(alt_match.group(2))

    if target_month and 1 <= target_month <= 12:
        # Statutory GSTR-1 cutoff is the 11th of the month following the return period
        if target_month == 12:
            deadline_year = year + 1
            deadline_month = 1
        else:
            deadline_year = year
            deadline_month = target_month + 1

        deadline_dt = datetime(deadline_year, deadline_month, 11, 23, 59, 59, tzinfo=timezone.utc)
        return now > deadline_dt

    if dispatched_at:
        try:
            disp_dt = datetime.fromisoformat(str(dispatched_at).replace("Z", "+00:00"))
            return (now - disp_dt).days > 35
        except Exception:
            pass

    return False


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
                    t_name = str(row.get("supplier_trade_name") or "").strip()
                    disp_name = resolve_supplier_display_name(supplier_name=t_name, trade_name=t_name, supplier_gstin=gstin)
                    vendor_map[gstin] = {
                        "supplier_gstin": gstin,
                        "supplier_name": disp_name,
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
                        "followup_status": None,
                        "response_action": None,
                        "arn_number": None,
                        "promised_period": None,
                        "promise_broken": False,
                        "promise_broken_note": None,
                        "token": None,
                        "viewed_at": None,
                    }
    except Exception as exc:
        logger.warning("Error fetching supplier_compliance_summary: %s", exc)

    # 2. Fetch Rule 37 overdue actions for invoice details — Aurora primary
    try:
        repo = _get_compliance_repo()
        r37_rows: list[dict] = []
        if repo is not None:
            r37_rows = repo.get_rule37_actions_for_client(
                str(client_gstin_id),
                columns=["supplier_gstin", "supplier_name", "invoice_number", "at_risk_itc_paise", "action_status"],
            )
        if not r37_rows:
            r37_res = (
                sb.table("rule37_actions")
                .select("supplier_gstin, supplier_name, invoice_number, at_risk_itc_paise, action_status")
                .eq("client_gstin_id", client_gstin_id)
                .execute()
            )
            r37_rows = list(r37_res.data or [])
        for r in r37_rows:
            gstin = str(r.get("supplier_gstin") or "").strip().upper()
            if not gstin:
                continue
            amt = round((float(r.get("at_risk_itc_paise") or 0)) / 100.0, 2)
            s_name = str(r.get("supplier_name") or "").strip()
            disp_name = resolve_supplier_display_name(supplier_name=s_name, trade_name=None, supplier_gstin=gstin)
            if gstin not in vendor_map:
                vendor_map[gstin] = {
                    "supplier_gstin": gstin,
                    "supplier_name": disp_name,
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
                    "followup_status": None,
                    "response_action": None,
                    "arn_number": None,
                    "promised_period": None,
                    "promise_broken": False,
                    "promise_broken_note": None,
                    "token": None,
                    "viewed_at": None,
                }
            else:
                vendor_map[gstin]["rule37_count"] += 1
                vendor_map[gstin]["rule37_at_risk_rupees"] = round(vendor_map[gstin]["rule37_at_risk_rupees"] + amt, 2)
                vendor_map[gstin]["at_risk_itc_rupees"] = round(vendor_map[gstin]["at_risk_itc_rupees"] + amt, 2)
    except Exception as exc:
        logger.warning("Error fetching rule37_actions for vendor follow-up: %s", exc)


    # 3. Attach past follow-up dispatch history and evaluate promise status
    try:
        logs = get_followup_history(sb, client_gstin_id)
        for log in logs:
            gstin = str(log.get("supplier_gstin") or "").strip().upper()
            if gstin in vendor_map:
                vendor_map[gstin]["followup_count"] += 1
                if not vendor_map[gstin]["last_followup_at"]:
                    vendor_map[gstin]["last_followup_at"] = log.get("dispatched_at")
                    f_status = log.get("status")
                    resp_act = log.get("response_action")
                    p_period = log.get("promised_period")
                    disp_at = log.get("dispatched_at")

                    is_broken = False
                    if f_status == "PROMISED_NEXT_CYCLE" or resp_act == "PROMISED_NEXT_CYCLE":
                        if is_promise_period_overdue(p_period, disp_at):
                            f_status = "PROMISE_BROKEN"
                            is_broken = True

                    vendor_map[gstin]["followup_status"] = f_status
                    vendor_map[gstin]["response_action"] = resp_act
                    vendor_map[gstin]["arn_number"] = log.get("arn_number")
                    vendor_map[gstin]["promised_period"] = p_period
                    vendor_map[gstin]["promise_broken"] = is_broken
                    if is_broken:
                        vendor_map[gstin]["promise_broken_note"] = (
                            f"Promised in {p_period}, but invoices remain unfiled" if p_period
                            else "Filing commitment period has passed — invoices remain unfiled"
                        )
                        # Auto-escalate risk score by 20 points
                        vendor_map[gstin]["risk_score"] = min(100, vendor_map[gstin]["risk_score"] + 20)

                    vendor_map[gstin]["token"] = log.get("token")
                    vendor_map[gstin]["viewed_at"] = log.get("viewed_at")
    except Exception as exc:
        logger.warning("Error attaching follow-up history: %s", exc)

    result = list(vendor_map.values())
    result.sort(key=lambda x: (x["at_risk_itc_rupees"], x["risk_score"]), reverse=True)
    return result


def generate_whatsapp_payload(
    supplier_gstin: str,
    supplier_name: Optional[str] = None,
    vendor_phone: Optional[str] = "",
    at_risk_itc_rupees: float = 0.0,
    template_type: str = "POLITE_REMINDER",
    trade_name: Optional[str] = None,
    contact_person: Optional[str] = None,
    custom_template: Optional[str] = None,
    portal_url: Optional[str] = None,
) -> dict[str, str]:
    """Generate pre-formatted WhatsApp wa.me deep link with encoded message text."""
    phone_clean = "".join(c for c in (vendor_phone or "") if c.isdigit())
    if len(phone_clean) == 10:
        phone_clean = f"91{phone_clean}"

    display_name = resolve_supplier_display_name(supplier_name, trade_name, supplier_gstin)
    salutation = resolve_contact_salutation(supplier_name, trade_name, contact_person, supplier_gstin)

    context = {
        "supplier_gstin": supplier_gstin,
        "supplier_name": supplier_name,
        "trade_name": trade_name,
        "contact_person": contact_person,
        "at_risk_itc_rupees": at_risk_itc_rupees,
    }

    if custom_template and custom_template.strip():
        message = sanitize_template_tokens(custom_template.strip(), context)
    elif template_type == "RULE37_NOTICE":
        message = (
            f"⚠️ *URGENT: Rule 37 Overdue Tax Risk Notice*\n\n"
            f"{salutation},\n\n"
            f"Our records indicate overdue unpaid invoices older than 180 days with total ITC exposure of *₹{at_risk_itc_rupees:,.2f}*.\n\n"
            f"Under Rule 37 of CGST Rules, failure to reconcile or settle payment will force an immediate ITC reversal with 18% interest.\n\n"
            f"Please share payment clearance confirmation or updated GSTR-1 filing status urgently.\n\n"
            f"— Finance & Tax Team, ReconDesk"
        )
    elif template_type == "FINAL_ESCALATION":
        message = (
            f"🚨 *FINAL NOTICE: Tax Compliance & Payment Escalation*\n\n"
            f"{salutation},\n\n"
            f"This is a final escalation regarding unfiled GSTR-1 invoices / unpaid bills totaling *₹{at_risk_itc_rupees:,.2f}*.\n\n"
            f"Your GST compliance score has dropped significantly, placing upcoming vendor payments on administrative hold.\n\n"
            f"Please file your pending GSTR-1 immediately to avoid legal recovery and vendor block.\n\n"
            f"— Finance & Audit Desk"
        )
    elif template_type == "MISSING_2B_REQUEST":
        message = (
            f"📄 *URGENT: Invoices Missing from GSTR-2B*\n\n"
            f"{salutation},\n\n"
            f"Invoices totaling *₹{at_risk_itc_rupees:,.2f}* are booked in our Purchase Register but are missing from your GSTR-1 / our GSTR-2B.\n\n"
            f"Under Section 16(2)(aa) of the CGST Act, our input tax credit is blocked until these appear in GSTR-2B.\n\n"
            f"Kindly upload these invoices in your upcoming GSTR-1 or provide filing confirmation.\n\n"
            f"— Finance & Tax Team, ReconDesk"
        )
    elif template_type == "VALUE_MISMATCH_VERIFICATION":
        message = (
            f"🔍 *Notice: Tax / Value Mismatch Verification*\n\n"
            f"{salutation},\n\n"
            f"We identified a tax discrepancy of *₹{at_risk_itc_rupees:,.2f}* between our purchase records and your GSTR-1 return.\n\n"
            f"Please verify invoice numbers, taxable values, and GST rates, and issue an amendment or credit/debit note if needed.\n\n"
            f"— Finance & Tax Team, ReconDesk"
        )
    elif template_type == "TAX_HEAD_MISMATCH_NOTICE":
        message = (
            f"🏛️ *URGENT: Tax Head / Place of Supply Discrepancy Notice*\n\n"
            f"{salutation},\n\n"
            f"We identified a tax head discrepancy on invoice(s) with total ITC exposure of *₹{at_risk_itc_rupees:,.2f}* between your GSTR-1 return and our purchase register (e.g. IGST filed instead of CGST/SGST, or asymmetric heads).\n\n"
            f"Under Section 77 of the CGST Act and Section 19 of the IGST Act, incorrect tax heads cannot be adjusted and will trigger tax demands and interest.\n\n"
            f"Please verify the Place of Supply (POS) and issue a Credit Note under Section 34 and re-issue the invoice with correct tax heads, or file the necessary amendment in your upcoming GSTR-1.\n\n"
            f"— Finance & Tax Team, ReconDesk"
        )
    elif template_type == "RCM_CONFLICT_NOTICE":
        message = (
            f"⚠️ *Notice: Reverse Charge (RCM) Treatment Discrepancy*\n\n"
            f"{salutation},\n\n"
            f"We noted a discrepancy in the Reverse Charge (RCM) classification on invoice(s) totaling *₹{at_risk_itc_rupees:,.2f}* between your GSTR-1 return and our purchase records.\n\n"
            f"If this supply attracts RCM under Section 9(3)/9(4) of the CGST Act, tax must be discharged in cash by the recipient and not billed by the supplier. If it is a forward charge supply, please amend your GSTR-1 return.\n\n"
            f"Kindly confirm the correct statutory treatment urgently so our GSTR-3B filings can be aligned.\n\n"
            f"— Finance & Tax Team, ReconDesk"
        )
    else:
        message = (
            f"📋 *GST Reconciliation & Invoice Follow-Up*\n\n"
            f"{salutation},\n\n"
            f"This is a gentle reminder regarding pending GSTR-1 filings / invoice reconciliations with total ITC amount of *₹{at_risk_itc_rupees:,.2f}*.\n\n"
            f"Kindly upload these invoices in your upcoming GSTR-1 so we can claim input tax credit smoothly.\n\n"
            f"Thank you for your prompt cooperation!\n\n"
            f"— ReconDesk Automated Tax Hub"
        )

    if portal_url and portal_url.strip():
        message = f"{message}\n\n🔗 *Action Required — Confirm Status in 1-Click:*\n{portal_url.strip()}"

    # Sanitize any residual tokens in message
    message = sanitize_template_tokens(message, context)

    encoded_msg = quote(message)
    wa_url = f"https://wa.me/{phone_clean}?text={encoded_msg}" if phone_clean else f"https://wa.me/?text={encoded_msg}"

    return {
        "supplier_gstin": supplier_gstin,
        "supplier_name": display_name,
        "vendor_phone": phone_clean,
        "template_type": template_type,
        "message_text": message,
        "whatsapp_url": wa_url,
        "portal_url": portal_url or "",
    }


def generate_email_template(
    supplier_gstin: str,
    supplier_name: Optional[str] = None,
    at_risk_itc_rupees: float = 0.0,
    template_type: str = "POLITE_REMINDER",
    trade_name: Optional[str] = None,
    contact_person: Optional[str] = None,
    custom_template: Optional[str] = None,
    portal_url: Optional[str] = None,
) -> dict[str, str]:
    """Generate formal HTML vendor email notice payload."""
    display_name = resolve_supplier_display_name(supplier_name, trade_name, supplier_gstin)
    contact_clean = str(contact_person or "").strip()

    context = {
        "supplier_gstin": supplier_gstin,
        "supplier_name": supplier_name,
        "trade_name": trade_name,
        "contact_person": contact_person,
        "at_risk_itc_rupees": at_risk_itc_rupees,
    }

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
    elif template_type == "TAX_HEAD_MISMATCH_NOTICE":
        subject = f"Notice: Tax Head / Place of Supply Discrepancy for {supplier_gstin} [₹{at_risk_itc_rupees:,.2f}]"
        detail_para = "We identified a tax head allocation mismatch on invoice(s) totaling <strong>₹" + f"{at_risk_itc_rupees:,.2f}" + "</strong> between your GSTR-1 filing and our purchase records (e.g. IGST declared instead of CGST/SGST, or asymmetric intra-state heads). Under Section 77 of the CGST Act and Section 19 of the IGST Act, cross-utilization of incorrectly paid tax is restricted and may attract interest. Kindly verify the Place of Supply (POS), issue a Section 34 Credit Note, and re-issue the invoice with correct tax heads or file the amendment in your upcoming GSTR-1 return."
    elif template_type == "RCM_CONFLICT_NOTICE":
        subject = f"Notice: Reverse Charge (RCM) Classification Discrepancy for {supplier_gstin} [₹{at_risk_itc_rupees:,.2f}]"
        detail_para = "A discrepancy has been identified regarding the Reverse Charge (RCM) treatment on invoice(s) totaling <strong>₹" + f"{at_risk_itc_rupees:,.2f}" + "</strong> between your GSTR-1 filing and our purchase register. If the supply falls under Section 9(3) or 9(4) of the CGST Act, recipient discharge is mandatory; otherwise, forward charge reporting must be maintained. Please confirm the statutory classification or furnish an amended return."
    else:
        subject = f"Notice: GST Reconciliation & ITC Compliance for {supplier_gstin} [₹{at_risk_itc_rupees:,.2f}]"
        detail_para = "We are currently conducting our period end GST audit and identified unmatched invoices / Rule 37 payment exposures totaling <strong>₹" + f"{at_risk_itc_rupees:,.2f}" + "</strong>."

    if contact_clean:
        if display_name != DEFAULT_SUPPLIER_NAME_FALLBACK:
            salutation_html = f"<p>Dear <strong>{contact_clean}</strong> ({display_name} / GSTIN: <code>{supplier_gstin}</code>),</p>"
        else:
            salutation_html = f"<p>Dear <strong>{contact_clean}</strong> (GSTIN: <code>{supplier_gstin}</code>),</p>"
    else:
        salutation_html = f"<p>Dear <strong>{display_name}</strong> (GSTIN: <code>{supplier_gstin}</code>),</p>"

    if custom_template and custom_template.strip():
        sanitized_custom = sanitize_template_tokens(custom_template.strip(), context)
        content_body = f"<p>{sanitized_custom}</p>"
    else:
        content_body = f"<p>{detail_para}</p>"

    cta_block = ""
    if portal_url and portal_url.strip():
        cta_block = f"""
        <div style="margin: 28px 0; text-align: center;">
            <a href="{portal_url.strip()}" style="background-color: #4f46e5; color: #ffffff; padding: 12px 24px; font-weight: bold; border-radius: 8px; text-decoration: none; display: inline-block;">
                Review Invoices &amp; Confirm Filing in 1-Click
            </a>
            <p style="font-size: 11px; color: #6b7280; margin-top: 8px;">No login required. Submit ARN or schedule next filing cycle securely under CGST Act, 2017.</p>
        </div>
        """

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; color: #111827; line-height: 1.6;">
        <h2 style="color: #4f46e5;">GST Compliance &amp; ITC Reconciliation Notice</h2>
        {salutation_html}
        {content_body}
        <div style="background-color: #f3f4f6; border-left: 4px solid #4f46e5; padding: 12px 16px; margin: 16px 0; border-radius: 4px;">
            <strong>Template Category:</strong> {template_type.replace('_', ' ').title()}<br/>
            <strong>Total ITC at Stake:</strong> ₹{at_risk_itc_rupees:,.2f}
        </div>
        {cta_block}
        <p>Kindly verify your GSTR-1 filings and invoice clearance status so we can reconcile input tax credit without statutory exposure.</p>
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;" />
        <p style="font-size: 12px; color: #6b7280;">Automated via ReconDesk Compliance Engine.</p>
    </div>
    """

    return {
        "subject": sanitize_template_tokens(subject, context),
        "html_body": html_body,
        "supplier_gstin": supplier_gstin,
        "supplier_name": display_name,
        "portal_url": portal_url or "",
    }


def fetch_vendor_invoices(sb: Client, client_gstin_id: str, supplier_gstin: str) -> list[dict[str, Any]]:
    """Retrieve at-risk invoices for a vendor from itc_work_items and rule37_actions."""
    invoices: list[dict[str, Any]] = []
    seen = set()

    # 1. Query itc_work_items
    try:
        q = (
            sb.table("itc_work_items")
            .select("invoice_number, invoice_date, taxable_value, total_tax, itc_amount_at_stake, exception_type, status")
            .eq("client_gstin_id", client_gstin_id)
            .eq("vendor_gstin", supplier_gstin)
        )
        if hasattr(q, "neq"):
            q = q.neq("status", "RESOLVED")
        wi_res = q.limit(50).execute()
        for r in wi_res.data or []:
            if r.get("status") == "RESOLVED":
                continue
            inv_no = str(r.get("invoice_number") or "").strip()
            if not inv_no or inv_no in seen:
                continue
            seen.add(inv_no)
            tax_val = float(r.get("total_tax") or r.get("itc_amount_at_stake") or 0.0)
            invoices.append({
                "invoice_number": inv_no,
                "invoice_date": r.get("invoice_date"),
                "taxable_value": float(r.get("taxable_value") or 0.0),
                "tax_amount": tax_val,
                "reason": r.get("exception_type") or "Missing in GSTR-2B",
            })
    except Exception as exc:
        logger.warning("Error fetching itc_work_items for vendor %s: %s", supplier_gstin, exc)

    # 2. Query rule37_actions — Aurora primary
    try:
        repo = _get_compliance_repo()
        r37_rows: list[dict] = []
        if repo is not None:
            all_client = repo.get_rule37_actions_for_client(
                str(client_gstin_id),
                columns=["invoice_number", "invoice_date", "taxable_value_paise", "at_risk_itc_paise", "action_status", "supplier_gstin"],
            )
            r37_rows = [
                r for r in all_client
                if str(r.get("supplier_gstin") or "").strip().upper() == str(supplier_gstin).strip().upper()
            ][:50]
        if not r37_rows:
            r37_res = (
                sb.table("rule37_actions")
                .select("invoice_number, invoice_date, taxable_value_paise, at_risk_itc_paise, action_status")
                .eq("client_gstin_id", client_gstin_id)
                .eq("supplier_gstin", supplier_gstin)
                .limit(50)
                .execute()
            )
            r37_rows = list(r37_res.data or [])
        for r in r37_rows:
            inv_no = str(r.get("invoice_number") or "").strip()
            if not inv_no or inv_no in seen:
                continue
            seen.add(inv_no)
            tax_val = round(float(r.get("at_risk_itc_paise") or 0.0) / 100.0, 2)
            taxable = round(float(r.get("taxable_value_paise") or 0.0) / 100.0, 2)
            invoices.append({
                "invoice_number": inv_no,
                "invoice_date": r.get("invoice_date"),
                "taxable_value": taxable,
                "tax_amount": tax_val,
                "reason": "Rule 37 Overdue (180 Days)",
            })
    except Exception as exc:
        logger.warning("Error fetching rule37_actions for vendor %s: %s", supplier_gstin, exc)

    return invoices


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
    token: Optional[str] = None,
    expires_at: Optional[str] = None,
    invoices_snapshot: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Persist follow-up dispatch event into vendor_followup_logs and record timeline event if work_item_id is provided."""
    status_label = "LINK_OPENED" if channel == "WHATSAPP" else "NOTICE_GENERATED"
    actual_token = token or secrets.token_urlsafe(32)
    actual_expires_at = expires_at or (datetime.now(timezone.utc) + timedelta(days=45)).isoformat()
    if invoices_snapshot is None:
        invoices_snapshot = fetch_vendor_invoices(sb, client_gstin_id, supplier_gstin)

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
        "token": actual_token,
        "expires_at": actual_expires_at,
        "invoices_snapshot": invoices_snapshot,
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
            import json
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
                            (client_gstin_id, supplier_gstin, supplier_name, vendor_phone, vendor_email, channel, template_type, at_risk_itc_rupees, status, work_item_id, message_body, token, expires_at, invoices_snapshot)
                            VALUES (:cid, :sgstin, :sname, :phone, :email, :chan, :ttype, :amt, :stat, :wid, :mbody, :tok, :exp, :inv_snap)
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
                            "tok": actual_token,
                            "exp": actual_expires_at,
                            "inv_snap": json.dumps(invoices_snapshot) if invoices_snapshot else None,
                        },
                    )
                    conn.commit()
                    eng.dispose()
                    created_record = dict(payload)
        except Exception as sql_exc:
            logger.error("Direct SQL fallback failed for log_followup_action: %s", sql_exc)

    # Only record COMMUNICATION_DISPATCHED if vendor_followup_logs was successfully persisted
    if work_item_id and created_record is not None:
        try:
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
                    "token": actual_token,
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            sb.table("itc_work_item_events").insert(ev_payload).execute()
        except Exception as ev_exc:
            logger.warning("Failed to record COMMUNICATION_DISPATCHED event for work item %s: %s", work_item_id, ev_exc)

    return created_record


def create_or_get_followup_token(
    sb: Client,
    client_gstin_id: str,
    supplier_gstin: str,
    supplier_name: Optional[str] = None,
    vendor_phone: Optional[str] = "",
    vendor_email: Optional[str] = "",
    at_risk_itc_rupees: float = 0.0,
    work_item_id: Optional[str] = None,
    template_type: str = "POLITE_REMINDER",
    channel: str = "WHATSAPP",
    dispatched_by: Optional[str] = None,
) -> dict[str, Any]:
    """Generate or retrieve a secure 32-byte cryptographic token for vendor action portal."""
    norm_gstin = (supplier_gstin or "").strip().upper()
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(days=45)).isoformat()

    # Check if a recent unexpired unresponded token exists for this client + supplier
    existing_token = None
    existing_invoices_count = 0
    try:
        res = (
            sb.table("vendor_followup_logs")
            .select("id, token, expires_at, status, invoices_snapshot")
            .eq("client_gstin_id", client_gstin_id)
            .eq("supplier_gstin", norm_gstin)
            .not_.is_("token", "null")
            .order("dispatched_at", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            row = res.data[0]
            exp_raw = row.get("expires_at")
            if exp_raw:
                exp_dt = datetime.fromisoformat(str(exp_raw).replace("Z", "+00:00"))
                if exp_dt > now and row.get("status") not in ("FILING_CONFIRMED", "PROMISED_NEXT_CYCLE", "DISPUTED"):
                    existing_token = row.get("token")
                    snap = row.get("invoices_snapshot")
                    if isinstance(snap, str):
                        try:
                            import json
                            snap = json.loads(snap)
                        except Exception:
                            snap = []
                    existing_invoices_count = len(snap) if isinstance(snap, list) else 0
    except Exception as exc:
        logger.warning("Error checking existing token: %s", exc)

    token = existing_token or secrets.token_urlsafe(32)

    # If no existing token, take an immutable snapshot and persist record
    if not existing_token:
        invoices = fetch_vendor_invoices(sb, client_gstin_id, norm_gstin)
        invoices_count = len(invoices)
        log_followup_action(
            sb=sb,
            client_gstin_id=client_gstin_id,
            supplier_gstin=norm_gstin,
            supplier_name=supplier_name or norm_gstin,
            vendor_phone=vendor_phone or "",
            vendor_email=vendor_email or "",
            channel=channel,
            template_type=template_type,
            at_risk_itc_rupees=at_risk_itc_rupees,
            dispatched_by=dispatched_by,
            work_item_id=work_item_id,
            token=token,
            expires_at=expires_at,
            invoices_snapshot=invoices,
        )
    else:
        invoices_count = existing_invoices_count

    from app.config import get_settings
    settings = get_settings()
    base_url = (getattr(settings, "FRONTEND_URL", None) or "https://recondesk.in").rstrip("/")
    portal_url = f"{base_url}/v/{token}"

    return {
        "token": token,
        "portal_url": portal_url,
        "expires_at": expires_at,
        "invoices_count": invoices_count,
    }


def get_vendor_portal_data(sb: Client, token: str) -> dict[str, Any]:
    """Retrieve vendor portal metadata, missing invoice list, and record viewed_at timestamp."""
    clean_token = (token or "").strip()
    if not clean_token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendor portal token is required",
        )

    # 1. Lookup followup log by token
    log_row = None
    try:
        res = sb.table("vendor_followup_logs").select("*").eq("token", clean_token).limit(1).execute()
        if res.data:
            log_row = res.data[0]
    except Exception as exc:
        logger.warning("PostgREST query by token failed, attempting SQL fallback: %s", exc)
        try:
            from app.config import get_settings
            import sqlalchemy as sa
            s = get_settings()
            db_url = s.SUPABASE_DATABASE_URL or s.DATABASE_URL
            if db_url:
                eng = sa.create_engine(db_url)
                with eng.connect() as conn:
                    _ensure_table_exists(conn)
                    q = conn.execute(
                        sa.text("SELECT * FROM public.vendor_followup_logs WHERE token = :tok LIMIT 1"),
                        {"tok": clean_token},
                    )
                    r = q.mappings().first()
                    if r:
                        log_row = dict(r)
                eng.dispose()
        except Exception as sql_exc:
            logger.error("SQL fallback failed for token lookup: %s", sql_exc)

    if not log_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired vendor verification link. Please request a new link from your client.",
        )

    # 2. Check expiration
    expires_at_raw = log_row.get("expires_at")
    if expires_at_raw:
        try:
            exp_dt = datetime.fromisoformat(str(expires_at_raw).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp_dt:
                raise HTTPException(
                    status_code=status.HTTP_410_GONE,
                    detail="This vendor reconciliation link has expired (45-day validity period exceeded).",
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("Error parsing expires_at: %s", e)

    # 3. Record viewed_at if not set (DPDP Act 2023 compliant: NO IP logging!)
    now_iso = datetime.now(timezone.utc).isoformat()
    if not log_row.get("viewed_at"):
        try:
            current_status = log_row.get("status")
            new_status = "VIEWED" if current_status in ("SENT", "LINK_OPENED", "DISPATCHED") else current_status
            sb.table("vendor_followup_logs").update({
                "viewed_at": now_iso,
                "status": new_status,
            }).eq("id", log_row["id"]).execute()
            log_row["viewed_at"] = now_iso
            log_row["status"] = new_status
        except Exception as exc:
            logger.warning("Failed to update viewed_at timestamp: %s", exc)

    # 4. Resolve client display info
    client_id = str(log_row.get("client_gstin_id") or "")
    client_name = "Finance & Tax Team"
    client_gstin = ""
    try:
        c_res = sb.table("client_gstins").select("gstin, legal_name, trade_name").eq("id", client_id).limit(1).execute()
        if c_res.data:
            c_row = c_res.data[0]
            client_gstin = str(c_row.get("gstin") or "").strip()
            client_name = str(c_row.get("trade_name") or c_row.get("legal_name") or "Valued Client").strip()
    except Exception as exc:
        logger.warning("Failed to fetch client details for portal: %s", exc)

    # 5. Retrieve invoice list strictly from immutable snapshot taken at notice dispatch time
    raw_snap = log_row.get("invoices_snapshot")
    invoices = []
    if raw_snap:
        if isinstance(raw_snap, str):
            try:
                import json
                invoices = json.loads(raw_snap)
            except Exception as e:
                logger.warning("Failed parsing invoices_snapshot JSON: %s", e)
                invoices = []
        elif isinstance(raw_snap, list):
            invoices = raw_snap

    # If no snapshot was recorded (legacy notices only), snapshot once and freeze
    if not invoices and client_id and log_row.get("supplier_gstin"):
        invoices = fetch_vendor_invoices(sb, client_id, log_row["supplier_gstin"])
        if invoices:
            try:
                sb.table("vendor_followup_logs").update({
                    "invoices_snapshot": invoices
                }).eq("id", log_row["id"]).execute()
            except Exception as exc:
                logger.warning("Could not freeze fallback invoices_snapshot: %s", exc)

    return {
        "id": str(log_row.get("id")),
        "token": clean_token,
        "client_name": client_name,
        "client_gstin": client_gstin,
        "supplier_name": log_row.get("supplier_name") or log_row.get("supplier_gstin"),
        "supplier_gstin": log_row.get("supplier_gstin"),
        "at_risk_itc_rupees": float(log_row.get("at_risk_itc_rupees") or 0.0),
        "status": log_row.get("status"),
        "response_action": log_row.get("response_action"),
        "arn_number": log_row.get("arn_number"),
        "promised_period": log_row.get("promised_period"),
        "dispute_reason": log_row.get("dispute_reason"),
        "attachment_key": log_row.get("attachment_key"),
        "viewed_at": log_row.get("viewed_at"),
        "responded_at": log_row.get("responded_at"),
        "expires_at": log_row.get("expires_at"),
        "invoices": invoices,
    }


def submit_vendor_portal_response(
    sb: Client,
    token: str,
    action: str,
    arn_number: Optional[str] = None,
    promised_period: Optional[str] = None,
    dispute_reason: Optional[str] = None,
    attachment_key: Optional[str] = None,
) -> dict[str, Any]:
    """Process vendor response: Validate statutory ARN, cycle selection, or dispute note."""
    clean_token = (token or "").strip()
    clean_action = (action or "").strip().upper()

    log_data = get_vendor_portal_data(sb, clean_token)
    log_id = log_data["id"]

    now_iso = datetime.now(timezone.utc).isoformat()
    arn_clean = (arn_number or "").strip().upper()

    if clean_action == "ALREADY_FILED":
        if not arn_clean:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="18-character Application Reference Number (ARN) is required to confirm filing.",
            )
        # Validate ARN format: AA followed by 2 digits followed by 14 alphanumeric chars
        if not re.match(r"^AA[0-9]{2}[A-Z0-9]{14}$", arn_clean):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid ARN format. Must be an 18-character GST Application Reference Number (e.g. AA2708260012345).",
            )
        status_val = "FILING_CONFIRMED"
    elif clean_action == "PROMISED_NEXT_CYCLE":
        if not (promised_period or "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Target filing cycle (e.g. 'September 2026') is required.",
            )
        status_val = "PROMISED_NEXT_CYCLE"
    elif clean_action == "DISPUTED":
        if not (dispute_reason or "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Please provide a brief explanation for why this invoice is canceled or not recognized.",
            )
        status_val = "DISPUTED"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid response action. Must be ALREADY_FILED, PROMISED_NEXT_CYCLE, or DISPUTED.",
        )

    update_payload = {
        "status": status_val,
        "response_action": clean_action,
        "arn_number": arn_clean if clean_action == "ALREADY_FILED" else None,
        "promised_period": (promised_period or "").strip() if clean_action == "PROMISED_NEXT_CYCLE" else None,
        "dispute_reason": (dispute_reason or "").strip() if clean_action == "DISPUTED" else None,
        "attachment_key": (attachment_key or "").strip() or None,
        "responded_at": now_iso,
    }

    try:
        sb.table("vendor_followup_logs").update(update_payload).eq("id", log_id).execute()
    except Exception as exc:
        logger.warning("Supabase update failed, attempting direct SQL: %s", exc)
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
                            UPDATE public.vendor_followup_logs
                            SET status = :stat,
                                response_action = :act,
                                arn_number = :arn,
                                promised_period = :pperiod,
                                dispute_reason = :dreason,
                                attachment_key = :akey,
                                responded_at = :resp_at
                            WHERE id = :lid
                            """
                        ),
                        {
                            "stat": status_val,
                            "act": clean_action,
                            "arn": update_payload["arn_number"],
                            "pperiod": update_payload["promised_period"],
                            "dreason": update_payload["dispute_reason"],
                            "akey": update_payload["attachment_key"],
                            "resp_at": now_iso,
                            "lid": log_id,
                        },
                    )
                    conn.commit()
                eng.dispose()
        except Exception as sql_exc:
            logger.error("SQL update failed in submit_vendor_portal_response: %s", sql_exc)

    return {
        "success": True,
        "status": status_val,
        "response_action": clean_action,
        "reference_id": log_id,
        "token": clean_token,
        "responded_at": now_iso,
        "arn_number": update_payload["arn_number"],
        "promised_period": update_payload["promised_period"],
        "dispute_reason": update_payload["dispute_reason"],
        "attachment_key": update_payload["attachment_key"],
        "message": "Thank you! Your response has been securely recorded for GST reconciliation.",
    }


def update_vendor_contact_info(
    sb: Client,
    client_gstin_id: str,
    supplier_gstin: str,
    vendor_phone: Optional[str] = None,
    vendor_email: Optional[str] = None,
) -> dict[str, Any]:
    """Persist updated vendor mobile and email into supplier compliance summary & recent logs."""
    gstin_norm = (supplier_gstin or "").strip().upper()
    phone_clean = "".join(c for c in (vendor_phone or "") if c.isdigit())
    email_clean = (vendor_email or "").strip().lower()

    # 1. Update in supplier_compliance_summary if row exists
    try:
        upd = {}
        if phone_clean:
            upd["vendor_phone"] = phone_clean
        if email_clean:
            upd["vendor_email"] = email_clean
        if upd:
            sb.table("supplier_compliance_summary").update(upd).eq("supplier_gstin_normalized", gstin_norm).execute()
    except Exception as exc:
        logger.warning("Could not update supplier_compliance_summary: %s", exc)

    # 2. Update existing followup logs for this client & supplier so UI displays immediately
    try:
        log_upd = {}
        if phone_clean:
            log_upd["vendor_phone"] = phone_clean
        if email_clean:
            log_upd["vendor_email"] = email_clean
        if log_upd:
            sb.table("vendor_followup_logs").update(log_upd).eq("client_gstin_id", client_gstin_id).eq("supplier_gstin", gstin_norm).execute()
    except Exception as exc:
        logger.warning("Could not update vendor_followup_logs: %s", exc)

    return {
        "supplier_gstin": gstin_norm,
        "vendor_phone": phone_clean,
        "vendor_email": email_clean,
        "message": "Vendor contact details updated successfully.",
    }


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
