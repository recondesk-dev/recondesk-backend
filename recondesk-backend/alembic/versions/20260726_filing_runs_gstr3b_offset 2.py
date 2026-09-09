"""Extend filing_runs for GSTR-3B Offset gate + dual-status states.

Revision ID: filing_runs_gstr3b_offset
Revises: filing_runs_save_status

Adds offset_pending / offset_complete / offset_failed, plus columns that
record the confirmed Offset payload and post-Offset tx_pmt snapshot used
as proof when blocking a second Save/Offset for the same (gstin, period).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "filing_runs_gstr3b_offset"
down_revision = "filing_runs_save_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE filing_runs DROP CONSTRAINT IF EXISTS filing_runs_status_chk;"
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE filing_runs
                ADD CONSTRAINT filing_runs_status_chk
                CHECK (status IN (
                    'draft',
                    'save_pending',
                    'saved',
                    'save_failed',
                    'offset_pending',
                    'offset_complete',
                    'offset_failed',
                    'proceeded',
                    'evc_pending',
                    'filed',
                    'failed'
                ));
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE filing_runs
                ADD COLUMN IF NOT EXISTS offset_payload jsonb,
                ADD COLUMN IF NOT EXISTS offset_completed_at timestamptz,
                ADD COLUMN IF NOT EXISTS tx_pmt_snapshot jsonb;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS idx_filing_runs_gstr3b_offset_gate
                ON filing_runs (gstin, period, status)
                WHERE return_type = 'gstr-3b'
                  AND status IN (
                      'offset_complete',
                      'evc_pending',
                      'filed'
                  );
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS idx_filing_runs_gstr3b_offset_gate;"
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE filing_runs
            SET status = 'failed'
            WHERE status IN (
                'offset_pending',
                'offset_complete',
                'offset_failed'
            );
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE filing_runs
                DROP COLUMN IF EXISTS offset_payload,
                DROP COLUMN IF EXISTS offset_completed_at,
                DROP COLUMN IF EXISTS tx_pmt_snapshot;
            """
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE filing_runs DROP CONSTRAINT IF EXISTS filing_runs_status_chk;"
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE filing_runs
                ADD CONSTRAINT filing_runs_status_chk
                CHECK (status IN (
                    'draft',
                    'save_pending',
                    'saved',
                    'save_failed',
                    'proceeded',
                    'evc_pending',
                    'filed',
                    'failed'
                ));
            """
        )
    )
