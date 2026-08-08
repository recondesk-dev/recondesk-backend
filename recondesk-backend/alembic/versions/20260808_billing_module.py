"""Add billing module master and invoice tables.

Revision ID: billing_module
Revises: filing_batches
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "billing_module"
down_revision = "filing_batches"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    r = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :name LIMIT 1"
        ),
        {"name": name},
    )
    return r.fetchone() is not None


def upgrade() -> None:
    if not _table_exists("billing_company_profiles"):
        op.execute(
            sa.text(
                """
                CREATE TABLE billing_company_profiles (
                    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    client_gstin_id         UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
                    legal_name              TEXT NOT NULL,
                    trade_name              TEXT,
                    address_line1           TEXT NOT NULL DEFAULT '',
                    address_line2           TEXT,
                    city                    TEXT NOT NULL DEFAULT '',
                    state                   TEXT NOT NULL DEFAULT '',
                    state_code              VARCHAR(2) NOT NULL,
                    pincode                 TEXT NOT NULL DEFAULT '',
                    gstin                   TEXT NOT NULL,
                    pan                     TEXT,
                    bank_account_number     TEXT,
                    bank_ifsc               TEXT,
                    bank_name               TEXT,
                    invoice_number_prefix   TEXT NOT NULL DEFAULT '',
                    invoice_number_next_seq BIGINT NOT NULL DEFAULT 1,
                    financial_year_reset    BOOLEAN NOT NULL DEFAULT true,
                    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_billing_company_profiles_client ON billing_company_profiles(client_gstin_id);
                """
            )
        )

    if not _table_exists("billing_customers"):
        op.execute(
            sa.text(
                """
                CREATE TABLE billing_customers (
                    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
                    name            TEXT NOT NULL,
                    gstin           TEXT,
                    address_line1   TEXT NOT NULL DEFAULT '',
                    address_line2   TEXT,
                    city            TEXT NOT NULL DEFAULT '',
                    state           TEXT NOT NULL DEFAULT '',
                    state_code      VARCHAR(2) NOT NULL,
                    pincode         TEXT NOT NULL DEFAULT '',
                    is_b2b          BOOLEAN NOT NULL DEFAULT true,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_billing_customers_client ON billing_customers(client_gstin_id);
                """
            )
        )

    if not _table_exists("billing_items"):
        op.execute(
            sa.text(
                """
                CREATE TABLE billing_items (
                    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    client_gstin_id          UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
                    name                     TEXT NOT NULL,
                    hsn_or_sac_code          TEXT NOT NULL,
                    unit                     TEXT NOT NULL DEFAULT 'NOS',
                    default_rate             BIGINT NOT NULL DEFAULT 0,
                    default_tax_rate_percent NUMERIC(5,2) NOT NULL DEFAULT 18.00,
                    item_type                TEXT NOT NULL DEFAULT 'goods' CHECK (item_type IN ('goods', 'service')),
                    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_billing_items_client ON billing_items(client_gstin_id);
                """
            )
        )

    if not _table_exists("billing_invoices"):
        op.execute(
            sa.text(
                """
                CREATE TABLE billing_invoices (
                    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    client_gstin_id    UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
                    company_profile_id UUID NOT NULL REFERENCES public.billing_company_profiles(id) ON DELETE RESTRICT,
                    customer_id        UUID NOT NULL REFERENCES public.billing_customers(id) ON DELETE RESTRICT,
                    invoice_number     TEXT NOT NULL,
                    invoice_date       DATE NOT NULL DEFAULT CURRENT_DATE,
                    due_date           DATE,
                    place_of_supply    VARCHAR(2) NOT NULL,
                    is_interstate      BOOLEAN NOT NULL DEFAULT false,
                    subtotal_paise     BIGINT NOT NULL DEFAULT 0,
                    total_tax_paise    BIGINT NOT NULL DEFAULT 0,
                    total_paise        BIGINT NOT NULL DEFAULT 0,
                    status             TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'finalized', 'cancelled')),
                    irn                TEXT,
                    notes              TEXT,
                    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_billing_invoices_client_inv_num UNIQUE (client_gstin_id, invoice_number)
                );
                CREATE INDEX IF NOT EXISTS idx_billing_invoices_client ON billing_invoices(client_gstin_id);
                CREATE INDEX IF NOT EXISTS idx_billing_invoices_company ON billing_invoices(company_profile_id);
                CREATE INDEX IF NOT EXISTS idx_billing_invoices_customer ON billing_invoices(customer_id);
                """
            )
        )

    if not _table_exists("billing_invoice_line_items"):
        op.execute(
            sa.text(
                """
                CREATE TABLE billing_invoice_line_items (
                    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    invoice_id          UUID NOT NULL REFERENCES public.billing_invoices(id) ON DELETE CASCADE,
                    item_id             UUID REFERENCES public.billing_items(id) ON DELETE SET NULL,
                    description         TEXT NOT NULL,
                    hsn_or_sac_code     TEXT NOT NULL,
                    quantity            NUMERIC(12,4) NOT NULL DEFAULT 1.0000,
                    unit                TEXT NOT NULL DEFAULT 'NOS',
                    rate_paise          BIGINT NOT NULL DEFAULT 0,
                    discount_percent    NUMERIC(5,2) DEFAULT 0.00,
                    taxable_value_paise BIGINT NOT NULL DEFAULT 0,
                    cgst_rate_percent   NUMERIC(5,2) DEFAULT 0.00,
                    cgst_paise          BIGINT DEFAULT 0,
                    sgst_rate_percent   NUMERIC(5,2) DEFAULT 0.00,
                    sgst_paise          BIGINT DEFAULT 0,
                    igst_rate_percent   NUMERIC(5,2) DEFAULT 0.00,
                    igst_paise          BIGINT DEFAULT 0,
                    cess_paise          BIGINT DEFAULT 0,
                    line_total_paise    BIGINT NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_billing_line_items_invoice ON billing_invoice_line_items(invoice_id);
                """
            )
        )

    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION increment_invoice_number_seq(p_profile_id uuid)
            RETURNS TABLE (prefix text, seq bigint)
            LANGUAGE plpgsql
            SECURITY DEFINER
            AS $$
            BEGIN
                RETURN QUERY
                UPDATE billing_company_profiles
                SET invoice_number_next_seq = invoice_number_next_seq + 1,
                    updated_at = now()
                WHERE id = p_profile_id
                RETURNING invoice_number_prefix AS prefix, (invoice_number_next_seq - 1) AS seq;
            END;
            $$;

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
    if _table_exists("billing_invoice_line_items"):
        op.execute(sa.text("DROP TABLE IF EXISTS billing_invoice_line_items CASCADE;"))
    if _table_exists("billing_invoices"):
        op.execute(sa.text("DROP TABLE IF EXISTS billing_invoices CASCADE;"))
    if _table_exists("billing_items"):
        op.execute(sa.text("DROP TABLE IF EXISTS billing_items CASCADE;"))
    if _table_exists("billing_customers"):
        op.execute(sa.text("DROP TABLE IF EXISTS billing_customers CASCADE;"))
    if _table_exists("billing_company_profiles"):
        op.execute(sa.text("DROP TABLE IF EXISTS billing_company_profiles CASCADE;"))
