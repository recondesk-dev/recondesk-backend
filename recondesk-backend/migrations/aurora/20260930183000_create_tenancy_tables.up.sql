-- ============================================================================
-- Migration: 20260930183000_create_tenancy_tables.up.sql
-- Description: Phase 3B - Foundational Aurora Tenancy Layer:
--              user_profiles, team_members, and client_gstins
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

-- 1. Table: public.user_profiles
-- Represents the canonical ReconDesk user identity and CA principal anchor.
CREATE TABLE IF NOT EXISTS public.user_profiles (
    id UUID PRIMARY KEY,
    email VARCHAR(255),
    full_name VARCHAR(255),
    firm_name VARCHAR(255),
    phone VARCHAR(50),
    role VARCHAR(50) NOT NULL DEFAULT 'admin',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    plan VARCHAR(50) DEFAULT 'free',
    runs_used INTEGER DEFAULT 0,
    runs_limit INTEGER DEFAULT 2,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    runs_balance INTEGER DEFAULT 0,
    free_runs_remaining INTEGER NOT NULL DEFAULT 2,
    firm_city VARCHAR(255),
    onboarding_completed BOOLEAN DEFAULT FALSE,
    icai_membership_number VARCHAR(100),
    firm_gstin VARCHAR(15),
    gstin_limit INTEGER NOT NULL DEFAULT 2,
    subscription_ends_at TIMESTAMPTZ,
    is_first_login BOOLEAN NOT NULL DEFAULT TRUE,
    client_gstin_id VARCHAR(15),
    auto_approve_confidence_threshold INTEGER NOT NULL DEFAULT 95
);

-- Ensure all production columns exist idempotently if table was pre-created in minimal form
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS phone VARCHAR(50);
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS plan VARCHAR(50) DEFAULT 'free';
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS runs_used INTEGER DEFAULT 0;
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS runs_limit INTEGER DEFAULT 2;
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS runs_balance INTEGER DEFAULT 0;
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS free_runs_remaining INTEGER DEFAULT 2;
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS firm_city VARCHAR(255);
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN DEFAULT FALSE;
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS icai_membership_number VARCHAR(100);
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS firm_gstin VARCHAR(15);
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS gstin_limit INTEGER DEFAULT 2;
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS subscription_ends_at TIMESTAMPTZ;
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS is_first_login BOOLEAN DEFAULT TRUE;
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS client_gstin_id VARCHAR(15);
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS auto_approve_confidence_threshold INTEGER DEFAULT 95;

CREATE INDEX IF NOT EXISTS idx_user_profiles_email ON public.user_profiles (LOWER(email));
CREATE INDEX IF NOT EXISTS idx_user_profiles_client_gstin_id ON public.user_profiles (client_gstin_id);


-- 2. Table: public.team_members
-- Represents staff membership and invitations anchored to a firm owner (CA principal).
CREATE TABLE IF NOT EXISTS public.team_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_owner_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    member_user_id UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,
    role VARCHAR(50) NOT NULL CHECK (role IN ('admin', 'staff')),
    invited_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accepted_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    invited_email VARCHAR(255),
    invite_token VARCHAR(255),
    invite_expires_at TIMESTAMPTZ,
    CONSTRAINT uq_team_members_firm_member UNIQUE (firm_owner_id, member_user_id)
);

CREATE INDEX IF NOT EXISTS idx_team_members_firm_owner_id ON public.team_members (firm_owner_id);
CREATE INDEX IF NOT EXISTS idx_team_members_member_user_id ON public.team_members (member_user_id);
CREATE INDEX IF NOT EXISTS idx_team_members_invited_email ON public.team_members (LOWER(invited_email));


-- 3. Table: public.client_gstins
-- Represents client GSTIN records owned by a firm owner and optionally assigned to staff.
CREATE TABLE IF NOT EXISTS public.client_gstins (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_owner_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    gstin VARCHAR(15) NOT NULL,
    trade_name VARCHAR(255),
    legal_name VARCHAR(255),
    state_code VARCHAR(10),
    registration_type VARCHAR(50),
    assigned_to UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    gstn_access_token TEXT,
    gstn_token_expiry TIMESTAMPTZ,
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    contact_name VARCHAR(255),
    contact_email VARCHAR(255),
    contact_phone VARCHAR(50),
    scheme_type VARCHAR(50) NOT NULL DEFAULT 'regular'
        CHECK (scheme_type IN ('regular', 'composition', 'casual', 'nrtp', 'isd', 'tds_tcs_deductor')),
    filing_frequency VARCHAR(20) NOT NULL DEFAULT 'monthly'
        CHECK (filing_frequency IN ('monthly', 'qrmp')),
    CONSTRAINT uq_client_gstins_firm_gstin UNIQUE (firm_owner_id, gstin)
);

CREATE INDEX IF NOT EXISTS idx_client_gstins_firm_owner_id ON public.client_gstins (firm_owner_id);
CREATE INDEX IF NOT EXISTS idx_client_gstins_assigned_to ON public.client_gstins (assigned_to);
CREATE INDEX IF NOT EXISTS idx_client_gstins_gstin ON public.client_gstins (gstin);
CREATE INDEX IF NOT EXISTS idx_client_gstins_firm_owner_is_demo ON public.client_gstins (firm_owner_id, is_demo) WHERE (is_active = TRUE);
