"""Disable RLS and grant permissions for billing module tables.

Revision ID: billing_rls
Revises: billing_module
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "billing_rls"
down_revision = "billing_module"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            ALTER TABLE IF EXISTS billing_company_profiles DISABLE ROW LEVEL SECURITY;
            ALTER TABLE IF EXISTS billing_customers DISABLE ROW LEVEL SECURITY;
            ALTER TABLE IF EXISTS billing_items DISABLE ROW LEVEL SECURITY;
            ALTER TABLE IF EXISTS billing_invoices DISABLE ROW LEVEL SECURITY;
            ALTER TABLE IF EXISTS billing_invoice_line_items DISABLE ROW LEVEL SECURITY;

            GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role, postgres;
            GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated, service_role, postgres;
            GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role, postgres;

            NOTIFY pgrst, 'reload schema';
            """
        )
    )


def downgrade() -> None:
    pass
