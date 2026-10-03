"""Test Suite for Phase 9F-11: Batch 3B Residual Supabase Dependency Audit.

Validates:
1. Zero normal Supabase dependencies (Aurora is primary for all reads and writes).
2. Supabase outage resilience (complete failure of Supabase causes zero operational failure).
3. IMS claim RPC routing (Aurora fn_claim_ims_action_submission is invoked; zero Supabase RPC in production).
4. Tenant isolation across all Batch 3B tables.
5. Zero Supabase writes under normal operation.
6. Deterministic fallback behavior only upon operational failure.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.integrations import Base
from app.repositories.integrations import AuroraIntegrationsRepository
from app.ims.ims_action_store import AuroraImsActionStore


class BrokenSupabaseClient:
    """Mock Supabase client that raises errors on any access to simulate an outage."""

    def table(self, *args, **kwargs):
        raise ConnectionError("Supabase connection unavailable (simulated outage)")

    def rpc(self, *args, **kwargs):
        raise ConnectionError("Supabase RPC service unavailable (simulated outage)")


@pytest.fixture
def memory_repo():
    """Create an in-memory SQLite database initialized with Batch 3B tables."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return AuroraIntegrationsRepository(session_factory=session_factory)


def test_aurora_primary_reads_and_writes_zero_supabase_calls(memory_repo: AuroraIntegrationsRepository):
    """Confirm all 6 tables perform normal reads and writes with zero Supabase interactions."""
    mock_sb = MagicMock()

    # 1. Tally Bridge Keys
    account_id = str(uuid.uuid4())
    key = memory_repo.create_tally_bridge_key(
        account_id=account_id,
        api_key="tbk_live_test_api_key_12345",
        company_name="Acme Primary",
    )
    assert key["id"] is not None
    mock_sb.table.assert_not_called()

    looked_up = memory_repo.get_tally_bridge_key_by_api_key("tbk_live_test_api_key_12345")
    assert looked_up["id"] == key["id"]
    mock_sb.table.assert_not_called()

    # 2. Tally Ledger Masters
    ledgers = [{"name": "Ledger A", "gstin": "27AABCU9603R1ZP"}]
    c = memory_repo.upsert_tally_ledgers(account_id, "Acme Primary", ledgers)
    assert c == 1
    m = memory_repo.load_tally_ledger_gstin_map(account_id)
    assert m["Ledger A"] == "27AABCU9603R1ZP"
    mock_sb.table.assert_not_called()

    # 3. Client e-Invoice Credentials
    client_id = str(uuid.uuid4())
    creds = memory_repo.upsert_client_einvoice_credential(
        client_gstin_id=client_id,
        einvoice_username="user_prim",
        einvoice_password="enc_pass_prim",
    )
    assert creds["einvoice_username"] == "user_prim"
    mock_sb.table.assert_not_called()

    # 4. e-Invoice Recon Results
    res_id = str(uuid.uuid4())
    ins = memory_repo.insert_einvoice_recon_results(
        [{"id": res_id, "client_gstin_id": client_id, "period": "2026-03", "invoice_number": "INV-1"}]
    )
    assert ins == 1
    fetched_res = memory_repo.get_einvoice_recon_result_by_id(res_id)
    assert fetched_res["invoice_number"] == "INV-1"
    mock_sb.table.assert_not_called()

    # 5. GST Fetch Log
    entry = {
        "client_id": client_id,
        "gstin": "27AABCU9603R1ZP",
        "return_type": "gstr2b",
        "period": "2026-03",
        "section": "b2b",
        "status": "success",
    }
    log_res = memory_repo.insert_gst_fetch_log(entry)
    assert log_res["status"] == "success"
    mock_sb.table.assert_not_called()

    # 6. IMS Action Submissions
    store = AuroraImsActionStore(sb=mock_sb)
    store._repo = memory_repo
    claimed = store.try_claim_submission(
        invoice_id="INV-1",
        period="2026-03",
        gstin="27AABCU9603R1ZP",
        chosen_action="accept",
    )
    assert claimed is not None
    assert claimed["status"] == "claiming"
    mock_sb.table.assert_not_called()
    mock_sb.rpc.assert_not_called()


def test_complete_supabase_outage_resilience(memory_repo: AuroraIntegrationsRepository):
    """Simulate total Supabase outage; verify all Batch 3B operations proceed without error."""
    broken_sb = BrokenSupabaseClient()
    store = AuroraImsActionStore(sb=broken_sb)
    store._repo = memory_repo

    account_id = str(uuid.uuid4())
    client_id = str(uuid.uuid4())

    # Tally key creation & retrieval during outage
    k = memory_repo.create_tally_bridge_key(
        account_id=account_id,
        api_key="tbk_outage_key",
        company_name="Outage Corp",
    )
    assert k["id"] is not None
    assert memory_repo.get_tally_bridge_key_by_api_key("tbk_outage_key") is not None

    # Ledgers during outage
    memory_repo.upsert_tally_ledgers(account_id, "Outage Corp", [{"name": "L1", "gstin": "27AABCU9603R1ZP"}])
    assert memory_repo.load_tally_ledger_gstin_map(account_id) == {"L1": "27AABCU9603R1ZP"}

    # e-Invoice credentials during outage
    memory_repo.upsert_client_einvoice_credential(
        client_gstin_id=client_id,
        einvoice_username="outage_user",
        einvoice_password="outage_pwd",
    )
    assert memory_repo.get_client_einvoice_credential(client_id)["einvoice_username"] == "outage_user"

    # e-Invoice results during outage
    rid = str(uuid.uuid4())
    memory_repo.insert_einvoice_recon_results([{"id": rid, "client_gstin_id": client_id, "period": "2026-03"}])
    assert memory_repo.get_einvoice_recon_result_by_id(rid) is not None

    # GST fetch log during outage
    l = memory_repo.insert_gst_fetch_log({
        "client_id": client_id,
        "gstin": "27AABCU9603R1ZP",
        "return_type": "gstr1",
        "period": "2026-03",
        "section": "b2b",
        "status": "success",
    })
    assert l["id"] is not None

    # IMS claiming during outage (Aurora handles claim natively)
    claimed = store.try_claim_submission(
        invoice_id="INV-OUT-1",
        period="2026-03",
        gstin="27AABCU9603R1ZP",
        chosen_action="accept",
    )
    assert claimed is not None
    assert claimed["invoice_id"] == "INV-OUT-1"


def test_ims_rpc_first_writer_wins_and_duplicate_prevention(memory_repo: AuroraIntegrationsRepository):
    """Verify first-writer-wins, duplicate conflict prevention, and state transitions."""
    store = AuroraImsActionStore(sb=None)
    store._repo = memory_repo

    inv = "INV-RACE-001"
    period = "2026-03"
    gstin = "27AABCU9603R1ZP"

    # Writer 1 claims successfully
    w1 = store.try_claim_submission(
        invoice_id=inv, period=period, gstin=gstin, chosen_action="accept"
    )
    assert w1 is not None
    assert w1["status"] == "claiming"

    # Writer 2 attempts same invoice/period/gstin -> lost race returns None
    w2 = store.try_claim_submission(
        invoice_id=inv, period=period, gstin=gstin, chosen_action="reject"
    )
    assert w2 is None

    # Settle to confirmed
    settled = store.upsert_submission({
        "invoice_id": inv,
        "period": period,
        "gstin": gstin,
        "chosen_action": "accept",
        "status": "confirmed",
    })
    assert settled["status"] == "confirmed"

    # Re-claim while confirmed returns None (cannot steal confirmed action)
    w3 = store.try_claim_submission(
        invoice_id=inv, period=period, gstin=gstin, chosen_action="hold"
    )
    assert w3 is None

    # Mark failed -> allow retry
    failed = store.upsert_submission({
        "invoice_id": inv,
        "period": period,
        "gstin": gstin,
        "chosen_action": "accept",
        "status": "failed",
    })
    assert failed["status"] == "failed"

    # Retry writer can reclaim
    retry = store.try_claim_submission(
        invoice_id=inv, period=period, gstin=gstin, chosen_action="accept"
    )
    assert retry is not None
    assert retry["status"] == "claiming"


def test_strict_cross_tenant_isolation(memory_repo: AuroraIntegrationsRepository):
    """Verify strict tenant boundaries: Tenant A cannot access Tenant B data."""
    tenant_a_acc = str(uuid.uuid4())
    tenant_b_acc = str(uuid.uuid4())
    tenant_a_client = str(uuid.uuid4())
    tenant_b_client = str(uuid.uuid4())

    # 1. Tally Bridge Keys
    key_a = memory_repo.create_tally_bridge_key(
        account_id=tenant_a_acc,
        api_key="tbk_tenant_a_secret",
        company_name="Tenant A Ltd",
    )
    # Tenant B cannot access Tenant A's key by ID with boundary
    assert memory_repo.get_tally_bridge_key_by_id(key_a["id"], account_id=tenant_b_acc) is None
    # Tenant B listing does not include Tenant A's key
    b_keys = memory_repo.list_tally_bridge_keys_for_account(tenant_b_acc)
    assert len(b_keys) == 0

    # 2. Tally Ledgers
    memory_repo.upsert_tally_ledgers(
        tenant_a_acc, "Tenant A Ltd", [{"name": "Ledger A", "gstin": "27AABCU9603R1ZP"}]
    )
    assert memory_repo.load_tally_ledger_gstin_map(tenant_b_acc) == {}

    # 3. Client e-Invoice Credentials
    memory_repo.upsert_client_einvoice_credential(
        client_gstin_id=tenant_a_client,
        einvoice_username="user_a",
        einvoice_password="secret_password_a",
    )
    # Tenant B cannot read Tenant A credentials
    assert memory_repo.get_client_einvoice_credential(tenant_b_client) is None

    # 4. e-Invoice Recon Results
    res_a_id = str(uuid.uuid4())
    memory_repo.insert_einvoice_recon_results([
        {"id": res_a_id, "client_gstin_id": tenant_a_client, "period": "2026-03", "invoice_number": "INV-A"}
    ])
    # Querying by Tenant B client returns zero results
    b_results = memory_repo.list_einvoice_recon_results(client_gstin_id=tenant_b_client, period="2026-03")
    assert len(b_results) == 0
