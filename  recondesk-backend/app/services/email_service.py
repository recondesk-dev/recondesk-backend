"""Backward-compatible sync/async helpers; prefer :mod:`app.utils.email` for new code."""

from __future__ import annotations

from html import escape


async def send_legacy_reconciliation_job_email_async(
    to: str, job_name: str, summary: dict
) -> bool:
    """Email for spreadsheet-style ``/reconciliation/jobs`` runs."""
    from app.utils.email import BRAND, send_email, wrap_branded_email  # noqa: PLC0415

    name_e = escape(job_name)
    inner = f"""<p style="margin:0 0 16px;">Your reconciliation job <strong>{name_e}</strong> has finished.</p>
<ul style="margin:0 0 16px;padding-left:20px;">
  <li>Total rows: {int(summary.get("total") or 0)}</li>
  <li>Matched: {int(summary.get("matched") or 0)}</li>
  <li>Partial: {int(summary.get("partial") or 0)}</li>
  <li>Unmatched: {int(summary.get("unmatched") or 0)}</li>
</ul>
<p style="margin:0;"><a href="https://recondesk.in/dashboard" style="color:{BRAND};font-weight:600;">Open ReconDesk →</a></p>"""

    plain = f"""Your reconciliation job '{job_name}' has finished.

Total rows: {int(summary.get("total") or 0)}
Matched: {int(summary.get("matched") or 0)}
Partial: {int(summary.get("partial") or 0)}
Unmatched: {int(summary.get("unmatched") or 0)}

Open ReconDesk: https://recondesk.in/dashboard
"""
    html, plain_body = wrap_branded_email("Job complete", inner, plain)
    return await send_email(
        to,
        f"[ReconDesk] Job '{job_name}' completed",
        html,
        text_content=plain_body,
    )


async def send_password_reset_email_async(to: str, reset_link: str) -> bool:
    from app.utils.email import BRAND, send_email, wrap_branded_email  # noqa: PLC0415

    link_e = escape(reset_link)
    inner = f"""<h2 style="margin:0 0 16px;font-size:18px;">Reset your ReconDesk password</h2>
<p style="margin:0 0 16px;">Click the link below to reset your password. This link expires in 1 hour.</p>
<p style="margin:0 0 16px;"><a href="{link_e}" style="display:inline-block;background:{BRAND};color:#ffffff;text-decoration:none;font-weight:600;padding:12px 24px;border-radius:8px;">Reset Password</a></p>
<p style="margin:0;font-size:13px;color:#666;">If you didn't request this, please ignore this email.</p>"""

    plain = f"""Reset your ReconDesk password

Click the link (expires in 1 hour):
{reset_link}

If you didn't request this, ignore this email.
"""
    html, plain_body = wrap_branded_email("Password reset", inner, plain)
    return await send_email(to, "Reset your ReconDesk password", html, text_content=plain_body)
