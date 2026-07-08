-- GSTN taxpayer session tokens for GSTR-2B auto-fetch (Sandbox GSP API).
-- Apply via Supabase SQL editor or: supabase db push

ALTER TABLE public.client_gstins
    ADD COLUMN IF NOT EXISTS gstn_access_token text;

ALTER TABLE public.client_gstins
    ADD COLUMN IF NOT EXISTS gstn_token_expiry timestamptz;
