-- ============================================================================
-- Migration: 20261004100000_create_batch2b_gstr3b_tables.up.sql
-- Description: Phase 9D-6 (Batch 2B) - GSTR-3B Table 4, Reversal & Reclaim Ledger:
--              gstr3b_reversal_ledger, gstr3b_table4_summaries,
--              gstr3b_table4_adjustments, gstr3b_reconciliation,
--              gstr3b_reclaim_events, and fn_execute_reclaim_event RPC.
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

-- 1. Table: public.gstr3b_reversal_ledger
-- Cross-period statutory reversal ledger tracking temporary reversals under GSTR-3B Table 4(B)(2).
-- NOTE: created_by is a bare UUID without FK to user_profiles; historical rows
-- contain non-user UUIDs from auth.users, matching Supabase reality.
CREATE TABLE IF NOT EXISTS public.gstr3b_reversal_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    source_type VARCHAR(30) NOT NULL,
    source_record_id TEXT NOT NULL,
    source_run_id UUID REFERENCES public.reconciliation_run(id) ON DELETE RESTRICT,
    reversal_tax_period VARCHAR(7) NOT NULL,
    source_state_hash VARCHAR(64) NOT NULL DEFAULT '',
    source_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    document_type VARCHAR(20) NOT NULL DEFAULT 'INVOICE',
    document_number VARCHAR(100),
    document_date DATE,
    supplier_gstin VARCHAR(15),
    reference_doc VARCHAR(150),
    reversal_table4_cell VARCHAR(10) NOT NULL DEFAULT '4B2',
    is_reclaimable BOOLEAN NOT NULL DEFAULT TRUE,
    statutory_reason VARCHAR(60) NOT NULL,
    itc_financial_year VARCHAR(7),
    supplier_outward_statement_period VARCHAR(7),
    supplier_gstr1_filing_date DATE,
    supplier_gstr3b_tax_period VARCHAR(7),
    supplier_gstr3b_filing_status VARCHAR(20) DEFAULT 'UNKNOWN',
    filed_by_september_30 BOOLEAN DEFAULT FALSE,
    september_test_date DATE,
    november_reversal_deadline DATE,
    actual_reversal_date DATE,
    subsequent_supplier_filing_date DATE,
    subsequent_filing_arn VARCHAR(50),
    condition_fulfilled_date DATE,
    reclaim_eligibility_date DATE,
    reversed_igst_paise BIGINT NOT NULL DEFAULT 0,
    reversed_cgst_paise BIGINT NOT NULL DEFAULT 0,
    reversed_sgst_paise BIGINT NOT NULL DEFAULT 0,
    reversed_cess_paise BIGINT NOT NULL DEFAULT 0,
    cached_reclaimed_igst_paise BIGINT NOT NULL DEFAULT 0,
    cached_reclaimed_cgst_paise BIGINT NOT NULL DEFAULT 0,
    cached_reclaimed_sgst_paise BIGINT NOT NULL DEFAULT 0,
    cached_reclaimed_cess_paise BIGINT NOT NULL DEFAULT 0,
    status VARCHAR(25) NOT NULL DEFAULT 'OPEN',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID,

    CONSTRAINT chk_reversal_table4_cell_4b2 CHECK (reversal_table4_cell = '4B2'),
    CONSTRAINT chk_non_negative_reversed_amounts CHECK (
        reversed_igst_paise >= 0 AND reversed_cgst_paise >= 0 AND 
        reversed_sgst_paise >= 0 AND reversed_cess_paise >= 0
    ),
    CONSTRAINT chk_total_reversed_positive CHECK (
        (reversed_igst_paise + reversed_cgst_paise + reversed_sgst_paise + reversed_cess_paise) > 0
    ),
    CONSTRAINT chk_cached_reclaim_le_reversed CHECK (
        cached_reclaimed_igst_paise <= reversed_igst_paise AND
        cached_reclaimed_cgst_paise <= reversed_cgst_paise AND
        cached_reclaimed_sgst_paise <= reversed_sgst_paise AND
        cached_reclaimed_cess_paise <= reversed_cess_paise
    ),
    CONSTRAINT chk_source_type CHECK (
        source_type IN ('RECON_OUTCOME', 'EXCEPTION_DISPOSITION', 'STATUTORY_ADJUSTMENT', 'OPENING_BALANCE')
    ),
    CONSTRAINT chk_statutory_reason CHECK (
        statutory_reason IN (
            'RULE_37_NON_PAYMENT', 'RULE_37A_SUPPLIER_NON_FILING',
            'SECTION_16_2_B_NOT_RECEIVED', 'SECTION_16_2_C_SUPPLIER_TAX_CONDITION',
            'OTHER_TEMPORARY', 'OPENING_BALANCE'
        )
    ),
    CONSTRAINT chk_reversal_status CHECK (
        status IN ('OPEN', 'CONDITION_FULFILLED', 'RECLAIM_AUTHORIZED', 'PARTIALLY_RECLAIMED', 'FULLY_RECLAIMED', 'NON_RECLAIMABLE')
    ),
    CONSTRAINT chk_reclaimable_status CHECK (
        (is_reclaimable = TRUE AND status IN ('OPEN', 'CONDITION_FULFILLED', 'RECLAIM_AUTHORIZED', 'PARTIALLY_RECLAIMED', 'FULLY_RECLAIMED')) OR
        (is_reclaimable = FALSE AND status = 'NON_RECLAIMABLE' AND 
         cached_reclaimed_igst_paise = 0 AND cached_reclaimed_cgst_paise = 0 AND 
         cached_reclaimed_sgst_paise = 0 AND cached_reclaimed_cess_paise = 0)
    )
);

CREATE INDEX IF NOT EXISTS idx_reversal_ledger_client_status ON public.gstr3b_reversal_ledger (client_gstin_id, status);
CREATE INDEX IF NOT EXISTS idx_reversal_ledger_source ON public.gstr3b_reversal_ledger (source_type, source_record_id);
CREATE INDEX IF NOT EXISTS idx_reversal_ledger_run_id ON public.gstr3b_reversal_ledger (source_run_id);

COMMENT ON TABLE public.gstr3b_reversal_ledger IS 'General Table 4(B)(2) statutory temporary reversal ledger';


-- 2. Table: public.gstr3b_table4_summaries
-- Authoritative Table 4 workpaper summary snapshots with versioning.
-- NOTE: finalized_by and superseded_by are bare UUIDs without FKs to user_profiles.
CREATE TABLE IF NOT EXISTS public.gstr3b_table4_summaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE RESTRICT,
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    tax_period VARCHAR(7) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PROVISIONAL',
    table_4a1 JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    table_4a2 JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    table_4a3 JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    table_4a4 JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    table_4a5 JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    table_4a_total JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    table_4b1 JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    table_4b2 JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    table_4b_total JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    table_4c JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "total_tax": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    table_4d1 JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    table_4d2 JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    audit_hash VARCHAR(64) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finalized_at TIMESTAMPTZ,
    finalized_by UUID,
    version INTEGER NOT NULL DEFAULT 1,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    superseded_at TIMESTAMPTZ,
    superseded_by UUID,
    source_state_digest VARCHAR(64) NOT NULL DEFAULT '',
    snapshot_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    contributing_outcome_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    contributing_disposition_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    contributing_adjustment_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    contributing_reclaim_ids JSONB NOT NULL DEFAULT '[]'::jsonb,

    CONSTRAINT uq_table4_summary_run_version UNIQUE (run_id, version)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_table4_summary_run_current ON public.gstr3b_table4_summaries (run_id) WHERE is_current = TRUE;
CREATE INDEX IF NOT EXISTS idx_gstr3b_table4_run_id ON public.gstr3b_table4_summaries (run_id);
CREATE INDEX IF NOT EXISTS idx_gstr3b_table4_client_period ON public.gstr3b_table4_summaries (client_gstin_id, tax_period);

COMMENT ON TABLE public.gstr3b_table4_summaries IS 'Authoritative GSTR-3B Table 4 workpaper snapshot summaries';


-- 3. Table: public.gstr3b_table4_adjustments
-- Manual and external statutory additions/reductions directly targeting Table 4 cells.
CREATE TABLE IF NOT EXISTS public.gstr3b_table4_adjustments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE CASCADE,
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    tax_period VARCHAR(7) NOT NULL,
    row_id VARCHAR(10) NOT NULL,
    igst_paise BIGINT NOT NULL DEFAULT 0,
    cgst_paise BIGINT NOT NULL DEFAULT 0,
    sgst_paise BIGINT NOT NULL DEFAULT 0,
    cess_paise BIGINT NOT NULL DEFAULT 0,
    adjustment_type VARCHAR(20) NOT NULL,
    statutory_category VARCHAR(50) NOT NULL,
    reason TEXT NOT NULL,
    reference_doc VARCHAR(100),
    turnover_ratio_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_table4_adj_run_id ON public.gstr3b_table4_adjustments (run_id);
CREATE INDEX IF NOT EXISTS idx_table4_adj_client_period ON public.gstr3b_table4_adjustments (client_gstin_id, tax_period);

COMMENT ON TABLE public.gstr3b_table4_adjustments IS 'Statutory Table 4 cell adjustments (Rules 42/43/38/RCM)';


-- 4. Table: public.gstr3b_reconciliation
-- Summary comparison between filed GSTR-3B values and GSTR-2B available values.
CREATE TABLE IF NOT EXISTS public.gstr3b_reconciliation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE CASCADE,
    client_gstin TEXT NOT NULL,
    tax_period VARCHAR(7) NOT NULL,
    gstr3b_igst_claimed NUMERIC(15,2) DEFAULT 0,
    gstr3b_cgst_claimed NUMERIC(15,2) DEFAULT 0,
    gstr3b_sgst_claimed NUMERIC(15,2) DEFAULT 0,
    gstr2b_igst_available NUMERIC(15,2) DEFAULT 0,
    gstr2b_cgst_available NUMERIC(15,2) DEFAULT 0,
    gstr2b_sgst_available NUMERIC(15,2) DEFAULT 0,
    igst_difference NUMERIC(15,2) DEFAULT 0,
    cgst_difference NUMERIC(15,2) DEFAULT 0,
    sgst_difference NUMERIC(15,2) DEFAULT 0,
    igst_status TEXT,
    cgst_status TEXT,
    sgst_status TEXT,
    overall_status TEXT,
    outward_supply_total NUMERIC(15,2) DEFAULT 0,
    raw_gstr3b JSONB,
    uploaded_by UUID NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gstr3b_recon_run_id ON public.gstr3b_reconciliation (run_id);

COMMENT ON TABLE public.gstr3b_reconciliation IS 'Per-run comparison of ITC available in GSTR-2B vs claimed in GSTR-3B';


-- 5. Table: public.gstr3b_reclaim_events
-- Immutable historical source of truth for reclaims against reversal ledger entries.
-- NOTE: authorized_by is a bare UUID without FK to user_profiles.
CREATE TABLE IF NOT EXISTS public.gstr3b_reclaim_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE RESTRICT,
    ledger_id UUID NOT NULL REFERENCES public.gstr3b_reversal_ledger(id) ON DELETE RESTRICT,
    reclaim_run_id UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE RESTRICT,
    reclaim_tax_period VARCHAR(7) NOT NULL,
    event_type VARCHAR(30) NOT NULL DEFAULT 'RECLAIM',
    compensates_event_id UUID REFERENCES public.gstr3b_reclaim_events(id) ON DELETE RESTRICT,
    reclaimed_igst_paise BIGINT NOT NULL DEFAULT 0,
    reclaimed_cgst_paise BIGINT NOT NULL DEFAULT 0,
    reclaimed_sgst_paise BIGINT NOT NULL DEFAULT 0,
    reclaimed_cess_paise BIGINT NOT NULL DEFAULT 0,
    statutory_evidence_type VARCHAR(50) NOT NULL,
    evidence_reference VARCHAR(150) NOT NULL,
    evidence_document_date DATE,
    authorized_by UUID,
    reclaim_notes TEXT NOT NULL DEFAULT '',
    idempotency_key VARCHAR(120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_reclaim_amounts_non_negative CHECK (
        reclaimed_igst_paise >= 0 AND reclaimed_cgst_paise >= 0 AND 
        reclaimed_sgst_paise >= 0 AND reclaimed_cess_paise >= 0
    ),
    CONSTRAINT chk_reclaim_amounts_positive CHECK (
        (reclaimed_igst_paise + reclaimed_cgst_paise + reclaimed_sgst_paise + reclaimed_cess_paise) > 0
    ),
    CONSTRAINT chk_evidence_type CHECK (
        statutory_evidence_type IN (
            'PAYMENT_TO_SUPPLIER', 'SUPPLIER_GSTR3B_FILED', 'GOODS_RECEIVED_GRN', 
            'TAX_DISCHARGE_CONFIRMED', 'OPENING_BALANCE_VERIFIED', 'COMPENSATING_ADJUSTMENT', 'OTHER_STATUTORY_PROOF'
        )
    ),
    CONSTRAINT chk_event_type CHECK (
        event_type IN ('RECLAIM', 'COMPENSATING_REVERSAL')
    )
);

CREATE INDEX IF NOT EXISTS idx_reclaim_events_ledger_id ON public.gstr3b_reclaim_events (ledger_id);
CREATE INDEX IF NOT EXISTS idx_reclaim_events_run_id ON public.gstr3b_reclaim_events (reclaim_run_id);
CREATE INDEX IF NOT EXISTS idx_reclaim_events_client_id ON public.gstr3b_reclaim_events (client_gstin_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_reclaim_events_client_idempotency ON public.gstr3b_reclaim_events (client_gstin_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

COMMENT ON TABLE public.gstr3b_reclaim_events IS 'Immutable historical audit trail of statutory reclaims against Table 4(B)(2) ledger';


-- 6. Stored Function: fn_execute_reclaim_event
-- Atomic execution with row lock, limit checks, idempotency, and status updates.
CREATE OR REPLACE FUNCTION public.fn_execute_reclaim_event(
    p_ledger_id UUID,
    p_reclaim_run_id UUID,
    p_reclaim_tax_period VARCHAR(7),
    p_reclaimed_igst_paise BIGINT,
    p_reclaimed_cgst_paise BIGINT,
    p_reclaimed_sgst_paise BIGINT,
    p_reclaimed_cess_paise BIGINT,
    p_statutory_evidence_type VARCHAR(50),
    p_evidence_reference VARCHAR(150),
    p_evidence_document_date DATE,
    p_authorized_by UUID,
    p_reclaim_notes TEXT,
    p_event_type VARCHAR(30) DEFAULT 'RECLAIM',
    p_compensates_event_id UUID DEFAULT NULL,
    p_idempotency_key VARCHAR(120) DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_ledger RECORD;
    v_existing_event RECORD;
    v_sum_igst BIGINT;
    v_sum_cgst BIGINT;
    v_sum_sgst BIGINT;
    v_sum_cess BIGINT;
    v_new_igst BIGINT;
    v_new_cgst BIGINT;
    v_new_sgst BIGINT;
    v_new_cess BIGINT;
    v_event_id UUID;
    v_new_status VARCHAR(25);
    v_is_fully_reclaimed BOOLEAN;
BEGIN
    -- 1. Validate requested amounts are non-negative and total > 0
    IF p_reclaimed_igst_paise < 0 OR p_reclaimed_cgst_paise < 0 OR 
       p_reclaimed_sgst_paise < 0 OR p_reclaimed_cess_paise < 0 THEN
        RAISE EXCEPTION 'NEGATIVE_RECLAIM_AMOUNT_NOT_PERMITTED';
    END IF;
    
    IF (p_reclaimed_igst_paise + p_reclaimed_cgst_paise + p_reclaimed_sgst_paise + p_reclaimed_cess_paise) <= 0 THEN
        RAISE EXCEPTION 'ZERO_RECLAIM_AMOUNT_NOT_PERMITTED';
    END IF;

    -- 2. Lock the reversal ledger row
    SELECT * INTO v_ledger 
    FROM public.gstr3b_reversal_ledger 
    WHERE id = p_ledger_id 
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'REVERSAL_LEDGER_ENTRY_NOT_FOUND: %', p_ledger_id;
    END IF;

    -- Strict Reclaimability Boundary Enforcement
    IF v_ledger.is_reclaimable IS NOT TRUE OR v_ledger.status = 'NON_RECLAIMABLE' THEN
        RAISE EXCEPTION 'REVERSAL_ENTRY_IS_NOT_RECLAIMABLE: %', p_ledger_id;
    END IF;

    -- Database-Level Idempotency Check: Same client + same idempotency key -> exactly one execution
    IF p_idempotency_key IS NOT NULL AND length(trim(p_idempotency_key)) > 0 THEN
        SELECT * INTO v_existing_event
        FROM public.gstr3b_reclaim_events
        WHERE client_gstin_id = v_ledger.client_gstin_id 
          AND idempotency_key = trim(p_idempotency_key)
        LIMIT 1;

        IF FOUND THEN
            RETURN jsonb_build_object(
                'event_id', v_existing_event.id,
                'ledger_id', v_existing_event.ledger_id,
                'status', v_ledger.status,
                'is_idempotent_replay', true,
                'reclaimed_igst_paise', v_existing_event.reclaimed_igst_paise,
                'reclaimed_cgst_paise', v_existing_event.reclaimed_cgst_paise,
                'reclaimed_sgst_paise', v_existing_event.reclaimed_sgst_paise,
                'reclaimed_cess_paise', v_existing_event.reclaimed_cess_paise,
                'remaining_igst_paise', (v_ledger.reversed_igst_paise - v_ledger.cached_reclaimed_igst_paise),
                'remaining_cgst_paise', (v_ledger.reversed_cgst_paise - v_ledger.cached_reclaimed_cgst_paise),
                'remaining_sgst_paise', (v_ledger.reversed_sgst_paise - v_ledger.cached_reclaimed_sgst_paise),
                'remaining_cess_paise', (v_ledger.reversed_cess_paise - v_ledger.cached_reclaimed_cess_paise)
            );
        END IF;
    END IF;

    -- 3. Calculate authoritative cumulative reclaimed sums directly from immutable reclaim events
    SELECT 
        COALESCE(SUM(CASE WHEN event_type = 'RECLAIM' THEN reclaimed_igst_paise ELSE -reclaimed_igst_paise END), 0),
        COALESCE(SUM(CASE WHEN event_type = 'RECLAIM' THEN reclaimed_cgst_paise ELSE -reclaimed_cgst_paise END), 0),
        COALESCE(SUM(CASE WHEN event_type = 'RECLAIM' THEN reclaimed_sgst_paise ELSE -reclaimed_sgst_paise END), 0),
        COALESCE(SUM(CASE WHEN event_type = 'RECLAIM' THEN reclaimed_cess_paise ELSE -reclaimed_cess_paise END), 0)
    INTO v_sum_igst, v_sum_cgst, v_sum_sgst, v_sum_cess
    FROM public.gstr3b_reclaim_events
    WHERE ledger_id = p_ledger_id;

    -- 4. Enforce strict tax-head isolation (independent checks)
    IF (v_sum_igst + p_reclaimed_igst_paise) > v_ledger.reversed_igst_paise THEN
        RAISE EXCEPTION 'EXCESS_RECLAIM_IGST: Requested % paise exceeds available % paise', 
            p_reclaimed_igst_paise, (v_ledger.reversed_igst_paise - v_sum_igst);
    END IF;

    IF (v_sum_cgst + p_reclaimed_cgst_paise) > v_ledger.reversed_cgst_paise THEN
        RAISE EXCEPTION 'EXCESS_RECLAIM_CGST: Requested % paise exceeds available % paise', 
            p_reclaimed_cgst_paise, (v_ledger.reversed_cgst_paise - v_sum_cgst);
    END IF;

    IF (v_sum_sgst + p_reclaimed_sgst_paise) > v_ledger.reversed_sgst_paise THEN
        RAISE EXCEPTION 'EXCESS_RECLAIM_SGST: Requested % paise exceeds available % paise', 
            p_reclaimed_sgst_paise, (v_ledger.reversed_sgst_paise - v_sum_sgst);
    END IF;

    IF (v_sum_cess + p_reclaimed_cess_paise) > v_ledger.reversed_cess_paise THEN
        RAISE EXCEPTION 'EXCESS_RECLAIM_CESS: Requested % paise exceeds available % paise', 
            p_reclaimed_cess_paise, (v_ledger.reversed_cess_paise - v_sum_cess);
    END IF;

    -- 5. Insert immutable reclaim event
    INSERT INTO public.gstr3b_reclaim_events (
        client_gstin_id,
        ledger_id,
        reclaim_run_id,
        reclaim_tax_period,
        event_type,
        compensates_event_id,
        reclaimed_igst_paise,
        reclaimed_cgst_paise,
        reclaimed_sgst_paise,
        reclaimed_cess_paise,
        statutory_evidence_type,
        evidence_reference,
        evidence_document_date,
        authorized_by,
        reclaim_notes,
        idempotency_key
    ) VALUES (
        v_ledger.client_gstin_id,
        p_ledger_id,
        p_reclaim_run_id,
        p_reclaim_tax_period,
        COALESCE(p_event_type, 'RECLAIM'),
        p_compensates_event_id,
        p_reclaimed_igst_paise,
        p_reclaimed_cgst_paise,
        p_reclaimed_sgst_paise,
        p_reclaimed_cess_paise,
        p_statutory_evidence_type,
        p_evidence_reference,
        p_evidence_document_date,
        p_authorized_by,
        p_reclaim_notes,
        NULLIF(trim(p_idempotency_key), '')
    ) RETURNING id INTO v_event_id;

    -- 6. Compute new cumulative totals and lifecycle status
    v_new_igst := v_sum_igst + p_reclaimed_igst_paise;
    v_new_cgst := v_sum_cgst + p_reclaimed_cgst_paise;
    v_new_sgst := v_sum_sgst + p_reclaimed_sgst_paise;
    v_new_cess := v_sum_cess + p_reclaimed_cess_paise;

    v_is_fully_reclaimed := (
        v_new_igst = v_ledger.reversed_igst_paise AND
        v_new_cgst = v_ledger.reversed_cgst_paise AND
        v_new_sgst = v_ledger.reversed_sgst_paise AND
        v_new_cess = v_ledger.reversed_cess_paise
    );

    IF v_is_fully_reclaimed THEN
        v_new_status := 'FULLY_RECLAIMED';
    ELSE
        v_new_status := 'PARTIALLY_RECLAIMED';
    END IF;

    -- 7. Update cached derived balances and status on reversal ledger
    UPDATE public.gstr3b_reversal_ledger SET
        cached_reclaimed_igst_paise = v_new_igst,
        cached_reclaimed_cgst_paise = v_new_cgst,
        cached_reclaimed_sgst_paise = v_new_sgst,
        cached_reclaimed_cess_paise = v_new_cess,
        status = v_new_status,
        updated_at = NOW()
    WHERE id = p_ledger_id;

    RETURN jsonb_build_object(
        'event_id', v_event_id,
        'ledger_id', p_ledger_id,
        'status', v_new_status,
        'is_idempotent_replay', false,
        'reclaimed_igst_paise', p_reclaimed_igst_paise,
        'reclaimed_cgst_paise', p_reclaimed_cgst_paise,
        'reclaimed_sgst_paise', p_reclaimed_sgst_paise,
        'reclaimed_cess_paise', p_reclaimed_cess_paise,
        'remaining_igst_paise', (v_ledger.reversed_igst_paise - v_new_igst),
        'remaining_cgst_paise', (v_ledger.reversed_cgst_paise - v_new_cgst),
        'remaining_sgst_paise', (v_ledger.reversed_sgst_paise - v_new_sgst),
        'remaining_cess_paise', (v_ledger.reversed_cess_paise - v_new_cess)
    );
END;
$$;

COMMENT ON FUNCTION public.fn_execute_reclaim_event IS 'Atomic execution of GSTR-3B Table 4 reclaims with row locking, limits, and status updates';
