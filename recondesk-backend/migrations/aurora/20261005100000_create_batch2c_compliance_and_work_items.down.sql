-- ============================================================================
-- Migration: 20261005100000_create_batch2c_compliance_and_work_items.down.sql
-- Description: Rollback Phase 9D-11 (Batch 2C) - Drop vendor compliance,
--              work items, audit, and vendor followup tables in reverse order.
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

DROP TABLE IF EXISTS public.vendor_followup_logs CASCADE;
DROP TABLE IF EXISTS public.itc_work_item_events CASCADE;
DROP TABLE IF EXISTS public.itc_work_items CASCADE;
DROP TABLE IF EXISTS public.supplier_followup_audit CASCADE;
DROP TABLE IF EXISTS public.supplier_compliance_by_client CASCADE;
DROP TABLE IF EXISTS public.supplier_compliance_summary CASCADE;
