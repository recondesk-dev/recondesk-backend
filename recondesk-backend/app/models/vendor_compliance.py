"""SQLAlchemy declarative models for Batch 2C Vendor Compliance, Audit, and Work Items.

Defines:
- SupplierComplianceSummary: Firm-level rollup of supplier compliance metrics.
- SupplierComplianceByClient: Per-client contribution counters for vendor compliance.
- SupplierFollowupAudit: Immutable audit trail for generated supplier follow-up letters.
- ITCWorkItem: Operational lifecycle tracking for at-risk ITC invoices.
- ITCWorkItemEvent: Activity log and status transitions on work items.
- VendorFollowupLog: Vendor communication dispatch log with portal response integration.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import sqlalchemy as sa
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
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON, TypeDecorator

from app.models.schema_base import Base, GUID


# ── Custom Cross-Dialect Types ───────────────────────────────────────────────

class ArrayOfUUID(TypeDecorator):
    """Platform-independent Array of UUIDs. Uses PG_ARRAY on Postgres and JSON on SQLite."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_ARRAY(PG_UUID(as_uuid=True)))
        return dialect.type_descriptor(JSON)

    def process_bind_param(self, value, dialect):
        if value is None:
            return []
        if isinstance(value, (list, set, tuple)):
            return [str(v) for v in value]
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value]
        return value


class ArrayOfText(TypeDecorator):
    """Platform-independent Array of Strings. Uses PG_ARRAY on Postgres and JSON on SQLite."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_ARRAY(Text))
        return dialect.type_descriptor(JSON)

    def process_bind_param(self, value, dialect):
        if value is None:
            return []
        if isinstance(value, (list, set, tuple)):
            return [str(v) for v in value]
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value]
        return value


# ── 1. SupplierComplianceSummary ─────────────────────────────────────────────

class SupplierComplianceSummary(Base):
    """Firm-level rollup of supplier compliance metrics keyed by (firm_owner_id, supplier_gstin_normalized)."""

    __tablename__ = "supplier_compliance_summary"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    firm_owner_id = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    supplier_gstin_normalized = Column(String(15), nullable=False)
    supplier_trade_name = Column(Text, nullable=False, default="")
    client_gstin_ids = Column(ArrayOfUUID, nullable=False, default=list)
    clients_touched_count = Column(Integer, nullable=False, default=0)
    total_invoices = Column(Integer, nullable=False, default=0)
    mismatch_invoice_count = Column(Integer, nullable=False, default=0)
    mismatch_rate = Column(Numeric(5, 4), nullable=False, default=Decimal("0.0000"))
    rule37_open_count = Column(Integer, nullable=False, default=0)
    rule37_at_risk_paise = Column(BigInteger, nullable=False, default=0)
    section_17_5_count = Column(Integer, nullable=False, default=0)
    late_filing_count = Column(Integer, nullable=False, default=0)
    late_filing_rate = Column(Numeric(5, 4), nullable=False, default=Decimal("0.0000"))
    pr_only_count = Column(Integer, nullable=False, default=0)
    quarterly_filer_flag = Column(Boolean, nullable=False, default=False)
    risk_score = Column(Integer, nullable=False, default=0)
    last_updated_at = Column(
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
        UniqueConstraint("firm_owner_id", "supplier_gstin_normalized", name="supplier_compliance_summary_unique"),
        CheckConstraint("length(supplier_gstin_normalized) = 15", name="supplier_compliance_summary_gstin_len"),
        CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="supplier_compliance_summary_risk_score_range"),
        Index("idx_supplier_compliance_summary_firm_risk", "firm_owner_id", sa.text("risk_score DESC")),
        Index("idx_supplier_compliance_summary_firm_clients", "firm_owner_id", sa.text("clients_touched_count DESC")),
        Index("idx_supplier_compliance_summary_firm_updated", "firm_owner_id", sa.text("last_updated_at DESC")),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "firm_owner_id": str(self.firm_owner_id),
            "supplier_gstin_normalized": self.supplier_gstin_normalized,
            "supplier_trade_name": self.supplier_trade_name or "",
            "client_gstin_ids": [str(c) for c in (self.client_gstin_ids or [])],
            "clients_touched_count": int(self.clients_touched_count or 0),
            "total_invoices": int(self.total_invoices or 0),
            "mismatch_invoice_count": int(self.mismatch_invoice_count or 0),
            "mismatch_rate": float(self.mismatch_rate) if self.mismatch_rate is not None else 0.0,
            "rule37_open_count": int(self.rule37_open_count or 0),
            "rule37_at_risk_paise": int(self.rule37_at_risk_paise or 0),
            "section_17_5_count": int(self.section_17_5_count or 0),
            "late_filing_count": int(self.late_filing_count or 0),
            "late_filing_rate": float(self.late_filing_rate) if self.late_filing_rate is not None else 0.0,
            "pr_only_count": int(self.pr_only_count or 0),
            "quarterly_filer_flag": bool(self.quarterly_filer_flag),
            "risk_score": int(self.risk_score or 0),
            "last_updated_at": self.last_updated_at.isoformat() if self.last_updated_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ── 2. SupplierComplianceByClient ───────────────────────────────────────────

class SupplierComplianceByClient(Base):
    """Per-client contribution counters for vendor compliance scorecard (refreshed on run complete)."""

    __tablename__ = "supplier_compliance_by_client"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    firm_owner_id = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    supplier_gstin_normalized = Column(String(15), nullable=False)
    client_gstin_id = Column(
        GUID(),
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
    )
    supplier_trade_name = Column(Text, nullable=False, default="")
    total_invoices = Column(Integer, nullable=False, default=0)
    mismatch_invoice_count = Column(Integer, nullable=False, default=0)
    rule37_open_count = Column(Integer, nullable=False, default=0)
    rule37_at_risk_paise = Column(BigInteger, nullable=False, default=0)
    section_17_5_count = Column(Integer, nullable=False, default=0)
    late_filing_count = Column(Integer, nullable=False, default=0)
    pr_only_count = Column(Integer, nullable=False, default=0)
    quarterly_filer_flag = Column(Boolean, nullable=False, default=False)
    last_updated_at = Column(
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
        UniqueConstraint("firm_owner_id", "supplier_gstin_normalized", "client_gstin_id", name="supplier_compliance_by_client_unique"),
        CheckConstraint("length(supplier_gstin_normalized) = 15", name="supplier_compliance_by_client_gstin_len"),
        Index("idx_supplier_compliance_by_client_firm_supplier", "firm_owner_id", "supplier_gstin_normalized"),
        Index("idx_supplier_compliance_by_client_client", "client_gstin_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "firm_owner_id": str(self.firm_owner_id),
            "supplier_gstin_normalized": self.supplier_gstin_normalized,
            "client_gstin_id": str(self.client_gstin_id),
            "supplier_trade_name": self.supplier_trade_name or "",
            "total_invoices": int(self.total_invoices or 0),
            "mismatch_invoice_count": int(self.mismatch_invoice_count or 0),
            "rule37_open_count": int(self.rule37_open_count or 0),
            "rule37_at_risk_paise": int(self.rule37_at_risk_paise or 0),
            "section_17_5_count": int(self.section_17_5_count or 0),
            "late_filing_count": int(self.late_filing_count or 0),
            "pr_only_count": int(self.pr_only_count or 0),
            "quarterly_filer_flag": bool(self.quarterly_filer_flag),
            "last_updated_at": self.last_updated_at.isoformat() if self.last_updated_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ── 3. SupplierFollowupAudit ─────────────────────────────────────────────────

class SupplierFollowupAudit(Base):
    """Audit trail for supplier follow-up letters and communication snapshots."""

    __tablename__ = "supplier_followup_audit"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        GUID(),
        ForeignKey("reconciliation_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    tax_period = Column(String(7), nullable=False)
    supplier_gstin = Column(Text, nullable=False)
    record_ids = Column(ArrayOfText, nullable=False, default=list)
    invoice_snapshot = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    template_type = Column(Text, nullable=False)
    generated_by = Column(GUID(), nullable=False)
    generated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    status = Column(Text, nullable=False)
    supplier_name_display = Column(Text, nullable=True)
    letter_body = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('generated', 'downloaded', 'copied')", name="supplier_followup_audit_status_check"),
        CheckConstraint("template_type IN ('wrongful_itc_single', 'wrongful_itc_bulk')", name="supplier_followup_audit_template_check"),
        Index("idx_supplier_followup_audit_run_id", "run_id"),
        Index("idx_supplier_followup_audit_supplier", "run_id", "supplier_gstin"),
        Index("idx_supplier_followup_audit_period", "tax_period", sa.text("generated_at DESC")),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "run_id": str(self.run_id),
            "tax_period": self.tax_period,
            "supplier_gstin": self.supplier_gstin,
            "record_ids": [str(r) for r in (self.record_ids or [])],
            "invoice_snapshot": self.invoice_snapshot or {},
            "template_type": self.template_type,
            "generated_by": str(self.generated_by),
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "status": self.status,
            "supplier_name_display": self.supplier_name_display,
            "letter_body": self.letter_body,
        }


# ── 4. ITCWorkItem ───────────────────────────────────────────────────────────

class ITCWorkItem(Base):
    """Exception Work Item Lifecycle Engine for CA operational exception handling."""

    __tablename__ = "itc_work_items"

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
    run_id = Column(
        GUID(),
        ForeignKey("reconciliation_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    record_id = Column(Text, nullable=False)
    exception_type = Column(String(50), nullable=False)

    status = Column(String(30), nullable=False, default="OPEN")

    priority = Column(String(20), nullable=False, default="MEDIUM")
    system_priority = Column(String(20), nullable=False, default="MEDIUM")
    manual_priority = Column(String(20), nullable=True)
    priority_override_reason = Column(Text, nullable=True)
    priority_changed_by = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    priority_changed_at = Column(DateTime(timezone=True), nullable=True)

    category = Column(String(50), nullable=False, default="OTHER")
    title = Column(Text, nullable=True)
    what = Column(Text, nullable=False, default="")
    why = Column(Text, nullable=False, default="")
    next_action = Column(Text, nullable=False, default="")

    assigned_to = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    assigned_by = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )

    due_at = Column(DateTime(timezone=True), nullable=True)
    sla_status = Column(String(20), nullable=False, default="NO_DUE_DATE")

    resolution_code = Column(String(50), nullable=True)
    resolution_note = Column(Text, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )

    dismissal_reason = Column(Text, nullable=True)
    dismissed_at = Column(DateTime(timezone=True), nullable=True)
    dismissed_by = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    reopen_reason = Column(Text, nullable=True)
    reopened_at = Column(DateTime(timezone=True), nullable=True)
    reopened_by = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )

    revalidation_status = Column(String(30), nullable=False, default="NONE")
    revalidation_requested_at = Column(DateTime(timezone=True), nullable=True)
    revalidation_completed_at = Column(DateTime(timezone=True), nullable=True)
    revalidation_result = Column(String(30), nullable=True)

    source_version = Column(Integer, nullable=False, default=1)
    carried_forward_from_id = Column(
        GUID(),
        ForeignKey("itc_work_items.id", ondelete="SET NULL"),
        nullable=True,
    )

    vendor_gstin = Column(String(15), nullable=True)
    vendor_name = Column(Text, nullable=True)
    invoice_number = Column(String(100), nullable=True)
    invoice_date = Column(Date, nullable=True)
    taxable_value = Column(Numeric(15, 2), nullable=False, default=Decimal("0.00"))
    igst = Column(Numeric(15, 2), nullable=False, default=Decimal("0.00"))
    cgst = Column(Numeric(15, 2), nullable=False, default=Decimal("0.00"))
    sgst = Column(Numeric(15, 2), nullable=False, default=Decimal("0.00"))
    cess = Column(Numeric(15, 2), nullable=False, default=Decimal("0.00"))
    total_tax = Column(Numeric(15, 2), nullable=False, default=Decimal("0.00"))
    itc_amount_at_stake = Column(Numeric(15, 2), nullable=False, default=Decimal("0.00"))
    itc_amount_at_stake_paise = Column(BigInteger, nullable=False, default=0)
    is_blocking = Column(Boolean, nullable=False, default=False)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    created_by = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_by = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("run_id", "record_id", "exception_type", name="uq_itc_work_item"),
        Index("idx_itc_work_items_firm", "firm_owner_id"),
        Index("idx_itc_work_items_client", "client_gstin_id"),
        Index("idx_itc_work_items_run", "run_id"),
        Index("idx_itc_work_items_assigned", "assigned_to"),
        Index("idx_itc_work_items_status", "status"),
        Index("idx_itc_work_items_priority", "priority"),
        Index("idx_itc_work_items_due", "due_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "firm_owner_id": str(self.firm_owner_id),
            "client_gstin_id": str(self.client_gstin_id),
            "run_id": str(self.run_id),
            "record_id": self.record_id,
            "exception_type": self.exception_type,
            "status": self.status,
            "priority": self.priority,
            "system_priority": self.system_priority,
            "manual_priority": self.manual_priority,
            "priority_override_reason": self.priority_override_reason,
            "priority_changed_by": str(self.priority_changed_by) if self.priority_changed_by else None,
            "priority_changed_at": self.priority_changed_at.isoformat() if self.priority_changed_at else None,
            "category": self.category,
            "title": self.title,
            "what": self.what,
            "why": self.why,
            "next_action": self.next_action,
            "assigned_to": str(self.assigned_to) if self.assigned_to else None,
            "assigned_at": self.assigned_at.isoformat() if self.assigned_at else None,
            "assigned_by": str(self.assigned_by) if self.assigned_by else None,
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "sla_status": self.sla_status,
            "resolution_code": self.resolution_code,
            "resolution_note": self.resolution_note,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": str(self.resolved_by) if self.resolved_by else None,
            "dismissal_reason": self.dismissal_reason,
            "dismissed_at": self.dismissed_at.isoformat() if self.dismissed_at else None,
            "dismissed_by": str(self.dismissed_by) if self.dismissed_by else None,
            "reopen_reason": self.reopen_reason,
            "reopened_at": self.reopened_at.isoformat() if self.reopened_at else None,
            "reopened_by": str(self.reopened_by) if self.reopened_by else None,
            "revalidation_status": self.revalidation_status,
            "revalidation_requested_at": self.revalidation_requested_at.isoformat() if self.revalidation_requested_at else None,
            "revalidation_completed_at": self.revalidation_completed_at.isoformat() if self.revalidation_completed_at else None,
            "revalidation_result": self.revalidation_result,
            "source_version": int(self.source_version or 1),
            "carried_forward_from_id": str(self.carried_forward_from_id) if self.carried_forward_from_id else None,
            "vendor_gstin": self.vendor_gstin,
            "vendor_name": self.vendor_name,
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date.isoformat() if self.invoice_date else None,
            "taxable_value": float(self.taxable_value) if self.taxable_value is not None else 0.0,
            "igst": float(self.igst) if self.igst is not None else 0.0,
            "cgst": float(self.cgst) if self.cgst is not None else 0.0,
            "sgst": float(self.sgst) if self.sgst is not None else 0.0,
            "cess": float(self.cess) if self.cess is not None else 0.0,
            "total_tax": float(self.total_tax) if self.total_tax is not None else 0.0,
            "itc_amount_at_stake": float(self.itc_amount_at_stake) if self.itc_amount_at_stake is not None else 0.0,
            "itc_amount_at_stake_paise": int(self.itc_amount_at_stake_paise or 0),
            "is_blocking": bool(self.is_blocking),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "created_by": str(self.created_by) if self.created_by else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "updated_by": str(self.updated_by) if self.updated_by else None,
        }


# ── 5. ITCWorkItemEvent ──────────────────────────────────────────────────────

class ITCWorkItemEvent(Base):
    """Audit and activity timeline for ITC work item state transitions."""

    __tablename__ = "itc_work_item_events"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    work_item_id = Column(
        GUID(),
        ForeignKey("itc_work_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type = Column(String(50), nullable=False)
    from_status = Column(String(30), nullable=True)
    to_status = Column(String(30), nullable=True)
    actor_id = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_role = Column(String(20), nullable=True)
    actor_name = Column(String(150), nullable=True)
    note = Column(Text, nullable=True)
    metadata_payload = Column(
        "metadata",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_itc_wi_events_wi_id", "work_item_id", sa.text("created_at ASC")),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "work_item_id": str(self.work_item_id),
            "event_type": self.event_type,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "actor_id": str(self.actor_id) if self.actor_id else None,
            "actor_role": self.actor_role,
            "actor_name": self.actor_name,
            "note": self.note,
            "metadata": self.metadata_payload or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ── 6. VendorFollowupLog ─────────────────────────────────────────────────────

class VendorFollowupLog(Base):
    """Vendor communication dispatch log with portal response and work item integration."""

    __tablename__ = "vendor_followup_logs"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    client_gstin_id = Column(
        GUID(),
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
    )
    supplier_gstin = Column(Text, nullable=False)
    supplier_name = Column(Text, nullable=True)
    vendor_phone = Column(Text, nullable=True)
    vendor_email = Column(Text, nullable=True)
    channel = Column(Text, nullable=False, default="WHATSAPP")
    template_type = Column(Text, nullable=False, default="POLITE_REMINDER")
    invoices_count = Column(Integer, nullable=False, default=1)
    at_risk_itc_rupees = Column(Numeric(15, 2), nullable=False, default=Decimal("0.00"))
    status = Column(Text, nullable=False, default="SENT")
    notes = Column(Text, nullable=True)
    dispatched_by = Column(
        GUID(),
        ForeignKey("user_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    dispatched_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    work_item_id = Column(
        GUID(),
        ForeignKey("itc_work_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    message_body = Column(Text, nullable=True)
    token = Column(Text, unique=True, nullable=True)
    viewed_at = Column(DateTime(timezone=True), nullable=True)
    arn_number = Column(Text, nullable=True)
    promised_period = Column(Text, nullable=True)
    dispute_reason = Column(Text, nullable=True)
    attachment_key = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    invoices_snapshot = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    response_action = Column(Text, nullable=True)
    responded_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_vendor_followup_client_supplier", "client_gstin_id", "supplier_gstin"),
        Index("idx_vendor_followup_work_item", "work_item_id"),
        Index("idx_vendor_followup_token", "token"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "client_gstin_id": str(self.client_gstin_id),
            "supplier_gstin": self.supplier_gstin,
            "supplier_name": self.supplier_name,
            "vendor_phone": self.vendor_phone,
            "vendor_email": self.vendor_email,
            "channel": self.channel,
            "template_type": self.template_type,
            "invoices_count": int(self.invoices_count or 1),
            "at_risk_itc_rupees": float(self.at_risk_itc_rupees) if self.at_risk_itc_rupees is not None else 0.0,
            "status": self.status,
            "notes": self.notes,
            "dispatched_by": str(self.dispatched_by) if self.dispatched_by else None,
            "dispatched_at": self.dispatched_at.isoformat() if self.dispatched_at else None,
            "work_item_id": str(self.work_item_id) if self.work_item_id else None,
            "message_body": self.message_body,
            "token": self.token,
            "viewed_at": self.viewed_at.isoformat() if self.viewed_at else None,
            "arn_number": self.arn_number,
            "promised_period": self.promised_period,
            "dispute_reason": self.dispute_reason,
            "attachment_key": self.attachment_key,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "invoices_snapshot": self.invoices_snapshot,
            "response_action": self.response_action,
            "responded_at": self.responded_at.isoformat() if self.responded_at else None,
        }
