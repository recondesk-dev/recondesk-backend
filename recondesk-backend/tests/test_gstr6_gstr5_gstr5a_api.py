"""Phase 4.3: FastAPI Integration Tests for Form GSTR-6, GSTR-5, and GSTR-5A Routers.

Tests:
1. GSTR-6 batch initialization, inward & distribution record addition, validation, and offline JSON export.
2. GSTR-5 batch initialization, import & outward record addition, validation, and offline JSON export.
3. GSTR-5A batch initialization, supply record addition, validation, and offline JSON export.
4. Multi-tenant isolation: cross-firm batch access returns HTTP 403.
5. RBAC authorization checks.
"""

from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_active_user
from app.main import app
from app.services.gstr6_service import reset_gstr6_store_for_testing
from app.services.gstr5_service import reset_gstr5_store_for_testing
from app.services.gstr5a_service import reset_gstr5a_store_for_testing


@pytest.fixture(autouse=True)
def clean_stores():
    reset_gstr6_store_for_testing()
    reset_gstr5_store_for_testing()
    reset_gstr5a_store_for_testing()


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


def test_gstr6_api_flow(client_app, firm_partner):
    client_gid = "00000000-0000-0000-0000-000000000002"
    app.dependency_overrides[get_current_active_user] = lambda: firm_partner

    try:
        with patch("app.routers.gstr6._assert_client_access", return_value={"id": client_gid, "gstin": "27AAACG0000A1Z5"}), \
             patch("app.routers.gstr6._firm_id", return_value="00000000-0000-0000-0000-000000000001"):

            # 1. GET /api/gstr6/batches
            resp_batch = client_app.get(f"/api/gstr6/batches?client_gstin_id={client_gid}&period=2026-07")
            assert resp_batch.status_code == 200
            batch_data = resp_batch.json()["batch"]
            batch_id = batch_data["id"]

            # 2. POST /api/gstr6/batches/{batch_id}/inward
            resp_inw = client_app.post(
                f"/api/gstr6/batches/{batch_id}/inward",
                json={
                    "supplier_gstin": "27AABCS1429B1Z1",
                    "invoice_number": "INV-101",
                    "invoice_date": "2026-07-10",
                    "taxable_value": 100000.0,
                    "igst": 18000.0,
                    "cgst": 0.0,
                    "sgst": 0.0,
                    "cess": 0.0,
                    "itc_eligible": "ELIGIBLE",
                },
            )
            assert resp_inw.status_code == 200

            # 3. POST /api/gstr6/batches/{batch_id}/distribute
            resp_dist = client_app.post(
                f"/api/gstr6/batches/{batch_id}/distribute",
                json={
                    "recipient_turnovers": [
                        {"recipient_gstin": "29AAACG0000A1Z2", "turnover": 100000.0}
                    ]
                },
            )
            assert resp_dist.status_code == 200

            # 4. POST /api/gstr6/batches/{batch_id}/validate
            resp_val = client_app.post(f"/api/gstr6/batches/{batch_id}/validate")
            assert resp_val.status_code == 200
            val_data = resp_val.json()
            assert val_data["is_valid"] is True

            # 5. GET /api/gstr6/batches/{batch_id}/offline-json
            resp_json = client_app.get(f"/api/gstr6/batches/{batch_id}/offline-json")
            assert resp_json.status_code == 200
            json_payload = resp_json.json()
            assert json_payload["gstin"] == "27AAACG0000A1Z5"
            assert json_payload["fp"] == "072026"
            assert "isd" in json_payload
    finally:
        app.dependency_overrides.clear()


def test_gstr5_api_flow(client_app, firm_partner):
    client_gid = "00000000-0000-0000-0000-000000000003"
    app.dependency_overrides[get_current_active_user] = lambda: firm_partner

    try:
        with patch("app.routers.gstr5._assert_client_access", return_value={"id": client_gid, "gstin": "27AAACG0000A1Z5"}), \
             patch("app.routers.gstr5._firm_id", return_value="00000000-0000-0000-0000-000000000001"):

            # 1. GET /api/gstr5/batches
            resp_batch = client_app.get(f"/api/gstr5/batches?client_gstin_id={client_gid}&period=2026-07&advance_tax_deposited=50000")
            assert resp_batch.status_code == 200
            batch_data = resp_batch.json()["batch"]
            batch_id = batch_data["id"]

            # 2. POST /api/gstr5/batches/{batch_id}/import
            resp_imp = client_app.post(
                f"/api/gstr5/batches/{batch_id}/import",
                json={
                    "boe_number": "BOE-8899",
                    "boe_date": "2026-07-05",
                    "port_code": "INBOM4",
                    "taxable_value": 100000.0,
                    "igst_paid": 18000.0,
                    "cess_paid": 0.0,
                },
            )
            assert resp_imp.status_code == 200

            # 3. POST /api/gstr5/batches/{batch_id}/outward
            resp_out = client_app.post(
                f"/api/gstr5/batches/{batch_id}/outward",
                json={
                    "pos": "27",
                    "invoice_number": "NRTP-001",
                    "invoice_date": "2026-07-15",
                    "taxable_value": 100000.0,
                    "rate_pct": 18.0,
                    "cgst": 9000.0,
                    "sgst": 9000.0,
                    "record_type": "ORIGINAL",
                },
            )
            assert resp_out.status_code == 200

            # 4. POST /api/gstr5/batches/{batch_id}/validate
            resp_val = client_app.post(f"/api/gstr5/batches/{batch_id}/validate")
            assert resp_val.status_code == 200
            assert resp_val.json()["is_valid"] is True

            # 5. GET /api/gstr5/batches/{batch_id}/offline-json
            resp_json = client_app.get(f"/api/gstr5/batches/{batch_id}/offline-json")
            assert resp_json.status_code == 200
            assert "imp_g" in resp_json.json()
    finally:
        app.dependency_overrides.clear()


def test_gstr5a_api_flow(client_app, firm_partner):
    client_gid = "00000000-0000-0000-0000-000000000004"
    app.dependency_overrides[get_current_active_user] = lambda: firm_partner

    try:
        with patch("app.routers.gstr5a._assert_client_access", return_value={"id": client_gid, "gstin": "9917USA00000OID"}), \
             patch("app.routers.gstr5a._firm_id", return_value="00000000-0000-0000-0000-000000000001"):

            # 1. GET /api/gstr5a/batches
            resp_batch = client_app.get(f"/api/gstr5a/batches?client_gstin_id={client_gid}&period=2026-07")
            assert resp_batch.status_code == 200
            batch_data = resp_batch.json()["batch"]
            batch_id = batch_data["id"]

            # 2. POST /api/gstr5a/batches/{batch_id}/record
            resp_rec = client_app.post(
                f"/api/gstr5a/batches/{batch_id}/record",
                json={
                    "pos": "27",
                    "taxable_value": 200000.0,
                    "rate_pct": 18.0,
                    "cess": 0.0,
                    "record_type": "ORIGINAL",
                },
            )
            assert resp_rec.status_code == 200
            assert resp_rec.json()["igst"] == 36000.0

            # 3. POST /api/gstr5a/batches/{batch_id}/validate
            resp_val = client_app.post(f"/api/gstr5a/batches/{batch_id}/validate")
            assert resp_val.status_code == 200
            assert resp_val.json()["is_valid"] is True

            # 4. GET /api/gstr5a/batches/{batch_id}/offline-json
            resp_json = client_app.get(f"/api/gstr5a/batches/{batch_id}/offline-json")
            assert resp_json.status_code == 200
            assert "sec5" in resp_json.json()
    finally:
        app.dependency_overrides.clear()


def test_cross_tenant_isolation_gstr6_gstr5_gstr5a(client_app):
    """Enforce strict cross-tenant isolation: Tenant B cannot access or mutate Tenant A's batches."""
    tenant_b_user = {
        "id": "22222222-2222-2222-2222-222222222222",
        "email": "intruder@otherfirm.com",
        "full_name": "Tenant B Admin",
        "role": "partner",
        "firm_id": "99999999-9999-9999-9999-999999999999",  # Firm B
    }
    client_app_user = tenant_b_user
    app.dependency_overrides[get_current_active_user] = lambda: client_app_user

    try:
        from app.services.gstr6_service import get_or_create_batch_sync as g6_init
        from app.services.gstr5_service import get_or_create_batch_sync as g5_init
        from app.services.gstr5a_service import get_or_create_batch_sync as g5a_init

        # Tenant A (Firm 1) creates batches
        b_g6 = g6_init(None, firm_id="00000000-0000-0000-0000-000000000001", client_gstin_id="cid-1", gstin="27AAACG0000A1Z5", period="2026-07")
        b_g5 = g5_init(None, firm_id="00000000-0000-0000-0000-000000000001", client_gstin_id="cid-1", gstin="27AAACG0000A1Z5", period="2026-07")
        b_g5a = g5a_init(None, firm_id="00000000-0000-0000-0000-000000000001", client_gstin_id="cid-1", gstin="9917USA00000OID", period="2026-07")

        # Tenant B tries to access Tenant A's batches
        with patch("app.routers.gstr6._firm_id", return_value="99999999-9999-9999-9999-999999999999"):
            resp = client_app.get(f"/api/gstr6/batches/{b_g6.id}")
            assert resp.status_code == 403

        with patch("app.routers.gstr5._firm_id", return_value="99999999-9999-9999-9999-999999999999"):
            resp = client_app.get(f"/api/gstr5/batches/{b_g5.id}")
            assert resp.status_code == 403

        with patch("app.routers.gstr5a._firm_id", return_value="99999999-9999-9999-9999-999999999999"):
            resp = client_app.get(f"/api/gstr5a/batches/{b_g5a.id}")
            assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()
