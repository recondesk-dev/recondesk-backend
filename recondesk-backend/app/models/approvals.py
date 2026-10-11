"""SQLAlchemy models for Phase 3.2 Maker-Checker Return Filing Approvals.

Defines:
- ReturnFilingApproval: Durable return approval state machine and cryptographic figure digests.
- ReturnApprovalAuditTrail: Immutable tenant-scoped audit records of every maker-checker transition.
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


class ReturnFilingApproval(Base):
    """Maker-Checker Return Filing Approval Model."""

    __tablename__ = "return_filing_approvals"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    firm_id = Column(GUID(), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    client_gstin_id = Column(GUID(), ForeignKey("client_gstins.id", ondelete="CASCADE"), nullable=False)
    gstin = Column(String(15), nullable=False)
    period = Column(String(7), nullable=False)
    return_type = Column(String(20), nullable=False)
    status = Column(String(30), default="DRAFT", nullable=False)
    figures_digest = Column(String(64), default="", nullable=False)
    validation_digest = Column(String(64), default="", nullable=False)
    figures_summary = Column(JSONB().with_variant(JSON(), "sqlite"), default=dict, nullable=False)
    
    preparer_id = Column(GUID(), ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True)
    preparer_name = Column(String(255), default="", nullable=False)
    preparer_role = Column(String(50), default="", nullable=False)
    prepared_at = Column(DateTime(timezone=True), nullable=True)
    submission_notes = Column(Text, default="", nullable=False)

    approver_id = Column(GUID(), ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True)
    approver_name = Column(String(255), default="", nullable=False)
    approver_role = Column(String(50), default="", nullable=False)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approval_notes = Column(Text, default="", nullable=False)

    rejected_by = Column(GUID(), ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True)
    rejected_by_name = Column(String(255), default="", nullable=False)
    rejected_by_role = Column(String(50), default="", nullable=False)
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, default="", nullable=False)

    filing_run_id = Column(GUID(), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint("firm_id", "client_gstin_id", "period", "return_type", name="uq_return_filing_approvals"),
        CheckConstraint("period ~ '^[0-9]{4}-[0-9]{2}$'", name="ck_return_filing_approvals_period"),
        CheckConstraint(
            "status IN ('DRAFT', 'PREPARED', 'UNDER_REVIEW', 'APPROVED', 'REJECTED', 'SAVED', 'OFFSET_COMPLETE', 'FILED')",
            name="ck_return_filing_approvals_status",
        ),
        Index("idx_return_approvals_lookup", "firm_id", "client_gstin_id", "period", "return_type"),
        Index("idx_return_approvals_status", "status"),
        Index("idx_return_approvals_digest", "figures_digest"),
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
            "validation_digest": self.validation_digest,
            "figures_summary": self.figures_summary or {},
            "preparer_id": str(self.preparer_id) if self.preparer_id else None,
            "preparer_name": self.preparer_name,
            "preparer_role": self.preparer_role,
            "prepared_at": self.prepared_at.isoformat() if self.prepared_at else None,
            "submission_notes": self.submission_notes,
            "approver_id": str(self.approver_id) if self.approver_id else None,
            "approver_name": self.approver_name,
            "approver_role": self.approver_role,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "approval_notes": self.approval_notes,
            "rejected_by": str(self.rejected_by) if self.rejected_by else None,
            "rejected_by_name": self.rejected_by_name,
            "rejected_by_role": self.rejected_by_role,
            "rejected_at": self.rejected_at.isoformat() if self.rejected_at else None,
            "rejection_reason": self.rejection_reason,
            "filing_run_id": str(self.filing_run_id) if self.filing_run_id else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ReturnApprovalAuditTrail(Base):
    """Immutable Audit Trail for Return Filing Approvals."""

    __tablename__ = "return_approval_audit_trail"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    approval_id = Column(GUID(), ForeignKey("return_filing_approvals.id", ondelete="CASCADE"), nullable=False)
    firm_id = Column(GUID(), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    client_gstin_id = Column(GUID(), nullable=True)
    gstin = Column(String(15), nullable=False)
    period = Column(String(7), nullable=False)
    return_type = Column(String(20), nullable=False)
    action = Column(String(50), nullable=False)
    from_status = Column(String(30), nullable=True)
    to_status = Column(String(30), nullable=False)
    actor_id = Column(GUID(), ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True)
    actor_name = Column(String(255), default="", nullable=False)
    actor_role = Column(String(50), default="", nullable=False)
    figures_digest = Column(String(64), default="", nullable=False)
    notes = Column(Text, default="", nullable=False)
    rejection_reason = Column(Text, default="", nullable=False)
    metadata_ = Column("metadata", JSONB().with_variant(JSON(), "sqlite"), default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("idx_return_audit_approval", "approval_id"),
        Index("idx_return_audit_firm", "firm_id", "created_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "approval_id": str(self.approval_id),
            "firm_id": str(self.firm_id),
            "client_gstin_id": str(self.client_gstin_id) if self.client_gstin_id else None,
            "gstin": self.gstin,
            "period": self.period,
            "return_type": self.return_type,
            "action": self.action,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "actor_id": str(self.actor_id) if self.actor_id else None,
            "actor_name": self.actor_name,
            "actor_role": self.actor_role,
            "figures_digest": self.figures_digest,
            "notes": self.notes,
            "rejection_reason": self.rejection_reason,
            "metadata": self.metadata_ or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
