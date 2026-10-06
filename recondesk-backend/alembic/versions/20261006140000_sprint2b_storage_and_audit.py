"""Add storage metadata to reconciliation_results and immutability trigger to audit_logs.

Revision ID: 20261006140000_sprint2b_storage_and_audit
Revises: 20260923_payments_b2b_gstin
Create Date: 2026-10-06 14:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20261006140000_sprint2b_storage_and_audit'
down_revision = '20260923_payments_b2b_gstin'
branch_labels = None
depends_on = None


def upgrade():
    # 1. reconciliation_results object storage metadata columns
    op.execute("""
        ALTER TABLE public.reconciliation_results
        ADD COLUMN IF NOT EXISTS storage_type VARCHAR(32) DEFAULT 'db',
        ADD COLUMN IF NOT EXISTS storage_path TEXT,
        ADD COLUMN IF NOT EXISTS payload_size_bytes BIGINT,
        ADD COLUMN IF NOT EXISTS compressed_size_bytes BIGINT;

        CREATE INDEX IF NOT EXISTS idx_reconciliation_results_storage_type
        ON public.reconciliation_results (storage_type);
    """)

    # 2. audit_logs database-level immutability trigger (safe for ON DELETE SET NULL cascade)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.prevent_audit_log_modification()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'audit_logs table is append-only: deletions are strictly forbidden.';
            ELSIF TG_OP = 'UPDATE' THEN
                IF (OLD.firm_id IS NOT NULL AND NEW.firm_id IS NULL)
                   AND (OLD.id = NEW.id)
                   AND (OLD.action = NEW.action)
                   AND (OLD.entity_type = NEW.entity_type)
                   AND (OLD.created_at = NEW.created_at) THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'audit_logs table is append-only: updates are strictly forbidden.';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON public.audit_logs;
        CREATE TRIGGER trg_audit_logs_immutable
        BEFORE UPDATE OR DELETE ON public.audit_logs
        FOR EACH ROW
        EXECUTE FUNCTION public.prevent_audit_log_modification();
    """)


def downgrade():
    op.execute("""
        DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON public.audit_logs;
        DROP FUNCTION IF EXISTS public.prevent_audit_log_modification();

        DROP INDEX IF EXISTS idx_reconciliation_results_storage_type;

        ALTER TABLE public.reconciliation_results
        DROP COLUMN IF EXISTS storage_type,
        DROP COLUMN IF EXISTS storage_path,
        DROP COLUMN IF EXISTS payload_size_bytes,
        DROP COLUMN IF EXISTS compressed_size_bytes;
    """)
