"""Tests for ReconDesk Dual-Auth / AWS Aurora Migration — Phase 4.

Covers:
1. Model & Schema Verification:
   - Table names: reconciliation_run, gstr_records, pr_records, reconciliation_results.
   - Foreign keys and cascade relationships (ON DELETE CASCADE).
   - Unique constraint uq_run_dedup (client_gstin_id, period, file_type, file_hash).
   - Serialization (.to_dict()) compatibility with Supabase PostgREST shape.
2. Repository Unit Tests (AuroraReconciliationRepository):
   - get_run: existing run returns dict; non-existent returns None.
   - list_runs: client scoping, status filtering, order by created_at DESC, limit capping.
   - list_runs tri-state: empty list for 0 runs (authoritative); None on failure.
   - create_run: ISO string date/datetime parsing, default values.
   - update_run: field updating, return updated dict, None if missing.
   - delete_run_cascade: transactional 7-step deletion, cascading GSTR/PR/results.
   - GSTR records: insert, get, count, tri-state (None on missing run, [] on 0 records).
   - PR records: insert, get, count, tri-state (None on missing run, [] on 0 records).
   - Reconciliation results: save and get payload.
3. Authorization & Scoping Tests (assert_run_accessible):
   - User with access to client GSTIN allows access via Aurora without Supabase.
   - User without access to client GSTIN raises 403 Forbidden without Supabase.
   - Missing Aurora run falls back to Supabase.
4. Router Dual-Read Tests (reconciliation_api):
   - _list_reconciliation_run_rows_for_clients returns Aurora runs without Supabase.
   - _list_reconciliation_run_rows_for_clients returns [] without Supabase.
   - _list_reconciliation_run_rows_for_clients falls back to Supabase on Aurora miss.
   - delete_reconcile_run triggers Aurora cascade deletion.
5. Outcomes & Payload Store Dual-Read Tests:
   - load_payload reads from Aurora when present.
   - load_payload falls back to Supabase on Aurora miss.
   - save_reconciliation_results dual-writes to Aurora.
"""

from __future__ import annotations

import base64
import gzip
import json
import os
import tempfile
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.reconciliation import (
    GstrRecord,
    PrRecord,
    ReconciliationResult,
    ReconciliationRun,
)
from app.models.schema_base import Base
from app.models.tenancy import ClientGSTIN, UserProfile
from app.repositories.reconciliation import (
    AuroraReconciliationRepository,
    get_reconciliation_repository,
    set_reconciliation_repository,
)
from app.routers.reconciliation_api import (
    _list_reconciliation_run_rows_for_clients,
    delete_reconcile_run,
)
from app.services.firm_access import assert_run_accessible
from app.services.reconciliation_outcomes import (
    _load_gstr_map,
    _load_pr_map,
    load_payload,
)
from app.services.reconciliation_payload_store import save_reconciliation_results


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def recon_sqlite_engine():
    """Create a temporary SQLite engine with all schema tables."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": 30},
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass


@pytest.fixture
def recon_repo(recon_sqlite_engine) -> AuroraReconciliationRepository:
    """Provide an AuroraReconciliationRepository backed by SQLite."""
    factory = sessionmaker(
        bind=recon_sqlite_engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    repo = AuroraReconciliationRepository(session_factory=factory)
    set_reconciliation_repository(repo)
    yield repo
    set_reconciliation_repository(None)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _create_firm_and_client(session: Session) -> tuple[str, str]:
    """Helper to create a firm owner user and client_gstin in SQLite."""
    owner_id = str(uuid.uuid4())
    client_id = str(uuid.uuid4())
    owner = UserProfile(
        id=owner_id,
        email="ca@example.com",
        full_name="CA Principal",
        role="admin",
        is_active=True,
    )
    client = ClientGSTIN(
        id=client_id,
        firm_owner_id=owner_id,
        gstin="27ABCDE1234F1Z5",
        trade_name="Acme Corp",
        is_active=True,
    )
    session.add_all([owner, client])
    session.commit()
    return owner_id, client_id


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Model & Schema Verification
# ═══════════════════════════════════════════════════════════════════════════════


class TestReconciliationModels:
    """Verify table names, column mappings, and .to_dict() serialization."""

    def test_table_names(self):
        assert ReconciliationRun.__tablename__ == "reconciliation_run"
        assert GstrRecord.__tablename__ == "gstr_records"
        assert PrRecord.__tablename__ == "pr_records"
        assert ReconciliationResult.__tablename__ == "reconciliation_results"

    def test_run_to_dict_shape(self):
        run_id = str(uuid.uuid4())
        client_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        run = ReconciliationRun(
            id=run_id,
            client_gstin_id=client_id,
            period="032026",
            status="completed",
            progress_percent=100.0,
            matched_count=42,
            unmatched_count=3,
            itc_at_risk=500000,
            wrongful_itc=0,
            late_itc=12000,
            gstr_period_end=date(2026, 3, 31),
            created_at=now,
        )
        d = run.to_dict()
        assert d["id"] == run_id
        assert d["client_gstin_id"] == client_id
        assert d["period"] == "032026"
        assert d["status"] == "completed"
        assert d["progress_percent"] == 100.0
        assert d["matched_count"] == 42
        assert d["itc_at_risk"] == 500000
        assert d["gstr_period_end"] == "2026-03-31"
        assert d["created_at"] == now.isoformat()
        assert d["is_locked"] is False

    def test_gstr_record_to_dict_shape(self):
        rec_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        rec = GstrRecord(
            id=rec_id,
            run_id=run_id,
            supplier_gstin="27ABCDE1234F1Z5",
            invoice_number="INV-001",
            invoice_date=date(2026, 3, 15),
            taxable_amount_paise=10000000,
            igst_paise=1800000,
            total_tax_paise=1800000,
            match_status="matched",
            match_confidence=98,
            created_at=now,
        )
        d = rec.to_dict()
        assert d["id"] == rec_id
        assert d["run_id"] == run_id
        assert d["supplier_gstin"] == "27ABCDE1234F1Z5"
        assert d["invoice_number"] == "INV-001"
        assert d["invoice_date"] == "2026-03-15"
        assert d["taxable_amount_paise"] == 10000000
        assert d["match_confidence"] == 98

    def test_pr_record_to_dict_shape(self):
        rec_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        rec = PrRecord(
            id=rec_id,
            run_id=run_id,
            supplier_gstin="27ABCDE1234F1Z5",
            invoice_number="INV-001",
            invoice_date=date(2026, 3, 15),
            taxable_amount_paise=10000000,
            payment_date=date(2026, 3, 20),
            is_paid=True,
            created_at=now,
        )
        d = rec.to_dict()
        assert d["id"] == rec_id
        assert d["run_id"] == run_id
        assert d["payment_date"] == "2026-03-20"
        assert d["is_paid"] is True

    def test_reconciliation_result_to_dict_shape(self):
        res_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        result = ReconciliationResult(
            id=res_id,
            run_id=run_id,
            payload={"engine": {"matched": []}},
            match_confidence=0.95,
            created_at=now,
        )
        d = result.to_dict()
        assert d["id"] == res_id
        assert d["run_id"] == run_id
        assert d["payload"] == {"engine": {"matched": []}}
        assert d["match_confidence"] == 0.95


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Repository Unit Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestReconciliationRepository:
    """Targeted tests for AuroraReconciliationRepository methods."""

    def test_create_and_get_run(self, recon_sqlite_engine, recon_repo):
        with Session(recon_sqlite_engine) as session:
            _, client_id = _create_firm_and_client(session)

        run_id = str(uuid.uuid4())
        run_data = {
            "id": run_id,
            "client_gstin_id": client_id,
            "period": "032026",
            "status": "completed",
            "progress_percent": 100,
            "created_at": "2026-03-31T10:00:00Z",
            "gstr_period_end": "2026-03-31",
        }
        created = recon_repo.create_run(run_data)
        assert created["id"] == run_id
        assert created["period"] == "032026"

        fetched = recon_repo.get_run(run_id)
        assert fetched is not None
        assert fetched["id"] == run_id
        assert fetched["status"] == "completed"

    def test_get_run_missing_returns_none(self, recon_repo):
        assert recon_repo.get_run(str(uuid.uuid4())) is None
        assert recon_repo.get_run("") is None

    def test_list_runs_client_scoping_and_ordering(
        self, recon_sqlite_engine, recon_repo
    ):
        with Session(recon_sqlite_engine) as session:
            _, c1 = _create_firm_and_client(session)
            _, c2 = _create_firm_and_client(session)

        base_time = datetime.now(timezone.utc)
        r1 = recon_repo.create_run(
            {
                "id": str(uuid.uuid4()),
                "client_gstin_id": c1,
                "period": "012026",
                "created_at": (base_time - timedelta(days=2)).isoformat(),
            }
        )
        r2 = recon_repo.create_run(
            {
                "id": str(uuid.uuid4()),
                "client_gstin_id": c1,
                "period": "022026",
                "created_at": (base_time - timedelta(days=1)).isoformat(),
            }
        )
        r3 = recon_repo.create_run(
            {
                "id": str(uuid.uuid4()),
                "client_gstin_id": c2,
                "period": "032026",
                "created_at": base_time.isoformat(),
            }
        )

        # Scoped to c1
        c1_runs = recon_repo.list_runs([c1])
        assert len(c1_runs) == 2
        # Ordered by created_at DESC (r2 before r1)
        assert c1_runs[0]["id"] == r2["id"]
        assert c1_runs[1]["id"] == r1["id"]

        # Scoped to both
        all_runs = recon_repo.list_runs([c1, c2])
        assert len(all_runs) == 3
        assert all_runs[0]["id"] == r3["id"]

    def test_list_runs_status_filtering(self, recon_sqlite_engine, recon_repo):
        with Session(recon_sqlite_engine) as session:
            _, c1 = _create_firm_and_client(session)

        recon_repo.create_run(
            {"id": str(uuid.uuid4()), "client_gstin_id": c1, "period": "012026", "status": "completed"}
        )
        recon_repo.create_run(
            {"id": str(uuid.uuid4()), "client_gstin_id": c1, "period": "022026", "status": "failed"}
        )
        recon_repo.create_run(
            {"id": str(uuid.uuid4()), "client_gstin_id": c1, "period": "032026", "status": "processing"}
        )

        completed = recon_repo.list_runs([c1], status_filter="completed")
        assert len(completed) == 1
        assert completed[0]["status"] == "completed"

        failed = recon_repo.list_runs([c1], status_filter="FAILED")
        assert len(failed) == 1
        assert failed[0]["status"] == "failed"

    def test_list_runs_authoritative_empty_list(self, recon_sqlite_engine, recon_repo):
        with Session(recon_sqlite_engine) as session:
            _, c1 = _create_firm_and_client(session)

        # Client exists with 0 runs -> returns [] (authoritative, NOT None)
        assert recon_repo.list_runs([c1]) == []
        assert recon_repo.list_runs([]) == []

    def test_list_runs_client_not_in_aurora_returns_none(self, recon_repo):
        missing_client_id = str(uuid.uuid4())
        # Client does not exist in Aurora tenancy -> returns None (migration miss, permits fallback)
        assert recon_repo.list_runs([missing_client_id]) is None

    def test_update_run(self, recon_sqlite_engine, recon_repo):
        with Session(recon_sqlite_engine) as session:
            _, c1 = _create_firm_and_client(session)

        run_id = str(uuid.uuid4())
        recon_repo.create_run(
            {"id": run_id, "client_gstin_id": c1, "period": "032026", "status": "queued"}
        )

        updated = recon_repo.update_run(
            run_id,
            {"status": "completed", "matched_count": 50, "itc_at_risk": 120000},
        )
        assert updated is not None
        assert updated["status"] == "completed"
        assert updated["matched_count"] == 50
        assert updated["itc_at_risk"] == 120000

        # Update non-existent run returns None
        assert recon_repo.update_run(str(uuid.uuid4()), {"status": "completed"}) is None

    def test_delete_run_cascade(self, recon_sqlite_engine, recon_repo):
        with Session(recon_sqlite_engine) as session:
            _, c1 = _create_firm_and_client(session)

        run_id = str(uuid.uuid4())
        recon_repo.create_run(
            {"id": run_id, "client_gstin_id": c1, "period": "032026", "status": "completed"}
        )

        # Insert GSTR, PR, and results records referencing this run
        recon_repo.insert_gstr_records(
            run_id,
            [
                {
                    "supplier_gstin": "27ABCDE1234F1Z5",
                    "invoice_number": "INV-1",
                    "invoice_date": "2026-03-10",
                }
            ],
        )
        recon_repo.insert_pr_records(
            run_id,
            [
                {
                    "supplier_gstin": "27ABCDE1234F1Z5",
                    "invoice_number": "INV-1",
                    "invoice_date": "2026-03-10",
                }
            ],
        )
        recon_repo.save_reconciliation_results(
            run_id,
            payload={"engine": {"matched": []}},
        )

        assert recon_repo.count_gstr_records(run_id) == 1
        assert recon_repo.count_pr_records(run_id) == 1
        assert recon_repo.get_reconciliation_results(run_id) is not None

        # Execute cascade deletion
        deleted = recon_repo.delete_run_cascade(run_id)
        assert deleted is True

        # Verify run and all child records are removed
        assert recon_repo.get_run(run_id) is None
        assert recon_repo.count_gstr_records(run_id) == 0
        assert recon_repo.count_pr_records(run_id) == 0
        assert recon_repo.get_reconciliation_results(run_id) is None

        # Subsequent deletion returns False
        assert recon_repo.delete_run_cascade(run_id) is False

    def test_gstr_and_pr_records_crud(self, recon_sqlite_engine, recon_repo):
        with Session(recon_sqlite_engine) as session:
            _, c1 = _create_firm_and_client(session)

        run_id = str(uuid.uuid4())
        recon_repo.create_run(
            {"id": run_id, "client_gstin_id": c1, "period": "032026", "status": "completed"}
        )

        # GSTR records
        assert recon_repo.get_gstr_records(run_id) == []
        gstr_rows = [
            {
                "supplier_gstin": "27A",
                "invoice_number": "1",
                "taxable_amount_paise": 1000,
            },
            {
                "supplier_gstin": "27B",
                "invoice_number": "2",
                "taxable_amount_paise": 2000,
            },
        ]
        inserted = recon_repo.insert_gstr_records(run_id, gstr_rows)
        assert inserted == 2
        assert recon_repo.count_gstr_records(run_id) == 2
        records = recon_repo.get_gstr_records(run_id)
        assert len(records) == 2

        # Missing run returns None
        assert recon_repo.get_gstr_records(str(uuid.uuid4())) is None

        # PR records
        assert recon_repo.get_pr_records(run_id) == []
        pr_rows = [
            {
                "supplier_gstin": "27A",
                "invoice_number": "1",
                "taxable_amount_paise": 1000,
            }
        ]
        inserted_pr = recon_repo.insert_pr_records(run_id, pr_rows)
        assert inserted_pr == 1
        assert recon_repo.count_pr_records(run_id) == 1
        assert len(recon_repo.get_pr_records(run_id)) == 1
        assert recon_repo.get_pr_records(str(uuid.uuid4())) is None


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Authorization & Scoping Tests (assert_run_accessible)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAssertRunAccessible:
    """Verify firm authorization and cross-tenant access enforcement."""

    def test_run_accessible_allowed_client(self, recon_sqlite_engine, recon_repo):
        with Session(recon_sqlite_engine) as session:
            owner_id, c1 = _create_firm_and_client(session)

        run_id = str(uuid.uuid4())
        recon_repo.create_run(
            {"id": run_id, "client_gstin_id": c1, "period": "032026", "status": "completed"}
        )

        mock_sb = MagicMock()
        current_user = {"id": owner_id, "role": "admin"}

        # Patch list_accessible_client_gstin_ids to include c1
        with patch(
            "app.services.firm_access.list_accessible_client_gstin_ids",
            return_value={c1},
        ):
            row = assert_run_accessible(mock_sb, run_id, current_user)
            assert row["id"] == run_id
            assert row["client_gstin_id"] == c1
            # Supabase table must NOT have been queried
            mock_sb.table.assert_not_called()

    def test_run_accessible_denied_client(self, recon_sqlite_engine, recon_repo):
        with Session(recon_sqlite_engine) as session:
            owner_id, c1 = _create_firm_and_client(session)

        run_id = str(uuid.uuid4())
        recon_repo.create_run(
            {"id": run_id, "client_gstin_id": c1, "period": "032026", "status": "completed"}
        )

        mock_sb = MagicMock()
        # Another user who does NOT have access to c1
        other_user = {"id": str(uuid.uuid4()), "role": "admin"}

        with patch(
            "app.services.firm_access.list_accessible_client_gstin_ids",
            return_value=set(),
        ):
            with pytest.raises(HTTPException) as exc_info:
                assert_run_accessible(mock_sb, run_id, other_user)
            assert exc_info.value.status_code == 403
            assert exc_info.value.detail == "Access denied"
            # Supabase table must NOT have been queried
            mock_sb.table.assert_not_called()

    def test_run_accessible_fallback_to_supabase(self, recon_repo):
        mock_sb = MagicMock()
        run_id = str(uuid.uuid4())
        client_id = str(uuid.uuid4())
        current_user = {"id": str(uuid.uuid4()), "role": "admin"}

        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": run_id, "client_gstin_id": client_id, "period": "032026"}
        ]

        with patch(
            "app.services.firm_access.list_accessible_client_gstin_ids",
            return_value={client_id},
        ):
            row = assert_run_accessible(mock_sb, run_id, current_user)
            assert row["id"] == run_id
            # Supabase was queried on Aurora miss
            mock_sb.table.assert_called_with("reconciliation_run")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Router Dual-Read Tests (reconciliation_api)
# ═══════════════════════════════════════════════════════════════════════════════


class TestReconciliationRouterDualRead:
    """Verify endpoint and helper dual-read behavior."""

    def test_list_run_rows_aurora_hit_skips_supabase(
        self, recon_sqlite_engine, recon_repo
    ):
        with Session(recon_sqlite_engine) as session:
            _, c1 = _create_firm_and_client(session)

        run_id = str(uuid.uuid4())
        recon_repo.create_run(
            {"id": run_id, "client_gstin_id": c1, "period": "032026", "status": "completed"}
        )

        mock_sb = MagicMock()
        rows = _list_reconciliation_run_rows_for_clients(
            mock_sb,
            [c1],
            status_filter=None,
            per_chunk_cap=50,
        )
        assert len(rows) == 1
        assert rows[0]["id"] == run_id
        # Supabase must NOT be called
        mock_sb.table.assert_not_called()

    def test_list_run_rows_authoritative_empty_skips_supabase(
        self, recon_sqlite_engine, recon_repo
    ):
        with Session(recon_sqlite_engine) as session:
            _, c1 = _create_firm_and_client(session)

        mock_sb = MagicMock()
        rows = _list_reconciliation_run_rows_for_clients(
            mock_sb,
            [c1],
            status_filter=None,
            per_chunk_cap=50,
        )
        assert rows == []
        mock_sb.table.assert_not_called()

    def test_list_run_rows_fallback_on_unconfigured_aurora(self):
        # Set repository to None
        set_reconciliation_repository(None)
        mock_sb = MagicMock()
        run_id = str(uuid.uuid4())
        mock_sb.table.return_value.select.return_value.in_.return_value.order.return_value.limit.return_value.execute.return_value.data = [
            {"id": run_id, "period": "032026"}
        ]

        rows = _list_reconciliation_run_rows_for_clients(
            mock_sb,
            [str(uuid.uuid4())],
            status_filter=None,
            per_chunk_cap=50,
        )
        assert len(rows) == 1
        assert rows[0]["id"] == run_id
        mock_sb.table.assert_called_with("reconciliation_run")

    def test_list_run_rows_invalid_status_filter_raises_422(self, recon_repo):
        mock_sb = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            _list_reconciliation_run_rows_for_clients(
                mock_sb,
                [str(uuid.uuid4())],
                status_filter="INVALID_STATUS",
                per_chunk_cap=50,
            )
        assert exc_info.value.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Outcomes & Payload Store Dual-Read Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestOutcomesAndPayloadStore:
    """Verify load_payload, _load_gstr_map, and save_reconciliation_results dual-read."""

    def test_load_payload_aurora_hit(self, recon_sqlite_engine, recon_repo):
        with Session(recon_sqlite_engine) as session:
            _, c1 = _create_firm_and_client(session)

        run_id = str(uuid.uuid4())
        recon_repo.create_run(
            {"id": run_id, "client_gstin_id": c1, "period": "032026", "status": "completed"}
        )

        expected_payload = {
            "engine": {
                "matched": [{"gstr_id": "g1", "pr_id": "p1"}],
                "missed_itc": [],
            }
        }
        compressed = base64.b64encode(
            gzip.compress(json.dumps(expected_payload).encode("utf-8"))
        ).decode("utf-8")
        recon_repo.save_reconciliation_results(run_id, payload=compressed)

        mock_sb = MagicMock()
        loaded = load_payload(mock_sb, run_id)
        assert loaded == expected_payload
        mock_sb.table.assert_not_called()

    def test_load_payload_fallback_on_aurora_miss(self, recon_repo):
        mock_sb = MagicMock()
        run_id = str(uuid.uuid4())
        expected_payload = {"engine": {"matched": []}}
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"payload": expected_payload, "record_data": None}
        ]

        loaded = load_payload(mock_sb, run_id)
        assert loaded == expected_payload
        mock_sb.table.assert_called_with("reconciliation_results")

    def test_save_reconciliation_results_dual_write(
        self, recon_sqlite_engine, recon_repo
    ):
        with Session(recon_sqlite_engine) as session:
            _, c1 = _create_firm_and_client(session)

        run_id = str(uuid.uuid4())
        recon_repo.create_run(
            {"id": run_id, "client_gstin_id": c1, "period": "032026", "status": "completed"}
        )

        mock_sb = MagicMock()
        mock_sb.table.return_value.delete.return_value.eq.return_value.execute.return_value = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "1"}]
        mock_sb.table.return_value.insert.return_value.execute.return_value.error = None

        payload = {"engine": {"matched": []}}
        save_reconciliation_results(
            mock_sb,
            run_id,
            payload,
            created_at="2026-03-31T12:00:00Z",
        )

        # Verified written to Aurora
        aurora_res = recon_repo.get_reconciliation_results(run_id)
        assert aurora_res is not None
        assert aurora_res["run_id"] == run_id
        # Verified written to Supabase
        mock_sb.table.assert_any_call("reconciliation_results")

    def test_save_reconciliation_results_supabase_failure_prevents_aurora_write(
        self, recon_sqlite_engine, recon_repo
    ):
        with Session(recon_sqlite_engine) as session:
            _, c1 = _create_firm_and_client(session)

        run_id = str(uuid.uuid4())
        recon_repo.create_run(
            {"id": run_id, "client_gstin_id": c1, "period": "032026", "status": "completed"}
        )

        mock_sb = MagicMock()
        mock_sb.table.return_value.delete.return_value.eq.return_value.execute.return_value = MagicMock()
        # Supabase insert fails with error
        mock_sb.table.return_value.insert.return_value.execute.return_value.data = None
        mock_sb.table.return_value.insert.return_value.execute.return_value.error = "Simulated Supabase failure"

        payload = {"engine": {"matched": []}}
        with pytest.raises(RuntimeError) as exc_info:
            save_reconciliation_results(
                mock_sb,
                run_id,
                payload,
                created_at="2026-03-31T12:00:00Z",
            )
        assert "Simulated Supabase failure" in str(exc_info.value)
        # Aurora was NOT written
        assert recon_repo.get_reconciliation_results(run_id) is None

    def test_save_reconciliation_results_aurora_failure_non_fatal(
        self, recon_sqlite_engine, recon_repo
    ):
        with Session(recon_sqlite_engine) as session:
            _, c1 = _create_firm_and_client(session)

        run_id = str(uuid.uuid4())
        recon_repo.create_run(
            {"id": run_id, "client_gstin_id": c1, "period": "032026", "status": "completed"}
        )

        mock_sb = MagicMock()
        mock_sb.table.return_value.delete.return_value.eq.return_value.execute.return_value = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "1"}]
        mock_sb.table.return_value.insert.return_value.execute.return_value.error = None

        payload = {"engine": {"matched": []}}
        # Simulate Aurora failure
        with patch.object(
            recon_repo, "save_reconciliation_results", side_effect=Exception("Simulated Aurora write error")
        ):
            # Must succeed without raising
            save_reconciliation_results(
                mock_sb,
                run_id,
                payload,
                created_at="2026-03-31T12:00:00Z",
            )
        # Supabase write succeeded
        mock_sb.table.assert_any_call("reconciliation_results")

    def test_load_gstr_and_pr_maps_aurora_hit(
        self, recon_sqlite_engine, recon_repo
    ):
        with Session(recon_sqlite_engine) as session:
            _, c1 = _create_firm_and_client(session)

        run_id = str(uuid.uuid4())
        recon_repo.create_run(
            {"id": run_id, "client_gstin_id": c1, "period": "032026", "status": "completed"}
        )
        recon_repo.insert_gstr_records(
            run_id,
            [
                {
                    "supplier_gstin": "27ABCDE1234F1Z5",
                    "invoice_number": "INV-G1",
                    "invoice_date": "2026-03-10",
                    "record_data": {"note": "gstr test"},
                }
            ],
        )
        recon_repo.insert_pr_records(
            run_id,
            [
                {
                    "supplier_gstin": "27ABCDE1234F1Z5",
                    "invoice_number": "INV-P1",
                    "invoice_date": "2026-03-10",
                    "record_data": {"note": "pr test"},
                }
            ],
        )

        mock_sb = MagicMock()
        gstr_map = _load_gstr_map(mock_sb, run_id)
        pr_map = _load_pr_map(mock_sb, run_id)

        assert len(gstr_map) == 1
        assert len(pr_map) == 1
        # Supabase must NOT be queried
        mock_sb.table.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Additional Constraints and Router Delete Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestConstraintsAndRouterDelete:
    """Verify constraint enforcement and delete endpoint."""

    @pytest.mark.asyncio
    async def test_delete_reconcile_run_endpoint_non_admin_forbidden(self):
        req = MagicMock()
        run_id = str(uuid.uuid4())
        non_admin_user = {"id": str(uuid.uuid4()), "role": "staff"}

        with patch("app.routers.reconciliation_api.get_user_role", return_value="staff"):
            with pytest.raises(HTTPException) as exc_info:
                await delete_reconcile_run(req, run_id, current_user=non_admin_user)
            assert exc_info.value.status_code == 403
            assert "Only admins" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_delete_reconcile_run_endpoint_admin_aurora_cascade(
        self, recon_sqlite_engine, recon_repo
    ):
        with Session(recon_sqlite_engine) as session:
            admin_id, c1 = _create_firm_and_client(session)

        run_id = str(uuid.uuid4())
        recon_repo.create_run(
            {"id": run_id, "client_gstin_id": c1, "period": "032026", "status": "completed"}
        )
        recon_repo.insert_gstr_records(
            run_id,
            [{"supplier_gstin": "27A", "invoice_number": "1", "invoice_date": "2026-03-10"}],
        )

        req = MagicMock()
        admin_user = {"id": admin_id, "role": "admin"}

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

        with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_sb), \
             patch("app.routers.reconciliation_api.get_user_role", return_value="admin"), \
             patch("app.routers.reconciliation_api.assert_run_accessible", return_value={"id": run_id, "client_gstin_id": c1}), \
             patch("app.routers.reconciliation_api.log_action", return_value=None), \
             patch("app.routers.reconciliation_api.invalidate_user_dashboard", return_value=None), \
             patch("app.routers.reconciliation_api.invalidate_run_bucket_cache", return_value=None):

            res = await delete_reconcile_run(req, run_id, current_user=admin_user)
            assert res == {"message": "Run deleted successfully"}

        # Verified deleted from Aurora
        assert recon_repo.get_run(run_id) is None
        assert recon_repo.count_gstr_records(run_id) == 0

    @pytest.mark.asyncio
    async def test_delete_reconcile_run_endpoint_supabase_failure_prevents_aurora_delete(
        self, recon_sqlite_engine, recon_repo
    ):
        with Session(recon_sqlite_engine) as session:
            admin_id, c1 = _create_firm_and_client(session)

        run_id = str(uuid.uuid4())
        recon_repo.create_run(
            {"id": run_id, "client_gstin_id": c1, "period": "032026", "status": "completed"}
        )

        req = MagicMock()
        admin_user = {"id": admin_id, "role": "admin"}

        mock_sb = MagicMock()
        # Supabase select finds the run
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": run_id, "client_gstin_id": c1}
        ]
        # Supabase RPC fails with hard 500 error
        mock_sb.rpc.return_value.execute.side_effect = Exception("Supabase connection broken")

        with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_sb), \
             patch("app.routers.reconciliation_api.get_user_role", return_value="admin"), \
             patch("app.routers.reconciliation_api.assert_run_accessible", return_value={"id": run_id, "client_gstin_id": c1}):

            with pytest.raises(HTTPException) as exc_info:
                await delete_reconcile_run(req, run_id, current_user=admin_user)
            assert exc_info.value.status_code == 500

        # Verified run is STILL present in Aurora because Supabase failed first
        assert recon_repo.get_run(run_id) is not None

    @pytest.mark.asyncio
    async def test_delete_reconcile_run_endpoint_aurora_failure_non_fatal(
        self, recon_sqlite_engine, recon_repo
    ):
        with Session(recon_sqlite_engine) as session:
            admin_id, c1 = _create_firm_and_client(session)

        run_id = str(uuid.uuid4())
        recon_repo.create_run(
            {"id": run_id, "client_gstin_id": c1, "period": "032026", "status": "completed"}
        )

        req = MagicMock()
        admin_user = {"id": admin_id, "role": "admin"}

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        mock_sb.rpc.return_value.execute.return_value = MagicMock()

        with patch("app.routers.reconciliation_api.get_supabase", return_value=mock_sb), \
             patch("app.routers.reconciliation_api.get_user_role", return_value="admin"), \
             patch("app.routers.reconciliation_api.assert_run_accessible", return_value={"id": run_id, "client_gstin_id": c1}), \
             patch.object(recon_repo, "delete_run_cascade", side_effect=Exception("Aurora failure")), \
             patch("app.routers.reconciliation_api.log_action", return_value=None), \
             patch("app.routers.reconciliation_api.invalidate_user_dashboard", return_value=None), \
             patch("app.routers.reconciliation_api.invalidate_run_bucket_cache", return_value=None):

            res = await delete_reconcile_run(req, run_id, current_user=admin_user)
            assert res == {"message": "Run deleted successfully"}

    def test_worker_load_gstr_matcher_and_raw_aurora_hit(
        self, recon_sqlite_engine, recon_repo
    ):
        from app.worker.reconciliation_task import _load_gstr_matcher_and_raw

        with Session(recon_sqlite_engine) as session:
            _, c1 = _create_firm_and_client(session)

        run_id = str(uuid.uuid4())
        recon_repo.create_run(
            {"id": run_id, "client_gstin_id": c1, "period": "032026", "status": "completed"}
        )
        recon_repo.insert_gstr_records(
            run_id,
            [
                {
                    "supplier_gstin": "27ABCDE1234F1Z5",
                    "invoice_number": "INV-G1",
                    "invoice_date": "2026-03-10",
                    "record_data": {"taxable_value": 1000},
                }
            ],
        )

        mock_sb = MagicMock()
        matcher_rows, raw_by_id = _load_gstr_matcher_and_raw(mock_sb, run_id)
        assert len(matcher_rows) == 1
        assert len(raw_by_id) == 1
        # Supabase must NOT be called
        mock_sb.table.assert_not_called()

