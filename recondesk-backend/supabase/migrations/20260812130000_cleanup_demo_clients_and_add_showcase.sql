-- Migration: Cleanup Demo Enterprises Pvt Ltd rows and add showcase_seen to user_profiles

-- 1. Add showcase_seen column to user_profiles if it does not exist
ALTER TABLE public.user_profiles 
ADD COLUMN IF NOT EXISTS showcase_seen BOOLEAN DEFAULT FALSE;

-- 2. Clean up any seeded Demo Enterprises Pvt Ltd rows and dependent tables
DO $$
DECLARE
    demo_client_id UUID;
BEGIN
    FOR demo_client_id IN 
        SELECT id FROM public.client_gstins WHERE is_demo = TRUE OR gstin = '27DEMOX1234Z1ZD'
    LOOP
        -- Delete dependent records
        DELETE FROM public.supplier_followup_audit WHERE client_gstin_id = demo_client_id;
        DELETE FROM public.rule37_warnings WHERE client_gstin_id = demo_client_id;
        DELETE FROM public.reconciliation_results WHERE reconciliation_run_id IN (
            SELECT id FROM public.reconciliation_run WHERE client_gstin_id = demo_client_id
        );
        DELETE FROM public.gstr_records WHERE client_gstin_id = demo_client_id;
        DELETE FROM public.pr_records WHERE client_gstin_id = demo_client_id;
        DELETE FROM public.reconciliation_run WHERE client_gstin_id = demo_client_id;
        DELETE FROM public.client_gstins WHERE id = demo_client_id;
    END LOOP;
END $$;
