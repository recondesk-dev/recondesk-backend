"""Import pipeline production upgrade: reconciliation_run columns, invoice uniques, job_logs.

Revision ID: import_pipeline_upgrade
Revises:
Create Date: 2026-04-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "import_pipeline_upgrade"
down_revision = None
branch_labels = None
depends_on = None


def _constraint_exists(name: str) -> bool:
    conn = op.get_bind()
    r = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_constraint WHERE conname = :n",
        ),
        {"n": name},
    )
    return r.scalar() is not None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    r = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :n",
        ),
        {"n": name},
    )
    return r.scalar() is not None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    r = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c",
        ),
        {"t": table, "c": column},
    )
    return r.scalar() is not None


def upgrade() -> None:
    # --- reconciliation_run: create or alter ---
    if not _table_exists("reconciliation_run"):
        op.execute(
            sa.text(
                """
                CREATE TABLE reconciliation_run (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    client_gstin_id VARCHAR(15) NOT NULL,
                    period VARCHAR(7) NOT NULL,
                    file_type VARCHAR(50) NOT NULL,
                    r2_key TEXT,
                    status VARCHAR(50) NOT NULL DEFAULT 'queued',
                    file_hash VARCHAR(64) NOT NULL DEFAULT '',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    total_records INTEGER NOT NULL DEFAULT 0,
                    inserted_records INTEGER NOT NULL DEFAULT 0,
                    failed_records INTEGER NOT NULL DEFAULT 0,
                    gstr_records_imported INTEGER NOT NULL DEFAULT 0,
                    pr_records_imported INTEGER NOT NULL DEFAULT 0,
                    progress_percent DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                    sanity_report JSONB,
                    status_message TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )
        )
    else:
        for col, ddl in [
            ("file_hash", "VARCHAR(64) NOT NULL DEFAULT ''"),
            ("retry_count", "INTEGER NOT NULL DEFAULT 0"),
            ("total_records", "INTEGER NOT NULL DEFAULT 0"),
            ("inserted_records", "INTEGER NOT NULL DEFAULT 0"),
            ("failed_records", "INTEGER NOT NULL DEFAULT 0"),
            ("gstr_records_imported", "INTEGER NOT NULL DEFAULT 0"),
            ("pr_records_imported", "INTEGER NOT NULL DEFAULT 0"),
            ("progress_percent", "DOUBLE PRECISION NOT NULL DEFAULT 0.0"),
            ("sanity_report", "JSONB"),
            ("status_message", "TEXT"),
        ]:
            if not _column_exists("reconciliation_run", col):
                op.execute(
                    sa.text(f"ALTER TABLE reconciliation_run ADD COLUMN {col} {ddl};")
                )

    if not _constraint_exists("uq_run_dedup"):
        op.execute(
            sa.text(
                """
                ALTER TABLE reconciliation_run
                ADD CONSTRAINT uq_run_dedup
                UNIQUE (client_gstin_id, period, file_type, file_hash);
                """
            )
        )

    # --- gstr2b_invoices ---
    if not _table_exists("gstr2b_invoices"):
        op.execute(
            sa.text(
                """
                CREATE TABLE gstr2b_invoices (
                    id BIGSERIAL PRIMARY KEY,
                    client_gstin_id VARCHAR(15) NOT NULL,
                    period VARCHAR(7) NOT NULL,
                    supplier_gstin TEXT NOT NULL,
                    invoice_number TEXT NOT NULL,
                    run_id UUID NOT NULL REFERENCES reconciliation_run(id) ON DELETE CASCADE,
                    invoice_date DATE,
                    payload JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )
        )

    if not _constraint_exists("uq_gstr2b_invoice"):
        op.execute(
            sa.text(
                """
                ALTER TABLE gstr2b_invoices
                ADD CONSTRAINT uq_gstr2b_invoice
                UNIQUE (client_gstin_id, period, supplier_gstin, invoice_number);
                """
            )
        )

    # --- purchase_register_invoices ---
    if not _table_exists("purchase_register_invoices"):
        op.execute(
            sa.text(
                """
                CREATE TABLE purchase_register_invoices (
                    id BIGSERIAL PRIMARY KEY,
                    client_gstin_id VARCHAR(15) NOT NULL,
                    period VARCHAR(7) NOT NULL,
                    supplier_gstin TEXT NOT NULL,
                    invoice_number TEXT NOT NULL,
                    run_id UUID NOT NULL REFERENCES reconciliation_run(id) ON DELETE CASCADE,
                    invoice_date DATE,
                    taxable_value NUMERIC,
                    igst NUMERIC,
                    cgst NUMERIC,
                    sgst NUMERIC,
                    raw JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )
        )

    if not _constraint_exists("uq_pr_invoice"):
        op.execute(
            sa.text(
                """
                ALTER TABLE purchase_register_invoices
                ADD CONSTRAINT uq_pr_invoice
                UNIQUE (client_gstin_id, period, supplier_gstin, invoice_number);
                """
            )
        )

    # --- job_logs ---
    if not _table_exists("job_logs"):
        op.execute(
            sa.text(
                """
                CREATE TABLE job_logs (
                    id SERIAL PRIMARY KEY,
                    run_id UUID NOT NULL REFERENCES reconciliation_run(id) ON DELETE CASCADE,
                    step_name VARCHAR(100) NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    error_details TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )
        )
        if _table_exists("job_logs"):
            op.execute(
                sa.text(
                    "CREATE INDEX IF NOT EXISTS idx_job_logs_run_id ON job_logs(run_id);"
                )
            )


def downgrade() -> None:
    if _table_exists("job_logs"):
        op.execute(sa.text("DROP TABLE IF EXISTS job_logs CASCADE;"))

    if _constraint_exists("uq_pr_invoice"):
        op.execute(
            sa.text("ALTER TABLE purchase_register_invoices DROP CONSTRAINT uq_pr_invoice;")
        )
    if _table_exists("purchase_register_invoices"):
        op.execute(sa.text("DROP TABLE IF EXISTS purchase_register_invoices CASCADE;"))

    if _constraint_exists("uq_gstr2b_invoice"):
        op.execute(
            sa.text("ALTER TABLE gstr2b_invoices DROP CONSTRAINT uq_gstr2b_invoice;")
        )
    if _table_exists("gstr2b_invoices"):
        op.execute(sa.text("DROP TABLE IF EXISTS gstr2b_invoices CASCADE;"))

    if _constraint_exists("uq_run_dedup"):
        op.execute(sa.text("ALTER TABLE reconciliation_run DROP CONSTRAINT uq_run_dedup;"))

    # Leave reconciliation_run table in place if it pre-existed; only drop if empty migration created it
    # (safe no-op if columns added only)
    op.execute(sa.text("-- reconciliation_run left in place; manual cleanup if needed"))
