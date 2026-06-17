"""Add client_gstin_id indexes on gstr_records, pr_records, and user_profiles.

Revision ID: add_client_gstin_id_indexes
Revises: audit_logs_enhanced
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "add_client_gstin_id_indexes"
down_revision = "audit_logs_enhanced"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_gstr_records_client_gstin_id ON public.gstr_records (client_gstin_id);"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_pr_records_client_gstin_id ON public.pr_records (client_gstin_id);"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_user_profiles_client_gstin_id ON public.user_profiles (client_gstin_id);"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS public.idx_gstr_records_client_gstin_id;"))
    op.execute(sa.text("DROP INDEX IF EXISTS public.idx_pr_records_client_gstin_id;"))
    op.execute(sa.text("DROP INDEX IF EXISTS public.idx_user_profiles_client_gstin_id;"))
