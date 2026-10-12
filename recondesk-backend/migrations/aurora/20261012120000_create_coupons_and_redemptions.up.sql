-- ============================================================================
-- Migration: 20261012120000_create_coupons_and_redemptions.up.sql
-- Description: Annual Subscription Coupon System (20%, 25%, 30%), redemptions,
--              concurrency safety, and payment discount linkage.
-- Target: AWS Aurora PostgreSQL / Supabase
-- ============================================================================

-- 1. Table: public.coupons
CREATE TABLE IF NOT EXISTS public.coupons (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code                        VARCHAR(50) NOT NULL,
    discount_percentage         INTEGER NOT NULL CHECK (discount_percentage IN (20, 25, 30)),
    eligible_plans              JSONB NOT NULL DEFAULT '["solo", "firm", "large_firm"]'::jsonb,
    is_active                   BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at                  TIMESTAMPTZ,
    max_redemptions             INTEGER,
    redemptions_count           INTEGER NOT NULL DEFAULT 0,
    max_per_customer            INTEGER NOT NULL DEFAULT 1,
    restricted_to_tenant_id     UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    restricted_to_email         VARCHAR(255),
    is_acquisition_only         BOOLEAN NOT NULL DEFAULT TRUE,
    created_by                  UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    founder_approved            BOOLEAN NOT NULL DEFAULT FALSE,
    founder_approved_by         VARCHAR(255),
    founder_approval_notes      TEXT,
    metadata                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Case-insensitive unique index on coupon code
CREATE UNIQUE INDEX IF NOT EXISTS uq_coupons_code_lower
    ON public.coupons (LOWER(code));

CREATE INDEX IF NOT EXISTS idx_coupons_is_active
    ON public.coupons (is_active);

CREATE INDEX IF NOT EXISTS idx_coupons_expires_at
    ON public.coupons (expires_at);

CREATE INDEX IF NOT EXISTS idx_coupons_restricted_tenant
    ON public.coupons (restricted_to_tenant_id);

CREATE INDEX IF NOT EXISTS idx_coupons_is_acquisition_only
    ON public.coupons (is_acquisition_only);


-- 2. Ensure public.payments exists and relax payments_plan_check to support solo and large_firm
CREATE TABLE IF NOT EXISTS public.payments (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_owner_id               UUID REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    run_id                      UUID,
    razorpay_order_id           TEXT,
    razorpay_payment_id         TEXT,
    amount_paise                BIGINT NOT NULL,
    status                      TEXT NOT NULL DEFAULT 'created',
    plan                        TEXT,
    plan_version                INTEGER DEFAULT 2,
    billing_cycle               TEXT DEFAULT 'yearly',
    gstin_limit                 INTEGER,
    overage_gstins              INTEGER DEFAULT 0,
    overage_rate_paise          INTEGER DEFAULT 0,
    runs_purchased              INTEGER DEFAULT 0,
    base_amount_paise           BIGINT,
    gst_paise                   BIGINT,
    total_amount_paise          BIGINT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Relax payments_plan_check constraint to include modern ReconDesk annual plans (solo, firm, large_firm)
ALTER TABLE public.payments DROP CONSTRAINT IF EXISTS payments_plan_check;
ALTER TABLE public.payments ADD CONSTRAINT payments_plan_check CHECK (
    plan IS NULL OR plan IN ('starter', 'growth', 'pro', 'firm', 'solo', 'large_firm', 'monthly', 'custom', 'enterprise', 'free')
);

CREATE INDEX IF NOT EXISTS idx_payments_razorpay_order_id ON public.payments (razorpay_order_id);
CREATE INDEX IF NOT EXISTS idx_payments_razorpay_payment_id ON public.payments (razorpay_payment_id);


-- 3. Table: public.coupon_redemptions
CREATE TABLE IF NOT EXISTS public.coupon_redemptions (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coupon_id                   UUID NOT NULL REFERENCES public.coupons (id) ON DELETE RESTRICT,
    tenant_id                   UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    user_id                     UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    payment_id                  UUID REFERENCES public.payments (id) ON DELETE SET NULL,
    razorpay_order_id           VARCHAR(100) NOT NULL,
    razorpay_payment_id         VARCHAR(100),
    original_base_amount_paise  INTEGER NOT NULL,
    discount_amount_paise       INTEGER NOT NULL,
    final_base_amount_paise     INTEGER NOT NULL,
    gst_amount_paise            INTEGER NOT NULL,
    total_amount_paise          INTEGER NOT NULL,
    plan                        VARCHAR(50) NOT NULL,
    billing_cycle               VARCHAR(20) NOT NULL DEFAULT 'yearly',
    status                      VARCHAR(30) NOT NULL DEFAULT 'pending',
    metadata                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_coupon_id
    ON public.coupon_redemptions (coupon_id);

CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_tenant_id
    ON public.coupon_redemptions (tenant_id);

CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_order_id
    ON public.coupon_redemptions (razorpay_order_id);

CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_status
    ON public.coupon_redemptions (status);

CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_tenant_coupon_status
    ON public.coupon_redemptions (tenant_id, coupon_id, status);


-- 4. Extend payments table with complete modern schema and coupon discount tracking
ALTER TABLE public.payments
    ADD COLUMN IF NOT EXISTS plan_version INTEGER DEFAULT 2,
    ADD COLUMN IF NOT EXISTS billing_cycle TEXT DEFAULT 'yearly',
    ADD COLUMN IF NOT EXISTS gstin_limit INTEGER,
    ADD COLUMN IF NOT EXISTS overage_gstins INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS overage_rate_paise INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS coupon_id UUID REFERENCES public.coupons (id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS coupon_code VARCHAR(50),
    ADD COLUMN IF NOT EXISTS discount_percentage INTEGER,
    ADD COLUMN IF NOT EXISTS discount_amount_paise INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS refund_id VARCHAR(100),
    ADD COLUMN IF NOT EXISTS refund_status VARCHAR(50),
    ADD COLUMN IF NOT EXISTS refund_error TEXT;

CREATE INDEX IF NOT EXISTS idx_payments_refund_id ON public.payments (refund_id);

COMMENT ON COLUMN public.payments.coupon_code IS 'Promotional coupon code applied during subscription checkout';
COMMENT ON COLUMN public.payments.discount_percentage IS 'Discount percentage applied (20, 25, or 30)';
COMMENT ON COLUMN public.payments.discount_amount_paise IS 'Discount base amount subtracted from taxable amount in paise';
COMMENT ON COLUMN public.payments.refund_id IS 'Gateway refund identifier if refund was initiated or processed';
COMMENT ON COLUMN public.payments.refund_status IS 'Refund lifecycle status: pending, processed, or failed';
COMMENT ON COLUMN public.payments.refund_error IS 'Error details if automated refund request failed on gateway';
