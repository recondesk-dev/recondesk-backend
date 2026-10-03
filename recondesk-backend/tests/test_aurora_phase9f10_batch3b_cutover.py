"""Test Suite for Phase 9F-10: Canonical Batch 3B Application Cutover.

Verifies that Aurora PostgreSQL repository layer and cut-over services behave
deterministically, enforce tenant boundaries, handle atomic claims, and succeed
even when Supabase is completely unavailable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.integrations import Base
from app.repositories.integrations import AuroraIntegrationsRepository
from app.ims.ims_action_store import AuroraImsActionStore, ImsClaimRpcError


@pytest.fixture
def sqlite_repo():
    """Create an in-memory SQLite database initialized with Batch 3B tables."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    repo = AuroraIntegrationsRepository(session_factory=session_factory)
    return repo


def test_tally_bridge_key_lifecycle(sqlite_repo: AuroraIntegrationsRepository):
    """Test creation, lookup, last_synced update, rotation, and revocation of Tally bridge keys."""
    account_id = str(uuid.uuid4())
    api_key_1 = "tbk_test_key_111111111111111111111111"

    # 1. Create key
    key1 = sqlite_repo.create_tally_bridge_key(
        account_id=account_id,
        api_key=api_key_1,
        company_name="Acme Corp",
    )
    assert key1["id"] is not None
    assert str(key1["account_id"]) == account_id
    assert key1["company_name"] == "Acme Corp"
    assert key1["api_key"] == api_key_1
    assert key1["revoked_at"] is None

    # 2. Lookup by API key
    lookup = sqlite_repo.get_tally_bridge_key_by_api_key(api_key_1)
    assert lookup is not None
    assert lookup["id"] == key1["id"]

    # 3. Lookup by ID and account boundary
    by_id = sqlite_repo.get_tally_bridge_key_by_id(key1["id"], account_id=account_id)
    assert by_id is not None
    # Tenant boundary mismatch returns None
    other_acc = str(uuid.uuid4())
    assert sqlite_repo.get_tally_bridge_key_by_id(key1["id"], account_id=other_acc) is None

    # 4. Update last_synced_at
    now = datetime.now(timezone.utc)
    updated = sqlite_repo.update_tally_bridge_key_last_synced(key_id=key1["id"], last_synced_at=now)
    assert updated == 1
    refreshed = sqlite_repo.get_tally_bridge_key_by_id(key1["id"])
    assert refreshed["last_synced_at"] is not None

    # 5. List keys for account
    keys = sqlite_repo.list_tally_bridge_keys_for_account(account_id)
    assert len(keys) == 1

    # 6. Rotate keys (revokes existing active keys)
    rotated = sqlite_repo.rotate_tally_bridge_keys_for_account(account_id)
    assert rotated == 1
    # Revoked key no longer accessible via active api_key lookup
    assert sqlite_repo.get_tally_bridge_key_by_api_key(api_key_1) is None


def test_tally_ledger_masters(sqlite_repo: AuroraIntegrationsRepository):
    """Test upserting Tally ledgers and loading ledger GSTIN map."""
    account_id = str(uuid.uuid4())
    ledgers = [
        {
            "name": "Tata Motors Ltd",
            "gstin": "27AAACT2727Q1ZB",
            "parent_group": "Sundry Creditors",
            "state": "Maharashtra",
            "opening_balance": 150000.50,
            "closing_balance": 50000.00,
        },
        {
            "name": "Infosys Ltd",
            "gstin": "29AAACI1681G1ZQ",
            "parent_group": "Sundry Debtors",
            "state": "Karnataka",
            "opening_balance": 0.0,
            "closing_balance": 20000.00,
        },
    ]

    count = sqlite_repo.upsert_tally_ledgers(account_id, "Test Corp", ledgers)
    assert count == 2

    # Verify map loading
    gstin_map = sqlite_repo.load_tally_ledger_gstin_map(account_id)
    assert gstin_map["Tata Motors Ltd"] == "27AAACT2727Q1ZB"
    assert gstin_map["Infosys Ltd"] == "29AAACI1681G1ZQ"

    # Tenant isolation check
    other_acc = str(uuid.uuid4())
    assert sqlite_repo.load_tally_ledger_gstin_map(other_acc) == {}


def test_client_einvoice_credentials(sqlite_repo: AuroraIntegrationsRepository):
    """Test upserting client e-invoice credentials and session token updating."""
    client_gstin_id = str(uuid.uuid4())

    # Upsert credentials
    creds = sqlite_repo.upsert_client_einvoice_credential(
        client_gstin_id=client_gstin_id,
        einvoice_username="test_user",
        einvoice_password="encrypted_secret_pass",
    )
    assert creds["einvoice_username"] == "test_user"
    assert creds["session_token"] is None

    # Retrieve credentials
    fetched = sqlite_repo.get_client_einvoice_credential(client_gstin_id)
    assert fetched is not None
    assert fetched["einvoice_password"] == "encrypted_secret_pass"

    # Update session token
    expiry = datetime.now(timezone.utc) + timedelta(hours=6)
    ok = sqlite_repo.update_client_einvoice_token(
        client_gstin_id=client_gstin_id,
        session_token="irp_token_xyz_12345",
        session_token_expiry=expiry,
    )
    assert ok is True

    refreshed = sqlite_repo.get_client_einvoice_credential(client_gstin_id)
    assert refreshed["session_token"] == "irp_token_xyz_12345"


def test_einvoice_recon_results(sqlite_repo: AuroraIntegrationsRepository):
    """Test batch inserting and querying e-invoice reconciliation results."""
    client_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    res_id = str(uuid.uuid4())

    items = [
        {
            "id": res_id,
            "run_id": run_id,
            "client_gstin_id": client_id,
            "period": "2026-03",
            "invoice_number": "INV-1001",
            "irn": "a" * 64,
            "irn_status": "ACT",
            "category": "MATCHED",
            "book_value": 10000.00,
            "einvoice_value": 10000.00,
            "details": {"doc_type": "INV"},
        }
    ]

    inserted = sqlite_repo.insert_einvoice_recon_results(items)
    assert inserted == 1

    # List by client and period
    results = sqlite_repo.list_einvoice_recon_results(
        client_gstin_id=client_id, period="2026-03"
    )
    assert len(results) == 1
    assert results[0]["invoice_number"] == "INV-1001"

    # Get by ID
    single = sqlite_repo.get_einvoice_recon_result_by_id(res_id)
    assert single is not None
    assert single["category"] == "MATCHED"

    # Update result
    up = sqlite_repo.update_einvoice_recon_result(
        res_id, {"verification_source": "irp_live_lookup"}
    )
    assert up is not None
    assert up["verification_source"] == "irp_live_lookup"


def test_gst_fetch_log(sqlite_repo: AuroraIntegrationsRepository):
    """Test recording outcomes in gst_fetch_log."""
    client_id = str(uuid.uuid4())
    log_entry = {
        "client_id": client_id,
        "gstin": "27AAACT2727Q1ZB",
        "return_type": "gstr2b",
        "period": "2026-03",
        "section": "b2b",
        "status": "success",
        "error_message": None,
    }

    row = sqlite_repo.insert_gst_fetch_log(log_entry)
    assert row["id"] is not None
    assert row["gstin"] == "27AAACT2727Q1ZB"
    assert row["status"] == "success"


def test_ims_claim_and_store(sqlite_repo: AuroraIntegrationsRepository):
    """Test atomic IMS submission claim semantics and AuroraImsActionStore."""
    store = AuroraImsActionStore(sb=None)
    # Inject test repo
    store._repo = sqlite_repo

    run_id = str(uuid.uuid4())
    inv_id = "INV-2026-001"
    period = "2026-03"
    gstin = "27AAACT2727Q1ZB"

    # 1. First claim succeeds
    claim1 = store.try_claim_submission(
        invoice_id=inv_id,
        period=period,
        gstin=gstin,
        chosen_action="accept",
        run_id=run_id,
    )
    assert claim1 is not None
    assert claim1["status"] == "claiming"
    assert claim1["chosen_action"] == "accept"

    # 2. Concurrent/duplicate claim for same invoice/period/gstin returns None (lost race)
    claim2 = store.try_claim_submission(
        invoice_id=inv_id,
        period=period,
        gstin=gstin,
        chosen_action="reject",
        run_id=run_id,
    )
    assert claim2 is None

    # 3. Find non-failed returns active claim
    active = store.find_non_failed(invoice_id=inv_id, period=period, gstin=gstin)
    assert active is not None
    assert active["status"] == "claiming"

    # 4. Upsert submission (settling to confirmed)
    settled = store.upsert_submission(
        {
            "invoice_id": inv_id,
            "period": period,
            "gstin": gstin,
            "status": "confirmed",
            "chosen_action": "accept",
            "run_id": run_id,
        }
    )
    assert settled["status"] == "confirmed"

    # 5. List confirmed submissions for run
    confirmed_rows = sqlite_repo.list_ims_submissions_for_run(run_id, status="confirmed")
    assert len(confirmed_rows) == 1
    assert confirmed_rows[0]["invoice_id"] == inv_id


def test_full_supabase_outage_resilience(sqlite_repo: AuroraIntegrationsRepository):
    """Verify that all cut-over operations complete successfully when Supabase is completely None/unreachable."""
    store = AuroraImsActionStore(sb=None)
    store._repo = sqlite_repo

    # Attempt find on nonexistent row
    assert store.find_non_failed(invoice_id="NO_SUCH_INV", period="2026-03", gstin="27AAACT2727Q1ZB") is None

    # Upsert and claim works 100% without Supabase
    claimed = store.try_claim_submission(
        invoice_id="INV-AIR-01",
        period="2026-03",
        gstin="27AAACT2727Q1ZB",
        chosen_action="accept",
    )
    assert claimed is not None
    assert claimed["invoice_id"] == "INV-AIR-01"
