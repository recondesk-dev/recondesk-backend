"""invoice_results + rule37_resolutions; drop compliance_state.

Revision ID: rule37_tables_drop_compliance_state
Revises: reconciliation_api_layer
Create Date: 2026-04-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "rule37_tables_drop_compliance_state"
down_revision = "reconciliation_api_layer"
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
    if not _table_exists("invoice_results"):
        op.execute(
            sa.text(
                """
                CREATE TABLE invoice_results (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    run_id UUID NOT NULL REFERENCES reconciliation_run(id) ON DELETE CASCADE,
                    pr_id VARCHAR(64) NOT NULL,
                    rule37_flag BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_invoice_results_run_pr UNIQUE (run_id, pr_id)
                );
                """
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_invoice_results_run_id "
                "ON invoice_results(run_id);"
            )
        )

    if not _table_exists("rule37_resolutions"):
        op.execute(
            sa.text(
                """
                CREATE TABLE rule37_resolutions (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    run_id UUID NOT NULL REFERENCES reconciliation_run(id) ON DELETE CASCADE,
                    invoice_result_id UUID NOT NULL REFERENCES invoice_results(id) ON DELETE CASCADE,
                    resolved_by VARCHAR(64) NOT NULL,
                    resolved_at TIMESTAMPTZ NOT NULL,
                    resolution_note VARCHAR(500),
                    CONSTRAINT uq_rule37_resolutions_one_per_invoice
                        UNIQUE (invoice_result_id)
                );
                """
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_rule37_resolutions_run_id "
                "ON rule37_resolutions(run_id);"
            )
        )

    if _table_exists("reconciliation_run") and _column_exists(
        "reconciliation_run", "compliance_state"
    ):
        op.execute(
            sa.text(
                "ALTER TABLE reconciliation_run DROP COLUMN compliance_state;"
            )
        )


def downgrade() -> None:
    if _table_exists("rule37_resolutions"):
        op.execute(sa.text("DROP TABLE IF EXISTS rule37_resolutions CASCADE;"))
    if _table_exists("invoice_results"):
        op.execute(sa.text("DROP TABLE IF EXISTS invoice_results CASCADE;"))
    if _table_exists("reconciliation_run") and not _column_exists(
        "reconciliation_run", "compliance_state"
    ):
        op.execute(
            sa.text(
                "ALTER TABLE reconciliation_run ADD COLUMN compliance_state "
                "JSONB NOT NULL DEFAULT '{}'::jsonb;"
            )
        )
