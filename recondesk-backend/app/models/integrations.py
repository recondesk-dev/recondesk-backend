"""SQLAlchemy declarative models for Canonical Batch 3B: External Integrations & Connectors.

Tables:
1. tally_bridge_keys
2. tally_ledger_masters
3. client_einvoice_credentials
4. einvoice_recon_results
5. gst_fetch_log
6. ims_action_submissions
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.models.schema_base import Base, GUID


class TallyBridgeKey(Base):
    """Firm-scoped API keys used by the local Tally Bridge agent."""

    __tablename__ = "tally_bridge_keys"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    api_key = Column(Text, nullable=False, unique=True, index=True)
    account_id = Column(
        GUID,
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_name = Column(Text, nullable=False, default="")
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_tbk_account_id", "account_id"),
        Index("idx_tbk_api_key", "api_key"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "api_key": self.api_key,
            "account_id": str(self.account_id),
            "company_name": self.company_name,
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
        }


class TallyLedgerMaster(Base):
    """Synced Tally ledger master records for vendor/customer mapping."""

    __tablename__ = "tally_ledger_masters"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    account_id = Column(
        GUID,
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_name = Column(Text, nullable=False, default="")
    name = Column(Text, nullable=False)
    parent_group = Column(Text, nullable=False, default="")
    gstin = Column(Text, nullable=False, default="")
    state = Column(Text, nullable=False, default="")
    opening_balance = Column(Numeric, nullable=True)
    closing_balance = Column(Numeric, nullable=True)
    synced_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("account_id", "company_name", "name", name="uq_tally_ledger_masters"),
        Index("idx_tlm_account_id", "account_id"),
        Index("idx_tlm_gstin", "account_id", "gstin"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "account_id": str(self.account_id),
            "company_name": self.company_name,
            "name": self.name,
            "parent_group": self.parent_group,
            "gstin": self.gstin,
            "state": self.state,
            "opening_balance": float(self.opening_balance) if self.opening_balance is not None else None,
            "closing_balance": float(self.closing_balance) if self.closing_balance is not None else None,
            "synced_at": self.synced_at.isoformat() if self.synced_at else None,
        }


class ClientEinvoiceCredential(Base):
    """Direct government portal / NIC e-invoicing API credentials per client GSTIN."""

    __tablename__ = "client_einvoice_credentials"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    client_gstin_id = Column(
        GUID,
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    einvoice_username = Column(Text, nullable=False)
    einvoice_password = Column(Text, nullable=False)
    session_token = Column(Text, nullable=True)
    session_token_expiry = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("idx_cec_client_gstin_id", "client_gstin_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "client_gstin_id": str(self.client_gstin_id),
            "einvoice_username": self.einvoice_username,
            "einvoice_password": self.einvoice_password,
            "session_token": self.session_token,
            "session_token_expiry": self.session_token_expiry.isoformat() if self.session_token_expiry else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class EinvoiceReconResult(Base):
    """Books-to-e-invoice reconciliation row results."""

    __tablename__ = "einvoice_recon_results"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    run_id = Column(
        GUID,
        ForeignKey("reconciliation_run.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    client_gstin_id = Column(
        GUID,
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period = Column(String(7), nullable=False)
    invoice_number = Column(Text, nullable=False)
    irn = Column(Text, nullable=True)
    irn_status = Column(Text, nullable=True)
    category = Column(Text, nullable=False)
    book_value = Column(Numeric, nullable=False, default=Decimal("0"))
    einvoice_value = Column(Numeric, nullable=False, default=Decimal("0"))
    details = Column(JSONB().with_variant(sa.JSON, "sqlite"), nullable=True)
    verification_source = Column(Text, nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("idx_err_client_period", "client_gstin_id", "period"),
        Index("idx_err_run_id", "run_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "run_id": str(self.run_id) if self.run_id else None,
            "client_gstin_id": str(self.client_gstin_id),
            "period": self.period,
            "invoice_number": self.invoice_number,
            "irn": self.irn,
            "irn_status": self.irn_status,
            "category": self.category,
            "book_value": float(self.book_value) if self.book_value is not None else 0.0,
            "einvoice_value": float(self.einvoice_value) if self.einvoice_value is not None else 0.0,
            "details": self.details,
            "verification_source": self.verification_source,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class GstFetchLog(Base):
    """Audit log of government portal automated return/IMS fetches."""

    __tablename__ = "gst_fetch_log"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    client_id = Column(
        GUID,
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    gstin = Column(Text, nullable=False)
    return_type = Column(Text, nullable=False)
    period = Column(Text, nullable=False)
    section = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    fetched_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_gfl_client_period", "client_id", "return_type", "period", "fetched_at"),
        Index("idx_gfl_gstin_period", "gstin", "return_type", "period", "fetched_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "client_id": str(self.client_id),
            "gstin": self.gstin,
            "return_type": self.return_type,
            "period": self.period,
            "section": self.section,
            "status": self.status,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "error_message": self.error_message,
        }


class ImsActionSubmission(Base):
    """Invoice Management System (IMS) writeback action persistence and idempotency tracking."""

    __tablename__ = "ims_action_submissions"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    invoice_id = Column(Text, nullable=False)
    gstin = Column(Text, nullable=False)
    period = Column(String(7), nullable=False)
    chosen_action = Column(Text, nullable=False)
    recommended_action = Column(Text, nullable=True)
    submit_mode = Column(Text, nullable=False, default="confirm_recommendation")
    status = Column(Text, nullable=False, default="pending")
    reference_id = Column(Text, nullable=True)
    transaction_id = Column(Text, nullable=True)
    status_cd = Column(Text, nullable=True)
    error_code = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    raw_poll = Column(JSONB().with_variant(sa.JSON, "sqlite"), nullable=True)
    run_id = Column(
        GUID,
        ForeignKey("reconciliation_run.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("invoice_id", "period", "gstin", name="uq_ias_key"),
        Index("idx_ias_gstin_period", "gstin", "period", "status"),
        Index("idx_ias_reference", "reference_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "invoice_id": self.invoice_id,
            "gstin": self.gstin,
            "period": self.period,
            "chosen_action": self.chosen_action,
            "recommended_action": self.recommended_action,
            "submit_mode": self.submit_mode,
            "status": self.status,
            "reference_id": self.reference_id,
            "transaction_id": self.transaction_id,
            "status_cd": self.status_cd,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "raw_poll": self.raw_poll,
            "run_id": str(self.run_id) if self.run_id else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
