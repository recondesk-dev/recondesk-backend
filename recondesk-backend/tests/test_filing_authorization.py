"""Tests for RBAC authorization enforcement on critical filing and IMS writeback operations."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.auth import get_current_active_user, require_admin_user

client = TestClient(app)

ADMIN_USER = {"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "email": "admin@example.com", "role": "admin"}
OWNER_USER = {"id": "oooooooo-oooo-oooo-oooo-oooooooooooo", "email": "owner@example.com", "role": "owner"}
STAFF_USER = {"id": "ssssssss-ssss-ssss-ssss-ssssssssssss", "email": "staff@example.com", "role": "staff"}
NO_ROLE_USER = {"id": "nnnnnnnn-nnnn-nnnn-nnnn-nnnnnnnnnnnn", "email": "norole@example.com", "role": ""}


@pytest.mark.asyncio
async def test_require_admin_user_allows_admin_and_owner():
    res_admin = await require_admin_user(current_user=ADMIN_USER)
    assert res_admin == ADMIN_USER

    res_owner = await require_admin_user(current_user=OWNER_USER)
    assert res_owner == OWNER_USER


@pytest.mark.asyncio
async def test_require_admin_user_denies_staff_and_unprivileged():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc1:
        await require_admin_user(current_user=STAFF_USER)
    assert exc1.value.status_code == 403
    assert "admin access required" in exc1.value.detail.lower()

    with pytest.raises(HTTPException) as exc2:
        await require_admin_user(current_user=NO_ROLE_USER)
    assert exc2.value.status_code == 403


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
