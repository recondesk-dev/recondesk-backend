"""Add B2B GSTIN and tax breakup columns to payments.

Revision ID: 20260923_payments_b2b_gstin
Revises: 20260815_client_gstin_scheme_filing
Create Date: 2026-09-23 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260923_payments_b2b_gstin'
down_revision = '20260815_client_gstin_scheme_filing'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE public.payments
        ADD COLUMN IF NOT EXISTS customer_gstin text,
        ADD COLUMN IF NOT EXISTS customer_trade_name text,
        ADD COLUMN IF NOT EXISTS customer_city text,
        ADD COLUMN IF NOT EXISTS customer_state_code text,
        ADD COLUMN IF NOT EXISTS tax_type text DEFAULT 'intra',
        ADD COLUMN IF NOT EXISTS cgst_paise integer DEFAULT 0,
        ADD COLUMN IF NOT EXISTS sgst_paise integer DEFAULT 0,
        ADD COLUMN IF NOT EXISTS igst_paise integer DEFAULT 0;
    """)


def downgrade():
    op.execute("""
        ALTER TABLE public.payments
        DROP COLUMN IF EXISTS customer_gstin,
        DROP COLUMN IF EXISTS customer_trade_name,
        DROP COLUMN IF EXISTS customer_city,
        DROP COLUMN IF EXISTS customer_state_code,
        DROP COLUMN IF EXISTS tax_type,
        DROP COLUMN IF EXISTS cgst_paise,
        DROP COLUMN IF EXISTS sgst_paise,
        DROP COLUMN IF EXISTS igst_paise;
    """)
