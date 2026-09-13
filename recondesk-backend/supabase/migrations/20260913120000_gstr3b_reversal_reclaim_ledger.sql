-- Migration: 20260913120000_gstr3b_reversal_reclaim_ledger.sql
-- Description: Phase 3A.1.1 General Table 4(B)(2) Reversal Ledger, Immutable Reclaim Events, and Snapshot Versioning

-- 1. Table 4 Snapshot Versioning Schema Updates
ALTER TABLE public.gstr3b_table4_summaries 
    DROP CONSTRAINT IF EXISTS uq_run_table4_summary;

-- Change foreign key on run_id from CASCADE to RESTRICT to protect runs with finalized history
ALTER TABLE public.gstr3b_table4_summaries 
    DROP CONSTRAINT IF EXISTS gstr3b_table4_summaries_run_id_fkey;

ALTER TABLE public.gstr3b_table4_summaries 
    ADD CONSTRAINT gstr3b_table4_summaries_run_id_fkey 
    FOREIGN KEY (run_id) REFERENCES public.reconciliation_run(id) ON DELETE RESTRICT;

ALTER TABLE public.gstr3b_table4_summaries 
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS superseded_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS source_state_digest VARCHAR(64) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS snapshot_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS contributing_outcome_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS contributing_disposition_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS contributing_adjustment_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS contributing_reclaim_ids JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE public.gstr3b_table4_summaries 
    DROP CONSTRAINT IF EXISTS uq_table4_summary_run_version;

ALTER TABLE public.gstr3b_table4_summaries 
    ADD CONSTRAINT uq_table4_summary_run_version UNIQUE (run_id, version);

CREATE UNIQUE INDEX IF NOT EXISTS uq_table4_summary_run_current 
ON public.gstr3b_table4_summaries (run_id) 
WHERE is_current = TRUE;


-- 2. General GSTR-3B Table 4(B)(2) Reversal Ledger Table
CREATE TABLE IF NOT EXISTS public.gstr3b_reversal_ledger (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id                 UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    
    -- Provenance & Source Discrimination
    source_type                     VARCHAR(30) NOT NULL, 
    -- 'RECON_OUTCOME' | 'EXCEPTION_DISPOSITION' | 'STATUTORY_ADJUSTMENT' | 'OPENING_BALANCE'
    source_record_id                TEXT NOT NULL,
    source_run_id                   UUID REFERENCES public.reconciliation_run(id) ON DELETE RESTRICT,
    reversal_tax_period             VARCHAR(7) NOT NULL, -- 'YYYY-MM'
    
    -- Source State Sealing (Immutable provenance payload & hash)
    source_state_hash               VARCHAR(64) NOT NULL DEFAULT '',
    source_payload                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    
    -- Document Identity (Relaxed for adjustments & opening balance)
    document_type                   VARCHAR(20) NOT NULL DEFAULT 'INVOICE', -- 'INVOICE' | 'DEBIT_NOTE' | 'CREDIT_NOTE' | 'ADJUSTMENT' | 'OPENING_BALANCE'
    document_number                 VARCHAR(100),
    document_date                   DATE,
    supplier_gstin                  VARCHAR(15),
    reference_doc                   VARCHAR(150),
    
    -- Statutory Reason & Reclaim Eligibility
    reversal_table4_cell            VARCHAR(10) NOT NULL DEFAULT '4B2',
    is_reclaimable                  BOOLEAN NOT NULL DEFAULT TRUE,
    statutory_reason                VARCHAR(60) NOT NULL,
    -- 'RULE_37_NON_PAYMENT' | 'RULE_37A_SUPPLIER_NON_FILING' | 'SECTION_16_2_B_NOT_RECEIVED' | 
    -- 'SECTION_16_2_C_SUPPLIER_TAX_CONDITION' | 'OTHER_TEMPORARY' | 'OPENING_BALANCE'
    
    -- Explicit Rule 37A Lifecycle & Provenance Fields
    itc_financial_year              VARCHAR(7),   -- 'YYYY-YY' e.g. '2025-26'
    supplier_outward_statement_period VARCHAR(7), -- 'YYYY-MM' GSTR-1/IFF outward period
    supplier_gstr1_filing_date      DATE,         -- Supplier GSTR-1 filing date
    supplier_gstr3b_tax_period      VARCHAR(7),   -- Supplier GSTR-3B tax period
    supplier_gstr3b_filing_status   VARCHAR(20) DEFAULT 'UNKNOWN', -- 'UNFILED' | 'FILED' | 'UNKNOWN'
    filed_by_september_30           BOOLEAN DEFAULT FALSE,
    september_test_date             DATE,         -- 30th September following FY end
    november_reversal_deadline      DATE,         -- 30th November following FY end
    actual_reversal_date            DATE,         -- Date of reversal in GSTR-3B
    subsequent_supplier_filing_date DATE,         -- Date supplier eventually filed GSTR-3B
    subsequent_filing_arn           VARCHAR(50),  -- Filing ARN
    condition_fulfilled_date        DATE,         -- Date statutory condition satisfied
    reclaim_eligibility_date        DATE,         -- Date reclaim became legally valid
    
    -- Initial Reversed Amounts in Integer Paise
    reversed_igst_paise             BIGINT NOT NULL DEFAULT 0,
    reversed_cgst_paise             BIGINT NOT NULL DEFAULT 0,
    reversed_sgst_paise             BIGINT NOT NULL DEFAULT 0,
    reversed_cess_paise             BIGINT NOT NULL DEFAULT 0,
    
    -- Cached Cumulative Reclaims in Integer Paise (Derived; authoritative source is gstr3b_reclaim_events)
    cached_reclaimed_igst_paise     BIGINT NOT NULL DEFAULT 0,
    cached_reclaimed_cgst_paise     BIGINT NOT NULL DEFAULT 0,
    cached_reclaimed_sgst_paise     BIGINT NOT NULL DEFAULT 0,
    cached_reclaimed_cess_paise     BIGINT NOT NULL DEFAULT 0,
    
    -- Lifecycle State
    status                          VARCHAR(25) NOT NULL DEFAULT 'OPEN',
    -- 'OPEN' | 'CONDITION_FULFILLED' | 'RECLAIM_AUTHORIZED' | 'PARTIALLY_RECLAIMED' | 'FULLY_RECLAIMED' | 'NON_RECLAIMABLE'
    
    -- Verification Metadata
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    created_by                      UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    
    -- INVARIANTS ENFORCED AT DB LEVEL
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
            'RULE_37_NON_PAYMENT',
            'RULE_37A_SUPPLIER_NON_FILING',
            'SECTION_16_2_B_NOT_RECEIVED',
            'SECTION_16_2_C_SUPPLIER_TAX_CONDITION',
            'OTHER_TEMPORARY',
            'OPENING_BALANCE'
        )
    ),
    CONSTRAINT chk_reversal_status CHECK (
        status IN ('OPEN', 'CONDITION_FULFILLED', 'RECLAIM_AUTHORIZED', 'PARTIALLY_RECLAIMED', 'FULLY_RECLAIMED', 'NON_RECLAIMABLE')
    ),
    -- Reclaimability Boundary Invariant: Non-reclaimable rows can NEVER transition to any reclaim state
    CONSTRAINT chk_reclaimable_status CHECK (
        (is_reclaimable = TRUE AND status IN ('OPEN', 'CONDITION_FULFILLED', 'RECLAIM_AUTHORIZED', 'PARTIALLY_RECLAIMED', 'FULLY_RECLAIMED')) OR
        (is_reclaimable = FALSE AND status = 'NON_RECLAIMABLE' AND 
         cached_reclaimed_igst_paise = 0 AND cached_reclaimed_cgst_paise = 0 AND 
         cached_reclaimed_sgst_paise = 0 AND cached_reclaimed_cess_paise = 0)
    )
);

CREATE INDEX IF NOT EXISTS idx_reversal_ledger_client_status 
ON public.gstr3b_reversal_ledger (client_gstin_id, status);

CREATE INDEX IF NOT EXISTS idx_reversal_ledger_source 
ON public.gstr3b_reversal_ledger (source_type, source_record_id);

CREATE INDEX IF NOT EXISTS idx_reversal_ledger_run_id 
ON public.gstr3b_reversal_ledger (source_run_id);

ALTER TABLE public.gstr3b_reversal_ledger DISABLE ROW LEVEL SECURITY;
GRANT ALL ON public.gstr3b_reversal_ledger TO postgres, service_role, authenticated;


-- 3. GSTR-3B Reclaim Events Table (Immutable Historical Source of Truth)
CREATE TABLE IF NOT EXISTS public.gstr3b_reclaim_events (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id             UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE RESTRICT,
    ledger_id                   UUID NOT NULL REFERENCES public.gstr3b_reversal_ledger(id) ON DELETE RESTRICT,
    reclaim_run_id              UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE RESTRICT,
    reclaim_tax_period          VARCHAR(7) NOT NULL, -- 'YYYY-MM'
    
    event_type                  VARCHAR(30) NOT NULL DEFAULT 'RECLAIM', -- 'RECLAIM' | 'COMPENSATING_REVERSAL'
    compensates_event_id        UUID REFERENCES public.gstr3b_reclaim_events(id) ON DELETE RESTRICT,
    
    -- Reclaimed Amounts in Integer Paise
    reclaimed_igst_paise        BIGINT NOT NULL DEFAULT 0,
    reclaimed_cgst_paise        BIGINT NOT NULL DEFAULT 0,
    reclaimed_sgst_paise        BIGINT NOT NULL DEFAULT 0,
    reclaimed_cess_paise        BIGINT NOT NULL DEFAULT 0,
    
    -- Mandatory Audit & Evidence Trail
    statutory_evidence_type     VARCHAR(50) NOT NULL,
    -- 'PAYMENT_TO_SUPPLIER' | 'SUPPLIER_GSTR3B_FILED' | 'GOODS_RECEIVED_GRN' | 'TAX_DISCHARGE_CONFIRMED' | 'OPENING_BALANCE_VERIFIED' | 'COMPENSATING_ADJUSTMENT' | 'OTHER_STATUTORY_PROOF'
    evidence_reference          VARCHAR(150) NOT NULL,
    evidence_document_date      DATE,
    authorized_by               UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    reclaim_notes               TEXT NOT NULL DEFAULT '',
    idempotency_key             VARCHAR(120),
    
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    
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

CREATE INDEX IF NOT EXISTS idx_reclaim_events_ledger_id 
ON public.gstr3b_reclaim_events (ledger_id);

CREATE INDEX IF NOT EXISTS idx_reclaim_events_run_id 
ON public.gstr3b_reclaim_events (reclaim_run_id);

CREATE INDEX IF NOT EXISTS idx_reclaim_events_client_id 
ON public.gstr3b_reclaim_events (client_gstin_id);

-- Database-Level Idempotency Constraint: same client + same reclaim idempotency key -> exactly one execution
CREATE UNIQUE INDEX IF NOT EXISTS uq_reclaim_events_client_idempotency 
ON public.gstr3b_reclaim_events (client_gstin_id, idempotency_key) 
WHERE idempotency_key IS NOT NULL;

ALTER TABLE public.gstr3b_reclaim_events DISABLE ROW LEVEL SECURITY;
GRANT ALL ON public.gstr3b_reclaim_events TO postgres, service_role, authenticated;


-- 4. Atomic Stored Procedure: fn_execute_reclaim_event
-- Enforces row lock, verifies is_reclaimable = TRUE, independent tax-head limit verification,
-- event insertion, cached balance update, lifecycle status transition, and database idempotency.
CREATE OR REPLACE FUNCTION public.fn_execute_reclaim_event(
    p_ledger_id                 UUID,
    p_reclaim_run_id            UUID,
    p_reclaim_tax_period        VARCHAR(7),
    p_reclaimed_igst_paise      BIGINT,
    p_reclaimed_cgst_paise      BIGINT,
    p_reclaimed_sgst_paise      BIGINT,
    p_reclaimed_cess_paise      BIGINT,
    p_statutory_evidence_type   VARCHAR(50),
    p_evidence_reference        VARCHAR(150),
    p_evidence_document_date    DATE,
    p_authorized_by             UUID,
    p_reclaim_notes             TEXT,
    p_event_type                VARCHAR(30) DEFAULT 'RECLAIM',
    p_compensates_event_id      UUID DEFAULT NULL,
    p_idempotency_key           VARCHAR(120) DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_ledger                    RECORD;
    v_existing_event            RECORD;
    v_sum_igst                  BIGINT;
    v_sum_cgst                  BIGINT;
    v_sum_sgst                  BIGINT;
    v_sum_cess                  BIGINT;
    v_new_igst                  BIGINT;
    v_new_cgst                  BIGINT;
    v_new_sgst                  BIGINT;
    v_new_cess                  BIGINT;
    v_event_id                  UUID;
    v_new_status                VARCHAR(25);
    v_is_fully_reclaimed        BOOLEAN;
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
        updated_at = timezone('utc'::text, now())
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

