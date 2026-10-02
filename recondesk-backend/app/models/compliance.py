"""SQLAlchemy declarative models for Batch 2A Compliance and Resolution Tracking.

Defines:
- MismatchNote: User notes and manual review status on discrepancy records.
- ReconciliationExceptionDisposition: Statutory dispositions affecting Table 4 outcomes.
- InvoiceTracking: Multi-period cross-run tracking of unmatched invoices and carry-forward.
- Rule37Action: 180-day non-payment dispositions, TDS deductions, and settlements.
- Rule37Resolution: Resolution tracking for Rule 37 invoice items.
- Rule37AlertDedup: Alert tier deduplication preventing repeated Rule 37 warning notifications.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.models.schema_base import Base, GUID


class MismatchNote(Base):
    """User notes and review disposition comments attached to discrepancy records."""

    __tablename__ = "mismatch_notes"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    record_id = Column(GUID(), nullable=False)
    record_type = Column(String, nullable=False)
    run_id = Column(
        GUID(),
        ForeignKey("reconciliation_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(GUID(), nullable=False)
    note = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    status = Column(String, default="pending", nullable=True)

    __table_args__ = (
        CheckConstraint(
            "record_type IN ('gstr', 'pr')",
            name="mismatch_notes_record_type_check",
        ),
        Index("idx_mismatch_notes_record_id", "record_id"),
        Index("idx_mismatch_notes_run_id", "run_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "record_id": str(self.record_id),
            "record_type": self.record_type,
            "run_id": str(self.run_id),
            "user_id": str(self.user_id),
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "status": self.status,
        }


class ReconciliationExceptionDisposition(Base):
    """Statutory dispositions applied to reconciliation discrepancies impacting Table 4 calculations."""

    __tablename__ = "reconciliation_exception_dispositions"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        GUID(),
        ForeignKey("reconciliation_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    record_id = Column(Text, nullable=False)
    exception_type = Column(String(50), nullable=False)
    disposition = Column(String(50), nullable=False)
    eligibility_effect = Column(String(30), nullable=False)
    table4_effect = Column(String(30), nullable=False)
    reason = Column(Text, nullable=False)
    reference_doc = Column(String(100), nullable=True)
    statutory_reference = Column(String(100), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    created_by = Column(GUID(), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "record_id",
            "exception_type",
            name="uq_exception_disposition",
        ),
        Index("idx_exception_disp_run_id", "run_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "run_id": str(self.run_id),
            "record_id": self.record_id,
            "exception_type": self.exception_type,
            "disposition": self.disposition,
            "eligibility_effect": self.eligibility_effect,
            "table4_effect": self.table4_effect,
            "reason": self.reason,
            "reference_doc": self.reference_doc,
            "statutory_reference": self.statutory_reference,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "created_by": str(self.created_by) if self.created_by else None,
        }


class InvoiceTracking(Base):
    """Multi-period cross-run tracking of unmatched invoices to detect chronic non-compliance."""

    __tablename__ = "invoice_tracking"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    client_gstin_id = Column(
        GUID(),
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
    )
    invoice_number = Column(Text, nullable=False)
    supplier_gstin = Column(Text, nullable=False)
    taxable_amount = Column(BigInteger, nullable=False)
    first_seen_run_id = Column(
        GUID(),
        ForeignKey("reconciliation_run.id"),
        nullable=False,
    )
    last_seen_run_id = Column(
        GUID(),
        ForeignKey("reconciliation_run.id"),
        nullable=False,
    )
    consecutive_unmatched_runs = Column(Integer, default=1, nullable=False)
    last_match_status = Column(Text, nullable=False)
    is_resolved = Column(Boolean, default=False, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "client_gstin_id",
            "invoice_number",
            "supplier_gstin",
            name="idx_invoice_tracking_unique",
        ),
        Index("idx_invoice_tracking_client", "client_gstin_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "client_gstin_id": str(self.client_gstin_id),
            "invoice_number": self.invoice_number,
            "supplier_gstin": self.supplier_gstin,
            "taxable_amount": self.taxable_amount,
            "first_seen_run_id": str(self.first_seen_run_id),
            "last_seen_run_id": str(self.last_seen_run_id),
            "consecutive_unmatched_runs": self.consecutive_unmatched_runs,
            "last_match_status": self.last_match_status,
            "is_resolved": self.is_resolved,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Rule37Action(Base):
    """180-day non-payment dispositions, TDS deductions, payment settlements."""

    __tablename__ = "rule37_actions"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    run_id = Column(GUID(), nullable=False)
    record_hash = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=True,
    )
    user_id = Column(GUID(), nullable=True)
    tds_deducted = Column(Numeric(15, 2), default=0, nullable=False)
    tds_confirmed = Column(Boolean, default=False, nullable=False)
    total_settled = Column(Numeric(15, 2), nullable=True)
    amount_paid = Column(Numeric(15, 2), nullable=True)
    remaining_unpaid_amount = Column(Numeric(15, 2), nullable=True)
    payment_coverage = Column(Text, nullable=True)
    source = Column(Text, nullable=True)
    settled_date = Column(Date, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "record_hash",
            name="rule37_actions_run_id_record_hash_key",
        ),
        Index("idx_rule37_actions_run_id", "run_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "run_id": str(self.run_id),
            "record_hash": self.record_hash,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "user_id": str(self.user_id) if self.user_id else None,
            "tds_deducted": float(self.tds_deducted) if self.tds_deducted is not None else 0.0,
            "tds_confirmed": self.tds_confirmed,
            "total_settled": float(self.total_settled) if self.total_settled is not None else None,
            "amount_paid": float(self.amount_paid) if self.amount_paid is not None else None,
            "remaining_unpaid_amount": (
                float(self.remaining_unpaid_amount)
                if self.remaining_unpaid_amount is not None
                else None
            ),
            "payment_coverage": self.payment_coverage,
            "source": self.source,
            "settled_date": self.settled_date.isoformat() if self.settled_date else None,
        }


class Rule37Resolution(Base):
    """Resolution tracking for Rule 37 action items."""

    __tablename__ = "rule37_resolutions"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        GUID(),
        ForeignKey("reconciliation_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    invoice_result_id = Column(Text, nullable=False)
    resolved_by = Column(GUID(), nullable=False)
    resolved_at = Column(
        DateTime(timezone=False),
        default=datetime.now,
        nullable=True,
    )
    resolution_note = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_rule37_resolutions_run_id", "run_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "run_id": str(self.run_id),
            "invoice_result_id": self.invoice_result_id,
            "resolved_by": str(self.resolved_by),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolution_note": self.resolution_note,
        }


class Rule37AlertDedup(Base):
    """Alert tier deduplication preventing repeated 180-day warning alerts."""

    __tablename__ = "rule37_alert_dedup"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    firm_owner_id = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_gstin_id = Column(
        GUID(),
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
    )
    invoice_key = Column(Text, nullable=False)
    last_alert_tier = Column(String, nullable=False)
    last_sent_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "client_gstin_id",
            "invoice_key",
            name="rule37_alert_dedup_client_invoice_unique",
        ),
        CheckConstraint(
            "last_alert_tier IN ('WARNING_60_DAYS', 'WARNING_30_DAYS', 'OVERDUE_UNPAID')",
            name="rule37_alert_dedup_tier_check",
        ),
        Index("idx_rule37_alert_dedup_firm_owner", "firm_owner_id"),
        Index("idx_rule37_alert_dedup_last_sent", "last_sent_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "firm_owner_id": str(self.firm_owner_id),
            "client_gstin_id": str(self.client_gstin_id),
            "invoice_key": self.invoice_key,
            "last_alert_tier": self.last_alert_tier,
            "last_sent_at": self.last_sent_at.isoformat() if self.last_sent_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# Convenience Aliases
AuroraMismatchNote = MismatchNote
AuroraReconciliationExceptionDisposition = ReconciliationExceptionDisposition
AuroraInvoiceTracking = InvoiceTracking
AuroraRule37Action = Rule37Action
AuroraRule37Resolution = Rule37Resolution
AuroraRule37AlertDedup = Rule37AlertDedup
