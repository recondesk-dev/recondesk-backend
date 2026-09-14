-- Migration: 20260914140000_vendor_followup_work_item.sql
-- Description: Phase 5.3 Vendor Resolution & Communication
-- Extends vendor_followup_logs with work_item_id and message_body.

ALTER TABLE public.vendor_followup_logs
    ADD COLUMN IF NOT EXISTS work_item_id UUID REFERENCES public.itc_work_items(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS message_body TEXT;

CREATE INDEX IF NOT EXISTS idx_vendor_followup_work_item
    ON public.vendor_followup_logs(work_item_id);
