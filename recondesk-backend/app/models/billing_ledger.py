"""SQLAlchemy declarative models for Batch 4B: E-Invoicing & B2B Billing Ledger.

Tables:
1. billing_company_profiles
2. billing_customers
3. billing_items
4. billing_invoices
5. billing_invoice_line_items
6. billing_credit_debit_notes
7. billing_cdn_line_items
8. billing_irp_submission_log
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy import (
    BigInteger,
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
)
from sqlalchemy.dialects.postgresql import JSONB

from app.models.schema_base import Base, GUID


class BillingCompanyProfile(Base):
    """Seller company profile for billing, GST details, bank coordinates, and sequence counters."""

    __tablename__ = "billing_company_profiles"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    client_gstin_id = Column(
        GUID,
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    legal_name = Column(Text, nullable=False)
    trade_name = Column(Text, nullable=True)
    address_line1 = Column(Text, nullable=False, default="")
    address_line2 = Column(Text, nullable=True)
    city = Column(Text, nullable=False, default="")
    state = Column(Text, nullable=False, default="")
    state_code = Column(String(2), nullable=False)
    pincode = Column(Text, nullable=False, default="")
    gstin = Column(Text, nullable=False)
    pan = Column(Text, nullable=True)
    bank_account_number = Column(Text, nullable=True)
    bank_ifsc = Column(Text, nullable=True)
    bank_name = Column(Text, nullable=True)
    invoice_number_prefix = Column(Text, nullable=False, default="")
    invoice_number_next_seq = Column(BigInteger, nullable=False, default=1)
    financial_year_reset = Column(Boolean, nullable=False, default=True)
    cdn_number_prefix = Column(Text, nullable=False, default="CRN/")
    cdn_number_next_seq = Column(BigInteger, nullable=False, default=1)
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

    def to_dict(self, *, redact_sensitive: bool = True) -> dict[str, Any]:
        """Convert BillingCompanyProfile to dictionary with optional bank redaction."""
        acct = self.bank_account_number
        if redact_sensitive and acct:
            acct = f"***REDACTED{acct[-4:]}***" if len(acct) >= 4 else "***REDACTED***"

        return {
            "id": str(self.id),
            "client_gstin_id": str(self.client_gstin_id),
            "legal_name": self.legal_name,
            "trade_name": self.trade_name,
            "address_line1": self.address_line1,
            "address_line2": self.address_line2,
            "city": self.city,
            "state": self.state,
            "state_code": self.state_code,
            "pincode": self.pincode,
            "gstin": self.gstin,
            "pan": self.pan,
            "bank_account_number": acct,
            "bank_ifsc": self.bank_ifsc,
            "bank_name": self.bank_name,
            "invoice_number_prefix": self.invoice_number_prefix,
            "invoice_number_next_seq": int(self.invoice_number_next_seq),
            "financial_year_reset": bool(self.financial_year_reset),
            "cdn_number_prefix": self.cdn_number_prefix,
            "cdn_number_next_seq": int(self.cdn_number_next_seq),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class BillingCustomer(Base):
    """Customer master records for B2B/B2C invoicing under client GSTIN."""

    __tablename__ = "billing_customers"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    client_gstin_id = Column(
        GUID,
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(Text, nullable=False)
    gstin = Column(Text, nullable=True)
    address_line1 = Column(Text, nullable=False, default="")
    address_line2 = Column(Text, nullable=True)
    city = Column(Text, nullable=False, default="")
    state = Column(Text, nullable=False, default="")
    state_code = Column(String(2), nullable=False)
    pincode = Column(Text, nullable=False, default="")
    is_b2b = Column(Boolean, nullable=False, default=True)
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
            "id": str(self.id),
            "client_gstin_id": str(self.client_gstin_id),
            "name": self.name,
            "gstin": self.gstin,
            "address_line1": self.address_line1,
            "address_line2": self.address_line2,
            "city": self.city,
            "state": self.state,
            "state_code": self.state_code,
            "pincode": self.pincode,
            "is_b2b": bool(self.is_b2b),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class BillingItem(Base):
    """Catalog of goods and services with HSN/SAC codes, rates, and default tax percentages."""

    __tablename__ = "billing_items"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    client_gstin_id = Column(
        GUID,
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(Text, nullable=False)
    hsn_or_sac_code = Column(Text, nullable=False)
    unit = Column(Text, nullable=False, default="NOS")
    default_rate = Column(BigInteger, nullable=False, default=0)
    default_tax_rate_percent = Column(Numeric(5, 2), nullable=False, default=18.00)
    item_type = Column(Text, nullable=False, default="goods")
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
            "id": str(self.id),
            "client_gstin_id": str(self.client_gstin_id),
            "name": self.name,
            "hsn_or_sac_code": self.hsn_or_sac_code,
            "unit": self.unit,
            "default_rate": int(self.default_rate),
            "default_tax_rate_percent": float(self.default_tax_rate_percent) if self.default_tax_rate_percent is not None else 0.0,
            "item_type": self.item_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class BillingInvoice(Base):
    """Sales invoices, tax breakdowns, and Government IRP registration details."""

    __tablename__ = "billing_invoices"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    client_gstin_id = Column(
        GUID,
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_profile_id = Column(
        GUID,
        ForeignKey("billing_company_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    customer_id = Column(
        GUID,
        ForeignKey("billing_customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    invoice_number = Column(Text, nullable=False)
    invoice_date = Column(Date, nullable=False, default=date.today)
    due_date = Column(Date, nullable=True)
    place_of_supply = Column(String(2), nullable=False)
    is_interstate = Column(Boolean, nullable=False, default=False)
    subtotal_paise = Column(BigInteger, nullable=False, default=0)
    total_tax_paise = Column(BigInteger, nullable=False, default=0)
    total_paise = Column(BigInteger, nullable=False, default=0)
    status = Column(Text, nullable=False, default="draft")
    irn = Column(Text, nullable=True, index=True)
    notes = Column(Text, nullable=True)
    irn_ack_number = Column(Text, nullable=True)
    irn_ack_date = Column(DateTime(timezone=True), nullable=True)
    irn_qr_code = Column(Text, nullable=True)
    irn_signed_json = Column(JSONB().with_variant(sa.JSON, "sqlite"), nullable=True)
    irp_status = Column(Text, nullable=False, default="not_submitted", index=True)
    irp_error_detail = Column(Text, nullable=True)
    irp_environment = Column(Text, nullable=False, default="test")
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
        UniqueConstraint(
            "client_gstin_id",
            "invoice_number",
            name="uq_billing_invoices_client_inv_num",
        ),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "client_gstin_id": str(self.client_gstin_id),
            "company_profile_id": str(self.company_profile_id),
            "customer_id": str(self.customer_id),
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date.isoformat() if self.invoice_date else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "place_of_supply": self.place_of_supply,
            "is_interstate": bool(self.is_interstate),
            "subtotal_paise": int(self.subtotal_paise),
            "total_tax_paise": int(self.total_tax_paise),
            "total_paise": int(self.total_paise),
            "status": self.status,
            "irn": self.irn,
            "notes": self.notes,
            "irn_ack_number": self.irn_ack_number,
            "irn_ack_date": self.irn_ack_date.isoformat() if self.irn_ack_date else None,
            "irn_qr_code": self.irn_qr_code,
            "irn_signed_json": self.irn_signed_json,
            "irp_status": self.irp_status,
            "irp_error_detail": self.irp_error_detail,
            "irp_environment": self.irp_environment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class BillingInvoiceLineItem(Base):
    """Itemized line entries for invoices with quantity, rates, and granular GST tax values."""

    __tablename__ = "billing_invoice_line_items"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    invoice_id = Column(
        GUID,
        ForeignKey("billing_invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id = Column(
        GUID,
        ForeignKey("billing_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    description = Column(Text, nullable=False)
    hsn_or_sac_code = Column(Text, nullable=False)
    quantity = Column(Numeric(12, 4), nullable=False, default=1.0000)
    unit = Column(Text, nullable=False, default="NOS")
    rate_paise = Column(BigInteger, nullable=False, default=0)
    discount_percent = Column(Numeric(5, 2), nullable=True, default=0.00)
    taxable_value_paise = Column(BigInteger, nullable=False, default=0)
    cgst_rate_percent = Column(Numeric(5, 2), nullable=True, default=0.00)
    cgst_paise = Column(BigInteger, nullable=True, default=0)
    sgst_rate_percent = Column(Numeric(5, 2), nullable=True, default=0.00)
    sgst_paise = Column(BigInteger, nullable=True, default=0)
    igst_rate_percent = Column(Numeric(5, 2), nullable=True, default=0.00)
    igst_paise = Column(BigInteger, nullable=True, default=0)
    cess_paise = Column(BigInteger, nullable=True, default=0)
    line_total_paise = Column(BigInteger, nullable=False, default=0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "invoice_id": str(self.invoice_id),
            "item_id": str(self.item_id) if self.item_id else None,
            "description": self.description,
            "hsn_or_sac_code": self.hsn_or_sac_code,
            "quantity": float(self.quantity) if self.quantity is not None else 1.0,
            "unit": self.unit,
            "rate_paise": int(self.rate_paise),
            "discount_percent": float(self.discount_percent) if self.discount_percent is not None else 0.0,
            "taxable_value_paise": int(self.taxable_value_paise),
            "cgst_rate_percent": float(self.cgst_rate_percent) if self.cgst_rate_percent is not None else 0.0,
            "cgst_paise": int(self.cgst_paise) if self.cgst_paise is not None else 0,
            "sgst_rate_percent": float(self.sgst_rate_percent) if self.sgst_rate_percent is not None else 0.0,
            "sgst_paise": int(self.sgst_paise) if self.sgst_paise is not None else 0,
            "igst_rate_percent": float(self.igst_rate_percent) if self.igst_rate_percent is not None else 0.0,
            "igst_paise": int(self.igst_paise) if self.igst_paise is not None else 0,
            "cess_paise": int(self.cess_paise) if self.cess_paise is not None else 0,
            "line_total_paise": int(self.line_total_paise),
        }


class BillingCreditDebitNote(Base):
    """Credit and debit notes linked to original e-invoices with statutory reasons and IRP registration."""

    __tablename__ = "billing_credit_debit_notes"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    client_gstin_id = Column(
        GUID,
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_invoice_id = Column(
        GUID,
        ForeignKey("billing_invoices.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    note_type = Column(Text, nullable=False, default="credit")
    note_number = Column(Text, nullable=False)
    note_date = Column(Date, nullable=False, default=date.today)
    reason = Column(Text, nullable=False, default="1-Sales Return")
    reason_detail = Column(Text, nullable=True)
    subtotal_paise = Column(BigInteger, nullable=False, default=0)
    total_tax_paise = Column(BigInteger, nullable=False, default=0)
    total_paise = Column(BigInteger, nullable=False, default=0)
    status = Column(Text, nullable=False, default="draft")
    irn = Column(Text, nullable=True, index=True)
    irn_ack_number = Column(Text, nullable=True)
    irn_ack_date = Column(DateTime(timezone=True), nullable=True)
    irn_qr_code = Column(Text, nullable=True)
    irn_signed_json = Column(JSONB().with_variant(sa.JSON, "sqlite"), nullable=True)
    irp_status = Column(Text, nullable=False, default="not_submitted", index=True)
    irp_error_detail = Column(Text, nullable=True)
    irp_environment = Column(Text, nullable=False, default="test")
    notes = Column(Text, nullable=True)
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
        UniqueConstraint(
            "client_gstin_id",
            "note_number",
            name="uq_billing_cdn_client_num",
        ),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "client_gstin_id": str(self.client_gstin_id),
            "original_invoice_id": str(self.original_invoice_id),
            "note_type": self.note_type,
            "note_number": self.note_number,
            "note_date": self.note_date.isoformat() if self.note_date else None,
            "reason": self.reason,
            "reason_detail": self.reason_detail,
            "subtotal_paise": int(self.subtotal_paise),
            "total_tax_paise": int(self.total_tax_paise),
            "total_paise": int(self.total_paise),
            "status": self.status,
            "irn": self.irn,
            "irn_ack_number": self.irn_ack_number,
            "irn_ack_date": self.irn_ack_date.isoformat() if self.irn_ack_date else None,
            "irn_qr_code": self.irn_qr_code,
            "irn_signed_json": self.irn_signed_json,
            "irp_status": self.irp_status,
            "irp_error_detail": self.irp_error_detail,
            "irp_environment": self.irp_environment,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class BillingCdnLineItem(Base):
    """Itemized line entries for credit and debit notes with taxes and line totals."""

    __tablename__ = "billing_cdn_line_items"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    cdn_id = Column(
        GUID,
        ForeignKey("billing_credit_debit_notes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id = Column(
        GUID,
        ForeignKey("billing_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    description = Column(Text, nullable=False)
    hsn_or_sac_code = Column(Text, nullable=False)
    quantity = Column(Numeric(12, 4), nullable=False, default=1.0000)
    unit = Column(Text, nullable=False, default="NOS")
    rate_paise = Column(BigInteger, nullable=False, default=0)
    discount_percent = Column(Numeric(5, 2), nullable=True, default=0.00)
    taxable_value_paise = Column(BigInteger, nullable=False, default=0)
    tax_rate_percent = Column(Numeric(5, 2), nullable=False, default=18.00)
    cgst_paise = Column(BigInteger, nullable=True, default=0)
    sgst_paise = Column(BigInteger, nullable=True, default=0)
    igst_paise = Column(BigInteger, nullable=True, default=0)
    cess_paise = Column(BigInteger, nullable=True, default=0)
    line_total_paise = Column(BigInteger, nullable=False, default=0)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "cdn_id": str(self.cdn_id),
            "item_id": str(self.item_id) if self.item_id else None,
            "description": self.description,
            "hsn_or_sac_code": self.hsn_or_sac_code,
            "quantity": float(self.quantity) if self.quantity is not None else 1.0,
            "unit": self.unit,
            "rate_paise": int(self.rate_paise),
            "discount_percent": float(self.discount_percent) if self.discount_percent is not None else 0.0,
            "taxable_value_paise": int(self.taxable_value_paise),
            "tax_rate_percent": float(self.tax_rate_percent) if self.tax_rate_percent is not None else 0.0,
            "cgst_paise": int(self.cgst_paise) if self.cgst_paise is not None else 0,
            "sgst_paise": int(self.sgst_paise) if self.sgst_paise is not None else 0,
            "igst_paise": int(self.igst_paise) if self.igst_paise is not None else 0,
            "cess_paise": int(self.cess_paise) if self.cess_paise is not None else 0,
            "line_total_paise": int(self.line_total_paise),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class BillingIrpSubmissionLog(Base):
    """Immutable audit log of all IRP submission requests, responses, and network payloads."""

    __tablename__ = "billing_irp_submission_log"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    invoice_id = Column(
        GUID,
        ForeignKey("billing_invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_gstin_id = Column(
        GUID,
        ForeignKey("client_gstins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempted_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    environment = Column(Text, nullable=False, default="test")
    request_payload = Column(JSONB().with_variant(sa.JSON, "sqlite"), nullable=True)
    response_status = Column(Text, nullable=False)
    response_body = Column(JSONB().with_variant(sa.JSON, "sqlite"), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "invoice_id": str(self.invoice_id),
            "client_gstin_id": str(self.client_gstin_id),
            "attempted_at": self.attempted_at.isoformat() if self.attempted_at else None,
            "environment": self.environment,
            "request_payload": self.request_payload,
            "response_status": self.response_status,
            "response_body": self.response_body,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
