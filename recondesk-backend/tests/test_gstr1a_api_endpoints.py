"""FastAPI endpoint integration tests for ReconDesk Phase 4.1:
GSTR-1A Amendment Intelligence & Filing Router.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth import get_current_active_user


@pytest.fixture
def preparer_user():
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "email": "preparer@firm.com",
        "full_name": "Pooja Preparer",
        "role": "preparer",
        "firm_id": "00000000-0000-0000-0000-000000000001",
    }


@pytest.fixture
def manager_user():
    return {
        "id": "22222222-2222-2222-2222-222222222222",
        "email": "manager@firm.com",
        "full_name": "Manish Manager",
        "role": "manager",
        "firm_id": "00000000-0000-0000-0000-000000000001",
    }


@pytest.fixture
def client_app():
    return TestClient(app)


def test_get_window_endpoint(client_app, preparer_user):
    """GET /api/v1/gstr1a/{client_gstin_id}/{period}/window returns window status."""
    client_gid = "00000000-0000-0000-0000-000000000002"
    app.dependency_overrides[get_current_active_user] = lambda: preparer_user

    try:
        with patch("app.routers.gstr1a._assert_client_access", return_value={"id": client_gid, "gstin": "27AAPFU0939F1ZV", "filing_frequency": "monthly"}), \
             patch("app.routers.gstr1a.get_supabase") as mock_sb:

            # Mock filing_runs lookup
            mock_runs = MagicMock()
            mock_runs.data = [{"return_type": "GSTR-1", "status": "filed", "filed_at": "2026-01-10"}]

            table_mock = MagicMock()
            table_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_runs
            mock_sb.return_value.table.return_value = table_mock

            resp = client_app.get(f"/api/v1/gstr1a/{client_gid}/2026-01/window")
            assert resp.status_code == 200
            data = resp.json()
            assert data["client_gstin_id"] == client_gid
            assert data["gstin"] == "27AAPFU0939F1ZV"
            assert "window" in data
            assert data["window"]["filing_frequency"] == "monthly"
    finally:
        app.dependency_overrides.clear()


def test_add_and_export_item_endpoint(client_app, preparer_user):
    """POST /items adds an item and /export-json outputs GSTN format."""
    client_gid = "00000000-0000-0000-0000-000000000002"
    app.dependency_overrides[get_current_active_user] = lambda: preparer_user

    try:
        with patch("app.routers.gstr1a._assert_client_access", return_value={"id": client_gid, "gstin": "27AAPFU0939F1ZV"}), \
             patch("app.routers.gstr1a.resolve_firm_id", return_value="00000000-0000-0000-0000-000000000001"), \
             patch("app.routers.gstr1a.get_supabase"), \
             patch("app.routers.gstr1a.add_or_update_amendment_item_sync") as mock_add, \
             patch("app.routers.gstr1a.get_or_create_batch_sync") as mock_get_batch, \
             patch("app.routers.gstr1a.build_gstr1a_offline_json") as mock_build_json:

            mock_add.return_value = {"id": "item-1", "table_name": "4A", "action_type": "ADDITION"}
            mock_get_batch.return_value = {"id": "batch-1", "gstin": "27AAPFU0939F1ZV", "figures_digest": "hash999"}
            mock_build_json.return_value = {"gstin": "27AAPFU0939F1ZV", "fp": "012026", "version": "GSTR1A_v1.0"}

            # Test add item
            payload = {
                "table_name": "4A",
                "action_type": "ADDITION",
                "amended_invoice_number": "INV-100",
                "amended_invoice_date": "2026-01-05",
                "amended_payload": {"taxable_value": 50000.0, "igst": 9000.0},
            }
            resp_add = client_app.post(f"/api/v1/gstr1a/{client_gid}/2026-01/items", json=payload)
            assert resp_add.status_code == 200
            assert resp_add.json()["success"] is True

            # Test export JSON
            resp_export = client_app.post(f"/api/v1/gstr1a/{client_gid}/2026-01/export-json")
            assert resp_export.status_code == 200
            export_data = resp_export.json()
            assert "filename" in export_data
            assert "payload" in export_data
            assert export_data["payload"]["version"] == "GSTR1A_v1.0"
    finally:
        app.dependency_overrides.clear()
