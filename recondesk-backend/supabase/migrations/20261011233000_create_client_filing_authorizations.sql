-- ============================================================================
-- Migration: 20261011233000_create_client_filing_authorizations.sql
-- Description: Phase 3.3 - Client Review, Consent and Filing Authorization
-- Target: Supabase / PostgreSQL
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.client_filing_authorizations (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id                         UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id                 UUID NOT NULL REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    gstin                           VARCHAR(15) NOT NULL,
    period                          VARCHAR(7) NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    return_type                     VARCHAR(20) NOT NULL CHECK (return_type IN ('GSTR-1', 'GSTR-3B', 'GSTR-4', 'GSTR-9', 'GSTR-9C')),
    status                          VARCHAR(30) NOT NULL DEFAULT 'PENDING'
                                    CHECK (status IN (
                                        'PENDING',
                                        'VIEWED',
                                        'AUTHORIZED',
                                        'REJECTED',
                                        'REVOKED',
                                        'EXPIRED'
                                    )),
    token_hash                      VARCHAR(64) NOT NULL UNIQUE,
    figures_digest                  VARCHAR(64) NOT NULL,
    figures_summary                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    signatory_name                  VARCHAR(255),
    signatory_designation           VARCHAR(100),
    signatory_contact               VARCHAR(100),
    consent_text_version            VARCHAR(20) NOT NULL DEFAULT 'v1.0',
    consent_declaration             TEXT,
    identity_verification_method    VARCHAR(50) NOT NULL DEFAULT 'self_declaration',
    client_ip                       VARCHAR(45),
    user_agent                      TEXT,
    authorized_at                   TIMESTAMPTZ,
    rejected_at                     TIMESTAMPTZ,
    rejection_reason                TEXT,
    revoked_at                      TIMESTAMPTZ,
    revocation_reason               TEXT,
    revoked_by                      UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    created_by                      UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at                      TIMESTAMPTZ NOT NULL,
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_client_auth_lookup
    ON public.client_filing_authorizations (firm_id, client_gstin_id, period, return_type);

CREATE INDEX IF NOT EXISTS idx_client_auth_token_hash
    ON public.client_filing_authorizations (token_hash);

CREATE INDEX IF NOT EXISTS idx_client_auth_status
    ON public.client_filing_authorizations (status);

CREATE INDEX IF NOT EXISTS idx_client_auth_expires
    ON public.client_filing_authorizations (expires_at);

ALTER TABLE public.client_filing_authorizations ENABLE ROW LEVEL SECURITY;

CREATE POLICY client_auth_firm_isolation
    ON public.client_filing_authorizations
    FOR ALL
    USING (firm_id = auth.uid())
    WITH CHECK (firm_id = auth.uid());


CREATE TABLE IF NOT EXISTS public.client_authorization_audit_trail (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    authorization_id                UUID NOT NULL REFERENCES public.client_filing_authorizations (id) ON DELETE CASCADE,
    firm_id                         UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    client_gstin_id                 UUID REFERENCES public.client_gstins (id) ON DELETE SET NULL,
    gstin                           VARCHAR(15) NOT NULL,
    period                          VARCHAR(7) NOT NULL,
    return_type                     VARCHAR(20) NOT NULL,
    action                          VARCHAR(50) NOT NULL,
    from_status                     VARCHAR(30),
    to_status                       VARCHAR(30) NOT NULL,
    actor_type                      VARCHAR(20) NOT NULL CHECK (actor_type IN ('ca_user', 'client', 'system')),
    actor_id                        UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    actor_name                      VARCHAR(255) NOT NULL DEFAULT '',
    figures_digest                  VARCHAR(64) NOT NULL,
    client_ip                       VARCHAR(45),
    user_agent                      TEXT,
    notes                           TEXT DEFAULT '',
    metadata                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_client_auth_audit_auth_id
    ON public.client_authorization_audit_trail (authorization_id);

CREATE INDEX IF NOT EXISTS idx_client_auth_audit_firm
    ON public.client_authorization_audit_trail (firm_id, created_at DESC);

ALTER TABLE public.client_authorization_audit_trail ENABLE ROW LEVEL SECURITY;

CREATE POLICY client_auth_audit_firm_isolation
    ON public.client_authorization_audit_trail
    FOR SELECT
    USING (firm_id = auth.uid());

GRANT SELECT, INSERT, UPDATE ON public.client_filing_authorizations TO authenticated;
GRANT SELECT, INSERT ON public.client_authorization_audit_trail TO authenticated;
GRANT SELECT, UPDATE ON public.client_filing_authorizations TO anon;
GRANT INSERT ON public.client_authorization_audit_trail TO anon;
