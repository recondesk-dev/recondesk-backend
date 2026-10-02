-- ============================================================================
-- Migration: 20261004100000_create_batch2b_gstr3b_tables.down.sql
-- Description: Rollback Batch 2B (GSTR-3B Table 4 / Reversal / Reclaim) tables.
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

DROP FUNCTION IF EXISTS public.fn_execute_reclaim_event(
    UUID, UUID, VARCHAR, BIGINT, BIGINT, BIGINT, BIGINT,
    VARCHAR, VARCHAR, DATE, UUID, TEXT, VARCHAR, UUID, VARCHAR
) CASCADE;

DROP TABLE IF EXISTS public.gstr3b_reclaim_events CASCADE;
DROP TABLE IF EXISTS public.gstr3b_reconciliation CASCADE;
DROP TABLE IF EXISTS public.gstr3b_table4_adjustments CASCADE;
DROP TABLE IF EXISTS public.gstr3b_table4_summaries CASCADE;
DROP TABLE IF EXISTS public.gstr3b_reversal_ledger CASCADE;
