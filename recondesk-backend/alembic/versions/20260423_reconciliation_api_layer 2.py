"""Reconciliation public API: finalize/lock, compliance_state, mismatch_notes, client_gstins.

Revision ID: reconciliation_api_layer
Revises: reconciliation_execute_schema
Create Date: 2026-04-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "reconciliation_api_layer"
down_revision = "reconciliation_execute_schema"
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
    if _table_exists("reconciliation_run"):
        for col, ddl in [
            ("finalized_at", "TIMESTAMPTZ"),
            ("finalized_by", "VARCHAR(64)"),
            ("is_locked", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("compliance_state", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
        ]:
            if not _column_exists("reconciliation_run", col):
                op.execute(
                    sa.text(
                        f"ALTER TABLE reconciliation_run ADD COLUMN {col} {ddl};"
                    )
                )

    if not _table_exists("mismatch_notes"):
        op.execute(
            sa.text(
                """
                CREATE TABLE mismatch_notes (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    record_id TEXT NOT NULL,
                    run_id UUID NOT NULL REFERENCES reconciliation_run(id) ON DELETE CASCADE,
                    user_id VARCHAR(64) NOT NULL,
                    firm_owner_id VARCHAR(64) NOT NULL,
                    note TEXT NOT NULL,
                    record_type VARCHAR(64) NOT NULL,
                    note_type VARCHAR(64) NOT NULL,
                    severity VARCHAR(32) NOT NULL DEFAULT 'low',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_mismatch_notes_record_id "
                "ON mismatch_notes(record_id);"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_mismatch_notes_run_id "
                "ON mismatch_notes(run_id);"
            )
        )

    if _table_exists("client_gstins"):
        for col, ddl in [
            ("is_active", "BOOLEAN NOT NULL DEFAULT TRUE"),
            ("trade_name", "TEXT"),
            ("legal_name", "TEXT"),
            ("contact_name", "TEXT"),
            ("contact_email", "TEXT"),
            ("contact_phone", "TEXT"),
            ("assigned_to", "VARCHAR(64)"),
            ("gstin", "VARCHAR(20)"),
        ]:
            if not _column_exists("client_gstins", col):
                op.execute(
                    sa.text(
                        f"ALTER TABLE client_gstins ADD COLUMN {col} {ddl};"
                    )
                )


def downgrade() -> None:
    if _table_exists("mismatch_notes"):
        op.execute(sa.text("DROP TABLE IF EXISTS mismatch_notes CASCADE;"))

    for col in [
        "compliance_state",
        "is_locked",
        "finalized_by",
        "finalized_at",
    ]:
        if _table_exists("reconciliation_run") and _column_exists(
            "reconciliation_run", col
        ):
            op.execute(
                sa.text(
                    f"ALTER TABLE reconciliation_run DROP COLUMN IF EXISTS {col};"
                )
            )

    if not _table_exists("client_gstins"):
        return
    for col in (
        "gstin",
        "assigned_to",
        "contact_phone",
        "contact_email",
        "contact_name",
        "legal_name",
        "trade_name",
        "is_active",
    ):
        if _column_exists("client_gstins", col):
            op.execute(
                sa.text(
                    f"ALTER TABLE client_gstins DROP COLUMN IF EXISTS {col};"
                )
            )
