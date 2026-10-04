"""SQLAlchemy declarative models for Batch 4A: Subscriptions, Payments & Credit Accounting.

Tables:
1. payments
2. run_credits
3. idempotency_keys
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
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.models.schema_base import Base, GUID


class Payment(Base):
    """Payment transactions for subscription plans and run credits."""

    __tablename__ = "payments"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    firm_owner_id = Column(
        GUID,
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id = Column(
        GUID,
        ForeignKey("reconciliation_run.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    razorpay_order_id = Column(Text, nullable=True, index=True)
    razorpay_payment_id = Column(Text, nullable=True)
    amount_paise = Column(BigInteger, nullable=False)
    status = Column(Text, nullable=False, default="created", index=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    plan = Column(Text, nullable=True)
    runs_purchased = Column(Integer, nullable=True)
    base_amount_paise = Column(BigInteger, nullable=True)
    gst_paise = Column(BigInteger, nullable=True)
    total_amount_paise = Column(BigInteger, nullable=True)
    customer_gstin = Column(Text, nullable=True)
    customer_trade_name = Column(Text, nullable=True)
    customer_city = Column(Text, nullable=True)
    customer_state_code = Column(Text, nullable=True)
    tax_type = Column(Text, nullable=True, default="intra")
    cgst_paise = Column(Integer, nullable=True, default=0)
    sgst_paise = Column(Integer, nullable=True, default=0)
    igst_paise = Column(Integer, nullable=True, default=0)

    def to_dict(self, *, redact_sensitive: bool = True) -> dict[str, Any]:
        """Convert Payment record to dictionary with optional payment-ID redaction."""
        order_id = self.razorpay_order_id
        payment_id = self.razorpay_payment_id
        if redact_sensitive and payment_id:
            payment_id = f"{payment_id[:6]}***REDACTED***" if len(payment_id) > 6 else "***REDACTED***"

        return {
            "id": str(self.id),
            "firm_owner_id": str(self.firm_owner_id) if self.firm_owner_id else None,
            "run_id": str(self.run_id) if self.run_id else None,
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "amount_paise": int(self.amount_paise) if self.amount_paise is not None else 0,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "plan": self.plan,
            "runs_purchased": self.runs_purchased,
            "base_amount_paise": int(self.base_amount_paise) if self.base_amount_paise is not None else None,
            "gst_paise": int(self.gst_paise) if self.gst_paise is not None else None,
            "total_amount_paise": int(self.total_amount_paise) if self.total_amount_paise is not None else None,
            "customer_gstin": self.customer_gstin,
            "customer_trade_name": self.customer_trade_name,
            "customer_city": self.customer_city,
            "customer_state_code": self.customer_state_code,
            "tax_type": self.tax_type,
            "cgst_paise": self.cgst_paise,
            "sgst_paise": self.sgst_paise,
            "igst_paise": self.igst_paise,
        }


class RunCredit(Base):
    """Purchased reconciliation run batches consumed FIFO by expires_at."""

    __tablename__ = "run_credits"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    firm_owner_id = Column(
        GUID,
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payment_id = Column(
        GUID,
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    plan = Column(Text, nullable=False)
    runs_purchased = Column(Integer, nullable=False)
    runs_remaining = Column(Integer, nullable=False)
    purchased_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("idx_run_credits_firm_expiry", "firm_owner_id", "expires_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "firm_owner_id": str(self.firm_owner_id) if self.firm_owner_id else None,
            "payment_id": str(self.payment_id) if self.payment_id else None,
            "plan": self.plan,
            "runs_purchased": self.runs_purchased,
            "runs_remaining": self.runs_remaining,
            "purchased_at": self.purchased_at.isoformat() if self.purchased_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class IdempotencyKey(Base):
    """Server mutation idempotency cache."""

    __tablename__ = "idempotency_keys"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    idempotency_key = Column(String(300), nullable=False)
    user_id = Column(String(64), nullable=False)
    response = Column(JSONB().with_variant(sa.JSON, "sqlite"), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("idempotency_key", "user_id", name="uq_idempotency_key_user"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "idempotency_key": self.idempotency_key,
            "user_id": self.user_id,
            "response": self.response,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
