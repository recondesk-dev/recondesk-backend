"""Phase 4.4: FastAPI Integration Tests for Form GSTR-10 and GSTR-11 Routers.

Tests:
1. GSTR-10 batch initialization, stock record addition (8A, 8D), validation, and offline JSON export.
2. GSTR-11 batch initialization, inward invoice (3A) & CDN (3B) addition, validation, and offline JSON export.
3. Multi-tenant isolation: cross-firm batch access returns HTTP 403 Forbidden.
"""

from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_active_user
from app.main import app
from app.services.gstr10_service import reset_gstr10_store_for_testing
from app.services.gstr11_service import reset_gstr11_store_for_testing


@pytest.fixture(autouse=True)
def clean_stores():
    reset_gstr10_store_for_testing()
    reset_gstr11_store_for_testing()


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
def other_firm_partner():
    return {
        "id": "22222222-2222-2222-2222-222222222222",
        "email": "intruder@otherfirm.com",
        "full_name": "Other Firm Partner",
        "role": "partner",
        "firm_id": "99999999-9999-9999-9999-999999999999",
    }


@pytest.fixture
def client_app():
    return TestClient(app)


def test_gstr10_api_flow(client_app, firm_partner):
    client_gid = "00000000-0000-0000-0000-000000000002"
    app.dependency_overrides[get_current_active_user] = lambda: firm_partner

    try:
        with patch("app.routers.gstr10._assert_client_access", return_value={"id": client_gid, "gstin": "27AAACG0000A1Z5"}), \
             patch("app.routers.gstr10._firm_id", return_value="00000000-0000-0000-0000-000000000001"):

            # 1. Initialize batch: GET /api/gstr10/batches
            resp_batch = client_app.get(
                f"/api/gstr10/batches?client_gstin_id={client_gid}&period=2026-10"
                "&cancellation_order_number=ORD-101&effective_cancellation_date=2026-08-31"
            )
            assert resp_batch.status_code == 200
            batch_data = resp_batch.json()["batch"]
            batch_id = batch_data["id"]

            # 2. Add Table 8A stock item: POST /api/gstr10/batches/{batch_id}/stock-records
            resp_stock_8a = client_app.post(
                f"/api/gstr10/batches/{batch_id}/stock-records",
                json={
                    "item_type": "8A",
                    "supplier_gstin": "27AABCU9603R1ZX",
                    "invoice_number": "INV-100",
                    "invoice_date": "2026-08-15",
                    "description": "Component stock",
                    "uqc": "NOS",
                    "quantity": 100,
                    "taxable_value": 100000.0,
                    "reverse_cgst": 9000.0,
                    "reverse_sgst": 9000.0,
                    "reverse_igst": 0.0,
                    "reverse_cess": 0.0,
                },
            )
            assert resp_stock_8a.status_code == 200

            # 3. Add Table 8D stock item with CA certification
            resp_stock_8d = client_app.post(
                f"/api/gstr10/batches/{batch_id}/stock-records",
                json={
                    "item_type": "8D",
                    "description": "Legacy inventory without invoices",
                    "uqc": "KGS",
                    "quantity": 50,
                    "taxable_value": 50000.0,
                    "reverse_igst": 9000.0,
                    "reverse_cgst": 0.0,
                    "reverse_sgst": 0.0,
                    "reverse_cess": 0.0,
                    "ca_name": "CA Rajesh Mehta",
                    "ca_membership_number": "089123",
                },
            )
            assert resp_stock_8d.status_code == 200

            # 4. Get batch summary: GET /api/gstr10/batches/{batch_id}
            resp_sum = client_app.get(f"/api/gstr10/batches/{batch_id}")
            assert resp_sum.status_code == 200
            s_data = resp_sum.json()
            assert len(s_data["stock_records"]) == 2
            assert s_data["stock_summary"]["total_reversal_liability"] == 27000.0

            # 5. Pre-filing validation: POST /api/gstr10/batches/{batch_id}/validate
            resp_val = client_app.post(f"/api/gstr10/batches/{batch_id}/validate")
            assert resp_val.status_code == 200
            val_data = resp_val.json()["validation"]
            assert val_data["is_valid"] is True
            assert val_data["statutory_checks"]["ca_certification_rule44_3"] == "PASSED"

            # 6. Export offline JSON: GET /api/gstr10/batches/{batch_id}/offline-json
            resp_json = client_app.get(f"/api/gstr10/batches/{batch_id}/offline-json")
            assert resp_json.status_code == 200
            offline = resp_json.json()
            assert offline["gstin"] == "27AAACG0000A1Z5"
            assert len(offline["sec8"]["inputs_in_stock_8a"]) == 1
            assert len(offline["sec8"]["inputs_no_invoice_8d"]) == 1
    finally:
        app.dependency_overrides.clear()


def test_gstr11_api_flow(client_app, firm_partner):
    client_gid = "00000000-0000-0000-0000-000000000003"
    app.dependency_overrides[get_current_active_user] = lambda: firm_partner

    try:
        with patch("app.routers.gstr11._assert_client_access", return_value={"id": client_gid, "gstin": "0717USA00001UN1"}), \
             patch("app.routers.gstr11._firm_id", return_value="00000000-0000-0000-0000-000000000001"):

            # 1. Initialize batch: GET /api/gstr11/batches
            resp_batch = client_app.get(f"/api/gstr11/batches?client_gstin_id={client_gid}&period=2026-10")
            assert resp_batch.status_code == 200
            batch_data = resp_batch.json()["batch"]
            batch_id = batch_data["id"]

            # 2. Add Table 3A Inward Invoice: POST /api/gstr11/batches/{batch_id}/inward-supplies
            resp_inv = client_app.post(
                f"/api/gstr11/batches/{batch_id}/inward-supplies",
                json={
                    "supply_type": "3A",
                    "supplier_gstin": "27AABCU9603R1ZX",
                    "supplier_name": "Official Supplier",
                    "doc_number": "INV-9901",
                    "doc_date": "2026-10-05",
                    "taxable_value": 100000.0,
                    "cgst": 9000.0,
                    "sgst": 9000.0,
                    "igst": 0.0,
                    "cess": 0.0,
                    "is_eligible_for_refund": True,
                },
            )
            assert resp_inv.status_code == 200

            # 3. Add Table 3B Credit Note: POST /api/gstr11/batches/{batch_id}/inward-supplies
            resp_cdn = client_app.post(
                f"/api/gstr11/batches/{batch_id}/inward-supplies",
                json={
                    "supply_type": "3B",
                    "supplier_gstin": "27AABCU9603R1ZX",
                    "doc_number": "CN-01",
                    "doc_date": "2026-10-15",
                    "cdn_type": "C",
                    "original_invoice_number": "INV-9901",
                    "original_invoice_date": "2026-10-05",
                    "taxable_value": 10000.0,
                    "cgst": 900.0,
                    "sgst": 900.0,
                    "igst": 0.0,
                    "cess": 0.0,
                    "is_eligible_for_refund": True,
                },
            )
            assert resp_cdn.status_code == 200

            # 4. Get batch summary: GET /api/gstr11/batches/{batch_id}
            resp_sum = client_app.get(f"/api/gstr11/batches/{batch_id}")
            assert resp_sum.status_code == 200
            s_data = resp_sum.json()
            assert len(s_data["inward_records"]) == 2
            # Net Refund = (9000 - 900) + (9000 - 900) = 8100 + 8100 = 16200
            assert s_data["refund_summary"]["total_net_refund_claimed"] == 16200.0

            # 5. Pre-filing validation: POST /api/gstr11/batches/{batch_id}/validate
            resp_val = client_app.post(f"/api/gstr11/batches/{batch_id}/validate")
            assert resp_val.status_code == 200
            val_data = resp_val.json()["validation"]
            assert val_data["is_valid"] is True
            assert val_data["statutory_checks"]["net_refund_positivity"] == "PASSED"

            # 6. Export offline JSON: GET /api/gstr11/batches/{batch_id}/offline-json
            resp_json = client_app.get(f"/api/gstr11/batches/{batch_id}/offline-json")
            assert resp_json.status_code == 200
            offline = resp_json.json()
            assert offline["uin"] == "0717USA00001UN1"
            assert len(offline["b2b"]) == 1
            assert len(offline["cdnr"]) == 1
    finally:
        app.dependency_overrides.clear()


def test_cross_tenant_isolation_gstr10_gstr11(client_app, other_firm_partner):
    """Verify cross-tenant barrier: actor from Firm B cannot access Firm A client batch."""
    from fastapi import HTTPException
    client_gid = "00000000-0000-0000-0000-000000000002"
    app.dependency_overrides[get_current_active_user] = lambda: other_firm_partner

    try:
        def mock_cross_tenant_check(sb, cid, fid):
            raise HTTPException(status_code=403, detail="Cross-firm access forbidden")

        with patch("app.routers.gstr10.assert_client_gstin_in_firm", side_effect=mock_cross_tenant_check), \
             patch("app.routers.gstr11.assert_client_gstin_in_firm", side_effect=mock_cross_tenant_check):

            resp_g10 = client_app.get(f"/api/gstr10/batches?client_gstin_id={client_gid}&period=2026-10")
            assert resp_g10.status_code == 403

            resp_g11 = client_app.get(f"/api/gstr11/batches?client_gstin_id={client_gid}&period=2026-10")
            assert resp_g11.status_code == 403
    finally:
        app.dependency_overrides.clear()
