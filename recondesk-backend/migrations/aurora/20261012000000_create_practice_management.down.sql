-- ============================================================================
-- Migration: 20261012000000_create_practice_management.down.sql
-- Description: Phase 3.4 - Safe Non-Destructive Rollback of CA Practice Management
-- Target: AWS Aurora PostgreSQL
-- ============================================================================
-- PRODUCTION ROLLBACK ADVISORY:
-- In production AWS Aurora environments, the authoritative recovery procedure
-- for release failure is AWS Aurora Point-in-Time Recovery (PITR) or cluster
-- snapshot restoration (e.g. `aws rds restore-db-cluster-to-point-in-time`).
-- Schema downgrades on live databases risk breaking transactional invariants
-- and statutory practice workflows.
--
-- This script implements a NON-DESTRUCTIVE archival rollback pattern:
-- 1. Archives audit trail history into `_archive_practice_task_audit_trail_rollback`.
-- 2. Archives staff tasks into `_archive_practice_tasks_rollback`.
-- 3. Archives compliance deadline overrides into `_archive_compliance_deadlines_rollback`.
-- 4. Archives client organization records into `_archive_client_organizations_rollback`.
-- 5. Archives GSTIN-organization linkages into `_archive_client_gstins_org_link_rollback`.
-- 6. Safely removes active tables only after records are durably archived.
-- ============================================================================

-- 1. Archive practice_task_audit_trail before table removal to prevent permanent audit loss
CREATE TABLE IF NOT EXISTS public._archive_practice_task_audit_trail_rollback (
    archive_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entry_id            UUID NOT NULL,
    task_id             UUID NOT NULL,
    firm_id             UUID NOT NULL,
    action              VARCHAR(50) NOT NULL,
    actor_id            UUID,
    actor_name          VARCHAR(255) NOT NULL,
    actor_role          VARCHAR(50) NOT NULL,
    from_status         VARCHAR(30),
    to_status           VARCHAR(30),
    from_assignee_id    UUID,
    to_assignee_id      UUID,
    notes               TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL,
    archived_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'practice_task_audit_trail'
    ) THEN
        INSERT INTO public._archive_practice_task_audit_trail_rollback (
            entry_id, task_id, firm_id, action, actor_id, actor_name, actor_role,
            from_status, to_status, from_assignee_id, to_assignee_id, notes,
            metadata, created_at
        )
        SELECT id, task_id, firm_id, action, actor_id, actor_name, actor_role,
               from_status, to_status, from_assignee_id, to_assignee_id, notes,
               metadata, created_at
        FROM public.practice_task_audit_trail
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;


-- 2. Archive practice_tasks before table removal
CREATE TABLE IF NOT EXISTS public._archive_practice_tasks_rollback (
    archive_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id             UUID NOT NULL,
    firm_id             UUID NOT NULL,
    organization_id     UUID,
    client_gstin_id     UUID,
    period              VARCHAR(7),
    category            VARCHAR(50) NOT NULL,
    title               VARCHAR(255) NOT NULL,
    description         TEXT,
    priority            VARCHAR(20) NOT NULL,
    status              VARCHAR(30) NOT NULL,
    assignee_id         UUID,
    due_date            DATE,
    created_by          UUID,
    completed_at        TIMESTAMPTZ,
    completed_by        UUID,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL,
    archived_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'practice_tasks'
    ) THEN
        INSERT INTO public._archive_practice_tasks_rollback (
            task_id, firm_id, organization_id, client_gstin_id, period, category,
            title, description, priority, status, assignee_id, due_date,
            created_by, completed_at, completed_by, metadata, created_at, updated_at
        )
        SELECT id, firm_id, organization_id, client_gstin_id, period, category,
               title, description, priority, status, assignee_id, due_date,
               created_by, completed_at, completed_by, metadata, created_at, updated_at
        FROM public.practice_tasks
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;


-- 3. Archive compliance_deadlines before table removal
CREATE TABLE IF NOT EXISTS public._archive_compliance_deadlines_rollback (
    archive_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deadline_id         UUID NOT NULL,
    period              VARCHAR(7) NOT NULL,
    return_type         VARCHAR(20) NOT NULL,
    category            VARCHAR(50) NOT NULL,
    state_group         VARCHAR(20) NOT NULL,
    standard_due_date   DATE NOT NULL,
    extended_due_date   DATE,
    notification_ref    VARCHAR(255),
    firm_id             UUID,
    created_at          TIMESTAMPTZ NOT NULL,
    archived_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'compliance_deadlines'
    ) THEN
        INSERT INTO public._archive_compliance_deadlines_rollback (
            deadline_id, period, return_type, category, state_group,
            standard_due_date, extended_due_date, notification_ref,
            firm_id, created_at
        )
        SELECT id, period, return_type, category, state_group,
               standard_due_date, extended_due_date, notification_ref,
               firm_id, created_at
        FROM public.compliance_deadlines
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;


-- 4. Archive client_organizations before table removal
CREATE TABLE IF NOT EXISTS public._archive_client_organizations_rollback (
    archive_id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                      UUID NOT NULL,
    firm_id                     UUID NOT NULL,
    pan                         VARCHAR(10) NOT NULL,
    legal_name                  VARCHAR(255) NOT NULL,
    trade_name                  VARCHAR(255),
    constitution_of_business    VARCHAR(100),
    contact_name                VARCHAR(255),
    contact_email               VARCHAR(255),
    contact_phone               VARCHAR(50),
    is_active                   BOOLEAN NOT NULL,
    metadata                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ NOT NULL,
    updated_at                  TIMESTAMPTZ NOT NULL,
    archived_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'client_organizations'
    ) THEN
        INSERT INTO public._archive_client_organizations_rollback (
            org_id, firm_id, pan, legal_name, trade_name, constitution_of_business,
            contact_name, contact_email, contact_phone, is_active, metadata,
            created_at, updated_at
        )
        SELECT id, firm_id, pan, legal_name, trade_name, constitution_of_business,
               contact_name, contact_email, contact_phone, is_active, metadata,
               created_at, updated_at
        FROM public.client_organizations
        ON CONFLICT (archive_id) DO NOTHING;
    END IF;
END $$;


-- 5. Archive GSTIN to Organization linkages before column drop
CREATE TABLE IF NOT EXISTS public._archive_client_gstins_org_link_rollback (
    archive_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_gstin_id     UUID NOT NULL,
    organization_id     UUID NOT NULL,
    firm_owner_id       UUID NOT NULL,
    archived_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'client_gstins' AND column_name = 'organization_id'
    ) THEN
        INSERT INTO public._archive_client_gstins_org_link_rollback (
            client_gstin_id, organization_id, firm_owner_id
        )
        SELECT id, organization_id, firm_owner_id
        FROM public.client_gstins
        WHERE organization_id IS NOT NULL
        ON CONFLICT (archive_id) DO NOTHING;

        -- Remove column from client_gstins
        ALTER TABLE public.client_gstins DROP COLUMN IF EXISTS organization_id;
    END IF;
END $$;


-- 6. Safely Drop Active Tables in Dependency Order
DROP TABLE IF EXISTS public.practice_task_audit_trail;
DROP TABLE IF EXISTS public.practice_tasks;
DROP TABLE IF EXISTS public.compliance_deadlines;
DROP TABLE IF EXISTS public.client_organizations;
