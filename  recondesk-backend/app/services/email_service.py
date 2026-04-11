import resend

from app.config import settings

resend.api_key = settings.RESEND_API_KEY


def send_email(to: str, subject: str, html: str) -> dict:
    """Send a transactional email via Resend."""
    params: resend.Emails.SendParams = {
        "from": settings.EMAIL_FROM,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    return resend.Emails.send(params)


def send_welcome_email(to: str, full_name: str) -> dict:
    html = f"""
    <h2>Welcome to ReconDesk, {full_name}!</h2>
    <p>Your account is ready. Start reconciling your data in minutes.</p>
    <p><a href="https://app.recondesk.com">Open ReconDesk →</a></p>
    """
    return send_email(to, "Welcome to ReconDesk", html)


def send_reconciliation_complete_email(to: str, job_name: str, summary: dict) -> dict:
    html = f"""
    <h2>Reconciliation Complete: {job_name}</h2>
    <ul>
        <li>Total rows: {summary.get('total', 0)}</li>
        <li>Matched: {summary.get('matched', 0)}</li>
        <li>Partial: {summary.get('partial', 0)}</li>
        <li>Unmatched: {summary.get('unmatched', 0)}</li>
    </ul>
    <p><a href="https://app.recondesk.com/jobs">View Results →</a></p>
    """
    return send_email(to, f"[ReconDesk] Job '{job_name}' completed", html)


def send_password_reset_email(to: str, reset_link: str) -> dict:
    html = f"""
    <h2>Reset your ReconDesk password</h2>
    <p>Click the link below to reset your password. This link expires in 1 hour.</p>
    <p><a href="{reset_link}">Reset Password →</a></p>
    <p>If you didn't request this, please ignore this email.</p>
    """
    return send_email(to, "Reset your ReconDesk password", html)
