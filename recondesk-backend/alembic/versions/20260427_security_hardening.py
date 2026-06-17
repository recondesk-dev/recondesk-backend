"""Security: audit_logs, idempotency_keys, reconciliation_run.created_by.

Revision ID: security_hardening
Revises: gstr_records_vendor_intelligence
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "security_hardening"
down_revision = "gstr_records_vendor_intelligence"
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


def upgrade() -> None:
    if not _table_exists("audit_logs"):
        op.execute(
            sa.text(
                """
                CREATE TABLE audit_logs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id VARCHAR(64),
                    action VARCHAR(64) NOT NULL,
                    entity_type VARCHAR(128) NOT NULL,
                    entity_id VARCHAR(128),
                    metadata JSONB DEFAULT '{}'::jsonb,
                    ip_address VARCHAR(128),
                    correlation_id VARCHAR(64),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_audit_logs_user_created
                    ON audit_logs (user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_logs_action
                    ON audit_logs (action);
                """
            )
        )

    if not _table_exists("idempotency_keys"):
        op.execute(
            sa.text(
                """
                CREATE TABLE idempotency_keys (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    idempotency_key VARCHAR(300) NOT NULL,
                    user_id VARCHAR(64) NOT NULL,
                    response JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_idempotency_key_user
                    ON idempotency_keys (idempotency_key, user_id);
                CREATE INDEX IF NOT EXISTS idx_idempotency_created
                    ON idempotency_keys (created_at);
                """
            )
        )

    if _table_exists("reconciliation_run") and not _column_exists(
        "reconciliation_run", "created_by"
    ):
        op.execute(
            sa.text(
                "ALTER TABLE reconciliation_run ADD COLUMN created_by VARCHAR(64);"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_reconciliation_run_created_by "
                "ON reconciliation_run(created_by);"
            )
        )


def downgrade() -> None:
    if _table_exists("reconciliation_run") and _column_exists(
        "reconciliation_run", "created_by"
    ):
        op.execute(
            sa.text("ALTER TABLE reconciliation_run DROP COLUMN IF EXISTS created_by;")
        )
    if _table_exists("idempotency_keys"):
        op.execute(sa.text("DROP TABLE IF EXISTS idempotency_keys;"))
    if _table_exists("audit_logs"):
        op.execute(sa.text("DROP TABLE IF EXISTS audit_logs;"))
