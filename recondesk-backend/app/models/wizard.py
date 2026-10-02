"""SQLAlchemy declarative models for the Reconciliation Ingestion & Wizard pipeline.

Defines:
- ClientImportMapping: Saved PR column -> standard field mappings per client GSTIN.
- ReconciliationImportRun: Multi-step GSTR-2B + PR import wizard state.
- ReconciliationImportRunAuditLog: Event log / audit trail for import wizard transitions.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON

from app.models.schema_base import Base, GUID


class ClientImportMapping(Base):
    """Saved PR column -> standard field mappings per client GSTIN."""

    __tablename__ = "client_import_mappings"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    client_gstin_id = Column(
        GUID(),
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_column_name = Column(String, nullable=False)
    target_field = Column(String, nullable=False)
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
            "target_field",
            name="client_import_mappings_client_target_unique",
        ),
        Index("client_import_mappings_client_gstin_id_idx", "client_gstin_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize into dictionary compatible with Supabase PostgREST shape."""
        return {
            "id": str(self.id),
            "client_gstin_id": str(self.client_gstin_id),
            "source_column_name": self.source_column_name,
            "target_field": self.target_field,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ReconciliationImportRun(Base):
    """Multi-step GSTR-2B + PR import wizard execution and status state."""

    __tablename__ = "reconciliation_import_runs"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    client_id = Column(
        GUID(),
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
    )
    firm_owner_id = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    period = Column(Date, nullable=False)
    status = Column(String, default="draft", nullable=False)
    current_step = Column(Integer, default=1, nullable=False)
    gstr2b_r2_key = Column(String, nullable=True)
    gstr2b_file_name = Column(String, nullable=True)
    gstr2b_file_size = Column(Integer, nullable=True)
    gstr2b_file_hash = Column(String, nullable=True)
    gstr2b_uploaded_at = Column(DateTime(timezone=True), nullable=True)
    gstr2b_record_count = Column(Integer, default=0, nullable=True)
    sanity_check_results = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    pr_r2_key = Column(String, nullable=True)
    pr_file_name = Column(String, nullable=True)
    pr_file_size = Column(Integer, nullable=True)
    pr_file_hash = Column(String, nullable=True)
    pr_uploaded_at = Column(DateTime(timezone=True), nullable=True)
    pr_record_count = Column(Integer, default=0, nullable=True)
    column_mapping = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    # created_by is a bare UUID without an FK constraint to user_profiles
    # because historical Supabase records contain non-user UUIDs.
    created_by = Column(GUID(), nullable=False)
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
    progress_pct = Column(Integer, default=0, nullable=False)
    status_message = Column(String, nullable=True)
    error_detail = Column(String, nullable=True)
    pr_column_headers = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    gstr2b_deleted_at = Column(DateTime(timezone=True), nullable=True)
    pr_deleted_at = Column(DateTime(timezone=True), nullable=True)
    itc_claimed_period = Column(Date, nullable=True)
    run_summary = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )

    __table_args__ = (
        Index("reconciliation_import_runs_client_id_idx", "client_id"),
    )

    audit_logs = relationship(
        "ReconciliationImportRunAuditLog",
        back_populates="run",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize into dictionary compatible with Supabase PostgREST shape."""
        return {
            "id": str(self.id),
            "client_id": str(self.client_id),
            "firm_owner_id": str(self.firm_owner_id) if self.firm_owner_id else None,
            "period": self.period.isoformat() if self.period else None,
            "status": self.status,
            "current_step": self.current_step,
            "gstr2b_r2_key": self.gstr2b_r2_key,
            "gstr2b_file_name": self.gstr2b_file_name,
            "gstr2b_file_size": self.gstr2b_file_size,
            "gstr2b_file_hash": self.gstr2b_file_hash,
            "gstr2b_uploaded_at": self.gstr2b_uploaded_at.isoformat() if self.gstr2b_uploaded_at else None,
            "gstr2b_record_count": self.gstr2b_record_count,
            "sanity_check_results": self.sanity_check_results,
            "pr_r2_key": self.pr_r2_key,
            "pr_file_name": self.pr_file_name,
            "pr_file_size": self.pr_file_size,
            "pr_file_hash": self.pr_file_hash,
            "pr_uploaded_at": self.pr_uploaded_at.isoformat() if self.pr_uploaded_at else None,
            "pr_record_count": self.pr_record_count,
            "column_mapping": self.column_mapping,
            "created_by": str(self.created_by),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "progress_pct": self.progress_pct,
            "status_message": self.status_message,
            "error_detail": self.error_detail,
            "pr_column_headers": self.pr_column_headers,
            "gstr2b_deleted_at": self.gstr2b_deleted_at.isoformat() if self.gstr2b_deleted_at else None,
            "pr_deleted_at": self.pr_deleted_at.isoformat() if self.pr_deleted_at else None,
            "itc_claimed_period": self.itc_claimed_period.isoformat() if self.itc_claimed_period else None,
            "run_summary": self.run_summary,
        }


class ReconciliationImportRunAuditLog(Base):
    """Audit trail for import wizard events and transitions."""

    __tablename__ = "reconciliation_import_run_audit_log"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        GUID(),
        ForeignKey("reconciliation_import_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(GUID(), nullable=False)
    event = Column(String, nullable=False)
    detail = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("reconciliation_import_run_audit_log_run_id_idx", "run_id"),
    )

    run = relationship("ReconciliationImportRun", back_populates="audit_logs")

    def to_dict(self) -> dict[str, Any]:
        """Serialize into dictionary compatible with Supabase PostgREST shape."""
        return {
            "id": str(self.id),
            "run_id": str(self.run_id),
            "user_id": str(self.user_id),
            "event": self.event,
            "detail": self.detail,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
