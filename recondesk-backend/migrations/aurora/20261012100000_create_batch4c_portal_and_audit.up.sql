-- Migration: 20261012100000_create_batch4c_portal_and_audit.up.sql
-- Batch 4C: Client Portal, Communication, User Preferences & Audit Logs
-- Tables:
-- 1. notification_preferences
-- 2. upload_requests
-- 3. uploaded_files
-- 4. communication_logs
-- 5. audit_logs

-- 1. notification_preferences
CREATE TABLE IF NOT EXISTS public.notification_preferences (
    user_id UUID PRIMARY KEY REFERENCES public.user_profiles(id) ON DELETE CASCADE,
    run_completed BOOLEAN NOT NULL DEFAULT true,
    runs_expiring_soon BOOLEAN NOT NULL DEFAULT true,
    payment_receipts BOOLEAN NOT NULL DEFAULT true,
    rule37_alerts BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_preferences_user_id 
    ON public.notification_preferences (user_id);

COMMENT ON TABLE public.notification_preferences IS
    'Per-user email notification toggles (run_completed, runs_expiring_soon, payment_receipts, rule37_alerts).';

-- 2. upload_requests
CREATE TABLE IF NOT EXISTS public.upload_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL,
    token TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    expires_at TIMESTAMPTZ DEFAULT (now() + INTERVAL '7 days'),
    created_by_user_id UUID NOT NULL REFERENCES public.user_profiles(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_upload_requests_client_org 
    ON public.upload_requests (client_id, organization_id);

CREATE INDEX IF NOT EXISTS idx_upload_requests_token 
    ON public.upload_requests (token);

COMMENT ON TABLE public.upload_requests IS
    'Client document upload links with cryptographic token and expiry.';

-- 3. uploaded_files
CREATE TABLE IF NOT EXISTS public.uploaded_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    upload_request_id UUID NOT NULL REFERENCES public.upload_requests(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_size BIGINT NOT NULL,
    mime_type TEXT NOT NULL,
    public_url TEXT NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_uploaded_files_request 
    ON public.uploaded_files (upload_request_id);

COMMENT ON TABLE public.uploaded_files IS
    'Metadata for files uploaded through client upload request links.';

-- 4. communication_logs
CREATE TABLE IF NOT EXISTS public.communication_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL,
    template_type TEXT NOT NULL,
    message_content TEXT NOT NULL,
    sent_via TEXT NOT NULL,
    sent_by_user_id UUID NOT NULL REFERENCES public.user_profiles(id),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_communication_logs_client_org 
    ON public.communication_logs (client_id, organization_id);

COMMENT ON TABLE public.communication_logs IS
    'Log of messages and upload requests dispatched to clients.';

-- 5. audit_logs
-- Note: user_id is an unconstrained UUID (no FK to user_profiles) per Phase 9G-10 audit,
-- preserving historical records of deleted/system users. firm_id references user_profiles(id).
CREATE TABLE IF NOT EXISTS public.audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id UUID,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ip_address TEXT,
    correlation_id UUID,
    firm_id UUID REFERENCES public.user_profiles(id),
    user_name TEXT,
    role TEXT,
    entity_label TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at 
    ON public.audit_logs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_entity_id 
    ON public.audit_logs (entity_id);

CREATE INDEX IF NOT EXISTS idx_audit_logs_firm_created 
    ON public.audit_logs (firm_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_firm_id 
    ON public.audit_logs (firm_id);

CREATE INDEX IF NOT EXISTS idx_audit_logs_firm_user 
    ON public.audit_logs (firm_id, user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id 
    ON public.audit_logs (user_id);

COMMENT ON TABLE public.audit_logs IS
    'Insert-only workspace audit trail. Scoped by firm_id = workspace anchor.';
