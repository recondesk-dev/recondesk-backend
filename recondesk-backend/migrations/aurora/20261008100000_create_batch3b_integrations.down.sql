-- Migration: 20261008100000_create_batch3b_integrations.down.sql
-- Description: Drop Canonical Batch 3B Integration Tables and IMS RPC
-- Target: AWS Aurora PostgreSQL

DROP FUNCTION IF EXISTS public.claim_ims_action_submission(text, text, character varying, text, text, text, uuid);
DROP FUNCTION IF EXISTS public.fn_claim_ims_action_submission(text, text, character varying, text, text, text, uuid);
DROP TABLE IF EXISTS public.ims_action_submissions CASCADE;
DROP TABLE IF EXISTS public.gst_fetch_log CASCADE;
DROP TABLE IF EXISTS public.einvoice_recon_results CASCADE;
DROP TABLE IF EXISTS public.client_einvoice_credentials CASCADE;
DROP TABLE IF EXISTS public.tally_ledger_masters CASCADE;
DROP TABLE IF EXISTS public.tally_bridge_keys CASCADE;
