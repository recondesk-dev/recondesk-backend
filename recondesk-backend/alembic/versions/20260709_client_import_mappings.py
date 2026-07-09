"""Add client_import_mappings for persistent PR column mapping.

Revision ID: client_import_mappings
Revises: add_client_gstin_id_indexes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "client_import_mappings"
down_revision = "add_client_gstin_id_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS public.client_import_mappings (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              client_gstin_id UUID NOT NULL
                REFERENCES public.client_gstins (id) ON DELETE CASCADE,
              source_column_name TEXT NOT NULL,
              target_field TEXT NOT NULL
                CHECK (target_field IN (
                  'gstin',
                  'invoice_number',
                  'invoice_date',
                  'taxable_value',
                  'cgst',
                  'sgst',
                  'igst',
                  'cess'
                )),
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              CONSTRAINT client_import_mappings_client_target_unique
                UNIQUE (client_gstin_id, target_field)
            );
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS client_import_mappings_client_gstin_id_idx
              ON public.client_import_mappings (client_gstin_id);
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS public.client_import_mappings;"))
