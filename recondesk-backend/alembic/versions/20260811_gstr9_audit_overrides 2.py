"""Create gstr9_audit_overrides table for CA cell adjustments.

Revision ID: gstr9_audit_overrides
Revises: 20260809200000_billing_cdnr
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "gstr9_audit_overrides"
down_revision = "20260809200000_billing_cdnr"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS public.gstr9_audit_overrides (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
                financial_year TEXT NOT NULL,
                table_key TEXT NOT NULL,
                cell_key TEXT NOT NULL,
                system_value NUMERIC(15, 2) DEFAULT 0.00,
                override_value NUMERIC(15, 2) NOT NULL,
                notes TEXT,
                updated_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
                CONSTRAINT uq_gstr9_override_cell UNIQUE (client_gstin_id, financial_year, table_key, cell_key)
            );

            CREATE INDEX IF NOT EXISTS idx_gstr9_audit_overrides_client_fy 
            ON public.gstr9_audit_overrides (client_gstin_id, financial_year);
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS public.gstr9_audit_overrides;"))
