-- Migration: 20261009100000_create_batch3c_filing_automation.down.sql
-- Description: Rollback Batch 3C Government Portal Filing Automation & Bulk Return Processing Tables
-- Target: AWS Aurora PostgreSQL

DROP TABLE IF EXISTS public.sr_records CASCADE;
DROP TABLE IF EXISTS public.sales_register_run CASCADE;
DROP TABLE IF EXISTS public.filing_batch_items CASCADE;
DROP TABLE IF EXISTS public.filing_batches CASCADE;
DROP TABLE IF EXISTS public.filing_runs CASCADE;
DROP TABLE IF EXISTS public.filing_sessions CASCADE;
