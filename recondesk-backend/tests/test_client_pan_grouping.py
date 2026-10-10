"""Tests for PAN-level company grouping and legal entity classification."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers.clients import (
    extract_pan_from_gstin,
    get_entity_type_from_pan,
    requires_dsc_for_pan,
    GSTIN_STATE_NAMES,
)


# ─── Unit Tests: PAN & Entity Classification Helpers ─────────────────────────


def test_extract_pan_from_gstin_valid():
    assert extract_pan_from_gstin("27AABCU9603R1ZM") == "AABCU9603R"
    assert extract_pan_from_gstin("29ABCDE1234F1Z5") == "ABCDE1234F"
    assert extract_pan_from_gstin("07AAACB1234C1Z1") == "AAACB1234C"


def test_extract_pan_from_gstin_case_insensitive_and_whitespace():
    assert extract_pan_from_gstin("  27aabcu9603r1zm  ") == "AABCU9603R"


def test_extract_pan_from_gstin_standalone_pan():
    assert extract_pan_from_gstin("AABCU9603R") == "AABCU9603R"


def test_extract_pan_from_gstin_invalid():
    assert extract_pan_from_gstin("") is None
    assert extract_pan_from_gstin("12345") is None
    assert extract_pan_from_gstin(None) is None  # type: ignore


def test_get_entity_type_from_pan():
    # 4th character determines entity type
    assert get_entity_type_from_pan("AAACB1234C") == "Company"
    assert get_entity_type_from_pan("AAAFB1234F") == "Partnership / LLP"
    assert get_entity_type_from_pan("AAAPB1234P") == "Proprietorship / Individual"
    assert get_entity_type_from_pan("AAAHB1234H") == "HUF"
    assert get_entity_type_from_pan("AAATB1234T") == "Trust"
    assert get_entity_type_from_pan("AAAAB1234A") == "Association of Persons (AOP)"
    assert get_entity_type_from_pan("AAABB1234B") == "Body of Individuals (BOI)"
    assert get_entity_type_from_pan("AAAGB1234G") == "Government Entity"
    assert get_entity_type_from_pan("AAALB1234L") == "Local Authority"
    assert get_entity_type_from_pan("AAAJB1234J") == "Artificial Juridical Person"
    assert get_entity_type_from_pan("AAAXX1234X") == "Other"
    assert get_entity_type_from_pan("") == "Other"


def test_requires_dsc_for_pan_rule_26():
    # CGST Rule 26: Companies ('C') and LLPs ('F') must sign using DSC
    assert requires_dsc_for_pan("AAACB1234C") is True
    assert requires_dsc_for_pan("AAAFB1234F") is True
    # Proprietorships and others can use EVC or DSC
    assert requires_dsc_for_pan("AAAPB1234P") is False
    assert requires_dsc_for_pan("AAAHB1234H") is False
    assert requires_dsc_for_pan("AAATB1234T") is False
    assert requires_dsc_for_pan("") is False


# ─── Integration Tests: GET /api/clients/organizations ───────────────────────


@pytest.fixture
def mock_clients_data() -> list[dict[str, Any]]:
    return [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "gstin": "27AAACB1234C1Z1",
            "trade_name": "Acme Tech Solutions MH",
            "legal_name": "Acme Technologies Private Limited",
            "state_code": "27",
            "is_active": True,
            "gstn_access_token": "secret_token_1",
            "gstn_token_expiry": "2026-12-31T23:59:59Z",
            "assigned_to": "user-1",
        },
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "gstin": "29AAACB1234C1Z3",
            "trade_name": "Acme Tech Solutions KA",
            "legal_name": "Acme Technologies Private Limited",
            "state_code": "29",
            "is_active": True,
            "gstn_access_token": None,
            "gstn_token_expiry": None,
            "assigned_to": "user-2",
        },
        {
            "id": "33333333-3333-3333-3333-333333333333",
            "gstin": "07AAACB1234C1Z5",
            "trade_name": "Acme Tech Solutions DL",
            "legal_name": "Acme Technologies Private Limited",
            "state_code": "07",
            "is_active": True,
            "gstn_access_token": "secret_token_3",
            "gstn_token_expiry": "2026-12-31T23:59:59Z",
            "assigned_to": "user-1",
        },
        {
            "id": "44444444-4444-4444-4444-444444444444",
            "gstin": "27BBBPB9876P1Z9",
            "trade_name": "Bharat Traders",
            "legal_name": "Bharat Sharma",
            "state_code": "27",
            "is_active": True,
            "gstn_access_token": None,
            "gstn_token_expiry": None,
            "assigned_to": "user-1",
        },
    ]


def test_list_client_organizations_grouping(client: TestClient, auth_headers: dict, mock_clients_data: list[dict[str, Any]]):
    with patch(
        "app.routers.clients._get_accessible_clients_list",
        new_callable=AsyncMock,
        return_value=mock_clients_data,
    ):
        resp = client.get("/api/clients/organizations", headers=auth_headers)
        assert resp.status_code == 200
        orgs = resp.json()

        # Should group into 2 distinct organizations by PAN
        assert len(orgs) == 2

        # 1. Acme Technologies (PAN AAACB1234C)
        acme = next((o for o in orgs if o["pan"] == "AAACB1234C"), None)
        assert acme is not None
        assert acme["company_name"] in ("Acme Tech Solutions MH", "Acme Technologies Private Limited")
        assert acme["entity_type"] == "Company"
        assert acme["requires_dsc"] is True
        assert acme["total_gstins"] == 3
        assert acme["connected_count"] == 2
        assert acme["all_connected"] is False
        assert len(acme["states"]) == 3
        state_codes = [s["code"] for s in acme["states"]]
        assert "07" in state_codes  # Delhi
        assert "27" in state_codes  # Maharashtra
        assert "29" in state_codes  # Karnataka
        assert len(acme["gstins"]) == 3
        # Sensitive tokens must be stripped
        for g in acme["gstins"]:
            assert g["gstn_access_token"] is None

        # 2. Bharat Traders (PAN BBBPB9876P)
        bharat = next((o for o in orgs if o["pan"] == "BBBPB9876P"), None)
        assert bharat is not None
        assert bharat["company_name"] == "Bharat Traders"
        assert bharat["entity_type"] == "Proprietorship / Individual"
        assert bharat["requires_dsc"] is False
        assert bharat["total_gstins"] == 1
        assert len(bharat["states"]) == 1
        assert bharat["states"][0]["code"] == "27"
        assert bharat["states"][0]["name"] == "Maharashtra"


def test_list_client_organizations_empty(client: TestClient, auth_headers: dict):
    with patch(
        "app.routers.clients._get_accessible_clients_list",
        new_callable=AsyncMock,
        return_value=[],
    ):
        resp = client.get("/api/clients/organizations", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []


def test_list_client_organizations_unauthorized(client: TestClient):
    resp = client.get("/api/clients/organizations")
    assert resp.status_code in (401, 403)
