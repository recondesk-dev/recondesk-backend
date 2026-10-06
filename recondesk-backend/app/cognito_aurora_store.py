"""SQLAlchemy-backed Amazon Cognito identity store for AWS Aurora PostgreSQL.

Provides transactional, concurrency-safe account mapping and verification
while preserving existing ReconDesk user UUIDs, firm ownership, and staff roles.
Isolates user identities by Cognito User Pool and stores persistent hashed linking tokens.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.cognito_config import get_cognito_config
from app.cognito_identity import (
    CognitoAccountConflictError,
    CognitoIdentityError,
    CognitoIdentityMapping,
    CognitoIdentityStore,
    InMemoryCognitoIdentityStore,
    is_strict_email_verified,
)
from app.models.cognito_schema import (
    CognitoAccountLinkingTokenModel,
    CognitoUserMappingModel,
    UserProfileModel,
)

_log = logging.getLogger("recondesk.cognito.store")


def _sanitize_db_message(exc: Exception, default_msg: str) -> str:
    """Return a sanitized error message devoid of credentials, connection strings,
    or raw database schema internals.
    """
    _log.warning("Database error encountered: %s", type(exc).__name__)
    return default_msg


def verify_ownership_proof(
    user_id: str,
    email: str,
    proof: Optional[dict[str, Any]],
) -> bool:
    """Verify trusted, server-side proof of existing ReconDesk account ownership.

    Security Policies (Items 1 & 2):
      - 'mock_test_proof' is strictly prohibited from runtime paths.
      - Never trust an 'admin_session' dictionary supplied by a request.
      - An ordinary firm administrator must not be able to link another user's account
        without that user's verified proof of ownership.
      - Only trusted, server-side verified credentials (active Supabase JWT or
        password verified against Supabase Auth) are accepted at runtime.
    """
    if not proof or not isinstance(proof, dict):
        return False

    proof_type = proof.get("type")

    # Reject any spoofed test or admin dictionaries
    if proof_type in ("mock_test_proof", "admin_session", "admin_override"):
        _log.warning("Rejected disallowed ownership proof type in runtime path: %s", proof_type)
        return False

    # 1. Active Supabase Session Token / JWT proof
    if proof_type == "supabase_jwt":
        token = proof.get("token")
        if not token or not isinstance(token, str):
            return False
        try:
            from app.auth import _decode_and_verify_token_network_first
            payload = _decode_and_verify_token_network_first(token)
            jwt_sub = payload.get("sub")
            jwt_email = (payload.get("email") or "").strip().lower()
            return jwt_sub == user_id and (not email or jwt_email == email.strip().lower())
        except Exception as exc:
            _log.warning("Supabase JWT ownership proof verification failed: %s", type(exc).__name__)
            return False

    # 2. Supabase password credential proof
    if proof_type == "supabase_password":
        password = proof.get("password")
        if not password or not isinstance(password, str):
            return False
        try:
            from app.database import get_supabase
            sb = get_supabase()
            res = sb.auth.sign_in_with_password({"email": email, "password": password})
            if res and res.user and str(res.user.id) == user_id:
                return True
            return False
        except Exception as exc:
            _log.warning("Supabase password ownership proof verification failed: %s", type(exc).__name__)
            return False

    return False


class SQLAlchemyCognitoIdentityStore(CognitoIdentityStore):
    """Transactional, thread-safe identity mapping store backed by AWS Aurora PostgreSQL.

    Guarantees:
      1. Strict 1:1 bijection within each Cognito User Pool.
      2. Persistent linking tokens stored strictly as SHA-256 hashes (never plaintext).
      3. Atomic token consumption and mapping creation inside a single transaction with row locking.
      4. Rollback safety: failed transactions never consume tokens.
      5. Protection against unauthorized privilege escalation or direct verified mapping insertion via save_mapping().
      6. User pool isolation derived strictly from trusted server configuration.
      7. Sanitized client responses and logs containing no credentials, tokens, or DB internals.
    """

    def __init__(
        self,
        session_factory: Optional[sessionmaker[Session]] = None,
        engine: Optional[Engine] = None,
        user_pool_id: Optional[str] = None,
    ) -> None:
        if session_factory is not None:
            self._session_factory = session_factory
        elif engine is not None:
            self._session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        else:
            # Lazy import from app.aurora to prevent circular dependencies
            from app.aurora import get_aurora_sessionmaker
            self._session_factory = get_aurora_sessionmaker()

        config = get_cognito_config()
        self._user_pool_id = (user_pool_id or config.COGNITO_USER_POOL_ID).strip()

    @property
    def user_pool_id(self) -> str:
        return self._user_pool_id

    def _get_session(self) -> Session:
        return self._session_factory()

    def get_mapping_by_sub(
        self, cognito_sub: str, pool_id: Optional[str] = None
    ) -> Optional[CognitoIdentityMapping]:
        """Fetch verified identity mapping by Cognito sub within the target user pool."""
        sub = (cognito_sub or "").strip()
        if not sub:
            return None
        target_pool = (pool_id or self._user_pool_id).strip()

        with self._get_session() as session:
            stmt = select(CognitoUserMappingModel).where(
                CognitoUserMappingModel.cognito_user_pool_id == target_pool,
                CognitoUserMappingModel.cognito_sub == sub,
            )
            record = session.scalar(stmt)
            if record is None:
                return None
            return record.to_domain()

    def get_mapping_by_user_id(
        self, user_id: str, pool_id: Optional[str] = None
    ) -> Optional[CognitoIdentityMapping]:
        """Fetch verified identity mapping by ReconDesk user_profiles.id within the target user pool."""
        uid = (user_id or "").strip()
        if not uid:
            return None
        target_pool = (pool_id or self._user_pool_id).strip()

        with self._get_session() as session:
            stmt = select(CognitoUserMappingModel).where(
                CognitoUserMappingModel.cognito_user_pool_id == target_pool,
                CognitoUserMappingModel.user_id == uid,
            )
            record = session.scalar(stmt)
            if record is None:
                return None
            return record.to_domain()

    def lookup_trusted_mapping(
        self,
        cognito_sub: str,
        pool_id: Optional[str] = None,
        profile_lookup_fn: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
    ) -> Optional[dict[str, Any]]:
        """Look up an exact, verified Cognito identity mapping in Aurora.

        Requirements:
          - Exact match on cognito_user_pool_id and cognito_sub
          - is_verified must be True
          - Mapped user_profiles row must exist and have is_active == True
          - Never matches on email alone; never auto-creates mappings.
        """
        sub = str(cognito_sub or "").strip()
        if not sub:
            return None
        target_pool = (pool_id or self._user_pool_id).strip()
        if not target_pool:
            return None

        with self._get_session() as session:
            stmt = select(CognitoUserMappingModel).where(
                CognitoUserMappingModel.cognito_user_pool_id == target_pool,
                CognitoUserMappingModel.cognito_sub == sub,
                CognitoUserMappingModel.is_verified.is_(True),
            )
            mapping = session.scalar(stmt)
            if mapping is None:
                return None

            profile_stmt = select(UserProfileModel).where(
                UserProfileModel.id == mapping.user_id,
                UserProfileModel.is_active.is_(True),
            )
            profile = session.scalar(profile_stmt)
            if profile is None:
                return None

            return {
                "user_id": str(mapping.user_id),
                "cognito_sub": mapping.cognito_sub,
                "cognito_user_pool_id": mapping.cognito_user_pool_id,
                "email": mapping.email,
                "mapping_method": mapping.mapping_method,
                "is_verified": True,
                "profile": {
                    "id": str(profile.id),
                    "email": profile.email,
                    "role": profile.role,
                    "is_active": bool(profile.is_active),
                    "full_name": profile.full_name,
                    "firm_name": profile.firm_name,
                },
            }

    def get_user_profile_by_id(
        self, user_id: str
    ) -> Optional[dict[str, Any]]:
        """Fetch user profile from Aurora public.user_profiles by primary key UUID."""
        uid = str(user_id or "").strip()
        if not uid:
            return None
        try:
            with self._get_session() as session:
                profile = session.scalar(
                    select(UserProfileModel).where(UserProfileModel.id == uid)
                )
                if profile is None:
                    return None
                return {
                    "id": str(profile.id),
                    "email": profile.email,
                    "role": profile.role,
                    "is_active": bool(profile.is_active),
                    "full_name": profile.full_name,
                    "firm_name": profile.firm_name,
                }
        except Exception as exc:
            _log.warning("Aurora user profile lookup failed: %s", type(exc).__name__)
            return None

    def get_user_profile_by_email(
        self, email: str
    ) -> Optional[dict[str, Any]]:
        """Fetch user profile from Aurora public.user_profiles by email."""
        clean_email = str(email or "").strip().lower()
        if not clean_email:
            return None
        try:
            with self._get_session() as session:
                profile = session.scalar(
                    select(UserProfileModel).where(UserProfileModel.email.ilike(clean_email))
                )
                if profile is None:
                    return None
                return {
                    "id": str(profile.id),
                    "email": profile.email,
                    "role": profile.role,
                    "is_active": bool(profile.is_active),
                    "full_name": profile.full_name,
                    "firm_name": profile.firm_name,
                }
        except Exception as exc:
            _log.warning("Aurora user profile email lookup failed: %s", type(exc).__name__)
            return None

    def save_mapping(self, mapping: CognitoIdentityMapping) -> None:
        """Persist or update an unverified identity mapping.

        Security Enforcement (Item 4):
          - DIRECT INSERTION OF VERIFIED MAPPINGS IS PROHIBITED.
            Verified mappings must be created exclusively via admin_provision_mapping()
            or complete_account_linking_transactional().
          - Prevents modifying `mapping_method` or `is_verified` on existing mappings.
          - Enforces user pool isolation.
        """
        pool_id = (mapping.cognito_user_pool_id or self._user_pool_id).strip()

        # Item 4: Prevent save_mapping() from directly inserting verified mappings
        if mapping.verified:
            with self._get_session() as session:
                existing = session.scalar(
                    select(CognitoUserMappingModel).where(
                        CognitoUserMappingModel.cognito_user_pool_id == pool_id,
                        CognitoUserMappingModel.cognito_sub == mapping.cognito_sub,
                    )
                )
                if existing is None:
                    raise CognitoIdentityError(
                        "Cannot directly insert verified mappings via save_mapping(). "
                        "Verified mappings must be established exclusively via admin_provision_mapping() "
                        "or complete_account_linking_transactional()."
                    )

        with self._get_session() as session:
            try:
                stmt = select(CognitoUserMappingModel).where(
                    CognitoUserMappingModel.cognito_user_pool_id == pool_id,
                    CognitoUserMappingModel.cognito_sub == mapping.cognito_sub,
                )
                existing = session.scalar(stmt)

                if existing is not None:
                    # Enforce Item 4: Prevent changing mapping_method or is_verified via save_mapping
                    if (
                        existing.mapping_method != mapping.mapping_method
                        or bool(existing.is_verified) != bool(mapping.verified)
                    ):
                        raise CognitoIdentityError(
                            "Unauthorized mapping modification: cannot change mapping_method or "
                            "verification status via save_mapping."
                        )

                    # Cross-account check
                    if str(existing.user_id) != str(mapping.user_id):
                        raise CognitoAccountConflictError(
                            "Cognito identity is already bound to a different ReconDesk user."
                        )
                    existing.email = mapping.email.strip().lower()
                    existing.updated_at = datetime.now(timezone.utc)
                else:
                    new_record = CognitoUserMappingModel(
                        cognito_user_pool_id=pool_id,
                        cognito_sub=mapping.cognito_sub,
                        user_id=mapping.user_id,
                        email=mapping.email.strip().lower(),
                        mapping_method=mapping.mapping_method,
                        is_verified=False,
                    )
                    session.add(new_record)

                session.commit()
            except (CognitoIdentityError, CognitoAccountConflictError):
                session.rollback()
                raise
            except IntegrityError as exc:
                session.rollback()
                _log.warning("IntegrityError saving Cognito mapping: %s", type(exc).__name__)
                raise CognitoAccountConflictError(
                    "Conflict persisting identity mapping: account or identity is already mapped."
                ) from exc
            except Exception:
                session.rollback()
                raise

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
        """Administratively provision a trusted 1:1 mapping prior to user sign-in.

        Fails closed if the ReconDesk profile does not exist or is inactive.
        """
        uid = str(user_id).strip()
        sub = str(cognito_sub).strip()
        clean_email = (email or "").strip().lower()
        target_pool = (pool_id or self._user_pool_id).strip()

        with self._get_session() as session:
            try:
                # 1. Profile existence and activity check
                profile_stmt = select(UserProfileModel).where(UserProfileModel.id == uid)
                profile = session.scalar(profile_stmt)
                if profile is None:
                    raise CognitoIdentityError(f"ReconDesk user profile {uid!r} does not exist.")
                if not profile.is_active:
                    raise CognitoIdentityError(f"ReconDesk user profile {uid!r} is inactive or disabled.")

                # 2. Check for duplicate user_id within target pool
                user_check_stmt = select(CognitoUserMappingModel).where(
                    CognitoUserMappingModel.cognito_user_pool_id == target_pool,
                    CognitoUserMappingModel.user_id == uid,
                )
                existing_for_user = session.scalar(user_check_stmt)
                if existing_for_user and existing_for_user.cognito_sub != sub:
                    raise CognitoAccountConflictError(
                        f"ReconDesk user {uid!r} is already mapped to Cognito identity {existing_for_user.cognito_sub!r}."
                    )

                # 3. Check for duplicate cognito_sub within target pool
                sub_check_stmt = select(CognitoUserMappingModel).where(
                    CognitoUserMappingModel.cognito_user_pool_id == target_pool,
                    CognitoUserMappingModel.cognito_sub == sub,
                )
                existing_for_sub = session.scalar(sub_check_stmt)
                if existing_for_sub and str(existing_for_sub.user_id) != uid:
                    raise CognitoAccountConflictError(
                        f"Cognito identity {sub!r} is already mapped to user {existing_for_sub.user_id!r}."
                    )

                if existing_for_sub is not None:
                    existing_for_sub.email = clean_email
                    existing_for_sub.mapping_method = "admin_provisioned"
                    existing_for_sub.is_verified = True
                    existing_for_sub.provisioned_by = provisioned_by
                    existing_for_sub.linking_ip = linking_ip
                    existing_for_sub.metadata_json = metadata or {}
                    existing_for_sub.updated_at = datetime.now(timezone.utc)
                    record = existing_for_sub
                else:
                    record = CognitoUserMappingModel(
                        cognito_user_pool_id=target_pool,
                        cognito_sub=sub,
                        user_id=uid,
                        email=clean_email,
                        mapping_method="admin_provisioned",
                        is_verified=True,
                        provisioned_by=provisioned_by,
                        linking_ip=linking_ip,
                        metadata_json=metadata or {},
                    )
                    session.add(record)

                session.commit()
                return record.to_domain()
            except IntegrityError as exc:
                session.rollback()
                raise CognitoAccountConflictError(
                    "Integrity violation during administrative provisioning: duplicate mapping detected."
                ) from exc
            except Exception:
                session.rollback()
                raise

    def _create_linking_token_internal(
        self,
        user_id: str,
        cognito_sub: str,
        email: str,
        pool_id: Optional[str] = None,
        ttl_seconds: int = 900,
        created_ip: Optional[str] = None,
    ) -> str:
        """Internal underlying token-creation operation invoked ONLY after authorization (Item 3).

        Requirement 1: Never stores plaintext linking tokens in the database.
        """
        uid = str(user_id).strip()
        sub = str(cognito_sub).strip()
        clean_email = (email or "").strip().lower()
        target_pool = (pool_id or self._user_pool_id).strip()

        with self._get_session() as session:
            # Profile validation: target profile must exist and be active
            profile = session.scalar(select(UserProfileModel).where(UserProfileModel.id == uid))
            if profile is None:
                raise CognitoIdentityError(f"ReconDesk user profile {uid!r} does not exist.")
            if not profile.is_active:
                raise CognitoIdentityError(f"ReconDesk user profile {uid!r} is inactive or disabled.")

            # Generate high-entropy plaintext token for the client
            raw_token = secrets.token_urlsafe(32)
            # Store only the SHA-256 digest in Aurora
            token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

            token_record = CognitoAccountLinkingTokenModel(
                token_hash=token_hash,
                cognito_user_pool_id=target_pool,
                cognito_sub=sub,
                user_id=uid,
                email=clean_email,
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
                created_ip=created_ip,
            )
            session.add(token_record)
            session.commit()

        return raw_token

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
        """Issue a persistent account-linking token ONLY after trusted server-side proof
        of existing ReconDesk account ownership (Requirements 2 & 3).

        Invokes the internal token-creation operation only after verification.
        """
        uid = str(user_id).strip()
        sub = str(cognito_sub).strip()
        clean_email = (email or "").strip().lower()
        target_pool = (pool_id or self._user_pool_id).strip()

        # Item 1 & 2: Verify trusted server-side proof of existing account ownership
        verifier = verify_proof_fn or verify_ownership_proof
        is_proven = verifier(uid, clean_email, ownership_proof)
        if not is_proven:
            _log.warning("Rejected token issuance: ownership proof verification failed")
            raise CognitoIdentityError(
                "Account linking token issuance rejected: trusted server-side proof of "
                "existing ReconDesk account ownership is required."
            )

        return self._create_linking_token_internal(
            user_id=uid,
            cognito_sub=sub,
            email=clean_email,
            pool_id=target_pool,
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
        self,
        token: str,
        cognito_sub: str,
        pool_id: Optional[str] = None,
    ) -> Optional[tuple[str, str]]:
        """Inspect and verify a linking token without consuming it.

        Returns (user_id, email) if valid and unconsumed, None otherwise.
        """
        clean_token = (token or "").strip()
        if not clean_token:
            return None

        token_hash = hashlib.sha256(clean_token.encode("utf-8")).hexdigest()
        target_pool = (pool_id or self._user_pool_id).strip()
        now = datetime.now(timezone.utc)

        with self._get_session() as session:
            stmt = select(CognitoAccountLinkingTokenModel).where(
                CognitoAccountLinkingTokenModel.token_hash == token_hash
            )
            record = session.scalar(stmt)
            if not record:
                return None
            if record.consumed_at is not None:
                return None
            record_exp = record.expires_at
            if record_exp.tzinfo is None:
                record_exp = record_exp.replace(tzinfo=timezone.utc)
            if now > record_exp:
                return None
            if record.cognito_sub != cognito_sub:
                return None
            if record.cognito_user_pool_id != target_pool:
                return None
            return str(record.user_id), record.email

    def complete_account_linking_transactional(
        self,
        linking_token: str,
        claims: dict[str, Any],
        linking_ip: Optional[str] = None,
        pool_id: Optional[str] = None,
    ) -> str:
        """Atomically consume a linking token and establish the identity mapping in a single transaction.

        Requirements 3, 5, 6, 7 & 9:
          - Uses row-level locking or atomic conditional state verification.
          - Verified email & subject matching.
          - Pool ID derived strictly from trusted server configuration.
          - Failed transactions rollback cleanly without consuming the token.
          - Strips credentials and raw DB exceptions.
        """
        sub = (claims.get("sub") or "").strip()
        if not sub:
            raise CognitoIdentityError("Missing 'sub' in Cognito claims")

        if not is_strict_email_verified(claims):
            raise CognitoIdentityError("Cognito email must be strictly verified to complete account linking.")

        claims_email = (claims.get("email") or "").strip().lower()
        if not claims_email:
            raise CognitoIdentityError("Missing 'email' in Cognito claims")

        clean_token = (linking_token or "").strip()
        if not clean_token:
            raise CognitoIdentityError("Invalid, expired, or mismatched account linking token")

        token_hash = hashlib.sha256(clean_token.encode("utf-8")).hexdigest()
        target_pool = self._user_pool_id
        now = datetime.now(timezone.utc)

        # Validate token issuer claim against trusted server pool ID (Item 5)
        iss = claims.get("iss")
        if iss and not iss.endswith(target_pool):
            _log.warning("Token issuer mismatch during account linking")
            raise CognitoIdentityError("Token was issued by an untrusted Cognito User Pool.")

        with self._get_session() as session:
            try:
                # 1. Query linking token with row lock (FOR UPDATE on PostgreSQL)
                token_stmt = select(CognitoAccountLinkingTokenModel).where(
                    CognitoAccountLinkingTokenModel.token_hash == token_hash
                )
                if session.bind and session.bind.dialect.name == "postgresql":
                    token_stmt = token_stmt.with_for_update()

                token_record = session.scalar(token_stmt)
                if token_record is None:
                    raise CognitoIdentityError("Invalid, expired, or mismatched account linking token")

                if token_record.consumed_at is not None:
                    raise CognitoIdentityError("Invalid, expired, or mismatched account linking token")

                record_exp = token_record.expires_at
                if record_exp.tzinfo is None:
                    record_exp = record_exp.replace(tzinfo=timezone.utc)
                if now > record_exp:
                    raise CognitoIdentityError("Invalid, expired, or mismatched account linking token")

                # Verify subject, pool, and email match strictly
                if token_record.cognito_sub != sub:
                    raise CognitoIdentityError("Invalid, expired, or mismatched account linking token")

                if token_record.cognito_user_pool_id != target_pool:
                    raise CognitoIdentityError("Invalid, expired, or mismatched account linking token")

                if token_record.email.strip().lower() != claims_email:
                    raise CognitoIdentityError("Invalid, expired, or mismatched account linking token")

                user_id = str(token_record.user_id)

                # 2. Profile existence and activity validation with lock
                profile_stmt = select(UserProfileModel).where(UserProfileModel.id == user_id)
                if session.bind and session.bind.dialect.name == "postgresql":
                    profile_stmt = profile_stmt.with_for_update()

                profile = session.scalar(profile_stmt)
                if profile is None:
                    raise CognitoAccountConflictError(f"ReconDesk user profile {user_id!r} not found.")
                if not profile.is_active:
                    raise CognitoIdentityError(f"ReconDesk user profile {user_id!r} is inactive or disabled.")

                # 3. Cross-account check on user_id within target pool
                user_check = select(CognitoUserMappingModel).where(
                    CognitoUserMappingModel.cognito_user_pool_id == target_pool,
                    CognitoUserMappingModel.user_id == user_id,
                )
                if session.bind and session.bind.dialect.name == "postgresql":
                    user_check = user_check.with_for_update()

                existing_for_user = session.scalar(user_check)
                if existing_for_user and existing_for_user.cognito_sub != sub:
                    raise CognitoAccountConflictError(
                        f"ReconDesk account {user_id!r} is already mapped to a different Cognito identity."
                    )

                # 4. Cross-account check on cognito_sub within target pool
                sub_check = select(CognitoUserMappingModel).where(
                    CognitoUserMappingModel.cognito_user_pool_id == target_pool,
                    CognitoUserMappingModel.cognito_sub == sub,
                )
                if session.bind and session.bind.dialect.name == "postgresql":
                    sub_check = sub_check.with_for_update()

                existing_for_sub = session.scalar(sub_check)
                if existing_for_sub and str(existing_for_sub.user_id) != user_id:
                    raise CognitoAccountConflictError(
                        f"Cognito identity {sub!r} is already mapped to a different user ({existing_for_sub.user_id!r})."
                    )

                # 5. ATOMIC CONSUMPTION: Mark token consumed in the same transaction
                token_record.consumed_at = now
                token_record.consumed_ip = linking_ip

                # 6. Create or update mapping
                if existing_for_sub is not None:
                    existing_for_sub.email = claims_email
                    existing_for_sub.mapping_method = "verified_link_token"
                    existing_for_sub.is_verified = True
                    existing_for_sub.linking_ip = linking_ip
                    existing_for_sub.updated_at = now
                else:
                    mapping = CognitoUserMappingModel(
                        cognito_user_pool_id=target_pool,
                        cognito_sub=sub,
                        user_id=user_id,
                        email=claims_email,
                        mapping_method="verified_link_token",
                        is_verified=True,
                        linking_ip=linking_ip,
                    )
                    session.add(mapping)

                session.commit()
                return user_id
            except (CognitoIdentityError, CognitoAccountConflictError):
                session.rollback()
                raise
            except IntegrityError as exc:
                session.rollback()
                _log.warning("Integrity error during account linking: %s", type(exc).__name__)
                raise CognitoAccountConflictError(
                    f"Concurrent linking conflict for user={user_id} or sub={sub}: unique constraint violated"
                ) from exc
            except Exception as exc:
                session.rollback()
                _log.warning("Unexpected error during account linking: %s", type(exc).__name__)
                raise CognitoIdentityError(
                    _sanitize_db_message(exc, "Database transaction failed during account linking.")
                ) from exc


# Singleton instance for identity store
_identity_store: Optional[CognitoIdentityStore] = None


def get_identity_store() -> CognitoIdentityStore:
    """Return the configured Cognito identity mapping store (SQLAlchemy/Aurora or InMemory fallback).

    Security Invariant:
      If Aurora is enabled or configured, failure to initialize the SQLAlchemy store
      must FAIL CLOSED. It must never silently fall back to InMemoryCognitoIdentityStore,
      nor leak database credentials, connection URLs, or raw exception strings.
    """
    global _identity_store
    if _identity_store is not None:
        return _identity_store

    from app.aurora import is_aurora_enabled, get_aurora_database_url

    aurora_configured = bool(is_aurora_enabled() and get_aurora_database_url())

    if aurora_configured:
        try:
            _identity_store = SQLAlchemyCognitoIdentityStore()
            return _identity_store
        except Exception as exc:
            _log.error(
                "Failed to initialize SQLAlchemyCognitoIdentityStore: %s",
                type(exc).__name__,
            )
            raise CognitoIdentityError(
                "Failed to initialize Aurora identity mapping store."
            ) from None

    _identity_store = InMemoryCognitoIdentityStore()
    return _identity_store


def set_identity_store(store: Optional[CognitoIdentityStore]) -> None:
    """Override or reset the identity mapping store (useful for tests)."""
    global _identity_store
    _identity_store = store
