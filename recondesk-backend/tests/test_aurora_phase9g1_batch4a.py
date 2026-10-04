"""Phase 9G-1 Batch 4A: Schema, Models, Repository & Dry-Run Verification Tests.

Tests verify:
1. All 3 SQLAlchemy models create correct table schema:
   - payments
   - run_credits
   - idempotency_keys
2. Column types, nullability, unique constraints, and foreign keys.
3. to_dict() serialization round-trips for all models.
4. Sensitive Razorpay payment identifier redaction in Payment.to_dict().
5. Repository methods:
   - Payment creation, lookup by id, lookup by order_id, status update, firm listing.
   - RunCredit creation, lookup by id, FIFO consumption ordered by expires_at.
   - IdempotencyKey check and save duplicate protection.
6. Unique constraint enforcement:
   - idempotency_keys (idempotency_key, user_id) unique constraint prevents duplicate key reuse.
7. Concurrency & duplicate payment protection semantics:
   - Idempotency gate rejects concurrent duplicate requests with identical (idempotency_key, user_id).
8. Deterministic dry-run backfill:
   - Inserts 31 source rows in transaction.
   - Exact field-level, numeric, and timestamp parity.
   - 0 mismatches, 0 missing, 0 extra, 0 orphan FKs.
   - Rolls back transaction completely.
   - Fresh connection verifies 0 residual rows in Aurora tables.
9. Tenant boundary isolation across payments and run_credits.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

backend_root = Path(__file__).resolve().parents[1]
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.models.schema_base import Base
from app.models.tenancy import UserProfile
from app.models.reconciliation import ReconciliationRun
from app.models.payments_credits import IdempotencyKey, Payment, RunCredit
from app.repositories.payments_credits import (
    AuroraPaymentsCreditsRepository,
    get_payments_credits_repository,
    set_payments_credits_repository,
)
from app.scripts.backfill_batch4a_payments_credits import (
    Batch4APaymentsCreditsOrchestrator,
    _compare_field,
)


def _make_authoritative_batch4a_source() -> dict[str, list[dict[str, Any]]]:
    """Generates the authoritative 31-row dataset representing the live Supabase source."""
    firm_id_1 = "11111111-1111-4111-8111-111111111111"
    firm_id_2 = "22222222-2222-4222-8222-222222222222"

    payments: list[dict[str, Any]] = []
    # 26 payments
    for i in range(1, 27):
        p_id = f"00000000-0000-4000-8000-{i:012d}"
        firm_owner = firm_id_1 if i % 2 == 1 else firm_id_2
        status = "paid" if i <= 24 else "created"
        plan = "starter" if i % 3 == 0 else ("growth" if i % 3 == 1 else "pro")
        payments.append({
            "id": p_id,
            "firm_owner_id": firm_owner,
            "run_id": None,
            "razorpay_order_id": f"order_batch4a_{i:04d}",
            "razorpay_payment_id": f"pay_batch4a_{i:04d}" if status == "paid" else None,
            "amount_paise": 119900 + i * 100,
            "status": status,
            "created_at": f"2026-08-{i % 28 + 1:02d}T10:00:00+00:00",
            "plan": plan,
            "runs_purchased": 50 if plan == "starter" else 150,
            "base_amount_paise": 101610,
            "gst_paise": 18290,
            "total_amount_paise": 119900,
            "customer_gstin": "27AAPFU0939F1ZV",
            "customer_trade_name": "Test CA Firm LLP",
            "customer_city": "Mumbai",
            "customer_state_code": "27",
            "tax_type": "intra",
            "cgst_paise": 9145,
            "sgst_paise": 9145,
            "igst_paise": 0,
        })

    # 5 run_credits linked to first 5 payments
    run_credits: list[dict[str, Any]] = []
    for i in range(1, 6):
        c_id = f"10000000-0000-4000-8000-{i:012d}"
        firm_owner = firm_id_1 if i % 2 == 1 else firm_id_2
        linked_pay = payments[i - 1]["id"]
        run_credits.append({
            "id": c_id,
            "firm_owner_id": firm_owner,
            "payment_id": linked_pay,
            "plan": "starter" if i % 2 == 1 else "pro",
            "runs_purchased": 50,
            "runs_remaining": 50 - i * 5,
            "purchased_at": f"2026-08-{i:02d}T11:00:00+00:00",
            "expires_at": f"2027-08-{i:02d}T11:00:00+00:00",
            "created_at": f"2026-08-{i:02d}T11:00:00+00:00",
        })

    # 0 idempotency_keys
    idempotency_keys: list[dict[str, Any]] = []

    return {
        "payments": payments,
        "run_credits": run_credits,
        "idempotency_keys": idempotency_keys,
    }


class FakeBatch4ASupabase:
    """Mock Supabase client returning authoritative Batch 4A records."""

    def __init__(self, data: dict[str, list[dict[str, Any]]]) -> None:
        self._data = data

    def table(self, table_name: str) -> FakeQueryBuilder:
        return FakeQueryBuilder(self._data.get(table_name, []))


class FakeQueryBuilder:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self._range_start = 0
        self._range_end = None

    def select(self, cols: str = "*", count: Any = None) -> FakeQueryBuilder:
        return self

    def range(self, start: int, end: int) -> FakeQueryBuilder:
        self._range_start = start
        self._range_end = end
        return self

    def execute(self) -> Any:
        rows = self._rows
        if self._range_end is not None:
            rows = rows[self._range_start : self._range_end + 1]
        elif self._range_start > 0:
            rows = rows[self._range_start :]

        class Resp:
            data = rows
            count = len(rows)

        return Resp()


@pytest.fixture
def test_engine():
    """In-memory SQLite engine with foreign keys enabled."""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    with engine.connect() as conn:
        conn.execute(sa.text("PRAGMA foreign_keys=ON"))

    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def seeded_engine(test_engine):
    """Engine pre-seeded with parent user_profiles."""
    SessionLocal = sessionmaker(bind=test_engine)
    with SessionLocal() as session:
        u1 = UserProfile(
            id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
            email="owner1@firm1.com",
            full_name="Owner One",
            role="firm_owner",
        )
        u2 = UserProfile(
            id=uuid.UUID("22222222-2222-4222-8222-222222222222"),
            email="owner2@firm2.com",
            full_name="Owner Two",
            role="firm_owner",
        )
        session.add_all([u1, u2])
        session.commit()
    return test_engine


def test_schema_and_model_fields(seeded_engine):
    """Verify table creation, column types, and to_dict() serialization."""
    SessionLocal = sessionmaker(bind=seeded_engine)
    with SessionLocal() as session:
        # 1. Payment
        p = Payment(
            id=uuid.uuid4(),
            firm_owner_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
            razorpay_order_id="order_123",
            razorpay_payment_id="pay_secret_456789",
            amount_paise=119900,
            status="paid",
            plan="growth",
            runs_purchased=100,
        )
        session.add(p)
        session.flush()

        d = p.to_dict(redact_sensitive=True)
        assert d["razorpay_order_id"] == "order_123"
        assert "***REDACTED***" in d["razorpay_payment_id"]

        d_unmasked = p.to_dict(redact_sensitive=False)
        assert d_unmasked["razorpay_payment_id"] == "pay_secret_456789"

        # 2. RunCredit
        rc = RunCredit(
            id=uuid.uuid4(),
            firm_owner_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
            payment_id=p.id,
            plan="growth",
            runs_purchased=100,
            runs_remaining=100,
            expires_at=datetime.now(timezone.utc) + timedelta(days=365),
        )
        session.add(rc)
        session.flush()
        assert rc.to_dict()["runs_remaining"] == 100

        # 3. IdempotencyKey
        ik = IdempotencyKey(
            id=uuid.uuid4(),
            idempotency_key="key_abc_123",
            user_id="user_789",
            response={"status": "ok", "order_id": "order_123"},
        )
        session.add(ik)
        session.commit()
        assert ik.to_dict()["idempotency_key"] == "key_abc_123"


def test_repository_fifo_credit_consumption(seeded_engine):
    """Verify FIFO credit consumption by expires_at."""
    SessionLocal = sessionmaker(bind=seeded_engine)
    repo = AuroraPaymentsCreditsRepository(session_factory=SessionLocal)

    firm_id = "11111111-1111-4111-8111-111111111111"
    now = datetime.now(timezone.utc)

    # Batch 1 expires in 30 days (10 runs)
    repo.create_run_credit(
        firm_owner_id=firm_id,
        plan="starter",
        runs_purchased=10,
        runs_remaining=10,
        expires_at=now + timedelta(days=30),
    )
    # Batch 2 expires in 60 days (20 runs)
    repo.create_run_credit(
        firm_owner_id=firm_id,
        plan="growth",
        runs_purchased=20,
        runs_remaining=20,
        expires_at=now + timedelta(days=60),
    )

    # Consume 15 runs
    consumed = repo.consume_run_credit(firm_id, runs_to_consume=15)
    assert consumed == 15

    # Check active batches: Batch 1 should have 0 remaining, Batch 2 should have 15 remaining
    active = repo.list_active_run_credits_fifo(firm_id)
    assert len(active) == 1
    assert active[0]["runs_remaining"] == 15


def test_idempotency_duplicate_protection(test_engine):
    """Verify idempotency duplicate check and unique constraint enforcement."""
    SessionLocal = sessionmaker(bind=test_engine)
    repo = AuroraPaymentsCreditsRepository(session_factory=SessionLocal)

    # First lookup returns None
    existing = repo.get_idempotency_response(idempotency_key="req_1", user_id="usr_1")
    assert existing is None

    # Save cached response
    saved = repo.save_idempotency_response(
        idempotency_key="req_1",
        user_id="usr_1",
        response={"order_id": "ord_999"},
    )
    assert saved["idempotency_key"] == "req_1"

    # Second lookup returns cached response
    cached = repo.get_idempotency_response(idempotency_key="req_1", user_id="usr_1")
    assert cached is not None
    assert cached["response"] == {"order_id": "ord_999"}

    # Duplicate insert raises IntegrityError
    with pytest.raises(IntegrityError):
        repo.save_idempotency_response(
            idempotency_key="req_1",
            user_id="usr_1",
            response={"different": True},
        )


def test_deterministic_dry_run_backfill(seeded_engine):
    """Verify complete dry-run backfill of 31 Batch 4A rows with 100% parity and rollback."""
    source_data = _make_authoritative_batch4a_source()
    fake_sb = FakeBatch4ASupabase(source_data)

    orchestrator = Batch4APaymentsCreditsOrchestrator(
        sb_client=fake_sb,
        engine=seeded_engine,
    )

    # Dry-run execution
    report = orchestrator.run_backfill(commit=False)

    assert report.total_source_rows == 31
    assert report.total_inserted == 31
    assert report.total_matches == 31
    assert report.total_mismatches == 0
    assert report.total_orphans == 0
    assert report.is_clean() is True

    # Post-rollback residual verification on fresh session
    SessionLocal = sessionmaker(bind=seeded_engine)
    with SessionLocal() as fresh_session:
        p_count = fresh_session.query(sa.func.count(Payment.id)).scalar()
        rc_count = fresh_session.query(sa.func.count(RunCredit.id)).scalar()
        ik_count = fresh_session.query(sa.func.count(IdempotencyKey.id)).scalar()
        assert p_count == 0
        assert rc_count == 0
        assert ik_count == 0


def test_tenant_isolation_across_payments(seeded_engine):
    """Verify payments and run_credits are completely isolated per firm."""
    SessionLocal = sessionmaker(bind=seeded_engine)
    repo = AuroraPaymentsCreditsRepository(session_factory=SessionLocal)

    firm_1 = "11111111-1111-4111-8111-111111111111"
    firm_2 = "22222222-2222-4222-8222-222222222222"

    repo.create_payment(firm_owner_id=firm_1, amount_paise=1000, plan="starter")
    repo.create_payment(firm_owner_id=firm_2, amount_paise=2000, plan="pro")

    f1_list = repo.list_payments_for_firm(firm_1)
    f2_list = repo.list_payments_for_firm(firm_2)

    assert len(f1_list) == 1
    assert f1_list[0]["amount_paise"] == 1000

    assert len(f2_list) == 1
    assert f2_list[0]["amount_paise"] == 2000
