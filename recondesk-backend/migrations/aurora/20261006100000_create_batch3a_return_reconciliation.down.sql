-- ============================================================================
-- Migration: 20261006100000_create_batch3a_return_reconciliation.down.sql
-- Description: Rollback Phase 9F-1 (Batch 3A) — Drop all 6 Batch 3A tables
--              in reverse dependency order (children before parents).
-- ============================================================================

DROP TABLE IF EXISTS public.gstr9_audit_overrides CASCADE;
DROP TABLE IF EXISTS public.gstr2a_delta_results CASCADE;
DROP TABLE IF EXISTS public.gstr1a_period_actions CASCADE;
DROP TABLE IF EXISTS public.gstr1_reconciliation_run CASCADE;
DROP TABLE IF EXISTS public.multi_period_recon_batch_items CASCADE;
DROP TABLE IF EXISTS public.multi_period_recon_batches CASCADE;
