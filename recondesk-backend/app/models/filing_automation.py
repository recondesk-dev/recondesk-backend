"""SQLAlchemy declarative models for Batch 3C: Government Portal Filing Automation & Bulk Return Processing.

Tables:
1. filing_sessions
2. filing_runs
3. filing_batches
4. filing_batch_items
5. sales_register_run
6. sr_records
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.models.schema_base import Base, GUID


class FilingSession(Base):
    """GSTN portal taxpayer session holding temporary access token (~6hr)."""

    __tablename__ = "filing_sessions"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    firm_id = Column(
        GUID,
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_gstin_id = Column(
        GUID,
        ForeignKey("client_gstins.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    gstin = Column(Text, nullable=False)
    username = Column(Text, nullable=False, default="")
    session_token = Column(Text, nullable=False)
    token_expires_at = Column(DateTime(timezone=True), nullable=False)
    session_expires_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(Text, nullable=False, default="active")
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
    logged_out_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_filing_sessions_firm_gstin", "firm_id", "gstin"),
        Index(
            "idx_filing_sessions_firm_active",
            "firm_id",
            "status",
            "token_expires_at",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'expired', 'logged_out')",
            name="filing_sessions_status_chk",
        ),
    )

    def to_dict(self, redact_token: bool = True) -> dict[str, Any]:
        """Serialize model instance.

        Sensitive token is masked by default unless explicit redact_token=False.
        """
        token_repr = (
            "***REDACTED***"
            if redact_token and self.session_token
            else self.session_token
        )
        return {
            "id": str(self.id),
            "firm_id": str(self.firm_id),
            "client_gstin_id": str(self.client_gstin_id) if self.client_gstin_id else None,
            "gstin": self.gstin,
            "username": self.username,
            "session_token": token_repr,
            "token_expires_at": self.token_expires_at.isoformat() if self.token_expires_at else None,
            "session_expires_at": self.session_expires_at.isoformat() if self.session_expires_at else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "logged_out_at": self.logged_out_at.isoformat() if self.logged_out_at else None,
        }


class FilingRun(Base):
    """Individual return Save, Offset, or File attempt for a period."""

    __tablename__ = "filing_runs"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    firm_id = Column(
        GUID,
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_gstin_id = Column(
        GUID,
        ForeignKey("client_gstins.id", ondelete="SET NULL"),
        nullable=True,
    )
    filing_session_id = Column(
        GUID,
        ForeignKey("filing_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    gstin = Column(Text, nullable=False)
    return_type = Column(Text, nullable=False)
    period = Column(String(7), nullable=False)
    status = Column(Text, nullable=False, default="draft")
    reference_id = Column(Text, nullable=True)
    ack_number = Column(Text, nullable=True)
    arn = Column(Text, nullable=True)
    filing_method = Column(Text, nullable=True)
    filed_at = Column(DateTime(timezone=True), nullable=True)
    save_payload = Column(JSONB().with_variant(sa.JSON, "sqlite"), nullable=True)
    raw_response = Column(JSONB().with_variant(sa.JSON, "sqlite"), nullable=True)
    error_code = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    offset_payload = Column(JSONB().with_variant(sa.JSON, "sqlite"), nullable=True)
    offset_completed_at = Column(DateTime(timezone=True), nullable=True)
    tx_pmt_snapshot = Column(JSONB().with_variant(sa.JSON, "sqlite"), nullable=True)
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

    __table_args__ = (
        Index("idx_filing_runs_firm_period", "firm_id", "return_type", "period"),
        Index("idx_filing_runs_gstin_period", "gstin", "return_type", "period"),
        Index("idx_filing_runs_gstr3b_offset_gate", "gstin", "period", "status"),
        sa.CheckConstraint(
            "return_type IN ('gstr-1', 'gstr-1a', 'gstr-3b', 'gstr-9', 'other')",
            name="filing_runs_return_type_chk",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'save_pending', 'saved', 'save_failed', 'offset_pending', 'offset_complete', 'offset_failed', 'proceeded', 'evc_pending', 'filed', 'failed')",
            name="filing_runs_status_chk",
        ),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "firm_id": str(self.firm_id),
            "client_gstin_id": str(self.client_gstin_id) if self.client_gstin_id else None,
            "filing_session_id": str(self.filing_session_id) if self.filing_session_id else None,
            "gstin": self.gstin,
            "return_type": self.return_type,
            "period": self.period,
            "status": self.status,
            "reference_id": self.reference_id,
            "ack_number": self.ack_number,
            "arn": self.arn,
            "filing_method": self.filing_method,
            "filed_at": self.filed_at.isoformat() if self.filed_at else None,
            "save_payload": self.save_payload,
            "raw_response": self.raw_response,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "offset_payload": self.offset_payload,
            "offset_completed_at": self.offset_completed_at.isoformat() if self.offset_completed_at else None,
            "tx_pmt_snapshot": self.tx_pmt_snapshot,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class FilingBatch(Base):
    """Header record for multi-GSTIN bulk return processing jobs."""

    __tablename__ = "filing_batches"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    firm_id = Column(
        GUID,
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by = Column(
        GUID,
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    return_type = Column(Text, nullable=False, default="gstr-1")
    period = Column(String(7), nullable=False)
    status = Column(Text, nullable=False, default="pending")
    total_count = Column(Integer, nullable=False, default=0)
    saved_count = Column(Integer, nullable=False, default=0)
    evc_pending_count = Column(Integer, nullable=False, default=0)
    filed_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    needs_review_count = Column(Integer, nullable=False, default=0)
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

    __table_args__ = (
        Index("idx_filing_batches_firm_period", "firm_id", "return_type", "period"),
        Index("idx_filing_batches_status", "status"),
        sa.CheckConstraint("return_type IN ('gstr-1')", name="filing_batches_return_type_chk"),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'partially_completed', 'failed', 'cancelled')",
            name="filing_batches_status_chk",
        ),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "firm_id": str(self.firm_id),
            "created_by": str(self.created_by),
            "return_type": self.return_type,
            "period": self.period,
            "status": self.status,
            "total_count": self.total_count,
            "saved_count": self.saved_count,
            "evc_pending_count": self.evc_pending_count,
            "filed_count": self.filed_count,
            "failed_count": self.failed_count,
            "needs_review_count": self.needs_review_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class FilingBatchItem(Base):
    """Child record for each client GSTIN enrolled in a bulk filing batch."""

    __tablename__ = "filing_batch_items"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    batch_id = Column(
        GUID,
        ForeignKey("filing_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_gstin_id = Column(
        GUID,
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    gstin = Column(Text, nullable=False)
    filing_run_id = Column(
        GUID,
        ForeignKey("filing_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(Text, nullable=False, default="pending")
    error_code = Column(Text, nullable=True)
    error_detail = Column(Text, nullable=True)
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

    __table_args__ = (
        Index("idx_filing_batch_items_batch", "batch_id", "status"),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'saved', 'proceeded', 'needs_review', 'evc_pending', 'failed', 'filed', 'skipped')",
            name="filing_batch_items_status_chk",
        ),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "batch_id": str(self.batch_id),
            "client_gstin_id": str(self.client_gstin_id),
            "gstin": self.gstin,
            "filing_run_id": str(self.filing_run_id) if self.filing_run_id else None,
            "status": self.status,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SalesRegisterRun(Base):
    """Tracks Tally Bridge Sales Register auto-sync import runs."""

    __tablename__ = "sales_register_run"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    client_gstin_id = Column(
        GUID,
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period = Column(String(7), nullable=False)
    file_type = Column(String(50), nullable=False, default="sales_register")
    r2_key = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, default="queued")
    file_hash = Column(String(64), nullable=False, default="")
    retry_count = Column(Integer, nullable=False, default=0)
    total_records = Column(Integer, nullable=False, default=0)
    inserted_records = Column(Integer, nullable=False, default=0)
    failed_records = Column(Integer, nullable=False, default=0)
    sr_records_imported = Column(Integer, nullable=False, default=0)
    progress_percent = Column(Float, nullable=False, default=0.0)
    sanity_report = Column(JSONB().with_variant(sa.JSON, "sqlite"), nullable=True)
    status_message = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("idx_sales_register_run_period", "client_gstin_id", "period"),
        Index("idx_sales_register_run_status", "status"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "client_gstin_id": str(self.client_gstin_id),
            "period": self.period,
            "file_type": self.file_type,
            "r2_key": self.r2_key,
            "status": self.status,
            "file_hash": self.file_hash,
            "retry_count": self.retry_count,
            "total_records": self.total_records,
            "inserted_records": self.inserted_records,
            "failed_records": self.failed_records,
            "sr_records_imported": self.sr_records_imported,
            "progress_percent": self.progress_percent,
            "sanity_report": self.sanity_report,
            "status_message": self.status_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SrRecord(Base):
    """Individual sales register voucher rows imported per sync run."""

    __tablename__ = "sr_records"

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    run_id = Column(
        GUID,
        ForeignKey("sales_register_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_gstin_id = Column(Text, nullable=False, index=True)
    period = Column(String(7), nullable=False)
    record_data = Column(JSONB().with_variant(sa.JSON, "sqlite"), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("idx_sr_records_period", "client_gstin_id", "period"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": str(self.run_id),
            "client_gstin_id": self.client_gstin_id,
            "period": self.period,
            "record_data": self.record_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
