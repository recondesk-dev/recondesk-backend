-- ============================================================================
-- Migration: 20260930183000_create_cognito_user_mappings.up.sql
-- Description: Phase 2A - Create persistent Cognito-to-ReconDesk identity mapping
--              and account-linking token tables with pool isolation
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

-- 1. Create table public.cognito_user_mappings
CREATE TABLE IF NOT EXISTS public.cognito_user_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cognito_user_pool_id VARCHAR(64) NOT NULL,
    cognito_sub VARCHAR(128) NOT NULL,
    user_id UUID NOT NULL,
    email VARCHAR(255) NOT NULL,
    mapping_method VARCHAR(50) NOT NULL,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    provisioned_by VARCHAR(128) NULL,
    linking_ip VARCHAR(64) NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Strict 1:1 Unique Constraints per User Pool:
    CONSTRAINT uq_cognito_pool_sub UNIQUE (cognito_user_pool_id, cognito_sub),
    CONSTRAINT uq_cognito_pool_user_id UNIQUE (cognito_user_pool_id, user_id),

    -- Foreign key to existing user profiles (prevents orphan mappings)
    CONSTRAINT fk_cognito_user_mappings_user_id
        FOREIGN KEY (user_id)
        REFERENCES public.user_profiles (id)
        ON DELETE RESTRICT,

    -- Check constraint on allowed provisioning methods
    CONSTRAINT ck_cognito_user_mappings_method
        CHECK (mapping_method IN ('admin_provisioned', 'verified_link_token'))
);

-- 2. Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_cognito_user_mappings_email
    ON public.cognito_user_mappings (LOWER(email));

CREATE INDEX IF NOT EXISTS idx_cognito_user_mappings_pool_sub
    ON public.cognito_user_mappings (cognito_user_pool_id, cognito_sub);

CREATE INDEX IF NOT EXISTS idx_cognito_user_mappings_verified
    ON public.cognito_user_mappings (cognito_user_pool_id, is_verified)
    WHERE is_verified = TRUE;

-- 3. Automatic updated_at trigger for cognito_user_mappings
CREATE OR REPLACE FUNCTION public.set_cognito_user_mappings_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_cognito_user_mappings_updated_at ON public.cognito_user_mappings;
CREATE TRIGGER trg_cognito_user_mappings_updated_at
    BEFORE UPDATE ON public.cognito_user_mappings
    FOR EACH ROW
    EXECUTE FUNCTION public.set_cognito_user_mappings_updated_at();

-- 4. Create table public.cognito_account_linking_tokens
-- Stores SHA-256 hashed one-time tokens. Plaintext tokens are NEVER stored.
CREATE TABLE IF NOT EXISTS public.cognito_account_linking_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash VARCHAR(64) NOT NULL,
    cognito_user_pool_id VARCHAR(64) NOT NULL,
    cognito_sub VARCHAR(128) NOT NULL,
    user_id UUID NOT NULL,
    email VARCHAR(255) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ NULL,
    created_ip VARCHAR(64) NULL,
    consumed_ip VARCHAR(64) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Token hash must be globally unique
    CONSTRAINT uq_cognito_linking_token_hash UNIQUE (token_hash),

    -- Foreign key to existing user profiles
    CONSTRAINT fk_cognito_linking_tokens_user_id
        FOREIGN KEY (user_id)
        REFERENCES public.user_profiles (id)
        ON DELETE RESTRICT
);

-- 5. Indexes for linking tokens
CREATE INDEX IF NOT EXISTS idx_cognito_tokens_lookup
    ON public.cognito_account_linking_tokens (token_hash)
    WHERE consumed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_cognito_tokens_user_id
    ON public.cognito_account_linking_tokens (user_id);

CREATE INDEX IF NOT EXISTS idx_cognito_tokens_pool_sub
    ON public.cognito_account_linking_tokens (cognito_user_pool_id, cognito_sub);

-- 6. Comments for data dictionary
COMMENT ON TABLE public.cognito_user_mappings IS
    'Persistent 1:1 identity mappings linking Amazon Cognito identities (sub) to ReconDesk users (user_profiles.id) isolated by user pool';
COMMENT ON COLUMN public.cognito_user_mappings.cognito_user_pool_id IS
    'Cognito User Pool ID (e.g. ap-south-1_nvIPYMvFh) isolating development from production';
COMMENT ON COLUMN public.cognito_user_mappings.cognito_sub IS
    'Amazon Cognito User Pool immutable user identifier (UUID format)';
COMMENT ON COLUMN public.cognito_user_mappings.user_id IS
    'ReconDesk user_profiles.id foreign key';
COMMENT ON COLUMN public.cognito_user_mappings.mapping_method IS
    'Provisioning method: admin_provisioned (pre-migration) or verified_link_token (cryptographic link)';
COMMENT ON COLUMN public.cognito_user_mappings.is_verified IS
    'Whether this mapping has been verified and is active';

COMMENT ON TABLE public.cognito_account_linking_tokens IS
    'Persistent store for one-time account linking tokens. Stores only SHA-256 hashes of issued tokens';
COMMENT ON COLUMN public.cognito_account_linking_tokens.token_hash IS
    'Hex-encoded SHA-256 hash of the one-time linking token';
COMMENT ON COLUMN public.cognito_account_linking_tokens.consumed_at IS
    'Timestamp when the token was consumed in an atomic transaction; NULL if unconsumed';
