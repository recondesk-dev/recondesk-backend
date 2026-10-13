"""Fail-closed staging safety guard for ReconDesk.

Enforces zero accidental interaction with production infrastructure or credentials
when running in a staging or non-production environment.

Checks:
1. Database Isolation: Aborts if any database URL targets production AWS Aurora
   or production database clusters.
2. Payment Isolation: Aborts if live Razorpay keys (rzp_live_*) are configured.
3. Storage Isolation: Aborts if the production Cloudflare R2 bucket (recondesk-uploads)
   is targeted.
4. Identity Isolation: Aborts if the live AWS Cognito User Pool (ap-south-1_nvlPYMvFh)
   or production App Client is targeted.
5. Notification Isolation: Aborts if live AWS SES SMTP credentials are configured
   for outbound email dispatch.
6. Filing Safety: Aborts if live GSTN filing is enabled in staging.
"""

from __future__ import annotations

import logging
import re
from typing import Any, List, Optional
from urllib.parse import urlparse

from app.config import Settings, get_settings

_log = logging.getLogger("recondesk.staging_guard")

# Prohibited production identifiers
PROD_AURORA_HOST_FRAGMENT = "recondesk.cluster-cre2mcouo1xv.ap-south-1.rds.amazonaws.com"
PROD_R2_BUCKET = "recondesk-uploads"
PROD_COGNITO_USER_POOL_ID = "ap-south-1_nvlPYMvFh"
PROD_COGNITO_CLIENT_ID = "2qui5lp7if0g4lftbrag7o6sce"
PROD_SES_HOST_PREFIX = "email-smtp."


class StagingIsolationViolationError(RuntimeError):
    """Raised when a staging environment violates strict isolation safeguards."""

    def __init__(self, violations: List[str]) -> None:
        self.violations = violations
        msg = (
            "STAGING ISOLATION SAFETY VIOLATION: Execution aborted to protect production assets.\n"
            + "\n".join(f"  - [VIOLATION] {v}" for v in violations)
        )
        super().__init__(msg)


def _check_db_url(url_str: str, param_name: str) -> Optional[str]:
    """Inspect database URL for production cluster hostnames."""
    if not url_str:
        return None
    trimmed = url_str.strip().strip('"').strip("'")
    try:
        from sqlalchemy.engine.url import make_url

        try:
            u = make_url(trimmed)
            host = (u.host or "").lower()
            database = (u.database or "").lower()
        except Exception:
            # Fallback to regex host extractor
            clean_url = re.sub(r"^[a-zA-Z0-9_+.-]+://", "http://", trimmed)
            parsed = urlparse(clean_url)
            host = (parsed.hostname or "").lower()
            database = (parsed.path or "").lower()

        if PROD_AURORA_HOST_FRAGMENT in host:
            return (
                f"{param_name} targets production Aurora cluster: '{host}'. "
                "Staging must use an isolated PostgreSQL database (e.g., staging-db:5432)."
            )
        if "rds.amazonaws.com" in host and "recondesk" in host and "staging" not in host:
            return (
                f"{param_name} targets an AWS RDS instance with production identifiers: '{host}'. "
                "Staging must use an isolated staging database."
            )
        if "recondesk_prod" in database or database == "recondesk" and host != "staging-db" and "localhost" not in host and "127.0.0.1" not in host:
            if "prod" in database:
                return (
                    f"{param_name} database name '{database}' contains production keywords. "
                    "Staging must target a dedicated staging database (e.g. /recondesk_staging)."
                )
    except Exception as exc:
        _log.warning("staging_guard: unable to parse %s: %s", param_name, exc)
    return None


def verify_staging_safety(settings: Optional[Settings] = None) -> List[str]:
    """Audit settings for any production leakage or unsafe configurations.

    Returns a list of violation strings. An empty list indicates a clean,
    isolated staging environment.
    """
    cfg = settings or get_settings()
    violations: List[str] = []

    # 1. Database isolation checks
    aurora_v = _check_db_url(cfg.AURORA_DATABASE_URL, "AURORA_DATABASE_URL")
    if aurora_v:
        violations.append(aurora_v)

    db_v = _check_db_url(cfg.DATABASE_URL, "DATABASE_URL")
    if db_v:
        violations.append(db_v)

    supa_db_v = _check_db_url(cfg.SUPABASE_DATABASE_URL, "SUPABASE_DATABASE_URL")
    if supa_db_v:
        violations.append(supa_db_v)

    # 2. Razorpay live key check
    rzp_key = (cfg.RAZORPAY_KEY_ID or "").strip()
    if rzp_key.startswith("rzp_live"):
        violations.append(
            f"RAZORPAY_KEY_ID starts with 'rzp_live'. Live payment processing keys are forbidden in staging."
        )

    # 3. Cloudflare R2 bucket check
    r2_bucket = (cfg.R2_BUCKET_NAME or "").strip().lower()
    if r2_bucket == PROD_R2_BUCKET.lower():
        violations.append(
            f"R2_BUCKET_NAME is set to '{cfg.R2_BUCKET_NAME}' (production bucket). "
            "Staging must use 'recondesk-staging-uploads' or local mock storage."
        )

    # 4. Amazon Cognito isolation check
    pool_id = (cfg.COGNITO_USER_POOL_ID or "").strip()
    if pool_id == PROD_COGNITO_USER_POOL_ID:
        violations.append(
            f"COGNITO_USER_POOL_ID is set to '{pool_id}' (production User Pool). "
            "Staging must use an isolated staging user pool or disable Cognito auth."
        )
    client_id = (cfg.COGNITO_CLIENT_ID or "").strip()
    if client_id == PROD_COGNITO_CLIENT_ID:
        violations.append(
            f"COGNITO_CLIENT_ID is set to '{client_id}' (production App Client). "
            "Staging must use an isolated staging app client."
        )

    # 5. Amazon SES isolation check
    ses_host = (cfg.SES_SMTP_HOST or "").strip().lower()
    ses_user = (cfg.SES_SMTP_USER or "").strip()
    ses_pass = (cfg.SES_SMTP_PASS or "").strip()
    if PROD_SES_HOST_PREFIX in ses_host and (ses_user or ses_pass):
        violations.append(
            f"SES_SMTP_HOST points to '{cfg.SES_SMTP_HOST}' with active credentials. "
            "Outbound emails to live recipient addresses are forbidden in staging. "
            "Use mock SMTP (e.g. MailHog / staging-mock) or leave credentials unset."
        )

    # 6. GSTN live filing safety check
    if cfg.GSTR3B_FILING_ENABLED:
        violations.append(
            "GSTR3B_FILING_ENABLED is set to True in staging. "
            "Live filing and ledger offset must remain False in staging to prevent financial mutation."
        )

    return violations


def enforce_staging_safety(settings: Optional[Settings] = None) -> None:
    """Fail-closed assertion: raises StagingIsolationViolationError if any violation exists."""
    violations = verify_staging_safety(settings)
    if violations:
        for v in violations:
            _log.critical("[STAGING SAFETY BLOCK] %s", v)
        raise StagingIsolationViolationError(violations)
    _log.info("Staging isolation verified: zero production resource references detected.")


def get_staging_guard_summary(settings: Optional[Settings] = None) -> dict[str, Any]:
    """Generate a clean, credentials-free summary of staging guard status."""
    cfg = settings or get_settings()
    violations = verify_staging_safety(cfg)
    return {
        "status": "pass" if not violations else "violation",
        "isolated": len(violations) == 0,
        "environment": cfg.APP_ENV,
        "violations_count": len(violations),
        "violations": violations,
    }
