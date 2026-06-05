"""Add remaining_unpaid_amount to rule37_actions.

Revision ID: rule37_actions_remaining_unpaid
Revises: rule37_actions_tds
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "rule37_actions_remaining_unpaid"
down_revision = "rule37_actions_tds"
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
    if not _column_exists("rule37_actions", "remaining_unpaid_amount"):
        op.execute(
            sa.text(
                "ALTER TABLE rule37_actions ADD COLUMN remaining_unpaid_amount numeric(15,2)"
            )
        )


def downgrade() -> None:
    if _column_exists("rule37_actions", "remaining_unpaid_amount"):
        op.execute(
            sa.text("ALTER TABLE rule37_actions DROP COLUMN remaining_unpaid_amount")
        )
