"""reconciliation run execution: timestamps, versions, run_summary, reconciliation_results.

Revision ID: reconciliation_execute_schema
Revises: widen_client_gstin_id_uuid
Create Date: 2026-04-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "reconciliation_execute_schema"
down_revision = "widen_client_gstin_id_uuid"
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
    if not _table_exists("reconciliation_results"):
        op.execute(
            sa.text(
                """
                CREATE TABLE reconciliation_results (
                    run_id UUID PRIMARY KEY REFERENCES reconciliation_run(id) ON DELETE CASCADE,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_reconciliation_results_created "
                "ON reconciliation_results(created_at);"
            )
        )

    for col, ddl in [
        ("processing_started_at", "TIMESTAMPTZ"),
        ("completed_at", "TIMESTAMPTZ"),
        ("gstr_period_end", "DATE"),
        ("matching_version", "VARCHAR(64)"),
        ("rules_version", "VARCHAR(64)"),
        ("decision_version", "VARCHAR(64)"),
        ("run_summary", "JSONB"),
    ]:
        if _table_exists("reconciliation_run") and not _column_exists("reconciliation_run", col):
            op.execute(
                sa.text(
                    f"ALTER TABLE reconciliation_run ADD COLUMN {col} {ddl};"
                )
            )

    if _table_exists("reconciliation_run"):
        op.execute(
            sa.text(
                """
                UPDATE reconciliation_run
                SET status = 'READY'
                WHERE status = 'complete'
                  AND gstr_records_imported > 0
                  AND pr_records_imported > 0;
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE reconciliation_run
                SET status = 'GSTR_IMPORT_COMPLETE'
                WHERE status = 'complete'
                  AND gstr_records_imported > 0
                  AND COALESCE(pr_records_imported, 0) = 0;
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE reconciliation_run
                SET status = 'PURCHASE_IMPORT_COMPLETE'
                WHERE status = 'complete'
                  AND COALESCE(gstr_records_imported, 0) = 0
                  AND pr_records_imported > 0;
                """
            )
        )


def downgrade() -> None:
    if _table_exists("reconciliation_results"):
        op.execute(sa.text("DROP TABLE IF EXISTS reconciliation_results CASCADE;"))

    for col in [
        "run_summary",
        "decision_version",
        "rules_version",
        "matching_version",
        "gstr_period_end",
        "completed_at",
        "processing_started_at",
    ]:
        if _table_exists("reconciliation_run") and _column_exists("reconciliation_run", col):
            op.execute(
                sa.text(
                    f"ALTER TABLE reconciliation_run DROP COLUMN IF EXISTS {col};"
                )
            )
