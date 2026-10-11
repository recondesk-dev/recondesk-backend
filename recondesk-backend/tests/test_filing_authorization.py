"""Tests for RBAC authorization enforcement on critical filing and IMS writeback operations."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.auth import get_current_active_user, require_admin_user

client = TestClient(app)

ADMIN_USER = {"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "email": "admin@example.com", "role": "admin"}
OWNER_USER = {"id": "oooooooo-oooo-oooo-oooo-oooooooooooo", "email": "owner@example.com", "role": "owner"}
PARTNER_USER = {"id": "pppppppp-pppp-pppp-pppp-pppppppppppp", "email": "partner@example.com", "role": "partner"}
MANAGER_USER = {"id": "mmmmmmmm-mmmm-mmmm-mmmm-mmmmmmmmmmmm", "email": "manager@example.com", "role": "manager"}
STAFF_USER = {"id": "ssssssss-ssss-ssss-ssss-ssssssssssss", "email": "staff@example.com", "role": "staff"}
PREPARER_USER = {"id": "rrrrrrrr-rrrr-rrrr-rrrr-rrrrrrrrrrrr", "email": "preparer@example.com", "role": "preparer"}
VIEWER_USER = {"id": "vvvvvvvv-vvvv-vvvv-vvvv-vvvvvvvvvvvv", "email": "viewer@example.com", "role": "viewer"}
NO_ROLE_USER = {"id": "nnnnnnnn-nnnn-nnnn-nnnn-nnnnnnnnnnnn", "email": "norole@example.com", "role": ""}


@pytest.mark.asyncio
async def test_require_admin_user_allows_admin_and_owner_and_partner():
    res_admin = await require_admin_user(current_user=ADMIN_USER)
    assert res_admin == ADMIN_USER

    res_owner = await require_admin_user(current_user=OWNER_USER)
    assert res_owner == OWNER_USER

    res_partner = await require_admin_user(current_user=PARTNER_USER)
    assert res_partner == PARTNER_USER


@pytest.mark.asyncio
async def test_require_admin_user_denies_staff_manager_preparer_viewer():
    from fastapi import HTTPException
    for unprivileged in (MANAGER_USER, PREPARER_USER, STAFF_USER, VIEWER_USER, NO_ROLE_USER):
        with pytest.raises(HTTPException) as exc:
            await require_admin_user(current_user=unprivileged)
        assert exc.value.status_code == 403
        assert "admin access required" in exc.value.detail.lower()



def test_staff_blocked_on_gstr1_file():
    app.dependency_overrides[get_current_active_user] = lambda: STAFF_USER
    try:
        response = client.post(
            "/api/filing/gstr-1/2026-03/file",
            json={"session_id": "sess-1", "run_id": "run-1", "evc_otp": "123456"},
        )
        assert response.status_code == 403
        assert "admin access required" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


def test_manager_blocked_on_gstr1_file():
    app.dependency_overrides[get_current_active_user] = lambda: MANAGER_USER
    try:
        response = client.post(
            "/api/filing/gstr-1/2026-03/file",
            json={"session_id": "sess-1", "run_id": "run-1", "evc_otp": "123456"},
        )
        assert response.status_code == 403
        assert "admin access required" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


def test_viewer_blocked_on_gstr1_file():
    app.dependency_overrides[get_current_active_user] = lambda: VIEWER_USER
    try:
        response = client.post(
            "/api/filing/gstr-1/2026-03/file",
            json={"session_id": "sess-1", "run_id": "run-1", "evc_otp": "123456"},
        )
        assert response.status_code == 403
        assert "admin access required" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)



def test_staff_blocked_on_gstr3b_offset():
    app.dependency_overrides[get_current_active_user] = lambda: STAFF_USER
    try:
        response = client.post(
            "/api/filing/gstr-3b/2026-03/offset",
            json={
                "session_id": "sess-1",
                "run_id": "run-1",
                "gstin": "27AAPFU0939F1ZV",
                "pdcash": {},
                "pditc": {},
            },
        )
        assert response.status_code == 403
        assert "admin access required" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


def test_staff_blocked_on_gstr3b_file():
    app.dependency_overrides[get_current_active_user] = lambda: STAFF_USER
    try:
        response = client.post(
            "/api/filing/gstr-3b/2026-03/file",
            json={
                "session_id": "sess-1",
                "run_id": "run-1",
                "gstin": "27AAPFU0939F1ZV",
                "evc_otp": "123456",
            },
        )
        assert response.status_code == 403
        assert "admin access required" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


def test_staff_blocked_on_ims_actions_confirm():
    app.dependency_overrides[get_current_active_user] = lambda: STAFF_USER
    try:
        response = client.post(
            "/api/reconcile/runs/run-1/ims/actions/confirm",
            json={
                "confirmed": True,
                "confirmation_summary": "Test confirmation",
                "expected_count": 0,
                "invoices": [],
            },
        )
        assert response.status_code == 403
        assert "admin access required" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
