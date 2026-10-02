from __future__ import annotations

import base64
from dataclasses import FrozenInstanceError
import time
import uuid
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from app.auth import (
    AuthenticatedUser,
    _detect_auth_provider_hint,
    _verify_cognito_bearer_token,
    _verify_supabase_bearer_token,
    get_current_active_user,
    get_current_user,
    get_current_user_id,
    get_user_role,
    require_admin,
    require_role,
)
from app.cognito_aurora_store import set_identity_store
from app.cognito_config import CognitoConfig
from app.cognito_identity import (
    CognitoIdentityError,
    CognitoIdentityMapping,
    InMemoryCognitoIdentityStore,
)
from app.cognito_verifier import set_cognito_jwks_cache_for_testing
from app.config import settings


def _int_to_base64url(n: int) -> str:
    byte_len = (n.bit_length() + 7) // 8
    b = n.to_bytes(byte_len, byteorder="big")
    return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")


@pytest.fixture(scope="module")
def rsa_key_pair():
    """Generate an RSA key pair for testing Cognito token signing and verification."""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_numbers = priv.public_key().public_numbers()
    kid = "test-cognito-key-dualauth"
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
        COGNITO_USER_POOL_ID="ap-south-1_nvlPYMvFh",
        COGNITO_CLIENT_ID="2qui5lp7if0g4lftbrag7o6sce",
        COGNITO_CLIENT_SECRET="test-secret",
        COGNITO_REDIRECT_URI="http://localhost:3000/api/auth/cognito/callback",
        COGNITO_LOGOUT_URI="http://localhost:3000/login",
        COGNITO_AUTH_ENABLED=True,
    )


def _sign_cognito_token(
    private_key,
    claims: dict[str, Any],
    kid: str = "test-cognito-key-dualauth",
    algorithm: str = "RS256",
) -> str:
    headers = {"kid": kid, "alg": algorithm}
    return pyjwt.encode(claims, private_key, algorithm=algorithm, headers=headers)


def _sign_supabase_hs256_token(
    claims: dict[str, Any],
    secret: Optional[str] = None,
) -> str:
    key = secret or settings.jwt_signing_key
    return pyjwt.encode(claims, key, algorithm="HS256", headers={"alg": "HS256"})


# ─── 1. AuthenticatedUser Model Invariants ───────────────────────────────────

class TestAuthenticatedUserModel:
    def test_authenticated_user_immutable(self):
        user = AuthenticatedUser(
            id="1fa557d7-5f6f-4539-9e0c-3e75a71a9a6c",
            auth_provider="cognito",
            provider_subject="d1a38dfa-20e1-70bb-061d-eb14138ccd11",
        )
        assert user.id == "1fa557d7-5f6f-4539-9e0c-3e75a71a9a6c"
        assert user.auth_provider == "cognito"
        assert user.provider_subject == "d1a38dfa-20e1-70bb-061d-eb14138ccd11"

        with pytest.raises(FrozenInstanceError):
            user.id = "modified-id"  # type: ignore[misc]

    def test_no_default_role_on_authenticated_user(self):
        """CRITICAL: AuthenticatedUser must NEVER carry default authorization role='admin'."""
        user = AuthenticatedUser(
            id="1fa557d7-5f6f-4539-9e0c-3e75a71a9a6c",
            auth_provider="supabase",
            provider_subject="1fa557d7-5f6f-4539-9e0c-3e75a71a9a6c",
        )
        assert not hasattr(user, "role")
        assert not hasattr(user, "is_admin")

    def test_str_representation_returns_canonical_id(self):
        user = AuthenticatedUser(
            id="usr-12345",
            auth_provider="supabase",
            provider_subject="usr-12345",
        )
        assert str(user) == "usr-12345"

    def test_equality_and_hashing(self):
        u1 = AuthenticatedUser(id="u1", auth_provider="supabase", provider_subject="sub1")
        u2 = AuthenticatedUser(id="u1", auth_provider="supabase", provider_subject="sub1")
        u3 = AuthenticatedUser(id="u1", auth_provider="cognito", provider_subject="sub1")

        assert u1 == u2
        assert u1 != u3
        assert len({u1, u2}) == 1
        assert len({u1, u3}) == 2


# ─── 2. Provider Hint Detection ───────────────────────────────────────────────

class TestProviderHintDetection:
    def test_detect_hs256_returns_none_when_supabase_removed(self):
        token = _sign_supabase_hs256_token({"sub": "user-123", "exp": int(time.time()) + 3600})
        assert _detect_auth_provider_hint(token) is None

    def test_detect_rs256_with_cognito_issuer_as_cognito(self, rsa_key_pair):
        priv, _, _ = rsa_key_pair
        token = _sign_cognito_token(
            priv,
            {
                "sub": "cog-sub-1",
                "iss": "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_nvlPYMvFh",
                "token_use": "access",
                "client_id": "2qui5lp7if0g4lftbrag7o6sce",
                "exp": int(time.time()) + 3600,
            },
        )
        assert _detect_auth_provider_hint(token) == "cognito"

    def test_detect_malformed_returns_none(self):
        assert _detect_auth_provider_hint("not-a-token") is None
        assert _detect_auth_provider_hint("") is None
        assert _detect_auth_provider_hint("abc.def") is None

    def test_detect_unrecognized_algorithm_returns_none(self):
        # none algorithm or unsupported
        token = pyjwt.encode({"sub": "test"}, "secret", algorithm="HS384")
        assert _detect_auth_provider_hint(token) is None


# ─── 3. Supabase Authentication Path (Disabled) ───────────────────────────────

class TestSupabaseAuthPath:
    def test_supabase_token_permanently_disabled_fails_closed(self):
        sub_id = str(uuid.uuid4())
        token = _sign_supabase_hs256_token(
            {
                "sub": sub_id,
                "email": "user@example.com",
                "aud": "authenticated",
                "exp": int(time.time()) + 3600,
            }
        )
        with pytest.raises(HTTPException) as exc_info:
            _verify_supabase_bearer_token(token)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "disabled" in exc_info.value.detail.lower()


# ─── 4. Cognito Authentication Path ───────────────────────────────────────────

class TestCognitoAuthPath:
    @pytest.fixture(autouse=True)
    def setup_cognito(self, rsa_key_pair, cognito_test_config):
        _, _, jwks = rsa_key_pair
        set_cognito_jwks_cache_for_testing(jwks)
        self.store = InMemoryCognitoIdentityStore(default_pool_id=cognito_test_config.COGNITO_USER_POOL_ID)
        set_identity_store(self.store)
        yield
        set_cognito_jwks_cache_for_testing(None)
        set_identity_store(None)

    def test_valid_cognito_access_token_with_trusted_mapping_succeeds(
        self, rsa_key_pair, cognito_test_config
    ):
        priv, _, _ = rsa_key_pair
        cognito_sub = "d1a38dfa-20e1-70bb-061d-eb14138ccd11"
        canonical_user_id = "1fa557d7-5f6f-4539-9e0c-3e75a71a9a6c"

        # Seed verified mapping in store
        mapping = CognitoIdentityMapping(
            cognito_sub=cognito_sub,
            user_id=canonical_user_id,
            email="recondesk.dev.email@gmail.com",
            mapping_method="verified_link_token",
            verified=True,
            cognito_user_pool_id=cognito_test_config.COGNITO_USER_POOL_ID,
        )
        self.store._mappings_by_sub[(cognito_test_config.COGNITO_USER_POOL_ID, cognito_sub)] = mapping
        self.store.set_user_profile(
            canonical_user_id,
            {"id": canonical_user_id, "email": "recondesk.dev.email@gmail.com", "role": "admin", "is_active": True},
        )

        token = _sign_cognito_token(
            priv,
            {
                "sub": cognito_sub,
                "iss": cognito_test_config.issuer,
                "client_id": cognito_test_config.COGNITO_CLIENT_ID,
                "token_use": "access",
                "exp": int(time.time()) + 3600,
            },
        )

        with patch("app.auth.get_cognito_config", return_value=cognito_test_config):
            user = _verify_cognito_bearer_token(token, store=self.store)
            assert isinstance(user, AuthenticatedUser)
            assert user.id == canonical_user_id  # Resolves to Aurora user_profiles.id, NOT cognito_sub
            assert user.auth_provider == "cognito"
            assert user.provider_subject == cognito_sub

    def test_cognito_id_token_rejected_as_bearer(
        self, rsa_key_pair, cognito_test_config
    ):
        """CRITICAL: Cognito ID tokens must be strictly rejected when passed as Bearer tokens."""
        priv, _, _ = rsa_key_pair
        token = _sign_cognito_token(
            priv,
            {
                "sub": "sub-123",
                "iss": cognito_test_config.issuer,
                "aud": cognito_test_config.COGNITO_CLIENT_ID,
                "token_use": "id",  # ID token, not access token
                "exp": int(time.time()) + 3600,
            },
        )

        with patch("app.auth.get_cognito_config", return_value=cognito_test_config):
            with pytest.raises(HTTPException) as exc_info:
                _verify_cognito_bearer_token(token, store=self.store)
            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cognito_unmapped_token_fails_closed(
        self, rsa_key_pair, cognito_test_config
    ):
        """Valid token from Cognito but NO verified Aurora mapping -> 401."""
        priv, _, _ = rsa_key_pair
        token = _sign_cognito_token(
            priv,
            {
                "sub": "unmapped-cognito-sub",
                "iss": cognito_test_config.issuer,
                "client_id": cognito_test_config.COGNITO_CLIENT_ID,
                "token_use": "access",
                "exp": int(time.time()) + 3600,
            },
        )

        with patch("app.auth.get_cognito_config", return_value=cognito_test_config):
            with pytest.raises(HTTPException) as exc_info:
                _verify_cognito_bearer_token(token, store=self.store)
            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
            assert "No verified account mapping" in exc_info.value.detail

    def test_cognito_unverified_mapping_fails_closed(
        self, rsa_key_pair, cognito_test_config
    ):
        """Mapping exists in Aurora but is_verified is False -> 401."""
        priv, _, _ = rsa_key_pair
        sub = "unverified-sub"
        user_id = str(uuid.uuid4())

        mapping = CognitoIdentityMapping(
            cognito_sub=sub,
            user_id=user_id,
            email="test@example.com",
            mapping_method="unverified",
            verified=False,  # Unverified!
            cognito_user_pool_id=cognito_test_config.COGNITO_USER_POOL_ID,
        )
        self.store._mappings_by_sub[(cognito_test_config.COGNITO_USER_POOL_ID, sub)] = mapping

        token = _sign_cognito_token(
            priv,
            {
                "sub": sub,
                "iss": cognito_test_config.issuer,
                "client_id": cognito_test_config.COGNITO_CLIENT_ID,
                "token_use": "access",
                "exp": int(time.time()) + 3600,
            },
        )

        with patch("app.auth.get_cognito_config", return_value=cognito_test_config):
            with pytest.raises(HTTPException) as exc_info:
                _verify_cognito_bearer_token(token, store=self.store)
            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cognito_inactive_user_profile_fails_closed(
        self, rsa_key_pair, cognito_test_config
    ):
        """Mapping exists and is verified, but user_profiles.is_active is False -> 401."""
        priv, _, _ = rsa_key_pair
        sub = "inactive-user-sub"
        user_id = str(uuid.uuid4())

        mapping = CognitoIdentityMapping(
            cognito_sub=sub,
            user_id=user_id,
            email="inactive@example.com",
            mapping_method="verified_link_token",
            verified=True,
            cognito_user_pool_id=cognito_test_config.COGNITO_USER_POOL_ID,
        )
        self.store._mappings_by_sub[(cognito_test_config.COGNITO_USER_POOL_ID, sub)] = mapping
        self.store.set_user_profile(
            user_id,
            {"id": user_id, "email": "inactive@example.com", "role": "admin", "is_active": False},
        )

        token = _sign_cognito_token(
            priv,
            {
                "sub": sub,
                "iss": cognito_test_config.issuer,
                "client_id": cognito_test_config.COGNITO_CLIENT_ID,
                "token_use": "access",
                "exp": int(time.time()) + 3600,
            },
        )

        with patch("app.auth.get_cognito_config", return_value=cognito_test_config):
            with pytest.raises(HTTPException) as exc_info:
                _verify_cognito_bearer_token(token, store=self.store)
            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
            assert "inactive" in exc_info.value.detail.lower()

    def test_cognito_auth_disabled_fails_closed(
        self, rsa_key_pair, cognito_test_config
    ):
        """When COGNITO_AUTH_ENABLED=False, Cognito tokens must be rejected."""
        priv, _, _ = rsa_key_pair
        token = _sign_cognito_token(
            priv,
            {
                "sub": "sub-1",
                "iss": cognito_test_config.issuer,
                "client_id": cognito_test_config.COGNITO_CLIENT_ID,
                "token_use": "access",
                "exp": int(time.time()) + 3600,
            },
        )
        disabled_config = CognitoConfig(
            COGNITO_USER_POOL_ID=cognito_test_config.COGNITO_USER_POOL_ID,
            COGNITO_CLIENT_ID=cognito_test_config.COGNITO_CLIENT_ID,
            COGNITO_AUTH_ENABLED=False,
        )
        with patch("app.auth.get_cognito_config", return_value=disabled_config):
            with pytest.raises(HTTPException) as exc_info:
                _verify_cognito_bearer_token(token, store=self.store)
            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
            assert "not enabled" in exc_info.value.detail.lower()

    def test_cognito_email_spoofing_defense(
        self, rsa_key_pair, cognito_test_config
    ):
        """Even if token claims an arbitrary email, user_id is anchored strictly to verified mapping."""
        priv, _, _ = rsa_key_pair
        cognito_sub = "legit-sub-1"
        mapped_user_id = str(uuid.uuid4())

        mapping = CognitoIdentityMapping(
            cognito_sub=cognito_sub,
            user_id=mapped_user_id,
            email="victim@example.com",
            mapping_method="verified_link_token",
            verified=True,
            cognito_user_pool_id=cognito_test_config.COGNITO_USER_POOL_ID,
        )
        self.store._mappings_by_sub[(cognito_test_config.COGNITO_USER_POOL_ID, cognito_sub)] = mapping
        self.store.set_user_profile(
            mapped_user_id,
            {"id": mapped_user_id, "email": "victim@example.com", "role": "admin", "is_active": True},
        )

        # Attacker crafts token claiming a different email
        token = _sign_cognito_token(
            priv,
            {
                "sub": cognito_sub,
                "email": "attacker-spoofed-email@evil.com",
                "iss": cognito_test_config.issuer,
                "client_id": cognito_test_config.COGNITO_CLIENT_ID,
                "token_use": "access",
                "exp": int(time.time()) + 3600,
            },
        )

        with patch("app.auth.get_cognito_config", return_value=cognito_test_config):
            user = _verify_cognito_bearer_token(token, store=self.store)
            assert user.id == mapped_user_id
            assert user.provider_subject == cognito_sub


# ─── 5. Unified get_current_user Dependency Dispatch ──────────────────────────

class TestGetCurrentUserDispatch:
    @pytest.fixture(autouse=True)
    def setup_cognito(self, rsa_key_pair, cognito_test_config):
        _, _, jwks = rsa_key_pair
        set_cognito_jwks_cache_for_testing(jwks)
        self.store = InMemoryCognitoIdentityStore(default_pool_id=cognito_test_config.COGNITO_USER_POOL_ID)
        set_identity_store(self.store)
        self.config = cognito_test_config
        yield
        set_cognito_jwks_cache_for_testing(None)
        set_identity_store(None)

    @pytest.mark.asyncio
    async def test_dispatch_missing_credentials_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(None)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_dispatch_empty_credentials_raises_401(self):
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="   ")
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(creds)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_dispatch_garbage_token_raises_401(self):
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="random-garbage-token")
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(creds)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_dispatch_rejects_supabase_token(self):
        uid = str(uuid.uuid4())
        token = _sign_supabase_hs256_token({"sub": uid, "exp": int(time.time()) + 3600})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(creds, store=self.store)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_dispatch_routes_cognito_token(self, rsa_key_pair):
        priv, _, _ = rsa_key_pair
        sub = "cog-sub-dispatch-1"
        mapped_uid = str(uuid.uuid4())

        mapping = CognitoIdentityMapping(
            cognito_sub=sub,
            user_id=mapped_uid,
            email="test@example.com",
            mapping_method="verified_link_token",
            verified=True,
            cognito_user_pool_id=self.config.COGNITO_USER_POOL_ID,
        )
        self.store._mappings_by_sub[(self.config.COGNITO_USER_POOL_ID, sub)] = mapping
        self.store.set_user_profile(
            mapped_uid,
            {"id": mapped_uid, "email": "test@example.com", "role": "admin", "is_active": True},
        )

        token = _sign_cognito_token(
            priv,
            {
                "sub": sub,
                "iss": self.config.issuer,
                "client_id": self.config.COGNITO_CLIENT_ID,
                "token_use": "access",
                "exp": int(time.time()) + 3600,
            },
        )
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        with patch("app.auth.get_cognito_config", return_value=self.config):
            user = await get_current_user(creds, store=self.store)
            assert user.id == mapped_uid
            assert user.auth_provider == "cognito"
            assert user.provider_subject == sub

    @pytest.mark.asyncio
    async def test_dispatch_forged_cognito_token_fails_closed(self):
        """Attacker signs a Cognito-shaped token with an untrusted key."""
        wrong_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = _sign_cognito_token(
            wrong_priv,
            {
                "sub": "attacker-sub",
                "iss": self.config.issuer,
                "client_id": self.config.COGNITO_CLIENT_ID,
                "token_use": "access",
                "exp": int(time.time()) + 3600,
            },
            kid="unknown-kid",
        )
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        with patch("app.auth.get_cognito_config", return_value=self.config):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(creds, store=self.store)
            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_dispatch_cognito_token_when_aurora_store_init_fails_fails_closed(self, rsa_key_pair):
        """When Aurora is configured but store initialization fails, Cognito auth fails closed."""
        priv, _, _ = rsa_key_pair
        set_identity_store(None)  # Clear injected test store so get_identity_store() runs

        token = _sign_cognito_token(
            priv,
            {
                "sub": "some-sub",
                "iss": self.config.issuer,
                "client_id": self.config.COGNITO_CLIENT_ID,
                "token_use": "access",
                "exp": int(time.time()) + 3600,
            },
        )
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        with patch("app.aurora.is_aurora_enabled", return_value=True), \
             patch("app.aurora.get_aurora_database_url", return_value="postgresql+psycopg2://user:pass@host:5432/db"), \
             patch("app.cognito_aurora_store.SQLAlchemyCognitoIdentityStore", side_effect=Exception("DB pool failed")), \
             patch("app.auth.get_cognito_config", return_value=self.config):

            with pytest.raises(CognitoIdentityError) as exc_info:
                await get_current_user(creds, store=None)

            assert "Failed to initialize Aurora identity mapping store." in str(exc_info.value)


# ─── 6. Downstream Authorization & Role Resolution ────────────────────────────

class TestDownstreamAuthorization:
    @pytest.fixture(autouse=True)
    def setup_store(self, cognito_test_config):
        self.store = InMemoryCognitoIdentityStore(default_pool_id=cognito_test_config.COGNITO_USER_POOL_ID)
        set_identity_store(self.store)
        yield
        set_identity_store(None)

    @pytest.mark.asyncio
    async def test_get_current_user_id(self):
        user = AuthenticatedUser(id="canon-uuid-1", auth_provider="cognito", provider_subject="cog-sub")
        resolved_id = await get_current_user_id(user)
        assert resolved_id == "canon-uuid-1"

    @pytest.mark.asyncio
    async def test_get_user_role_from_profile(self):
        uid = "usr-role-test"
        self.store.set_user_profile(uid, {"id": uid, "role": "admin", "is_active": True})

        role = await get_user_role(uid)
        assert role == "admin"

    @pytest.mark.asyncio
    async def test_require_role_admin_permits_admin(self):
        uid = "admin-user"
        self.store.set_user_profile(uid, {"id": uid, "role": "admin", "is_active": True})
        user = AuthenticatedUser(id=uid, auth_provider="cognito", provider_subject="sub1")

        dep = require_role("admin")
        result = await dep(user)
        assert result == uid

    @pytest.mark.asyncio
    async def test_require_role_admin_rejects_staff_with_403(self):
        uid = "staff-user"
        self.store.set_user_profile(uid, {"id": uid, "role": "staff", "is_active": True})
        user = AuthenticatedUser(id=uid, auth_provider="supabase", provider_subject=uid)

        dep = require_role("admin")
        with pytest.raises(HTTPException) as exc_info:
            await dep(user)
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_require_admin_permits_owner_and_admin(self):
        u1 = "admin-1"
        u2 = "owner-1"
        u3 = "staff-1"
        self.store.set_user_profile(u1, {"id": u1, "role": "admin", "is_active": True})
        self.store.set_user_profile(u2, {"id": u2, "role": "owner", "is_active": True})
        self.store.set_user_profile(u3, {"id": u3, "role": "staff", "is_active": True})

        assert await require_admin(u1) == u1
        assert await require_admin(u2) == u2

        with pytest.raises(HTTPException) as exc_info:
            await require_admin(u3)
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_get_current_active_user_attaches_profile_and_firm(self):
        uid = "user-profile-active"
        self.store.set_user_profile(
            uid,
            {"id": uid, "email": "test@example.com", "role": "admin", "is_active": True, "firm_name": "Test Firm"},
        )
        user = AuthenticatedUser(id=uid, auth_provider="cognito", provider_subject="sub-active")

        active_user = await get_current_active_user(user)
        assert active_user["id"] == uid
        assert active_user["email"] == "test@example.com"
        assert active_user["role"] == "admin"
        assert active_user["is_active"] is True
        assert active_user["auth_provider"] == "cognito"
        assert active_user["provider_subject"] == "sub-active"
        assert "firm_id" in active_user

    @pytest.mark.asyncio
    async def test_get_current_active_user_inactive_profile_raises_403(self):
        uid = "user-profile-disabled"
        self.store.set_user_profile(
            uid,
            {"id": uid, "email": "disabled@example.com", "role": "admin", "is_active": False},
        )
        user = AuthenticatedUser(id=uid, auth_provider="supabase", provider_subject=uid)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_active_user(user)
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
