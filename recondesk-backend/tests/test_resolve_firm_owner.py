from unittest.mock import MagicMock, patch
import pytest
from fastapi import HTTPException

from app.routers.clients import _resolve_firm_owner


def test_resolve_firm_owner_admin():
    sb = MagicMock()
    with patch("app.routers.clients.get_user_profile", return_value={"role": "admin"}):
        owner_id = _resolve_firm_owner(sb, "admin-user-123")
        assert owner_id == "admin-user-123"


def test_resolve_firm_owner_staff_via_team_members():
    sb = MagicMock()
    mock_tm = MagicMock()
    mock_tm.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"firm_owner_id": "owner-abc"}
    ]
    sb.table.side_effect = lambda table: mock_tm if table == "team_members" else MagicMock()

    with patch("app.routers.clients.get_user_profile", return_value={"role": "staff", "email": "staff@example.com"}):
        owner_id = _resolve_firm_owner(sb, "staff-user-456")
        assert owner_id == "owner-abc"


def test_resolve_firm_owner_staff_via_client_gstins_fallback():
    sb = MagicMock()
    mock_tm = MagicMock()
    mock_tm.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    mock_tm.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

    mock_cg = MagicMock()
    mock_cg.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"firm_owner_id": "owner-xyz"}
    ]

    def table_router(tbl):
        if tbl == "team_members":
            return mock_tm
        if tbl == "client_gstins":
            return mock_cg
        return MagicMock()

    sb.table.side_effect = table_router

    with patch("app.routers.clients.get_user_profile", return_value={"role": "staff", "email": "staff@example.com"}):
        owner_id = _resolve_firm_owner(sb, "staff-user-789")
        assert owner_id == "owner-xyz"


def test_resolve_firm_owner_staff_unassociated_raises_400():
    sb = MagicMock()
    mock_empty = MagicMock()
    mock_empty.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    mock_empty.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    sb.table.return_value = mock_empty

    with patch("app.routers.clients.get_user_profile", return_value={"role": "staff", "email": "unlinked@example.com"}):
        with pytest.raises(HTTPException) as exc:
            _resolve_firm_owner(sb, "staff-user-unlinked")
        assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_list_team_members_include_owner():
    from app.routers.team import list_team_members

    sb = MagicMock()
    mock_active = MagicMock()
    mock_active.select.return_value.eq.return_value.eq.return_value.not_.is_.return_value.execute.return_value.data = []

    mock_pending = MagicMock()
    mock_pending.select.return_value.eq.return_value.eq.return_value.is_.return_value.execute.return_value.data = []

    def table_router(tbl):
        if tbl == "team_members":
            return mock_active
        return MagicMock()

    sb.table.side_effect = table_router

    with patch("app.routers.team.get_supabase", return_value=sb), \
         patch("app.routers.team._firm_owner_id", return_value="owner-123"), \
         patch("app.routers.team._active_members_inner_join_profiles", return_value=[]), \
         patch("app.routers.team.get_user_profile", return_value={
             "full_name": "Omkar Kadam",
             "email": "omkar@example.com",
             "created_at": "2026-01-01T00:00:00Z",
         }):
        res = await list_team_members(include_owner=True, current_user={"id": "staff-1"})
        assert len(res) == 1
        assert res[0]["member_user_id"] == "owner-123"
        assert res[0]["full_name"] == "Omkar Kadam"
        assert res[0]["role"] == "owner"


def test_resolve_firm_owner_owner_role():
    sb = MagicMock()
    with patch("app.routers.clients.get_user_profile", return_value={"role": "owner"}):
        owner_id = _resolve_firm_owner(sb, "owner-user-123")
        assert owner_id == "owner-user-123"
    # Ensure no table lookups happened
    sb.table.assert_not_called()


def test_resolve_firm_owner_role_param_admin():
    sb = MagicMock()
    owner_id = _resolve_firm_owner(sb, "admin-user-777", role="admin")
    assert owner_id == "admin-user-777"
    sb.table.assert_not_called()


def test_resolve_firm_owner_role_param_owner():
    sb = MagicMock()
    owner_id = _resolve_firm_owner(sb, "owner-user-888", role="owner")
    assert owner_id == "owner-user-888"
    sb.table.assert_not_called()


def test_resolve_firm_owner_standalone_no_profile():
    sb = MagicMock()
    mock_empty = MagicMock()
    mock_empty.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    mock_empty.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    sb.table.return_value = mock_empty

    # Newly registered user whose get_user_profile returns None
    with patch("app.routers.clients.get_user_profile", return_value=None):
        owner_id = _resolve_firm_owner(sb, "fresh-admin-999")
        assert owner_id == "fresh-admin-999"


def test_resolve_firm_owner_standalone_empty_role():
    sb = MagicMock()
    mock_empty = MagicMock()
    mock_empty.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    mock_empty.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    sb.table.return_value = mock_empty

    with patch("app.routers.clients.get_user_profile", return_value={"role": "", "email": "fresh@example.com"}):
        owner_id = _resolve_firm_owner(sb, "fresh-admin-000")
        assert owner_id == "fresh-admin-000"


@pytest.mark.asyncio
async def test_list_team_members_standalone_admin_empty_team():
    from app.routers.team import list_team_members

    sb = MagicMock()
    mock_active = MagicMock()
    mock_active.select.return_value.eq.return_value.eq.return_value.not_.is_.return_value.execute.return_value.data = []
    mock_pending = MagicMock()
    mock_pending.select.return_value.eq.return_value.eq.return_value.is_.return_value.execute.return_value.data = []

    def table_router(tbl):
        if tbl == "team_members":
            return mock_active
        return MagicMock()

    sb.table.side_effect = table_router

    with patch("app.routers.team.get_supabase", return_value=sb), \
         patch("app.routers.team.get_user_profile", return_value={"role": "admin"}):
        res = await list_team_members(include_owner=False, current_user={"id": "standalone-admin", "role": "admin"})
        assert res == []


@pytest.mark.asyncio
async def test_list_team_members_standalone_owner_empty_team():
    from app.routers.team import list_team_members

    sb = MagicMock()
    mock_active = MagicMock()
    mock_active.select.return_value.eq.return_value.eq.return_value.not_.is_.return_value.execute.return_value.data = []

    def table_router(tbl):
        if tbl == "team_members":
            return mock_active
        return MagicMock()

    sb.table.side_effect = table_router

    with patch("app.routers.team.get_supabase", return_value=sb), \
         patch("app.routers.team.get_user_profile", return_value={"role": "owner"}):
        res = await list_team_members(include_owner=False, current_user={"id": "standalone-owner", "role": "owner"})
        assert res == []


@pytest.mark.asyncio
async def test_list_team_members_unlinked_staff_returns_empty():
    from app.routers.team import list_team_members

    sb = MagicMock()
    mock_empty = MagicMock()
    mock_empty.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    mock_empty.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    sb.table.return_value = mock_empty

    with patch("app.routers.team.get_supabase", return_value=sb), \
         patch("app.routers.team.get_user_profile", return_value={"role": "staff", "email": "unlinked@example.com"}):
        res = await list_team_members(include_owner=False, current_user={"id": "unlinked-staff", "role": "staff"})
        assert res == []


@pytest.mark.asyncio
async def test_create_first_client_fresh_admin_success():
    from app.routers.clients import create_client, ClientCreate

    sb = MagicMock()
    mock_cg = MagicMock()
    # No existing soft-deleted client
    mock_cg.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    mock_cg.insert.return_value.execute.return_value.data = [{"id": "new-client-id"}]
    # Post-insert single fetch
    mock_cg.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "id": "new-client-id",
        "gstin": "27AAPFU0939F1ZV",
        "trade_name": "Acme Traders",
        "firm_owner_id": "gst-guy-1",
        "is_active": True,
    }
    sb.table.return_value = mock_cg

    body = ClientCreate(
        gstin="27AAPFU0939F1ZV",
        trade_name="Acme Traders",
        contact_name="GST Guy",
        contact_email="gstguy@example.com",
        contact_phone="9876543210",
    )

    with patch("app.routers.clients.get_supabase", return_value=sb), \
         patch("app.routers.clients.get_user_profile", return_value={"role": "admin"}), \
         patch("app.routers.clients.assert_gstin_capacity", return_value={"gstins_used": 0, "gstin_limit": 2}), \
         patch("app.routers.clients.log_audit", return_value=None), \
         patch("app.routers.clients.invalidate_user_dashboard", return_value=None):
        resp = await create_client(body=body, current_user={"id": "gst-guy-1", "role": "admin"})
        assert resp.status_code == 201

