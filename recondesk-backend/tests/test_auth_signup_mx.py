"""Tests for email domain MX record validation on signup and typo detection."""

from unittest.mock import MagicMock, patch
import dns.resolver
import dns.exception
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.utils.email_domain import (
    INVALID_EMAIL_DOMAIN_DETAIL,
    has_mx_record,
    validate_email_mx,
)


# ── 1. Unit Tests for has_mx_record ──────────────────────────────────────────

def test_has_mx_record_invalid_inputs():
    """Empty or malformed email/domain inputs must return False."""
    assert has_mx_record("") is False
    assert has_mx_record("notanemail") is False
    assert has_mx_record("@") is False
    assert has_mx_record("user@") is False
    assert has_mx_record("user@nodot") is False


def test_has_mx_record_nxdomain_fails():
    """Nonexistent domain (NXDOMAIN) must return False."""
    with patch("dns.resolver.Resolver.resolve", side_effect=dns.resolver.NXDOMAIN()):
        assert has_mx_record("test@nonexistent-domain-12345xyz.com") is False
        assert has_mx_record("nonexistent-domain-12345xyz.com") is False


def test_has_mx_record_no_answer_fails():
    """Domain with no MX records (NoAnswer) must return False."""
    with patch("dns.resolver.Resolver.resolve", side_effect=dns.resolver.NoAnswer()):
        assert has_mx_record("test@nomx-domain-12345xyz.com") is False


def test_has_mx_record_no_nameservers_fails():
    """DNS failure (NoNameservers) must return False."""
    with patch("dns.resolver.Resolver.resolve", side_effect=dns.resolver.NoNameservers()):
        assert has_mx_record("test@broken-dns-domain.com") is False


def test_has_mx_record_timeout_fails():
    """DNS resolution timeout must return False."""
    with patch("dns.resolver.Resolver.resolve", side_effect=dns.resolver.LifetimeTimeout()):
        assert has_mx_record("test@timeout-domain.com") is False


def test_has_mx_record_valid_domain():
    """Domain with valid MX records returns True."""
    mock_mx = MagicMock()
    mock_mx.exchange = "mail.example.com"
    with patch("dns.resolver.Resolver.resolve", return_value=[mock_mx]):
        assert has_mx_record("test@gmail.com") is True
        assert has_mx_record("gmail.com") is True


# ── 2. Unit Tests for validate_email_mx ───────────────────────────────────────

def test_validate_email_mx_raises_400_on_invalid():
    """validate_email_mx raises HTTPException(400) with required typo warning message."""
    with patch("app.utils.email_domain.has_mx_record", return_value=False):
        with pytest.raises(HTTPException) as exc_info:
            validate_email_mx("test@nonexistent-domain.com")
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == INVALID_EMAIL_DOMAIN_DETAIL


def test_validate_email_mx_passes_on_valid():
    """validate_email_mx does not raise on valid domains."""
    with patch("app.utils.email_domain.has_mx_record", return_value=True):
        validate_email_mx("test@gmail.com")


# ── 3. Integration Tests for POST /api/v1/auth/signup ─────────────────────────

def test_signup_fails_with_nonexistent_domain_mx(client: TestClient):
    """Signup endpoint rejects nonexistent domain with clear 400 error before user creation."""
    with patch("app.utils.email_domain.has_mx_record", return_value=False):
        response = client.post(
            "/api/v1/auth/signup",
            json={
                "email": "omkar@nonexistent-domain-xyz-404.com",
                "password": "StrongPassword123!",
                "full_name": "Omkar Kadam",
                "firm_name": "Kadam & Co",
                "phone": "9876543210",
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == INVALID_EMAIL_DOMAIN_DETAIL


def test_signup_passes_mx_check_on_valid_domain(client: TestClient):
    """Signup endpoint passes MX validation for valid email domain."""
    from app.routers.cognito_auth import CognitoSignupResponse
    mock_cognito_res = CognitoSignupResponse(
        user_id="11111111-1111-1111-1111-111111111111",
        message="Sign up successful.",
        cognito_sub="cog-sub-123",
        user_confirmed=False,
    )

    with (
        patch("app.utils.email_domain.has_mx_record", return_value=True),
        patch("app.routers.cognito_auth.cognito_signup", return_value=mock_cognito_res),
        patch("app.routers.auth.log_action", return_value=None),
    ):
        response = client.post(
            "/api/v1/auth/signup",
            json={
                "email": "kadamomkar9988@gmail.com",
                "password": "StrongPassword123!",
                "full_name": "Omkar Kadam",
                "firm_name": "Kadam & Co",
                "phone": "9876543210",
            },
        )
        assert response.status_code == 201
        assert response.json()["user_id"] == "11111111-1111-1111-1111-111111111111"
