-- Taxpayer OTP sessions + return filing runs (Sandbox GSP).
-- filing_sessions is return-type-agnostic (GSTR-1, IMS actions, GSTR-3B, …).

CREATE TABLE IF NOT EXISTS public.filing_sessions (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             uuid NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id     uuid REFERENCES public.client_gstins (id) ON DELETE SET NULL,
    gstin               text NOT NULL,
    username            text NOT NULL DEFAULT '',
    session_token       text NOT NULL,
    token_expires_at    timestamptz NOT NULL,
    session_expires_at  timestamptz,
    status              text NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'expired', 'logged_out')),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    logged_out_at       timestamptz
);

CREATE INDEX IF NOT EXISTS idx_filing_sessions_firm_gstin
    ON public.filing_sessions (firm_id, gstin);

CREATE INDEX IF NOT EXISTS idx_filing_sessions_firm_active
    ON public.filing_sessions (firm_id, status, token_expires_at DESC)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_filing_sessions_client_gstin
    ON public.filing_sessions (client_gstin_id)
    WHERE client_gstin_id IS NOT NULL;

COMMENT ON TABLE public.filing_sessions IS
    'Sandbox taxpayer OTP session (~6hr access token). Shared by GSTR filing and future IMS accept/reject.';

CREATE TABLE IF NOT EXISTS public.filing_runs (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             uuid NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id     uuid REFERENCES public.client_gstins (id) ON DELETE SET NULL,
    filing_session_id   uuid REFERENCES public.filing_sessions (id) ON DELETE SET NULL,
    gstin               text NOT NULL,
    return_type         text NOT NULL
                        CHECK (return_type IN (
                            'gstr-1', 'gstr-1a', 'gstr-3b', 'gstr-9', 'other'
                        )),
    period              varchar(7) NOT NULL
                        CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    status              text NOT NULL DEFAULT 'draft'
                        CHECK (status IN (
                            'draft',
                            'save_pending',
                            'saved',
                            'save_failed',
                            'proceeded',
                            'evc_pending',
                            'filed',
                            'failed'
                        )),
    reference_id        text,
    ack_number          text,
    save_payload        jsonb,
    raw_response        jsonb,
    error_code          text,
    error_message       text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_filing_runs_firm_period
    ON public.filing_runs (firm_id, return_type, period, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_filing_runs_gstin_period
    ON public.filing_runs (gstin, return_type, period, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_filing_runs_session
    ON public.filing_runs (filing_session_id)
    WHERE filing_session_id IS NOT NULL;

COMMENT ON TABLE public.filing_runs IS
    'One Save→File attempt for a return type + period; raw_response stores portal envelopes.';

ALTER TABLE public.filing_sessions DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.filing_runs DISABLE ROW LEVEL SECURITY;

GRANT ALL ON public.filing_sessions TO service_role;
GRANT ALL ON public.filing_runs TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.filing_sessions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.filing_runs TO authenticated;
