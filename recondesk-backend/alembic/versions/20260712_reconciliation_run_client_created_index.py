"""Add index on reconciliation_run (client_gstin_id, created_at DESC).

Revision ID: recon_run_client_created_idx
Revises: client_import_mappings
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "recon_run_client_created_idx"
down_revision = "client_import_mappings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_reconciliation_run_client_created_at "
            "ON public.reconciliation_run (client_gstin_id, created_at DESC);"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS public.idx_reconciliation_run_client_created_at;"
        )
    )
