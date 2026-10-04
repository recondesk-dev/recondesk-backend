"""SQLAlchemy declarative models for Batch 4C: Client Portal, Communication, User Preferences & Audit Logs.

Tables:
1. notification_preferences
2. upload_requests
3. uploaded_files
4. communication_logs
5. audit_logs
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.models.schema_base import Base, GUID


class NotificationPreference(Base):
    """Per-user email notification toggles (run_completed, runs_expiring_soon, payment_receipts, rule37_alerts)."""

    __tablename__ = "notification_preferences"

    user_id = Column(
        GUID,
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    run_completed = Column(Boolean, nullable=False, default=True)
    runs_expiring_soon = Column(Boolean, nullable=False, default=True)
    payment_receipts = Column(Boolean, nullable=False, default=True)
    rule37_alerts = Column(Boolean, nullable=False, default=True)
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": str(self.user_id),
            "run_completed": bool(self.run_completed),
            "runs_expiring_soon": bool(self.runs_expiring_soon),
            "payment_receipts": bool(self.payment_receipts),
            "rule37_alerts": bool(self.rule37_alerts),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class UploadRequest(Base):
    """Client document upload request links with token authentication and expiration."""

    __tablename__ = "upload_requests"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    client_id = Column(
        GUID,
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id = Column(GUID, nullable=False)
    token = Column(Text, nullable=False, unique=True, index=True)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_by_user_id = Column(
        GUID,
        ForeignKey("user_profiles.id"),
        nullable=False,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("idx_upload_requests_client_org", "client_id", "organization_id"),
    )

    files = relationship(
        "UploadedFile",
        back_populates="upload_request",
        cascade="all, delete-orphan",
        order_by="UploadedFile.uploaded_at.desc()",
    )

    def to_dict(self, mask_token: bool = False) -> dict[str, Any]:
        token_val = str(self.token) if self.token else ""
        if mask_token and token_val:
            token_val = f"{token_val[:4]}...***REDACTED***"
        return {
            "id": str(self.id),
            "client_id": str(self.client_id),
            "organization_id": str(self.organization_id),
            "token": token_val,
            "title": self.title,
            "description": self.description,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_by_user_id": str(self.created_by_user_id),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class UploadedFile(Base):
    """Files uploaded by clients against a specific upload request."""

    __tablename__ = "uploaded_files"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    upload_request_id = Column(
        GUID,
        ForeignKey("upload_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename = Column(Text, nullable=False)
    file_size = Column(BigInteger, nullable=False)
    mime_type = Column(Text, nullable=False)
    public_url = Column(Text, nullable=False)
    uploaded_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    upload_request = relationship("UploadRequest", back_populates="files")

    def to_dict(self, mask_url: bool = False) -> dict[str, Any]:
        url_val = str(self.public_url) if self.public_url else ""
        if mask_url and url_val:
            url_val = "***REDACTED_URL***"
        return {
            "id": str(self.id),
            "upload_request_id": str(self.upload_request_id),
            "filename": self.filename,
            "file_size": int(self.file_size),
            "mime_type": self.mime_type,
            "public_url": url_val,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
        }


class CommunicationLog(Base):
    """Log of client communications, notices, and upload link dispatches."""

    __tablename__ = "communication_logs"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    client_id = Column(
        GUID,
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id = Column(GUID, nullable=False)
    template_type = Column(Text, nullable=False)
    message_content = Column(Text, nullable=False)
    sent_via = Column(Text, nullable=False)
    sent_by_user_id = Column(
        GUID,
        ForeignKey("user_profiles.id"),
        nullable=False,
        index=True,
    )
    notes = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("idx_communication_logs_client_org", "client_id", "organization_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "client_id": str(self.client_id),
            "organization_id": str(self.organization_id),
            "template_type": self.template_type,
            "message_content": self.message_content,
            "sent_via": self.sent_via,
            "sent_by_user_id": str(self.sent_by_user_id),
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AuditLog(Base):
    """Insert-only workspace audit trail. Scoped by firm_id (workspace owner anchor).

    Notice: user_id is an unconstrained UUID without FK constraint per Phase 9G-10 audit,
    preserving historical integrity of deleted and system users.
    firm_id references user_profiles(id).
    """

    __tablename__ = "audit_logs"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID, nullable=True, index=True)
    action = Column(Text, nullable=False)
    entity_type = Column(Text, nullable=True)
    entity_id = Column(GUID, nullable=True, index=True)
    metadata_ = Column(
        "metadata",
        JSONB().with_variant(sa.JSON, "sqlite"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    ip_address = Column(Text, nullable=True)
    correlation_id = Column(GUID, nullable=True)
    firm_id = Column(
        GUID,
        ForeignKey("user_profiles.id"),
        nullable=True,
        index=True,
    )
    user_name = Column(Text, nullable=True)
    role = Column(Text, nullable=True)
    entity_label = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_audit_logs_created_at", created_at.desc()),
        Index("idx_audit_logs_firm_created", "firm_id", created_at.desc()),
        Index("idx_audit_logs_firm_user", "firm_id", "user_id", created_at.desc()),
    )

    def to_dict(self, mask_ip: bool = False) -> dict[str, Any]:
        ip_val = str(self.ip_address) if self.ip_address else None
        if mask_ip and ip_val:
            ip_val = "***REDACTED_IP***"
        return {
            "id": str(self.id),
            "user_id": str(self.user_id) if self.user_id else None,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": str(self.entity_id) if self.entity_id else None,
            "metadata": self.metadata_,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "ip_address": ip_val,
            "correlation_id": str(self.correlation_id) if self.correlation_id else None,
            "firm_id": str(self.firm_id) if self.firm_id else None,
            "user_name": self.user_name,
            "role": self.role,
            "entity_label": self.entity_label,
        }
