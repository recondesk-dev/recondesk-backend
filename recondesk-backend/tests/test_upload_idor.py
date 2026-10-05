"""Tests for Cross-Tenant Purchase Register Upload IDOR / BOLA Prevention."""

import uuid
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.auth import get_current_active_user

client = TestClient(app)

FIRM_A_USER = {"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "email": "ca_a@example.com", "role": "admin"}
FIRM_B_USER = {"id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "email": "ca_b@example.com", "role": "admin"}

CLIENT_A_ID = "11111111-1111-1111-1111-111111111111"
CLIENT_B_ID = "22222222-2222-2222-2222-222222222222"

RUN_A_ID = "33333333-3333-3333-3333-333333333333"
RUN_B_ID = "44444444-4444-4444-4444-444444444444"


@pytest.fixture(autouse=True)
def override_user():
    app.dependency_overrides[get_current_active_user] = lambda: FIRM_A_USER
    yield
    app.dependency_overrides.pop(get_current_active_user, None)


def test_firm_a_upload_to_firm_b_client_forbidden():
    with patch("app.routers.upload.get_supabase") as mock_sb, \
         patch("app.services.firm_access.list_accessible_client_gstin_ids", return_value={CLIENT_A_ID}):
        files = {"file": ("test.csv", b"dummy content", "text/csv")}
        data = {"client_id": CLIENT_B_ID, "run_id": RUN_A_ID}
        response = client.post("/api/v1/upload/purchase-register", data=data, files=files)

        assert response.status_code == 403
        assert response.json()["detail"] == "Access denied"


def test_firm_a_upload_to_firm_b_run_forbidden():
    sb_mock = MagicMock()
    # Run B in DB belongs to Client B
    sb_mock.table().select().eq().limit().execute.return_value.data = [
        {"id": RUN_B_ID, "client_gstin_id": CLIENT_B_ID}
    ]

    with patch("app.routers.upload.get_supabase", return_value=sb_mock), \
         patch("app.services.firm_access.list_accessible_client_gstin_ids", return_value={CLIENT_A_ID}):
        files = {"file": ("test.csv", b"dummy content", "text/csv")}
        # Firm A user passes their own client_id, but points to Firm B's run_id
        data = {"client_id": CLIENT_A_ID, "run_id": RUN_B_ID}
        response = client.post("/api/v1/upload/purchase-register", data=data, files=files)

        assert response.status_code == 403
        assert response.json()["detail"] == "Access denied"


def test_nonexistent_run_does_not_leak_presence():
    sb_mock = MagicMock()
    sb_mock.table().select().eq().limit().execute.return_value.data = []

    unknown_run_id = str(uuid.uuid4())
    with patch("app.routers.upload.get_supabase", return_value=sb_mock), \
         patch("app.services.firm_access.list_accessible_client_gstin_ids", return_value={CLIENT_A_ID}):
        files = {"file": ("test.csv", b"dummy content", "text/csv")}
        data = {"client_id": CLIENT_A_ID, "run_id": unknown_run_id}
        response = client.post("/api/v1/upload/purchase-register", data=data, files=files)

        # Must return 403 "Access denied" to avoid leaking whether run_id exists in other tenants
        assert response.status_code == 403
        assert response.json()["detail"] == "Access denied"


def test_invalid_uuid_returns_400():
    files = {"file": ("test.csv", b"dummy content", "text/csv")}
    data = {"client_id": "not-a-uuid", "run_id": RUN_A_ID}
    response = client.post("/api/v1/upload/purchase-register", data=data, files=files)

    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()
