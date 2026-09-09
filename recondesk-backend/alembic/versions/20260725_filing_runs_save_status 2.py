"""Add save_pending / save_failed to filing_runs status CHECK.

Revision ID: filing_runs_save_status
Revises: filing_sessions_runs

Outer Sandbox status_cd \"1\" on Save only means accepted for processing.
Runs move draft → save_pending → saved | save_failed after Return Status
shows inner GSTN status_cd P / ER|PE.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "filing_runs_save_status"
down_revision = "filing_sessions_runs"
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
                    'proceeded',
                    'evc_pending',
                    'filed',
                    'failed'
                ));
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE filing_runs SET status = 'failed' "
            "WHERE status IN ('save_pending', 'save_failed');"
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
                    'saved',
                    'proceeded',
                    'evc_pending',
                    'filed',
                    'failed'
                ));
            """
        )
    )
