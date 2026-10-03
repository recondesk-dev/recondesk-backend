"""SQLAlchemy declarative models for Batch 3A: Return Reconciliation & Audit Overrides.

Defines:
- MultiPeriodReconBatch: Multi-period reconciliation orchestration batch header.
- MultiPeriodReconBatchItem: Individual period reconciliation item within a batch.
- Gstr1ReconciliationRun: GSTR-1 vs Sales Register reconciliation run record.
- Gstr1aPeriodAction: CA accept/reject action on a GSTR-1A amendment per period.
- Gstr2aDeltaResult: GSTR-2A vs GSTR-2B snapshot delta reconciliation result.
- Gstr9AuditOverride: CA manual override for a specific GSTR-9 annual return cell.

All models are source-compatible with the Supabase PostgreSQL schema as verified
from the live PostgREST OpenAPI schema during Phase 9F-0 and 9F-1 audits.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.types import JSON, TypeDecorator, Text as TextType
from sqlalchemy.orm import relationship

from app.models.schema_base import Base, GUID


class _JSONB(TypeDecorator):
    """Platform-independent JSONB type.

    Uses PostgreSQL native JSONB when available; falls back to TEXT-stored JSON
    for SQLite (test / CI environments).
    """

    impl = TextType
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_JSONB())
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        return value  # SQLAlchemy JSON/JSONB handle serialization

    def process_result_value(self, value, dialect):
        return value  # SQLAlchemy JSON/JSONB handle deserialization


class MultiPeriodReconBatch(Base):
    """Multi-period reconciliation orchestration batch header.

    Scoped to a single client GSTIN. Groups multiple period items
    for a single financial year's consolidated reconciliation run.
    """

    __tablename__ = "multi_period_recon_batches"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    client_gstin_id = Column(
        GUID(),
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
    )
    financial_year = Column(String(10), nullable=False)
    status = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    # Nullable: creator may be NULL for programmatic batches
    created_by = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )

    items = relationship(
        "MultiPeriodReconBatchItem",
        back_populates="batch",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    __table_args__ = (
        Index("ix_mpreb_client_gstin_id", "client_gstin_id"),
        Index("ix_mpreb_status", "status"),
        Index("ix_mpreb_financial_year", "financial_year"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "client_gstin_id": str(self.client_gstin_id),
            "financial_year": self.financial_year,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": str(self.created_by) if self.created_by else None,
        }


class MultiPeriodReconBatchItem(Base):
    """Individual reconciliation period item within a multi-period batch.

    FK to reconciliation_run is nullable — item may be queued with no run yet assigned.
    Unique per (batch_id, period) — each period appears exactly once per batch.
    """

    __tablename__ = "multi_period_recon_batch_items"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    batch_id = Column(
        GUID(),
        ForeignKey("multi_period_recon_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    period = Column(String(20), nullable=False)
    status = Column(Text, nullable=False)
    reconciliation_run_id = Column(
        GUID(),
        ForeignKey("reconciliation_run.id", ondelete="SET NULL"),
        nullable=True,
    )
    gstr2b_file_path = Column(Text, nullable=True)
    gstr2b_source = Column(Text, nullable=True)
    pr_file_path = Column(Text, nullable=True)
    pr_source = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    batch = relationship("MultiPeriodReconBatch", back_populates="items")

    __table_args__ = (
        UniqueConstraint("batch_id", "period", name="uq_batch_period"),
        Index("ix_mprebi_batch_id", "batch_id"),
        Index("ix_mprebi_status", "status"),
        Index(
            "ix_mprebi_recon_run",
            "reconciliation_run_id",
            postgresql_where="reconciliation_run_id IS NOT NULL",
        ),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "batch_id": str(self.batch_id),
            "period": self.period,
            "status": self.status,
            "reconciliation_run_id": str(self.reconciliation_run_id) if self.reconciliation_run_id else None,
            "gstr2b_file_path": self.gstr2b_file_path,
            "gstr2b_source": self.gstr2b_source,
            "pr_file_path": self.pr_file_path,
            "pr_source": self.pr_source,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Gstr1ReconciliationRun(Base):
    """GSTR-1 vs Sales Register reconciliation run record.

    Stores full result_payload and optional run_summary as JSONB.
    Parent of Gstr1aPeriodAction records.
    completed_at is NOT NULL in source: preserved exactly.
    created_by is a bare nullable UUID (not FK'd) to avoid Cognito UID mapping breakage.
    """

    __tablename__ = "gstr1_reconciliation_run"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    client_gstin_id = Column(
        GUID(),
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(Text, nullable=False)
    result_payload = Column(_JSONB(), nullable=False, default=dict)
    run_summary = Column(_JSONB(), nullable=True)
    period = Column(String(10), nullable=True)
    gstr1_filed_date = Column(Date, nullable=True)
    gstr3b_filed_date = Column(Date, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    # No FK — preserves source UUID values without cross-referencing Cognito users
    created_by = Column(GUID(), nullable=True)

    period_actions = relationship(
        "Gstr1aPeriodAction",
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    __table_args__ = (
        Index("ix_g1rr_client_gstin_id", "client_gstin_id"),
        Index("ix_g1rr_status", "status"),
        Index(
            "ix_g1rr_period",
            "period",
            postgresql_where="period IS NOT NULL",
        ),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "client_gstin_id": str(self.client_gstin_id),
            "status": self.status,
            "result_payload": self.result_payload,
            "run_summary": self.run_summary,
            "period": self.period,
            "gstr1_filed_date": self.gstr1_filed_date.isoformat() if self.gstr1_filed_date else None,
            "gstr3b_filed_date": self.gstr3b_filed_date.isoformat() if self.gstr3b_filed_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_by": str(self.created_by) if self.created_by else None,
        }


class Gstr1aPeriodAction(Base):
    """CA accept/reject action on GSTR-1A amendment for a specific period.

    user_id is stored as TEXT (not UUID FK) to preserve legacy Supabase auth
    identifier strings that may not map to current user_profiles rows.
    """

    __tablename__ = "gstr1a_period_actions"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        GUID(),
        ForeignKey("gstr1_reconciliation_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    period = Column(String(20), nullable=False)
    status = Column(Text, nullable=False)
    # TEXT not GUID: source stores legacy Supabase auth UIDs as raw string
    user_id = Column(Text, nullable=False)
    note = Column(Text, nullable=True)
    filed_date = Column(Date, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    run = relationship("Gstr1ReconciliationRun", back_populates="period_actions")

    __table_args__ = (
        Index("ix_g1pa_run_id", "run_id"),
        Index("ix_g1pa_period", "period"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "run_id": str(self.run_id),
            "period": self.period,
            "status": self.status,
            "user_id": self.user_id,
            "note": self.note,
            "filed_date": self.filed_date.isoformat() if self.filed_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Gstr2aDeltaResult(Base):
    """GSTR-2A vs GSTR-2B snapshot delta reconciliation result.

    summary and results are JSONB payloads. cutoff_date is nullable.
    Unique per (client_gstin_id, period) enforced at query level
    (no DB UNIQUE to allow multiple re-runs per period — source has no constraint).
    """

    __tablename__ = "gstr2a_delta_results"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    client_gstin_id = Column(
        GUID(),
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
    )
    period = Column(Text, nullable=False)
    reconciled_at = Column(DateTime(timezone=True), nullable=False)
    summary = Column(_JSONB(), nullable=False, default=dict)
    results = Column(_JSONB(), nullable=False, default=list)
    cutoff_date = Column(Date, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_g2dr_client_gstin_id", "client_gstin_id"),
        Index("ix_g2dr_period", "period"),
        Index("ix_g2dr_client_period", "client_gstin_id", "period"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "client_gstin_id": str(self.client_gstin_id),
            "period": self.period,
            "reconciled_at": self.reconciled_at.isoformat() if self.reconciled_at else None,
            "summary": self.summary,
            "results": self.results,
            "cutoff_date": self.cutoff_date.isoformat() if self.cutoff_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Gstr9AuditOverride(Base):
    """CA manual override for a specific GSTR-9 annual return cell.

    Unique per (client_gstin_id, financial_year, table_key, cell_key).
    system_value and override_value are NUMERIC(15,2) — large values supported
    (confirmed from sample: override_value=384300387.06 exists in production).
    updated_by is a nullable UUID with no FK to avoid Cognito UID mapping issues.
    """

    __tablename__ = "gstr9_audit_overrides"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    client_gstin_id = Column(
        GUID(),
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
    )
    financial_year = Column(Text, nullable=False)
    table_key = Column(Text, nullable=False)
    cell_key = Column(Text, nullable=False)
    system_value = Column(Numeric(15, 2), nullable=True, default=0)
    override_value = Column(Numeric(15, 2), nullable=False)
    notes = Column(Text, nullable=True)
    # No FK — preserves source UUID values without Cognito cross-reference
    updated_by = Column(GUID(), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "client_gstin_id", "financial_year", "table_key", "cell_key",
            name="uq_gstr9_override_cell",
        ),
        Index("ix_g9ao_client_gstin_id", "client_gstin_id"),
        Index("ix_g9ao_client_fy", "client_gstin_id", "financial_year"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "client_gstin_id": str(self.client_gstin_id),
            "financial_year": self.financial_year,
            "table_key": self.table_key,
            "cell_key": self.cell_key,
            "system_value": float(self.system_value) if self.system_value is not None else None,
            "override_value": float(self.override_value),
            "notes": self.notes,
            "updated_by": str(self.updated_by) if self.updated_by else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
