"""SQLAlchemy declarative models for Batch 2B GSTR-3B Table 4, Reversal & Reclaim Ledger.

Defines:
- Gstr3bReversalLedger: Cross-period statutory reversal ledger tracking temporary reversals (Table 4B2).
- Gstr3bTable4Summary: Authoritative Table 4 workpaper summary snapshots with versioning.
- Gstr3bReclaimEvent: Immutable historical source of truth for reclaims against reversal ledger entries.
- Gstr3bTable4Adjustment: Manual and external statutory additions/reductions directly targeting Table 4 cells.
- Gstr3bReconciliation: Per-run comparison of ITC available in GSTR-2B vs claimed in GSTR-3B.
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON

from app.models.schema_base import Base, GUID


class Gstr3bReversalLedger(Base):
    """General Table 4(B)(2) statutory temporary reversal ledger."""

    __tablename__ = "gstr3b_reversal_ledger"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    client_gstin_id = Column(
        GUID(),
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_type = Column(String(30), nullable=False)
    source_record_id = Column(Text, nullable=False)
    source_run_id = Column(
        GUID(),
        ForeignKey("reconciliation_run.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reversal_tax_period = Column(String(7), nullable=False)
    source_state_hash = Column(String(64), nullable=False, default="")
    source_payload = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    document_type = Column(String(20), nullable=False, default="INVOICE")
    document_number = Column(String(100), nullable=True)
    document_date = Column(Date, nullable=True)
    supplier_gstin = Column(String(15), nullable=True)
    reference_doc = Column(String(150), nullable=True)
    reversal_table4_cell = Column(String(10), nullable=False, default="4B2")
    is_reclaimable = Column(Boolean, nullable=False, default=True)
    statutory_reason = Column(String(60), nullable=False)
    itc_financial_year = Column(String(7), nullable=True)
    supplier_outward_statement_period = Column(String(7), nullable=True)
    supplier_gstr1_filing_date = Column(Date, nullable=True)
    supplier_gstr3b_tax_period = Column(String(7), nullable=True)
    supplier_gstr3b_filing_status = Column(String(20), nullable=True, default="UNKNOWN")
    filed_by_september_30 = Column(Boolean, nullable=True, default=False)
    september_test_date = Column(Date, nullable=True)
    november_reversal_deadline = Column(Date, nullable=True)
    actual_reversal_date = Column(Date, nullable=True)
    subsequent_supplier_filing_date = Column(Date, nullable=True)
    subsequent_filing_arn = Column(String(50), nullable=True)
    condition_fulfilled_date = Column(Date, nullable=True)
    reclaim_eligibility_date = Column(Date, nullable=True)
    reversed_igst_paise = Column(BigInteger, nullable=False, default=0)
    reversed_cgst_paise = Column(BigInteger, nullable=False, default=0)
    reversed_sgst_paise = Column(BigInteger, nullable=False, default=0)
    reversed_cess_paise = Column(BigInteger, nullable=False, default=0)
    cached_reclaimed_igst_paise = Column(BigInteger, nullable=False, default=0)
    cached_reclaimed_cgst_paise = Column(BigInteger, nullable=False, default=0)
    cached_reclaimed_sgst_paise = Column(BigInteger, nullable=False, default=0)
    cached_reclaimed_cess_paise = Column(BigInteger, nullable=False, default=0)
    status = Column(String(25), nullable=False, default="OPEN")
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
    created_by = Column(GUID(), nullable=True)  # Bare UUID, no FK to user_profiles

    # Relationships
    reclaim_events = relationship(
        "Gstr3bReclaimEvent",
        back_populates="ledger_entry",
        foreign_keys="Gstr3bReclaimEvent.ledger_id",
    )

    __table_args__ = (
        CheckConstraint("reversal_table4_cell = '4B2'", name="chk_reversal_table4_cell_4b2"),
        CheckConstraint(
            "reversed_igst_paise >= 0 AND reversed_cgst_paise >= 0 AND reversed_sgst_paise >= 0 AND reversed_cess_paise >= 0",
            name="chk_non_negative_reversed_amounts",
        ),
        CheckConstraint(
            "(reversed_igst_paise + reversed_cgst_paise + reversed_sgst_paise + reversed_cess_paise) > 0",
            name="chk_total_reversed_positive",
        ),
        CheckConstraint(
            "cached_reclaimed_igst_paise <= reversed_igst_paise AND "
            "cached_reclaimed_cgst_paise <= reversed_cgst_paise AND "
            "cached_reclaimed_sgst_paise <= reversed_sgst_paise AND "
            "cached_reclaimed_cess_paise <= reversed_cess_paise",
            name="chk_cached_reclaim_le_reversed",
        ),
        CheckConstraint(
            "source_type IN ('RECON_OUTCOME', 'EXCEPTION_DISPOSITION', 'STATUTORY_ADJUSTMENT', 'OPENING_BALANCE')",
            name="chk_source_type",
        ),
        CheckConstraint(
            "statutory_reason IN ('RULE_37_NON_PAYMENT', 'RULE_37A_SUPPLIER_NON_FILING', "
            "'SECTION_16_2_B_NOT_RECEIVED', 'SECTION_16_2_C_SUPPLIER_TAX_CONDITION', "
            "'OTHER_TEMPORARY', 'OPENING_BALANCE')",
            name="chk_statutory_reason",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'CONDITION_FULFILLED', 'RECLAIM_AUTHORIZED', 'PARTIALLY_RECLAIMED', 'FULLY_RECLAIMED', 'NON_RECLAIMABLE')",
            name="chk_reversal_status",
        ),
        Index("idx_reversal_ledger_client_status", "client_gstin_id", "status"),
        Index("idx_reversal_ledger_source", "source_type", "source_record_id"),
        Index("idx_reversal_ledger_run_id", "source_run_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "client_gstin_id": str(self.client_gstin_id),
            "source_type": self.source_type,
            "source_record_id": self.source_record_id,
            "source_run_id": str(self.source_run_id) if self.source_run_id else None,
            "reversal_tax_period": self.reversal_tax_period,
            "source_state_hash": self.source_state_hash,
            "source_payload": self.source_payload,
            "document_type": self.document_type,
            "document_number": self.document_number,
            "document_date": self.document_date.isoformat() if self.document_date else None,
            "supplier_gstin": self.supplier_gstin,
            "reference_doc": self.reference_doc,
            "reversal_table4_cell": self.reversal_table4_cell,
            "is_reclaimable": self.is_reclaimable,
            "statutory_reason": self.statutory_reason,
            "itc_financial_year": self.itc_financial_year,
            "supplier_outward_statement_period": self.supplier_outward_statement_period,
            "supplier_gstr1_filing_date": self.supplier_gstr1_filing_date.isoformat() if self.supplier_gstr1_filing_date else None,
            "supplier_gstr3b_tax_period": self.supplier_gstr3b_tax_period,
            "supplier_gstr3b_filing_status": self.supplier_gstr3b_filing_status,
            "filed_by_september_30": self.filed_by_september_30,
            "september_test_date": self.september_test_date.isoformat() if self.september_test_date else None,
            "november_reversal_deadline": self.november_reversal_deadline.isoformat() if self.november_reversal_deadline else None,
            "actual_reversal_date": self.actual_reversal_date.isoformat() if self.actual_reversal_date else None,
            "subsequent_supplier_filing_date": self.subsequent_supplier_filing_date.isoformat() if self.subsequent_supplier_filing_date else None,
            "subsequent_filing_arn": self.subsequent_filing_arn,
            "condition_fulfilled_date": self.condition_fulfilled_date.isoformat() if self.condition_fulfilled_date else None,
            "reclaim_eligibility_date": self.reclaim_eligibility_date.isoformat() if self.reclaim_eligibility_date else None,
            "reversed_igst_paise": self.reversed_igst_paise,
            "reversed_cgst_paise": self.reversed_cgst_paise,
            "reversed_sgst_paise": self.reversed_sgst_paise,
            "reversed_cess_paise": self.reversed_cess_paise,
            "cached_reclaimed_igst_paise": self.cached_reclaimed_igst_paise,
            "cached_reclaimed_cgst_paise": self.cached_reclaimed_cgst_paise,
            "cached_reclaimed_sgst_paise": self.cached_reclaimed_sgst_paise,
            "cached_reclaimed_cess_paise": self.cached_reclaimed_cess_paise,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": str(self.created_by) if self.created_by else None,
        }


class Gstr3bTable4Summary(Base):
    """Authoritative Table 4 workpaper summary snapshots with versioning."""

    __tablename__ = "gstr3b_table4_summaries"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        GUID(),
        ForeignKey("reconciliation_run.id", ondelete="RESTRICT"),
        nullable=False,
    )
    client_gstin_id = Column(
        GUID(),
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
    )
    tax_period = Column(String(7), nullable=False)
    status = Column(String(20), nullable=False, default="PROVISIONAL")
    table_4a1 = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    table_4a2 = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    table_4a3 = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    table_4a4 = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    table_4a5 = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    table_4a_total = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    table_4b1 = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    table_4b2 = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    table_4b_total = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    table_4c = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    table_4d1 = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    table_4d2 = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    audit_hash = Column(String(64), nullable=False, default="")
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
    finalized_at = Column(DateTime(timezone=True), nullable=True)
    finalized_by = Column(GUID(), nullable=True)  # Bare UUID
    version = Column(Integer, nullable=False, default=1)
    is_current = Column(Boolean, nullable=False, default=True)
    superseded_at = Column(DateTime(timezone=True), nullable=True)
    superseded_by = Column(GUID(), nullable=True)  # Bare UUID
    source_state_digest = Column(String(64), nullable=False, default="")
    snapshot_payload = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    contributing_outcome_ids = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    contributing_disposition_ids = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    contributing_adjustment_ids = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    contributing_reclaim_ids = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)

    __table_args__ = (
        UniqueConstraint("run_id", "version", name="uq_table4_summary_run_version"),
        Index("idx_gstr3b_table4_run_id", "run_id"),
        Index("idx_gstr3b_table4_client_period", "client_gstin_id", "tax_period"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "run_id": str(self.run_id),
            "client_gstin_id": str(self.client_gstin_id),
            "tax_period": self.tax_period,
            "status": self.status,
            "table_4a1": self.table_4a1,
            "table_4a2": self.table_4a2,
            "table_4a3": self.table_4a3,
            "table_4a4": self.table_4a4,
            "table_4a5": self.table_4a5,
            "table_4a_total": self.table_4a_total,
            "table_4b1": self.table_4b1,
            "table_4b2": self.table_4b2,
            "table_4b_total": self.table_4b_total,
            "table_4c": self.table_4c,
            "table_4d1": self.table_4d1,
            "table_4d2": self.table_4d2,
            "audit_hash": self.audit_hash,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "finalized_at": self.finalized_at.isoformat() if self.finalized_at else None,
            "finalized_by": str(self.finalized_by) if self.finalized_by else None,
            "version": self.version,
            "is_current": self.is_current,
            "superseded_at": self.superseded_at.isoformat() if self.superseded_at else None,
            "superseded_by": str(self.superseded_by) if self.superseded_by else None,
            "source_state_digest": self.source_state_digest,
            "snapshot_payload": self.snapshot_payload,
            "contributing_outcome_ids": self.contributing_outcome_ids,
            "contributing_disposition_ids": self.contributing_disposition_ids,
            "contributing_adjustment_ids": self.contributing_adjustment_ids,
            "contributing_reclaim_ids": self.contributing_reclaim_ids,
        }


class Gstr3bReclaimEvent(Base):
    """Immutable historical source of truth for reclaims against reversal ledger entries."""

    __tablename__ = "gstr3b_reclaim_events"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    client_gstin_id = Column(
        GUID(),
        ForeignKey("client_gstins.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ledger_id = Column(
        GUID(),
        ForeignKey("gstr3b_reversal_ledger.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reclaim_run_id = Column(
        GUID(),
        ForeignKey("reconciliation_run.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reclaim_tax_period = Column(String(7), nullable=False)
    event_type = Column(String(30), nullable=False, default="RECLAIM")
    compensates_event_id = Column(
        GUID(),
        ForeignKey("gstr3b_reclaim_events.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reclaimed_igst_paise = Column(BigInteger, nullable=False, default=0)
    reclaimed_cgst_paise = Column(BigInteger, nullable=False, default=0)
    reclaimed_sgst_paise = Column(BigInteger, nullable=False, default=0)
    reclaimed_cess_paise = Column(BigInteger, nullable=False, default=0)
    statutory_evidence_type = Column(String(50), nullable=False)
    evidence_reference = Column(String(150), nullable=False)
    evidence_document_date = Column(Date, nullable=True)
    authorized_by = Column(GUID(), nullable=True)  # Bare UUID
    reclaim_notes = Column(Text, nullable=False, default="")
    idempotency_key = Column(String(120), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    ledger_entry = relationship(
        "Gstr3bReversalLedger",
        back_populates="reclaim_events",
        foreign_keys=[ledger_id],
    )
    compensating_event = relationship(
        "Gstr3bReclaimEvent",
        remote_side=[id],
        foreign_keys=[compensates_event_id],
    )

    __table_args__ = (
        CheckConstraint(
            "reclaimed_igst_paise >= 0 AND reclaimed_cgst_paise >= 0 AND reclaimed_sgst_paise >= 0 AND reclaimed_cess_paise >= 0",
            name="chk_reclaim_amounts_non_negative",
        ),
        CheckConstraint(
            "(reclaimed_igst_paise + reclaimed_cgst_paise + reclaimed_sgst_paise + reclaimed_cess_paise) > 0",
            name="chk_reclaim_amounts_positive",
        ),
        CheckConstraint(
            "statutory_evidence_type IN ('PAYMENT_TO_SUPPLIER', 'SUPPLIER_GSTR3B_FILED', 'GOODS_RECEIVED_GRN', "
            "'TAX_DISCHARGE_CONFIRMED', 'OPENING_BALANCE_VERIFIED', 'COMPENSATING_ADJUSTMENT', 'OTHER_STATUTORY_PROOF')",
            name="chk_evidence_type",
        ),
        CheckConstraint(
            "event_type IN ('RECLAIM', 'COMPENSATING_REVERSAL')",
            name="chk_event_type",
        ),
        Index("idx_reclaim_events_ledger_id", "ledger_id"),
        Index("idx_reclaim_events_run_id", "reclaim_run_id"),
        Index("idx_reclaim_events_client_id", "client_gstin_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "client_gstin_id": str(self.client_gstin_id),
            "ledger_id": str(self.ledger_id),
            "reclaim_run_id": str(self.reclaim_run_id),
            "reclaim_tax_period": self.reclaim_tax_period,
            "event_type": self.event_type,
            "compensates_event_id": str(self.compensates_event_id) if self.compensates_event_id else None,
            "reclaimed_igst_paise": self.reclaimed_igst_paise,
            "reclaimed_cgst_paise": self.reclaimed_cgst_paise,
            "reclaimed_sgst_paise": self.reclaimed_sgst_paise,
            "reclaimed_cess_paise": self.reclaimed_cess_paise,
            "statutory_evidence_type": self.statutory_evidence_type,
            "evidence_reference": self.evidence_reference,
            "evidence_document_date": self.evidence_document_date.isoformat() if self.evidence_document_date else None,
            "authorized_by": str(self.authorized_by) if self.authorized_by else None,
            "reclaim_notes": self.reclaim_notes,
            "idempotency_key": self.idempotency_key,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Gstr3bTable4Adjustment(Base):
    """Statutory Table 4 cell adjustments (Rules 42/43/38/RCM)."""

    __tablename__ = "gstr3b_table4_adjustments"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        GUID(),
        ForeignKey("reconciliation_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_gstin_id = Column(
        GUID(),
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
    )
    tax_period = Column(String(7), nullable=False)
    row_id = Column(String(10), nullable=False)
    igst_paise = Column(BigInteger, nullable=False, default=0)
    cgst_paise = Column(BigInteger, nullable=False, default=0)
    sgst_paise = Column(BigInteger, nullable=False, default=0)
    cess_paise = Column(BigInteger, nullable=False, default=0)
    adjustment_type = Column(String(20), nullable=False)
    statutory_category = Column(String(50), nullable=False)
    reason = Column(Text, nullable=False)
    reference_doc = Column(String(100), nullable=True)
    turnover_ratio_data = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    created_by = Column(GUID(), nullable=True)  # Bare UUID
    is_deleted = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("idx_table4_adj_run_id", "run_id"),
        Index("idx_table4_adj_client_period", "client_gstin_id", "tax_period"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "run_id": str(self.run_id),
            "client_gstin_id": str(self.client_gstin_id),
            "tax_period": self.tax_period,
            "row_id": self.row_id,
            "igst_paise": self.igst_paise,
            "cgst_paise": self.cgst_paise,
            "sgst_paise": self.sgst_paise,
            "cess_paise": self.cess_paise,
            "adjustment_type": self.adjustment_type,
            "statutory_category": self.statutory_category,
            "reason": self.reason,
            "reference_doc": self.reference_doc,
            "turnover_ratio_data": self.turnover_ratio_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "created_by": str(self.created_by) if self.created_by else None,
            "is_deleted": self.is_deleted,
        }


class Gstr3bReconciliation(Base):
    """Per-run comparison of ITC available in GSTR-2B vs claimed in GSTR-3B."""

    __tablename__ = "gstr3b_reconciliation"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        GUID(),
        ForeignKey("reconciliation_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_gstin = Column(Text, nullable=False)
    tax_period = Column(String(7), nullable=False)
    gstr3b_igst_claimed = Column(Numeric(15, 2), default=Decimal("0.00"), nullable=True)
    gstr3b_cgst_claimed = Column(Numeric(15, 2), default=Decimal("0.00"), nullable=True)
    gstr3b_sgst_claimed = Column(Numeric(15, 2), default=Decimal("0.00"), nullable=True)
    gstr2b_igst_available = Column(Numeric(15, 2), default=Decimal("0.00"), nullable=True)
    gstr2b_cgst_available = Column(Numeric(15, 2), default=Decimal("0.00"), nullable=True)
    gstr2b_sgst_available = Column(Numeric(15, 2), default=Decimal("0.00"), nullable=True)
    igst_difference = Column(Numeric(15, 2), default=Decimal("0.00"), nullable=True)
    cgst_difference = Column(Numeric(15, 2), default=Decimal("0.00"), nullable=True)
    sgst_difference = Column(Numeric(15, 2), default=Decimal("0.00"), nullable=True)
    igst_status = Column(Text, nullable=True)
    cgst_status = Column(Text, nullable=True)
    sgst_status = Column(Text, nullable=True)
    overall_status = Column(Text, nullable=True)
    outward_supply_total = Column(Numeric(15, 2), default=Decimal("0.00"), nullable=True)
    raw_gstr3b = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    uploaded_by = Column(GUID(), nullable=False)  # Bare UUID
    uploaded_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_gstr3b_recon_run_id", "run_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "run_id": str(self.run_id),
            "client_gstin": self.client_gstin,
            "tax_period": self.tax_period,
            "gstr3b_igst_claimed": float(self.gstr3b_igst_claimed) if self.gstr3b_igst_claimed is not None else 0.0,
            "gstr3b_cgst_claimed": float(self.gstr3b_cgst_claimed) if self.gstr3b_cgst_claimed is not None else 0.0,
            "gstr3b_sgst_claimed": float(self.gstr3b_sgst_claimed) if self.gstr3b_sgst_claimed is not None else 0.0,
            "gstr2b_igst_available": float(self.gstr2b_igst_available) if self.gstr2b_igst_available is not None else 0.0,
            "gstr2b_cgst_available": float(self.gstr2b_cgst_available) if self.gstr2b_cgst_available is not None else 0.0,
            "gstr2b_sgst_available": float(self.gstr2b_sgst_available) if self.gstr2b_sgst_available is not None else 0.0,
            "igst_difference": float(self.igst_difference) if self.igst_difference is not None else 0.0,
            "cgst_difference": float(self.cgst_difference) if self.cgst_difference is not None else 0.0,
            "sgst_difference": float(self.sgst_difference) if self.sgst_difference is not None else 0.0,
            "igst_status": self.igst_status,
            "cgst_status": self.cgst_status,
            "sgst_status": self.sgst_status,
            "overall_status": self.overall_status,
            "outward_supply_total": float(self.outward_supply_total) if self.outward_supply_total is not None else 0.0,
            "raw_gstr3b": self.raw_gstr3b,
            "uploaded_by": str(self.uploaded_by),
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
        }
