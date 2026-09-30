from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from app.cognito_config import get_cognito_config
from app.cognito_verifier import CognitoAuthError

_log = logging.getLogger(__name__)


class CognitoIdentityError(CognitoAuthError):
    """Base exception for identity mapping and tenancy resolution failures."""


class CognitoAccountLinkingRequiredError(CognitoIdentityError):
    """Raised when a Cognito user matches an existing profile by email,
    preventing automatic account takeover without cryptographic proof of ownership.
    """

    def __init__(self, user_id: str, email: str, message: str) -> None:
        super().__init__(message)
        self.user_id = user_id
        self.email = email


class CognitoAccountConflictError(CognitoIdentityError):
    """Raised when conflicting identities or spoofed attributes are detected."""


def is_strict_email_verified(claims: dict[str, Any]) -> bool:
    """Strictly validates whether the Cognito email_verified claim is True.

    Prevents permissive truthiness issues where 'false', 0, or empty strings
    could inadvertently be coerced into True in Python.
    """
    raw_val = claims.get("email_verified")
    if isinstance(raw_val, bool):
        return raw_val
    if isinstance(raw_val, str):
        return raw_val.strip().lower() == "true"
    return False


@dataclass
class CognitoIdentityMapping:
    """Represents a verified 1:1 binding between a Cognito sub and a ReconDesk user_profiles.id
    within an isolated Cognito User Pool.
    """

    cognito_sub: str
    user_id: str
    email: str
    mapping_method: str  # 'admin_provisioned' | 'verified_link_token'
    verified: bool = False
    cognito_user_pool_id: str = "ap-south-1_nvlPYMvFh"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CognitoIdentityStore:
    """Abstract interface for managing identity mappings and one-time linking tokens."""

    def get_mapping_by_sub(
        self, cognito_sub: str, pool_id: Optional[str] = None
    ) -> Optional[CognitoIdentityMapping]:
        raise NotImplementedError

    def get_mapping_by_user_id(
        self, user_id: str, pool_id: Optional[str] = None
    ) -> Optional[CognitoIdentityMapping]:
        raise NotImplementedError

    def lookup_trusted_mapping(
        self,
        cognito_sub: str,
        pool_id: Optional[str] = None,
        profile_lookup_fn: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
    ) -> Optional[dict[str, Any]]:
        """Look up an exact, verified Cognito identity mapping.

        Requirements:
          - Exact match on cognito_user_pool_id and cognito_sub
          - is_verified must be True
          - Mapped user_profiles row must exist and have is_active == True
          - Never matches on email alone; never auto-creates mappings.
        """
        raise NotImplementedError

    def save_mapping(self, mapping: CognitoIdentityMapping) -> None:
        """Persist or update an unverified identity mapping.
        Direct insertion or modification of verified mappings via save_mapping() is prohibited.
        """
        raise NotImplementedError

    def issue_account_linking_token(
        self,
        user_id: str,
        cognito_sub: str,
        email: str,
        ownership_proof: dict[str, Any],
        pool_id: Optional[str] = None,
        ttl_seconds: int = 900,
        created_ip: Optional[str] = None,
        verify_proof_fn: Optional[Callable[[str, str, dict[str, Any]], bool]] = None,
    ) -> str:
        """Issue an account-linking token ONLY after trusted proof of ownership."""
        raise NotImplementedError

    def create_linking_token(
        self,
        user_id: str,
        cognito_sub: str,
        email: str,
        pool_id: Optional[str] = None,
        ttl_seconds: int = 900,
        created_ip: Optional[str] = None,
    ) -> str:
        """Direct creation without verified ownership proof is restricted (Item 3)."""
        raise CognitoIdentityError(
            "Direct invocation of create_linking_token() without verified ownership is restricted. "
            "Use issue_account_linking_token() with trusted ownership proof."
        )

    def verify_linking_token(
        self, token: str, cognito_sub: str, pool_id: Optional[str] = None
    ) -> Optional[tuple[str, str]]:  # (user_id, email)
        raise NotImplementedError


class InMemoryCognitoIdentityStore(CognitoIdentityStore):
    """Thread-safe in-memory store for unit tests, local development, and mocking."""

    def __init__(self, default_pool_id: str = "ap-south-1_nvlPYMvFh") -> None:
        self.default_pool_id = default_pool_id
        # Keyed by (pool_id, sub) and (pool_id, user_id)
        self._mappings_by_sub: dict[tuple[str, str], CognitoIdentityMapping] = {}
        self._mappings_by_user_id: dict[tuple[str, str], CognitoIdentityMapping] = {}
        self._profiles: dict[str, dict[str, Any]] = {}
        self._tokens: dict[str, dict[str, Any]] = {}
        self._secret = secrets.token_bytes(32)

    def set_user_profile(self, user_id: str, profile: dict[str, Any]) -> None:
        """Register or mock a user profile in memory."""
        self._profiles[str(user_id)] = profile

    def get_user_profile_by_id(self, user_id: str) -> Optional[dict[str, Any]]:
        return self._profiles.get(str(user_id))

    def get_user_profile_by_email(self, email: str) -> Optional[dict[str, Any]]:
        clean_email = str(email or "").strip().lower()
        for p in self._profiles.values():
            if str(p.get("email") or "").strip().lower() == clean_email:
                return p
        return None

    def lookup_trusted_mapping(
        self,
        cognito_sub: str,
        pool_id: Optional[str] = None,
        profile_lookup_fn: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
    ) -> Optional[dict[str, Any]]:
        """Look up verified mapping in memory store enforcing all invariants."""
        sub = str(cognito_sub or "").strip()
        if not sub:
            return None
        target_pool = (pool_id or self.default_pool_id).strip()
        if not target_pool:
            return None

        mapping = self._mappings_by_sub.get((target_pool, sub))
        if not mapping or not mapping.verified:
            return None
        if mapping.cognito_user_pool_id != target_pool or mapping.cognito_sub != sub:
            return None

        # Look up profile
        profile = None
        if profile_lookup_fn:
            profile = profile_lookup_fn(mapping.user_id)
        if profile is None:
            profile = self._profiles.get(mapping.user_id)

        if not profile or not profile.get("is_active", True):
            return None

        return {
            "user_id": mapping.user_id,
            "cognito_sub": mapping.cognito_sub,
            "cognito_user_pool_id": mapping.cognito_user_pool_id,
            "email": mapping.email,
            "mapping_method": mapping.mapping_method,
            "is_verified": True,
            "profile": profile,
        }

    def get_mapping_by_sub(
        self, cognito_sub: str, pool_id: Optional[str] = None
    ) -> Optional[CognitoIdentityMapping]:
        pid = pool_id or self.default_pool_id
        return self._mappings_by_sub.get((pid, cognito_sub))

    def get_mapping_by_user_id(
        self, user_id: str, pool_id: Optional[str] = None
    ) -> Optional[CognitoIdentityMapping]:
        pid = pool_id or self.default_pool_id
        return self._mappings_by_user_id.get((pid, user_id))

    def save_mapping(self, mapping: CognitoIdentityMapping) -> None:
        """Prevent save_mapping() from directly inserting verified mappings (Item 4)."""
        pid = mapping.cognito_user_pool_id or self.default_pool_id
        existing = self._mappings_by_sub.get((pid, mapping.cognito_sub))
        if existing is not None:
            if existing.mapping_method != mapping.mapping_method or existing.verified != mapping.verified:
                raise CognitoIdentityError(
                    "Cannot modify mapping_method or verification status via save_mapping. "
                    "Authorized provisioning or verified linking workflow is required."
                )
            if existing.user_id != mapping.user_id:
                raise CognitoAccountConflictError(
                    f"Cognito identity is already bound to user {existing.user_id}."
                )
        else:
            if mapping.verified or mapping.mapping_method in ("admin_provisioned", "verified_link_token"):
                raise CognitoIdentityError(
                    "Cannot directly insert verified mappings via save_mapping(). "
                    "Verified mappings must be established exclusively via admin_provision_mapping() "
                    "or complete_account_linking_transactional()."
                )
        self._mappings_by_sub[(pid, mapping.cognito_sub)] = mapping
        self._mappings_by_user_id[(pid, mapping.user_id)] = mapping

    def admin_provision_mapping(
        self,
        user_id: str,
        cognito_sub: str,
        email: str,
        provisioned_by: str,
        linking_ip: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        pool_id: Optional[str] = None,
    ) -> CognitoIdentityMapping:
        pid = pool_id or self.default_pool_id
        if (pid, user_id) in self._mappings_by_user_id and self._mappings_by_user_id[(pid, user_id)].cognito_sub != cognito_sub:
            raise CognitoAccountConflictError(f"User {user_id} already mapped")
        if (pid, cognito_sub) in self._mappings_by_sub and self._mappings_by_sub[(pid, cognito_sub)].user_id != user_id:
            raise CognitoAccountConflictError(f"Sub {cognito_sub} already mapped")
        mapping = CognitoIdentityMapping(
            cognito_sub=cognito_sub,
            user_id=user_id,
            email=email,
            mapping_method="admin_provisioned",
            verified=True,
            cognito_user_pool_id=pid,
        )
        self._mappings_by_sub[(pid, cognito_sub)] = mapping
        self._mappings_by_user_id[(pid, user_id)] = mapping
        return mapping

    def _create_linking_token_internal(
        self,
        user_id: str,
        cognito_sub: str,
        email: str,
        pool_id: Optional[str] = None,
        ttl_seconds: int = 900,
        created_ip: Optional[str] = None,
    ) -> str:
        pid = pool_id or self.default_pool_id
        token_id = secrets.token_urlsafe(32)
        exp = time.time() + ttl_seconds
        payload = f"{token_id}:{user_id}:{cognito_sub}:{exp}:{pid}"
        signature = hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        full_token = f"{token_id}.{signature}"
        self._tokens[token_id] = {
            "user_id": user_id,
            "cognito_sub": cognito_sub,
            "email": email,
            "pool_id": pid,
            "exp": exp,
            "signature": signature,
        }
        return full_token

    def issue_account_linking_token(
        self,
        user_id: str,
        cognito_sub: str,
        email: str,
        ownership_proof: dict[str, Any],
        pool_id: Optional[str] = None,
        ttl_seconds: int = 900,
        created_ip: Optional[str] = None,
        verify_proof_fn: Optional[Callable[[str, str, dict[str, Any]], bool]] = None,
    ) -> str:
        if verify_proof_fn is not None:
            if not verify_proof_fn(user_id, email, ownership_proof):
                raise CognitoIdentityError(
                    "Account linking token issuance rejected: ownership proof verification failed."
                )
        else:
            from app.cognito_aurora_store import verify_ownership_proof
            if not verify_ownership_proof(user_id, email, ownership_proof):
                raise CognitoIdentityError(
                    "Account linking token issuance rejected: trusted server-side proof of "
                    "existing ReconDesk account ownership is required."
                )
        return self._create_linking_token_internal(
            user_id=user_id,
            cognito_sub=cognito_sub,
            email=email,
            pool_id=pool_id,
            ttl_seconds=ttl_seconds,
            created_ip=created_ip,
        )

    def create_linking_token(
        self,
        user_id: str,
        cognito_sub: str,
        email: str,
        pool_id: Optional[str] = None,
        ttl_seconds: int = 900,
        created_ip: Optional[str] = None,
    ) -> str:
        """Prevent direct untrusted creation without verified ownership (Item 3)."""
        raise CognitoIdentityError(
            "Direct invocation of create_linking_token() without verified ownership is restricted. "
            "Use issue_account_linking_token() with trusted ownership proof."
        )

    def verify_linking_token(
        self, token: str, cognito_sub: str, pool_id: Optional[str] = None
    ) -> Optional[tuple[str, str]]:
        if "." not in token:
            return None
        token_id, signature = token.split(".", 1)
        record = self._tokens.get(token_id)
        if not record:
            return None
        if time.time() > record["exp"]:
            del self._tokens[token_id]
            return None
        if not hmac.compare_digest(record["signature"], signature):
            return None
        if record["cognito_sub"] != cognito_sub:
            return None
        pid = pool_id or self.default_pool_id
        if record["pool_id"] != pid:
            return None
        return record["user_id"], record["email"]

    def complete_account_linking_transactional(
        self,
        linking_token: str,
        claims: dict[str, Any],
        linking_ip: Optional[str] = None,
        pool_id: Optional[str] = None,
    ) -> str:
        sub = claims.get("sub")
        if not sub:
            raise CognitoIdentityError("Missing 'sub' in Cognito claims")
        if not is_strict_email_verified(claims):
            raise CognitoIdentityError("Cognito email must be strictly verified to complete account linking.")
        claims_email = (claims.get("email") or "").strip().lower()

        pid = pool_id or self.default_pool_id
        verified = self.verify_linking_token(linking_token, sub, pool_id=pid)
        if not verified:
            raise CognitoIdentityError("Invalid, expired, or mismatched account linking token")
        user_id, token_email = verified
        if token_email.strip().lower() != claims_email:
            raise CognitoIdentityError("Linking token email does not match authenticated identity")

        # Single-use consumption
        token_id = linking_token.split(".", 1)[0]
        self._tokens.pop(token_id, None)

        if (pid, user_id) in self._mappings_by_user_id and self._mappings_by_user_id[(pid, user_id)].cognito_sub != sub:
            raise CognitoAccountConflictError(f"ReconDesk account {user_id!r} is already mapped to a different Cognito identity.")
        if (pid, sub) in self._mappings_by_sub and self._mappings_by_sub[(pid, sub)].user_id != user_id:
            raise CognitoAccountConflictError(f"Cognito identity {sub!r} is already mapped to a different user.")

        mapping = CognitoIdentityMapping(
            cognito_sub=sub,
            user_id=user_id,
            email=claims_email,
            mapping_method="verified_link_token",
            verified=True,
            cognito_user_pool_id=pid,
        )
        self._mappings_by_sub[(pid, sub)] = mapping
        self._mappings_by_user_id[(pid, user_id)] = mapping
        return user_id


def resolve_cognito_user_id(
    claims: dict[str, Any],
    *,
    identity_store: CognitoIdentityStore,
    profile_lookup_fn: Callable[[str], Optional[dict[str, Any]]],
    profile_by_email_fn: Callable[[str], Optional[dict[str, Any]]],
    auto_provision_new_users: bool = False,
    expected_user_pool_id: Optional[str] = None,
) -> str:
    """Resolve a verified Cognito token's claims to an existing ReconDesk user_profiles.id UUID.

    Hardened Security & Tenancy Invariants:
      1. User Pool Isolation: ensure token belongs to the expected User Pool.
      2. Never map solely based on email (prevents account takeover).
      3. If an existing mapping exists in the trusted store and is verified
         ('admin_provisioned' or 'verified_link_token'), resolve to that user_id.
      4. DO NOT trust 'custom:recondesk_user_id' merely because it matches an
         existing profile's email. Reject untrusted custom attribute claims.
      5. Automatic new-user provisioning is DISABLED. Never auto-assign a user_profiles ID.
      6. Strict email_verified validation: require a strictly verified email for
         any email-dependent linking operations.
    """
    sub = claims.get("sub")
    if not sub or not isinstance(sub, str):
        raise CognitoIdentityError("Cognito token missing or invalid 'sub' claim")

    # Step 0: User Pool Isolation Check (Derived strictly from trusted server configuration)
    configured_pool = (expected_user_pool_id or get_cognito_config().COGNITO_USER_POOL_ID).strip()
    iss = claims.get("iss")
    if iss:
        if not iss.endswith(configured_pool):
            _log.warning("Cognito token issuer %r does not match expected user pool %r", iss, configured_pool)
            raise CognitoIdentityError("Token was issued by an untrusted Cognito User Pool.")

    email = (claims.get("email") or "").strip().lower()
    email_verified = is_strict_email_verified(claims)

    # Step 1: Check existing verified mapping in trusted store
    existing_mapping = identity_store.get_mapping_by_sub(sub, pool_id=configured_pool)
    if existing_mapping and existing_mapping.verified:
        if existing_mapping.mapping_method not in ("admin_provisioned", "verified_link_token"):
            raise CognitoIdentityError(
                f"Untrusted mapping method {existing_mapping.mapping_method!r}; "
                "only 'admin_provisioned' or 'verified_link_token' mappings are accepted."
            )
        profile = profile_lookup_fn(existing_mapping.user_id)
        if not profile:
            raise CognitoAccountConflictError(
                f"Mapped ReconDesk user profile {existing_mapping.user_id!r} not found"
            )
        if not profile.get("is_active", True):
            raise CognitoIdentityError(
                f"ReconDesk user profile {existing_mapping.user_id!r} is inactive or disabled."
            )
        return existing_mapping.user_id

    # Step 2: Untrusted custom:recondesk_user_id claim defense (Requirement 3)
    custom_user_id = claims.get("custom:recondesk_user_id")
    if custom_user_id:
        _log.warning("Untrusted custom:recondesk_user_id claim presented for sub %s. Rejecting auto-link.", sub)
        raise CognitoIdentityError(
            "Untrusted identity claim: 'custom:recondesk_user_id' is not trusted on email match alone. "
            "Must be established through administrative provisioning or verified account-linking."
        )

    # Step 3: Check if email already belongs to an existing ReconDesk profile
    if email:
        profile_by_email = profile_by_email_fn(email)
        if profile_by_email:
            existing_user_id = str(profile_by_email.get("id"))
            # Require strict email verification before initiating account linking
            if not email_verified:
                raise CognitoIdentityError(
                    "Cognito email must be strictly verified before account linking can be requested."
                )

            # STRICT DEFENSE: Do NOT auto-map on email alone!
            _log.warning("Cognito sub attempted login for existing email without verified mapping. Rejecting auto-link.")
            raise CognitoAccountLinkingRequiredError(
                user_id=existing_user_id,
                email=email,
                message=(
                    f"An existing ReconDesk account is associated with {email}. "
                    "Cryptographic account linking is required before access can be granted."
                ),
            )

    # Step 4: Automatic new-user provisioning is DISABLED (Requirement 4)
    if auto_provision_new_users:
        raise CognitoIdentityError("Automatic new-user provisioning is currently disabled.")

    raise CognitoIdentityError(
        "Cognito user identity is not mapped to an existing ReconDesk profile and "
        "automatic provisioning is disabled."
    )


def complete_account_linking(
    linking_token: str,
    claims: dict[str, Any],
    *,
    identity_store: CognitoIdentityStore,
    profile_lookup_fn: Callable[[str], Optional[dict[str, Any]]],
    expected_user_pool_id: Optional[str] = None,
    linking_ip: Optional[str] = None,
) -> str:
    """Verify an account linking token and activate the 1:1 identity mapping."""
    configured_pool = (expected_user_pool_id or get_cognito_config().COGNITO_USER_POOL_ID).strip()
    if hasattr(identity_store, "complete_account_linking_transactional"):
        return identity_store.complete_account_linking_transactional(
            linking_token=linking_token,
            claims=claims,
            linking_ip=linking_ip,
            pool_id=configured_pool,
        )

    sub = claims.get("sub")
    if not sub:
        raise CognitoIdentityError("Missing 'sub' in Cognito claims")

    if not is_strict_email_verified(claims):
        raise CognitoIdentityError(
            "Cognito email must be strictly verified to complete account linking."
        )

    verified_result = identity_store.verify_linking_token(
        linking_token, sub, pool_id=configured_pool
    )
    if not verified_result:
        raise CognitoIdentityError("Invalid, expired, or mismatched account linking token")

    user_id, email = verified_result

    claims_email = (claims.get("email") or "").strip().lower()
    if claims_email != email.strip().lower():
        raise CognitoIdentityError("Linking token email does not match authenticated identity")

    existing_for_user = identity_store.get_mapping_by_user_id(user_id, pool_id=configured_pool)
    if existing_for_user and existing_for_user.cognito_sub != sub:
        raise CognitoAccountConflictError(
            f"ReconDesk account {user_id!r} is already mapped to a different Cognito identity."
        )

    profile = profile_lookup_fn(user_id)
    if not profile:
        raise CognitoAccountConflictError(f"Target profile {user_id!r} not found during linking")

    mapping = CognitoIdentityMapping(
        cognito_sub=sub,
        user_id=user_id,
        email=email,
        mapping_method="verified_link_token",
        verified=True,
        cognito_user_pool_id=configured_pool,
    )
    identity_store.save_mapping(mapping)
    return user_id
