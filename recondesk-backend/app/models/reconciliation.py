"""SQLAlchemy declarative models and Pydantic schemas for the reconciliation data layer.

Defines:
- ReconciliationRun: Purchase-side reconciliation run header, status, KPIs, and audit metadata.
- GstrRecord: Line items parsed and ingested from GSTR-2B / GSTR-2A supplier filings.
- PrRecord: Line items ingested from taxpayer books (purchase registers).
- ReconciliationResult: Serialized / compressed reconciliation engine results and match confidence.
- Legacy Pydantic models preserved for backward compatibility.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON

from app.models.base import StrictModel
from app.models.schema_base import Base, GUID


# ── Preserved Pydantic Models ──────────────────────────────────────────────────


class ReconciliationStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class MatchStatus(str, Enum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    PARTIAL = "partial"
    EXCEPTION = "exception"


class ReconciliationJobCreate(StrictModel):
    name: str
    source_file_key: str
    target_file_key: str
    match_columns: List[str]
    tolerance: Optional[float] = 0.0


class ReconciliationJobResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    status: ReconciliationStatus
    source_file_key: str
    target_file_key: str
    match_columns: List[str]
    tolerance: float
    total_rows: Optional[int] = None
    matched_rows: Optional[int] = None
    unmatched_rows: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ReconciliationRow(BaseModel):
    row_index: int
    match_status: MatchStatus
    source_data: Dict[str, Any]
    target_data: Optional[Dict[str, Any]] = None
    discrepancies: Optional[Dict[str, Any]] = None
    match_score: Optional[float] = None


# ── SQLAlchemy Models for AWS Aurora ─────────────────────────────────────────


class ReconciliationRun(Base):
    """Purchase-side reconciliation run header and execution lifecycle in AWS Aurora."""

    __tablename__ = "reconciliation_run"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    client_gstin_id = Column(
        GUID(),
        ForeignKey("client_gstins.id"),
        nullable=True,
    )
    period = Column(String, nullable=False)
    file_type = Column(String, nullable=True)
    file_hash = Column(String, nullable=True)
    r2_key = Column(String, nullable=True)
    status = Column(String, default="queued", nullable=True)
    progress_percent = Column(Numeric, default=0, nullable=True)
    status_message = Column(String, nullable=True)
    gstr_records_imported = Column(Integer, default=0, nullable=True)
    pr_records_imported = Column(Integer, default=0, nullable=True)
    failed_records = Column(Integer, default=0, nullable=True)
    total_records = Column(Integer, default=0, nullable=True)
    inserted_records = Column(Integer, default=0, nullable=True)
    retry_count = Column(Integer, default=0, nullable=True)
    sanity_report = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=True,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=True,
    )
    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    run_summary = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    matched_count = Column(Integer, nullable=True)
    unmatched_count = Column(Integer, nullable=True)
    itc_at_risk = Column(BigInteger, nullable=True)
    wrongful_itc = Column(BigInteger, nullable=True)
    late_itc = Column(BigInteger, nullable=True)
    matching_version = Column(String, nullable=True)
    rules_version = Column(String, nullable=True)
    decision_version = Column(String, nullable=True)
    gstr_period_end = Column(Date, nullable=True)
    is_locked = Column(Boolean, default=False, nullable=True)
    finalized_at = Column(DateTime(timezone=False), nullable=True)
    finalized_by = Column(GUID(), nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String(64), nullable=True)
    table4_summary_id = Column(GUID(), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "client_gstin_id",
            "period",
            "file_type",
            "file_hash",
            name="uq_run_dedup",
        ),
        Index("idx_reconciliation_run_client_created_at", "client_gstin_id", "created_at"),
        Index("idx_reconciliation_run_created_by", "created_by"),
        Index("idx_reconciliation_run_paid_at", "paid_at"),
        Index("idx_reconciliation_run_status", "status"),
    )

    # Relationships
    gstr_records = relationship(
        "GstrRecord",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    pr_records = relationship(
        "PrRecord",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    results = relationship(
        "ReconciliationResult",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize run header into dictionary compatible with Supabase PostgREST shape."""
        return {
            "id": str(self.id),
            "client_gstin_id": str(self.client_gstin_id) if self.client_gstin_id else None,
            "period": self.period,
            "file_type": self.file_type,
            "file_hash": self.file_hash,
            "r2_key": self.r2_key,
            "status": self.status,
            "progress_percent": float(self.progress_percent) if self.progress_percent is not None else 0.0,
            "status_message": self.status_message,
            "gstr_records_imported": self.gstr_records_imported or 0,
            "pr_records_imported": self.pr_records_imported or 0,
            "failed_records": self.failed_records or 0,
            "total_records": self.total_records or 0,
            "inserted_records": self.inserted_records or 0,
            "retry_count": self.retry_count or 0,
            "sanity_report": self.sanity_report,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "processing_started_at": self.processing_started_at.isoformat() if self.processing_started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "run_summary": self.run_summary,
            "matched_count": self.matched_count,
            "unmatched_count": self.unmatched_count,
            "itc_at_risk": self.itc_at_risk,
            "wrongful_itc": self.wrongful_itc,
            "late_itc": self.late_itc,
            "matching_version": self.matching_version,
            "rules_version": self.rules_version,
            "decision_version": self.decision_version,
            "gstr_period_end": self.gstr_period_end.isoformat() if self.gstr_period_end else None,
            "is_locked": self.is_locked if self.is_locked is not None else False,
            "finalized_at": self.finalized_at.isoformat() if self.finalized_at else None,
            "finalized_by": str(self.finalized_by) if self.finalized_by else None,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "created_by": self.created_by,
            "table4_summary_id": str(self.table4_summary_id) if self.table4_summary_id else None,
        }


class GstrRecord(Base):
    """Line items ingested from GSTR-2B / GSTR-2A supplier filings in AWS Aurora."""

    __tablename__ = "gstr_records"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        GUID(),
        ForeignKey("reconciliation_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    supplier_gstin_raw = Column(String, nullable=True)
    supplier_gstin = Column(String, nullable=True)
    invoice_number_raw = Column(String, nullable=True)
    invoice_number = Column(String, nullable=True)
    invoice_date_raw = Column(String, nullable=True)
    invoice_date = Column(Date, nullable=True)
    taxable_amount_raw = Column(String, nullable=True)
    taxable_amount_paise = Column(BigInteger, nullable=True)
    igst_paise = Column(BigInteger, nullable=True)
    cgst_paise = Column(BigInteger, nullable=True)
    sgst_paise = Column(BigInteger, nullable=True)
    total_tax_paise = Column(BigInteger, nullable=True)
    hsn_code = Column(String, nullable=True)
    document_type = Column(String, nullable=True)
    is_amendment = Column(Boolean, default=False, nullable=False)
    match_status = Column(String, nullable=True)
    match_level = Column(Integer, nullable=True)
    match_confidence = Column(Integer, nullable=True)
    matched_pr_record_id = Column(GUID(), nullable=True)
    match_reason = Column(String, nullable=True)
    match_discrepancies = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    possible_blocked_credit = Column(Boolean, nullable=True)
    decision_what = Column(String, nullable=True)
    decision_why = Column(String, nullable=True)
    decision_next = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    client_gstin_id = Column(String, nullable=True)
    period = Column(String(7), nullable=True)
    record_data = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    amount_difference_paise = Column(BigInteger, nullable=True)
    gstr2b_reflection_date = Column(Date, nullable=True)
    ai_explanation = Column(String, nullable=True)

    __table_args__ = (
        Index("idx_gstr_records_run_id", "run_id"),
        Index("idx_gstr_records_client_gstin_id", "client_gstin_id"),
        Index("idx_gstr_records_supplier_gstin", "supplier_gstin"),
        Index("idx_gstr_records_invoice_number", "invoice_number"),
        Index("idx_gstr_client_period", "client_gstin_id", "period"),
        Index("idx_gstr_run_gstin", "run_id", "supplier_gstin"),
        Index("idx_gstr_run_invoice", "run_id", "invoice_number"),
        Index("idx_gstr_run_status", "run_id", "match_status"),
    )

    run = relationship("ReconciliationRun", back_populates="gstr_records")

    def to_dict(self) -> dict[str, Any]:
        """Serialize GSTR record into dictionary compatible with Supabase PostgREST shape."""
        return {
            "id": str(self.id),
            "run_id": str(self.run_id),
            "supplier_gstin_raw": self.supplier_gstin_raw,
            "supplier_gstin": self.supplier_gstin,
            "invoice_number_raw": self.invoice_number_raw,
            "invoice_number": self.invoice_number,
            "invoice_date_raw": self.invoice_date_raw,
            "invoice_date": self.invoice_date.isoformat() if self.invoice_date else None,
            "taxable_amount_raw": self.taxable_amount_raw,
            "taxable_amount_paise": self.taxable_amount_paise,
            "igst_paise": self.igst_paise,
            "cgst_paise": self.cgst_paise,
            "sgst_paise": self.sgst_paise,
            "total_tax_paise": self.total_tax_paise,
            "hsn_code": self.hsn_code,
            "document_type": self.document_type,
            "is_amendment": self.is_amendment,
            "match_status": self.match_status,
            "match_level": self.match_level,
            "match_confidence": self.match_confidence,
            "matched_pr_record_id": str(self.matched_pr_record_id) if self.matched_pr_record_id else None,
            "match_reason": self.match_reason,
            "match_discrepancies": self.match_discrepancies,
            "possible_blocked_credit": self.possible_blocked_credit,
            "decision_what": self.decision_what,
            "decision_why": self.decision_why,
            "decision_next": self.decision_next,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "client_gstin_id": self.client_gstin_id,
            "period": self.period,
            "record_data": self.record_data,
            "amount_difference_paise": self.amount_difference_paise,
            "gstr2b_reflection_date": self.gstr2b_reflection_date.isoformat() if self.gstr2b_reflection_date else None,
            "ai_explanation": self.ai_explanation,
        }


class PrRecord(Base):
    """Line items ingested from taxpayer books (purchase registers) in AWS Aurora."""

    __tablename__ = "pr_records"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        GUID(),
        ForeignKey("reconciliation_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    supplier_gstin_raw = Column(String, nullable=True)
    supplier_gstin = Column(String, nullable=True)
    invoice_number_raw = Column(String, nullable=True)
    invoice_number = Column(String, nullable=True)
    invoice_date_raw = Column(String, nullable=True)
    invoice_date = Column(Date, nullable=True)
    taxable_amount_raw = Column(String, nullable=True)
    taxable_amount_paise = Column(BigInteger, nullable=True)
    igst_paise = Column(BigInteger, nullable=True)
    cgst_paise = Column(BigInteger, nullable=True)
    sgst_paise = Column(BigInteger, nullable=True)
    hsn_code = Column(String, nullable=True)
    document_type = Column(String, nullable=True)
    is_amendment = Column(Boolean, default=False, nullable=False)
    match_status = Column(String, nullable=True)
    match_level = Column(Integer, nullable=True)
    match_confidence = Column(Integer, nullable=True)
    matched_pr_record_id = Column(GUID(), nullable=True)
    match_reason = Column(String, nullable=True)
    possible_blocked_credit = Column(Boolean, nullable=True)
    payment_date = Column(Date, nullable=True)
    is_paid = Column(Boolean, nullable=True)
    rule_37_status = Column(String, nullable=True)
    rule_37_deadline = Column(Date, nullable=True)
    source_software = Column(String, nullable=True)
    decision_what = Column(String, nullable=True)
    decision_why = Column(String, nullable=True)
    decision_next = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    sanity_gstin_valid = Column(Boolean, default=True, nullable=True)
    sanity_date_valid = Column(Boolean, default=True, nullable=True)
    sanity_amount_valid = Column(Boolean, default=True, nullable=True)
    sanity_duplicate_flag = Column(Boolean, default=False, nullable=True)
    discrepancy_gstin = Column(String, nullable=True)
    discrepancy_amount_diff_paise = Column(BigInteger, default=0, nullable=True)
    discrepancy_date_diff_days = Column(Integer, default=0, nullable=True)
    discrepancy_notes = Column(String, nullable=True)
    client_gstin_id = Column(GUID(), nullable=True)
    period = Column(String, nullable=True)
    record_data = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )

    __table_args__ = (
        Index("idx_pr_records_run_id", "run_id"),
        Index("idx_pr_records_client_gstin_id", "client_gstin_id"),
        Index("idx_pr_records_supplier_gstin", "supplier_gstin"),
        Index("idx_pr_records_invoice_number", "invoice_number"),
        Index("idx_pr_records_invoice_date", "invoice_date"),
        Index("idx_pr_records_match_status", "match_status"),
        Index("idx_pr_records_client_period_id", "client_gstin_id", "period", "id"),
        Index("idx_pr_matched_record", "matched_pr_record_id"),
    )

    run = relationship("ReconciliationRun", back_populates="pr_records")

    def to_dict(self) -> dict[str, Any]:
        """Serialize PR record into dictionary compatible with Supabase PostgREST shape."""
        return {
            "id": str(self.id),
            "run_id": str(self.run_id),
            "supplier_gstin_raw": self.supplier_gstin_raw,
            "supplier_gstin": self.supplier_gstin,
            "invoice_number_raw": self.invoice_number_raw,
            "invoice_number": self.invoice_number,
            "invoice_date_raw": self.invoice_date_raw,
            "invoice_date": self.invoice_date.isoformat() if self.invoice_date else None,
            "taxable_amount_raw": self.taxable_amount_raw,
            "taxable_amount_paise": self.taxable_amount_paise,
            "igst_paise": self.igst_paise,
            "cgst_paise": self.cgst_paise,
            "sgst_paise": self.sgst_paise,
            "hsn_code": self.hsn_code,
            "document_type": self.document_type,
            "is_amendment": self.is_amendment,
            "match_status": self.match_status,
            "match_level": self.match_level,
            "match_confidence": self.match_confidence,
            "matched_pr_record_id": str(self.matched_pr_record_id) if self.matched_pr_record_id else None,
            "match_reason": self.match_reason,
            "possible_blocked_credit": self.possible_blocked_credit,
            "payment_date": self.payment_date.isoformat() if self.payment_date else None,
            "is_paid": self.is_paid,
            "rule_37_status": self.rule_37_status,
            "rule_37_deadline": self.rule_37_deadline.isoformat() if self.rule_37_deadline else None,
            "source_software": self.source_software,
            "decision_what": self.decision_what,
            "decision_why": self.decision_why,
            "decision_next": self.decision_next,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "sanity_gstin_valid": self.sanity_gstin_valid,
            "sanity_date_valid": self.sanity_date_valid,
            "sanity_amount_valid": self.sanity_amount_valid,
            "sanity_duplicate_flag": self.sanity_duplicate_flag,
            "discrepancy_gstin": self.discrepancy_gstin,
            "discrepancy_amount_diff_paise": self.discrepancy_amount_diff_paise or 0,
            "discrepancy_date_diff_days": self.discrepancy_date_diff_days or 0,
            "discrepancy_notes": self.discrepancy_notes,
            "client_gstin_id": str(self.client_gstin_id) if self.client_gstin_id else None,
            "period": self.period,
            "record_data": self.record_data,
        }


class ReconciliationResult(Base):
    """Compressed reconciliation engine results and match confidence in AWS Aurora."""

    __tablename__ = "reconciliation_results"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        GUID(),
        ForeignKey("reconciliation_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    record_data = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=True,
    )
    payload = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    match_confidence = Column(Float, nullable=True)

    __table_args__ = (
        Index("idx_reconciliation_results_run_id", "run_id"),
        Index("idx_reconciliation_results_created", "created_at"),
    )

    run = relationship("ReconciliationRun", back_populates="results")

    def to_dict(self) -> dict[str, Any]:
        """Serialize result row into dictionary compatible with Supabase PostgREST shape."""
        return {
            "id": str(self.id),
            "run_id": str(self.run_id),
            "record_data": self.record_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "payload": self.payload,
            "match_confidence": self.match_confidence,
        }
