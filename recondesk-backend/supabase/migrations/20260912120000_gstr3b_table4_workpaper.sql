-- Migration: 20260912120000_gstr3b_table4_workpaper.sql
-- Description: GSTR-3B Table 4 Workpaper summaries, external adjustments, and exception dispositions.

-- 1. Authoritative Table 4 Snapshot Table
CREATE TABLE IF NOT EXISTS public.gstr3b_table4_summaries (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id                  UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE CASCADE,
    client_gstin_id         UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    tax_period              VARCHAR(7) NOT NULL, -- 'YYYY-MM'
    status                  VARCHAR(20) NOT NULL DEFAULT 'PROVISIONAL', -- 'PROVISIONAL' | 'FINALIZED'
    
    -- Table 4(A) ITC Available
    table_4a1               JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    table_4a2               JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    table_4a3               JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    table_4a4               JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    table_4a5               JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    table_4a_total          JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    
    -- Table 4(B) ITC Reversed
    table_4b1               JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    table_4b2               JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    table_4b_total          JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    
    -- Table 4(C) Net ITC Available
    table_4c                JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "total_tax": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    
    -- Table 4(D) Other Details
    table_4d1               JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    table_4d2               JSONB NOT NULL DEFAULT '{"igst": 0, "cgst": 0, "sgst": 0, "cess": 0, "count": 0, "igst_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}'::jsonb,
    
    audit_hash              VARCHAR(64) NOT NULL DEFAULT '',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    finalized_at            TIMESTAMPTZ,
    finalized_by            UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    
    CONSTRAINT uq_run_table4_summary UNIQUE (run_id)
);

CREATE INDEX IF NOT EXISTS idx_gstr3b_table4_run_id 
ON public.gstr3b_table4_summaries (run_id);

CREATE INDEX IF NOT EXISTS idx_gstr3b_table4_client_period 
ON public.gstr3b_table4_summaries (client_gstin_id, tax_period);

ALTER TABLE public.gstr3b_table4_summaries DISABLE ROW LEVEL SECURITY;
GRANT ALL ON public.gstr3b_table4_summaries TO postgres, service_role, authenticated;


-- 2. Dedicated External Adjustments Table
CREATE TABLE IF NOT EXISTS public.gstr3b_table4_adjustments (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id                  UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE CASCADE,
    client_gstin_id         UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    tax_period              VARCHAR(7) NOT NULL,
    row_id                  VARCHAR(10) NOT NULL, -- '4A1', '4A2', '4A3', '4A4', '4A5', '4B1', '4B2', '4D1', '4D2'
    
    igst_paise              BIGINT NOT NULL DEFAULT 0,
    cgst_paise              BIGINT NOT NULL DEFAULT 0,
    sgst_paise              BIGINT NOT NULL DEFAULT 0,
    cess_paise              BIGINT NOT NULL DEFAULT 0,
    
    adjustment_type         VARCHAR(20) NOT NULL, -- 'ADDITION' | 'REDUCTION'
    statutory_category      VARCHAR(50) NOT NULL,
    -- 'RULE_42_INPUTS' | 'RULE_43_CAPITAL_GOODS' | 'RULE_38_BANKING' | 
    -- 'IMPORT_SERVICES_RCM' | 'DOMESTIC_RCM' | 'RECLAIM_RULE37' | 
    -- 'RECLAIM_RULE37A' | 'SEC16_4_INELIGIBLE' | 'OTHER_MANUAL'
    
    reason                  TEXT NOT NULL,
    reference_doc           VARCHAR(100),
    turnover_ratio_data     JSONB,
    
    created_at              TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    created_by              UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_table4_adj_run_id 
ON public.gstr3b_table4_adjustments (run_id);

CREATE INDEX IF NOT EXISTS idx_table4_adj_client_period 
ON public.gstr3b_table4_adjustments (client_gstin_id, tax_period);

ALTER TABLE public.gstr3b_table4_adjustments DISABLE ROW LEVEL SECURITY;
GRANT ALL ON public.gstr3b_table4_adjustments TO postgres, service_role, authenticated;


-- 3. Exception Dispositions Table
CREATE TABLE IF NOT EXISTS public.reconciliation_exception_dispositions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id                  UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE CASCADE,
    record_id               TEXT NOT NULL, -- outcome row id (e.g. pm:..., gstr:..., pr:...)
    exception_type          VARCHAR(50) NOT NULL, -- 'SEC_17_5', 'RULE_37', 'TWO_B_ONLY', 'GOODS_RECEIPT', 'RULE_37A'
    disposition             VARCHAR(50) NOT NULL,
    eligibility_effect      VARCHAR(30) NOT NULL, -- 'ELIGIBLE', 'INELIGIBLE', 'HELD', 'REVERSED'
    table4_effect           VARCHAR(30) NOT NULL, -- '4A5', '4B1', '4B2', 'EXCLUDED'
    reason                  TEXT NOT NULL,
    reference_doc           VARCHAR(100),
    statutory_reference     VARCHAR(100),
    
    created_at              TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    created_by              UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    
    CONSTRAINT uq_exception_disposition UNIQUE (run_id, record_id, exception_type)
);

CREATE INDEX IF NOT EXISTS idx_exception_disp_run_id 
ON public.reconciliation_exception_dispositions (run_id);

ALTER TABLE public.reconciliation_exception_dispositions DISABLE ROW LEVEL SECURITY;
GRANT ALL ON public.reconciliation_exception_dispositions TO postgres, service_role, authenticated;


-- 4. Foreign Key on reconciliation_run to authoritative Table 4 summary
ALTER TABLE public.reconciliation_run 
ADD COLUMN IF NOT EXISTS table4_summary_id UUID REFERENCES public.gstr3b_table4_summaries(id) ON DELETE SET NULL;
