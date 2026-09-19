"""Add e-Invoice IRP submission columns and audit log table.

Revision ID: billing_irp
Revises: 92f7064a0b30_merge_billing_and_tally_bridge_heads
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "billing_irp"
down_revision = "92f7064a0b30"
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
    # 1. Add IRP columns to billing_invoices if missing
    if _table_exists("billing_invoices"):
        if not _column_exists("billing_invoices", "irn_ack_number"):
            op.add_column("billing_invoices", sa.Column("irn_ack_number", sa.Text(), nullable=True))
        if not _column_exists("billing_invoices", "irn_ack_date"):
            op.add_column("billing_invoices", sa.Column("irn_ack_date", postgresql.TIMESTAMP(timezone=True), nullable=True))
        if not _column_exists("billing_invoices", "irn_qr_code"):
            op.add_column("billing_invoices", sa.Column("irn_qr_code", sa.Text(), nullable=True))
        if not _column_exists("billing_invoices", "irn_signed_json"):
            op.add_column("billing_invoices", sa.Column("irn_signed_json", sa.JSON(), nullable=True))
        if not _column_exists("billing_invoices", "irp_status"):
            op.add_column(
                "billing_invoices",
                sa.Column("irp_status", sa.Text(), nullable=False, server_default="not_submitted"),
            )
        if not _column_exists("billing_invoices", "irp_error_detail"):
            op.add_column("billing_invoices", sa.Column("irp_error_detail", sa.Text(), nullable=True))
        if not _column_exists("billing_invoices", "irp_environment"):
            op.add_column(
                "billing_invoices",
                sa.Column("irp_environment", sa.Text(), nullable=False, server_default="test"),
            )

        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_billing_invoices_irp_status ON billing_invoices(irp_status);"
                "CREATE INDEX IF NOT EXISTS idx_billing_invoices_irn ON billing_invoices(irn);"
            )
        )

    # 2. Create billing_irp_submission_log table if missing
    if not _table_exists("billing_irp_submission_log"):
        op.execute(
            sa.text(
                """
                CREATE TABLE billing_irp_submission_log (
                    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    invoice_id       UUID NOT NULL REFERENCES public.billing_invoices(id) ON DELETE CASCADE,
                    client_gstin_id  UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
                    attempted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    environment      TEXT NOT NULL DEFAULT 'test',
                    request_payload  JSONB,
                    response_status  TEXT NOT NULL,
                    response_body    JSONB,
                    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_billing_irp_log_invoice ON billing_irp_submission_log(invoice_id);
                CREATE INDEX IF NOT EXISTS idx_billing_irp_log_client ON billing_irp_submission_log(client_gstin_id);
                ALTER TABLE IF EXISTS billing_irp_submission_log DISABLE ROW LEVEL SECURITY;
                GRANT ALL ON TABLE billing_irp_submission_log TO anon, authenticated, service_role;
                """
            )
        )


def downgrade() -> None:
    if _table_exists("billing_irp_submission_log"):
        op.execute(sa.text("DROP TABLE IF EXISTS billing_irp_submission_log CASCADE;"))
    if _table_exists("billing_invoices"):
        for col in [
            "irn_ack_number",
            "irn_ack_date",
            "irn_qr_code",
            "irn_signed_json",
            "irp_status",
            "irp_error_detail",
            "irp_environment",
        ]:
            if _column_exists("billing_invoices", col):
                op.drop_column("billing_invoices", col)
