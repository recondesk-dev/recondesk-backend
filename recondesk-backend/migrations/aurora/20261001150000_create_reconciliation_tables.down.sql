-- ============================================================================
-- Migration: 20261001150000_create_reconciliation_tables.down.sql
-- Description: Phase 4 Rollback - Drop reconciliation tables and cascade function.
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

DROP FUNCTION IF EXISTS public.delete_reconciliation_run_cascade(uuid);
DROP TABLE IF EXISTS public.reconciliation_results CASCADE;
DROP TABLE IF EXISTS public.pr_records CASCADE;
DROP TABLE IF EXISTS public.gstr_records CASCADE;
DROP TABLE IF EXISTS public.reconciliation_run CASCADE;
