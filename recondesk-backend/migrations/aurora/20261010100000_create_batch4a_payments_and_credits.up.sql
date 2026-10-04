-- Migration: 20261010100000_create_batch4a_payments_and_credits.up.sql
-- Batch 4A: Subscriptions, Payments & Credit Accounting
-- Tables:
-- 1. payments
-- 2. run_credits
-- 3. idempotency_keys

-- 1. payments table
CREATE TABLE IF NOT EXISTS public.payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_owner_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    run_id UUID REFERENCES public.reconciliation_run(id) ON DELETE SET NULL,
    razorpay_order_id TEXT,
    razorpay_payment_id TEXT,
    amount_paise BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    plan TEXT,
    runs_purchased INTEGER,
    base_amount_paise BIGINT,
    gst_paise BIGINT,
    total_amount_paise BIGINT,
    customer_gstin TEXT,
    customer_trade_name TEXT,
    customer_city TEXT,
    customer_state_code TEXT,
    tax_type TEXT DEFAULT 'intra',
    cgst_paise INTEGER DEFAULT 0,
    sgst_paise INTEGER DEFAULT 0,
    igst_paise INTEGER DEFAULT 0,
    CONSTRAINT payments_plan_check CHECK (
        plan IS NULL OR plan IN ('starter', 'growth', 'pro', 'enterprise', 'solo', 'firm', 'large_firm', 'monthly')
    )
);

CREATE INDEX IF NOT EXISTS idx_payments_firm_owner_id
    ON public.payments (firm_owner_id);

CREATE INDEX IF NOT EXISTS idx_payments_run_id
    ON public.payments (run_id)
    WHERE run_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_payments_razorpay_order_id
    ON public.payments (razorpay_order_id)
    WHERE razorpay_order_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_payments_status
    ON public.payments (status);

COMMENT ON TABLE public.payments IS
    'Tracks SaaS subscription and run credit purchase orders, payments, and GST tax invoice details.';

-- 2. run_credits table
CREATE TABLE IF NOT EXISTS public.run_credits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_owner_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    payment_id UUID REFERENCES public.payments(id) ON DELETE SET NULL,
    plan TEXT NOT NULL,
    runs_purchased INTEGER NOT NULL,
    runs_remaining INTEGER NOT NULL,
    purchased_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT run_credits_plan_check CHECK (
        plan IN ('starter', 'growth', 'pro', 'enterprise', 'solo', 'firm', 'large_firm', 'monthly')
    )
);

CREATE INDEX IF NOT EXISTS idx_run_credits_firm_expiry
    ON public.run_credits (firm_owner_id, expires_at);

CREATE INDEX IF NOT EXISTS idx_run_credits_owner_expires
    ON public.run_credits (firm_owner_id, expires_at);

CREATE INDEX IF NOT EXISTS idx_run_credits_payment_id
    ON public.run_credits (payment_id)
    WHERE payment_id IS NOT NULL;

COMMENT ON TABLE public.run_credits IS
    'Purchased reconciliation run batches consumed FIFO by expires_at.';

-- 3. idempotency_keys table
CREATE TABLE IF NOT EXISTS public.idempotency_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key VARCHAR(300) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    response JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_idempotency_key_user UNIQUE (idempotency_key, user_id)
);

CREATE INDEX IF NOT EXISTS idx_idempotency_created
    ON public.idempotency_keys (created_at);

COMMENT ON TABLE public.idempotency_keys IS
    'Stores idempotent payment/mutation response payloads keyed by idempotency_key and user_id.';
