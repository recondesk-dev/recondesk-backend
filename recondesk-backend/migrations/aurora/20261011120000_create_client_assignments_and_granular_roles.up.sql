-- ============================================================================
-- Migration: 20261011120000_create_client_assignments_and_granular_roles.up.sql
-- Description: Phase 3.1 - Granular RBAC and Multi-Role Client Assignments Migration
-- Target: AWS Aurora PostgreSQL
-- ============================================================================

-- 1. Update check constraint on team_members to include granular roles
ALTER TABLE public.team_members DROP CONSTRAINT IF EXISTS ck_team_members_role;
ALTER TABLE public.team_members DROP CONSTRAINT IF EXISTS team_members_role_check;
ALTER TABLE public.team_members ADD CONSTRAINT ck_team_members_role
    CHECK (role IN ('admin', 'staff', 'owner', 'partner', 'manager', 'preparer', 'viewer'));

-- 2. Create client_assignments table
CREATE TABLE IF NOT EXISTS public.client_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    firm_owner_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    assignment_role VARCHAR(50) NOT NULL DEFAULT 'preparer'
        CHECK (assignment_role IN ('preparer', 'reviewer', 'partner', 'manager', 'viewer')),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    assigned_by UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,
    CONSTRAINT uq_client_assignments_client_user_role UNIQUE (client_gstin_id, user_id, assignment_role)
);

CREATE INDEX IF NOT EXISTS idx_client_assignments_client_id ON public.client_assignments (client_gstin_id);
CREATE INDEX IF NOT EXISTS idx_client_assignments_user_id ON public.client_assignments (user_id);
CREATE INDEX IF NOT EXISTS idx_client_assignments_firm_owner_id ON public.client_assignments (firm_owner_id);

-- 3. Backward-compatible backfill: existing client_gstins.assigned_to -> client_assignments as 'preparer'
INSERT INTO public.client_assignments (client_gstin_id, firm_owner_id, user_id, assignment_role, assigned_at)
SELECT cg.id, cg.firm_owner_id, cg.assigned_to, 'preparer', cg.added_at
FROM public.client_gstins cg
JOIN public.user_profiles up_user ON up_user.id = cg.assigned_to
JOIN public.user_profiles up_owner ON up_owner.id = cg.firm_owner_id
WHERE cg.assigned_to IS NOT NULL AND cg.is_active = TRUE
ON CONFLICT (client_gstin_id, user_id, assignment_role) DO NOTHING;
