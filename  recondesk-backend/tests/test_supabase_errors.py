"""Tests for Supabase error message helpers."""

from app.utils.supabase_errors import supabase_error_message


def test_missing_table_message():
    exc = Exception(
        "Could not find the table 'public.supplier_followup_audit' in the schema cache"
    )
    msg = supabase_error_message(exc)
    assert "supplier_followup_audit" in msg
    assert "migration" in msg.lower() or "Apply" in msg


def test_rls_message():
    exc = Exception("new row violates row-level security policy")
    msg = supabase_error_message(exc)
    assert "row-level security" in msg.lower() or "SERVICE_ROLE" in msg
