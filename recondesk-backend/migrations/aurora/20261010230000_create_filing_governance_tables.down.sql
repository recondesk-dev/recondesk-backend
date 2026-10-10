-- ============================================================================
-- Migration: 20261010230000_create_filing_governance_tables.down.sql
-- Description: Rollback filing governance tables and indices.
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

DROP TABLE IF EXISTS public.filing_overrides CASCADE;
DROP TABLE IF EXISTS public.filing_governance_policies CASCADE;
