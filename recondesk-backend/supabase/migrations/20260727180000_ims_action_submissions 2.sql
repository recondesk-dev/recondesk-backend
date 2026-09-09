-- Per-invoice IMS writeback submissions (idempotency for Accept/Reject/Hold).
-- filing_runs is period-level for GSTR Save/File — not suitable for invoice-level IMS.

CREATE TABLE IF NOT EXISTS public.ims_action_submissions (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id          text NOT NULL,
    gstin               text NOT NULL,
    period              varchar(7) NOT NULL
                        CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    chosen_action       text NOT NULL
                        CHECK (chosen_action IN ('accept', 'reject', 'hold', 'pending')),
    recommended_action  text,
    submit_mode         text NOT NULL DEFAULT 'confirm_recommendation'
                        CHECK (submit_mode IN ('confirm_recommendation', 'override')),
    -- pending = save accepted, poll not finished; confirmed / failed / unclear = terminal
    status              text NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'confirmed', 'failed', 'unclear')),
    reference_id        text,
    transaction_id      text,
    status_cd           text,
    error_code          text,
    error_message       text,
    raw_poll            jsonb,
    run_id              uuid,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (invoice_id, period, gstin)
);

CREATE INDEX IF NOT EXISTS idx_ims_action_submissions_gstin_period
    ON public.ims_action_submissions (gstin, period, status);

CREATE INDEX IF NOT EXISTS idx_ims_action_submissions_reference
    ON public.ims_action_submissions (reference_id)
    WHERE reference_id IS NOT NULL;

COMMENT ON TABLE public.ims_action_submissions IS
    'Idempotent IMS Accept/Reject/Hold writebacks keyed by (invoice_id, period, gstin). Non-failed rows block re-submit.';

ALTER TABLE public.ims_action_submissions DISABLE ROW LEVEL SECURITY;

GRANT ALL ON public.ims_action_submissions TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.ims_action_submissions TO authenticated;
