"""Transactional email via Resend; failures are logged to audit_logs and never raised."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from html import escape
from typing import Any

import resend

from app.config import settings
from app.utils.audit import log_action

_log = logging.getLogger(__name__)

resend.api_key = settings.RESEND_API_KEY or ""

EMAIL_FROM = (settings.EMAIL_FROM or "").strip() or "ReconDesk <onboarding@resend.dev>"
DASHBOARD_URL = "https://recondesk.in/dashboard"
BRAND = "#6C63FF"


def _format_in_rupees_indian(paise: int) -> str:
    """Convert paise to a rupee string with Indian-style grouping."""
    sign = "-" if paise < 0 else ""
    ap = abs(int(paise))
    rupees = ap // 100
    sub = ap % 100
    s = str(rupees)
    if len(s) <= 3:
        grouped = s
    else:
        last3 = s[-3:]
        rest = s[:-3]
        parts: list[str] = []
        while rest:
            parts.append(rest[-2:])
            rest = rest[:-2]
        grouped = ",".join(reversed(parts)) + "," + last3
    return f"{sign}Rs {grouped}.{sub:02d}"


def _month_name_year(d: datetime | None = None) -> str:
    d = d or datetime.now(timezone.utc)
    return d.strftime("%B %Y")


def _base_wrapper(title: str, inner_html: str, plain: str) -> tuple[str, str]:
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{escape(title)}</title></head>
<body style="margin:0;padding:0;background:#f5f5f8;font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f5f5f8;padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06);">
        <tr><td style="padding:24px 28px;background:{BRAND};color:#ffffff;font-size:20px;font-weight:600;">ReconDesk</td></tr>
        <tr><td style="padding:28px 28px 36px;color:#1a1a2e;font-size:15px;line-height:1.55;">
{inner_html}
        </td></tr>
      </table>
      <p style="margin:20px 0 0;font-size:12px;color:#888;">GSTR-2B reconciliation for CA firms in India</p>
    </td></tr>
  </table>
</body></html>"""
    return html, plain


def wrap_branded_email(title: str, inner_html: str, plain: str) -> tuple[str, str]:
    """Public alias for branded HTML shell + plain body (used by email_service)."""
    return _base_wrapper(title, inner_html, plain)


def _cta_button(href: str, label: str) -> str:
    return f"""<p style="margin:28px 0 0;">
  <a href="{escape(href)}" style="display:inline-block;background:{BRAND};color:#ffffff;text-decoration:none;font-weight:600;padding:12px 24px;border-radius:8px;">{escape(label)}</a>
</p>"""


async def send_email(
    to: str,
    subject: str,
    html_content: str,
    *,
    text_content: str | None = None,
) -> bool:
    """Send via Resend. On failure, log EMAIL_FAILED; never raises. Returns True on success."""
    params: dict[str, Any] = {
        "from": EMAIL_FROM,
        "to": [to],
        "subject": subject,
        "html": html_content,
    }
    if text_content and text_content.strip():
        params["text"] = text_content.strip()

    if not (settings.RESEND_API_KEY or "").strip():
        _log.warning("RESEND_API_KEY not set; skip send to=%s subject=%s", to, subject)
        await log_action(
            None,
            "EMAIL_FAILED",
            "email",
            None,
            {
                "to": to,
                "subject": subject,
                "error_message": "RESEND_API_KEY not configured",
            },
        )
        return False

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, lambda: resend.Emails.send(params)  # type: ignore[arg-type]
        )
    except Exception as exc:  # noqa: BLE001
        err_msg = str(exc)
        _log.exception("Resend send failed to=%s: %s", to, err_msg)
        await log_action(
            None,
            "EMAIL_FAILED",
            "email",
            None,
            {
                "to": to,
                "subject": subject,
                "error_message": err_msg[:4000],
            },
        )
        return False
    return True


async def send_welcome_email(to: str, full_name: str) -> bool:
    name = escape(full_name.strip() or "there")
    inner = f"""<p style="margin:0 0 16px;">Hi {name}, welcome to ReconDesk.</p>
<p style="margin:0 0 16px;">ReconDesk helps your firm reconcile GSTR-2B invoices with purchase records—built for Chartered Accountants in India.</p>
<p style="margin:0 0 8px;font-weight:600;">Get started in three steps:</p>
<ol style="margin:0 0 16px;padding-left:20px;">
  <li>Add client</li>
  <li>Upload files</li>
  <li>See results</li>
</ol>
{_cta_button(DASHBOARD_URL, "Open ReconDesk")}"""
    plain = f"""Hi {full_name.strip() or 'there'}, welcome to ReconDesk.

ReconDesk helps your firm reconcile GSTR-2B invoices with purchase records—built for Chartered Accountants in India.

Get started: Add client → Upload files → See results.

Open ReconDesk: {DASHBOARD_URL}
"""
    html, plain = _base_wrapper("Welcome to ReconDesk", inner, plain)
    return await send_email(
        to, "Welcome to ReconDesk — Getting Started", html, text_content=plain
    )


async def send_reconciliation_complete_email(
    to: str,
    full_name: str,
    client_name: str,
    period: str,
    matched_count: int,
    missed_itc_amount_paise: int,
    wrongful_risk_amount_paise: int,
    match_rate_percent: float,
    run_id: str,
) -> bool:
    name = escape(full_name.strip() or "there")
    subj = f"Reconciliation Complete — {client_name.strip() or 'Client'} {period.strip()}"

    missed_rs = _format_in_rupees_indian(missed_itc_amount_paise)
    risk_rs = _format_in_rupees_indian(wrongful_risk_amount_paise)

    boxes = ""
    if missed_itc_amount_paise > 0:
        boxes += f"""
<div style="margin:16px 0;padding:14px 16px;background:#e8f5e9;border-radius:8px;border-left:4px solid #2e7d32;">
  <strong style="color:#1b5e20;">{missed_rs} ITC you can still claim</strong>
</div>"""
    if wrongful_risk_amount_paise > 0:
        boxes += f"""
<div style="margin:16px 0;padding:14px 16px;background:#ffebee;border-radius:8px;border-left:4px solid #c62828;">
  <strong style="color:#b71c1c;">{risk_rs} ITC at risk — not reflected in GSTR-2B</strong>
</div>"""

    results_url = f"https://recondesk.in/reconcile/runs/{run_id}/results"
    inner = f"""<p style="margin:0 0 16px;">Hi {name},</p>
<p style="margin:0 0 16px;"><strong>{match_rate_percent:.2f}%</strong> of invoices matched.</p>
{boxes}
<p style="margin:16px 0;padding:12px;background:#f0f0f5;border-radius:8px;font-size:14px;">
  Matched: <strong>{matched_count}</strong>
  &nbsp;|&nbsp; Missed ITC: <strong>{missed_rs}</strong>
  &nbsp;|&nbsp; At Risk: <strong>{risk_rs}</strong>
</p>
{_cta_button(results_url, "View Full Report")}"""

    plain = f"""Hi {full_name.strip() or 'there'},

{match_rate_percent:.2f}% of invoices matched for {client_name.strip() or 'Client'} ({period.strip()}).
Matched: {matched_count} | Missed ITC: {missed_rs} | At Risk: {risk_rs}
"""
    if missed_itc_amount_paise > 0:
        plain += f"\n{missed_rs} ITC you can still claim.\n"
    if wrongful_risk_amount_paise > 0:
        plain += f"\n{risk_rs} ITC at risk — not reflected in GSTR-2B.\n"
    plain += f"\nView full report: {results_url}\n"

    html, plain_body = _base_wrapper("Reconciliation complete", inner, plain)
    return await send_email(to, subj, html, text_content=plain_body)


async def send_rule37_alert_email(
    to: str,
    full_name: str,
    client_name: str,
    invoices: list[dict],
) -> bool:
    n = len(invoices)
    subj = f"Payment Deadline Alert — {n} Invoices Expiring Soon"
    name = escape(full_name.strip() or "there")
    client_e = escape(client_name.strip() or "Client")

    rows_html = ""
    rows_plain = ""
    for inv in invoices:
        gstin = escape(str(inv.get("supplier_gstin") or ""))
        inv_no = escape(str(inv.get("invoice_number") or ""))
        amt = _format_in_rupees_indian(int(inv.get("amount_paise") or 0))
        ddl = escape(str(inv.get("deadline_date") or ""))
        rows_html += f"<tr><td style='padding:8px;border-bottom:1px solid #eee;'>{gstin}</td><td style='padding:8px;border-bottom:1px solid #eee;'>{inv_no}</td><td style='padding:8px;border-bottom:1px solid #eee;'>{amt}</td><td style='padding:8px;border-bottom:1px solid #eee;'>{ddl}</td></tr>"
        rows_plain += f"  - {inv.get('supplier_gstin')} | {inv.get('invoice_number')} | {amt} | {inv.get('deadline_date')}\n"

    inner = f"""<p style="margin:0 0 16px;">Hi {name},</p>
<p style="margin:0 0 16px;"><strong>{n} invoices</strong> for <strong>{client_e}</strong> are approaching the 180-day Rule 37 deadline.</p>
<table style="width:100%;border-collapse:collapse;font-size:14px;margin:16px 0;">
  <thead><tr style="background:#f0f0f5;text-align:left;">
    <th style="padding:8px;">Supplier GSTIN</th><th style="padding:8px;">Invoice#</th><th style="padding:8px;">Amount</th><th style="padding:8px;">Deadline</th>
  </tr></thead>
  <tbody>{rows_html}</tbody>
</table>
<p style="margin:0 0 8px;">Pay these suppliers before the deadline to retain ITC.</p>
{_cta_button(DASHBOARD_URL, "View in ReconDesk")}"""

    plain = f"""Hi {full_name.strip() or 'there'},

{n} invoices for {client_name.strip() or 'Client'} are approaching the 180-day Rule 37 deadline.

{rows_plain}
Pay these suppliers before the deadline to retain ITC.

View in ReconDesk: {DASHBOARD_URL}
"""
    html, plain_body = _base_wrapper("Rule 37 alert", inner, plain)
    return await send_email(to, subj, html, text_content=plain_body)


async def send_monthly_reminder_email(
    to: str,
    full_name: str,
    pending_clients: list[dict],
) -> bool:
    n = len(pending_clients)
    month_label = _month_name_year()
    subj = f"GSTR-2B Available — {n} Clients Due for Reconciliation"
    name = escape(full_name.strip() or "there")

    rows_html = ""
    rows_plain = ""
    for c in pending_clients:
        cn = escape(str(c.get("client_name") or ""))
        gst = escape(str(c.get("gstin") or ""))
        last = escape(str(c.get("last_reconciled_period") or "—"))
        rows_html += f"<tr><td style='padding:8px;border-bottom:1px solid #eee;'>{cn}</td><td style='padding:8px;border-bottom:1px solid #eee;'>{gst}</td><td style='padding:8px;border-bottom:1px solid #eee;'>{last}</td></tr>"
        rows_plain += f"  - {c.get('client_name')} | {c.get('gstin')} | {c.get('last_reconciled_period')}\n"

    inner = f"""<p style="margin:0 0 16px;">Hi {name},</p>
<p style="margin:0 0 16px;">GSTR-2B for <strong>{escape(month_label)}</strong> is now available.</p>
<table style="width:100%;border-collapse:collapse;font-size:14px;margin:16px 0;">
  <thead><tr style="background:#f0f0f5;text-align:left;">
    <th style="padding:8px;">Client Name</th><th style="padding:8px;">GSTIN</th><th style="padding:8px;">Last Reconciled</th>
  </tr></thead>
  <tbody>{rows_html}</tbody>
</table>
{_cta_button(DASHBOARD_URL, "Start Reconciling")}"""

    plain = f"""Hi {full_name.strip() or 'there'},

GSTR-2B for {month_label} is now available.

Pending clients:
{rows_plain}
Start reconciling: {DASHBOARD_URL}
"""
    html, plain_body = _base_wrapper("Monthly reminder", inner, plain)
    return await send_email(to, subj, html, text_content=plain_body)


async def send_team_invite_email(
    to: str,
    inviter_firm_name: str,
    role: str,
    invite_token: str,
) -> bool:
    firm = escape(inviter_firm_name.strip() or "A firm")
    r = (role or "").strip().lower()
    if r == "admin":
        role_desc = "You will have full access including finalizing reconciliations."
    else:
        role_desc = "You can upload files, run reconciliations, and add notes."

    subj = f"{inviter_firm_name.strip() or 'A firm'} has invited you to ReconDesk"
    accept_url = f"https://recondesk.in/team/accept/{invite_token}"

    inner = f"""<p style="margin:0 0 16px;"><strong>{firm}</strong> has invited you to join their team on ReconDesk.</p>
<p style="margin:0 0 16px;">{escape(role_desc)}</p>
<p style="margin:0 0 16px;">ReconDesk streamlines GSTR-2B reconciliation so your firm can close books faster and with fewer errors.</p>
{_cta_button(accept_url, "Accept Invitation")}
<p style="margin:24px 0 0;font-size:13px;color:#666;">This invitation expires in 7 days.</p>"""

    plain = f"""{inviter_firm_name.strip() or 'A firm'} has invited you to join their team on ReconDesk.

{role_desc}

ReconDesk streamlines GSTR-2B reconciliation for CA firms.

Accept invitation: {accept_url}

This invitation expires in 7 days.
"""
    html, plain_body = _base_wrapper("Team invitation", inner, plain)
    return await send_email(to, subj, html, text_content=plain_body)


async def send_payment_receipt_email(
    to: str,
    full_name: str,
    plan: str,
    amount_paise: int,
    payment_id: str,
    purchased_at: datetime | None = None,
) -> bool:
    """Send payment receipt confirmation email to the user."""
    name = escape(full_name.strip() or "there")
    plan_name = plan.capitalize()
    amount_str = _format_in_rupees_indian(amount_paise)
    date_str = (purchased_at or datetime.now(timezone.utc)).strftime("%d %b %Y, %I:%M %p UTC")

    subj = f"Payment Receipt — {plan_name} Pack"

    inner = f"""<p style="margin:0 0 16px;">Hi {name},</p>
<p style="margin:0 0 16px;">Thank you for your purchase! We have successfully received your payment of <strong>{amount_str}</strong> for the <strong>{plan_name}</strong> run credits pack.</p>
<div style="margin:20px 0;padding:16px;background:#f8f9fa;border-radius:8px;font-size:14px;border:1px solid #e9ecef;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
    <tr>
      <td style="padding:4px 0;color:#6c757d;">Pack Type:</td>
      <td style="padding:4px 0;font-weight:600;text-align:right;">{plan_name}</td>
    </tr>
    <tr>
      <td style="padding:4px 0;color:#6c757d;">Amount Paid:</td>
      <td style="padding:4px 0;font-weight:600;text-align:right;">{amount_str}</td>
    </tr>
    <tr>
      <td style="padding:4px 0;color:#6c757d;">Payment ID:</td>
      <td style="padding:4px 0;font-family:monospace;font-size:12px;text-align:right;">{payment_id}</td>
    </tr>
    <tr>
      <td style="padding:4px 0;color:#6c757d;">Date & Time:</td>
      <td style="padding:4px 0;text-align:right;">{date_str}</td>
    </tr>
  </table>
</div>
<p style="margin:16px 0 0;">The run credits have been added to your balance. You can start using them immediately.</p>
{_cta_button(DASHBOARD_URL, "Go to Dashboard")}"""

    plain = f"""Hi {full_name.strip() or 'there'},

Thank you for your purchase! We have successfully received your payment of {amount_str} for the {plan_name} run credits pack.

Purchase Details:
- Pack Type: {plan_name}
- Amount Paid: {amount_str}
- Payment ID: {payment_id}
- Date & Time: {date_str}

The run credits have been added to your balance. You can start using them immediately.

Go to Dashboard: {DASHBOARD_URL}
"""

    html, plain_body = _base_wrapper("Payment receipt", inner, plain)
    return await send_email(to, subj, html, text_content=plain_body)


async def send_runs_expiring_email(
    to: str,
    full_name: str,
    runs_expiring: int,
    expires_at: datetime,
) -> bool:
    """Send credit expiration warning email to the user."""
    name = escape(full_name.strip() or "there")
    date_str = expires_at.strftime("%d %b %Y")

    subj = f"Alert: {runs_expiring} Run Credits Expiring Soon"

    inner = f"""<p style="margin:0 0 16px;">Hi {name},</p>
<p style="margin:0 0 16px;">This is a friendly reminder that you have <strong>{runs_expiring}</strong> run credit(s) expiring on <strong>{date_str}</strong>.</p>
<p style="margin:0 0 16px;color:#c62828;font-weight:600;">As per policy, credit batches expire monthly and do not carry over.</p>
<p style="margin:16px 0 0;">We recommend running your pending reconciliations now to make the most of these credits before they expire.</p>
{_cta_button(DASHBOARD_URL, "Run Reconciliation Now")}"""

    plain = f"""Hi {full_name.strip() or 'there'},

This is a friendly reminder that you have {runs_expiring} run credit(s) expiring on {date_str}.

As per policy, credit batches expire monthly and do not carry over.

We recommend running your pending reconciliations now to make the most of these credits before they expire.

Run Reconciliation Now: {DASHBOARD_URL}
"""

    html, plain_body = _base_wrapper("Credits expiring soon", inner, plain)
    return await send_email(to, subj, html, text_content=plain_body)

