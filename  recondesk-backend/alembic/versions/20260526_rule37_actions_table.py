"""Dedicated rule37_actions table to replace mismatch_notes for rule37 action tracking.

Revision ID: rule37_actions_table
Revises: mismatch_notes_status
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "rule37_actions_table"
down_revision = "mismatch_notes_status"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    r = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :name LIMIT 1"
        ),
        {"name": name},
    )
    return r.fetchone() is not None


def upgrade() -> None:
    if not _table_exists("rule37_actions"):
        op.execute(
            sa.text(
                """
                CREATE TABLE rule37_actions (
                    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
                    run_id      UUID        NOT NULL,
                    record_hash TEXT        NOT NULL,
                    status      TEXT        NOT NULL,
                    user_id     TEXT        NOT NULL DEFAULT '',
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (run_id, record_hash)
                );
                """
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_rule37_actions_run_id "
                "ON rule37_actions(run_id);"
            )
        )


def downgrade() -> None:
    if _table_exists("rule37_actions"):
        op.execute(sa.text("DROP TABLE IF EXISTS rule37_actions CASCADE;"))
