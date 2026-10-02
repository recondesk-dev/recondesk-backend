-- ============================================================================
-- Migration: 20261003150000_create_batch2a_compliance_tables.down.sql
-- Description: Rollback Batch 2A (Compliance & Resolution Tracking) tables.
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

DROP TRIGGER IF EXISTS trg_invoice_tracking_updated_at ON public.invoice_tracking;
DROP FUNCTION IF EXISTS public.set_invoice_tracking_updated_at();

DROP TABLE IF EXISTS public.rule37_alert_dedup CASCADE;
DROP TABLE IF EXISTS public.rule37_resolutions CASCADE;
DROP TABLE IF EXISTS public.rule37_actions CASCADE;
DROP TABLE IF EXISTS public.invoice_tracking CASCADE;
DROP TABLE IF EXISTS public.reconciliation_exception_dispositions CASCADE;
DROP TABLE IF EXISTS public.mismatch_notes CASCADE;
