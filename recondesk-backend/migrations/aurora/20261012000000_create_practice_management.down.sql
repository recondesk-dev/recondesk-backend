-- ============================================================================
-- Migration: 20261012000000_create_practice_management.down.sql
-- Description: Rollback Phase 3.4 - CA Firm Practice Management
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

DROP TABLE IF EXISTS public.practice_task_audit_trail;
DROP TABLE IF EXISTS public.practice_tasks;
DROP TABLE IF EXISTS public.compliance_deadlines;

-- Remove organization reference from client_gstins before dropping organization table
ALTER TABLE public.client_gstins DROP COLUMN IF EXISTS organization_id;

DROP TABLE IF EXISTS public.client_organizations;
