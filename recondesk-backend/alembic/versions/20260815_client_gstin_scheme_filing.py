"""Add scheme_type and filing_frequency columns to client_gstins.

Revision ID: 20260815_client_gstin_scheme_filing
Revises: 20260811_vendor_followup_tables
Create Date: 2026-08-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260815_client_gstin_scheme_filing'
down_revision = '20260811_vendor_followup_tables'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE public.client_gstins
        ADD COLUMN IF NOT EXISTS scheme_type text NOT NULL DEFAULT 'regular'
            CHECK (scheme_type IN ('regular', 'composition', 'casual', 'nrtp', 'isd', 'tds_tcs_deductor')),
        ADD COLUMN IF NOT EXISTS filing_frequency text NOT NULL DEFAULT 'monthly'
            CHECK (filing_frequency IN ('monthly', 'qrmp'));
    """)


def downgrade():
    op.execute("""
        ALTER TABLE public.client_gstins
        DROP COLUMN IF EXISTS scheme_type,
        DROP COLUMN IF EXISTS filing_frequency;
    """)
