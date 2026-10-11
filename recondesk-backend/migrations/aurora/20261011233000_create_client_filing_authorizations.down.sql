-- ============================================================================
-- Migration: 20261011233000_create_client_filing_authorizations.down.sql
-- Description: Phase 3.3 - Safe Non-Destructive Rollback of Client Filing Authorizations
-- Target: AWS Aurora PostgreSQL
-- ============================================================================
-- PRODUCTION ROLLBACK ADVISORY:
-- In production AWS Aurora environments, the authoritative recovery procedure
-- for release failure is AWS Aurora Point-in-Time Recovery (PITR) or cluster
-- snapshot restoration (e.g. `aws rds restore-db-cluster-to-point-in-time`).
-- Schema downgrades on live databases risk breaking transactional invariants
-- and statutory compliance if downstream applications or users wrote consent
-- records under Phase 3.3.
--
-- This script provides a NON-DESTRUCTIVE rollback pattern for staging/dev environments:
-- 1. Archives all audit trail history into `_archive_client_authorization_audit_trail_rollback`.
-- 2. Archives all authorizations into `_archive_client_filing_authorizations_rollback`.
-- 3. Safely drops active tables only after records are durably archived.
-- ============================================================================

-- 1. Archive client_authorization_audit_trail before table removal to prevent permanent audit loss
CREATE TABLE IF NOT EXISTS public._archive_client_authorization_audit_trail_rollback (
    archive_id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entry_id                        UUID NOT NULL,
    authorization_id                UUID NOT NULL,
    firm_id                         UUID NOT NULL,
    client_gstin_id                 UUID,
    gstin                           VARCHAR(15) NOT NULL,
    period                          VARCHAR(7) NOT NULL,
    return_type                     VARCHAR(20) NOT NULL,
    action                          VARCHAR(50) NOT NULL,
    from_status                     VARCHAR(30),
    to_status                       VARCHAR(30) NOT NULL,
    actor_type                      VARCHAR(20) NOT NULL,
    actor_id                        UUID,
    actor_name                      VARCHAR(255) NOT NULL,
    figures_digest                  VARCHAR(64) NOT NULL,
    client_ip                       VARCHAR(45),
    user_agent                      TEXT,
    notes                           TEXT,
    metadata                        JSONB,
    created_at                      TIMESTAMPTZ NOT NULL,
    archived_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public._archive_client_authorization_audit_trail_rollback (
    entry_id, authorization_id, firm_id, client_gstin_id, gstin, period, return_type,
    action, from_status, to_status, actor_type, actor_id, actor_name,
    figures_digest, client_ip, user_agent, notes, metadata, created_at
)
SELECT id, authorization_id, firm_id, client_gstin_id, gstin, period, return_type,
       action, from_status, to_status, actor_type, actor_id, actor_name,
       figures_digest, client_ip, user_agent, notes, metadata, created_at
FROM public.client_authorization_audit_trail
ON CONFLICT (archive_id) DO NOTHING;

-- 2. Archive client_filing_authorizations before table removal to prevent permanent consent loss
CREATE TABLE IF NOT EXISTS public._archive_client_filing_authorizations_rollback (
    archive_id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_id                         UUID NOT NULL,
    firm_id                         UUID NOT NULL,
    client_gstin_id                 UUID NOT NULL,
    gstin                           VARCHAR(15) NOT NULL,
    period                          VARCHAR(7) NOT NULL,
    return_type                     VARCHAR(20) NOT NULL,
    status                          VARCHAR(30) NOT NULL,
    token_hash                      VARCHAR(64) NOT NULL,
    figures_digest                  VARCHAR(64) NOT NULL,
    figures_summary                 JSONB NOT NULL,
    signatory_name                  VARCHAR(255),
    signatory_designation           VARCHAR(100),
    signatory_contact               VARCHAR(100),
    consent_text_version            VARCHAR(20) NOT NULL,
    consent_declaration             TEXT,
    client_ip                       VARCHAR(45),
    user_agent                      TEXT,
    authorized_at                   TIMESTAMPTZ,
    rejected_at                     TIMESTAMPTZ,
    rejection_reason                TEXT,
    revoked_at                      TIMESTAMPTZ,
    revocation_reason               TEXT,
    revoked_by                      UUID,
    created_by                      UUID,
    created_at                      TIMESTAMPTZ NOT NULL,
    expires_at                      TIMESTAMPTZ NOT NULL,
    updated_at                      TIMESTAMPTZ NOT NULL,
    archived_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public._archive_client_filing_authorizations_rollback (
    auth_id, firm_id, client_gstin_id, gstin, period, return_type,
    status, token_hash, figures_digest, figures_summary,
    signatory_name, signatory_designation, signatory_contact,
    consent_text_version, consent_declaration, client_ip, user_agent,
    authorized_at, rejected_at, rejection_reason, revoked_at,
    revocation_reason, revoked_by, created_by, created_at, expires_at, updated_at
)
SELECT id, firm_id, client_gstin_id, gstin, period, return_type,
       status, token_hash, figures_digest, figures_summary,
       signatory_name, signatory_designation, signatory_contact,
       consent_text_version, consent_declaration, client_ip, user_agent,
       authorized_at, rejected_at, rejection_reason, revoked_at,
       revocation_reason, revoked_by, created_by, created_at, expires_at, updated_at
FROM public.client_filing_authorizations
ON CONFLICT (archive_id) DO NOTHING;

-- 3. Safely drop active tables now that records are fully archived
DROP TABLE IF EXISTS public.client_authorization_audit_trail CASCADE;
DROP TABLE IF EXISTS public.client_filing_authorizations CASCADE;
