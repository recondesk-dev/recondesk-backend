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

