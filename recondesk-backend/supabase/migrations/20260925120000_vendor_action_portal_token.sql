-- Migration: 20260925120000_vendor_action_portal_token.sql
-- Description: Tokenized Vendor Action Portal (/v/[token]) support for vendor follow-up logs.

ALTER TABLE public.vendor_followup_logs
    ADD COLUMN IF NOT EXISTS token TEXT UNIQUE,
    ADD COLUMN IF NOT EXISTS viewed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS arn_number TEXT,
    ADD COLUMN IF NOT EXISTS promised_period TEXT,
    ADD COLUMN IF NOT EXISTS dispute_reason TEXT,
    ADD COLUMN IF NOT EXISTS attachment_key TEXT,
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS invoices_snapshot JSONB,
    ADD COLUMN IF NOT EXISTS response_action TEXT,
    ADD COLUMN IF NOT EXISTS responded_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_vendor_followup_token
    ON public.vendor_followup_logs(token);
