-- Migration: 20261010100000_create_batch4a_payments_and_credits.down.sql
-- Rollback Batch 4A: Subscriptions, Payments & Credit Accounting

DROP TABLE IF EXISTS public.idempotency_keys CASCADE;
DROP TABLE IF EXISTS public.run_credits CASCADE;
DROP TABLE IF EXISTS public.payments CASCADE;
