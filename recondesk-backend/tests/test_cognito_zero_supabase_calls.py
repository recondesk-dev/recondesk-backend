from __future__ import annotations

import base64
import json
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from app.cognito_aurora_store import set_identity_store
from app.cognito_config import CognitoConfig, get_cognito_config
from app.cognito_identity import InMemoryCognitoIdentityStore
from app.cognito_verifier import verify_cognito_token
from app.auth import get_current_user, AuthenticatedUser
from app.main import app
from app.services.cognito_service import get_cognito_service


def _make_dummy_jwt(payload: dict) -> str:
    header = {"alg": "RS256", "typ": "JWT", "kid": "test-kid"}
    h_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    p_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig_b64 = base64.urlsafe_b64encode(b"dummy-sig-12345678901234567890").decode().rstrip("=")
    return f"{h_b64}.{p_b64}.{sig_b64}"


@pytest.fixture
def mock_sb_auth():
    """Mock Supabase client that tracks any and all calls to .auth attributes."""
    sb = MagicMock()
    # auth and all its methods/properties will be Mock instances
    sb.auth = MagicMock()
    sb.auth.sign_in_with_password = MagicMock()
    sb.auth.sign_up = MagicMock()
    sb.auth.get_user = MagicMock()
    sb.auth.admin = MagicMock()
    sb.auth.admin.get_user_by_id = MagicMock()
    return sb


@pytest.fixture
def test_env(mock_sb_auth):
    store = InMemoryCognitoIdentityStore()
    set_identity_store(store)

    mock_idp = MagicMock()
    cognito_cfg = CognitoConfig(
        COGNITO_REGION="ap-south-1",
        COGNITO_USER_POOL_ID="ap-south-1_nvlPYMvFh",
        COGNITO_CLIENT_ID="2qui5lp7if0g4lftbrag7o6sce",
        COGNITO_CLIENT_SECRET="test-secret-key",
        COGNITO_AUTH_ENABLED=True,
        _env_file=None,
    )

    from app.services.cognito_service import CognitoService
    service = CognitoService(config=cognito_cfg, client=mock_idp)

    app.dependency_overrides[get_cognito_config] = lambda: cognito_cfg
    app.dependency_overrides[get_cognito_service] = lambda: service

    with patch("app.routers.cognito_auth.get_supabase", return_value=mock_sb_auth), \
         patch("app.auth.get_supabase", return_value=mock_sb_auth), \
         patch("app.database.get_supabase", return_value=mock_sb_auth), \
         patch("app.auth.get_cognito_config", return_value=cognito_cfg), \
         patch("app.cognito_verifier.get_cognito_config", return_value=cognito_cfg):
        client = TestClient(app, raise_server_exceptions=False)
        yield {
            "client": client,
            "mock_idp": mock_idp,
            "store": store,
            "cfg": cognito_cfg,
            "mock_sb_auth": mock_sb_auth,
        }

    app.dependency_overrides.clear()
    set_identity_store(None)


@patch("app.routers.cognito_auth.validate_email_mx")
def test_zero_supabase_calls_on_signup(mock_mx, test_env):
    """Test 1: Normal Cognito signup does ZERO Supabase Auth calls."""
    mock_idp = test_env["mock_idp"]
    client = test_env["client"]
    sb = test_env["mock_sb_auth"]

    mock_idp.sign_up.return_value = {
        "UserSub": str(uuid.uuid4()),
        "UserConfirmed": False,
        "CodeDeliveryDetails": {"DeliveryMedium": "EMAIL", "Destination": "u***@example.com"},
    }

    resp = client.post(
        "/api/v1/auth/cognito/signup",
        json={
            "email": "fresh-user@example.com",
            "password": "StrongPassword123!",
            "full_name": "Fresh User",
            "firm_name": "Fresh CA Firm",
            "phone": "9876543210",
        },
    )
    assert resp.status_code in (200, 201)

    # Ensure zero calls to sb.auth
    assert sb.auth.sign_up.call_count == 0
    assert sb.auth.sign_in_with_password.call_count == 0
    assert sb.auth.get_user.call_count == 0
    assert sb.auth.admin.get_user_by_id.call_count == 0
    assert len(sb.auth.mock_calls) == 0, f"sb.auth was called: {sb.auth.mock_calls}"


def test_zero_supabase_calls_on_confirm_signup(test_env):
    """Test 2: Normal Cognito email confirmation does ZERO Supabase Auth calls."""
    mock_idp = test_env["mock_idp"]
    client = test_env["client"]
    sb = test_env["mock_sb_auth"]

    mock_idp.confirm_sign_up.return_value = {}

    resp = client.post(
        "/api/v1/auth/cognito/confirm-signup",
        json={
            "email": "fresh-user@example.com",
            "confirmation_code": "123456",
        },
    )
    assert resp.status_code == 200
    assert len(sb.auth.mock_calls) == 0


def test_zero_supabase_calls_on_resend_code(test_env):
    """Test 3: Resending verification code does ZERO Supabase Auth calls."""
    mock_idp = test_env["mock_idp"]
    client = test_env["client"]
    sb = test_env["mock_sb_auth"]

    mock_idp.resend_confirmation_code.return_value = {
        "CodeDeliveryDetails": {"DeliveryMedium": "EMAIL"}
    }

    resp = client.post(
        "/api/v1/auth/cognito/resend-code",
        json={"email": "fresh-user@example.com"},
    )
    assert resp.status_code == 200
    assert len(sb.auth.mock_calls) == 0


@patch("app.routers.cognito_auth.verify_cognito_token")
def test_zero_supabase_calls_on_normal_login(mock_verify, test_env):
    """Test 4: Normal Cognito login does ZERO Supabase Auth calls."""
    mock_idp = test_env["mock_idp"]
    client = test_env["client"]
    store = test_env["store"]
    sb = test_env["mock_sb_auth"]

    user_id = str(uuid.uuid4())
    cognito_sub = str(uuid.uuid4())
    email = "active-ca@example.com"

    # Pre-provision user and mapping in Aurora store
    store.create_user_profile(user_id=user_id, email=email, full_name="Active CA")
    store.pre_provision_mapping(
        user_id=user_id,
        cognito_sub=cognito_sub,
        email=email,
        pool_id=test_env["cfg"].COGNITO_USER_POOL_ID,
    )

    access_tok = _make_dummy_jwt({"sub": cognito_sub, "token_use": "access", "email": email})
    mock_idp.initiate_auth.return_value = {
        "AuthenticationResult": {
            "AccessToken": access_tok,
            "IdToken": "id-token-abc",
            "RefreshToken": "refresh-token-xyz",
            "ExpiresIn": 3600,
            "TokenType": "Bearer",
        }
    }
    mock_verify.return_value = {"sub": cognito_sub, "token_use": "access", "email": email}

    resp = client.post(
        "/api/v1/auth/cognito/login",
        json={"email": email, "password": "StrongPassword123!"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "cognito"
    assert data["user"]["id"] == user_id

    # ZERO calls to sb.auth
    assert sb.auth.sign_in_with_password.call_count == 0
    assert len(sb.auth.mock_calls) == 0, f"sb.auth was called: {sb.auth.mock_calls}"


def test_zero_supabase_calls_on_forgot_password(test_env):
    """Test 5: Password recovery initialization does ZERO Supabase Auth calls."""
    mock_idp = test_env["mock_idp"]
    client = test_env["client"]
    sb = test_env["mock_sb_auth"]

    mock_idp.forgot_password.return_value = {
        "CodeDeliveryDetails": {"DeliveryMedium": "EMAIL", "Destination": "u***@example.com"}
    }

    resp = client.post(
        "/api/v1/auth/cognito/forgot-password",
        json={"email": "active-ca@example.com"},
    )
    assert resp.status_code == 200
    assert len(sb.auth.mock_calls) == 0


def test_zero_supabase_calls_on_confirm_forgot_password(test_env):
    """Test 6: Password reset confirmation does ZERO Supabase Auth calls."""
    mock_idp = test_env["mock_idp"]
    client = test_env["client"]
    sb = test_env["mock_sb_auth"]

    mock_idp.confirm_forgot_password.return_value = {}

    resp = client.post(
        "/api/v1/auth/cognito/confirm-forgot-password",
        json={
            "email": "active-ca@example.com",
            "confirmation_code": "123456",
            "new_password": "NewStrongPassword123!",
        },
    )
    assert resp.status_code == 200
    assert len(sb.auth.mock_calls) == 0


def test_zero_supabase_calls_on_token_refresh(test_env):
    """Test 7: Cognito token refresh does ZERO Supabase Auth calls."""
    mock_idp = test_env["mock_idp"]
    client = test_env["client"]
    sb = test_env["mock_sb_auth"]

    mock_idp.initiate_auth.return_value = {
        "AuthenticationResult": {
            "AccessToken": "new-access-tok-123",
            "ExpiresIn": 3600,
            "TokenType": "Bearer",
        }
    }

    resp = client.post(
        "/api/v1/auth/cognito/refresh",
        json={"refresh_token": "valid-cognito-refresh-tok"},
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"] == "new-access-tok-123"
    assert len(sb.auth.mock_calls) == 0


def test_zero_supabase_calls_on_logout(test_env):
    """Test 8: Cognito logout does ZERO Supabase Auth calls."""
    mock_idp = test_env["mock_idp"]
    client = test_env["client"]
    sb = test_env["mock_sb_auth"]

    mock_idp.global_sign_out.return_value = {}

    resp = client.post(
        "/api/v1/auth/cognito/logout",
        headers={"Authorization": "Bearer test-access-tok"},
    )
    assert resp.status_code == 200
    assert len(sb.auth.mock_calls) == 0


@pytest.mark.asyncio
@patch("app.auth.verify_cognito_token")
@patch("app.cognito_verifier.verify_cognito_token")
async def test_zero_supabase_calls_on_protected_api_route(mock_cv_verify, mock_auth_verify, test_env):
    """Test 9: Protected route request using Cognito JWT does ZERO Supabase Auth calls."""
    store = test_env["store"]
    sb = test_env["mock_sb_auth"]
    client = test_env["client"]

    user_id = str(uuid.uuid4())
    cognito_sub = str(uuid.uuid4())
    pool_id = test_env["cfg"].COGNITO_USER_POOL_ID

    store.create_user_profile(user_id=user_id, email="ca@example.com", full_name="CA User", role="admin")
    store.pre_provision_mapping(user_id=user_id, cognito_sub=cognito_sub, email="ca@example.com", pool_id=pool_id)

    access_tok = _make_dummy_jwt({
        "sub": cognito_sub,
        "token_use": "access",
        "iss": f"https://cognito-idp.ap-south-1.amazonaws.com/{pool_id}",
        "client_id": test_env["cfg"].COGNITO_CLIENT_ID,
    })
    token_claims = {
        "sub": cognito_sub,
        "token_use": "access",
        "iss": f"https://cognito-idp.ap-south-1.amazonaws.com/{pool_id}",
        "client_id": test_env["cfg"].COGNITO_CLIENT_ID,
    }
    mock_auth_verify.return_value = token_claims
    mock_cv_verify.return_value = token_claims

    # 1. Test get_current_user dependency directly
    from fastapi.security import HTTPAuthorizationCredentials
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=access_tok)
    auth_user = await get_current_user(credentials=creds, store=store)
    assert auth_user.id == user_id
    assert auth_user.auth_provider == "cognito"
    assert auth_user.provider_subject == cognito_sub

    # 2. Test protected endpoint /api/v1/auth/cognito/me
    resp = client.get(
        "/api/v1/auth/cognito/me",
        headers={"Authorization": f"Bearer {access_tok}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == user_id

    # ZERO calls to sb.auth
    assert sb.auth.get_user.call_count == 0
    assert len(sb.auth.mock_calls) == 0


@pytest.mark.asyncio
@patch("app.auth.verify_cognito_token")
@patch("app.cognito_verifier.verify_cognito_token")
async def test_tenant_isolation_with_cognito_identities(mock_cv_verify, mock_auth_verify, test_env):
    """Test 10: Multi-tenant isolation: Cognito Sub A cannot resolve to User B."""
    store = test_env["store"]
    pool_id = test_env["cfg"].COGNITO_USER_POOL_ID
    client = test_env["client"]

    user_a_id = str(uuid.uuid4())
    sub_a = str(uuid.uuid4())
    store.create_user_profile(user_id=user_a_id, email="tenant_a@example.com", full_name="Tenant A")
    store.pre_provision_mapping(user_id=user_a_id, cognito_sub=sub_a, email="tenant_a@example.com", pool_id=pool_id)

    user_b_id = str(uuid.uuid4())
    sub_b = str(uuid.uuid4())
    store.create_user_profile(user_id=user_b_id, email="tenant_b@example.com", full_name="Tenant B")
    store.pre_provision_mapping(user_id=user_b_id, cognito_sub=sub_b, email="tenant_b@example.com", pool_id=pool_id)

    tok_a = _make_dummy_jwt({"sub": sub_a, "token_use": "access", "iss": f"https://cognito-idp.ap-south-1.amazonaws.com/{pool_id}"})
    claims_a = {"sub": sub_a, "token_use": "access", "iss": f"https://cognito-idp.ap-south-1.amazonaws.com/{pool_id}"}
    mock_auth_verify.return_value = claims_a
    mock_cv_verify.return_value = claims_a

    from fastapi.security import HTTPAuthorizationCredentials
    auth_a = await get_current_user(credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=tok_a), store=store)
    assert auth_a.id == user_a_id
    assert auth_a.id != user_b_id

    resp = client.get(
        "/api/v1/auth/cognito/me",
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    assert resp.status_code == 200
    assert resp.json()["user_id"] == user_a_id
    assert resp.json()["user_id"] != user_b_id
