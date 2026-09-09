"""Enhance audit_logs with firm_id, user_name, role, entity_label.

Revision ID: audit_logs_enhanced
Revises: rule37_actions_remaining_unpaid
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "audit_logs_enhanced"
down_revision = "rule37_actions_remaining_unpaid"
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


def upgrade() -> None:
    for col, ddl in (
        ("firm_id", "UUID"),
        ("user_name", "TEXT"),
        ("role", "TEXT"),
        ("entity_label", "TEXT"),
    ):
        if not _column_exists("audit_logs", col):
            op.execute(sa.text(f"ALTER TABLE audit_logs ADD COLUMN {col} {ddl};"))

    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'audit_logs_firm_id_fkey'
                      AND table_schema = 'public'
                      AND table_name = 'audit_logs'
                ) THEN
                    ALTER TABLE audit_logs
                        ADD CONSTRAINT audit_logs_firm_id_fkey
                        FOREIGN KEY (firm_id) REFERENCES user_profiles (id)
                        ON DELETE SET NULL;
                END IF;
            END $$;
            CREATE INDEX IF NOT EXISTS idx_audit_logs_firm_id
                ON audit_logs (firm_id);
            CREATE INDEX IF NOT EXISTS idx_audit_logs_firm_created
                ON audit_logs (firm_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_logs_firm_user
                ON audit_logs (firm_id, user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at
                ON audit_logs (created_at DESC);
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS idx_audit_logs_created_at;"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_audit_logs_firm_user;"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_audit_logs_firm_created;"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_audit_logs_firm_id;"))
    op.execute(
        sa.text("ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS audit_logs_firm_id_fkey;")
    )
    for col in ("entity_label", "role", "user_name", "firm_id"):
        if _column_exists("audit_logs", col):
            op.execute(sa.text(f"ALTER TABLE audit_logs DROP COLUMN {col};"))
