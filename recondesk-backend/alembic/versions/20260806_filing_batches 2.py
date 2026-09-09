"""Create filing_batches and filing_batch_items for bulk return processing.

Revision ID: filing_batches
Revises: filing_runs_gstr3b_offset

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "filing_batches"
down_revision = "filing_runs_gstr3b_offset"
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
    if not _table_exists("filing_batches"):
        op.execute(
            sa.text(
                """
                CREATE TABLE filing_batches (
                    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    firm_id             UUID NOT NULL
                        REFERENCES user_profiles (id) ON DELETE CASCADE,
                    created_by          UUID NOT NULL
                        REFERENCES user_profiles (id) ON DELETE CASCADE,
                    return_type         TEXT NOT NULL DEFAULT 'gstr-1',
                    period              VARCHAR(7) NOT NULL,
                    status              TEXT NOT NULL DEFAULT 'pending',
                    total_count         INTEGER NOT NULL DEFAULT 0,
                    saved_count         INTEGER NOT NULL DEFAULT 0,
                    evc_pending_count   INTEGER NOT NULL DEFAULT 0,
                    filed_count         INTEGER NOT NULL DEFAULT 0,
                    failed_count        INTEGER NOT NULL DEFAULT 0,
                    needs_review_count  INTEGER NOT NULL DEFAULT 0,
                    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT filing_batches_return_type_chk
                        CHECK (return_type IN ('gstr-1')),
                    CONSTRAINT filing_batches_status_chk
                        CHECK (status IN (
                            'pending',
                            'in_progress',
                            'completed',
                            'partially_completed',
                            'failed',
                            'cancelled'
                        )),
                    CONSTRAINT filing_batches_period_chk
                        CHECK (period ~ '^[0-9]{4}-[0-9]{2}$')
                );
                """
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_filing_batches_firm_period "
                "ON filing_batches (firm_id, return_type, period, created_at DESC);"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_filing_batches_status "
                "ON filing_batches (status);"
            )
        )

    if not _table_exists("filing_batch_items"):
        op.execute(
            sa.text(
                """
                CREATE TABLE filing_batch_items (
                    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    batch_id            UUID NOT NULL
                        REFERENCES filing_batches (id) ON DELETE CASCADE,
                    client_gstin_id     UUID NOT NULL
                        REFERENCES client_gstins (id) ON DELETE CASCADE,
                    gstin               TEXT NOT NULL,
                    filing_run_id       UUID
                        REFERENCES filing_runs (id) ON DELETE SET NULL,
                    status              TEXT NOT NULL DEFAULT 'pending',
                    error_code          TEXT,
                    error_detail        TEXT,
                    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT filing_batch_items_status_chk
                        CHECK (status IN (
                            'pending',
                            'in_progress',
                            'saved',
                            'proceeded',
                            'needs_review',
                            'evc_pending',
                            'failed',
                            'filed',
                            'skipped'
                        ))
                );
                """
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_filing_batch_items_batch "
                "ON filing_batch_items (batch_id, status);"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_filing_batch_items_client_gstin "
                "ON filing_batch_items (client_gstin_id);"
            )
        )


def downgrade() -> None:
    if _table_exists("filing_batch_items"):
        op.execute(sa.text("DROP TABLE IF EXISTS filing_batch_items CASCADE"))
    if _table_exists("filing_batches"):
        op.execute(sa.text("DROP TABLE IF EXISTS filing_batches CASCADE"))
