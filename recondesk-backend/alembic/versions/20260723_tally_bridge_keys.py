"""Add tally_bridge_keys and Rule 37 action provenance columns.

Revision ID: tally_bridge_keys
Revises: auto_approve_confidence
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tally_bridge_keys"
down_revision = "auto_approve_confidence"
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


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    r = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    return r.fetchone() is not None


def upgrade() -> None:
    if not _table_exists("tally_bridge_keys"):
        op.execute(
            sa.text(
                """
                CREATE TABLE tally_bridge_keys (
                    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    api_key         TEXT NOT NULL UNIQUE,
                    account_id      UUID NOT NULL,
                    company_name    TEXT NOT NULL DEFAULT '',
                    last_synced_at  TIMESTAMPTZ,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    revoked_at      TIMESTAMPTZ
                );
                """
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_tally_bridge_keys_account_id "
                "ON tally_bridge_keys(account_id);"
            )
        )

    if _table_exists("rule37_actions"):
        if not _column_exists("rule37_actions", "source"):
            op.execute(sa.text("ALTER TABLE rule37_actions ADD COLUMN source TEXT"))
        if not _column_exists("rule37_actions", "settled_date"):
            op.execute(
                sa.text("ALTER TABLE rule37_actions ADD COLUMN settled_date DATE")
            )


def downgrade() -> None:
    if _table_exists("rule37_actions"):
        if _column_exists("rule37_actions", "settled_date"):
            op.execute(sa.text("ALTER TABLE rule37_actions DROP COLUMN settled_date"))
        if _column_exists("rule37_actions", "source"):
            op.execute(sa.text("ALTER TABLE rule37_actions DROP COLUMN source"))
    if _table_exists("tally_bridge_keys"):
        op.execute(sa.text("DROP TABLE IF EXISTS tally_bridge_keys CASCADE"))
