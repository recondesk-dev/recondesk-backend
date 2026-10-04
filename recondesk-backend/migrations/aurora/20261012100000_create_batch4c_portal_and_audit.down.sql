-- Migration: 20261012100000_create_batch4c_portal_and_audit.down.sql
-- Rollback Batch 4C: Client Portal, Communication, User Preferences & Audit Logs

DROP TABLE IF EXISTS public.audit_logs CASCADE;
DROP TABLE IF EXISTS public.communication_logs CASCADE;
DROP TABLE IF EXISTS public.uploaded_files CASCADE;
DROP TABLE IF EXISTS public.upload_requests CASCADE;
DROP TABLE IF EXISTS public.notification_preferences CASCADE;
