-- ============================================================================
-- Migration: 20261001120000_create_tenancy_tables.down.sql
-- Description: Phase 3B - Revert foundational Aurora Tenancy Layer
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

DROP TABLE IF EXISTS public.client_gstins CASCADE;
DROP TABLE IF EXISTS public.team_members CASCADE;

-- Note: user_profiles is preserved if cognito_user_mappings or other tables depend on it;
-- if strictly rolling back tenancy tables without foreign key dependencies:
-- DROP TABLE IF EXISTS public.user_profiles CASCADE;
