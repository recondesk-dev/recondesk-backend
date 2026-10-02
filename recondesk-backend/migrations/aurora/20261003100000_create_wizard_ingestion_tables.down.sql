-- ============================================================================
-- Migration: 20261003100000_create_wizard_ingestion_tables.down.sql
-- Description: Rollback Phase 9B (Batch 1) - Ingestion & Wizard Pipeline
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

DROP TRIGGER IF EXISTS trg_reconciliation_import_runs_updated_at ON public.reconciliation_import_runs;
DROP TRIGGER IF EXISTS trg_client_import_mappings_updated_at ON public.client_import_mappings;

DROP FUNCTION IF EXISTS public.set_reconciliation_import_runs_updated_at();
DROP FUNCTION IF EXISTS public.set_client_import_mappings_updated_at();

DROP TABLE IF EXISTS public.reconciliation_import_run_audit_log CASCADE;
DROP TABLE IF EXISTS public.reconciliation_import_runs CASCADE;
DROP TABLE IF EXISTS public.client_import_mappings CASCADE;
