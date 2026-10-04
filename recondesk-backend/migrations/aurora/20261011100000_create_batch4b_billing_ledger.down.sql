-- Migration: 20261011100000_create_batch4b_billing_ledger.down.sql
-- Rollback Batch 4B: E-Invoicing & B2B Billing Ledger

DROP FUNCTION IF EXISTS public.increment_invoice_number_seq(uuid);

DROP TABLE IF EXISTS public.billing_irp_submission_log CASCADE;
DROP TABLE IF EXISTS public.billing_cdn_line_items CASCADE;
DROP TABLE IF EXISTS public.billing_credit_debit_notes CASCADE;
DROP TABLE IF EXISTS public.billing_invoice_line_items CASCADE;
DROP TABLE IF EXISTS public.billing_invoices CASCADE;
DROP TABLE IF EXISTS public.billing_items CASCADE;
DROP TABLE IF EXISTS public.billing_customers CASCADE;
DROP TABLE IF EXISTS public.billing_company_profiles CASCADE;
