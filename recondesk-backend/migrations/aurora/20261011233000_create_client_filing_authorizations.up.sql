-- ============================================================================
-- Migration: 20261011233000_create_client_filing_authorizations.up.sql
-- Description: Phase 3.3 - Client Review, Consent and Filing Authorization
--              Introduces time-limited, cryptographically hashed access tokens,
--              explicit legal consent declarations, and immutable audit logs.
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

-- 1. Table: public.client_filing_authorizations
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

COMMENT ON TABLE public.client_filing_authorizations IS
    'Client filing authorization tokens, legal consent records, and status.';


-- 2. Table: public.client_authorization_audit_trail
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

COMMENT ON TABLE public.client_authorization_audit_trail IS
    'Immutable tenant-scoped audit trail for all client review and authorization actions.';


-- 3. Non-Destructive Restoration from Rollback Archives (if present)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = '_archive_client_filing_authorizations_rollback'
    ) THEN
        INSERT INTO public.client_filing_authorizations (
            id, firm_id, client_gstin_id, gstin, period, return_type,
            status, token_hash, figures_digest, figures_summary,
            signatory_name, signatory_designation, signatory_contact,
            consent_text_version, consent_declaration, client_ip, user_agent,
            authorized_at, rejected_at, rejection_reason, revoked_at,
            revocation_reason, revoked_by, created_by, created_at, expires_at, updated_at
        )
        SELECT auth_id, firm_id, client_gstin_id, gstin, period, return_type,
               status, token_hash, figures_digest, figures_summary,
               signatory_name, signatory_designation, signatory_contact,
               consent_text_version, consent_declaration, client_ip, user_agent,
               authorized_at, rejected_at, rejection_reason, revoked_at,
               revocation_reason, revoked_by, created_by, created_at, expires_at, updated_at
        FROM public._archive_client_filing_authorizations_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = '_archive_client_authorization_audit_trail_rollback'
    ) THEN
        INSERT INTO public.client_authorization_audit_trail (
            id, authorization_id, firm_id, client_gstin_id, gstin, period, return_type,
            action, from_status, to_status, actor_type, actor_id, actor_name,
            figures_digest, client_ip, user_agent, notes, metadata, created_at
        )
        SELECT entry_id, authorization_id, firm_id, client_gstin_id, gstin, period, return_type,
               action, from_status, to_status, actor_type, actor_id, actor_name,
               figures_digest, client_ip, user_agent, notes, metadata, created_at
        FROM public._archive_client_authorization_audit_trail_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;
END $$;
