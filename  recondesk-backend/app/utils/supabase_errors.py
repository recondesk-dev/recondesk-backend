"""Map Supabase/PostgREST exceptions to operator-friendly messages."""

from __future__ import annotations


def supabase_error_message(exc: BaseException, *, context: str = "") -> str:
    """Return a safe, actionable message from a Supabase client error."""
    parts: list[str] = []
    for attr in ("message", "details", "hint", "code"):
        val = getattr(exc, attr, None)
        if val is not None and str(val).strip():
            parts.append(str(val).strip())
    if not parts and exc.args:
        parts.append(str(exc.args[0]))
    msg = " — ".join(parts) if parts else str(exc)
    low = msg.lower()

    if "rule37_actions" in low and any(
        token in low
        for token in (
            "does not exist",
            "42p01",
            "pgrst204",
            "schema cache",
            "could not find the table",
            "could not find the column",
            "relation",
        )
    ):
        return (
            "The rule37_actions table or settlement columns are missing in Supabase. "
            "Apply migrations "
            "(20260605120000_rule37_actions_tds.sql, "
            "20260605140000_rule37_actions_remaining_unpaid.sql, "
            "20260605150000_rule37_actions_table_and_grants.sql), then reload the schema."
        )

    if "supplier_followup_audit" in low and any(
        token in low
        for token in (
            "does not exist",
            "42p01",
            "pgrst205",
            "schema cache",
            "could not find the table",
            "relation",
        )
    ):
        return (
            "The supplier_followup_audit table is missing or not in the API schema cache. "
            "Apply Supabase migrations "
            "(20260604120000_supplier_followup_audit.sql and "
            "20260604140000_supplier_followup_audit_grants.sql), then reload the schema."
        )

    if any(
        token in low
        for token in (
            "row-level security",
            "42501",
            "permission denied",
            "violates row-level security",
        )
    ):
        return (
            "Row-level security blocked the database write. "
            "Confirm Railway uses SUPABASE_SERVICE_ROLE_KEY (not the anon key) for the API."
        )

    if context:
        return f"{context}: {msg[:400]}"
    return msg[:500]
