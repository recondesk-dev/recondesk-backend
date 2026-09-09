"""Add optional status column to mismatch_notes for action tracking.

Revision ID: mismatch_notes_status
Revises: security_hardening
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "mismatch_notes_status"
down_revision = "security_hardening"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    r = conn.execute(
        sa.text(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table
              AND column_name = :column
            LIMIT 1
            """
        ),
        {"table": table, "column": column},
    )
    return r.fetchone() is not None


def upgrade() -> None:
    if not _column_exists("mismatch_notes", "status"):
        op.execute(
            sa.text(
                "ALTER TABLE mismatch_notes "
                "ADD COLUMN status TEXT DEFAULT 'pending';"
            )
        )


def downgrade() -> None:
    if _column_exists("mismatch_notes", "status"):
        op.execute(sa.text("ALTER TABLE mismatch_notes DROP COLUMN status;"))
