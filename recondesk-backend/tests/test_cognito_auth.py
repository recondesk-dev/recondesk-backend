from __future__ import annotations

import base64
import time
import uuid
from typing import Any, Optional

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.cognito_config import CognitoConfig
from app.cognito_identity import (
    CognitoAccountConflictError,
    CognitoAccountLinkingRequiredError,
    CognitoIdentityError,
    CognitoIdentityMapping,
    InMemoryCognitoIdentityStore,
    complete_account_linking,
    is_strict_email_verified,
    resolve_cognito_user_id,
)
from app.cognito_verifier import (
    CognitoTokenExpiredError,
    CognitoTokenInvalidError,
    set_cognito_jwks_cache_for_testing,
    verify_cognito_token,
)
from app.main import app
from app.routers.cognito_auth import get_identity_store


def _int_to_base64url(n: int) -> str:
    byte_len = (n.bit_length() + 7) // 8
    b = n.to_bytes(byte_len, byteorder="big")
    return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")


@pytest.fixture(scope="module")
def rsa_key_pair():
    """Generate an RSA key pair for testing token signing and verification."""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_numbers = priv.public_key().public_numbers()
    kid = "test-cognito-key-1"
    jwk = {
        "kty": "RSA",
        "alg": "RS256",
        "use": "sig",
        "kid": kid,
        "n": _int_to_base64url(pub_numbers.n),
        "e": _int_to_base64url(pub_numbers.e),
    }
    jwks = {"keys": [jwk]}
    return priv, jwk, jwks


@pytest.fixture
def cognito_test_config():
    return CognitoConfig(
        COGNITO_REGION="ap-south-1",
        COGNITO_USER_POOL_ID="ap-south-1_nvIPYMvFh",
        COGNITO_CLIENT_ID="2qui5lp7if0g4lftbrag7o6sce",
        COGNITO_CLIENT_SECRET="test-server-side-secret-do-not-leak",
        COGNITO_REDIRECT_URI="http://localhost:3000/api/auth/cognito/callback",
        COGNITO_LOGOUT_URI="http://localhost:3000/login",
        COGNITO_AUTH_ENABLED=True,
    )


def _sign_test_token(
    private_key,
    claims: dict[str, Any],
    kid: str = "test-cognito-key-1",
    algorithm: str = "RS256",
) -> str:
    headers = {"kid": kid, "alg": algorithm}
    return pyjwt.encode(claims, private_key, algorithm=algorithm, headers=headers)


# ─── 1. Configuration Tests ──────────────────────────────────────────────────

class TestCognitoConfig:
    def test_default_config_matches_development_environment(self):
        cfg = CognitoConfig()
        assert cfg.COGNITO_REGION == "ap-south-1"
        assert cfg.COGNITO_USER_POOL_ID == "ap-south-1_nvIPYMvFh"
        assert cfg.COGNITO_CLIENT_ID == "2qui5lp7if0g4lftbrag7o6sce"
        assert cfg.COGNITO_REDIRECT_URI == "http://localhost:3000/api/auth/cognito/callback"
        assert cfg.COGNITO_LOGOUT_URI == "http://localhost:3000/login"
        assert cfg.COGNITO_AUTH_ENABLED is False  # Safe default: disabled

    def test_issuer_and_jwks_url_calculation(self):
        cfg = CognitoConfig(
            COGNITO_REGION="ap-south-1",
            COGNITO_USER_POOL_ID="ap-south-1_nvIPYMvFh",
        )
        assert cfg.issuer == "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_nvIPYMvFh"
        assert cfg.jwks_url == "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_nvIPYMvFh/.well-known/jwks.json"

    def test_client_secret_is_never_logged_or_exposed_in_repr(self):
        secret = "super-secret-client-credential-12345"
        cfg = CognitoConfig(COGNITO_CLIENT_SECRET=secret)
        repr_str = repr(cfg)
        safe_dict = cfg.get_safe_dict()

        assert secret not in repr_str
        assert "has_client_secret" in safe_dict
        assert safe_dict["has_client_secret"] is True
        assert secret not in str(safe_dict)

    def test_cognito_domain_endpoint_construction(self):
        cfg = CognitoConfig(
            COGNITO_DOMAIN="https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com",
            COGNITO_REGION="ap-south-1",
        )
        assert cfg.domain_url == "https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com"
        assert cfg.authorize_url == "https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com/oauth2/authorize"
        assert cfg.token_url == "https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com/oauth2/token"
        safe = cfg.get_safe_dict()
        assert safe["domain"] == "https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com"
        assert safe["domain_url"] == "https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com"
        assert safe["authorize_url"] == "https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com/oauth2/authorize"
        assert safe["token_url"] == "https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com/oauth2/token"

    def test_cognito_domain_prefix_construction(self):
        cfg = CognitoConfig(
            COGNITO_DOMAIN="ap-south-1nvlpymvfh",
            COGNITO_REGION="ap-south-1",
        )
        assert cfg.domain_url == "https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com"
        assert cfg.authorize_url == "https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com/oauth2/authorize"
        assert cfg.token_url == "https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com/oauth2/token"

    def test_cognito_domain_trailing_slash_normalization(self):
        cfg = CognitoConfig(
            COGNITO_DOMAIN="https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com///",
            COGNITO_REGION="ap-south-1",
        )
        assert cfg.domain_url == "https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com"
        assert cfg.authorize_url == "https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com/oauth2/authorize"
        assert cfg.token_url == "https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com/oauth2/token"

    def test_missing_domain_handling(self):
        cfg = CognitoConfig(COGNITO_DOMAIN="")
        with pytest.raises(ValueError, match="COGNITO_DOMAIN is not configured"):
            _ = cfg.domain_url
        with pytest.raises(ValueError, match="COGNITO_DOMAIN is not configured"):
            _ = cfg.authorize_url
        with pytest.raises(ValueError, match="COGNITO_DOMAIN is not configured"):
            _ = cfg.token_url
        safe = cfg.get_safe_dict()
        assert safe["domain"] is None
        assert safe["domain_url"] is None
        assert safe["authorize_url"] is None
        assert safe["token_url"] is None


# ─── 2. JWT Verification Tests ───────────────────────────────────────────────

class TestCognitoJWTVerification:
    def test_verify_valid_id_token(self, rsa_key_pair, cognito_test_config):
        priv, _, jwks = rsa_key_pair
        now = int(time.time())
        claims = {
            "sub": "user-uuid-123",
            "iss": cognito_test_config.issuer,
            "aud": cognito_test_config.COGNITO_CLIENT_ID,
            "token_use": "id",
            "exp": now + 3600,
            "iat": now,
            "email": "user@example.com",
            "email_verified": True,
        }
        token = _sign_test_token(priv, claims)

        verified = verify_cognito_token(
            token,
            expected_token_use="id",
            config=cognito_test_config,
            jwks_override=jwks,
        )
        assert verified["sub"] == "user-uuid-123"
        assert verified["email"] == "user@example.com"
        assert verified["token_use"] == "id"

    def test_verify_valid_access_token(self, rsa_key_pair, cognito_test_config):
        priv, _, jwks = rsa_key_pair
        now = int(time.time())
        claims = {
            "sub": "user-uuid-123",
            "iss": cognito_test_config.issuer,
            "client_id": cognito_test_config.COGNITO_CLIENT_ID,
            "token_use": "access",
            "exp": now + 3600,
            "iat": now,
            "scope": "openid email profile",
        }
        token = _sign_test_token(priv, claims)

        verified = verify_cognito_token(
            token,
            expected_token_use="access",
            config=cognito_test_config,
            jwks_override=jwks,
        )
        assert verified["sub"] == "user-uuid-123"
        assert verified["client_id"] == cognito_test_config.COGNITO_CLIENT_ID
        assert verified["token_use"] == "access"

    def test_verify_expired_token_raises_expired_error(self, rsa_key_pair, cognito_test_config):
        priv, _, jwks = rsa_key_pair
        now = int(time.time())
        claims = {
            "sub": "user-uuid-123",
            "iss": cognito_test_config.issuer,
            "aud": cognito_test_config.COGNITO_CLIENT_ID,
            "token_use": "id",
            "exp": now - 3600,  # 1 hour in the past
            "iat": now - 7200,
        }
        token = _sign_test_token(priv, claims)

        with pytest.raises(CognitoTokenExpiredError):
            verify_cognito_token(
                token,
                config=cognito_test_config,
                jwks_override=jwks,
            )

    def test_verify_invalid_signature_fails_closed(self, cognito_test_config):
        other_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = int(time.time())
        claims = {
            "sub": "user-uuid-123",
            "iss": cognito_test_config.issuer,
            "aud": cognito_test_config.COGNITO_CLIENT_ID,
            "token_use": "id",
            "exp": now + 3600,
        }
        token = _sign_test_token(other_priv, claims, kid="test-cognito-key-1")

        official_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub_numbers = official_priv.public_key().public_numbers()
        jwks = {
            "keys": [
                {
                    "kty": "RSA",
                    "alg": "RS256",
                    "use": "sig",
                    "kid": "test-cognito-key-1",
                    "n": _int_to_base64url(pub_numbers.n),
                    "e": _int_to_base64url(pub_numbers.e),
                }
            ]
        }

        with pytest.raises(CognitoTokenInvalidError, match="Cognito token validation failed"):
            verify_cognito_token(
                token,
                config=cognito_test_config,
                jwks_override=jwks,
            )

    def test_verify_issuer_mismatch_fails_closed(self, rsa_key_pair, cognito_test_config):
        priv, _, jwks = rsa_key_pair
        now = int(time.time())
        claims = {
            "sub": "user-uuid-123",
            "iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_spoofedPool",
            "aud": cognito_test_config.COGNITO_CLIENT_ID,
            "token_use": "id",
            "exp": now + 3600,
        }
        token = _sign_test_token(priv, claims)

        with pytest.raises(CognitoTokenInvalidError):
            verify_cognito_token(
                token,
                config=cognito_test_config,
                jwks_override=jwks,
            )

    def test_verify_audience_mismatch_fails_closed(self, rsa_key_pair, cognito_test_config):
        priv, _, jwks = rsa_key_pair
        now = int(time.time())
        claims = {
            "sub": "user-uuid-123",
            "iss": cognito_test_config.issuer,
            "aud": "wrong-client-id-aud",
            "token_use": "id",
            "exp": now + 3600,
        }
        token = _sign_test_token(priv, claims)

        with pytest.raises(CognitoTokenInvalidError, match="Audience mismatch"):
            verify_cognito_token(
                token,
                config=cognito_test_config,
                jwks_override=jwks,
            )

    def test_verify_client_id_mismatch_for_access_token_fails_closed(
        self, rsa_key_pair, cognito_test_config
    ):
        priv, _, jwks = rsa_key_pair
        now = int(time.time())
        claims = {
            "sub": "user-uuid-123",
            "iss": cognito_test_config.issuer,
            "client_id": "wrong-app-client-id",
            "token_use": "access",
            "exp": now + 3600,
        }
        token = _sign_test_token(priv, claims)

        with pytest.raises(CognitoTokenInvalidError, match="Client ID mismatch"):
            verify_cognito_token(
                token,
                config=cognito_test_config,
                jwks_override=jwks,
            )

    def test_verify_token_use_mismatch_fails_closed(self, rsa_key_pair, cognito_test_config):
        priv, _, jwks = rsa_key_pair
        now = int(time.time())
        claims = {
            "sub": "user-uuid-123",
            "iss": cognito_test_config.issuer,
            "client_id": cognito_test_config.COGNITO_CLIENT_ID,
            "token_use": "access",
            "exp": now + 3600,
        }
        token = _sign_test_token(priv, claims)

        with pytest.raises(CognitoTokenInvalidError, match="Expected token_use='id'"):
            verify_cognito_token(
                token,
                expected_token_use="id",
                config=cognito_test_config,
                jwks_override=jwks,
            )

    def test_verify_unsupported_algorithm_fails_closed(self, cognito_test_config):
        token = pyjwt.encode({"sub": "123"}, "secret", algorithm="HS256", headers={"kid": "key1"})
        with pytest.raises(CognitoTokenInvalidError, match="Unsupported algorithm"):
            verify_cognito_token(token, config=cognito_test_config)

    def test_verify_missing_kid_header_fails_closed(self, cognito_test_config):
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = pyjwt.encode({"sub": "123"}, priv, algorithm="RS256")
        with pytest.raises(CognitoTokenInvalidError, match="missing 'kid'"):
            verify_cognito_token(token, config=cognito_test_config)

    def test_verify_malformed_token_fails_closed(self, cognito_test_config):
        for bad in ("", "bad.token", "...", None):
            with pytest.raises(CognitoTokenInvalidError):
                verify_cognito_token(bad, config=cognito_test_config)  # type: ignore[arg-type]


# ─── 3. Identity Mapping & Account Takeover Prevention Tests ─────────────────

class TestCognitoIdentityMapping:
    def test_admin_provisioned_mapping_resolves_directly(self):
        store = InMemoryCognitoIdentityStore()
        existing_recondesk_id = str(uuid.uuid4())
        cognito_sub = str(uuid.uuid4())

        store.admin_provision_mapping(
            user_id=existing_recondesk_id,
            cognito_sub=cognito_sub,
            email="ca@example.com",
            provisioned_by="test-admin",
        )

        mock_profile = {"id": existing_recondesk_id, "email": "ca@example.com", "role": "admin"}

        resolved_id = resolve_cognito_user_id(
            {"sub": cognito_sub, "email": "ca@example.com", "email_verified": True},
            identity_store=store,
            profile_lookup_fn=lambda uid: mock_profile if uid == existing_recondesk_id else None,
            profile_by_email_fn=lambda em: mock_profile if em == "ca@example.com" else None,
        )

        assert resolved_id == existing_recondesk_id

    def test_untrusted_custom_attribute_rejected_even_if_email_matches(self):
        """CRITICAL SECURITY TEST (Requirement 3):

        Do not trust custom:recondesk_user_id merely because it matches an existing
        profile's email. Must be rejected if not pre-provisioned or verified via linking.
        """
        store = InMemoryCognitoIdentityStore()
        existing_recondesk_id = str(uuid.uuid4())
        cognito_sub = str(uuid.uuid4())

        mock_profile = {"id": existing_recondesk_id, "email": "ca@example.com", "role": "admin"}

        claims = {
            "sub": cognito_sub,
            "email": "ca@example.com",
            "email_verified": True,
            "custom:recondesk_user_id": existing_recondesk_id,
        }

        with pytest.raises(CognitoIdentityError, match="Untrusted identity claim"):
            resolve_cognito_user_id(
                claims,
                identity_store=store,
                profile_lookup_fn=lambda uid: mock_profile if uid == existing_recondesk_id else None,
                profile_by_email_fn=lambda em: mock_profile if em == "ca@example.com" else None,
            )

    def test_email_only_match_requires_cryptographic_linking_preventing_account_takeover(self):
        """CRITICAL SECURITY TEST:

        If a Cognito user has an email matching an existing ReconDesk profile,
        do NOT automatically map or reassign the account on email alone.
        Must raise CognitoAccountLinkingRequiredError!
        """
        store = InMemoryCognitoIdentityStore()
        existing_recondesk_id = str(uuid.uuid4())
        cognito_sub = str(uuid.uuid4())

        mock_existing_profile = {
            "id": existing_recondesk_id,
            "email": "existing_ca@recondesk.in",
            "role": "admin",
        }

        claims = {
            "sub": cognito_sub,
            "email": "existing_ca@recondesk.in",
            "email_verified": True,
        }

        with pytest.raises(CognitoAccountLinkingRequiredError) as exc_info:
            resolve_cognito_user_id(
                claims,
                identity_store=store,
                profile_lookup_fn=lambda uid: mock_existing_profile if uid == existing_recondesk_id else None,
                profile_by_email_fn=lambda em: mock_existing_profile if em == "existing_ca@recondesk.in" else None,
            )

        assert exc_info.value.user_id == existing_recondesk_id
        assert exc_info.value.email == "existing_ca@recondesk.in"
        assert store.get_mapping_by_sub(cognito_sub) is None

    def test_strict_email_verified_evaluation(self):
        """Requirement 5: Strict validation of email_verified claim."""
        assert is_strict_email_verified({"email_verified": True}) is True
        assert is_strict_email_verified({"email_verified": "true"}) is True
        assert is_strict_email_verified({"email_verified": "True"}) is True
        assert is_strict_email_verified({"email_verified": "TRUE"}) is True

        # Permissive truthiness rejection
        assert is_strict_email_verified({"email_verified": False}) is False
        assert is_strict_email_verified({"email_verified": "false"}) is False
        assert is_strict_email_verified({"email_verified": 0}) is False
        assert is_strict_email_verified({"email_verified": 1}) is False
        assert is_strict_email_verified({"email_verified": None}) is False
        assert is_strict_email_verified({"email_verified": ""}) is False
        assert is_strict_email_verified({}) is False

    def test_unverified_email_rejected_for_account_linking(self):
        """Requirement 5: Require verified email for email-dependent operations."""
        store = InMemoryCognitoIdentityStore()
        existing_recondesk_id = str(uuid.uuid4())
        cognito_sub = str(uuid.uuid4())

        mock_profile = {"id": existing_recondesk_id, "email": "ca@example.com", "role": "admin"}
        claims = {
            "sub": cognito_sub,
            "email": "ca@example.com",
            "email_verified": "false",  # Unverified!
        }

        with pytest.raises(CognitoIdentityError, match="strictly verified"):
            resolve_cognito_user_id(
                claims,
                identity_store=store,
                profile_lookup_fn=lambda uid: mock_profile if uid == existing_recondesk_id else None,
                profile_by_email_fn=lambda em: mock_profile if em == "ca@example.com" else None,
            )

    def test_cryptographic_account_linking_completion(self):
        store = InMemoryCognitoIdentityStore()
        existing_recondesk_id = str(uuid.uuid4())
        cognito_sub = str(uuid.uuid4())
        email = "ca@example.com"

        mock_profile = {"id": existing_recondesk_id, "email": email, "role": "admin"}

        # Generate one-time cryptographic linking token internally
        token = store._create_linking_token_internal(existing_recondesk_id, cognito_sub, email, ttl_seconds=300)
        assert token is not None and "." in token

        # Complete linking with verified token
        claims = {"sub": cognito_sub, "email": email, "email_verified": True}
        linked_id = complete_account_linking(
            token,
            claims,
            identity_store=store,
            profile_lookup_fn=lambda uid: mock_profile if uid == existing_recondesk_id else None,
        )
        assert linked_id == existing_recondesk_id

        # Subsequent logins resolve directly through trusted mapping
        second_login_id = resolve_cognito_user_id(
            claims,
            identity_store=store,
            profile_lookup_fn=lambda uid: mock_profile if uid == existing_recondesk_id else None,
            profile_by_email_fn=lambda em: mock_profile if em == email else None,
        )
        assert second_login_id == existing_recondesk_id

    def test_cross_account_mapping_rejected(self):
        """Cross-account collision: user_id already mapped to a different Cognito sub."""
        store = InMemoryCognitoIdentityStore()
        user_id = str(uuid.uuid4())
        sub_a = str(uuid.uuid4())
        sub_b = str(uuid.uuid4())

        # sub_a is already mapped to user_id
        store.admin_provision_mapping(
            user_id=user_id,
            cognito_sub=sub_a,
            email="user@example.com",
            provisioned_by="test-admin",
        )

        mock_profile = {"id": user_id, "email": "user@example.com", "role": "admin"}
        token_for_sub_b = store._create_linking_token_internal(user_id, sub_b, "user@example.com")

        with pytest.raises(CognitoAccountConflictError, match="already mapped to a different Cognito identity"):
            complete_account_linking(
                token_for_sub_b,
                {"sub": sub_b, "email": "user@example.com", "email_verified": True},
                identity_store=store,
                profile_lookup_fn=lambda uid: mock_profile if uid == user_id else None,
            )

    def test_automatic_new_user_provisioning_is_disabled(self):
        """Requirement 4: Disable automatic new-user provisioning."""
        store = InMemoryCognitoIdentityStore()
        new_cognito_sub = str(uuid.uuid4())
        claims = {
            "sub": new_cognito_sub,
            "email": "brandnew@example.com",
            "email_verified": True,
        }

        with pytest.raises(CognitoIdentityError, match="automatic provisioning is disabled"):
            resolve_cognito_user_id(
                claims,
                identity_store=store,
                profile_lookup_fn=lambda uid: None,
                profile_by_email_fn=lambda em: None,
                auto_provision_new_users=False,
            )


# ─── 4. FastAPI Endpoint Integration Tests ───────────────────────────────────

class TestCognitoEndpoints:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_cognito_status_endpoint_never_exposes_secrets(self, client):
        resp = client.get("/api/v1/auth/cognito/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["region"] == "ap-south-1"
        assert data["user_pool_id"] == "ap-south-1_nvIPYMvFh"
        assert data["client_id"] == "2qui5lp7if0g4lftbrag7o6sce"
        assert data["redirect_uri"] == "http://localhost:3000/api/auth/cognito/callback"
        assert "client_secret" not in data
        assert "has_client_secret" in data
        assert "domain" in data
        assert "domain_url" in data
        assert "authorize_url" in data
        assert "token_url" in data

    def test_cognito_status_endpoint_returns_domain_info(self, client):
        from app.cognito_config import get_cognito_config

        test_cfg = CognitoConfig(
            COGNITO_DOMAIN="https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com",
            COGNITO_AUTH_ENABLED=False,
        )
        app.dependency_overrides[get_cognito_config] = lambda: test_cfg
        try:
            resp = client.get("/api/v1/auth/cognito/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["domain"] == "https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com"
            assert data["domain_url"] == "https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com"
            assert data["authorize_url"] == "https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com/oauth2/authorize"
            assert data["token_url"] == "https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com/oauth2/token"
            assert data["enabled"] is False
        finally:
            app.dependency_overrides.clear()

    def test_cognito_me_endpoint_fails_501_when_feature_flag_is_disabled(self, client):
        resp = client.get("/api/v1/auth/cognito/me")
        assert resp.status_code == 501
        assert "disabled" in resp.json()["detail"].lower()

    def test_cognito_me_endpoint_requires_bearer_token(self, client):
        from app.cognito_config import get_cognito_config

        test_cfg = CognitoConfig(COGNITO_AUTH_ENABLED=True)
        app.dependency_overrides[get_cognito_config] = lambda: test_cfg
        try:
            resp = client.get("/api/v1/auth/cognito/me")
            assert resp.status_code == 401
        finally:
            app.dependency_overrides.clear()

    def test_cognito_me_endpoint_rejects_id_token_for_bearer_auth(
        self, client, rsa_key_pair
    ):
        """Requirement 6: Never accept an ID token as a bearer access token."""
        from app.cognito_config import get_cognito_config

        priv, _, jwks = rsa_key_pair
        test_cfg = CognitoConfig(
            COGNITO_REGION="ap-south-1",
            COGNITO_USER_POOL_ID="ap-south-1_nvIPYMvFh",
            COGNITO_CLIENT_ID="2qui5lp7if0g4lftbrag7o6sce",
            COGNITO_AUTH_ENABLED=True,
        )
        app.dependency_overrides[get_cognito_config] = lambda: test_cfg
        set_cognito_jwks_cache_for_testing(jwks)

        try:
            now = int(time.time())
            sub = str(uuid.uuid4())
            id_token_claims = {
                "sub": sub,
                "iss": test_cfg.issuer,
                "aud": test_cfg.COGNITO_CLIENT_ID,
                "token_use": "id",  # ID token, not access token!
                "exp": now + 3600,
                "email": "user@example.com",
                "email_verified": True,
            }
            id_token = _sign_test_token(priv, id_token_claims)

            resp = client.get(
                "/api/v1/auth/cognito/me",
                headers={"Authorization": f"Bearer {id_token}"},
            )
            # Must reject with 401
            assert resp.status_code == 401
            assert "invalid" in resp.headers.get("WWW-Authenticate", "").lower()
        finally:
            app.dependency_overrides.clear()
            set_cognito_jwks_cache_for_testing(None)

    def test_cognito_me_endpoint_succeeds_with_valid_access_token_and_trusted_mapping(
        self, client, rsa_key_pair, monkeypatch
    ):
        """Requirement 6: Accept valid access token for mapped identity."""
        from app.cognito_config import get_cognito_config

        priv, _, jwks = rsa_key_pair
        test_cfg = CognitoConfig(
            COGNITO_REGION="ap-south-1",
            COGNITO_USER_POOL_ID="ap-south-1_nvIPYMvFh",
            COGNITO_CLIENT_ID="2qui5lp7if0g4lftbrag7o6sce",
            COGNITO_AUTH_ENABLED=True,
        )
        app.dependency_overrides[get_cognito_config] = lambda: test_cfg
        set_cognito_jwks_cache_for_testing(jwks)

        # Pre-seed a trusted administrative mapping in store
        store = get_identity_store()
        sub = str(uuid.uuid4())
        recondesk_user_id = str(uuid.uuid4())
        store.admin_provision_mapping(
            user_id=recondesk_user_id,
            cognito_sub=sub,
            email="admin_user@example.com",
            provisioned_by="test-admin",
        )

        mock_profile = {"id": recondesk_user_id, "email": "admin_user@example.com", "role": "admin"}
        monkeypatch.setattr(
            "app.routers.cognito_auth._lookup_profile_by_id",
            lambda uid: mock_profile if uid == recondesk_user_id else None,
        )

        try:
            now = int(time.time())
            access_claims = {
                "sub": sub,
                "iss": test_cfg.issuer,
                "client_id": test_cfg.COGNITO_CLIENT_ID,
                "token_use": "access",
                "exp": now + 3600,
                "scope": "openid email profile",
            }
            access_token = _sign_test_token(priv, access_claims)

            resp = client.get(
                "/api/v1/auth/cognito/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["cognito_sub"] == sub
            assert body["user_id"] == recondesk_user_id
            assert body["token_use"] == "access"
        finally:
            app.dependency_overrides.clear()
            set_cognito_jwks_cache_for_testing(None)
