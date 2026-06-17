"""Rename legacy invoice_results table to reconciliation_results if present.

Databases that applied an older revision of rule37_tables that created
``invoice_results`` get the table name aligned with Supabase / app code.

Revision ID: rename_invoice_results_to_reconciliation_results
Revises: rule37_tables_drop_compliance_state
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "rename_invoice_results_to_reconciliation_results"
down_revision = "rule37_tables_drop_compliance_state"
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


def upgrade() -> None:
    if not _table_exists("invoice_results") or _table_exists("reconciliation_results"):
        return
    op.execute(
        sa.text("ALTER TABLE invoice_results RENAME TO reconciliation_results;")
    )
    # Indexes and constraints keep their old names; only the table name changes.


def downgrade() -> None:
    if not _table_exists("reconciliation_results") or _table_exists("invoice_results"):
        return
    op.execute(
        sa.text("ALTER TABLE reconciliation_results RENAME TO invoice_results;")
    )
