-- ============================================================================
-- Migration: 20261006100000_create_batch3a_return_reconciliation.up.sql
-- Description: Phase 9F-1 (Batch 3A) — Return Reconciliation & Audit Overrides:
--              1. multi_period_recon_batches
--              2. multi_period_recon_batch_items
--              3. gstr1_reconciliation_run
--              4. gstr1a_period_actions
--              5. gstr2a_delta_results
--              6. gstr9_audit_overrides
-- Target: AWS Aurora PostgreSQL (ap-south-1)
-- Source-compatible: All column semantics, nullability, and constraints preserved
--   exactly as confirmed from live Supabase PostgREST OpenAPI schema audit.
-- Parent dependencies: user_profiles, client_gstins, reconciliation_run (all in Aurora).
-- No circular FKs. No FKs to auth.users (Cognito-migrated; replaced with nullable UUID).
-- ============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. multi_period_recon_batches
--    Parent of multi_period_recon_batch_items.
--    Tenant scope: client_gstin_id -> client_gstins(id).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.multi_period_recon_batches (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id     UUID        NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    financial_year      VARCHAR(10) NOT NULL,
    status              TEXT        NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    -- nullable: creator may be NULL for programmatic batches
    created_by          UUID        REFERENCES public.user_profiles(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_mpreb_client_gstin_id
    ON public.multi_period_recon_batches (client_gstin_id);

CREATE INDEX IF NOT EXISTS ix_mpreb_status
    ON public.multi_period_recon_batches (status);

CREATE INDEX IF NOT EXISTS ix_mpreb_financial_year
    ON public.multi_period_recon_batches (financial_year);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. multi_period_recon_batch_items
--    Child of multi_period_recon_batches.
--    FK to reconciliation_run is nullable (item may be pending with no run yet).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.multi_period_recon_batch_items (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id              UUID        NOT NULL REFERENCES public.multi_period_recon_batches(id) ON DELETE CASCADE,
    period                VARCHAR(20) NOT NULL,
    status                TEXT        NOT NULL,
    reconciliation_run_id UUID        REFERENCES public.reconciliation_run(id) ON DELETE SET NULL,
    gstr2b_file_path      TEXT,
    gstr2b_source         TEXT,
    pr_file_path          TEXT,
    pr_source             TEXT,
    error_message         TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    -- Business key: one item per (batch, period)
    CONSTRAINT uq_batch_period UNIQUE (batch_id, period)
);

CREATE INDEX IF NOT EXISTS ix_mprebi_batch_id
    ON public.multi_period_recon_batch_items (batch_id);

CREATE INDEX IF NOT EXISTS ix_mprebi_status
    ON public.multi_period_recon_batch_items (status);

CREATE INDEX IF NOT EXISTS ix_mprebi_recon_run
    ON public.multi_period_recon_batch_items (reconciliation_run_id)
    WHERE reconciliation_run_id IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. gstr1_reconciliation_run
--    Independent per-client GSTR-1 vs SR comparison run record.
--    Parent of gstr1a_period_actions.
--    Stores large result payloads and summaries as JSONB.
--    completed_at is NOT NULL in source — preserve (use source value verbatim).
--    created_by is nullable UUID (Cognito user identifier).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.gstr1_reconciliation_run (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id  UUID        NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    status           TEXT        NOT NULL,
    result_payload   JSONB       NOT NULL DEFAULT '{}'::jsonb,
    run_summary      JSONB,
    period           VARCHAR(10),
    gstr1_filed_date DATE,
    gstr3b_filed_date DATE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    completed_at     TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    -- nullable: creator may be a text user-id from legacy Supabase auth
    created_by       UUID
);

CREATE INDEX IF NOT EXISTS ix_g1rr_client_gstin_id
    ON public.gstr1_reconciliation_run (client_gstin_id);

CREATE INDEX IF NOT EXISTS ix_g1rr_status
    ON public.gstr1_reconciliation_run (status);

CREATE INDEX IF NOT EXISTS ix_g1rr_period
    ON public.gstr1_reconciliation_run (period)
    WHERE period IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. gstr1a_period_actions
--    Child of gstr1_reconciliation_run.
--    Tracks CA accept/reject actions on GSTR-1A amendments per period.
--    user_id is TEXT in source (not UUID FK — preserves legacy Supabase auth uid format).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.gstr1a_period_actions (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id     UUID        NOT NULL REFERENCES public.gstr1_reconciliation_run(id) ON DELETE CASCADE,
    period     VARCHAR(20) NOT NULL,
    status     TEXT        NOT NULL,
    -- user_id stored as TEXT to preserve legacy Supabase auth uid strings exactly
    user_id    TEXT        NOT NULL,
    note       TEXT,
    filed_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS ix_g1pa_run_id
    ON public.gstr1a_period_actions (run_id);

CREATE INDEX IF NOT EXISTS ix_g1pa_period
    ON public.gstr1a_period_actions (period);

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. gstr2a_delta_results
--    Stores GSTR-2A vs GSTR-2B delta reconciliation snapshots.
--    summary and results are large JSONB payloads.
--    cutoff_date is nullable.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.gstr2a_delta_results (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id UUID        NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    period          TEXT        NOT NULL,
    reconciled_at   TIMESTAMPTZ NOT NULL,
    summary         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    results         JSONB       NOT NULL DEFAULT '[]'::jsonb,
    cutoff_date     DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS ix_g2dr_client_gstin_id
    ON public.gstr2a_delta_results (client_gstin_id);

CREATE INDEX IF NOT EXISTS ix_g2dr_period
    ON public.gstr2a_delta_results (period);

CREATE INDEX IF NOT EXISTS ix_g2dr_client_period
    ON public.gstr2a_delta_results (client_gstin_id, period);

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. gstr9_audit_overrides
--    Stores CA manual overrides for GSTR-9 annual return cells.
--    Unique per (client_gstin_id, financial_year, table_key, cell_key).
--    system_value and override_value are NUMERIC(15,2) matching source.
--    updated_by is nullable UUID (CA who made the override; no FK to avoid Cognito-id mismatch).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.gstr9_audit_overrides (
    id               UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id  UUID           NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    financial_year   TEXT           NOT NULL,
    table_key        TEXT           NOT NULL,
    cell_key         TEXT           NOT NULL,
    system_value     NUMERIC(15, 2) DEFAULT 0.00,
    override_value   NUMERIC(15, 2) NOT NULL,
    notes            TEXT,
    -- nullable: no FK to avoid breakage from Cognito UID migration history
    updated_by       UUID,
    updated_at       TIMESTAMPTZ    NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT uq_gstr9_override_cell UNIQUE (client_gstin_id, financial_year, table_key, cell_key)
);

CREATE INDEX IF NOT EXISTS ix_g9ao_client_gstin_id
    ON public.gstr9_audit_overrides (client_gstin_id);

CREATE INDEX IF NOT EXISTS ix_g9ao_client_fy
    ON public.gstr9_audit_overrides (client_gstin_id, financial_year);
