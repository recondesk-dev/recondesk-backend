"""AWS Aurora Payments & Credits Repository for ReconDesk — Batch 4A.

Provides typed, safe SQLAlchemy 2.x data access for:
1. payments (Subscription checkout, run credit orders, Razorpay transactions, B2B tax breakup)
2. run_credits (Purchased reconciliation run batches consumed FIFO by expires_at)
3. idempotency_keys (Atomic idempotency gate for payment order and verify calls)

Architecture & Invariants:
- Designed as future PRIMARY for Batch 4A operations.
- Zero payment secret / sensitive credential exposure in logs or string representations.
- Atomic balance consumption and credit expiration tracking.
- Idempotency key duplicate protection with atomic check-and-insert.
- Full dialect compatibility: AWS Aurora PostgreSQL in production, SQLite in test suites.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import delete, desc as sa_desc, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.aurora import (
    AuroraConfigurationError,
    get_aurora_engine,
    get_aurora_session,
)
from app.models.payments_credits import IdempotencyKey, Payment, RunCredit

_log = logging.getLogger("recondesk.aurora.payments_credits")


def _parse_uuid(val: Any) -> Optional[UUID]:
    if val is None:
        return None
    if isinstance(val, UUID):
        return val
    try:
        return UUID(str(val).strip())
    except (ValueError, TypeError, AttributeError):
        return None


def _parse_dt(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo is not None else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


class AuroraPaymentsCreditsRepository:
    """Safe, typed data access layer for Batch 4A entities."""

    def __init__(self, session_factory: Optional[sessionmaker[Session]] = None) -> None:
        self._session_factory = session_factory

    def _get_session(self) -> Session:
        if self._session_factory is not None:
            return self._session_factory()
        return get_aurora_session()

    # =========================================================================
    # 1. Payments Operations
    # =========================================================================

    def create_payment(
        self,
        *,
        firm_owner_id: str,
        amount_paise: int,
        status: str = "created",
        razorpay_order_id: Optional[str] = None,
        razorpay_payment_id: Optional[str] = None,
        plan: Optional[str] = None,
        runs_purchased: Optional[int] = None,
        base_amount_paise: Optional[int] = None,
        gst_paise: Optional[int] = None,
        total_amount_paise: Optional[int] = None,
        customer_gstin: Optional[str] = None,
        customer_trade_name: Optional[str] = None,
        customer_city: Optional[str] = None,
        customer_state_code: Optional[str] = None,
        tax_type: Optional[str] = "intra",
        cgst_paise: Optional[int] = 0,
        sgst_paise: Optional[int] = 0,
        igst_paise: Optional[int] = 0,
        run_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new payment order record."""
        f_uuid = _parse_uuid(firm_owner_id)
        if not f_uuid:
            raise ValueError(f"Invalid firm_owner_id: {firm_owner_id}")
        r_uuid = _parse_uuid(run_id) if run_id else None

        with self._get_session() as session:
            payment = Payment(
                firm_owner_id=f_uuid,
                run_id=r_uuid,
                razorpay_order_id=razorpay_order_id,
                razorpay_payment_id=razorpay_payment_id,
                amount_paise=amount_paise,
                status=status,
                plan=plan,
                runs_purchased=runs_purchased,
                base_amount_paise=base_amount_paise,
                gst_paise=gst_paise,
                total_amount_paise=total_amount_paise,
                customer_gstin=customer_gstin,
                customer_trade_name=customer_trade_name,
                customer_city=customer_city,
                customer_state_code=customer_state_code,
                tax_type=tax_type,
                cgst_paise=cgst_paise or 0,
                sgst_paise=sgst_paise or 0,
                igst_paise=igst_paise or 0,
            )
            session.add(payment)
            session.commit()
            session.refresh(payment)
            return payment.to_dict(redact_sensitive=False)

    def get_payment_by_id(self, payment_id: str) -> Optional[dict[str, Any]]:
        """Retrieve payment by ID."""
        p_uuid = _parse_uuid(payment_id)
        if not p_uuid:
            return None
        with self._get_session() as session:
            p = session.get(Payment, p_uuid)
            return p.to_dict(redact_sensitive=False) if p else None

    def get_payment_by_order_id(self, order_id: str) -> Optional[dict[str, Any]]:
        """Retrieve payment by Razorpay order ID."""
        if not order_id:
            return None
        with self._get_session() as session:
            stmt = select(Payment).where(Payment.razorpay_order_id == str(order_id).strip())
            p = session.scalars(stmt).first()
            return p.to_dict(redact_sensitive=False) if p else None

    def update_payment_status(
        self,
        payment_id: str,
        *,
        status: str,
        razorpay_payment_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Update payment status and optionally record razorpay_payment_id."""
        p_uuid = _parse_uuid(payment_id)
        if not p_uuid:
            return None
        with self._get_session() as session:
            p = session.get(Payment, p_uuid)
            if not p:
                return None
            p.status = status
            if razorpay_payment_id:
                p.razorpay_payment_id = razorpay_payment_id
            session.commit()
            session.refresh(p)
            return p.to_dict(redact_sensitive=False)

    def list_payments_for_firm(
        self, firm_owner_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """List payments for a firm owner ordered by created_at DESC."""
        f_uuid = _parse_uuid(firm_owner_id)
        if not f_uuid:
            return []
        with self._get_session() as session:
            stmt = (
                select(Payment)
                .where(Payment.firm_owner_id == f_uuid)
                .order_by(sa_desc(Payment.created_at))
                .limit(limit)
            )
            rows = session.scalars(stmt).all()
            return [r.to_dict(redact_sensitive=False) for r in rows]

    def get_payment_by_payment_id(self, razorpay_payment_id: str) -> Optional[dict[str, Any]]:
        """Retrieve payment by Razorpay payment ID."""
        if not razorpay_payment_id:
            return None
        with self._get_session() as session:
            stmt = select(Payment).where(Payment.razorpay_payment_id == str(razorpay_payment_id).strip())
            p = session.scalars(stmt).first()
            return p.to_dict(redact_sensitive=False) if p else None

    def list_paid_payments(self, limit: int = 1000) -> list[dict[str, Any]]:
        """Retrieve paid payments for statutory export / reporting."""
        with self._get_session() as session:
            stmt = (
                select(Payment)
                .where(Payment.status == "paid")
                .order_by(sa_desc(Payment.created_at))
                .limit(limit)
            )
            rows = session.scalars(stmt).all()
            return [r.to_dict(redact_sensitive=False) for r in rows]

    def count_payments_today(self) -> int:
        """Count captured/paid payments created today (UTC)."""
        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        with self._get_session() as session:
            stmt = (
                select(func.count())
                .select_from(Payment)
                .where(
                    Payment.created_at >= start_of_day,
                    Payment.status.in_(["paid", "captured"]),
                )
            )
            return int(session.scalar(stmt) or 0)

    def delete_payment(self, payment_id: str) -> bool:
        """Delete payment by ID (cascading to dependent run_credits)."""
        p_uuid = _parse_uuid(payment_id)
        if not p_uuid:
            return False
        with self._get_session() as session:
            row = session.get(Payment, p_uuid)
            if not row:
                return False
            session.delete(row)
            session.commit()
            return True

    # =========================================================================
    # 2. Run Credits Operations
    # =========================================================================

    def create_run_credit(
        self,
        *,
        firm_owner_id: str,
        plan: str,
        runs_purchased: int,
        runs_remaining: int,
        expires_at: datetime | str,
        payment_id: Optional[str] = None,
        purchased_at: Optional[datetime | str] = None,
    ) -> dict[str, Any]:
        """Create a new run credit batch."""
        f_uuid = _parse_uuid(firm_owner_id)
        if not f_uuid:
            raise ValueError(f"Invalid firm_owner_id: {firm_owner_id}")
        p_uuid = _parse_uuid(payment_id) if payment_id else None
        exp_dt = _parse_dt(expires_at)
        if not exp_dt:
            raise ValueError(f"Invalid expires_at: {expires_at}")
        purch_dt = _parse_dt(purchased_at) or datetime.now(timezone.utc)

        with self._get_session() as session:
            rc = RunCredit(
                firm_owner_id=f_uuid,
                payment_id=p_uuid,
                plan=plan,
                runs_purchased=runs_purchased,
                runs_remaining=runs_remaining,
                expires_at=exp_dt,
                purchased_at=purch_dt,
            )
            session.add(rc)
            session.commit()
            session.refresh(rc)
            return rc.to_dict()

    def get_run_credit_by_id(self, credit_id: str) -> Optional[dict[str, Any]]:
        """Retrieve run credit batch by ID."""
        c_uuid = _parse_uuid(credit_id)
        if not c_uuid:
            return None
        with self._get_session() as session:
            rc = session.get(RunCredit, c_uuid)
            return rc.to_dict() if rc else None

    def list_active_run_credits_fifo(
        self, firm_owner_id: str
    ) -> list[dict[str, Any]]:
        """List unexpired run credit batches with remaining runs ordered FIFO by expires_at."""
        f_uuid = _parse_uuid(firm_owner_id)
        if not f_uuid:
            return []
        now = datetime.now(timezone.utc)
        with self._get_session() as session:
            stmt = (
                select(RunCredit)
                .where(
                    RunCredit.firm_owner_id == f_uuid,
                    RunCredit.runs_remaining > 0,
                    RunCredit.expires_at > now,
                )
                .order_by(RunCredit.expires_at.asc())
            )
            rows = session.scalars(stmt).all()
            return [r.to_dict() for r in rows]

    def consume_run_credit(
        self, firm_owner_id: str, runs_to_consume: int = 1
    ) -> int:
        """Consume runs from active credit batches in strict FIFO order by expires_at."""
        f_uuid = _parse_uuid(firm_owner_id)
        if not f_uuid or runs_to_consume <= 0:
            return 0
        now = datetime.now(timezone.utc)
        consumed = 0
        with self._get_session() as session:
            stmt = (
                select(RunCredit)
                .where(
                    RunCredit.firm_owner_id == f_uuid,
                    RunCredit.runs_remaining > 0,
                    RunCredit.expires_at > now,
                )
                .order_by(RunCredit.expires_at.asc())
                .with_for_update()
            )
            batches = session.scalars(stmt).all()
            needed = runs_to_consume
            for b in batches:
                if needed <= 0:
                    break
                available = b.runs_remaining
                take = min(available, needed)
                b.runs_remaining -= take
                needed -= take
                consumed += take
            session.commit()
            return consumed

    def forfeit_expired_credit_batches(self, firm_owner_id: str) -> tuple[int, int]:
        """Zero remaining runs on expired batches and calculate active remaining balance."""
        f_uuid = _parse_uuid(firm_owner_id)
        if not f_uuid:
            return 0, 0
        now = datetime.now(timezone.utc)
        forfeited = 0
        active_bal = 0
        with self._get_session() as session:
            stmt = select(RunCredit).where(
                RunCredit.firm_owner_id == f_uuid,
                RunCredit.runs_remaining > 0,
            ).with_for_update()
            batches = session.scalars(stmt).all()
            for b in batches:
                exp = b.expires_at
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp <= now:
                    forfeited += b.runs_remaining
                    b.runs_remaining = 0
                else:
                    active_bal += b.runs_remaining
            session.commit()
            return forfeited, active_bal

    def decrement_oldest_credit_batch(self, firm_owner_id: str) -> bool:
        """Decrement 1 run from the oldest active batch by expires_at."""
        return self.consume_run_credit(firm_owner_id, runs_to_consume=1) > 0

    def delete_run_credit(self, credit_id: str) -> bool:
        """Delete run credit batch by ID."""
        c_uuid = _parse_uuid(credit_id)
        if not c_uuid:
            return False
        with self._get_session() as session:
            row = session.get(RunCredit, c_uuid)
            if not row:
                return False
            session.delete(row)
            session.commit()
            return True

    # =========================================================================
    # 3. Idempotency Key Operations
    # =========================================================================

    def get_idempotency_response(
        self, *, idempotency_key: str, user_id: str, since: Optional[datetime] = None
    ) -> Optional[dict[str, Any]]:
        """Look up existing idempotency record."""
        k = str(idempotency_key).strip()
        u = str(user_id).strip()
        with self._get_session() as session:
            stmt = select(IdempotencyKey).where(
                IdempotencyKey.idempotency_key == k,
                IdempotencyKey.user_id == u,
            )
            if since:
                stmt = stmt.where(IdempotencyKey.created_at >= since)
            record = session.scalars(stmt).first()
            return record.to_dict() if record else None

    def save_idempotency_response(
        self,
        *,
        idempotency_key: str,
        user_id: str,
        response: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically persist an idempotency key and cached response."""
        k = str(idempotency_key).strip()
        u = str(user_id).strip()
        with self._get_session() as session:
            rec = IdempotencyKey(
                idempotency_key=k,
                user_id=u,
                response=response,
            )
            session.add(rec)
            session.commit()
            session.refresh(rec)
            return rec.to_dict()

    def delete_idempotency_key(self, record_id: str) -> bool:
        """Delete idempotency record by ID."""
        r_uuid = _parse_uuid(record_id)
        if not r_uuid:
            return False
        with self._get_session() as session:
            row = session.get(IdempotencyKey, r_uuid)
            if not row:
                return False
            session.delete(row)
            session.commit()
            return True


_global_payments_repo: Optional[AuroraPaymentsCreditsRepository] = None


def get_payments_credits_repository() -> AuroraPaymentsCreditsRepository:
    """Return the global payments & credits repository singleton."""
    global _global_payments_repo
    if _global_payments_repo is None:
        _global_payments_repo = AuroraPaymentsCreditsRepository()
    return _global_payments_repo


def set_payments_credits_repository(
    repo: Optional[AuroraPaymentsCreditsRepository],
) -> None:
    """Inject or reset payments & credits repository instance (used in tests)."""
    global _global_payments_repo
    _global_payments_repo = repo
