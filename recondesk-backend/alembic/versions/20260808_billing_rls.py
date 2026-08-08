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
            ALTER TABLE IF EXISTS billing_company_profiles ENABLE ROW LEVEL SECURITY;
            ALTER TABLE IF EXISTS billing_customers ENABLE ROW LEVEL SECURITY;
            ALTER TABLE IF EXISTS billing_items ENABLE ROW LEVEL SECURITY;
            ALTER TABLE IF EXISTS billing_invoices ENABLE ROW LEVEL SECURITY;
            ALTER TABLE IF EXISTS billing_invoice_line_items ENABLE ROW LEVEL SECURITY;

            DROP POLICY IF EXISTS "Allow all billing_company_profiles" ON billing_company_profiles;
            CREATE POLICY "Allow all billing_company_profiles" ON billing_company_profiles FOR ALL USING (true) WITH CHECK (true);

            DROP POLICY IF EXISTS "Allow all billing_customers" ON billing_customers;
            CREATE POLICY "Allow all billing_customers" ON billing_customers FOR ALL USING (true) WITH CHECK (true);

            DROP POLICY IF EXISTS "Allow all billing_items" ON billing_items;
            CREATE POLICY "Allow all billing_items" ON billing_items FOR ALL USING (true) WITH CHECK (true);

            DROP POLICY IF EXISTS "Allow all billing_invoices" ON billing_invoices;
            CREATE POLICY "Allow all billing_invoices" ON billing_invoices FOR ALL USING (true) WITH CHECK (true);

            DROP POLICY IF EXISTS "Allow all billing_invoice_line_items" ON billing_invoice_line_items;
            CREATE POLICY "Allow all billing_invoice_line_items" ON billing_invoice_line_items FOR ALL USING (true) WITH CHECK (true);

            GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role, postgres;
            GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated, service_role, postgres;
            GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role, postgres;

            NOTIFY pgrst, 'reload schema';
            """
        )
    )


def downgrade() -> None:
    pass
