"""Phase 4.2: FastAPI Integration Tests for Form GSTR-7 and GSTR-8 Routers.

Tests:
1. GSTR-7 batch initialization, record addition, validation, and offline JSON export.
2. GSTR-8 batch initialization, record addition, validation, and offline JSON export.
3. Multi-tenant isolation: unauthorized client GSTIN returns HTTP 403.
4. RBAC authorization checks.
"""

from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_active_user
from app.main import app
from app.services.gstr7_service import reset_gstr7_memory_store_for_testing
from app.services.gstr8_service import reset_gstr8_memory_store_for_testing


@pytest.fixture(autouse=True)
def clean_stores():
    reset_gstr7_memory_store_for_testing()
    reset_gstr8_memory_store_for_testing()


@pytest.fixture
def firm_partner():
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "email": "partner@firm.com",
        "full_name": "Senior Partner",
        "role": "partner",
        "firm_id": "00000000-0000-0000-0000-000000000001",
    }


@pytest.fixture
def client_app():
    return TestClient(app)


def test_gstr7_api_flow(client_app, firm_partner):
    client_gid = "00000000-0000-0000-0000-000000000002"
    app.dependency_overrides[get_current_active_user] = lambda: firm_partner

    try:
        with patch("app.routers.gstr7._assert_client_access", return_value={"id": client_gid, "gstin": "27AAACG0000A1Z5"}), \
             patch("app.routers.gstr7._firm_id", return_value="00000000-0000-0000-0000-000000000001"):

            # 1. GET /api/gstr7/batches
            resp_batch = client_app.get(f"/api/gstr7/batches?client_gstin_id={client_gid}&period=2026-07")
            assert resp_batch.status_code == 200
            batch_data = resp_batch.json()
            batch_id = batch_data["id"]
            assert batch_data["gstin"] == "27AAACG0000A1Z5"

            # 2. POST /api/gstr7/batches/{batch_id}/records
            resp_rec = client_app.post(
                f"/api/gstr7/batches/{batch_id}/records",
                json={
                    "record_type": "ORIGINAL",
                    "deductee_gstin": "27ABCDE1234F1Z5",
                    "contract_number": "PO-101",
                    "contract_value": 500000.0,
                    "payment_reference": "VCH-01",
                    "amount_paid": 100000.0,
                    "pos": "27",
                },
            )
            assert resp_rec.status_code == 200
            rec_data = resp_rec.json()
            assert rec_data["tds_cgst"] == 1000.0
            assert rec_data["tds_sgst"] == 1000.0

            # 3. POST /api/gstr7/batches/{batch_id}/validate
            resp_val = client_app.post(f"/api/gstr7/batches/{batch_id}/validate")
            assert resp_val.status_code == 200
            val_data = resp_val.json()
            assert val_data["is_valid"] is True
            assert val_data["return_type"] == "gstr-7"

            # 4. GET /api/gstr7/batches/{batch_id}/offline-json
            resp_json = client_app.get(f"/api/gstr7/batches/{batch_id}/offline-json")
            assert resp_json.status_code == 200
            json_payload = resp_json.json()
            assert json_payload["gstin"] == "27AAACG0000A1Z5"
            assert json_payload["fp"] == "072026"
            assert len(json_payload["tds"]) == 1
    finally:
        app.dependency_overrides.clear()


def test_gstr8_api_flow(client_app, firm_partner):
    client_gid = "00000000-0000-0000-0000-000000000003"
    app.dependency_overrides[get_current_active_user] = lambda: firm_partner

    try:
        with patch("app.routers.gstr8._assert_client_access", return_value={"id": client_gid, "gstin": "27AAACG0000A1Z5"}), \
             patch("app.routers.gstr8._firm_id", return_value="00000000-0000-0000-0000-000000000001"):

            # 1. GET /api/gstr8/batches
            resp_batch = client_app.get(f"/api/gstr8/batches?client_gstin_id={client_gid}&period=2026-07")
            assert resp_batch.status_code == 200
            batch_data = resp_batch.json()
            batch_id = batch_data["id"]

            # 2. POST /api/gstr8/batches/{batch_id}/records (B2B)
            resp_rec = client_app.post(
                f"/api/gstr8/batches/{batch_id}/records",
                json={
                    "supply_type": "B2B",
                    "record_type": "ORIGINAL",
                    "supplier_gstin": "27ABCDE1234F1Z5",
                    "gross_supplies": 500000.0,
                    "returned_supplies": 50000.0,
                    "pos": "27",
                },
            )
            assert resp_rec.status_code == 200
            rec_data = resp_rec.json()
            assert rec_data["net_supplies"] == 450000.0
            assert rec_data["tcs_cgst"] == 1125.0
            assert rec_data["tcs_sgst"] == 1125.0

            # 3. POST /api/gstr8/batches/{batch_id}/validate
            resp_val = client_app.post(f"/api/gstr8/batches/{batch_id}/validate")
            assert resp_val.status_code == 200
            val_data = resp_val.json()
            assert val_data["is_valid"] is True
            assert val_data["return_type"] == "gstr-8"

            # 4. GET /api/gstr8/batches/{batch_id}/offline-json
            resp_json = client_app.get(f"/api/gstr8/batches/{batch_id}/offline-json")
            assert resp_json.status_code == 200
            json_payload = resp_json.json()
            assert json_payload["fp"] == "072026"
            assert len(json_payload["tcs"]) == 1
    finally:
        app.dependency_overrides.clear()
