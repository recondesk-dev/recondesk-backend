import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_get_upload_request_info_success():
    mock_supabase = MagicMock()
    mock_upload_req = {
        "id": "req-12345",
        "client_id": "client-999",
        "created_by_user_id": "user-888",
        "title": "September 2026 Purchase Invoices",
        "description": "Please provide your invoices in Excel or PDF format.",
        "expires_at": "2030-01-01T00:00:00Z",
        "created_at": "2026-09-24T00:00:00Z",
    }
    mock_client_row = {
        "trade_name": "Acme Manufacturing Pvt Ltd",
        "legal_name": "Acme Manufacturing Private Limited",
        "gstin": "27AABCA1234F1Z5",
    }
    mock_user_row = {
        "firm_name": "Kadam & Singhania, Chartered Accountants",
        "full_name": "Omkar Kadam",
        "firm_city": "Mumbai",
    }

    def table_router(table_name):
        mock_table = MagicMock()
        if table_name == "upload_requests":
            mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[mock_upload_req]
            )
        elif table_name == "client_gstins":
            mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[mock_client_row]
            )
        elif table_name == "user_profiles":
            mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[mock_user_row]
            )
        return mock_table

    mock_supabase.table.side_effect = table_router

    with patch("app.routers.upload.get_supabase", return_value=mock_supabase):
        resp = client.get("/upload/info/valid-token-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "req-12345"
        assert data["token"] == "valid-token-123"
        assert data["title"] == "September 2026 Purchase Invoices"
        assert data["description"] == "Please provide your invoices in Excel or PDF format."
        assert data["is_expired"] is False
        assert data["client_name"] == "Acme Manufacturing Pvt Ltd"
        assert data["client_gstin"] == "27AABCA1234F1Z5"
        assert data["firm_name"] == "Kadam & Singhania, Chartered Accountants"
        assert data["ca_name"] == "Omkar Kadam"
        assert data["firm_city"] == "Mumbai"


def test_get_upload_request_info_expired():
    mock_supabase = MagicMock()
    mock_upload_req = {
        "id": "req-expired",
        "client_id": None,
        "created_by_user_id": None,
        "title": "Expired Request",
        "description": None,
        "expires_at": "2020-01-01T00:00:00Z",
        "created_at": "2019-12-01T00:00:00Z",
    }
    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[mock_upload_req]
    )
    mock_supabase.table.return_value = mock_table

    with patch("app.routers.upload.get_supabase", return_value=mock_supabase):
        resp = client.get("/upload/info/expired-token")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "req-expired"
        assert data["is_expired"] is True
        assert data["firm_name"] == "Chartered Accountant & Tax Advisors"


def test_get_upload_request_info_not_found():
    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[]
    )
    mock_supabase.table.return_value = mock_table

    with patch("app.routers.upload.get_supabase", return_value=mock_supabase):
        resp = client.get("/upload/info/nonexistent-token")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Upload link not found"
