"""SQLAlchemy schema models and DDL definitions for persistent Cognito account mapping.

Phase 2A Target Schema for AWS Aurora PostgreSQL.
Enforces a strict 1:1 bijection between Amazon Cognito 'sub' and ReconDesk 'user_profiles.id'
within an isolated Cognito User Pool.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import declarative_base
from sqlalchemy.types import JSON, TypeDecorator, CHAR

from app.cognito_identity import CognitoIdentityMapping
from app.models.schema_base import Base, GUID  # noqa: F401
from app.models.tenancy import UserProfile

# Maintain backwards compatibility with existing codebase and tests
UserProfileModel = UserProfile


class CognitoUserMappingModel(Base):
    """SQLAlchemy model for public.cognito_user_mappings in AWS Aurora.

    Enforces 1:1 unique constraints on (cognito_user_pool_id, cognito_sub)
    and (cognito_user_pool_id, user_id).
    """

    __tablename__ = "cognito_user_mappings"
    __table_args__ = (
        UniqueConstraint("cognito_user_pool_id", "cognito_sub", name="uq_cognito_pool_sub"),
        UniqueConstraint("cognito_user_pool_id", "user_id", name="uq_cognito_pool_user_id"),
        CheckConstraint(
            "mapping_method IN ('admin_provisioned', 'verified_link_token')",
            name="ck_cognito_user_mappings_method",
        ),
        Index("idx_cognito_user_mappings_email", "email"),
        Index("idx_cognito_user_mappings_pool_sub", "cognito_user_pool_id", "cognito_sub"),
    )

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    cognito_user_pool_id = Column(String(64), nullable=False, default="ap-south-1_uPECX7n1n")
    cognito_sub = Column(String(128), nullable=False)
    user_id = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    email = Column(String(255), nullable=False)
    mapping_method = Column(String(50), nullable=False)
    is_verified = Column(Boolean, nullable=False, default=False)
    provisioned_by = Column(String(128), nullable=True)
    linking_ip = Column(String(64), nullable=True)
    # Explicitly map Python attribute 'metadata_json' to the database column 'metadata'
    # to avoid colliding with SQLAlchemy's reserved 'metadata' attribute on declarative models
    # while preserving the Aurora table column name 'metadata' (JSONB NOT NULL DEFAULT '{}'::jsonb).
    metadata_json = Column(
        "metadata",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_domain(self) -> CognitoIdentityMapping:
        """Convert SQLAlchemy database record to domain dataclass."""
        return CognitoIdentityMapping(
            cognito_sub=self.cognito_sub,
            user_id=str(self.user_id),
            email=self.email,
            mapping_method=self.mapping_method,
            verified=bool(self.is_verified),
            cognito_user_pool_id=self.cognito_user_pool_id,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class CognitoAccountLinkingTokenModel(Base):
    """SQLAlchemy model for public.cognito_account_linking_tokens in AWS Aurora.

    Stores cryptographic SHA-256 hashes of one-time linking tokens.
    Plaintext tokens are NEVER stored in the database.
    """

    __tablename__ = "cognito_account_linking_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_cognito_linking_token_hash"),
        Index("idx_cognito_tokens_lookup", "token_hash"),
        Index("idx_cognito_tokens_user_id", "user_id"),
        Index("idx_cognito_tokens_pool_sub", "cognito_user_pool_id", "cognito_sub"),
    )

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_hash = Column(String(64), nullable=False)
    cognito_user_pool_id = Column(String(64), nullable=False, default="ap-south-1_uPECX7n1n")
    cognito_sub = Column(String(128), nullable=False)
    user_id = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    email = Column(String(255), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    created_ip = Column(String(64), nullable=True)
    consumed_ip = Column(String(64), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
