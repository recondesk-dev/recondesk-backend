"""Add auto_approve_confidence_threshold to user_profiles.

Revision ID: auto_approve_confidence
Revises: recon_run_client_created_idx
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "auto_approve_confidence"
down_revision = "recon_run_client_created_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE public.user_profiles "
            "ADD COLUMN IF NOT EXISTS auto_approve_confidence_threshold "
            "INTEGER NOT NULL DEFAULT 95;"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE public.user_profiles "
            "DROP COLUMN IF EXISTS auto_approve_confidence_threshold;"
        )
    )
