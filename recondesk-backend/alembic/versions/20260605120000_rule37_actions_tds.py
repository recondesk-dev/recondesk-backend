"""Add TDS and settlement columns to rule37_actions.

Revision ID: rule37_actions_tds
Revises: rule37_actions_table
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "rule37_actions_tds"
down_revision = "rule37_actions_table"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    r = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c LIMIT 1"
        ),
        {"t": table, "c": column},
    )
    return r.fetchone() is not None


def upgrade() -> None:
    if not _column_exists("rule37_actions", "amount_paid"):
        op.execute(
            sa.text("ALTER TABLE rule37_actions ADD COLUMN amount_paid numeric(15,2)")
        )
    if not _column_exists("rule37_actions", "tds_deducted"):
        op.execute(
            sa.text(
                "ALTER TABLE rule37_actions ADD COLUMN tds_deducted numeric(15,2) "
                "NOT NULL DEFAULT 0"
            )
        )
    if not _column_exists("rule37_actions", "tds_confirmed"):
        op.execute(
            sa.text(
                "ALTER TABLE rule37_actions ADD COLUMN tds_confirmed boolean "
                "NOT NULL DEFAULT false"
            )
        )
    if not _column_exists("rule37_actions", "total_settled"):
        op.execute(
            sa.text("ALTER TABLE rule37_actions ADD COLUMN total_settled numeric(15,2)")
        )
    if not _column_exists("rule37_actions", "payment_coverage"):
        op.execute(
            sa.text("ALTER TABLE rule37_actions ADD COLUMN payment_coverage text")
        )


def downgrade() -> None:
    for col in (
        "payment_coverage",
        "total_settled",
        "tds_confirmed",
        "tds_deducted",
        "amount_paid",
    ):
        if _column_exists("rule37_actions", col):
            op.execute(sa.text(f"ALTER TABLE rule37_actions DROP COLUMN {col}"))
