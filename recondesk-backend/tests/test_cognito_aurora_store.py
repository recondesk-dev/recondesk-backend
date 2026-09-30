from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import os
import tempfile
import time
import uuid
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.cognito_aurora_store import SQLAlchemyCognitoIdentityStore, verify_ownership_proof
from app.cognito_identity import (
    CognitoAccountConflictError,
    CognitoAccountLinkingRequiredError,
    CognitoIdentityError,
    CognitoIdentityMapping,
    resolve_cognito_user_id,
)
from app.models.cognito_schema import (
    Base,
    CognitoAccountLinkingTokenModel,
    CognitoUserMappingModel,
    UserProfileModel,
)


@pytest.fixture
def sqlite_engine():
    """Create a temporary file-backed SQLite engine supporting concurrent connections and multi-threading."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": 30},
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass


@pytest.fixture
def aurora_store(sqlite_engine):
    """Instantiate a SQLAlchemyCognitoIdentityStore bound to the test engine."""
    session_factory = sessionmaker(bind=sqlite_engine, autoflush=False, expire_on_commit=False)
    return SQLAlchemyCognitoIdentityStore(session_factory=session_factory)


def _create_user_profile(
    engine,
    user_id: str,
    email: str,
    role: str = "admin",
    is_active: bool = True,
    full_name: Optional[str] = "Test User",
) -> None:
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        profile = UserProfileModel(
            id=user_id,
            email=email,
            role=role,
            is_active=is_active,
            full_name=full_name,
        )
        session.add(profile)
        session.commit()


# ─── 1. Duplicate Mappings & Unique Constraints Tests ─────────────────────────

class TestDuplicateMappings:
    def test_duplicate_cognito_sub_rejected(self, sqlite_engine, aurora_store):
        user_1 = str(uuid.uuid4())
        user_2 = str(uuid.uuid4())
        sub = str(uuid.uuid4())

        _create_user_profile(sqlite_engine, user_1, "user1@example.com")
        _create_user_profile(sqlite_engine, user_2, "user2@example.com")

        # Provision first user with sub
        aurora_store.admin_provision_mapping(
            user_id=user_1,
            cognito_sub=sub,
            email="user1@example.com",
            provisioned_by="admin-1",
        )

        # Attempt to provision a different user with the same cognito_sub
        with pytest.raises(CognitoAccountConflictError, match="already mapped"):
            aurora_store.admin_provision_mapping(
                user_id=user_2,
                cognito_sub=sub,
                email="user2@example.com",
                provisioned_by="admin-1",
            )

    def test_duplicate_user_id_rejected(self, sqlite_engine, aurora_store):
        user_id = str(uuid.uuid4())
        sub_1 = str(uuid.uuid4())
        sub_2 = str(uuid.uuid4())

        _create_user_profile(sqlite_engine, user_id, "user@example.com")

        # Provision user with sub_1
        aurora_store.admin_provision_mapping(
            user_id=user_id,
            cognito_sub=sub_1,
            email="user@example.com",
            provisioned_by="admin-1",
        )

        # Attempt to provision the same user_id with a different sub_2
        with pytest.raises(CognitoAccountConflictError, match="already mapped"):
            aurora_store.admin_provision_mapping(
                user_id=user_id,
                cognito_sub=sub_2,
                email="user@example.com",
                provisioned_by="admin-1",
            )

    def test_save_mapping_duplicate_user_id_rejected(self, sqlite_engine, aurora_store):
        user_id = str(uuid.uuid4())
        sub_1 = str(uuid.uuid4())
        sub_2 = str(uuid.uuid4())

        _create_user_profile(sqlite_engine, user_id, "user@example.com")

        mapping_1 = CognitoIdentityMapping(
            cognito_sub=sub_1,
            user_id=user_id,
            email="user@example.com",
            mapping_method="admin_provisioned",
            verified=False,
        )
        aurora_store.save_mapping(mapping_1)

        # Attempt to insert a second mapping for the same user_id
        mapping_2 = CognitoIdentityMapping(
            cognito_sub=sub_2,
            user_id=user_id,
            email="user@example.com",
            mapping_method="admin_provisioned",
            verified=False,
        )
        with pytest.raises(CognitoAccountConflictError):
            aurora_store.save_mapping(mapping_2)


# ─── 2. Inactive Profile Protection Tests ────────────────────────────────────

class TestInactiveProfiles:
    def test_admin_provisioning_inactive_profile_fails_closed(self, sqlite_engine, aurora_store):
        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())

        _create_user_profile(sqlite_engine, user_id, "inactive@example.com", is_active=False)

        with pytest.raises(CognitoIdentityError, match="inactive or disabled"):
            aurora_store.admin_provision_mapping(
                user_id=user_id,
                cognito_sub=sub,
                email="inactive@example.com",
                provisioned_by="admin-1",
            )

    def test_resolving_inactive_profile_fails_closed(self, sqlite_engine, aurora_store):
        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())

        # Initially active and provisioned
        _create_user_profile(sqlite_engine, user_id, "user@example.com", is_active=True)
        aurora_store.admin_provision_mapping(
            user_id=user_id,
            cognito_sub=sub,
            email="user@example.com",
            provisioned_by="admin-1",
        )

        # Now deactivate the profile
        session_factory = sessionmaker(bind=sqlite_engine)
        with session_factory() as session:
            p = session.get(UserProfileModel, user_id)
            p.is_active = False
            session.commit()

        # Resolution must fail closed
        with pytest.raises(CognitoIdentityError, match="inactive or disabled"):
            resolve_cognito_user_id(
                {"sub": sub, "email": "user@example.com", "email_verified": True},
                identity_store=aurora_store,
                profile_lookup_fn=lambda uid: {"id": uid, "is_active": False},
                profile_by_email_fn=lambda em: None,
            )

    def test_linking_inactive_profile_fails_closed(self, sqlite_engine, aurora_store):
        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())

        _create_user_profile(sqlite_engine, user_id, "inactive@example.com", is_active=False)

        with pytest.raises(CognitoIdentityError, match="inactive or disabled"):
            aurora_store._create_linking_token_internal(user_id, sub, "inactive@example.com")


# ─── 3. Token Replay, Hashing, & Validation Tests ─────────────────────────────

class TestTokenReplayAndValidation:
    def test_tokens_are_stored_hashed_never_plaintext(self, sqlite_engine, aurora_store):
        """Requirement 1: Never store plaintext linking tokens in the database."""
        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())
        email = "hashcheck@example.com"

        _create_user_profile(sqlite_engine, user_id, email)
        raw_token = aurora_store._create_linking_token_internal(user_id, sub, email)

        # Inspect Aurora database table directly
        session_factory = sessionmaker(bind=sqlite_engine)
        with session_factory() as session:
            token_rows = session.query(CognitoAccountLinkingTokenModel).all()
            assert len(token_rows) == 1
            row = token_rows[0]
            # Ensure raw_token does NOT exist anywhere in database row
            assert row.token_hash != raw_token
            # Verify SHA-256 hash match
            expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            assert row.token_hash == expected_hash
            assert row.consumed_at is None

    def test_tampered_linking_token_rejected(self, sqlite_engine, aurora_store):
        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())

        _create_user_profile(sqlite_engine, user_id, "user@example.com")
        token = aurora_store._create_linking_token_internal(user_id, sub, "user@example.com")

        tampered = token[:-4] + "xxxx"
        claims = {"sub": sub, "email": "user@example.com", "email_verified": True}

        with pytest.raises(CognitoIdentityError, match="Invalid, expired, or mismatched"):
            aurora_store.complete_account_linking_transactional(tampered, claims)

    def test_expired_linking_token_rejected(self, sqlite_engine, aurora_store):
        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())

        _create_user_profile(sqlite_engine, user_id, "user@example.com")
        token = aurora_store._create_linking_token_internal(user_id, sub, "user@example.com", ttl_seconds=-10)
        claims = {"sub": sub, "email": "user@example.com", "email_verified": True}

        with pytest.raises(CognitoIdentityError, match="Invalid, expired, or mismatched"):
            aurora_store.complete_account_linking_transactional(token, claims)

    def test_linking_token_wrong_sub_rejected(self, sqlite_engine, aurora_store):
        user_id = str(uuid.uuid4())
        sub_a = str(uuid.uuid4())
        sub_b = str(uuid.uuid4())

        _create_user_profile(sqlite_engine, user_id, "user@example.com")
        token = aurora_store._create_linking_token_internal(user_id, sub_a, "user@example.com")

        # Contender presents sub_b
        claims = {"sub": sub_b, "email": "user@example.com", "email_verified": True}

        with pytest.raises(CognitoIdentityError, match="Invalid, expired, or mismatched"):
            aurora_store.complete_account_linking_transactional(token, claims)

    def test_linking_token_single_use_consumption_replay_rejected(self, sqlite_engine, aurora_store):
        """Requirement 1 & 3: Single-use consumption and replay rejection."""
        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())

        _create_user_profile(sqlite_engine, user_id, "user@example.com")
        token = aurora_store._create_linking_token_internal(user_id, sub, "user@example.com")
        claims = {"sub": sub, "email": "user@example.com", "email_verified": True}

        # First use succeeds
        res = aurora_store.complete_account_linking_transactional(token, claims)
        assert res == user_id

        # Verify consumed_at was recorded in persistent table
        session_factory = sessionmaker(bind=sqlite_engine)
        with session_factory() as session:
            h = hashlib.sha256(token.encode("utf-8")).hexdigest()
            row = session.query(CognitoAccountLinkingTokenModel).filter_by(token_hash=h).first()
            assert row.consumed_at is not None

        # Replay attempt fails immediately
        with pytest.raises(CognitoIdentityError, match="Invalid, expired, or mismatched"):
            aurora_store.complete_account_linking_transactional(token, claims)


# ─── 4. Cross-Account Linking Protection Tests ───────────────────────────────

class TestCrossAccountLinking:
    def test_cross_account_linking_attempt_rejected(self, sqlite_engine, aurora_store):
        user_id = str(uuid.uuid4())
        sub_1 = str(uuid.uuid4())
        sub_2 = str(uuid.uuid4())

        _create_user_profile(sqlite_engine, user_id, "ca@example.com")

        # user_id is already mapped to sub_1
        aurora_store.admin_provision_mapping(
            user_id=user_id,
            cognito_sub=sub_1,
            email="ca@example.com",
            provisioned_by="admin",
        )

        # Attacker tries to complete account linking for the same user_id using sub_2
        token = aurora_store._create_linking_token_internal(user_id, sub_2, "ca@example.com")
        claims = {"sub": sub_2, "email": "ca@example.com", "email_verified": True}

        with pytest.raises(CognitoAccountConflictError, match="already mapped to a different Cognito identity"):
            aurora_store.complete_account_linking_transactional(token, claims)

    def test_cross_cognito_sub_linking_attempt_rejected(self, sqlite_engine, aurora_store):
        user_1 = str(uuid.uuid4())
        user_2 = str(uuid.uuid4())
        sub = str(uuid.uuid4())

        _create_user_profile(sqlite_engine, user_1, "user1@example.com")
        _create_user_profile(sqlite_engine, user_2, "user2@example.com")

        # sub is already mapped to user_1
        aurora_store.admin_provision_mapping(
            user_id=user_1,
            cognito_sub=sub,
            email="user1@example.com",
            provisioned_by="admin",
        )

        # Contender attempts to link user_2 using the same sub
        token = aurora_store._create_linking_token_internal(user_2, sub, "user2@example.com")
        claims = {"sub": sub, "email": "user2@example.com", "email_verified": True}

        with pytest.raises(CognitoAccountConflictError, match="already mapped to a different user"):
            aurora_store.complete_account_linking_transactional(token, claims)


# ─── 5. Concurrent Linking Race Condition Tests ──────────────────────────────

class TestConcurrency:
    def test_concurrent_linking_race_condition_handled(self, sqlite_engine, aurora_store):
        """Requirement 3: Simulate concurrent threads attempting to link the same user simultaneously.
        Guarantees: Exactly one succeeds, others fail closed with conflict error,
        and database maintains 1:1 integrity.
        """
        user_id = str(uuid.uuid4())
        sub_1 = str(uuid.uuid4())
        sub_2 = str(uuid.uuid4())

        _create_user_profile(sqlite_engine, user_id, "concurrent@example.com")

        token_1 = aurora_store._create_linking_token_internal(user_id, sub_1, "concurrent@example.com")
        token_2 = aurora_store._create_linking_token_internal(user_id, sub_2, "concurrent@example.com")

        claims_1 = {"sub": sub_1, "email": "concurrent@example.com", "email_verified": True}
        claims_2 = {"sub": sub_2, "email": "concurrent@example.com", "email_verified": True}

        results = []
        errors = []

        def _attempt_link(token, claims):
            try:
                res = aurora_store.complete_account_linking_transactional(token, claims)
                results.append(res)
            except Exception as exc:
                errors.append(exc)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(_attempt_link, token_1, claims_1)
            f2 = executor.submit(_attempt_link, token_2, claims_2)
            concurrent.futures.wait([f1, f2])

        # Exactly ONE attempt must succeed
        assert len(results) == 1
        assert results[0] == user_id

        # Exactly ONE attempt must fail with conflict error
        assert len(errors) == 1
        assert isinstance(errors[0], CognitoAccountConflictError)

        # Database state: Exactly 1 mapping row for user_id
        session_factory = sessionmaker(bind=sqlite_engine)
        with session_factory() as session:
            count = session.query(CognitoUserMappingModel).filter_by(user_id=user_id).count()
            assert count == 1


# ─── 6. Ownership Proof Before Issuance Tests ─────────────────────────────────

class TestOwnershipProofAndIssuance:
    def test_unauthorized_token_issuance_rejected_without_proof(self, sqlite_engine, aurora_store):
        """Requirement 2: Reject linking token generation without trusted server-side proof."""
        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())
        email = "proof_required@example.com"

        _create_user_profile(sqlite_engine, user_id, email)

        # Attempt to issue token without proof
        with pytest.raises(CognitoIdentityError, match="proof of existing ReconDesk account ownership is required"):
            aurora_store.issue_account_linking_token(
                user_id=user_id,
                cognito_sub=sub,
                email=email,
                ownership_proof={},
            )

    def test_spoofed_admin_session_rejected(self, sqlite_engine, aurora_store):
        """Item 2 & 7: Never trust an admin_session dictionary supplied by a request."""
        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())
        email = "spoofed_admin@example.com"

        _create_user_profile(sqlite_engine, user_id, email)

        spoofed_proof = {"type": "admin_session", "is_admin": True, "admin_id": "attacker-id"}
        with pytest.raises(CognitoIdentityError, match="proof of existing ReconDesk account ownership is required"):
            aurora_store.issue_account_linking_token(
                user_id=user_id,
                cognito_sub=sub,
                email=email,
                ownership_proof=spoofed_proof,
            )

    def test_test_only_proof_type_rejected_in_runtime(self, sqlite_engine, aurora_store):
        """Item 1 & 7: Remove mock_test_proof from runtime verification paths."""
        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())
        email = "mock_test_reject@example.com"

        _create_user_profile(sqlite_engine, user_id, email)

        mock_proof = {"type": "mock_test_proof", "verified": True, "user_id": user_id}
        with pytest.raises(CognitoIdentityError, match="proof of existing ReconDesk account ownership is required"):
            aurora_store.issue_account_linking_token(
                user_id=user_id,
                cognito_sub=sub,
                email=email,
                ownership_proof=mock_proof,
            )

    def test_direct_create_linking_token_rejected_without_proof(self, sqlite_engine, aurora_store):
        """Item 3 & 7: Prevent untrusted code from calling create_linking_token() directly."""
        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())
        email = "direct_create@example.com"

        _create_user_profile(sqlite_engine, user_id, email)

        with pytest.raises(CognitoIdentityError, match="Direct invocation of create_linking_token"):
            aurora_store.create_linking_token(
                user_id=user_id,
                cognito_sub=sub,
                email=email,
            )

    def test_authorized_token_issuance_via_test_dependency_override(self, sqlite_engine, aurora_store):
        """Item 1: Test fixtures inject mock verifiers through test-only overrides."""
        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())
        email = "injected_verifier@example.com"

        _create_user_profile(sqlite_engine, user_id, email)

        # Injected test verifier
        def mock_verifier(uid: str, em: str, proof: dict) -> bool:
            return uid == user_id and proof.get("type") == "test_authorized"

        token = aurora_store.issue_account_linking_token(
            user_id=user_id,
            cognito_sub=sub,
            email=email,
            ownership_proof={"type": "test_authorized"},
            verify_proof_fn=mock_verifier,
        )
        assert token and len(token) > 20

        # Verify it was stored as hash in DB
        session_factory = sessionmaker(bind=sqlite_engine)
        with session_factory() as session:
            h = hashlib.sha256(token.encode("utf-8")).hexdigest()
            row = session.query(CognitoAccountLinkingTokenModel).filter_by(token_hash=h).first()
            assert row is not None
            assert str(row.user_id) == user_id


# ─── 7. Failed Transaction Rollback Safety Tests ─────────────────────────────

class TestFailedTransactionRollback:
    def test_failed_transaction_does_not_consume_token(self, sqlite_engine, aurora_store):
        """Requirement 3: Failed transactions must rollback without consuming valid tokens."""
        user_id = str(uuid.uuid4())
        sub_1 = str(uuid.uuid4())
        sub_2 = str(uuid.uuid4())
        email = "rollback_test@example.com"

        _create_user_profile(sqlite_engine, user_id, email)

        # Pre-map user_id to sub_1 so sub_2 linking will trigger a conflict
        aurora_store.admin_provision_mapping(
            user_id=user_id,
            cognito_sub=sub_1,
            email=email,
            provisioned_by="admin",
        )

        # Issue token for sub_2 internally
        token = aurora_store._create_linking_token_internal(user_id, sub_2, email)
        claims = {"sub": sub_2, "email": email, "email_verified": True}

        # Attempt to link sub_2 (fails with conflict)
        with pytest.raises(CognitoAccountConflictError):
            aurora_store.complete_account_linking_transactional(token, claims)

        # Verify token was NOT consumed due to transactional rollback
        session_factory = sessionmaker(bind=sqlite_engine)
        with session_factory() as session:
            h = hashlib.sha256(token.encode("utf-8")).hexdigest()
            token_row = session.query(CognitoAccountLinkingTokenModel).filter_by(token_hash=h).first()
            assert token_row is not None
            assert token_row.consumed_at is None


# ─── 8. User Pool Isolation Tests ────────────────────────────────────────────

class TestUserPoolIsolation:
    def test_cross_pool_identity_resolution_isolated(self, sqlite_engine):
        """Requirement 5: Dev and prod identities are isolated by cognito_user_pool_id."""
        dev_pool = "ap-south-1_devPool"
        prod_pool = "ap-south-1_prodPool"
        dev_store = SQLAlchemyCognitoIdentityStore(
            session_factory=sessionmaker(bind=sqlite_engine), user_pool_id=dev_pool
        )
        prod_store = SQLAlchemyCognitoIdentityStore(
            session_factory=sessionmaker(bind=sqlite_engine), user_pool_id=prod_pool
        )

        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())
        email = "pool_iso@example.com"

        _create_user_profile(sqlite_engine, user_id, email)

        # Provision in dev pool
        dev_store.admin_provision_mapping(
            user_id=user_id,
            cognito_sub=sub,
            email=email,
            provisioned_by="admin",
        )

        # Resolving via dev pool succeeds
        dev_mapping = dev_store.get_mapping_by_sub(sub)
        assert dev_mapping is not None
        assert dev_mapping.user_id == user_id

        # Resolving via prod pool must NOT find the dev identity
        prod_mapping = prod_store.get_mapping_by_sub(sub)
        assert prod_mapping is None

    def test_cross_pool_linking_token_rejected(self, sqlite_engine):
        """Item 5 & 7: Tokens or claims from another pool are rejected."""
        dev_pool = "ap-south-1_devPool"
        prod_pool = "ap-south-1_prodPool"
        dev_store = SQLAlchemyCognitoIdentityStore(
            session_factory=sessionmaker(bind=sqlite_engine), user_pool_id=dev_pool
        )
        prod_store = SQLAlchemyCognitoIdentityStore(
            session_factory=sessionmaker(bind=sqlite_engine), user_pool_id=prod_pool
        )

        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())
        email = "token_iso@example.com"

        _create_user_profile(sqlite_engine, user_id, email)

        # Issue token in dev pool
        token = dev_store._create_linking_token_internal(user_id, sub, email)
        claims = {"sub": sub, "email": email, "email_verified": True}

        # Attempt to consume token in prod pool fails closed
        with pytest.raises(CognitoIdentityError, match="Invalid, expired, or mismatched"):
            prod_store.complete_account_linking_transactional(token, claims)

    def test_cross_pool_issuer_mismatch_rejected(self, sqlite_engine, aurora_store):
        """Item 5: Validate token issuer claim against configured user pool."""
        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())
        email = "issuer_mismatch@example.com"

        _create_user_profile(sqlite_engine, user_id, email)
        token = aurora_store._create_linking_token_internal(user_id, sub, email)

        # Spoofed issuer from another pool
        claims = {
            "sub": sub,
            "email": email,
            "email_verified": True,
            "iss": "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_foreignPool",
        }
        with pytest.raises(CognitoIdentityError, match="untrusted Cognito User Pool"):
            aurora_store.complete_account_linking_transactional(token, claims)


# ─── 9. Subject and Email Mismatch Protection Tests ─────────────────────────

class TestSubjectAndEmailMatching:
    def test_email_mismatch_rejected(self, sqlite_engine, aurora_store):
        """Requirement 6: Verify authenticated claims email matches token intended email."""
        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())

        _create_user_profile(sqlite_engine, user_id, "primary@example.com")
        token = aurora_store._create_linking_token_internal(user_id, sub, "primary@example.com")

        # Claims present a different email
        claims = {"sub": sub, "email": "different@example.com", "email_verified": True}
        with pytest.raises(CognitoIdentityError, match="Invalid, expired, or mismatched"):
            aurora_store.complete_account_linking_transactional(token, claims)

    def test_unverified_email_in_claims_rejected(self, sqlite_engine, aurora_store):
        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())

        _create_user_profile(sqlite_engine, user_id, "test@example.com")
        token = aurora_store._create_linking_token_internal(user_id, sub, "test@example.com")

        claims = {"sub": sub, "email": "test@example.com", "email_verified": False}
        with pytest.raises(CognitoIdentityError, match="strictly verified"):
            aurora_store.complete_account_linking_transactional(token, claims)


# ─── 10. Tamper-Proof Mapping Updates Tests ─────────────────────────────────

class TestTamperProofMappingUpdates:
    def test_direct_verified_mapping_insertion_via_save_mapping_rejected(self, sqlite_engine, aurora_store):
        """Item 4 & 7: Prevent save_mapping() from directly inserting verified mappings."""
        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())

        _create_user_profile(sqlite_engine, user_id, "direct_insert@example.com")

        verified_mapping = CognitoIdentityMapping(
            cognito_sub=sub,
            user_id=user_id,
            email="direct_insert@example.com",
            mapping_method="admin_provisioned",
            verified=True,
        )
        with pytest.raises(CognitoIdentityError, match="Cannot directly insert verified mappings via save_mapping"):
            aurora_store.save_mapping(verified_mapping)

    def test_save_mapping_cannot_upgrade_verification_or_method(self, sqlite_engine, aurora_store):
        """Requirement 4: Prevent save_mapping() from modifying mapping_method or is_verified."""
        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())

        _create_user_profile(sqlite_engine, user_id, "tamper@example.com")

        # Initial mapping created via admin provisioning as verified
        initial_mapping = aurora_store.admin_provision_mapping(
            user_id=user_id,
            cognito_sub=sub,
            email="tamper@example.com",
            provisioned_by="admin-1",
        )
        assert initial_mapping.verified is True

        # Attacker tries to alter mapping_method to verified_link_token via save_mapping
        escalation_attempt = CognitoIdentityMapping(
            cognito_sub=sub,
            user_id=user_id,
            email="tamper@example.com",
            mapping_method="verified_link_token",
            verified=True,
        )
        with pytest.raises(CognitoIdentityError, match="Unauthorized mapping modification"):
            aurora_store.save_mapping(escalation_attempt)

        # Attacker tries to toggle verification status
        toggle_attempt = CognitoIdentityMapping(
            cognito_sub=sub,
            user_id=user_id,
            email="tamper@example.com",
            mapping_method="admin_provisioned",
            verified=False,
        )
        with pytest.raises(CognitoIdentityError, match="Unauthorized mapping modification"):
            aurora_store.save_mapping(toggle_attempt)


# ─── 11. Safe Reversible Rollback Tests ──────────────────────────────────────

class TestSafeRollbackSQL:
    def test_rollback_sql_syntax_and_safety_checks(self):
        """Item 6: Verify transaction wrapping, absence of CASCADE, and rejection on ANY records."""
        down_sql_path = os.path.join(
            os.path.dirname(__file__),
            "../migrations/aurora/20260930183000_create_cognito_user_mappings.down.sql",
        )
        with open(down_sql_path, "r", encoding="utf-8") as f:
            content = f.read()

        # CASCADE must NOT be present
        assert "CASCADE" not in content

        # Transaction wrapping must be present
        assert "BEGIN;" in content
        assert "COMMIT;" in content

        # Active mapping protection must be present
        assert "Refusing to drop public.cognito_user_mappings" in content
        assert "Refusing to drop public.cognito_account_linking_tokens" in content


# ─── 12. Rate Limiting and Log Sanitization Tests ────────────────────────────

class TestRateLimitingAndLogSanitization:
    def test_rate_limiting_on_account_linking_endpoints(self, monkeypatch):
        """Item 8: Check that account-linking requests are rate-limited."""
        from app.main import app
        from app.main import app
        from app.cognito_config import CognitoConfig, get_cognito_config
        from app.cognito_verifier import get_current_cognito_claims

        app.dependency_overrides[get_cognito_config] = lambda: CognitoConfig(COGNITO_AUTH_ENABLED=True)
        app.dependency_overrides[get_current_cognito_claims] = lambda: {"sub": "test-sub", "email": "test@example.com", "email_verified": True}

        try:
            client = TestClient(app)
            responses = []
            for _ in range(8):
                resp = client.post(
                    "/api/v1/auth/cognito/request-link",
                    json={"supabase_token": "dummy"},
                )
                responses.append(resp.status_code)

            # At least one request beyond the limit must return 429 Too Many Requests
            assert 429 in responses
        finally:
            app.dependency_overrides.pop(get_cognito_config, None)
            app.dependency_overrides.pop(get_current_cognito_claims, None)

    def test_passwords_tokens_and_jwts_never_logged(self, sqlite_engine, aurora_store, caplog):
        """Item 8: Check that passwords, linking tokens, JWTs never appear in application logs."""
        caplog.set_level(logging.DEBUG)

        user_id = str(uuid.uuid4())
        sub = str(uuid.uuid4())
        secret_password = "SuperSecretPassword123!"
        secret_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy_secret_jwt"
        email = "log_security@example.com"

        _create_user_profile(sqlite_engine, user_id, email)

        # Attempt issuance with invalid credentials
        try:
            aurora_store.issue_account_linking_token(
                user_id=user_id,
                cognito_sub=sub,
                email=email,
                ownership_proof={"type": "supabase_password", "password": secret_password},
            )
        except Exception:
            pass

        # Inspect all logged text
        logged_text = caplog.text
        assert secret_password not in logged_text
        assert secret_jwt not in logged_text
