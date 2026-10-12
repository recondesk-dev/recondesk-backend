-- ============================================================================
-- Migration: 20261012200000_create_private_ca_coupon_assignments.down.sql
-- Description: Revert private CA coupon assignment columns
-- Target: AWS Aurora PostgreSQL / Supabase
-- ============================================================================

DROP INDEX IF EXISTS public.idx_coupons_tenant_active_offer;
DROP INDEX IF EXISTS public.idx_coupons_offer_status;
DROP INDEX IF EXISTS public.idx_coupons_assigned_to_tenant_id;

ALTER TABLE public.coupons DROP CONSTRAINT IF EXISTS coupons_offer_status_check;

ALTER TABLE public.coupons
    DROP COLUMN IF EXISTS revoked_reason,
    DROP COLUMN IF EXISTS revoked_by_name,
    DROP COLUMN IF EXISTS revoked_by,
    DROP COLUMN IF EXISTS revoked_at,
    DROP COLUMN IF EXISTS offer_status,
    DROP COLUMN IF EXISTS sales_notes,
    DROP COLUMN IF EXISTS assigned_at,
    DROP COLUMN IF EXISTS assigned_by_name,
    DROP COLUMN IF EXISTS assigned_by,
    DROP COLUMN IF EXISTS assigned_to_email,
    DROP COLUMN IF EXISTS assigned_to_firm_name,
    DROP COLUMN IF EXISTS assigned_to_name,
    DROP COLUMN IF EXISTS assigned_to_tenant_id;
