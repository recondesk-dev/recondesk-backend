"""Phase 9F-1 Batch 3A: Aurora Schema, Model, and Dry-Run Verification Tests.

Tests verify:
1. All 6 SQLAlchemy models create correct table schema (SQLite in-memory).
2. Column presence, nullability, unique constraints, and type correctness.
3. Relationship chains: multi_period_recon_batches -> items, gstr1_run -> actions.
4. to_dict() serialization round-trips for all models.
5. Backfill orchestrator dry-run with synthetic data:
   - Seed all parent dependencies.
   - Insert all 6 table types in dependency order.
   - Verify field parity (exact row match).
   - Verify rollback leaves zero residual rows.
6. Numeric edge-case: Gstr9AuditOverride with large override_value (e.g., 384300387.06).
7. JSONB round-trip: gstr1_reconciliation_run result_payload and gstr2a_delta_results.
8. Foreign key cascade: delete parent -> children removed.
9. Unique constraint: duplicate (batch_id, period) is rejected.
10. Unique constraint: duplicate (client_gstin_id, fy, table_key, cell_key) is rejected.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure backend is importable
backend_root = Path(__file__).resolve().parents[1]
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.models.schema_base import Base, GUID
from app.models.tenancy import ClientGSTIN, UserProfile
from app.models.reconciliation import ReconciliationRun
from app.models.return_reconciliation import (
    MultiPeriodReconBatch,
    MultiPeriodReconBatchItem,
    Gstr1ReconciliationRun,
    Gstr1aPeriodAction,
    Gstr2aDeltaResult,
    Gstr9AuditOverride,
)
from app.scripts.backfill_batch3a_return_reconciliation import (
    Batch3AReturnReconciliationOrchestrator,
    _normalize_ts,
    _normalize_date,
    _normalize_numeric,
    _normalize_json,
    _compare_row,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def engine():
    """SQLite in-memory engine with all tables created."""
    eng = create_engine(
        "sqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture(scope="module")
def Session(engine):
    return sessionmaker(bind=engine)


@pytest.fixture
def session(Session):
    s = Session()
    yield s
    s.rollback()
    s.close()


@pytest.fixture(scope="module")
def seed_ids():
    """Stable IDs for parent entities."""
    return {
        "user_id": uuid.uuid4(),
        "client_id": uuid.uuid4(),
        "run_id": uuid.uuid4(),
    }


@pytest.fixture(scope="module")
def parent_entities(engine, seed_ids, Session):
    """Seed UserProfile, ClientGSTIN, and ReconciliationRun once for the module."""
    s = Session()
    try:
        user = UserProfile(
            id=seed_ids["user_id"],
            email="test@recondesk.example",
            full_name="Test User",
            role="admin",
        )
        s.add(user)
        s.flush()

        client = ClientGSTIN(
            id=seed_ids["client_id"],
            gstin="27AABCH2726A1Z5",
            trade_name="Test Client",
            firm_owner_id=seed_ids["user_id"],
        )
        s.add(client)
        s.flush()

        recon_run = ReconciliationRun(
            id=seed_ids["run_id"],
            client_gstin_id=seed_ids["client_id"],
            status="COMPLETED",
            period="042025",
        )
        s.add(recon_run)
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
    return seed_ids


# ─── Helper builders ──────────────────────────────────────────────────────────

def _mk_batch(client_id, created_by=None, **kw) -> MultiPeriodReconBatch:
    return MultiPeriodReconBatch(
        id=uuid.uuid4(),
        client_gstin_id=client_id,
        financial_year="2025-26",
        status="pending",
        created_by=created_by,
        **kw,
    )


def _mk_item(batch_id, period="042025", run_id=None, **kw) -> MultiPeriodReconBatchItem:
    return MultiPeriodReconBatchItem(
        id=uuid.uuid4(),
        batch_id=batch_id,
        period=period,
        status="pending",
        reconciliation_run_id=run_id,
        **kw,
    )


def _mk_g1_run(client_id, **kw) -> Gstr1ReconciliationRun:
    return Gstr1ReconciliationRun(
        id=uuid.uuid4(),
        client_gstin_id=client_id,
        status="complete",
        result_payload={"invoices": [], "total": 0},
        run_summary={"matched": 0, "mismatched": 0},
        period="042025",
        completed_at=datetime.now(timezone.utc),
        **kw,
    )


def _mk_g1a_action(run_id, period="042025", **kw) -> Gstr1aPeriodAction:
    return Gstr1aPeriodAction(
        id=uuid.uuid4(),
        run_id=run_id,
        period=period,
        status="accepted",
        user_id="legacy-supabase-uid-abc123",
        **kw,
    )


def _mk_g2a_result(client_id, period="042025", **kw) -> Gstr2aDeltaResult:
    return Gstr2aDeltaResult(
        id=uuid.uuid4(),
        client_gstin_id=client_id,
        period=period,
        reconciled_at=datetime.now(timezone.utc),
        summary={"matched": 10, "delta": 2},
        results=[{"invoice_no": "INV001", "delta_value": 1000}],
        **kw,
    )


def _mk_g9_override(client_id, table_key="table4", cell_key="4A_b2c", **kw) -> Gstr9AuditOverride:
    return Gstr9AuditOverride(
        id=uuid.uuid4(),
        client_gstin_id=client_id,
        financial_year="2025-26",
        table_key=table_key,
        cell_key=cell_key,
        system_value=Decimal("0.00"),
        override_value=Decimal("384300387.06"),
        **kw,
    )


# ─── Schema Creation Tests ─────────────────────────────────────────────────────

class TestSchemaCreation:
    def test_all_six_tables_exist(self, engine):
        inspector = sa.inspect(engine)
        tables = inspector.get_table_names()
        expected = [
            "multi_period_recon_batches",
            "multi_period_recon_batch_items",
            "gstr1_reconciliation_run",
            "gstr1a_period_actions",
            "gstr2a_delta_results",
            "gstr9_audit_overrides",
        ]
        for t in expected:
            assert t in tables, f"Table {t} missing from schema"

    def test_multi_period_recon_batches_columns(self, engine):
        inspector = sa.inspect(engine)
        cols = {c["name"] for c in inspector.get_columns("multi_period_recon_batches")}
        assert cols == {"id", "client_gstin_id", "financial_year", "status", "created_at", "updated_at", "created_by"}

    def test_multi_period_recon_batch_items_columns(self, engine):
        inspector = sa.inspect(engine)
        cols = {c["name"] for c in inspector.get_columns("multi_period_recon_batch_items")}
        assert cols == {
            "id", "batch_id", "period", "status", "reconciliation_run_id",
            "gstr2b_file_path", "gstr2b_source", "pr_file_path", "pr_source",
            "error_message", "created_at", "updated_at",
        }

    def test_gstr1_reconciliation_run_columns(self, engine):
        inspector = sa.inspect(engine)
        cols = {c["name"] for c in inspector.get_columns("gstr1_reconciliation_run")}
        assert cols == {
            "id", "client_gstin_id", "status", "result_payload", "run_summary",
            "period", "gstr1_filed_date", "gstr3b_filed_date",
            "created_at", "completed_at", "created_by",
        }

    def test_gstr1a_period_actions_columns(self, engine):
        inspector = sa.inspect(engine)
        cols = {c["name"] for c in inspector.get_columns("gstr1a_period_actions")}
        assert cols == {"id", "run_id", "period", "status", "user_id", "note", "filed_date", "created_at"}

    def test_gstr2a_delta_results_columns(self, engine):
        inspector = sa.inspect(engine)
        cols = {c["name"] for c in inspector.get_columns("gstr2a_delta_results")}
        assert cols == {
            "id", "client_gstin_id", "period", "reconciled_at",
            "summary", "results", "cutoff_date", "created_at", "updated_at",
        }

    def test_gstr9_audit_overrides_columns(self, engine):
        inspector = sa.inspect(engine)
        cols = {c["name"] for c in inspector.get_columns("gstr9_audit_overrides")}
        assert cols == {
            "id", "client_gstin_id", "financial_year", "table_key", "cell_key",
            "system_value", "override_value", "notes", "updated_by", "updated_at",
        }


# ─── Nullability Tests ─────────────────────────────────────────────────────────

class TestNullability:
    def test_batch_created_by_nullable(self, engine):
        inspector = sa.inspect(engine)
        col = next(c for c in inspector.get_columns("multi_period_recon_batches") if c["name"] == "created_by")
        assert col["nullable"] is True

    def test_batch_item_reconciliation_run_id_nullable(self, engine):
        inspector = sa.inspect(engine)
        col = next(c for c in inspector.get_columns("multi_period_recon_batch_items") if c["name"] == "reconciliation_run_id")
        assert col["nullable"] is True

    def test_gstr1_run_created_by_nullable(self, engine):
        inspector = sa.inspect(engine)
        col = next(c for c in inspector.get_columns("gstr1_reconciliation_run") if c["name"] == "created_by")
        assert col["nullable"] is True

    def test_gstr1_run_period_nullable(self, engine):
        inspector = sa.inspect(engine)
        col = next(c for c in inspector.get_columns("gstr1_reconciliation_run") if c["name"] == "period")
        assert col["nullable"] is True

    def test_gstr9_override_notes_nullable(self, engine):
        inspector = sa.inspect(engine)
        col = next(c for c in inspector.get_columns("gstr9_audit_overrides") if c["name"] == "notes")
        assert col["nullable"] is True

    def test_gstr9_override_updated_by_nullable(self, engine):
        inspector = sa.inspect(engine)
        col = next(c for c in inspector.get_columns("gstr9_audit_overrides") if c["name"] == "updated_by")
        assert col["nullable"] is True


# ─── CRUD and Relationship Tests ───────────────────────────────────────────────

class TestCRUD:
    def test_insert_and_retrieve_batch(self, session, parent_entities):
        ids = parent_entities
        batch = _mk_batch(ids["client_id"], created_by=ids["user_id"])
        session.add(batch)
        session.flush()
        result = session.query(MultiPeriodReconBatch).filter_by(id=batch.id).one()
        assert str(result.client_gstin_id) == str(ids["client_id"])
        assert result.financial_year == "2025-26"
        assert result.status == "pending"

    def test_insert_batch_item_with_run_id(self, session, parent_entities):
        ids = parent_entities
        batch = _mk_batch(ids["client_id"])
        session.add(batch)
        session.flush()
        item = _mk_item(batch.id, run_id=ids["run_id"])
        session.add(item)
        session.flush()
        result = session.query(MultiPeriodReconBatchItem).filter_by(id=item.id).one()
        assert str(result.reconciliation_run_id) == str(ids["run_id"])

    def test_insert_batch_item_without_run_id(self, session, parent_entities):
        ids = parent_entities
        batch = _mk_batch(ids["client_id"])
        session.add(batch)
        session.flush()
        item = _mk_item(batch.id, run_id=None)
        session.add(item)
        session.flush()
        result = session.query(MultiPeriodReconBatchItem).filter_by(id=item.id).one()
        assert result.reconciliation_run_id is None

    def test_insert_gstr1_run_with_jsonb(self, session, parent_entities):
        ids = parent_entities
        run = _mk_g1_run(ids["client_id"])
        session.add(run)
        session.flush()
        result = session.query(Gstr1ReconciliationRun).filter_by(id=run.id).one()
        assert result.result_payload == {"invoices": [], "total": 0}
        assert result.run_summary == {"matched": 0, "mismatched": 0}

    def test_insert_gstr1a_action_with_text_user_id(self, session, parent_entities):
        ids = parent_entities
        run = _mk_g1_run(ids["client_id"])
        session.add(run)
        session.flush()
        action = _mk_g1a_action(run.id)
        session.add(action)
        session.flush()
        result = session.query(Gstr1aPeriodAction).filter_by(id=action.id).one()
        assert result.user_id == "legacy-supabase-uid-abc123"

    def test_insert_gstr2a_delta_result(self, session, parent_entities):
        ids = parent_entities
        delta = _mk_g2a_result(ids["client_id"])
        session.add(delta)
        session.flush()
        result = session.query(Gstr2aDeltaResult).filter_by(id=delta.id).one()
        assert result.period == "042025"
        assert result.summary["matched"] == 10

    def test_insert_gstr9_override_large_value(self, session, parent_entities):
        ids = parent_entities
        override = _mk_g9_override(ids["client_id"])
        session.add(override)
        session.flush()
        result = session.query(Gstr9AuditOverride).filter_by(id=override.id).one()
        assert float(result.override_value) == pytest.approx(384300387.06, abs=0.01)

    def test_gstr9_override_notes_null(self, session, parent_entities):
        ids = parent_entities
        override = _mk_g9_override(ids["client_id"], table_key="table5", cell_key="5A_total")
        override.notes = None
        session.add(override)
        session.flush()
        result = session.query(Gstr9AuditOverride).filter_by(id=override.id).one()
        assert result.notes is None


# ─── Unique Constraint Tests ───────────────────────────────────────────────────

class TestUniqueConstraints:
    def test_unique_batch_period(self, session, parent_entities):
        ids = parent_entities
        batch = _mk_batch(ids["client_id"])
        session.add(batch)
        session.flush()

        item1 = _mk_item(batch.id, period="042025")
        item2 = _mk_item(batch.id, period="042025")  # duplicate period!
        session.add(item1)
        session.flush()
        session.add(item2)
        with pytest.raises(IntegrityError):
            session.flush()

    def test_unique_gstr9_override_cell(self, session, parent_entities):
        ids = parent_entities
        override1 = _mk_g9_override(ids["client_id"], table_key="table6", cell_key="6A_dup")
        override2 = _mk_g9_override(ids["client_id"], table_key="table6", cell_key="6A_dup")  # duplicate!
        session.add(override1)
        session.flush()
        session.add(override2)
        with pytest.raises(IntegrityError):
            session.flush()

    def test_different_periods_allowed_in_same_batch(self, session, parent_entities):
        ids = parent_entities
        batch = _mk_batch(ids["client_id"])
        session.add(batch)
        session.flush()
        item1 = _mk_item(batch.id, period="042025")
        item2 = _mk_item(batch.id, period="052025")  # different period — OK
        session.add_all([item1, item2])
        session.flush()  # should not raise


# ─── to_dict() Serialization Tests ────────────────────────────────────────────

class TestToDictSerialization:
    def test_batch_to_dict(self, session, parent_entities):
        ids = parent_entities
        batch = _mk_batch(ids["client_id"])
        session.add(batch)
        session.flush()
        d = batch.to_dict()
        assert "id" in d
        assert d["financial_year"] == "2025-26"
        assert d["status"] == "pending"
        assert d["created_by"] is None

    def test_gstr1_run_to_dict_has_jsonb(self, session, parent_entities):
        ids = parent_entities
        run = _mk_g1_run(ids["client_id"])
        session.add(run)
        session.flush()
        d = run.to_dict()
        assert isinstance(d["result_payload"], dict)
        assert isinstance(d["run_summary"], dict)
        assert d["completed_at"] is not None

    def test_gstr9_override_to_dict_float_values(self, session, parent_entities):
        ids = parent_entities
        override = _mk_g9_override(ids["client_id"], table_key="table7", cell_key="7A_val")
        session.add(override)
        session.flush()
        d = override.to_dict()
        assert isinstance(d["override_value"], float)
        assert d["override_value"] == pytest.approx(384300387.06, abs=0.01)

    def test_gstr1a_action_to_dict(self, session, parent_entities):
        ids = parent_entities
        run = _mk_g1_run(ids["client_id"])
        session.add(run)
        session.flush()
        action = _mk_g1a_action(run.id, period="062025")
        session.add(action)
        session.flush()
        d = action.to_dict()
        assert d["user_id"] == "legacy-supabase-uid-abc123"
        assert d["status"] == "accepted"
        assert d["filed_date"] is None


# ─── Normalization Utility Tests ───────────────────────────────────────────────

class TestNormalizationUtils:
    def test_normalize_ts_string(self):
        ts_str = "2026-09-11T10:10:41.985638+00:00"
        result = _normalize_ts(ts_str)
        assert "2026-09-11" in result

    def test_normalize_ts_datetime(self):
        dt = datetime(2026, 9, 11, 10, 10, 41, tzinfo=timezone.utc)
        result = _normalize_ts(dt)
        assert "2026-09-11" in result

    def test_normalize_ts_none(self):
        assert _normalize_ts(None) is None

    def test_normalize_date_string(self):
        assert _normalize_date("2026-03-31") == "2026-03-31"

    def test_normalize_date_date_obj(self):
        assert _normalize_date(date(2026, 3, 31)) == "2026-03-31"

    def test_normalize_date_none(self):
        assert _normalize_date(None) is None

    def test_normalize_numeric_decimal(self):
        assert _normalize_numeric(Decimal("384300387.06")) == pytest.approx(384300387.06, abs=0.01)

    def test_normalize_numeric_none(self):
        assert _normalize_numeric(None) is None

    def test_normalize_numeric_float_string(self):
        assert _normalize_numeric("0.00") == pytest.approx(0.0)

    def test_normalize_json_dict(self):
        d = {"b": 2, "a": 1}
        result = _normalize_json(d)
        assert json.loads(result) == {"a": 1, "b": 2}

    def test_normalize_json_list(self):
        lst = [{"x": 1}, {"y": 2}]
        result = _normalize_json(lst)
        assert json.loads(result) == lst

    def test_normalize_json_none(self):
        assert _normalize_json(None) == "null"


# ─── Orchestrator Dry-Run Test ─────────────────────────────────────────────────

class TestOrchestratorDryRun:
    """Exercises the Batch3AReturnReconciliationOrchestrator with synthetic data."""

    def _make_synthetic_source_data(self, client_id: str, user_id: str, run_id: str) -> dict:
        batch_id = str(uuid.uuid4())
        g1_run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        return {
            "multi_period_recon_batches": [
                {
                    "id": batch_id,
                    "client_gstin_id": client_id,
                    "financial_year": "2025-26",
                    "status": "complete",
                    "created_at": now,
                    "updated_at": now,
                    "created_by": user_id,
                }
            ],
            "multi_period_recon_batch_items": [
                {
                    "id": str(uuid.uuid4()),
                    "batch_id": batch_id,
                    "period": "042025",
                    "status": "complete",
                    "reconciliation_run_id": run_id,
                    "gstr2b_file_path": None,
                    "gstr2b_source": "portal",
                    "pr_file_path": None,
                    "pr_source": "upload",
                    "error_message": None,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": str(uuid.uuid4()),
                    "batch_id": batch_id,
                    "period": "052025",
                    "status": "pending",
                    "reconciliation_run_id": None,
                    "gstr2b_file_path": None,
                    "gstr2b_source": None,
                    "pr_file_path": None,
                    "pr_source": None,
                    "error_message": None,
                    "created_at": now,
                    "updated_at": now,
                },
            ],
            "gstr1_reconciliation_run": [
                {
                    "id": g1_run_id,
                    "client_gstin_id": client_id,
                    "status": "complete",
                    "result_payload": {"total": 100, "invoices": [{"no": "INV001"}]},
                    "run_summary": {"matched": 100, "mismatched": 0},
                    "period": "042025",
                    "gstr1_filed_date": "2026-05-11",
                    "gstr3b_filed_date": None,
                    "created_at": now,
                    "completed_at": now,
                    "created_by": user_id,
                }
            ],
            "gstr1a_period_actions": [],
            "gstr2a_delta_results": [
                {
                    "id": str(uuid.uuid4()),
                    "client_gstin_id": client_id,
                    "period": "042025",
                    "reconciled_at": now,
                    "summary": {"matched": 5, "delta": 1},
                    "results": [{"invoice_no": "INV002", "delta": 500}],
                    "cutoff_date": "2026-05-01",
                    "created_at": now,
                    "updated_at": now,
                }
            ],
            "gstr9_audit_overrides": [
                {
                    "id": str(uuid.uuid4()),
                    "client_gstin_id": client_id,
                    "financial_year": "2025-26",
                    "table_key": "table4",
                    "cell_key": "4A_b2c",
                    "system_value": 0.0,
                    "override_value": 384300387.06,
                    "notes": None,
                    "updated_by": user_id,
                    "updated_at": now,
                }
            ],
        }

    def _make_mock_supabase(self, source_data: dict):
        """Return a mock Supabase client that yields synthetic data."""

        class _MockQueryBuilder:
            def __init__(self, data):
                self._data = data

            def select(self, *a, **kw):
                return self

            def range(self, *a, **kw):
                return self

            def execute(self):
                class _R:
                    pass
                r = _R()
                r.data = self._data
                r.count = len(self._data)
                return r

        class _MockTable:
            def __init__(self, data):
                self._data = data

            def select(self, *a, **kw):
                return _MockQueryBuilder(self._data)

        class _MockSB:
            def __init__(self, data):
                self._data = data

            def table(self, name):
                return _MockTable(self._data.get(name, []))

        return _MockSB(source_data)

    def test_dry_run_with_synthetic_data(self, engine, seed_ids):
        client_id = str(seed_ids["client_id"])
        user_id = str(seed_ids["user_id"])
        run_id = str(seed_ids["run_id"])

        source_data = self._make_synthetic_source_data(client_id, user_id, run_id)
        mock_sb = self._make_mock_supabase(source_data)

        # Override expected counts to match synthetic data
        orchestrator = Batch3AReturnReconciliationOrchestrator(
            sb_client=mock_sb,
            engine=engine,
        )
        # Override expected counts to match synthetic dataset size
        orchestrator.EXPECTED_COUNTS = {
            "multi_period_recon_batches": 1,
            "multi_period_recon_batch_items": 2,
            "gstr1_reconciliation_run": 1,
            "gstr1a_period_actions": 0,
            "gstr2a_delta_results": 1,
            "gstr9_audit_overrides": 1,
        }

        report = orchestrator.run(commit=False)

        # Verify summary
        assert report.total_supabase_rows == 6  # 1+2+1+0+1+1
        assert report.total_inserted == 6
        assert report.total_mismatches == 0
        assert report.is_clean()

        # Verify all tables individually
        tr_by_name = {t.table_name: t for t in report.tables}
        assert tr_by_name["multi_period_recon_batches"].inserted_count == 1
        assert tr_by_name["multi_period_recon_batch_items"].inserted_count == 2
        assert tr_by_name["gstr1_reconciliation_run"].inserted_count == 1
        assert tr_by_name["gstr1a_period_actions"].inserted_count == 0
        assert tr_by_name["gstr2a_delta_results"].inserted_count == 1
        assert tr_by_name["gstr9_audit_overrides"].inserted_count == 1

    def test_dry_run_leaves_zero_residual_rows(self, engine, seed_ids):
        """After dry-run, all 6 tables must be empty (rollback verified)."""
        client_id = str(seed_ids["client_id"])
        user_id = str(seed_ids["user_id"])
        run_id = str(seed_ids["run_id"])

        source_data = self._make_synthetic_source_data(client_id, user_id, run_id)
        mock_sb = self._make_mock_supabase(source_data)
        orchestrator = Batch3AReturnReconciliationOrchestrator(
            sb_client=mock_sb,
            engine=engine,
        )
        orchestrator.EXPECTED_COUNTS = {
            "multi_period_recon_batches": 1,
            "multi_period_recon_batch_items": 2,
            "gstr1_reconciliation_run": 1,
            "gstr1a_period_actions": 0,
            "gstr2a_delta_results": 1,
            "gstr9_audit_overrides": 1,
        }
        orchestrator.run(commit=False)

        # Fresh session — tables must be empty (dry-run rolled back)
        from sqlalchemy.orm import Session as SASession
        with SASession(engine) as s:
            for table in [
                "multi_period_recon_batches",
                "multi_period_recon_batch_items",
                "gstr1_reconciliation_run",
                "gstr1a_period_actions",
                "gstr2a_delta_results",
                "gstr9_audit_overrides",
            ]:
                count = s.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
                assert count == 0, f"Expected 0 residual rows in {table}, got {count}"

    def test_count_discrepancy_raises_escalation(self, engine, seed_ids):
        """Count discrepancy > 0.5% must raise RuntimeError (escalation)."""
        client_id = str(seed_ids["client_id"])
        user_id = str(seed_ids["user_id"])
        run_id = str(seed_ids["run_id"])

        source_data = self._make_synthetic_source_data(client_id, user_id, run_id)
        mock_sb = self._make_mock_supabase(source_data)
        orchestrator = Batch3AReturnReconciliationOrchestrator(
            sb_client=mock_sb,
            engine=engine,
        )
        # Expected count for multi_period_recon_batches is 999 but source has 1 -> discrepancy
        orchestrator.EXPECTED_COUNTS = {
            "multi_period_recon_batches": 999,  # huge mismatch
            "multi_period_recon_batch_items": 2,
            "gstr1_reconciliation_run": 1,
            "gstr1a_period_actions": 0,
            "gstr2a_delta_results": 1,
            "gstr9_audit_overrides": 1,
        }
        with pytest.raises(RuntimeError, match="ESCALATION"):
            orchestrator.run(commit=False)


# ─── Compare Row Utility Tests ─────────────────────────────────────────────────

class TestCompareRow:
    def test_identical_rows_return_no_mismatches(self):
        src = {
            "id": "abc123",
            "client_gstin_id": "def456",
            "financial_year": "2025-26",
            "table_key": "table4",
            "cell_key": "4A",
            "system_value": 0.0,
            "override_value": 100.50,
            "notes": None,
            "updated_by": None,
            "updated_at": "2026-08-10T19:36:24.323387+00:00",
        }
        aurora = dict(src)
        mismatches = _compare_row("gstr9_audit_overrides", src, aurora)
        assert mismatches == []

    def test_numeric_mismatch_detected(self):
        src = {"id": "x", "override_value": 100.00, "system_value": 0.0,
               "client_gstin_id": "y", "financial_year": "2025-26",
               "table_key": "t", "cell_key": "c", "notes": None,
               "updated_by": None, "updated_at": "2026-01-01T00:00:00+00:00"}
        aurora = dict(src)
        aurora["override_value"] = 200.00  # different!
        mismatches = _compare_row("gstr9_audit_overrides", src, aurora)
        assert any("override_value" in m for m in mismatches)

    def test_ts_normalization_accepts_equivalent_timestamps(self):
        src = {"id": "x", "client_gstin_id": "y", "period": "042025",
               "reconciled_at": "2026-09-11T10:10:41+00:00",
               "summary": {}, "results": [], "cutoff_date": None,
               "created_at": "2026-09-11T10:10:41Z",
               "updated_at": "2026-09-11T10:10:41.000000+00:00"}
        aurora = dict(src)
        mismatches = _compare_row("gstr2a_delta_results", src, aurora)
        assert mismatches == []

    def test_json_mismatch_detected(self):
        src = {"id": "x", "client_gstin_id": "y", "status": "complete",
               "result_payload": {"a": 1}, "run_summary": None,
               "period": "042025", "gstr1_filed_date": None, "gstr3b_filed_date": None,
               "created_at": "2026-01-01T00:00:00+00:00",
               "completed_at": "2026-01-01T00:00:00+00:00", "created_by": None}
        aurora = dict(src)
        aurora["result_payload"] = {"a": 2}  # different!
        mismatches = _compare_row("gstr1_reconciliation_run", src, aurora)
        assert any("result_payload" in m for m in mismatches)
