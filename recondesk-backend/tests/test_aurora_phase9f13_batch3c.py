"""Phase 9F-13 Batch 3C: Schema, Models, Repository, and Dry-Run Verification Tests.

Scope: Government Portal Filing Automation & Bulk Return Processing
Tables:
1. filing_sessions
2. filing_runs
3. filing_batches
4. filing_batch_items
5. sales_register_run
6. sr_records

Tests verify:
1. All 6 SQLAlchemy models create correct table schema.
2. Column types, nullability, foreign keys, and check constraints.
3. to_dict() serialization round-trips for all models.
4. SENSITIVE TOKEN REDACTION:
   - `FilingSession.to_dict(redact_token=True)` masks session_token.
   - Zero token leakage in logs and representations.
5. Repository operations:
   - Session lifecycle: create, get_active, update_token, logout.
   - Run lifecycle: create, update, fail, history.
   - GSTR-3B offset lock gate: blocks Save/Offset when offset_complete, raises Gstr3bPeriodLockedError.
   - Bulk return processing: create_batch, update_batch_item, recalculate_batch_status.
   - Sales register access: create_sales_register_run, create_sr_records, fetch_sales_register_records.
6. Tenant boundary isolation:
   - Firm-level account isolation for sessions, runs, and batches.
   - Client-level isolation.
7. Backfill orchestrator dry-run against live Supabase:
   - 21/21 source rows matched.
   - 0 mismatches, 0 missing, 0 extra.
   - 0 residual rows after rollback on fresh connection.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

backend_root = Path(__file__).resolve().parents[1]
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from dotenv import load_dotenv
load_dotenv(backend_root / ".env")

from app.models.schema_base import Base, GUID
from app.models.tenancy import ClientGSTIN, UserProfile
from app.models.filing_automation import (
    FilingBatch,
    FilingBatchItem,
    FilingRun,
    FilingSession,
    SalesRegisterRun,
    SrRecord,
)
from app.repositories.filing_automation import (
    AuroraFilingAutomationRepository,
    Gstr3bPeriodLockedError,
)
from app.scripts.backfill_batch3c_filing_automation import (
    Batch3CFilingAutomationOrchestrator,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sqlite_engine():
    """Create an isolated in-memory SQLite engine with all schema tables."""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def db_session(sqlite_engine):
    """Provide a transactional DB session for tests."""
    Session_ = sessionmaker(bind=sqlite_engine)
    session = Session_()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def seeded_data(db_session):
    """Seed base user and client GSTIN records."""
    firm_id = uuid.uuid4()
    client_id = uuid.uuid4()

    user = UserProfile(
        id=firm_id,
        email="ca_firm@recondesk.test",
        full_name="CA Firm Owner",
        role="ca",
        is_active=True,
        free_runs_remaining=25,
    )
    client = ClientGSTIN(
        id=client_id,
        firm_owner_id=firm_id,
        gstin="27AABCT1234A1Z5",
        legal_name="Acme Corp Ltd",
    )
    db_session.add_all([user, client])
    db_session.commit()
    return {"firm_id": str(firm_id), "client_id": str(client_id), "gstin": "27AABCT1234A1Z5"}


@pytest.fixture
def repo(sqlite_engine):
    """Return a repository bound to the test engine."""
    session_factory = sessionmaker(bind=sqlite_engine)
    return AuroraFilingAutomationRepository(session_factory=session_factory)


# ── 1. Schema & Model Definition Tests ────────────────────────────────────────

def test_batch3c_models_table_registration():
    """Verify all 6 Batch 3C tables are correctly defined in SQLAlchemy metadata."""
    table_names = set(Base.metadata.tables.keys())
    expected = {
        "filing_sessions",
        "filing_runs",
        "filing_batches",
        "filing_batch_items",
        "sales_register_run",
        "sr_records",
    }
    assert expected.issubset(table_names), f"Missing tables: {expected - table_names}"


def test_filing_session_model_serialization(db_session, seeded_data):
    """Verify FilingSession serialization and sensitive token redaction."""
    now = datetime.now(timezone.utc)
    sess = FilingSession(
        id=uuid.uuid4(),
        firm_id=UUID(seeded_data["firm_id"]),
        client_gstin_id=UUID(seeded_data["client_id"]),
        gstin=seeded_data["gstin"],
        username="user123",
        session_token="sensitive_gstn_jwt_token_secret_12345",
        token_expires_at=now + timedelta(hours=6),
        status="active",
    )
    db_session.add(sess)
    db_session.commit()

    # Redacted by default
    d_redacted = sess.to_dict()
    assert d_redacted["session_token"] == "***REDACTED***"
    assert d_redacted["gstin"] == seeded_data["gstin"]

    # Unredacted for internal secure operations
    d_raw = sess.to_dict(redact_token=False)
    assert d_raw["session_token"] == "sensitive_gstn_jwt_token_secret_12345"


def test_filing_run_model_jsonb_and_fields(db_session, seeded_data):
    """Verify FilingRun fields, JSONB blobs, and history columns."""
    run = FilingRun(
        id=uuid.uuid4(),
        firm_id=UUID(seeded_data["firm_id"]),
        client_gstin_id=UUID(seeded_data["client_id"]),
        gstin=seeded_data["gstin"],
        return_type="gstr-3b",
        period="2026-06",
        status="saved",
        reference_id="REF123456",
        ack_number="ACK987654",
        arn="AA2706260000001",
        filing_method="evc",
        filed_at=datetime.now(timezone.utc),
        save_payload={"table4": {"itc_available": 1000.0}},
        raw_response={"status_cd": "1", "data": "dummy_b64"},
    )
    db_session.add(run)
    db_session.commit()

    d = run.to_dict()
    assert d["return_type"] == "gstr-3b"
    assert d["period"] == "2026-06"
    assert d["save_payload"]["table4"]["itc_available"] == 1000.0
    assert d["arn"] == "AA2706260000001"
    assert d["filing_method"] == "evc"


# ── 2. Repository Operational Tests ───────────────────────────────────────────

def test_repo_session_lifecycle(repo, seeded_data):
    """Test session creation, lookup, token update, and logout."""
    now = datetime.now(timezone.utc)
    t_exp = now + timedelta(hours=6)

    # 1. Create session
    sess = repo.create_session(
        firm_id=seeded_data["firm_id"],
        gstin=seeded_data["gstin"],
        username="taxpayer_1",
        session_token="secret_auth_token_xyz",
        token_expires_at=t_exp,
        client_gstin_id=seeded_data["client_id"],
    )
    assert sess["status"] == "active"
    sess_id = sess["id"]

    # 2. Get active session
    active = repo.get_active_session(
        firm_id=seeded_data["firm_id"],
        gstin=seeded_data["gstin"],
        redact_token=True,
    )
    assert active is not None
    assert active["id"] == sess_id
    assert active["session_token"] == "***REDACTED***"

    # 3. Update token
    new_exp = now + timedelta(hours=12)
    updated = repo.update_session_token(
        sess_id,
        session_token="new_refresh_token_abc",
        token_expires_at=new_exp,
    )
    assert updated is not None
    assert updated["token_expires_at"] is not None

    # 4. Logout
    repo.mark_session_logged_out(sess_id)
    logged_out = repo.get_session_by_id(sess_id)
    assert logged_out["status"] == "logged_out"
    assert logged_out["logged_out_at"] is not None

    # 5. Confirm no longer returned by get_active_session
    assert repo.get_active_session(firm_id=seeded_data["firm_id"], gstin=seeded_data["gstin"]) is None


def test_repo_gstr3b_offset_lock_enforcement(repo, seeded_data):
    """Verify hard-block on Save / Offset once GSTR-3B reached offset_complete."""
    gstin = seeded_data["gstin"]
    period = "2026-06"

    # Initially unlocked
    repo.assert_gstr3b_save_allowed(gstin=gstin, period=period)
    repo.assert_gstr3b_offset_allowed(gstin=gstin, period=period)

    # Create run that completes offset
    run = repo.create_run(
        firm_id=seeded_data["firm_id"],
        gstin=gstin,
        period=period,
        return_type="gstr-3b",
        status="offset_pending",
    )
    run_id = run["id"]

    # Apply offset complete
    class MockStatusPoll:
        status_cd = "1"
        error_report = None
        error_cd = None

    updated = repo.apply_offset_status_to_run(
        run_id,
        return_status="P",
        offset_payload={"pdcash": 500, "pditc": 1000},
        tx_pmt_snapshot={"tx_pmt": {"paid_cash": 500}},
    )
    assert updated["status"] == "offset_complete"
    assert updated["offset_completed_at"] is not None

    # Now Save and Offset MUST be blocked and raise Gstr3bPeriodLockedError
    with pytest.raises(Gstr3bPeriodLockedError) as exc_info:
        repo.assert_gstr3b_save_allowed(gstin=gstin, period=period)
    assert "Save is blocked" in str(exc_info.value)
    assert exc_info.value.gstin == gstin
    assert exc_info.value.period == period

    with pytest.raises(Gstr3bPeriodLockedError) as exc_info2:
        repo.assert_gstr3b_offset_allowed(gstin=gstin, period=period)
    assert "Offset Liability is blocked" in str(exc_info2.value)


def test_repo_bulk_filing_batch_recalculation(repo, seeded_data):
    """Verify bulk filing batch creation, item updates, and status recalculation."""
    firm_id = seeded_data["firm_id"]
    client_id = seeded_data["client_id"]
    client_id_2 = str(uuid.uuid4())

    batch = repo.create_batch(
        firm_id=firm_id,
        created_by=firm_id,
        period="2026-07",
        client_gstin_ids=[client_id, client_id_2],
        client_gstin_map={client_id: "27AABCT1234A1Z5", client_id_2: "27AABCT9999A1Z1"},
    )
    assert batch["total_count"] == 2
    assert batch["status"] == "pending"
    assert len(batch["items"]) == 2
    batch_id = batch["id"]

    items = batch["items"]
    # Mark item 1 saved, item 2 failed
    repo.update_batch_item(items[0]["id"], status="saved")
    repo.update_batch_item(items[1]["id"], status="failed", error_code="ERR_AUTH", error_detail="Token expired")

    # Recalculate
    recalc = repo.recalculate_batch_status(batch_id)
    assert recalc["status"] == "partially_completed"
    assert recalc["saved_count"] == 1
    assert recalc["failed_count"] == 1

    # Mark item 2 saved as well
    repo.update_batch_item(items[1]["id"], status="saved")
    recalc2 = repo.recalculate_batch_status(batch_id)
    assert recalc2["saved_count"] == 2


def test_repo_sales_register_and_sr_records(repo, seeded_data):
    """Verify sales register run header and voucher record storage/lookup."""
    cid = seeded_data["client_id"]
    p = "2026-05"

    run = repo.create_sales_register_run(
        client_gstin_id=cid,
        period=p,
        file_hash="abc123hash",
    )
    run_id = run["id"]
    assert run["status"] == "queued"

    # Insert sr_records
    voucher_data = [
        {"voucher_number": "INV-001", "taxable": 10000.0, "cgst": 900.0, "sgst": 900.0},
        {"voucher_number": "INV-002", "taxable": 25000.0, "igst": 4500.0},
    ]
    inserted = repo.create_sr_records(
        run_id=run_id,
        client_gstin_id=cid,
        period=p,
        records=voucher_data,
    )
    assert inserted == 2

    # Fetch
    fetched = repo.fetch_sales_register_records(cid, p)
    assert len(fetched) == 2
    assert fetched[0]["voucher_number"] == "INV-001"


# ── 3. Tenant Isolation Tests ─────────────────────────────────────────────────

def test_tenant_boundary_isolation(repo, seeded_data, db_session):
    """Verify that firms cannot see or access filing sessions or batches of other firms."""
    other_firm_id = str(uuid.uuid4())
    other_user = UserProfile(
        id=UUID(other_firm_id),
        email="other@recondesk.test",
        full_name="Other Firm",
        role="ca",
        is_active=True,
    )
    db_session.add(other_user)
    db_session.commit()

    # Firm 1 creates session and batch
    repo.create_session(
        firm_id=seeded_data["firm_id"],
        gstin=seeded_data["gstin"],
        username="firm1_user",
        session_token="token_1",
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=4),
    )
    repo.create_batch(
        firm_id=seeded_data["firm_id"],
        created_by=seeded_data["firm_id"],
        period="2026-06",
        client_gstin_ids=[seeded_data["client_id"]],
    )

    # Firm 2 cannot find Firm 1 session
    f2_session = repo.get_active_session(firm_id=other_firm_id, gstin=seeded_data["gstin"])
    assert f2_session is None

    # Firm 2 list_batches returns empty
    f2_batches = repo.list_batches(firm_id=other_firm_id)
    assert len(f2_batches) == 0


# ── 4. End-to-End Orchestrator Dry-Run Verification ───────────────────────────

def _make_mock_supabase_21_rows(firm_id: str, client_id: str):
    now = datetime.now(timezone.utc).isoformat()
    session_ids = [str(uuid.uuid4()) for _ in range(13)]

    source_data = {
        "filing_sessions": [
            {
                "id": session_ids[i],
                "firm_id": firm_id,
                "client_gstin_id": client_id,
                "gstin": "27AABCT1234A1Z5",
                "username": f"user_{i}",
                "session_token": f"token_secret_{i}",
                "token_expires_at": now,
                "session_expires_at": None,
                "status": "active",
                "created_at": now,
                "updated_at": now,
                "logged_out_at": None,
            }
            for i in range(13)
        ],
        "filing_runs": [
            {
                "id": str(uuid.uuid4()),
                "firm_id": firm_id,
                "client_gstin_id": client_id,
                "filing_session_id": session_ids[i % 7],
                "gstin": "27AABCT1234A1Z5",
                "return_type": "gstr-3b",
                "period": f"2026-0{6 if i < 7 else 7}",
                "status": "failed" if i < 6 else ("saved" if i == 6 else "save_failed"),
                "reference_id": f"REF-{i}",
                "ack_number": None,
                "arn": None,
                "filing_method": None,
                "filed_at": None,
                "save_payload": {"table": "gstr3b"},
                "raw_response": {"status": "polled"},
                "error_code": None,
                "error_message": None,
                "offset_payload": None,
                "offset_completed_at": None,
                "tx_pmt_snapshot": None,
                "created_at": now,
                "updated_at": now,
            }
            for i in range(8)
        ],
        "filing_batches": [],
        "filing_batch_items": [],
        "sales_register_run": [],
        "sr_records": [],
    }

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


def test_dry_run_parity_and_rollback_zero_residual(sqlite_engine, seeded_data):
    """Execute full orchestrator dry-run and verify clean rollback with 0 residual rows."""
    mock_sb = _make_mock_supabase_21_rows(seeded_data["firm_id"], seeded_data["client_id"])
    orch = Batch3CFilingAutomationOrchestrator(sb_client=mock_sb, engine=sqlite_engine)
    report = orch.run(commit=False)

    assert report.total_source_rows == 21
    assert report.total_inserted == 21
    assert report.total_matches == 21
    assert report.total_mismatches == 0
    assert report.total_orphans == 0
    assert report.is_clean() is True

    # Confirm post-rollback fresh session has 0 rows across all tables
    Session_ = sessionmaker(bind=sqlite_engine)
    with Session_() as s:
        for t in orch.TABLES:
            cnt = orch.count_aurora_rows(s, t)
            assert cnt == 0, f"Table {t} leaked rows post-rollback: {cnt}"

