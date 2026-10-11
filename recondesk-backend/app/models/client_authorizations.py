"""SQLAlchemy models for Phase 3.3 Client Review, Consent and Filing Authorization.

Defines:
- ClientFilingAuthorization: Time-limited, cryptographically hashed access tokens,
  return summaries, and explicit client authorization records.
- ClientAuthorizationAuditTrail: Immutable tenant-scoped audit records of every client review,
  link view, consent authorization, rejection, revocation, and expiration.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from app.models.schema_base import Base, GUID


class ClientFilingAuthorization(Base):
    """Client Filing Authorization Model."""

    __tablename__ = "client_filing_authorizations"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    firm_id = Column(GUID(), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    client_gstin_id = Column(GUID(), ForeignKey("client_gstins.id", ondelete="CASCADE"), nullable=False)
    gstin = Column(String(15), nullable=False)
    period = Column(String(7), nullable=False)
    return_type = Column(String(20), nullable=False)
    status = Column(String(30), default="PENDING", nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    figures_digest = Column(String(64), nullable=False)
    figures_summary = Column(JSONB().with_variant(JSON(), "sqlite"), default=dict, nullable=False)

    signatory_name = Column(String(255), nullable=True)
    signatory_designation = Column(String(100), nullable=True)
    signatory_contact = Column(String(100), nullable=True)
    consent_text_version = Column(String(20), default="v1.0", nullable=False)
    consent_declaration = Column(Text, nullable=True)
    identity_verification_method = Column(String(50), default="self_declaration", nullable=False)
    client_ip = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)

    authorized_at = Column(DateTime(timezone=True), nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revocation_reason = Column(Text, nullable=True)
    revoked_by = Column(GUID(), ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True)
    created_by = Column(GUID(), ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'VIEWED', 'AUTHORIZED', 'REJECTED', 'REVOKED', 'EXPIRED')",
            name="ck_client_auth_status",
        ),
        CheckConstraint(
            "return_type IN ('GSTR-1', 'GSTR-3B', 'GSTR-4', 'GSTR-9', 'GSTR-9C')",
            name="ck_client_auth_return_type",
        ),
        Index("idx_client_auth_lookup", "firm_id", "client_gstin_id", "period", "return_type"),
        Index("idx_client_auth_status", "status"),
        Index("idx_client_auth_expires", "expires_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "firm_id": str(self.firm_id),
            "client_gstin_id": str(self.client_gstin_id),
            "gstin": self.gstin,
            "period": self.period,
            "return_type": self.return_type,
            "status": self.status,
            "figures_digest": self.figures_digest,
            "figures_summary": self.figures_summary or {},
            "signatory_name": self.signatory_name,
            "signatory_designation": self.signatory_designation,
            "signatory_contact": self.signatory_contact,
            "consent_text_version": self.consent_text_version,
            "consent_declaration": self.consent_declaration,
            "identity_verification_method": self.identity_verification_method or "self_declaration",
            "client_ip": self.client_ip,
            "user_agent": self.user_agent,
            "authorized_at": self.authorized_at.isoformat() if self.authorized_at else None,
            "rejected_at": self.rejected_at.isoformat() if self.rejected_at else None,
            "rejection_reason": self.rejection_reason,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "revocation_reason": self.revocation_reason,
            "revoked_by": str(self.revoked_by) if self.revoked_by else None,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ClientAuthorizationAuditTrail(Base):
    """Immutable audit trail for all client review, consent, and authorization events."""

    __tablename__ = "client_authorization_audit_trail"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    authorization_id = Column(GUID(), ForeignKey("client_filing_authorizations.id", ondelete="CASCADE"), nullable=False)
    firm_id = Column(GUID(), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    client_gstin_id = Column(GUID(), ForeignKey("client_gstins.id", ondelete="SET NULL"), nullable=True)
    gstin = Column(String(15), nullable=False)
    period = Column(String(7), nullable=False)
    return_type = Column(String(20), nullable=False)
    action = Column(String(50), nullable=False)
    from_status = Column(String(30), nullable=True)
    to_status = Column(String(30), nullable=False)
    actor_type = Column(String(20), nullable=False)
    actor_id = Column(GUID(), ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True)
    actor_name = Column(String(255), default="", nullable=False)
    figures_digest = Column(String(64), nullable=False)
    client_ip = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    notes = Column(Text, default="", nullable=False)
    metadata_ = Column("metadata", JSONB().with_variant(JSON(), "sqlite"), default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        CheckConstraint("actor_type IN ('ca_user', 'client', 'system')", name="ck_client_audit_actor_type"),
        Index("idx_client_auth_audit_auth_id", "authorization_id"),
        Index("idx_client_auth_audit_firm", "firm_id", "created_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "authorization_id": str(self.authorization_id),
            "firm_id": str(self.firm_id),
            "client_gstin_id": str(self.client_gstin_id) if self.client_gstin_id else None,
            "gstin": self.gstin,
            "period": self.period,
            "return_type": self.return_type,
            "action": self.action,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "actor_type": self.actor_type,
            "actor_id": str(self.actor_id) if self.actor_id else None,
            "actor_name": self.actor_name,
            "figures_digest": self.figures_digest,
            "client_ip": self.client_ip,
            "user_agent": self.user_agent,
            "notes": self.notes,
            "metadata": self.metadata_ or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
