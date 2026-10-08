"""Tests for AuroraClient JSONB serialization parity and RPC support."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.aurora_client import (
    AuroraClient,
    AuroraRpcQuery,
    _NATIVE_ARRAY_COLS,
    _prepare_sql_param,
)


def test_prepare_sql_param_jsonb_list_of_strings():
    """List of plain strings (e.g. pr_column_headers) must serialize to JSON string."""
    headers = ["Invoice Number", "Invoice Date", "Supplier GSTIN", "Taxable Value"]
    res = _prepare_sql_param("pr_column_headers", headers)
    assert isinstance(res, str)
    assert json.loads(res) == headers


def test_prepare_sql_param_jsonb_empty_list():
    """Empty list must serialize to JSON string '[]', not raw Python list."""
    res = _prepare_sql_param("sanity_check_results", [])
    assert res == "[]"


def test_prepare_sql_param_jsonb_list_of_dicts():
    """List of dicts (e.g. column_mapping) must serialize to JSON string."""
    mapping = [{"standard_field": "gstin", "detected_column": "Supplier GSTIN"}]
    res = _prepare_sql_param("column_mapping", mapping)
    assert isinstance(res, str)
    assert json.loads(res) == mapping


def test_prepare_sql_param_jsonb_dict():
    """Dict (e.g. run_summary) must serialize to JSON string."""
    summary = {"matched_count": 10, "unmatched_count": 2}
    res = _prepare_sql_param("run_summary", summary)
    assert isinstance(res, str)
    assert json.loads(res) == summary


def test_prepare_sql_param_native_array():
    """Native PostgreSQL array column (e.g. client_gstin_ids) must remain a list."""
    ids = ["uuid-1", "uuid-2"]
    res = _prepare_sql_param("client_gstin_ids", ids)
    assert isinstance(res, list)
    assert res == ids


def test_prepare_sql_param_primitives():
    """Primitives (int, str, None) must remain unchanged."""
    assert _prepare_sql_param("count", 42) == 42
    assert _prepare_sql_param("name", "test") == "test"
    assert _prepare_sql_param("status", None) is None


def test_aurora_table_query_update_prepares_params():
    """Verify AuroraTableQuery.update() passes JSONB lists through _prepare_sql_param."""
    client = AuroraClient()
    query = client.table("reconciliation_import_runs")
    headers = ["Invoice Number", "Invoice Date"]
    query.update({
        "pr_column_headers": headers,
        "pr_record_count": 100,
    })

    # Mock DB engine connection
    mock_conn = MagicMock()
    mock_res = MagicMock()
    mock_res.fetchall.return_value = []
    mock_conn.execute.return_value = mock_res

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("app.aurora_client.get_aurora_engine", return_value=mock_engine):
        query.eq("id", "test-run-id").execute()

    # Verify executed SQL and parameters
    call_args = mock_conn.execute.call_args
    assert call_args is not None
    sql_text, params = call_args[0]
    assert 'UPDATE public."reconciliation_import_runs"' in str(sql_text)
    # Check that pr_column_headers param was serialized to a JSON string, not a raw list
    param_values = list(params.values())
    assert json.dumps(headers) in param_values


def test_aurora_client_has_rpc():
    """Verify AuroraClient exposes .rpc() method."""
    client = AuroraClient()
    assert hasattr(client, "rpc")
    rpc_query = client.rpc("delete_reconciliation_run_cascade", {"p_run_id": "test-id"})
    assert isinstance(rpc_query, AuroraRpcQuery)
    assert rpc_query.func_name == "delete_reconciliation_run_cascade"
    assert rpc_query.params == {"p_run_id": "test-id"}


def test_serialize_row_primitives_and_types():
    """Verify _serialize_row correctly handles UUID, date, datetime, Decimal, dict, list."""
    from datetime import date, datetime, timezone
    from decimal import Decimal
    from uuid import UUID
    from app.aurora_client import _serialize_row

    u = UUID("3c9cf6f2-2d94-4088-a1cc-8e7cb6986bb7")
    dt = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
    d = date(2026, 10, 1)
    dec = Decimal("1234.56")

    row = {
        "id": u,
        "created_at": dt,
        "period": d,
        "amount": dec,
        "is_active": True,
        "count": 5,
        "meta": {"nested_id": u, "inner_date": d},
        "tags": ["alpha", "beta"],
        "empty": None,
    }

    res = _serialize_row(row)
    assert res["id"] == "3c9cf6f2-2d94-4088-a1cc-8e7cb6986bb7"
    assert res["created_at"] == dt.isoformat()
    assert res["period"] == "2026-10-01"
    assert res["amount"] == 1234.56
    assert res["is_active"] is True
    assert res["count"] == 5
    assert res["meta"]["nested_id"] == "3c9cf6f2-2d94-4088-a1cc-8e7cb6986bb7"
    assert res["meta"]["inner_date"] == "2026-10-01"
    assert res["tags"] == ["alpha", "beta"]
    assert res["empty"] is None


def test_aurora_table_query_select_row_serialization():
    """Verify execute() on select converts DB Row mapping through _serialize_row."""
    from datetime import date
    from uuid import UUID
    from collections import namedtuple

    class RowMock:
        def __init__(self, mapping):
            self._mapping = mapping

    client = AuroraClient()
    query = client.table("reconciliation_import_runs").select("*")

    mock_mapping = {
        "id": UUID("3c9cf6f2-2d94-4088-a1cc-8e7cb6986bb7"),
        "period": date(2026, 10, 1),
        "status": "draft",
    }

    mock_conn = MagicMock()
    mock_res = MagicMock()
    mock_res.fetchall.return_value = [RowMock(mock_mapping)]
    mock_conn.execute.return_value = mock_res

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("app.aurora_client.get_aurora_engine", return_value=mock_engine):
        response = query.execute()

    assert len(response.data) == 1
    row = response.data[0]
    assert row["id"] == "3c9cf6f2-2d94-4088-a1cc-8e7cb6986bb7"
    assert row["period"] == "2026-10-01"
    assert row["status"] == "draft"


@pytest.mark.asyncio
async def test_wizard_get_active_run_found():
    """Verify get_active_run endpoint returns the active draft run."""
    import uuid
    from datetime import date
    from app.routers.reconciliation_import_wizard import get_active_run

    client_id = uuid.uuid4()
    mock_run = {
        "id": str(uuid.uuid4()),
        "client_id": str(client_id),
        "period": date(2026, 10, 1),
        "status": "draft",
    }

    mock_sb = MagicMock()
    mock_query = MagicMock()
    mock_query.select.return_value = mock_query
    mock_query.eq.return_value = mock_query
    mock_query.in_.return_value = mock_query
    mock_query.order.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.execute.return_value = MagicMock(data=[mock_run])
    mock_sb.table.return_value = mock_query

    with patch("app.routers.reconciliation_import_wizard.get_supabase", return_value=mock_sb), \
         patch("app.routers.reconciliation_import_wizard.ws.assert_client_access", return_value={"id": str(client_id)}):
        resp = await get_active_run(client_id=client_id, user_id="test-user")
        assert resp.status_code == 200
        import json
        body = json.loads(resp.body.decode())
        assert body["run"] is not None
        assert body["run"]["client_id"] == str(client_id)
        assert body["run"]["status"] == "draft"


@pytest.mark.asyncio
async def test_wizard_get_active_run_none():
    """Verify get_active_run endpoint returns run: null when no active runs exist."""
    import uuid
    from app.routers.reconciliation_import_wizard import get_active_run

    client_id = uuid.uuid4()
    mock_sb = MagicMock()
    mock_query = MagicMock()
    mock_query.select.return_value = mock_query
    mock_query.eq.return_value = mock_query
    mock_query.in_.return_value = mock_query
    mock_query.order.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.execute.return_value = MagicMock(data=[])
    mock_sb.table.return_value = mock_query

    with patch("app.routers.reconciliation_import_wizard.get_supabase", return_value=mock_sb), \
         patch("app.routers.reconciliation_import_wizard.ws.assert_client_access", return_value={"id": str(client_id)}):
        resp = await get_active_run(client_id=client_id, user_id="test-user")
        assert resp.status_code == 200
        import json
        body = json.loads(resp.body.decode())
        assert body["run"] is None
