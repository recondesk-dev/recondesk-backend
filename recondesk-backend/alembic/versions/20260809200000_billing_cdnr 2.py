"""Add Credit Notes and Debit Notes (CDNR) tables and columns.

Revision ID: 20260809200000_billing_cdnr
Revises: billing_irp
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260809200000_billing_cdnr"
down_revision = "billing_irp"
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


def _column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    r = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :tname AND column_name = :cname LIMIT 1"
        ),
        {"tname": table_name, "cname": column_name},
    )
    return r.fetchone() is not None


def upgrade() -> None:
    # 1. Add CDN Prefix and Sequence to billing_company_profiles
    if _table_exists("billing_company_profiles"):
        if not _column_exists("billing_company_profiles", "cdn_number_prefix"):
            op.add_column(
                "billing_company_profiles",
                sa.Column("cdn_number_prefix", sa.Text(), nullable=False, server_default="CRN/"),
            )
        if not _column_exists("billing_company_profiles", "cdn_number_next_seq"):
            op.add_column(
                "billing_company_profiles",
                sa.Column("cdn_number_next_seq", sa.BigInteger(), nullable=False, server_default="1"),
            )

    # 2. Create billing_credit_debit_notes table
    if not _table_exists("billing_credit_debit_notes"):
        op.execute(
            sa.text(
                """
                CREATE TABLE public.billing_credit_debit_notes (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
                    original_invoice_id UUID NOT NULL REFERENCES public.billing_invoices(id) ON DELETE RESTRICT,
                    note_type TEXT NOT NULL DEFAULT 'credit' CHECK (note_type IN ('credit', 'debit')),
                    note_number TEXT NOT NULL,
                    note_date DATE NOT NULL DEFAULT CURRENT_DATE,
                    reason TEXT NOT NULL DEFAULT '1-Sales Return' CHECK (reason IN (
                        '1-Sales Return',
                        '2-Post Sale Discount',
                        '3-Deficiency in Service',
                        '4-Correction in Invoice',
                        '5-Change in POS',
                        '6-Finalization of Provisional Assessment',
                        '7-Others'
                    )),
                    reason_detail TEXT,
                    subtotal_paise BIGINT NOT NULL DEFAULT 0,
                    total_tax_paise BIGINT NOT NULL DEFAULT 0,
                    total_paise BIGINT NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'finalized', 'cancelled')),
                    irn TEXT,
                    irn_ack_number TEXT,
                    irn_ack_date TIMESTAMPTZ,
                    irn_qr_code TEXT,
                    irn_signed_json JSONB,
                    irp_status TEXT NOT NULL DEFAULT 'not_submitted',
                    irp_error_detail TEXT,
                    irp_environment TEXT NOT NULL DEFAULT 'test',
                    notes TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_billing_cdn_client_num UNIQUE (client_gstin_id, note_number)
                );

                CREATE INDEX IF NOT EXISTS idx_billing_cdn_client ON public.billing_credit_debit_notes(client_gstin_id);
                CREATE INDEX IF NOT EXISTS idx_billing_cdn_orig_inv ON public.billing_credit_debit_notes(original_invoice_id);
                CREATE INDEX IF NOT EXISTS idx_billing_cdn_irp_status ON public.billing_credit_debit_notes(irp_status);
                CREATE INDEX IF NOT EXISTS idx_billing_cdn_irn ON public.billing_credit_debit_notes(irn);

                ALTER TABLE IF EXISTS public.billing_credit_debit_notes DISABLE ROW LEVEL SECURITY;
                GRANT ALL ON TABLE public.billing_credit_debit_notes TO anon, authenticated, service_role;
                """
            )
        )

    # 3. Create billing_cdn_line_items table
    if not _table_exists("billing_cdn_line_items"):
        op.execute(
            sa.text(
                """
                CREATE TABLE public.billing_cdn_line_items (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    cdn_id UUID NOT NULL REFERENCES public.billing_credit_debit_notes(id) ON DELETE CASCADE,
                    item_id UUID REFERENCES public.billing_items(id) ON DELETE SET NULL,
                    description TEXT NOT NULL,
                    hsn_or_sac_code TEXT NOT NULL,
                    quantity NUMERIC(12,4) NOT NULL DEFAULT 1.0000,
                    unit TEXT NOT NULL DEFAULT 'NOS',
                    rate_paise BIGINT NOT NULL DEFAULT 0,
                    discount_percent NUMERIC(5,2) DEFAULT 0.00,
                    taxable_value_paise BIGINT NOT NULL DEFAULT 0,
                    tax_rate_percent NUMERIC(5,2) NOT NULL DEFAULT 18.00,
                    cgst_paise BIGINT NOT NULL DEFAULT 0,
                    sgst_paise BIGINT NOT NULL DEFAULT 0,
                    igst_paise BIGINT NOT NULL DEFAULT 0,
                    cess_paise BIGINT NOT NULL DEFAULT 0,
                    line_total_paise BIGINT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_billing_cdn_line_items_cdn ON public.billing_cdn_line_items(cdn_id);

                ALTER TABLE IF EXISTS public.billing_cdn_line_items DISABLE ROW LEVEL SECURITY;
                GRANT ALL ON TABLE public.billing_cdn_line_items TO anon, authenticated, service_role;
                """
            )
        )


def downgrade() -> None:
    if _table_exists("billing_cdn_line_items"):
        op.execute(sa.text("DROP TABLE IF EXISTS public.billing_cdn_line_items CASCADE;"))
    if _table_exists("billing_credit_debit_notes"):
        op.execute(sa.text("DROP TABLE IF EXISTS public.billing_credit_debit_notes CASCADE;"))
    if _table_exists("billing_company_profiles"):
        if _column_exists("billing_company_profiles", "cdn_number_next_seq"):
            op.drop_column("billing_company_profiles", "cdn_number_next_seq")
        if _column_exists("billing_company_profiles", "cdn_number_prefix"):
            op.drop_column("billing_company_profiles", "cdn_number_prefix")
