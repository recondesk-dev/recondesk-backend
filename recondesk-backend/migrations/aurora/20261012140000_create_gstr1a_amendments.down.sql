-- ============================================================================
-- Migration: 20261012140000_create_gstr1a_amendments.down.sql
-- Description: Phase 4.1 - Safe Non-Destructive Rollback of GSTR-1A Amendments
-- Target: AWS Aurora PostgreSQL
-- ============================================================================
-- PRODUCTION ROLLBACK ADVISORY:
-- In production AWS Aurora environments, the authoritative recovery procedure
-- for release failure is AWS Aurora Point-in-Time Recovery (PITR) or cluster
-- snapshot restoration. Schema downgrades on live databases risk breaking
-- statutory audit records.
--
-- This script implements a NON-DESTRUCTIVE archival rollback pattern:
-- 1. Archives audit trail history into `_archive_gstr1a_audit_trail_rollback`.
-- 2. Archives amendment items into `_archive_gstr1a_items_rollback`.
-- 3. Archives amendment batches into `_archive_gstr1a_batches_rollback`.
-- 4. Safely removes active tables only after records are durably archived.
-- ============================================================================

-- 1. Archive gstr1a_amendment_audit_trail
CREATE TABLE IF NOT EXISTS public._archive_gstr1a_audit_trail_rollback (
    archive_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entry_id        UUID NOT NULL,
    batch_id        UUID NOT NULL,
    firm_id         UUID NOT NULL,
    action          VARCHAR(50) NOT NULL,
    actor_id        UUID,
    actor_name      VARCHAR(255) NOT NULL,
    actor_role      VARCHAR(50) NOT NULL,
    from_status     VARCHAR(30),
    to_status       VARCHAR(30),
    details         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL,
    archived_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr1a_amendment_audit_trail'
    ) THEN
        INSERT INTO public._archive_gstr1a_audit_trail_rollback (
            entry_id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
            from_status, to_status, details, created_at
        )
        SELECT id, batch_id, firm_id, action, actor_id, actor_name, actor_role,
               from_status, to_status, details, created_at
        FROM public.gstr1a_amendment_audit_trail
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

-- 2. Archive gstr1a_amendment_items
CREATE TABLE IF NOT EXISTS public._archive_gstr1a_items_rollback (
    archive_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id                 UUID NOT NULL,
    batch_id                UUID NOT NULL,
    firm_id                 UUID NOT NULL,
    client_gstin_id         UUID NOT NULL,
    period                  VARCHAR(7) NOT NULL,
    table_name              VARCHAR(20) NOT NULL,
    action_type             VARCHAR(20) NOT NULL,
    original_invoice_number VARCHAR(100),
    original_invoice_date   DATE,
    amended_invoice_number  VARCHAR(100),
    amended_invoice_date    DATE,
    recipient_gstin         VARCHAR(15),
    pos                     VARCHAR(5),
    supply_type             VARCHAR(20),
    original_payload        JSONB NOT NULL,
    amended_payload         JSONB NOT NULL,
    diff_summary            JSONB NOT NULL,
    delta_taxable_value     NUMERIC(15, 2) NOT NULL,
    delta_igst              NUMERIC(15, 2) NOT NULL,
    delta_cgst              NUMERIC(15, 2) NOT NULL,
    delta_sgst              NUMERIC(15, 2) NOT NULL,
    delta_cess              NUMERIC(15, 2) NOT NULL,
    item_digest             VARCHAR(64) NOT NULL,
    source_note             TEXT,
    created_at              TIMESTAMPTZ NOT NULL,
    archived_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr1a_amendment_items'
    ) THEN
        INSERT INTO public._archive_gstr1a_items_rollback (
            item_id, batch_id, firm_id, client_gstin_id, period, table_name,
            action_type, original_invoice_number, original_invoice_date,
            amended_invoice_number, amended_invoice_date, recipient_gstin,
            pos, supply_type, original_payload, amended_payload, diff_summary,
            delta_taxable_value, delta_igst, delta_cgst, delta_sgst, delta_cess,
            item_digest, source_note, created_at
        )
        SELECT id, batch_id, firm_id, client_gstin_id, period, table_name,
               action_type, original_invoice_number, original_invoice_date,
               amended_invoice_number, amended_invoice_date, recipient_gstin,
               pos, supply_type, original_payload, amended_payload, diff_summary,
               delta_taxable_value, delta_igst, delta_cgst, delta_sgst, delta_cess,
               item_digest, source_note, created_at
        FROM public.gstr1a_amendment_items
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

-- 3. Archive gstr1a_amendment_batches
CREATE TABLE IF NOT EXISTS public._archive_gstr1a_batches_rollback (
    archive_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id            UUID NOT NULL,
    firm_id             UUID NOT NULL,
    client_gstin_id     UUID NOT NULL,
    gstin               VARCHAR(15) NOT NULL,
    period              VARCHAR(7) NOT NULL,
    status              VARCHAR(30) NOT NULL,
    figures_digest      VARCHAR(64) NOT NULL,
    total_additions     INT NOT NULL,
    total_amendments    INT NOT NULL,
    delta_taxable_value NUMERIC(15, 2) NOT NULL,
    delta_igst          NUMERIC(15, 2) NOT NULL,
    delta_cgst          NUMERIC(15, 2) NOT NULL,
    delta_sgst          NUMERIC(15, 2) NOT NULL,
    delta_cess          NUMERIC(15, 2) NOT NULL,
    gstn_reference_id   VARCHAR(100),
    gstn_status         VARCHAR(20),
    arn                 VARCHAR(50),
    filing_run_id       UUID,
    created_by          UUID,
    created_at          TIMESTAMPTZ NOT NULL,
    archived_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'gstr1a_amendment_batches'
    ) THEN
        INSERT INTO public._archive_gstr1a_batches_rollback (
            batch_id, firm_id, client_gstin_id, gstin, period, status,
            figures_digest, total_additions, total_amendments,
            delta_taxable_value, delta_igst, delta_cgst, delta_sgst, delta_cess,
            gstn_reference_id, gstn_status, arn, filing_run_id, created_by,
            created_at
        )
        SELECT id, firm_id, client_gstin_id, gstin, period, status,
               figures_digest, total_additions, total_amendments,
               delta_taxable_value, delta_igst, delta_cgst, delta_sgst, delta_cess,
               gstn_reference_id, gstn_status, arn, filing_run_id, created_by,
               created_at
        FROM public.gstr1a_amendment_batches
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;

-- 4. Drop active tables safely
DROP TABLE IF EXISTS public.gstr1a_amendment_audit_trail CASCADE;
DROP TABLE IF EXISTS public.gstr1a_amendment_items CASCADE;
DROP TABLE IF EXISTS public.gstr1a_amendment_batches CASCADE;
