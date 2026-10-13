-- ============================================================================
-- Migration: 20261012220000_fix_filing_runs_columns_and_reconciliation_syntax.down.sql
-- Description: Phase 5.4 - Non-destructive rollback for corrective migration.
--              Added columns on filing_runs remain intact to prevent data loss.
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

-- Non-destructive rollback: Do not drop columns on filing_runs to preserve operational data.
-- Drop indexes created if reverting
DROP INDEX IF EXISTS public.idx_filing_runs_firm_period;
