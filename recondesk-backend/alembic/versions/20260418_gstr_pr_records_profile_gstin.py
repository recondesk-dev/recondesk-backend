"""gstr_records, pr_records tables; user_profiles.client_gstin_id.

Revision ID: gstr_pr_records_profile_gstin
Revises: import_pipeline_upgrade
Create Date: 2026-04-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "gstr_pr_records_profile_gstin"
down_revision = "import_pipeline_upgrade"
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
    if not _table_exists("gstr_records"):
        op.execute(
            sa.text(
                """
                CREATE TABLE gstr_records (
                    id BIGSERIAL PRIMARY KEY,
                    run_id UUID NOT NULL REFERENCES reconciliation_run(id) ON DELETE CASCADE,
                    client_gstin_id VARCHAR(15) NOT NULL,
                    period VARCHAR(7) NOT NULL,
                    record_data JSONB NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_gstr_records_run_id ON gstr_records(run_id);"
            )
        )

    if not _table_exists("pr_records"):
        op.execute(
            sa.text(
                """
                CREATE TABLE pr_records (
                    id BIGSERIAL PRIMARY KEY,
                    run_id UUID NOT NULL REFERENCES reconciliation_run(id) ON DELETE CASCADE,
                    client_gstin_id VARCHAR(15) NOT NULL,
                    period VARCHAR(7) NOT NULL,
                    record_data JSONB NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )
        )
        op.execute(
            sa.text("CREATE INDEX IF NOT EXISTS idx_pr_records_run_id ON pr_records(run_id);")
        )

    if _table_exists("user_profiles") and not _column_exists("user_profiles", "client_gstin_id"):
        op.execute(
            sa.text(
                "ALTER TABLE user_profiles ADD COLUMN client_gstin_id VARCHAR(15);"
            )
        )


def downgrade() -> None:
    if _table_exists("pr_records"):
        op.execute(sa.text("DROP TABLE IF EXISTS pr_records CASCADE;"))
    if _table_exists("gstr_records"):
        op.execute(sa.text("DROP TABLE IF EXISTS gstr_records CASCADE;"))
    if _table_exists("user_profiles") and _column_exists("user_profiles", "client_gstin_id"):
        op.execute(sa.text("ALTER TABLE user_profiles DROP COLUMN IF EXISTS client_gstin_id;"))
