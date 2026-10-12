-- ============================================================================
-- Migration: 20261012140000_create_gstr1a_amendments.up.sql
-- Description: Phase 4.1 - GSTR-1A Amendment Intelligence & Filing Integration
--              Tables for GSTR-1A amendment batches, items, original vs revised
--              diffs, tax deltas, and immutable audit trail.
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

-- 1. Extend return_filing_approvals check constraint to include GSTR-1A
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'return_filing_approvals_return_type_check'
          AND table_name = 'return_filing_approvals'
    ) THEN
        ALTER TABLE public.return_filing_approvals
            DROP CONSTRAINT return_filing_approvals_return_type_check;
        ALTER TABLE public.return_filing_approvals
            ADD CONSTRAINT return_filing_approvals_return_type_check
            CHECK (return_type IN ('GSTR-1', 'GSTR-3B', 'GSTR-4', 'GSTR-9', 'GSTR-9C', 'GSTR-1A'));
    END IF;
END $$;

-- 2. Extend client_filing_authorizations check constraint to include GSTR-1A
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'client_filing_authorizations_return_type_check'
          AND table_name = 'client_filing_authorizations'
    ) THEN
        ALTER TABLE public.client_filing_authorizations
            DROP CONSTRAINT client_filing_authorizations_return_type_check;
        ALTER TABLE public.client_filing_authorizations
            ADD CONSTRAINT client_filing_authorizations_return_type_check
            CHECK (return_type IN ('GSTR-1', 'GSTR-3B', 'GSTR-4', 'GSTR-9', 'GSTR-9C', 'GSTR-1A'));
    END IF;
END $$;

-- 3. Table: public.gstr1a_amendment_batches
CREATE TABLE IF NOT EXISTS public.gstr1a_amendment_batches (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id                 UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id         UUID NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    gstin                   VARCHAR(15) NOT NULL,
    period                  VARCHAR(7) NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    status                  VARCHAR(30) NOT NULL DEFAULT 'DRAFT'
                            CHECK (status IN (
                                'DRAFT',
                                'PREPARED',
                                'UNDER_REVIEW',
                                'APPROVED',
                                'REJECTED',
                                'SAVED',
                                'FILED'
                            )),
    figures_digest          VARCHAR(64) NOT NULL DEFAULT '',
    total_additions         INT NOT NULL DEFAULT 0,
    total_amendments        INT NOT NULL DEFAULT 0,
    delta_taxable_value     NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    delta_igst              NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    delta_cgst              NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    delta_sgst              NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    delta_cess              NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    gstn_reference_id       VARCHAR(100),
    gstn_status             VARCHAR(20),
    arn                     VARCHAR(50),
    filing_run_id           UUID REFERENCES public.filing_runs (id) ON DELETE SET NULL,
    created_by              UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_gstr1a_batch UNIQUE (firm_id, client_gstin_id, period)
);

CREATE INDEX IF NOT EXISTS idx_gstr1a_batches_lookup
    ON public.gstr1a_amendment_batches (firm_id, client_gstin_id, period);

CREATE INDEX IF NOT EXISTS idx_gstr1a_batches_status
    ON public.gstr1a_amendment_batches (status);

-- 4. Table: public.gstr1a_amendment_items
CREATE TABLE IF NOT EXISTS public.gstr1a_amendment_items (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                UUID NOT NULL REFERENCES public.gstr1a_amendment_batches (id) ON DELETE CASCADE,
    firm_id                 UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id         UUID NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    period                  VARCHAR(7) NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    table_name              VARCHAR(20) NOT NULL,
    action_type             VARCHAR(20) NOT NULL CHECK (action_type IN ('ADDITION', 'AMENDMENT', 'DELETE')),
    original_invoice_number VARCHAR(100),
    original_invoice_date   DATE,
    amended_invoice_number  VARCHAR(100),
    amended_invoice_date    DATE,
    recipient_gstin         VARCHAR(15),
    pos                     VARCHAR(5),
    supply_type             VARCHAR(20),
    original_payload        JSONB NOT NULL DEFAULT '{}'::jsonb,
    amended_payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    diff_summary            JSONB NOT NULL DEFAULT '{}'::jsonb,
    delta_taxable_value     NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    delta_igst              NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    delta_cgst              NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    delta_sgst              NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    delta_cess              NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    item_digest             VARCHAR(64) NOT NULL DEFAULT '',
    source_note             TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr1a_items_batch
    ON public.gstr1a_amendment_items (batch_id);

CREATE INDEX IF NOT EXISTS idx_gstr1a_items_lookup
    ON public.gstr1a_amendment_items (firm_id, client_gstin_id, period, table_name);

CREATE INDEX IF NOT EXISTS idx_gstr1a_items_invoices
    ON public.gstr1a_amendment_items (client_gstin_id, period, original_invoice_number, amended_invoice_number);

-- 5. Table: public.gstr1a_amendment_audit_trail
CREATE TABLE IF NOT EXISTS public.gstr1a_amendment_audit_trail (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                UUID NOT NULL REFERENCES public.gstr1a_amendment_batches (id) ON DELETE CASCADE,
    firm_id                 UUID NOT NULL,
    action                  VARCHAR(50) NOT NULL,
    actor_id                UUID,
    actor_name              VARCHAR(255) NOT NULL,
    actor_role              VARCHAR(50) NOT NULL,
    from_status             VARCHAR(30),
    to_status               VARCHAR(30),
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr1a_audit_batch
    ON public.gstr1a_amendment_audit_trail (batch_id, created_at DESC);

COMMENT ON TABLE public.gstr1a_amendment_batches IS
    'Phase 4.1: Tracks GSTR-1A amendment batches per client GSTIN and tax period with tax deltas and figures digest.';

COMMENT ON TABLE public.gstr1a_amendment_items IS
    'Phase 4.1: Individual invoice additions and Table 9/10 amendments with original vs revised diffs and tax delta calculations.';

COMMENT ON TABLE public.gstr1a_amendment_audit_trail IS
    'Phase 4.1: Tamper-evident audit log for GSTR-1A amendment lifecycle transitions and approvals.';

-- 6. Idempotently restore historical data if rolling forward from a previous archive
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = '_archive_gstr1a_batches_rollback'
    ) THEN
        INSERT INTO public.gstr1a_amendment_batches (
            id, firm_id, client_gstin_id, gstin, period, status,
            figures_digest, total_additions, total_amendments,
            delta_taxable_value, delta_igst, delta_cgst, delta_sgst, delta_cess,
            gstn_reference_id, gstn_status, arn, filing_run_id, created_by,
            created_at, updated_at
        )
        SELECT
            batch_id, firm_id, client_gstin_id, gstin, period, status,
            figures_digest, total_additions, total_amendments,
            delta_taxable_value, delta_igst, delta_cgst, delta_sgst, delta_cess,
            gstn_reference_id, gstn_status, arn, filing_run_id, created_by,
            created_at, archived_at
        FROM public._archive_gstr1a_batches_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = '_archive_gstr1a_items_rollback'
    ) THEN
        INSERT INTO public.gstr1a_amendment_items (
            id, batch_id, firm_id, client_gstin_id, period, table_name,
            action_type, original_invoice_number, original_invoice_date,
            amended_invoice_number, amended_invoice_date, recipient_gstin,
            pos, supply_type, original_payload, amended_payload, diff_summary,
            delta_taxable_value, delta_igst, delta_cgst, delta_sgst, delta_cess,
            item_digest, source_note, created_at, updated_at
        )
        SELECT
            item_id, batch_id, firm_id, client_gstin_id, period, table_name,
            action_type, original_invoice_number, original_invoice_date,
            amended_invoice_number, amended_invoice_date, recipient_gstin,
            pos, supply_type, original_payload, amended_payload, diff_summary,
            delta_taxable_value, delta_igst, delta_cgst, delta_sgst, delta_cess,
            item_digest, source_note, created_at, archived_at
        FROM public._archive_gstr1a_items_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = '_archive_gstr1a_audit_trail_rollback'
    ) THEN
        INSERT INTO public.gstr1a_amendment_audit_trail (
            id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
            from_status, to_status, details, created_at
        )
        SELECT
            entry_id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
            from_status, to_status, details, created_at
        FROM public._archive_gstr1a_audit_trail_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;
END $$;

