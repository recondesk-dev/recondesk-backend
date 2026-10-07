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
