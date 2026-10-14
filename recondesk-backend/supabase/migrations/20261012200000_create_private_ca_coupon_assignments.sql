-- ============================================================================
-- Migration: 20261012200000_create_private_ca_coupon_assignments.sql
-- Description: Private CA Coupon Assignment System (Supabase Parity)
-- Target: Supabase / PostgreSQL
-- ============================================================================

ALTER TABLE public.coupons
    ADD COLUMN IF NOT EXISTS assigned_to_tenant_id UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS assigned_to_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS assigned_to_firm_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS assigned_to_email VARCHAR(255),
    ADD COLUMN IF NOT EXISTS assigned_by UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS assigned_by_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS assigned_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS sales_notes TEXT,
    ADD COLUMN IF NOT EXISTS offer_status VARCHAR(30) NOT NULL DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS revoked_by UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS revoked_by_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS revoked_reason TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'coupons_offer_status_check'
    ) THEN
        ALTER TABLE public.coupons
            ADD CONSTRAINT coupons_offer_status_check
            CHECK (offer_status IN ('draft', 'active', 'redeemed', 'revoked', 'expired'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_coupons_assigned_to_tenant_id
    ON public.coupons (assigned_to_tenant_id);

CREATE INDEX IF NOT EXISTS idx_coupons_offer_status
    ON public.coupons (offer_status);

CREATE INDEX IF NOT EXISTS idx_coupons_tenant_active_offer
    ON public.coupons (assigned_to_tenant_id, is_active, offer_status)
    WHERE is_active = TRUE AND offer_status = 'active';

-- 4. Update discount_percentage check constraint to allow 40% discount tier
ALTER TABLE public.coupons
    DROP CONSTRAINT IF EXISTS coupons_discount_percentage_check;

ALTER TABLE public.coupons
    ADD CONSTRAINT coupons_discount_percentage_check
    CHECK (discount_percentage IN (20, 25, 30, 40));
