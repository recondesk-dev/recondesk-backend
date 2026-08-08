"""Widen client_gstin_id to fit client_gstins.id (UUID), not only 15-char GSTIN.

Revision ID: widen_client_gstin_id_uuid
Revises: gstr_pr_records_profile_gstin
Create Date: 2026-04-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "widen_client_gstin_id_uuid"
down_revision = "gstr_pr_records_profile_gstin"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    r = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :n",
        ),
        {"n": name},
    )
    return r.scalar() is not None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    r = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c",
        ),
        {"t": table, "c": column},
    )
    return r.scalar() is not None


def _drop_fk_constraints_on_column(table: str, column: str) -> None:
    """Find and drop any foreign key constraints on `column` before type alteration."""
    conn = op.get_bind()
    res = conn.execute(
        sa.text(
            """
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            JOIN pg_namespace n ON t.relnamespace = n.oid
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
            WHERE n.nspname = 'public'
              AND t.relname = :table
              AND a.attname = :column
              AND c.contype = 'f';
            """
        ),
        {"table": table, "column": column},
    )
    fk_names = [row[0] for row in res.fetchall()]
    for fk in fk_names:
        op.execute(sa.text(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{fk}";'))


def _widen(table: str) -> None:
    if _table_exists(table) and _column_exists(table, "client_gstin_id"):
        _drop_fk_constraints_on_column(table, "client_gstin_id")
        op.execute(sa.text("SET lock_timeout = '15s';"))
        op.execute(
            sa.text(
                f'ALTER TABLE "{table}" ALTER COLUMN client_gstin_id TYPE VARCHAR(64) USING client_gstin_id::varchar(64);'
            )
        )


def upgrade() -> None:
    for t in (
        "reconciliation_run",
        "gstr_records",
        "pr_records",
        "gstr2b_invoices",
        "purchase_register_invoices",
    ):
        _widen(t)


def downgrade() -> None:
    for t in (
        "reconciliation_run",
        "gstr_records",
        "pr_records",
        "gstr2b_invoices",
        "purchase_register_invoices",
    ):
        if _table_exists(t) and _column_exists(t, "client_gstin_id"):
            op.execute(
                sa.text(
                    f"ALTER TABLE {t} ALTER COLUMN client_gstin_id TYPE VARCHAR(15) USING left(client_gstin_id::text, 15);"
                )
            )
