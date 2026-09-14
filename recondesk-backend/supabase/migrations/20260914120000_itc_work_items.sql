-- Migration: 20260914120000_itc_work_items.sql
-- Description: Phase 5.2 Exception Work Item Lifecycle Engine
-- Creates itc_work_items and itc_work_item_events for CA operational exception handling.

-- 1. ITC Work Items Table
CREATE TABLE IF NOT EXISTS public.itc_work_items (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_owner_id               UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    client_gstin_id             UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    run_id                      UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE CASCADE,
    record_id                   TEXT NOT NULL,
    exception_type              VARCHAR(50) NOT NULL,

    -- Operational Lifecycle Status
    status                      VARCHAR(30) NOT NULL DEFAULT 'OPEN',
    -- 'OPEN' | 'TRIAGED' | 'ASSIGNED' | 'IN_PROGRESS' | 'WAITING_VENDOR' | 
    -- 'READY_FOR_REVIEW' | 'RESOLVED' | 'DISMISSED' | 'NOT_ACTIONABLE' | 'CARRIED_FORWARD'

    -- Priority with Manual Override Tracking
    priority                    VARCHAR(20) NOT NULL DEFAULT 'MEDIUM', -- ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')
    system_priority             VARCHAR(20) NOT NULL DEFAULT 'MEDIUM',
    manual_priority             VARCHAR(20),
    priority_override_reason    TEXT,
    priority_changed_by         UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,
    priority_changed_at         TIMESTAMPTZ,

    -- Categorization and CA Guidance
    category                    VARCHAR(50) NOT NULL DEFAULT 'OTHER',
    title                       TEXT,
    what                        TEXT NOT NULL DEFAULT '',
    why                         TEXT NOT NULL DEFAULT '',
    next_action                 TEXT NOT NULL DEFAULT '',

    -- Ownership Assignment
    assigned_to                 UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,
    assigned_at                 TIMESTAMPTZ,
    assigned_by                 UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,

    -- Due Dates and SLA Status
    due_at                      TIMESTAMPTZ,
    sla_status                  VARCHAR(20) NOT NULL DEFAULT 'NO_DUE_DATE',
    -- 'ON_TRACK' | 'DUE_SOON' | 'OVERDUE' | 'NO_DUE_DATE'

    -- Structured Resolution
    resolution_code             VARCHAR(50),
    resolution_note             TEXT,
    resolved_at                 TIMESTAMPTZ,
    resolved_by                 UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,

    -- Dismissal and Reopen
    dismissal_reason            TEXT,
    dismissed_at                TIMESTAMPTZ,
    dismissed_by                UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,
    reopen_reason               TEXT,
    reopened_at                 TIMESTAMPTZ,
    reopened_by                 UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,

    -- Revalidation Hook (Orthogonal to Operational Status)
    revalidation_status         VARCHAR(30) NOT NULL DEFAULT 'NONE',
    -- 'NONE' | 'PENDING' | 'REVALIDATED'
    revalidation_requested_at   TIMESTAMPTZ,
    revalidation_completed_at   TIMESTAMPTZ,
    revalidation_result         VARCHAR(30),
    -- 'EXCEPTION_CLEARED' | 'EXCEPTION_REMAINED' | 'EXCEPTION_CHANGED'

    -- Lineage and Source Versioning
    source_version              INTEGER NOT NULL DEFAULT 1,
    carried_forward_from_id     UUID REFERENCES public.itc_work_items(id) ON DELETE SET NULL,

    -- Contextual Invoice & Tax Snapshots (Read-only reference for UI)
    vendor_gstin                VARCHAR(15),
    vendor_name                 TEXT,
    invoice_number              VARCHAR(100),
    invoice_date                DATE,
    taxable_value               NUMERIC(15,2) NOT NULL DEFAULT 0,
    igst                        NUMERIC(15,2) NOT NULL DEFAULT 0,
    cgst                        NUMERIC(15,2) NOT NULL DEFAULT 0,
    sgst                        NUMERIC(15,2) NOT NULL DEFAULT 0,
    cess                        NUMERIC(15,2) NOT NULL DEFAULT 0,
    total_tax                   NUMERIC(15,2) NOT NULL DEFAULT 0,
    itc_amount_at_stake         NUMERIC(15,2) NOT NULL DEFAULT 0,
    itc_amount_at_stake_paise   BIGINT NOT NULL DEFAULT 0,
    is_blocking                 BOOLEAN NOT NULL DEFAULT FALSE,

    -- System Timestamps
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    created_by                  UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_by                  UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,

    -- Authoritative Canonical Uniqueness Constraint
    CONSTRAINT uq_itc_work_item UNIQUE (run_id, record_id, exception_type)
);

-- Indexes for Fast Operational Queries
CREATE INDEX IF NOT EXISTS idx_itc_work_items_firm ON public.itc_work_items (firm_owner_id);
CREATE INDEX IF NOT EXISTS idx_itc_work_items_client ON public.itc_work_items (client_gstin_id);
CREATE INDEX IF NOT EXISTS idx_itc_work_items_run ON public.itc_work_items (run_id);
CREATE INDEX IF NOT EXISTS idx_itc_work_items_assigned ON public.itc_work_items (assigned_to);
CREATE INDEX IF NOT EXISTS idx_itc_work_items_status ON public.itc_work_items (status);
CREATE INDEX IF NOT EXISTS idx_itc_work_items_priority ON public.itc_work_items (priority);
CREATE INDEX IF NOT EXISTS idx_itc_work_items_due ON public.itc_work_items (due_at);

ALTER TABLE public.itc_work_items DISABLE ROW LEVEL SECURITY;
GRANT ALL ON public.itc_work_items TO postgres, service_role, authenticated;


-- 2. ITC Work Item Events (Audit & Activity Timeline)
CREATE TABLE IF NOT EXISTS public.itc_work_item_events (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    work_item_id                UUID NOT NULL REFERENCES public.itc_work_items(id) ON DELETE CASCADE,
    event_type                  VARCHAR(50) NOT NULL,
    -- 'WORK_ITEM_CREATED' | 'ASSIGNED' | 'REASSIGNED' | 'STATUS_CHANGED' | 
    -- 'PRIORITY_CHANGED' | 'NOTE_ADDED' | 'DUE_DATE_CHANGED' | 'WAITING_VENDOR' | 
    -- 'SUBMITTED_FOR_REVIEW' | 'RESOLUTION_PROPOSED' | 'RESOLUTION_APPROVED' | 
    -- 'DISMISSED' | 'CARRIED_FORWARD' | 'REOPENED' | 'REVALIDATION_REQUESTED'

    from_status                 VARCHAR(30),
    to_status                   VARCHAR(30),

    actor_id                    UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,
    actor_role                  VARCHAR(20),
    actor_name                  VARCHAR(150),

    note                        TEXT,
    metadata                    JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_itc_wi_events_wi_id ON public.itc_work_item_events (work_item_id, created_at ASC);

ALTER TABLE public.itc_work_item_events DISABLE ROW LEVEL SECURITY;
GRANT ALL ON public.itc_work_item_events TO postgres, service_role, authenticated;
