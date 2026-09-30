-- ============================================================================
-- Migration Rollback: 20260930183000_create_cognito_user_mappings.down.sql
-- Description: Safe, reversible rollback for Cognito identity mapping and token tables
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

BEGIN;

DO $$
BEGIN
    -- Refuse rollback if ANY identity mappings exist to prevent accidental data loss
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = 'cognito_user_mappings'
    ) THEN
        IF EXISTS (SELECT 1 FROM public.cognito_user_mappings LIMIT 1) THEN
            RAISE EXCEPTION 'Refusing to drop public.cognito_user_mappings: table contains existing identity mappings. Explicit data purge is required.';
        END IF;
    END IF;

    -- Refuse rollback if ANY linking-token audit records exist
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = 'cognito_account_linking_tokens'
    ) THEN
        IF EXISTS (SELECT 1 FROM public.cognito_account_linking_tokens LIMIT 1) THEN
            RAISE EXCEPTION 'Refusing to drop public.cognito_account_linking_tokens: table contains existing linking-token audit records. Explicit data purge is required.';
        END IF;
    END IF;
END $$;

-- 1. Drop trigger and trigger function
DROP TRIGGER IF EXISTS trg_cognito_user_mappings_updated_at ON public.cognito_user_mappings;
DROP FUNCTION IF EXISTS public.set_cognito_user_mappings_updated_at();

-- 2. Drop tables in safe dependency order without cascading drops
DROP TABLE IF EXISTS public.cognito_account_linking_tokens;
DROP TABLE IF EXISTS public.cognito_user_mappings;

COMMIT;
