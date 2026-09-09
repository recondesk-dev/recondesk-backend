"""GSTR-1 DOC_ISSUE (Table 13) — external-input envelope only."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.filing.gstr1_external_input import TABLE_DOC_ISSUE
from app.filing.gstr1_filing_mapper import map_sales_register_to_gstr1_doc_issue


PERIOD = "2025-04"
MAPPER_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "filing" / "gstr1_filing_mapper.py"
)


def test_outward_supplies_present_flags_external_input_no_doc_issue_save():
    result = map_sales_register_to_gstr1_doc_issue(
        filing_period=PERIOD,
        b2b_save_count=3,
    )
    assert result.doc_issue is None
    assert result.blocked_by_external_input is True
    assert result.outward_save_count == 3
    gap = result.needs_external_input
    assert gap is not None
    assert gap.table == TABLE_DOC_ISSUE
    assert gap.reason == "sr_has_no_document_series"
    assert gap.missing_fields == (
        "doc_num", "from", "to", "totnum", "cancel", "net_issue",
    )


def test_any_outward_table_triggers_external_input():
    for kwargs in (
        {"b2cs_save_count": 1},
        {"b2cl_save_count": 1},
        {"cdnr_save_count": 2},
        {"cdnur_save_count": 1},
        {"exp_save_count": 4},
    ):
        result = map_sales_register_to_gstr1_doc_issue(
            filing_period=PERIOD, **kwargs,
        )
        assert result.needs_external_input is not None, kwargs
        assert result.doc_issue is None


def test_true_nil_period_omits_doc_issue_and_external_input():
    result = map_sales_register_to_gstr1_doc_issue(filing_period=PERIOD)
    assert result.outward_save_count == 0
    assert result.doc_issue is None
    assert result.needs_external_input is None
    assert result.blocked_by_external_input is False


def test_zero_counts_explicit_still_nil():
    result = map_sales_register_to_gstr1_doc_issue(
        filing_period=PERIOD,
        b2b_save_count=0,
        b2cs_save_count=0,
        b2cl_save_count=0,
        cdnr_save_count=0,
        cdnur_save_count=0,
        exp_save_count=0,
    )
    assert result.needs_external_input is None
    assert result.doc_issue is None


def test_filing_period_format():
    with pytest.raises(ValueError, match="YYYY-MM"):
        map_sales_register_to_gstr1_doc_issue(
            filing_period="042025", b2b_save_count=1,
        )


def test_doc_issue_mapper_does_not_reference_g1m8_or_g1m10():
    """Import-boundary: filing DOC_ISSUE must not touch recon series helpers."""
    source = MAPPER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_imports = {
        "app.rules.gstr1_mismatch_rules",
        "gstr1_mismatch_rules",
    }
    forbidden_names = {
        "check_invoice_series_continuity",
        "summarize_documents_issued",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert mod not in forbidden_imports, mod
            for alias in node.names:
                assert alias.name not in forbidden_names, alias.name
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden_imports, alias.name
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Load, ast.Store)):
            if node.id in forbidden_names:
                raise AssertionError(f"forbidden name referenced: {node.id}")
        if isinstance(node, ast.Attribute) and node.attr in forbidden_names:
            raise AssertionError(f"forbidden attr referenced: {node.attr}")

    # Function must not accept SR records / invent series fields.
    fn = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == (
            "map_sales_register_to_gstr1_doc_issue"
        ):
            fn = node
            break
    assert fn is not None
    arg_names = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
    assert "records" not in arg_names
    for forbidden_arg in ("from", "to", "totnum", "cancel", "net_issue", "doc_num"):
        assert forbidden_arg not in arg_names
