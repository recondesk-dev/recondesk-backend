"""Unit tests for ReconDesk Staging Guard (Phase 5.2).

Verifies fail-closed safeguards protecting production assets from accidental
connection or mutations during staging environment execution.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.staging_guard import (
    PROD_AURORA_HOST_FRAGMENT,
    PROD_COGNITO_CLIENT_ID,
    PROD_COGNITO_USER_POOL_ID,
    PROD_R2_BUCKET,
    StagingIsolationViolationError,
    enforce_staging_safety,
    get_staging_guard_summary,
    verify_staging_safety,
)


def _make_safe_staging_settings(**kwargs) -> Settings:
    """Create a pristine, completely isolated staging Settings object."""
    defaults = {
        "APP_ENV": "staging",
        "DATABASE_URL": "postgresql://postgres:postgres@staging-db:5432/recondesk_staging",
        "AURORA_DATABASE_URL": "postgresql+psycopg2://postgres:postgres@staging-db:5432/recondesk_staging",
        "SUPABASE_DATABASE_URL": "",
        "RAZORPAY_KEY_ID": "rzp_test_mock_12345",
        "R2_BUCKET_NAME": "recondesk-staging-uploads",
        "COGNITO_USER_POOL_ID": "ap-south-1_STAGING001",
        "COGNITO_CLIENT_ID": "staging_client_id_999",
        "SES_SMTP_HOST": "staging-mock",
        "SES_SMTP_USER": "",
        "SES_SMTP_PASS": "",
        "GSTR3B_FILING_ENABLED": False,
    }
    defaults.update(kwargs)
    return Settings(**defaults)


def test_clean_staging_environment_passes():
    """Isolated staging settings must produce zero violations."""
    cfg = _make_safe_staging_settings()
    violations = verify_staging_safety(cfg)
    assert violations == []

    # Must not raise
    enforce_staging_safety(cfg)

    summary = get_staging_guard_summary(cfg)
    assert summary["status"] == "pass"
    assert summary["isolated"] is True
    assert summary["violations_count"] == 0


def test_production_aurora_host_rejected():
    """Pointing to production Aurora cluster must fail closed."""
    cfg = _make_safe_staging_settings(
        AURORA_DATABASE_URL=f"postgresql+psycopg2://admin:secret@{PROD_AURORA_HOST_FRAGMENT}:5432/recondesk"
    )
    violations = verify_staging_safety(cfg)
    assert len(violations) == 1
    assert "production Aurora cluster" in violations[0]

    with pytest.raises(StagingIsolationViolationError) as exc_info:
        enforce_staging_safety(cfg)
    assert "production Aurora cluster" in str(exc_info.value)


def test_production_database_url_rejected():
    """Targeting production RDS host via DATABASE_URL must fail closed."""
    cfg = _make_safe_staging_settings(
        DATABASE_URL=f"postgresql://admin:secret@{PROD_AURORA_HOST_FRAGMENT}:5432/recondesk"
    )
    violations = verify_staging_safety(cfg)
    assert len(violations) == 1
    assert "targets production Aurora cluster" in violations[0]

    with pytest.raises(StagingIsolationViolationError):
        enforce_staging_safety(cfg)


def test_live_razorpay_key_rejected():
    """Configuring live Razorpay keys (rzp_live_*) must fail closed."""
    cfg = _make_safe_staging_settings(
        RAZORPAY_KEY_ID="rzp_live_AbCdEf123456"
    )
    violations = verify_staging_safety(cfg)
    assert any("rzp_live" in v for v in violations)

    with pytest.raises(StagingIsolationViolationError):
        enforce_staging_safety(cfg)


def test_production_r2_bucket_rejected():
    """Targeting the production R2 bucket (recondesk-uploads) must fail closed."""
    cfg = _make_safe_staging_settings(
        R2_BUCKET_NAME=PROD_R2_BUCKET
    )
    violations = verify_staging_safety(cfg)
    assert any("production bucket" in v for v in violations)

    with pytest.raises(StagingIsolationViolationError):
        enforce_staging_safety(cfg)


def test_production_cognito_pool_rejected():
    """Targeting the production Cognito user pool or client must fail closed."""
    cfg = _make_safe_staging_settings(
        COGNITO_USER_POOL_ID=PROD_COGNITO_USER_POOL_ID,
        COGNITO_CLIENT_ID=PROD_COGNITO_CLIENT_ID,
    )
    violations = verify_staging_safety(cfg)
    assert len(violations) == 2
    assert any("production User Pool" in v for v in violations)
    assert any("production App Client" in v for v in violations)

    with pytest.raises(StagingIsolationViolationError):
        enforce_staging_safety(cfg)


def test_live_ses_smtp_credentials_rejected():
    """Targeting AWS SES with active credentials in staging must fail closed."""
    cfg = _make_safe_staging_settings(
        SES_SMTP_HOST="email-smtp.ap-south-1.amazonaws.com",
        SES_SMTP_USER="AKIAIOSFODNN7EXAMPLE",
        SES_SMTP_PASS="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    )
    violations = verify_staging_safety(cfg)
    assert any("Outbound emails to live recipient addresses are forbidden" in v for v in violations)

    with pytest.raises(StagingIsolationViolationError):
        enforce_staging_safety(cfg)


def test_live_gstn_filing_rejected_in_staging():
    """Enabling live GSTR-3B filing in staging must fail closed."""
    cfg = _make_safe_staging_settings(
        GSTR3B_FILING_ENABLED=True
    )
    violations = verify_staging_safety(cfg)
    assert any("GSTR3B_FILING_ENABLED is set to True in staging" in v for v in violations)

    with pytest.raises(StagingIsolationViolationError):
        enforce_staging_safety(cfg)


def test_multiple_simultaneous_violations():
    """Multiple violations must all be reported clearly without truncated exceptions."""
    cfg = _make_safe_staging_settings(
        AURORA_DATABASE_URL=f"postgresql+psycopg2://admin:secret@{PROD_AURORA_HOST_FRAGMENT}:5432/recondesk",
        RAZORPAY_KEY_ID="rzp_live_supersecret",
        R2_BUCKET_NAME=PROD_R2_BUCKET,
        COGNITO_USER_POOL_ID=PROD_COGNITO_USER_POOL_ID,
        GSTR3B_FILING_ENABLED=True,
    )
    violations = verify_staging_safety(cfg)
    assert len(violations) == 5

    summary = get_staging_guard_summary(cfg)
    assert summary["status"] == "violation"
    assert summary["isolated"] is False
    assert summary["violations_count"] == 5

    with pytest.raises(StagingIsolationViolationError) as exc_info:
        enforce_staging_safety(cfg)
    err_text = str(exc_info.value)
    assert "production Aurora cluster" in err_text
    assert "rzp_live" in err_text
    assert "recondesk-uploads" in err_text
    assert "production User Pool" in err_text
    assert "GSTR3B_FILING_ENABLED" in err_text
