-- Reclaim abandoned ``claiming`` rows (crash/kill between claim and Sandbox).
-- Fresh installs already get this from 20260727190000; this replaces the
-- function for environments that applied the earlier failed-only reclaim.

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

    -- 2) Reclaim failed, or abandoned stale ``claiming`` (crash between
    --    claim and save+poll). Still atomic. Fresh claiming/pending/etc. win.
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
      AND (
          s.status = 'failed'
          OR (
              s.status = 'claiming'
              AND s.updated_at < now() - interval '5 minutes'
          )
      )
    RETURNING * INTO claimed;

    IF FOUND THEN
        RETURN NEXT claimed;
    END IF;
    RETURN;
END;
$$;

COMMENT ON FUNCTION public.claim_ims_action_submission IS
    'Atomically claim an IMS invoice for writeback. Returns the row if this caller won (insert, failed reclaim, or stale claiming >5m); empty if another non-failed non-stale submission owns the key.';
