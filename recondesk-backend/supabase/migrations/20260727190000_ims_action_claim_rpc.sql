-- Atomic claim for IMS writeback (INSERT ON CONFLICT DO NOTHING + failed reclaim).
-- PostgREST .upsert() is DO UPDATE — not safe as a claim. Use RPC instead.

ALTER TABLE public.ims_action_submissions
    DROP CONSTRAINT IF EXISTS ims_action_submissions_status_check;

ALTER TABLE public.ims_action_submissions
    ADD CONSTRAINT ims_action_submissions_status_check
    CHECK (status IN ('claiming', 'pending', 'confirmed', 'failed', 'unclear'));

COMMENT ON COLUMN public.ims_action_submissions.status IS
    'claiming = row reserved before Sandbox save; pending = save accepted / polling; confirmed|failed|unclear = terminal.';

CREATE OR REPLACE FUNCTION public.claim_ims_action_submission(
    p_invoice_id text,
    p_gstin text,
    p_period character varying,
    p_chosen_action text,
    p_recommended_action text DEFAULT NULL,
    p_submit_mode text DEFAULT 'confirm_recommendation',
    p_run_id uuid DEFAULT NULL
)
RETURNS SETOF public.ims_action_submissions
LANGUAGE plpgsql
AS $$
DECLARE
    claimed public.ims_action_submissions%ROWTYPE;
    g text := upper(btrim(p_gstin));
    p character varying := left(btrim(p_period), 7);
BEGIN
    -- 1) First writer wins: atomic insert, conflict does nothing.
    INSERT INTO public.ims_action_submissions (
        invoice_id,
        gstin,
        period,
        chosen_action,
        recommended_action,
        submit_mode,
        status,
        run_id
    ) VALUES (
        p_invoice_id,
        g,
        p,
        p_chosen_action,
        p_recommended_action,
        COALESCE(NULLIF(btrim(p_submit_mode), ''), 'confirm_recommendation'),
        'claiming',
        p_run_id
    )
    ON CONFLICT (invoice_id, period, gstin) DO NOTHING
    RETURNING * INTO claimed;

    IF FOUND THEN
        RETURN NEXT claimed;
        RETURN;
    END IF;

    -- 2) Only failed rows may be reclaimed for retry (still atomic).
    UPDATE public.ims_action_submissions AS s
    SET
        status = 'claiming',
        chosen_action = p_chosen_action,
        recommended_action = p_recommended_action,
        submit_mode = COALESCE(NULLIF(btrim(p_submit_mode), ''), 'confirm_recommendation'),
        run_id = COALESCE(p_run_id, s.run_id),
        reference_id = NULL,
        transaction_id = NULL,
        status_cd = NULL,
        error_code = NULL,
        error_message = NULL,
        raw_poll = NULL,
        updated_at = now()
    WHERE s.invoice_id = p_invoice_id
      AND s.period = p
      AND s.gstin = g
      AND s.status = 'failed'
    RETURNING * INTO claimed;

    IF FOUND THEN
        RETURN NEXT claimed;
    END IF;
    RETURN;
END;
$$;

COMMENT ON FUNCTION public.claim_ims_action_submission IS
    'Atomically claim an IMS invoice for writeback. Returns the row if this caller won the claim; empty if another non-failed submission already owns the key.';

GRANT EXECUTE ON FUNCTION public.claim_ims_action_submission(
    text, text, character varying, text, text, text, uuid
) TO service_role, authenticated;
