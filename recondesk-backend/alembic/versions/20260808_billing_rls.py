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

            GRANT ALL ON TABLE billing_company_profiles TO anon, authenticated, service_role;
            GRANT ALL ON TABLE billing_customers TO anon, authenticated, service_role;
            GRANT ALL ON TABLE billing_items TO anon, authenticated, service_role;
            GRANT ALL ON TABLE billing_invoices TO anon, authenticated, service_role;
            GRANT ALL ON TABLE billing_invoice_line_items TO anon, authenticated, service_role;
            """
        )
    )


def downgrade() -> None:
    pass
