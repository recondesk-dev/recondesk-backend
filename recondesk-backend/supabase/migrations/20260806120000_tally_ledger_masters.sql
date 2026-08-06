-- Tally Ledger Masters table for persisting synced ledger masters from local Tally instance.

CREATE TABLE IF NOT EXISTS public.tally_ledger_masters (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      uuid NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    company_name    text NOT NULL DEFAULT '',
    name            text NOT NULL,
    parent_group    text NOT NULL DEFAULT '',
    gstin           text NOT NULL DEFAULT '',
    state           text NOT NULL DEFAULT '',
    opening_balance numeric,
    closing_balance numeric,
    synced_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tally_ledger_masters_unique UNIQUE (account_id, company_name, name)
);

CREATE INDEX IF NOT EXISTS idx_tally_ledger_masters_account_id
    ON public.tally_ledger_masters (account_id);

CREATE INDEX IF NOT EXISTS idx_tally_ledger_masters_gstin
    ON public.tally_ledger_masters (account_id, gstin);

COMMENT ON TABLE public.tally_ledger_masters IS
    'Party ledger masters synced from Tally via Tally Bridge agent.';

GRANT USAGE ON SCHEMA public TO postgres, anon, authenticated, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.tally_ledger_masters
    TO postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.tally_ledger_masters
    TO authenticated;

ALTER TABLE public.tally_ledger_masters DISABLE ROW LEVEL SECURITY;
