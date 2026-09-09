"""gstr_records: amount_difference_paise, gstr2b_reflection_date for vendor intelligence.

Revision ID: gstr_records_vendor_intelligence
Revises: rename_invoice_results_to_reconciliation_results
Create Date: 2026-04-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "gstr_records_vendor_intelligence"
down_revision = "rename_invoice_results_to_reconciliation_results"
branch_labels = None
depends_on = None


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
    if not _table_exists("gstr_records"):
        return
    if not _column_exists("gstr_records", "amount_difference_paise"):
        op.execute(
            sa.text(
                "ALTER TABLE gstr_records ADD COLUMN amount_difference_paise BIGINT;"
            )
        )
    if not _column_exists("gstr_records", "gstr2b_reflection_date"):
        op.execute(
            sa.text(
                "ALTER TABLE gstr_records ADD COLUMN gstr2b_reflection_date DATE;"
            )
        )


def downgrade() -> None:
    if not _table_exists("gstr_records"):
        return
    if _column_exists("gstr_records", "gstr2b_reflection_date"):
        op.execute(
            sa.text(
                "ALTER TABLE gstr_records DROP COLUMN IF EXISTS gstr2b_reflection_date;"
            )
        )
    if _column_exists("gstr_records", "amount_difference_paise"):
        op.execute(
            sa.text(
                "ALTER TABLE gstr_records DROP COLUMN IF EXISTS amount_difference_paise;"
            )
        )
