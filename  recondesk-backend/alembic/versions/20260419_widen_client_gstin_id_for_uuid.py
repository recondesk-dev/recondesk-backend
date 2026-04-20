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


def _widen(table: str) -> None:
    if _table_exists(table) and _column_exists(table, "client_gstin_id"):
        op.execute(
            sa.text(
                f"ALTER TABLE {table} ALTER COLUMN client_gstin_id TYPE VARCHAR(64) USING client_gstin_id::varchar(64);"
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
