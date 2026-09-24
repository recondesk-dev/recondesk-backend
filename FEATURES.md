# ReconDesk — Feature Inventory

Code-backed map of the Next.js frontend (`recondesk-frontend/`) and FastAPI backend (`recondesk-backend/`). Status inferred from handlers, TODOs, feature flags, and UI copy.

---

## 1. Reconciliation Engine

### Bidirectional GSTR-2B ↔ Purchase Register Matching
- **What it does**: Multi-phase engine that pairs GSTR-2B invoices with purchase-register rows and buckets outcomes into matched, review, missed ITC, wrongful ITC, duplicates, and unmatched notes.
- **Where it lives**:
  - Backend: `app/services/reconciliation.py`, `matcher.py`, `matching_core.py`, `normalizer.py`, `vendor_name_matcher.py`, `app/matching/engine.py`, `generic_matcher.py`, `app/worker/reconciliation_task.py`, `app/services/reconciliation_outcomes.py`, `reconciliation_payload_store.py`
  - Frontend: `app/(dashboard)/reconcile/runs/[run_id]/results/page.tsx`, `components/reconcile/ResultsUi.tsx`
- **Key logic**: Production 2B↔PR matcher emits **L1–L4 then L6** (there is no L5 outcome on this path). Tolerances: `AMOUNT_TOLERANCE_L1_PAISE=100` (₹1), L2 1%/7d, L3 5%/30d. **L1** = same GSTIN + raw-identical invoice + amount/date/tax OK → clean match. **L2** = normalized/format-variant invoice (zero fin. delta = clean; else review). **L3** = identity with larger amount/date/tax drift → review. **L4** = same PAN / different GSTIN → `GSTIN_MISMATCH`, never auto-claim. **L6** = no pair match. Near-miss fuzzy/TYPO/`TYPO_MISMATCH` runs in Phase 2/3 as **review** (not a match level). The old `L5_PROBABLE` decision path was removed as dead code; an L5 tier still exists only in `generic_matcher` (unused for production 2B↔PR). Phases: CN/DN quarantine → duplicate prepass → chunk match → orphan/fuzzy/wrongful resolution. Vendor-name stub-mismatch guard blocks weak L1 name matches.
- **APIs/DB touched**: `POST /api/reconciliation/start`, `GET /api/reconciliation/status/{run_id}`, `/api/reconcile/runs…` (summary, matched, itc, risk, late-matches, confidence, finalize, retry, delete); wizard `POST /api/runs/{id}/start`. Tables: `reconciliation_run`, `gstr_records` / `gstr2b_invoices`, `pr_records` / `purchase_register_invoices`, `reconciliation_results` (JSONB), `job_logs`.
- **Status**: complete

### Decision Layer (WHAT / WHY / NEXT)
- **What it does**: Enriches every outcome row with CA-facing structured guidance and action states (claim / follow_up / escalate / ignore).
- **Where it lives**:
  - Backend: `app/decisions/layer.py`, `app/services/decision_templates.py` (applied in worker via `populate_decisions` / `populate_review_decisions`)
  - Frontend: `components/reconcile/DecisionInvoiceCard.tsx`, decision UI in results page + `ResultsUi.tsx`
- **Key logic**: Templates keyed by rule (`L1_EXACT`, `L2_NORMALIZED`, `L2_AMOUNT_DIFF`, `L3_AMOUNT_DIFF`, `L4_INVOICE_NUM`, `MISSED_ITC`, `WRONGFUL_ITC`, `RULE37_*`, `BLOCKED_CREDIT*`, `LATE_FILING`, `REVIEW_*`, `DUPLICATE_ENTRY`, …). No `L5_PROBABLE` template. Bulk status via optimistic local map + patch.
- **APIs/DB touched**: Embedded in reconcile list/summary/export payloads; `PATCH /api/reconcile/records/bulk-update`. Stored in `reconciliation_results.payload`.
- **Status**: complete

### Diff / Field Comparison View
- **What it does**: Field-by-field GSTR vs PR comparison (amounts highlighted) with “Why?” diagnostics (matched/differed fields, normalized invoice pairs).
- **Where it lives**: Inline in `results/page.tsx` (`ComparedFieldsPanel`, `ComparedFieldsAccordionRow`, `WhyRationaleButton`, `DecisionDiagnosticsBlock`)
- **Key logic**: Uses `compared_fields` / decision metadata on rows — no separate endpoint.
- **APIs/DB touched**: Row payloads from matched/itc/risk list endpoints.
- **Status**: complete

### Auto-Approve High-Confidence Review
- **What it does**: End-of-run promotion of review rows above a firm confidence threshold (default 95%) into Matched with `auto_approved=True`.
- **Where it lives**:
  - Backend: `app/services/auto_approve.py`
  - Frontend: `app/(dashboard)/settings/reconciliation/page.tsx`
- **Key logic**: Threshold stored on `user_profiles`; applied after engine completes.
- **APIs/DB touched**: `PATCH /api/users/auto-approve-threshold`; read via `GET /api/v1/auth/me`. Table: `user_profiles`.
- **Status**: complete

### Carry-Forward / Late Matches / Amendments / Credit Notes
- **What it does**: Re-enters prior-period unmatched PR lines; flags late filing; links amendments; quarantines CN/DN and nets ITC.
- **Where it lives**: `app/services/carry_forward.py`, `late_filing_tracker.py`, `amendment_handler.py`, `credit_note_handler.py`; results tabs for late-matches / unmatched notes
- **Key logic**: Carry-forward upserts tracking rows per client; CN/DN excluded from primary invoice matching (see CDN stub below).
- **APIs/DB touched**: `GET …/late-matches`, ITC/risk buckets. Tracking + payload on `reconciliation_run` / results JSON.
- **Status**: complete

### Credit/Debit Note (CDN) Matching Engine & Quarantine
- **What it does**: Matches purchase register credit and debit notes against GSTR-2B CDNR/CDNRA records via direct note number, original invoice reference (Pathway C), and date/amount tolerances. Unmatched notes remain quarantined to avoid distorting invoice match rates and are surfaced in a dedicated audit tab and Excel export.
- **Where it lives**: Results tab `unmatched_notes` in `results/page.tsx`; backend `app/services/cdn_reconciliation.py`, `reconciliation_outcomes.py`, `reconcile_export_workbook.py`, `gstr2b_parser.py`, `purchase_register_parser.py`, `gstr2b_excel.py`.
- **Key logic**: Multi-pathway matching (direct note match, original invoice cross-reference, fuzzy date/amount); accounting negative ERP sign normalization; unmatched notes surfaced with supplier follow-up action recommendations.
- **APIs/DB touched**: Reconcile run payload / outcomes (`category=unmatched_notes`), `/summary` (`matched_notes_count`, `unmatched_notes_count`), Excel export ("Unmatched Notes" worksheet).
- **Status**: complete

### Rule 37 (180-Day Payment / ITC Reversal)
- **What it does**: Tracks unpaid/partially-paid PR invoices past invoice_date+180; surfaces warnings, overdue, paid-late; lets CAs mark settled (with TDS/payment coverage).
- **Where it lives**:
  - Backend: `app/services/rule37_tracker.py`, `rule37_alert_scan.py` (lifespan), `invoice_results_sync.py`, routes in `reconciliation_api.py`
  - Frontend: `Rule37SummarySection.tsx`, `Rule37MarkPaidModal.tsx`, `lib/rule37Summary.ts`, results Rule 37 tab
- **Key logic**: Statuses `OVERDUE_UNPAID`, `WARNING_30/60_DAYS`, `PAID_LATE`, `PENDING_VERIFICATION`, `OK`. Skip if ITC not claimed; blank payment past deadline → pending verification with **0** at-risk; **proportionate ITC reversal** for partial payments; optional `itc_claimed_period` for interest proxy in audit observations (Rule 37(3) 18% p.a.). Background alert scan in app lifespan.
- **APIs/DB touched**: `GET …/rule37`, `…/rule37/summary`, `PATCH …/rule37/{record_id}`, legacy `POST /api/reconciliation/runs/{id}/rule37/{pr_id}/resolve`. Tables: `rule37_actions`, alert prefs/dedup migrations, `reconciliation_results`.
- **Status**: complete (DEVLOG still lists older cross-period persistence TODOs; proportional partial payment is implemented)

### Section 17(5) Blocked Credit (Advisory)
- **What it does**: Warns on HSN chapters commonly restricted under §17(5); never auto-blocks ITC; feeds Decision Layer + IMS reject recommendation.
- **Where it lives**:
  - Backend: `app/services/blocked_credit_checker.py`, `app/rules/itc.py`, decision templates `BLOCKED_CREDIT*`
  - Frontend: results Section 17(5) tab
- **Key logic**: Chapters `8703`, `2106`, `9963`, `9972`, `9995`, `9954`, `9993` with category + usage/exempt notes; HSN from invoice top-level or `items[]`.
- **APIs/DB touched**: `GET /api/reconcile/runs/{run_id}/section17`; also in risk/export/observations. In payload (no dedicated table).
- **Status**: complete (advisory only)

### IMS Status Overlay
- **What it does**: Fetches Invoice Management System statuses from Sandbox/GSP and overlays them onto GSTR rows by (supplier GSTIN, normalized invoice).
- **Where it lives**: `app/services/ims_overlay.py`, `sandbox_gst_client.py`, worker `try_fetch_ims_status_map_for_client`; `components/clients/ConnectGstnModal.tsx`
- **Key logic**: Non-blocking overlay during/after reconcile; terminal IMS statuses skip further action.
- **APIs/DB touched**: `POST /api/clients/{id}/gstn/fetch-ims`. Tokens on `client_gstins`.
- **Status**: complete

### IMS Action Recommendations (Phase 1)
- **What it does**: Suggests accept / reject / hold per invoice from outcome category + real confidence + Rule 37 + §17(5); never writes to GSTN.
- **Where it lives**:
  - Backend: `app/ims/ims_recommendation.py`, `ims_run_service.py`
  - Frontend: `ImsActionPanel.tsx`, `imsActionLogic.ts`
- **Key logic**: Blocked credit → reject; active Rule 37 → hold; high-confidence matched (≥90%) → accept; amount mismatch / low confidence → hold; terminal IMS status skipped. UI never auto-fetches on mount (explicit Load).
- **APIs/DB touched**: `GET /api/reconcile/runs/{run_id}/ims/recommendations` (+ `/api/v1/reconcile/…`).
- **Status**: complete

### IMS Confirmed Writeback + Atomic Claim (Phase 2)
- **What it does**: Explicit CA confirm (`confirmed=true` + typed count) maps hold→GSTN `pending`, saves via Sandbox, polls dual-status until terminal confirmed/failed/unclear.
- **Where it lives**: `app/ims/ims_writeback_client.py`, `ims_action_store.py`, `app/routers/ims_actions.py`; frontend IMS panel confirm + poll
- **Key logic**: Idempotent claim RPC `claim_ims_action_submission` — INSERT ON CONFLICT DO NOTHING; reclaim `failed` or stale `claiming` >5m. Hold-to-commit + expected-count gate on UI.
- **APIs/DB touched**: `POST …/ims/actions/confirm`, `GET …/ims/actions/status?reference_id=`. Table: `ims_action_submissions`. Migrations: `20260727190000_ims_action_claim_rpc.sql`, `20260728120000_ims_claim_stale_reclaim.sql`.
- **Status**: complete — recommend + claim/writeback/poll + post-action GSTR-2B overlay sync (POST /runs/{run_id}/ims/sync) complete

### GSTR-3B vs Books ITC Check (Per Run)
- **What it does**: Compares run ITC buckets to uploaded/parsed GSTR-3B figures; surfaces Rule 88D / DRC-01C threshold context.
- **Where it lives**:
  - Backend: `app/services/gstr3b_reconciliation.py`
  - Frontend: `Gstr3bSummaryView.tsx`, `Gstr3bCheckPanel.tsx`, `app/.../runs/[run_id]/gstr3b/page.tsx`, results `gstr3b` tab
- **APIs/DB touched**: `POST/GET /api/reconcile/runs/{run_id}/gstr3b`. Stored on run/payload (`20260605120000_gstr3b_reconciliation.sql`).
- **Status**: complete

### GSTR-1 ↔ Sales Register Reconciliation
- **What it does**: Sales-side match of Sales Register ↔ GSTR-1 with mismatch codes G1M1–G1M10; optional GSTR-1 vs 3B liability tie-out and Table 13 docs.
- **Where it lives**:
  - Backend: `app/routers/gstr1_reconcile.py`, `app/rules/gstr1_mismatch_rules.py`, `app/reconciliation/gstr1_vs_3b.py`, `app/services/gstr1_run_store.py`, `app/matching/generic_matcher.py`
  - Frontend: `reconcile/gstr1/new/page.tsx`, `…/results/page.tsx`, `Gstr1ResultsView.tsx`, `Gstr1TieOutPanel.tsx`, `Gstr1DocumentsIssuedPanel.tsx`, `lib/gstr1Reconcile.ts`, `gstr1ReconcileExport.ts`
- **Key logic**: Sales buckets: Matched · Review · Missing in GSTR-1 · Extra in GSTR-1 · GSTR-1 vs 3B · Table 13 · Diagnostics.
- **APIs/DB touched**: `POST /api/gstr1-reconcile`, `GET …/runs`, `GET …/runs/{id}`. Table: `gstr1_reconciliation_run`.
- **Status**: complete

### GSTR-1A Window / Mark Filed
- **What it does**: Shows GSTR-1A amendability window for a period and lets CA mark filed.
- **Where it lives**:
  - Backend: `app/rules/gstr1a_eligibility.py`, `app/services/gstr1a_period_actions.py`
  - Frontend: `reconcile/gstr1/gstr1a/page.tsx`, `Gstr1aPeriodSummaryView.tsx`, `Gstr1aWindowBadge.tsx`, `Gstr1aMarkFiledModal.tsx`
- **APIs/DB touched**: `GET/PATCH …/gstr1-reconcile/runs/{id}/gstr1a-filed`. Table: `gstr1a_period_actions`.
- **Status**: complete

### GSTR-9C ITC FY Rollup
- **What it does**: Client-level FY rollup of ITC figures to support GSTR-9C workpapers.
- **Where it lives**:
  - Backend: `app/services/gstr9c_itc_fy_rollup.py`
  - Frontend: `clients/[id]/gstr9c/page.tsx`, `Gstr9cItcFyRollupPanel.tsx`
- **APIs/DB touched**: `GET /api/reconcile/clients/{id}/gstr9c-itc-fy`
- **Status**: complete

### Rules Catalogue (Documentation Registry)
- **What it does**: Read-only MAT_/ITC_/… rule definitions for UI docs — not the live matcher.
- **Where it lives**: `app/rules/*`, `app/routers/rules.py`
- **APIs/DB touched**: `GET /api/rules/summary|list|{id}`
- **Status**: complete (catalogue; some MAT_011 doc text may drift vs engine)

### Run Finalize + Confidence Summary
- **What it does**: Finalize checklist (incl. unresolved Rule 37 pre-check), confidence breakdown, delete/retry runs.
- **Where it lives**: results page finalize flow; `reconciliation_api.py`, `invoice_results_sync.count_unresolved_rule37`
- **APIs/DB touched**: `POST …/finalize`, `GET …/confidence-summary`, `POST …/retry`, `DELETE` run. Table: `reconciliation_run`.
- **Status**: complete

### Reconciliations List
- **What it does**: Cross-client run list with type filter (2B / 1 / 3B), status, deep-links.
- **Where it lives**: `app/(dashboard)/reconciliations/`, `/runs` redirects here
- **APIs/DB touched**: `GET /api/reconcile/runs`
- **Status**: complete

### Run-Level Vendor Risk Aggregation
- **What it does**: Groups ITC-at-risk by supplier for a single run.
- **Where it lives**: `app/(dashboard)/reconcile/runs/[run_id]/vendors/page.tsx`, `lib/groupBySupplier.ts`, `SupplierGroupView.tsx`
- **APIs/DB touched**: summary + risk list; client-side grouping
- **Status**: complete

### DRC-01B Reply Draft
- **What it does**: Client-side modal to draft reply narratives from reason stubs + ARN/amount fields.
- **Where it lives**: `Drc01bReplyDraftModal.tsx`, `lib/drc01bReplyDraft.ts`
- **APIs/DB touched**: None (local draft tooling only)
- **Status**: complete (local tooling; no GSTN submit)

### Mismatch Notes
- **What it does**: Per-record CA notes on GSTR/PR side of a run.
- **Where it lives**:
  - Backend: `app/routers/notes.py`
  - Frontend: notes drawer on results; proxy `app/api/notes/[...path]/route.ts`
- **APIs/DB touched**: `POST/GET /api/notes/{record_id}`, `PATCH/DELETE /api/notes/entry/{note_id}`. Table: `mismatch_notes`.
- **Status**: complete

### Audit Observations
- **What it does**: Severity-ranked observation list aggregating GSTR-1 mismatch codes + Rule 37 / §17(5) / GSTR-1-vs-3B with ₹ impact.
- **Where it lives**:
  - Backend: `app/audit/observation_rules.py`, `observation_builder.py`, `app/routers/audit_observations.py`
  - Frontend: `components/AuditObservationsPanel.tsx`, proxy `app/api/audit-observations/[...path]/route.ts`
- **Key logic**: Read-only; does not re-run matching.
- **APIs/DB touched**: `GET /api/audit-observations/{run_id}`
- **Status**: complete

### Legacy Reconciliation Jobs / PDF Reports
- **What it does**: Older job-model routes and PDF generation against `reconciliation_jobs` / `reconciliation_rows`.
- **Where it lives**: `app/routers/reconciliation.py` (legacy), `app/routers/reports.py`, `app/services/report_service.py`
- **APIs/DB touched**: `/api/v1/reconciliation/jobs…`, `GET /api/v1/reports/reconciliation/{job_id}/pdf`
- **Status**: legacy / likely stale vs current `reconciliation_run` flow

---

## 2. Data Import/Export

### Reconciliation Import Wizard
- **What it does**: Guided create-run → signed upload → GSTR/PR complete → sanity → column mapping → start/cancel/retry with status poll.
- **Where it lives**:
  - Backend: `app/routers/reconciliation_import_wizard.py`, `app/services/reconciliation_import_wizard/{wizard_service,state_machine}.py`, `sanity.py`
  - Frontend: `app/(dashboard)/reconcile/[client_id]/new/page.tsx`, `TallyRegisterImportHints.tsx`
- **Key logic**: SHA-256 integrity, R2 signed uploads, register-type detection (purchase vs sales), acknowledgment gates, direct-backend status poll (avoids Vercel 300s timeout).
- **APIs/DB touched**: `/api/runs`, `/api/runs/{id}/…` (uploads, sanity, mapping, start, status, retry, cancel). Tables: `reconciliation_run` wizard columns (`20260428120000_reconciliation_import_wizard.sql`), R2 keys.
- **Status**: complete

### Purchase Register / GSTR-2B File Import
- **What it does**: Upload+parse Excel/CSV/JSON into GSTR and PR record tables with sanity checks.
- **Where it lives**: `app/routers/import_router.py`, `upload.py`, parsers under `app/parsers/*` (`gstr2b_parser`, `gstr2b_excel`, `purchase_register_parser`, `tally_register`, `excel_parser`, `csv_parser`, `file_router`, …)
- **APIs/DB touched**: `POST /api/import/gstr2b`, `/purchase-register`, `GET /status/{run_id}`; `POST /api/v1/upload/file|presign|purchase-register`, `/upload/presigned-url`. Tables: `gstr_records`, `pr_records`, `reconciliation_run`.
- **Status**: complete

### PR Column Mapping
- **What it does**: Detect, validate, and persist client-specific PR column → standard-field maps for reuse.
- **Where it lives**:
  - Backend: `app/routers/pr_upload.py`, `app/services/client_import_mapping.py`
  - Frontend: wizard mapping step; `clients/[id]/import-mapping/page.tsx`
- **APIs/DB touched**: `POST /api/pr-upload/detect-columns|validate-for-upload`, mapping CRUD `/api/pr-upload/mapping/{client}`. Table: `client_import_mappings`.
- **Status**: complete

### Register Type Detection
- **What it does**: Detects whether an uploaded register is purchase vs sales (Tally/Excel heuristics).
- **Where it lives**: `app/routers/register_upload.py`; used by import wizard + GSTR-1 flow
- **APIs/DB touched**: `POST /api/register-upload/detect-type`
- **Status**: complete

### GSTN OTP + GSTR-2B Autofetch
- **What it does**: Connect client GSTIN via OTP; fetch GSTR-2B (and IMS) for a period into the import path.
- **Where it lives**:
  - Backend: `app/integrations/gstr2b_autofetch.py`, `app/routers/gstr2b_autofetch_routes.py`, `app/services/gst_fetch/token.py`
  - Frontend: `components/clients/ConnectGstnModal.tsx`
- **APIs/DB touched**: `POST /api/clients/{id}/gstn/send-otp|verify-otp|fetch|fetch-ims`. Table: `client_gstins` (GSTN tokens).
- **Status**: complete

### Generic GST Return Fetch (1 / 2A / 3B) → R2
- **What it does**: Downloads GSTR-1 / 2A / 3B sections to Cloudflare R2 and logs fetches.
- **Where it lives**: `app/services/gst_fetch/{gstr1,gstr2a,gstr3b,_http,token}.py`, `app/routers/gst_fetch_routes.py`
- **APIs/DB touched**: `POST /api/fetch/{gstr1|gstr2a|gstr3b}`. Table: `gst_fetch_log`; R2 storage.
- **Status**: complete

### Advanced Export + Workbook Exports
- **What it does**: Filtered multi-sheet XLSX/PDF advanced export with preview counts; also ITC/risk CSV and reconcile Excel workbook; client-side jsPDF report helpers.
- **Where it lives**:
  - Backend: `app/routers/export.py`, `advanced_export_*`, `reconcile_export_workbook.py`, `followup_audit_export.py`
  - Frontend: `AdvancedExportPanel.tsx`, `lib/reconciliationReportPdf.ts`, `reconciliationReportData.ts`, `download.ts`
- **APIs/DB touched**: `POST /api/export/advanced` (preview|xlsx|pdf); `GET …/export/excel|itc|risk`
- **Status**: complete

### Manage Data (Raw File Admin)
- **What it does**: List/download/soft-delete raw GSTR-2B/PR files for runs (admin-gated in nav).
- **Where it lives**:
  - Backend: `app/routers/manage_data.py`
  - Frontend: `manage-data/page.tsx`, `ManageDataPageContent.tsx`
- **APIs/DB touched**: `/api/v1/manage-data`, delete, download URL. R2 + run file metadata.
- **Status**: complete

### Public Client Upload Page
- **What it does**: Unauthenticated tokenized upload for client-requested files; multipart to signed URL.
- **Where it lives**: `app/upload/[token]/page.tsx`, `UploadPageClient.tsx`; communication center generates links
- **APIs/DB touched**: Supabase `upload_requests`, `uploaded_files`; signed URL against backend `API_URL`
- **Status**: complete — CA firm branding, client GSTIN entity box, live upload progress, and digital receipts active

### Sales / GSTR-1 / GSTR-3B Parsers
- **What it does**: Parse sales register, GSTR-1, GSTR-3B workbooks/JSON for reconcile and filing flows.
- **Where it lives**: `app/parsers/sales_register_parser.py`, `gstr1_parser.py`, `gstr3b_parser.py`
- **APIs/DB touched**: Used by GSTR-1 reconcile + filing readiness/upload paths
- **Status**: complete

---

## 3. Filing

### Taxpayer Filing Session (OTP)
- **What it does**: Generate/verify OTP, refresh, logout for GSTN filing sessions (shared for GSTR-1/3B; intended for IMS).
- **Where it lives**:
  - Backend: `app/routers/filing.py`, `app/filing/filing_store.py`, `sandbox_filing_client.py`
  - Frontend: `components/filing/GstnSessionPanel.tsx`
- **APIs/DB touched**: `POST /api/filing/session/otp/generate|verify`, `/refresh`, `/logout`. Table: `filing_sessions`.
- **Status**: complete

### GSTR-1 Save → Proceed → EVC → File
- **What it does**: Readiness from sales register → pending review queue → external input gaps → save to GSTN → proceed → EVC OTP → file.
- **Where it lives**:
  - Backend: `gstr1_filing_mapper.py`, `gstr1_orchestrator.py`, `gstr1_thresholds.py`, `gstr1_external_input.py`, `filing.py`
  - Frontend: `filing/gstr-1/page.tsx`, `[period]/page.tsx`; `FilingReadinessSummary`, `PendingReviewQueue`, `ExternalInputGapsPanel`, `SaveToGstnAction`, `EvcAndFilePanel`
- **Key logic**: Feature flag always on for GSTR-1; threshold-based readiness; mapper builds GSTN payload sections.
- **APIs/DB touched**: `/api/filing/gstr-1/{period}/readiness(|-upload)|save(|-upload)|status|proceed|summary|evc-otp|file`; `GET /api/filing/features`. Table: `filing_runs` (`return_type=gstr-1`).
- **Status**: complete

### GSTR-3B Save → Offset → EVC → File
- **What it does**: Get details/ledger, CA-confirmed save body, offset liability (stale-check / period-locked), EVC, file; draft suggestions for osup_det / itc_oth.
- **Where it lives**:
  - Backend: `gstr3b_offset.py`, `gstr3b_suggestions.py`, nested `gstr3b_router` in `filing.py`
  - Frontend: `filing/gstr-3b/`, `components/filing/gstr3b/*` (FiguresForm, OffsetLiabilityGate, OffsetDeliberateConfirm, OffsetStaleBanner, PeriodLockedProof, DraftSuggestionBanner, …)
- **Key logic**: Typed offset confirm amount; 409 handling for stale/period-locked. Gate: `settings.gstr3b_filing_enabled` — **default OFF in production**, ON in local unless overridden.
- **APIs/DB touched**: `/api/filing/gstr-3b/{period}/details|ledger-balance|suggestions/*|offset-preview|save|status|offset|evc-otp|file`. Table: `filing_runs`.
- **Status**: complete code; **production-gated (in-progress for live rollout)**

### Filing Feature Flags
- **What it does**: Exposes which filing flows are enabled to the UI.
- **Where it lives**: `app/routers/filing.py`, `app/config.py`; frontend `filingApi.features`
- **APIs/DB touched**: `GET /api/filing/features` → `{gstr1_filing_enabled, gstr3b_filing_enabled}`
- **Status**: complete

---

## 4. Client & Firm Management

### Client GSTIN CRUD & Assignment
- **What it does**: List/search clients, add validated GSTIN, assign staff, open per-client workspace.
- **Where it lives**:
  - Backend: `app/routers/clients.py`, `app/services/gstin_verification.py`, `firm_access.py`
  - Frontend: `clients/page.tsx`, `ClientsPageContent.tsx`, `clients/[id]/page.tsx` + layout tabs, `components/ui/GstinInput.tsx`
- **APIs/DB touched**: validate-gstin, list/create/get/patch/assign/delete; `POST /api/gstin/verify`. Table: `client_gstins`.
- **Status**: complete

### Client Detail Workspace
- **What it does**: Per-client overview (runs history, ITC trend, GSTN connect CTA) with tabs for command-center, gstr9c, follow-up, communication, import-mapping.
- **Where it lives**: `clients/[id]/page.tsx`, `layout.tsx`
- **APIs/DB touched**: `clientsApi.get`, reconcile runs, team members, `listGstr1Runs`
- **Status**: complete

### Client ITC Command Center & Statutory Timelines
- **What it does**: Executive client-level command center with live Indian GST statutory deadline countdown timers (GSTR-1 on 11th, GSTR-2B on 14th, GSTR-3B on 20th), filing cycle phase tracker, net claimable Table 4 ITC position card, CA operational quick actions bar, and prioritized exception work items queue.
- **Where it lives**:
  - Backend: `app/routers/clients.py` (`GET /{client_id}/command-center`), `app/services/itc_command_center_service.py`
  - Frontend: `app/(dashboard)/clients/[id]/command-center/page.tsx`, `components/clients/ItcCommandCenterView.tsx`, `StatutoryCountdownCard.tsx`, `CommandCenterQuickActions.tsx`, `CumulativeItcExposureCard.tsx`, `lib/statutoryCompliance.ts`
- **Key logic**: IST-based deadline computation; period-specific compliance evaluation (on-time vs overdue); Net ITC claimable formula ($4A5 - 4B + 4D1$); Rule 88D (DRC-01C) & Rule 37 180-day automated safeguard alerts; 1-click launchpad to new reconcile run, client document requests, and reversal ledgers.
- **APIs/DB touched**: `GET /api/clients/{id}/command-center`
- **Status**: complete

### Supplier Follow-up Letters + Audit Trail
- **What it does**: Generate supplier follow-up letters from results; log audits; view run + client history; export.
- **Where it lives**:
  - Backend: follow-up audit routes in `reconciliation_api.py`, `followup_audit_export.py`
  - Frontend: `SupplierFollowupLetterModal.tsx`, `SupplierFollowupAuditLogPanel.tsx`, `SupplierFollowupAuditTable.tsx`, `ClientFollowupHistoryPanel.tsx`; `clients/[id]/follow-up`; `lib/supplierFollowupLetter.ts`, `followupAudit.ts`
- **APIs/DB touched**: `POST/GET …/runs/{id}/supplier-followup/audit`, `GET …/clients/{id}/supplier-followup/audit`. Table: `supplier_followup_audit`.
- **Status**: complete

### Vendor Firm-Wide Risk Scorecard
- **What it does**: Precomputed firm-scoped supplier risk (mismatch rate, open Rule 37, §17(5), late filing, PR-only — explicitly not non-filer). Rebuild on run complete + daily throttle.
- **Where it lives**:
  - Backend: `app/services/supplier_compliance_scorecard.py`, `app/routers/vendors.py`, lifespan in `main.py`
  - Frontend: `vendors/page.tsx`, `VendorsPageContent.tsx`, `vendors/[supplier_gstin]/page.tsx`, `RiskScoreBadge.tsx`
- **APIs/DB touched**: `GET /api/vendors/scorecard`, `/scorecard/{supplier_gstin}`. Tables: `supplier_compliance_by_client`, `supplier_compliance_summary`.
- **Status**: complete

### Vendor Intelligence / Chronic Risks
- **What it does**: Historical supplier patterns for a client; chronic-risks endpoint.
- **Where it lives**: `app/services/vendor_intelligence.py`, `app/routers/intelligence.py`, clients `GET …/chronic-risks`
- **APIs/DB touched**: `GET /api/intelligence/suppliers/{client_gstin_id}`; chronic-risks on clients router
- **Status**: complete

### Communication Center + Upload Links
- **What it does**: Create tokenized upload requests; log communications; list uploaded files.
- **Where it lives**: `clients/[id]/communication/page.tsx`, `CommunicationCenter.tsx`, `GenerateUploadLinkModal.tsx`
- **APIs/DB touched**: Supabase `upload_requests`, communication logs, `uploaded_files`
- **Status**: complete

### Team Invites & Members
- **What it does**: Invite admin/staff, list/remove members; accept invite via token link (invited users forced `role=staff`).
- **Where it lives**:
  - Backend: `app/routers/team.py`
  - Frontend: `settings/team/page.tsx`, `app/team/accept/[token]/page.tsx`
- **APIs/DB touched**: `GET/POST/DELETE /api/team/members|invite`, `POST /api/team/accept/{token}`. Table: `team_members`.
- **Status**: complete

---

## 5. Auth & Roles

### Supabase Auth + JWT API Access
- **What it does**: Signup, login (throttled), logout, `/me`, password reset; middleware enforces session + onboarding; access-token cookie bridge for API calls.
- **Where it lives**:
  - Backend: `app/routers/auth.py`, `app/auth.py` (JWKS), `app/models/user.py`
  - Frontend: `app/(auth)/*`, `app/auth/*`, `middleware.ts`, `lib/supabase/*`, `lib/auth-profile.ts`, `lib/auth-validation.ts`, `app/api/auth/access-token/route.ts`
- **Key logic**: Roles `admin` (firm owner) vs `staff` (invited); access via `firm_access.py` + `client_gstins.firm_owner_id` / `assigned_to`. Cookie `rd_ob` for onboarding skip.
- **APIs/DB touched**: `/api/v1/auth/…`, webhook `/api/auth`; Supabase Auth. Table: `user_profiles`.
- **Status**: complete

### User Profile Settings
- **What it does**: Update name, phone, firm, ICAI, firm GSTIN, city.
- **Where it lives**: `settings/profile/page.tsx`, `lib/profile-validation.ts`; backend `app/routers/users.py`
- **APIs/DB touched**: `PATCH /api/users/profile`, `authApi.me`. Table: `user_profiles`.
- **Status**: complete

### Firm Access Control
- **What it does**: Multi-tenant scoping so staff only see assigned clients / firm data.
- **Where it lives**: `app/services/firm_access.py` (used across routers)
- **APIs/DB touched**: Cross-cutting; `client_gstins`, `team_members`, `user_profiles`
- **Status**: complete

---

## 6. Onboarding/Product Tour

### First-Run Onboarding Wizard
- **What it does**: 4-step first-run: add GSTIN client → assign → upload files → celebrate with run summary + Excel export.
- **Where it lives**: `app/onboarding/page.tsx`, `celebrate/page.tsx`, `layout.tsx`, `lib/onboarding-cookie.ts`; backend onboarding-complete on auth/users
- **APIs/DB touched**: `clientsApi`, `teamApi`, import/reconcile start, `POST/PATCH onboarding-complete` (`/api/v1/auth/onboarding-complete` or `/api/users/onboarding-complete`)
- **Status**: complete

### Landing “Product Tour” (Marketing Only)
- **What it does**: Animated multi-screen dashboard preview labeled “Product tour” on the marketing landing page.
- **Where it lives**: `components/public/LandingDashboardPreview.tsx`, `app/(landing)/page.tsx`
- **Key logic**: **No in-app guided tour** — `driver.js` is not a frontend dependency (orphan install may exist at monorepo root only).
- **APIs/DB touched**: None
- **Status**: complete as marketing mock; **interactive product tour not built**

---

## 7. Dashboard & UI

### Portfolio Dashboard
- **What it does**: Firm-wide client portfolio: stats, filters, priority scoring, return-period board, retry failed runs, attention items, ITC trend.
- **Where it lives**: `app/(dashboard)/dashboard/page.tsx`, `components/dashboard/*`, `lib/dashboard-portfolio.ts`, `lib/priority.ts`
- **Key logic**: Builds portfolio rows from clients + reconcile runs + team; client-side filter/sort/pagination; SWR cache keys under `DW`.
- **APIs/DB touched**: `GET /api/dashboard/summary`, `/api/clients`, `/api/reconcile/runs`, `/api/team/members`, retry run, `/api/v1/auth/me`
- **Status**: complete

### Dashboard Shell / Navigation
- **What it does**: Primary nav (Dashboard / Clients / Vendors / Reconciliations / Manage Data / Billing / Settings), profile menu, billing capacity badge.
- **Where it lives**: `components/layout/DashboardShellLayout.tsx`; settings hub `settings/page.tsx`
- **Key logic**: Legacy `Sidebar` / `Header` / `DashboardShell` exist but are **not** wired by `app/(dashboard)/layout.tsx`.
- **APIs/DB touched**: billing status for capacity badge
- **Status**: complete (legacy shell = dead code)

### Public / Legal / Pricing Pages
- **What it does**: Marketing landing, pricing, privacy, terms, refund, return, shipping, contact.
- **Where it lives**: `app/(landing)/`, `app/(public)/`, `app/(legal)/`, `components/public/*`, `MarketingPageLayout.tsx`
- **APIs/DB touched**: None (static/marketing)
- **Status**: complete

### Notification Preferences UI
- **What it does**: Email toggles for run completed, runs expiring, payment receipts, Rule 37 alerts.
- **Where it lives**: `settings/notifications/page.tsx`; backend `app/routers/notifications.py`
- **APIs/DB touched**: `GET/PUT /api/v1/notifications/preferences`
- **Status**: complete

---

## 8. Infra/Admin

### Celery Reconciliation Worker
- **What it does**: Async run execution: batched DB I/O, full engine + Rule 37 + blocked credit + IMS overlay + decisions + payload persist + scorecard hook + email notify.
- **Where it lives**: `app/worker/celery_app.py`, `reconciliation_task.py`, `tasks.py`, `app/celery_app.py`
- **APIs/DB touched**: Triggered by start endpoints; writes `reconciliation_run` / `reconciliation_results`
- **Status**: complete

### Health + Stuck-Job Watchdog
- **What it does**: `/health` probes Supabase + R2 (2s timeout); lifespan loop every 5m marks stuck MATCHING/PROCESSING/importing >15m as FAILED; also Rule 37 alert scan + supplier scorecard rebuild.
- **Where it lives**: `app/main.py`
- **APIs/DB touched**: `GET /health`; updates `reconciliation_run`
- **Status**: complete

### Cloudflare R2 Storage
- **What it does**: Object storage for uploads, GST fetches, manage-data downloads.
- **Where it lives**: `app/services/r2_service.py`; used by upload/import/fetch/manage_data
- **APIs/DB touched**: Presign/upload/download routes under `/api/v1/upload`, `/upload`, manage-data
- **Status**: complete

### GSTIN Subscription Billing (Razorpay)
- **What it does**: Plans Starter/Growth/Pro/Firm (GSTIN limits 25/60/100/100+); free 1 GSTIN (lifetime — removing does not free the slot) + 2 free runs; create-order / verify / webhook / history / receipt PDF / send-receipt / billing status.
- **Where it lives**:
  - Backend: `app/routers/payments.py`, `webhooks.py`, `app/services/billing_gate.py`, `billing_service.py`, `receipt_pdf.py`, `payment_idempotency.py`
  - Frontend: `billing/page.tsx`, `SubscriptionFeatures.tsx`, `lib/billing-checkout.ts`, Next proxies `app/api/billing/{create-order,verify-payment}`
- **APIs/DB touched**: `/api/payments/*`, `/api/billing/status`, `/api/v1/webhooks/razorpay`. Billing credit/subscription/payment tables; `idempotency_keys`.
- **Status**: complete

### Legacy Billing Plans Listing
- **What it does**: Older plan listing / order endpoint.
- **Where it lives**: `app/routers/billing.py`
- **APIs/DB touched**: `GET /api/v1/billing/plans`, `POST /api/v1/billing/order`
- **Status**: in-progress / legacy — explicit TODO to update Razorpay plan IDs

### Audit Action Log
- **What it does**: Firm activity trail of audited actions.
- **Where it lives**:
  - Backend: `app/routers/audit_logs.py`
  - Frontend: `settings/activity/page.tsx`, `ActivityLogPanel.tsx`, `lib/activityLog.ts`
- **APIs/DB touched**: `GET /api/audit-logs`. Table: `audit_logs`.
- **Status**: complete

### Admin Ops Digest
- **What it does**: Restricted ops digest for a configured admin user.
- **Where it lives**: `app/routers/admin.py`
- **APIs/DB touched**: `GET /api/admin/digest` (env `ADMIN_USER_ID` only)
- **Status**: complete

### Same-Origin Backend Proxy Layer
- **What it does**: Proxies reconcile/notes/audit-observations/reconciliation to Railway to avoid CORS / long browser timeouts; status polls can use `directBackend: true`.
- **Where it lives**: `lib/backendProxy.ts`, `lib/api.ts`; `app/api/{reconcile,reconciliation,notes,audit-observations}/[...path]/route.ts`
- **APIs/DB touched**: Proxies to FastAPI
- **Status**: complete

### KeepAlive / Warm Backend
- **What it does**: Periodic ping to keep backend warm (e.g. Railway idle).
- **Where it lives**: `components/KeepAlive.tsx`, `app/api/keepalive/route.ts`, `lib/keepalive.ts`
- **APIs/DB touched**: Health/keepalive endpoints
- **Status**: complete

### CI Test Workflow
- **What it does**: On push/PR to `main`, installs backend deps and runs pytest (incl. ground-truth silent-drop regressions).
- **Where it lives**: `.github/workflows/deploy.yml` (named “Run Tests”)
- **APIs/DB touched**: None (CI)
- **Status**: complete

### Observability (Sentry / Clarity / Rate Limits)
- **What it does**: Sentry + SlowAPI rate limits on FastAPI; Microsoft Clarity script on frontend.
- **Where it lives**: `app/main.py`; `components/ClarityScript.tsx`
- **APIs/DB touched**: External SaaS only
- **Status**: complete

### Email Notifications
- **What it does**: Welcome email, run-complete, Rule 37 alerts, payment receipts (gated by prefs).
- **Where it lives**: `app/services/email_service.py`, utils email helpers; wired from auth webhook, worker, Rule 37 scan, billing
- **APIs/DB touched**: Notification prefs; external SMTP/provider
- **Status**: complete

### Sandbox / GSP GST Client
- **What it does**: Shared HTTP client for GSTN sandbox operations (2B fetch, IMS, filing).
- **Where it lives**: `app/services/sandbox_gst_client.py`, `app/filing/sandbox_filing_client.py`
- **APIs/DB touched**: External Sandbox/GSP APIs
- **Status**: complete

---

## Partial / In-Progress Summary

| Feature | What’s done | What’s missing |
|--------|-------------|----------------|
| **IMS writeback & sync** | Recommend + confirm + atomic claim + dual-status poll + post-action GSTR-2B sync | Live portal production GSP rollout |
| **CDN / credit-note matching** | Bilateral 4-tier CDNR matching (REM-04) + quarantine list + UI tab | Fully automated |
| **GSTR-3B filing** | Full Save → Offset → EVC → File UI + API | Production flag off by default — live rollout gated |
| **In-app product tour** | Landing marketing carousel | No driver.js / guided in-app tour |
| **Legacy `/v1/billing`** | Plans/order stubs | Razorpay plan IDs TODO |
| **Legacy reports/jobs** | Old PDF/job routes | Superseded by `reconciliation_run` flow |
| **Public upload branding** | Token upload, CA firm branding, client GSTIN card, live progress, digital receipt | Complete |

---

## Key Tables (Supabase)

| Table | Purpose |
|-------|---------|
| `user_profiles` | Auth profile, role, billing limits, onboarding, auto-approve |
| `client_gstins` | Clients, GSTN tokens, assignment, firm_owner |
| `team_members` | Invites / staff |
| `reconciliation_run` | Run lifecycle, period, summary, wizard state |
| `gstr_records` / `gstr2b_invoices` | 2B invoice rows |
| `pr_records` / `purchase_register_invoices` | Purchase register rows |
| `reconciliation_results` | JSONB engine payload |
| `mismatch_notes` | CA notes |
| `rule37_actions` | Settlement actions |
| `ims_action_submissions` | IMS writeback idempotency |
| `filing_sessions` / `filing_runs` | Filing OTP + Save/File |
| `gstr1_reconciliation_run` | Sales-side runs |
| `gstr1a_period_actions` | GSTR-1A filed marks |
| `supplier_compliance_*` | Vendor scorecard |
| `supplier_followup_audit` | Follow-up trail |
| `client_import_mappings` | Saved PR column maps |
| `gst_fetch_log` | Auto-fetch audit |
| `audit_logs` | Action audit |
| `idempotency_keys` | Payment / API idempotency |
| `job_logs` | Import/job logs |
| `upload_requests` / `uploaded_files` | Client communication uploads |
| Billing credit / payment tables | Via billing migrations |
