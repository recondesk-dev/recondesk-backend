-- Tally Bridge API keys + optional Rule 37 action provenance columns.

CREATE TABLE IF NOT EXISTS public.tally_bridge_keys (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    api_key         text NOT NULL UNIQUE,
    account_id      uuid NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    company_name    text NOT NULL DEFAULT '',
    last_synced_at  timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    revoked_at      timestamptz
);

CREATE INDEX IF NOT EXISTS idx_tally_bridge_keys_account_id
    ON public.tally_bridge_keys (account_id);

CREATE INDEX IF NOT EXISTS idx_tally_bridge_keys_api_key
    ON public.tally_bridge_keys (api_key);

COMMENT ON TABLE public.tally_bridge_keys IS
    'API keys for the local Tally Bridge agent; account_id is the firm owner (user_profiles.id).';

ALTER TABLE public.rule37_actions
    ADD COLUMN IF NOT EXISTS source text,
    ADD COLUMN IF NOT EXISTS settled_date date;

COMMENT ON COLUMN public.rule37_actions.source IS
    'Origin of the settlement action (e.g. manual UI, tally_bridge).';
COMMENT ON COLUMN public.rule37_actions.settled_date IS
    'Payment / bill date used when settling (from Tally when source=tally_bridge).';

GRANT USAGE ON SCHEMA public TO postgres, anon, authenticated, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.tally_bridge_keys
    TO postgres, service_role;

GRANT SELECT, INSERT, UPDATE ON TABLE public.tally_bridge_keys
    TO authenticated;

ALTER TABLE public.tally_bridge_keys DISABLE ROW LEVEL SECURITY;
