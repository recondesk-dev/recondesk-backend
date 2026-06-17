-- Idempotent rule37_actions table + grants for Rule 37 mark-as-settled (FastAPI via service_role).

CREATE TABLE IF NOT EXISTS public.rule37_actions (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id                  uuid NOT NULL,
    record_hash             text NOT NULL,
    status                  text NOT NULL,
    user_id                 text NOT NULL DEFAULT '',
    created_at              timestamptz NOT NULL DEFAULT now(),
    amount_paid             numeric(15,2),
    tds_deducted            numeric(15,2) NOT NULL DEFAULT 0,
    tds_confirmed           boolean NOT NULL DEFAULT false,
    total_settled           numeric(15,2),
    remaining_unpaid_amount numeric(15,2),
    payment_coverage        text,
    UNIQUE (run_id, record_hash)
);

ALTER TABLE public.rule37_actions
    ADD COLUMN IF NOT EXISTS amount_paid numeric(15,2),
    ADD COLUMN IF NOT EXISTS tds_deducted numeric(15,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tds_confirmed boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS total_settled numeric(15,2),
    ADD COLUMN IF NOT EXISTS remaining_unpaid_amount numeric(15,2),
    ADD COLUMN IF NOT EXISTS payment_coverage text;

CREATE INDEX IF NOT EXISTS idx_rule37_actions_run_id
    ON public.rule37_actions (run_id);

GRANT USAGE ON SCHEMA public TO postgres, anon, authenticated, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.rule37_actions
    TO postgres, service_role;

GRANT SELECT, INSERT, UPDATE ON TABLE public.rule37_actions
    TO authenticated;

ALTER TABLE public.rule37_actions DISABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.rule37_actions IS
    'Rule 37 settlement actions (mark as settled / ITC reversed) per reconciliation run invoice.';
