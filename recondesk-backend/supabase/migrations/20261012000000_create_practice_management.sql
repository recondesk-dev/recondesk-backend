-- ============================================================================
-- Migration: 20261012000000_create_practice_management.sql
-- Description: Phase 3.4 - CA Firm Practice Management, PAN-Level Organizations,
--              Staff Task Management, Compliance Calendar, and Audit Trail.
-- Target: Supabase / PostgreSQL Parity
-- ============================================================================

-- 1. Table: public.client_organizations (PAN-Level Legal Entities)
CREATE TABLE IF NOT EXISTS public.client_organizations (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id                     UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    pan                         VARCHAR(10) NOT NULL CHECK (pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]{1}$'),
    legal_name                  VARCHAR(255) NOT NULL,
    trade_name                  VARCHAR(255),
    constitution_of_business    VARCHAR(100),
    contact_name                VARCHAR(255),
    contact_email               VARCHAR(255),
    contact_phone               VARCHAR(50),
    is_active                   BOOLEAN NOT NULL DEFAULT TRUE,
    metadata                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_client_organizations_firm_pan UNIQUE (firm_id, pan)
);

CREATE INDEX IF NOT EXISTS idx_client_organizations_firm_id
    ON public.client_organizations (firm_id);

CREATE INDEX IF NOT EXISTS idx_client_organizations_pan
    ON public.client_organizations (pan);

CREATE INDEX IF NOT EXISTS idx_client_organizations_legal_name
    ON public.client_organizations (firm_id, LOWER(legal_name));


-- 2. Link client_gstins to client_organizations
ALTER TABLE public.client_gstins
    ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES public.client_organizations (id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_client_gstins_organization_id
    ON public.client_gstins (organization_id);

-- Idempotent backfill from existing client_gstins PANs
INSERT INTO public.client_organizations (
    firm_id,
    pan,
    legal_name,
    trade_name,
    constitution_of_business,
    metadata,
    created_at,
    updated_at
)
SELECT
    cg.firm_owner_id,
    substring(cg.gstin from 3 for 10) AS pan,
    COALESCE(NULLIF(TRIM(cg.legal_name), ''), NULLIF(TRIM(cg.trade_name), ''), 'Organization ' || substring(cg.gstin from 3 for 10)) AS legal_name,
    cg.trade_name,
    CASE substring(cg.gstin from 6 for 1)
        WHEN 'C' THEN 'Company'
        WHEN 'F' THEN 'Firm (Partnership / LLP) [Inferred]'
        WHEN 'P' THEN 'Individual / Proprietorship'
        WHEN 'H' THEN 'HUF'
        WHEN 'T' THEN 'Trust'
        WHEN 'A' THEN 'Association of Persons (AOP)'
        WHEN 'B' THEN 'Body of Individuals (BOI)'
        WHEN 'G' THEN 'Government Entity'
        WHEN 'L' THEN 'Local Authority'
        WHEN 'J' THEN 'Artificial Juridical Person'
        ELSE 'Other'
    END AS constitution_of_business,
    jsonb_build_object('constitution_inferred', true, 'constitution_source', 'PAN_4TH_CHAR', 'pan_entity_code', substring(cg.gstin from 6 for 1)),
    MIN(cg.added_at),
    NOW()
FROM public.client_gstins cg
WHERE length(cg.gstin) >= 12
  AND substring(cg.gstin from 3 for 10) ~ '^[A-Z]{5}[0-9]{4}[A-Z]{1}$'
GROUP BY cg.firm_owner_id, substring(cg.gstin from 3 for 10), cg.legal_name, cg.trade_name, substring(cg.gstin from 6 for 1)
ON CONFLICT (firm_id, pan) DO NOTHING;

UPDATE public.client_gstins cg
SET organization_id = co.id
FROM public.client_organizations co
WHERE cg.organization_id IS NULL
  AND co.firm_id = cg.firm_owner_id
  AND co.pan = substring(cg.gstin from 3 for 10);


-- 3. Table: public.practice_tasks (Staff Task Management)
CREATE TABLE IF NOT EXISTS public.practice_tasks (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    organization_id     UUID REFERENCES public.client_organizations (id) ON DELETE SET NULL,
    client_gstin_id     UUID REFERENCES public.client_gstins (id) ON DELETE CASCADE,
    period              VARCHAR(7) CHECK (period IS NULL OR period ~ '^[0-9]{4}-[0-9]{2}$'),
    category            VARCHAR(50) NOT NULL CHECK (category IN (
                            'RECONCILIATION',
                            'GSTR1_FILING',
                            'GSTR3B_FILING',
                            'GSTR9_FILING',
                            'CLIENT_APPROVAL',
                            'MAKER_CHECKER_REVIEW',
                            'NOTICE_REPLY',
                            'ITC_REVIEW',
                            'GENERAL_COMPLIANCE'
                        )),
    title               VARCHAR(255) NOT NULL,
    description         TEXT,
    priority            VARCHAR(20) NOT NULL DEFAULT 'MEDIUM' CHECK (priority IN ('LOW', 'MEDIUM', 'HIGH', 'URGENT')),
    status              VARCHAR(30) NOT NULL DEFAULT 'TODO' CHECK (status IN ('TODO', 'IN_PROGRESS', 'BLOCKED', 'COMPLETED', 'CANCELLED')),
    assignee_id         UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    due_date            DATE,
    created_by          UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    completed_at        TIMESTAMPTZ,
    completed_by        UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_practice_tasks_firm_status
    ON public.practice_tasks (firm_id, status);

CREATE INDEX IF NOT EXISTS idx_practice_tasks_assignee
    ON public.practice_tasks (firm_id, assignee_id);

CREATE INDEX IF NOT EXISTS idx_practice_tasks_client_period
    ON public.practice_tasks (client_gstin_id, period);

CREATE INDEX IF NOT EXISTS idx_practice_tasks_due_date
    ON public.practice_tasks (firm_id, due_date);


-- 4. Table: public.practice_task_audit_trail (Task Transition Audit Log)
CREATE TABLE IF NOT EXISTS public.practice_task_audit_trail (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id             UUID NOT NULL REFERENCES public.practice_tasks (id) ON DELETE CASCADE,
    firm_id             UUID NOT NULL REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    action              VARCHAR(50) NOT NULL,
    actor_id            UUID REFERENCES public.user_profiles (id) ON DELETE SET NULL,
    actor_name          VARCHAR(255) NOT NULL,
    actor_role          VARCHAR(50) NOT NULL,
    from_status         VARCHAR(30),
    to_status           VARCHAR(30),
    from_assignee_id    UUID,
    to_assignee_id      UUID,
    notes               TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_practice_task_audit_task_id
    ON public.practice_task_audit_trail (task_id, created_at);

CREATE INDEX IF NOT EXISTS idx_practice_task_audit_firm_id
    ON public.practice_task_audit_trail (firm_id, created_at);


-- 5. Table: public.compliance_deadlines (Configurable Statutory Compliance Calendar)
CREATE TABLE IF NOT EXISTS public.compliance_deadlines (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    period              VARCHAR(7) NOT NULL CHECK (period ~ '^[0-9]{4}-[0-9]{2}$'),
    return_type         VARCHAR(20) NOT NULL,
    category            VARCHAR(50) NOT NULL DEFAULT 'regular',
    state_group         VARCHAR(20) NOT NULL DEFAULT 'ALL',
    standard_due_date   DATE NOT NULL,
    extended_due_date   DATE,
    notification_ref    VARCHAR(255),
    firm_id             UUID REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_compliance_deadlines_lookup
    ON public.compliance_deadlines (period, return_type, category, state_group);


-- 6. Non-Destructive Restoration from Rollback Archives (if present)
DO $$
BEGIN
    -- 6.1 Restore Client Organizations
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = '_archive_client_organizations_rollback'
    ) THEN
        INSERT INTO public.client_organizations (
            id, firm_id, pan, legal_name, trade_name, constitution_of_business,
            contact_name, contact_email, contact_phone, is_active, metadata,
            created_at, updated_at
        )
        SELECT org_id, firm_id, pan, legal_name, trade_name, constitution_of_business,
               contact_name, contact_email, contact_phone, is_active, metadata,
               created_at, updated_at
        FROM public._archive_client_organizations_rollback
        ON CONFLICT (firm_id, pan) DO NOTHING;
    END IF;

    -- 6.2 Restore Practice Tasks
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = '_archive_practice_tasks_rollback'
    ) THEN
        INSERT INTO public.practice_tasks (
            id, firm_id, organization_id, client_gstin_id, period, category,
            title, description, priority, status, assignee_id, due_date,
            created_by, completed_at, completed_by, metadata, created_at, updated_at
        )
        SELECT task_id, firm_id, organization_id, client_gstin_id, period, category,
               title, description, priority, status, assignee_id, due_date,
               created_by, completed_at, completed_by, metadata, created_at, updated_at
        FROM public._archive_practice_tasks_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;

    -- 6.3 Restore Practice Task Audit Trail
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = '_archive_practice_task_audit_trail_rollback'
    ) THEN
        INSERT INTO public.practice_task_audit_trail (
            id, task_id, firm_id, action, actor_id, actor_name, actor_role,
            from_status, to_status, from_assignee_id, to_assignee_id, notes,
            metadata, created_at
        )
        SELECT entry_id, task_id, firm_id, action, actor_id, actor_name, actor_role,
               from_status, to_status, from_assignee_id, to_assignee_id, notes,
               metadata, created_at
        FROM public._archive_practice_task_audit_trail_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;

    -- 6.4 Restore Compliance Deadlines
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = '_archive_compliance_deadlines_rollback'
    ) THEN
        INSERT INTO public.compliance_deadlines (
            id, period, return_type, category, state_group,
            standard_due_date, extended_due_date, notification_ref,
            firm_id, created_at
        )
        SELECT deadline_id, period, return_type, category, state_group,
               standard_due_date, extended_due_date, notification_ref,
               firm_id, created_at
        FROM public._archive_compliance_deadlines_rollback
        ON CONFLICT (id) DO NOTHING;
    END IF;

    -- 6.5 Restore GSTIN to Organization Linkages
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = '_archive_client_gstins_org_link_rollback'
    ) THEN
        UPDATE public.client_gstins cg
        SET organization_id = arc.organization_id
        FROM public._archive_client_gstins_org_link_rollback arc
        WHERE cg.id = arc.client_gstin_id
          AND cg.organization_id IS NULL;
    END IF;
END $$;
