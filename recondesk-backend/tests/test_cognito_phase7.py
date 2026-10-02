"""Unit and integration tests for ReconDesk Phase 7 — 100% Cognito Auth Cutover.

Verifies:
1. Cognito self-service signup (/api/v1/auth/cognito/signup).
2. Signup email confirmation and resend code (/confirm-signup, /resend-code).
3. Direct username/password login (/login) with Cognito tokens.
4. Seamless fallback and transparent migration for existing Supabase users.
5. Password recovery flow (/forgot-password, /confirm-forgot-password).
6. Refresh token rotation (/refresh).
7. Global session logout (/logout).
8. Feature flag guard (HTTP 501 when COGNITO_AUTH_ENABLED is False).
9. Tenancy and Aurora user profile / mapping preservation.
"""

from __future__ import annotations

import base64
import json
import uuid
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from app.cognito_config import CognitoConfig, get_cognito_config
from app.cognito_identity import InMemoryCognitoIdentityStore
from app.cognito_aurora_store import get_identity_store, set_identity_store
from app.main import app
from app.services.cognito_service import (
    CognitoService,
    get_cognito_service,
    set_cognito_service,
    compute_secret_hash,
)


@pytest.fixture
def mock_config():
    return CognitoConfig(
        COGNITO_AUTH_ENABLED=True,
        COGNITO_REGION="ap-south-1",
        COGNITO_USER_POOL_ID="ap-south-1_nvlPYMvFh",
        COGNITO_CLIENT_ID="test-client-id",
        COGNITO_CLIENT_SECRET="test-client-secret-1234567890",
        _env_file=None,
    )


@pytest.fixture
def memory_store():
    store = InMemoryCognitoIdentityStore(default_pool_id="ap-south-1_nvlPYMvFh")
    set_identity_store(store)
    yield store
    set_identity_store(None)


@pytest.fixture
def mock_cognito_idp():
    client = MagicMock()
    return client


@pytest.fixture
def cognito_service(mock_config, mock_cognito_idp):
    svc = CognitoService(config=mock_config, client=mock_cognito_idp)
    set_cognito_service(svc)
    yield svc
    set_cognito_service(None)


@pytest.fixture
def client(mock_config, memory_store, cognito_service):
    app.dependency_overrides[get_cognito_config] = lambda: mock_config
    app.dependency_overrides[get_identity_store] = lambda: memory_store
    app.dependency_overrides[get_cognito_service] = lambda: cognito_service

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


# ── SecretHash Calculation Tests ──────────────────────────────────────────────


def test_secret_hash_calculation():
    secret = "test-secret"
    client_id = "test-client"
    username = "user@example.com"
    h = compute_secret_hash(client_id, secret, username)
    assert isinstance(h, str)
    assert len(h) > 0

    # Repeatable
    assert compute_secret_hash(client_id, secret, username) == h


# ── Signup & Confirmation Tests ───────────────────────────────────────────────


@patch("app.routers.cognito_auth.validate_email_mx")
def test_cognito_signup_success(mock_mx, client, mock_cognito_idp, memory_store):
    sub = str(uuid.uuid4())
    mock_cognito_idp.sign_up.return_value = {
        "UserSub": sub,
        "UserConfirmed": False,
        "CodeDeliveryDetails": {
            "DeliveryMedium": "EMAIL",
            "Destination": "t***@example.com",
        },
    }

    resp = client.post(
        "/api/v1/auth/cognito/signup",
        json={
            "email": "testca@example.com",
            "password": "Password123!",
            "full_name": "Test CA",
            "firm_name": "CA & Associates",
            "phone": "9876543210",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["cognito_sub"] == sub
    assert data["user_confirmed"] is False
    assert data["delivery_medium"] == "EMAIL"
    assert "user_id" in data

    # Verify profile and mapping were created in store
    user_id = data["user_id"]
    prof = memory_store.get_user_profile_by_id(user_id)
    assert prof is not None
    assert prof["email"] == "testca@example.com"
    assert prof["full_name"] == "Test CA"

    mapping = memory_store.get_mapping_by_sub(sub)
    assert mapping is not None
    assert mapping.user_id == user_id


@patch("app.routers.cognito_auth.validate_email_mx")
def test_cognito_signup_already_exists(mock_mx, client, mock_cognito_idp):
    mock_cognito_idp.sign_up.side_effect = ClientError(
        {"Error": {"Code": "UsernameExistsException", "Message": "User exists"}},
        "sign_up",
    )

    resp = client.post(
        "/api/v1/auth/cognito/signup",
        json={
            "email": "existing@example.com",
            "password": "Password123!",
            "full_name": "Existing User",
        },
    )
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"].lower()


@patch("app.routers.cognito_auth.validate_email_mx")
def test_cognito_signup_weak_password(mock_mx, client, mock_cognito_idp):
    mock_cognito_idp.sign_up.side_effect = ClientError(
        {"Error": {"Code": "InvalidPasswordException", "Message": "Password does not conform"}},
        "sign_up",
    )

    resp = client.post(
        "/api/v1/auth/cognito/signup",
        json={
            "email": "test@example.com",
            "password": "weakpassword",
            "full_name": "User",
        },
    )
    assert resp.status_code == 400


def test_cognito_confirm_signup_success(client, mock_cognito_idp):
    mock_cognito_idp.confirm_sign_up.return_value = {}

    resp = client.post(
        "/api/v1/auth/cognito/confirm-signup",
        json={
            "email": "user@example.com",
            "confirmation_code": "123456",
        },
    )
    assert resp.status_code == 200
    assert "confirmed successfully" in resp.json()["message"]


def test_cognito_confirm_signup_code_mismatch(client, mock_cognito_idp):
    mock_cognito_idp.confirm_sign_up.side_effect = ClientError(
        {"Error": {"Code": "CodeMismatchException", "Message": "Invalid code"}},
        "confirm_sign_up",
    )

    resp = client.post(
        "/api/v1/auth/cognito/confirm-signup",
        json={
            "email": "user@example.com",
            "confirmation_code": "999999",
        },
    )
    assert resp.status_code == 400
    assert "invalid verification code" in resp.json()["detail"].lower()


def test_cognito_resend_code_success(client, mock_cognito_idp):
    mock_cognito_idp.resend_confirmation_code.return_value = {
        "CodeDeliveryDetails": {"DeliveryMedium": "EMAIL"}
    }

    resp = client.post(
        "/api/v1/auth/cognito/resend-code",
        json={"email": "user@example.com"},
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "Verification code resent successfully."


# ── Direct Login & Fallback Tests ─────────────────────────────────────────────


def _make_dummy_jwt(payload: dict) -> str:
    header = {"alg": "RS256", "typ": "JWT", "kid": "test-kid"}
    h_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    p_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig_b64 = base64.urlsafe_b64encode(b"dummy-signature-1234567890123456").decode().rstrip("=")
    return f"{h_b64}.{p_b64}.{sig_b64}"


@patch("app.routers.cognito_auth.verify_cognito_token")
def test_cognito_login_direct_success(mock_verify, client, mock_cognito_idp, memory_store):
    sub = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    memory_store.create_user_profile(user_id=user_id, email="ca@example.com", full_name="CA User")
    memory_store.pre_provision_mapping(user_id=user_id, cognito_sub=sub, email="ca@example.com")

    access_tok = _make_dummy_jwt({"sub": sub, "token_use": "access", "email": "ca@example.com"})
    mock_cognito_idp.initiate_auth.return_value = {
        "AuthenticationResult": {
            "AccessToken": access_tok,
            "IdToken": "dummy-id-tok",
            "RefreshToken": "dummy-refresh-tok",
            "ExpiresIn": 3600,
            "TokenType": "Bearer",
        }
    }
    mock_verify.return_value = {"sub": sub, "token_use": "access", "email": "ca@example.com"}

    resp = client.post(
        "/api/v1/auth/cognito/login",
        json={"email": "ca@example.com", "password": "ValidPassword123!"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"] == access_tok
    assert data["provider"] == "cognito"
    assert data["user"]["id"] == user_id


def test_cognito_login_unconfirmed_email(client, mock_cognito_idp):
    mock_cognito_idp.initiate_auth.side_effect = ClientError(
        {"Error": {"Code": "UserNotConfirmedException", "Message": "User is not confirmed"}},
        "initiate_auth",
    )

    resp = client.post(
        "/api/v1/auth/cognito/login",
        json={"email": "unconfirmed@example.com", "password": "Password123!"},
    )
    assert resp.status_code == 403
    assert "email address is not confirmed" in resp.json()["detail"].lower()


def test_cognito_login_fallback_to_supabase_removed_fails_closed(
    client, mock_cognito_idp
):
    # Cognito does not know user
    mock_cognito_idp.initiate_auth.side_effect = ClientError(
        {"Error": {"Code": "NotAuthorizedException", "Message": "User does not exist"}},
        "initiate_auth",
    )

    resp = client.post(
        "/api/v1/auth/cognito/login",
        json={"email": "legacy@example.com", "password": "LegacyPassword123!"},
    )
    assert resp.status_code == 401
    assert "incorrect email or password" in resp.json()["detail"].lower()


def test_cognito_login_invalid_credentials_everywhere(client, mock_cognito_idp):
    mock_cognito_idp.initiate_auth.side_effect = ClientError(
        {"Error": {"Code": "NotAuthorizedException", "Message": "Incorrect username or password"}},
        "initiate_auth",
    )

    with patch("app.routers.cognito_auth.get_supabase") as mock_sb:
        mock_sb.return_value.auth.sign_in_with_password.side_effect = Exception("Bad credentials")
        resp = client.post(
            "/api/v1/auth/cognito/login",
            json={"email": "wrong@example.com", "password": "WrongPassword"},
        )
    assert resp.status_code == 401
    assert "incorrect email or password" in resp.json()["detail"].lower()


# ── Password Recovery Tests ───────────────────────────────────────────────────


def test_cognito_forgot_password_success(client, mock_cognito_idp):
    mock_cognito_idp.forgot_password.return_value = {
        "CodeDeliveryDetails": {"DeliveryMedium": "EMAIL", "Destination": "u***@example.com"}
    }

    resp = client.post(
        "/api/v1/auth/cognito/forgot-password",
        json={"email": "user@example.com"},
    )
    assert resp.status_code == 200
    assert "reset code sent" in resp.json()["message"].lower()


def test_cognito_confirm_forgot_password_success(client, mock_cognito_idp):
    mock_cognito_idp.confirm_forgot_password.return_value = {}

    resp = client.post(
        "/api/v1/auth/cognito/confirm-forgot-password",
        json={
            "email": "user@example.com",
            "confirmation_code": "123456",
            "new_password": "NewStrongPassword123!",
        },
    )
    assert resp.status_code == 200
    assert "reset successfully" in resp.json()["message"].lower()


def test_cognito_confirm_forgot_password_bad_code(client, mock_cognito_idp):
    mock_cognito_idp.confirm_forgot_password.side_effect = ClientError(
        {"Error": {"Code": "CodeMismatchException", "Message": "Bad code"}},
        "confirm_forgot_password",
    )

    resp = client.post(
        "/api/v1/auth/cognito/confirm-forgot-password",
        json={
            "email": "user@example.com",
            "confirmation_code": "000000",
            "new_password": "NewStrongPassword123!",
        },
    )
    assert resp.status_code == 400
    assert "invalid verification code" in resp.json()["detail"].lower()


# ── Session Refresh & Logout Tests ────────────────────────────────────────────


def test_cognito_refresh_token_success(client, mock_cognito_idp):
    mock_cognito_idp.initiate_auth.return_value = {
        "AuthenticationResult": {
            "AccessToken": "new-access-tok",
            "IdToken": "new-id-tok",
            "ExpiresIn": 3600,
            "TokenType": "Bearer",
        }
    }

    resp = client.post(
        "/api/v1/auth/cognito/refresh",
        json={"refresh_token": "valid-refresh-tok"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"] == "new-access-tok"


def test_cognito_logout_success(client, mock_cognito_idp):
    mock_cognito_idp.global_sign_out.return_value = {}

    resp = client.post(
        "/api/v1/auth/cognito/logout",
        headers={"Authorization": "Bearer test-access-tok"},
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "Logged out successfully."
    mock_cognito_idp.global_sign_out.assert_called_once_with(AccessToken="test-access-tok")


# ── Disabled Flag Test ────────────────────────────────────────────────────────


def test_endpoints_return_501_when_cognito_disabled(client):
    disabled_cfg = CognitoConfig(COGNITO_AUTH_ENABLED=False, _env_file=None)
    app.dependency_overrides[get_cognito_config] = lambda: disabled_cfg
    try:
        resp = client.post("/api/v1/auth/cognito/signup", json={"email": "a@b.com", "password": "password123", "full_name": "A"})
        assert resp.status_code == 501

        resp = client.post("/api/v1/auth/cognito/login", json={"email": "a@b.com", "password": "password123"})
        assert resp.status_code == 501

        resp = client.post("/api/v1/auth/cognito/forgot-password", json={"email": "a@b.com"})
        assert resp.status_code == 501
    finally:
        app.dependency_overrides.clear()
