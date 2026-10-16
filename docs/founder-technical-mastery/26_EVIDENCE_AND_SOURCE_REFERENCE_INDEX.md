# Volume 26: Master Evidence & Source Reference Index

> **Document ID**: `RD-TECH-26`  
> **Author**: Chief Technology Officer & Principal Systems Architect  
> **Target Audience**: ReconDesk Founder, Technical Due Diligence Auditors, Institutional Investors, EF / YC Interviewers  
> **Repository Baseline**: `release/v1.5.2-rc1`  
> **Verification Mandate**: Zero hallucinations. Every claim is categorized by evidentiary standard and tied to exact file paths, line ranges, symbols, and test suites.

---

## 1. Evidentiary Classification Standards

To ensure absolute credibility during technical audits and investor due diligence, all architectural assertions in the ReconDesk Founder Mastery suite are assigned one of seven evidentiary levels:

1. **[VERIFIED IN SOURCE CODE]**: Direct inspection of committed application code in `recondesk-backend/` or `recondesk-frontend/`.
2. **[VERIFIED BY TEST]**: Proven by an automated, executable test in `recondesk-backend/tests/` or frontend unit test suites.
3. **[VERIFIED IN DEPLOYMENT CONFIGURATION]**: Confirmed via committed infrastructure definitions (`docker-compose.prod.yml`, `Caddyfile`, `amplify.yml`, `Dockerfile`).
4. **[DOCUMENTED BUT NOT VERIFIED]**: Described in internal markdown architecture docs or comments, but lacking direct runtime proof in the repository.
5. **[REPORTED HISTORICALLY]**: Documented in commit messages, dev logs, or previous sprint reviews (e.g., historical Supabase behavior).
6. **[INFERRED FROM IMPLEMENTATION]**: Logical architectural deduction based on how multiple interacting modules are structured.
7. **[UNKNOWN / REQUIRES PRODUCTION VERIFICATION]**: Operational parameters that depend on live AWS environment variables, DNS propagation, or cloud console settings.

---

## 2. Core Matching Engine & Algorithmic Invariants

| Architectural & Algorithmic Claim | Evidentiary Standard | Exact Code Reference | Symbols / Line Numbers | Verifying Test Suite |
| :--- | :---: | :--- | :--- | :--- |
| **Integer-Paise Monetary Precision** (1 INR = 100 Paise) | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/models/reconciliation.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/models/reconciliation.py) | `taxable_amount_paise`, `igst_paise`, `cgst_paise`, `sgst_paise`, Lines 251–255 | [`test_accuracy_suite.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_accuracy_suite.py) |
| **Document Type Semantic Gate** (Invoices $\neq$ Credit Notes) | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/services/matcher.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/matcher.py) | `are_document_types_compatible()`, Lines 2190–2202 | [`test_cdn_reconciliation.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_cdn_reconciliation.py) |
| **Tier 1 (L1) Exact Match Tolerances** (₹1.00 & 3 Days) | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/services/matcher.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/matcher.py) | `AMOUNT_TOLERANCE_L1_PAISE = 100`, `DATE_TOLERANCE_L1_DAYS = 3`, Lines 30–35 | [`test_accuracy_suite.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_accuracy_suite.py) |
| **Vendor Legal Name Guard** (Normalizes Pvt Ltd / Expands Abbreviations) | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/services/vendor_name_matcher.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/vendor_name_matcher.py) | `l1_vendor_name_ok()`, `vendor_name_similarity()`, Lines 24–28 | [`test_accuracy_fixes.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_accuracy_fixes.py) |
| **Period-Boundary Crossing Guard** (`PERIOD_BOUNDARY_DATE_MISMATCH`) | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/services/matcher.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/matcher.py) | `_crosses_gst_return_period()`, Lines 2384–2424 | [`test_amendment_reconciliation.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_amendment_reconciliation.py) |
| **Note-in-B2B Detection** (Routes misfiled Credit Notes to Review) | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/services/matcher.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/matcher.py) | `_RE_NOTE_IN_B2B`, Lines 56–58, 2449–2460 | [`test_cdn.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_cdn.py) |
| **Branch Variant & Prefix/Suffix Normalization** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/services/matcher.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/matcher.py) | `check_is_branch_variant()`, `normalize_invoice()`, Lines 98–105 | [`test_branch_suffix_safety.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_branch_suffix_safety.py) |
| **OCR Character Substitution Matrix** (`O` $\leftrightarrow$ `0`, `I` $\leftrightarrow$ `1`) | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/services/matcher.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/matcher.py) | `ocr_canonical_invoice()`, Lines 2287–2291 | [`test_advanced_parser_improvements.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_advanced_parser_improvements.py) |
| **Tier 5 (L5) Levenshtein Similarity Threshold** ($\ge 70\%$) | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/services/matcher.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/matcher.py) | `INVOICE_SIMILARITY_L5_MIN = 0.70`, Line 40 | [`test_accuracy_suite.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_accuracy_suite.py) |
| **RCM Conflict Detection** (Reverse Charge Mismatch) | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/services/statutory_eligibility.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/statutory_eligibility.py) | `detect_rcm_conflict()`, Lines 19–20 | [`test_rcm_reconciliation.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_rcm_reconciliation.py) |
| **Tax Head Structure Mismatch** (IGST vs CGST+SGST Conflict) | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/services/statutory_eligibility.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/statutory_eligibility.py) | `detect_tax_head_mismatch()`, Lines 21–22 | [`test_accuracy_suite.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_accuracy_suite.py) |

---

## 3. Asynchronous Execution & Background Worker Fleet

| Celery & Redis Reliability Claim | Evidentiary Standard | Exact Code Reference | Symbols / Line Numbers | Verifying Test Suite |
| :--- | :---: | :--- | :--- | :--- |
| **7 Isolated Domain Queues** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/worker/reliability.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/reliability.py) | `ALL_QUEUES`, Lines 22–38 | [`test_celery_reliability.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_celery_reliability.py) |
| **Late Acknowledgement & Worker Crash Re-Queue** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/worker/celery_app.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/celery_app.py) | `task_acks_late=True`, `task_reject_on_worker_lost=True`, Lines 43–44 | [`test_celery_worker_environment.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_celery_worker_environment.py) |
| **Task Routing Map** (`TASK_ROUTES`) | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/worker/reliability.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/reliability.py) | `TASK_ROUTES`, Lines 41–50 | [`test_celery_reliability.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_celery_reliability.py) |
| **Reconciliation Task Execution Limits** (Soft: 3600s, Hard: 3900s) | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/worker/reconciliation_task.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/reconciliation_task.py) | `soft_time_limit=_RECON_SOFT_LIMIT`, `time_limit=_RECON_HARD_LIMIT`, Lines 930–938 | [`test_celery_reliability.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_celery_reliability.py) |
| **Heartbeat Watchdog & Stuck Job Detector** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/main.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py) | `stuck_job_detector()`, `_stuck_job_tick()`, Lines 126–216 | [`test_celery_reliability.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_celery_reliability.py) |
| **Dead-Letter Failure Logging** (`record_failed_job`) | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/worker/reliability.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/reliability.py) | `record_failed_job()`, Lines 184–196 in `main.py` | [`test_celery_reliability.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_celery_reliability.py) |
| **Cloudflare R2 Payload Offloading (Sprint 2B)** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/services/reconciliation_payload_store.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/reconciliation_payload_store.py) | `save_reconciliation_results()`, Lines 43–47 | [`test_celery_reliability.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_celery_reliability.py) |

---

## 4. Database, Multi-Tenancy & Data Architecture

| Database & Tenancy Architecture Claim | Evidentiary Standard | Exact Code Reference | Symbols / Line Numbers | Verifying Test Suite |
| :--- | :---: | :--- | :--- | :--- |
| **PostgREST-to-Aurora Client Adapter** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/aurora_client.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/aurora_client.py) | `AuroraClient`, Lines 1–60 | [`test_aurora_client_parity.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_aurora_client_parity.py) |
| **SQLAlchemy Connection Pool Tuning** (`pool_size=20`, `recycle=1800`) | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/aurora.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/aurora.py) | `create_aurora_engine()`, Lines 76–102 | [`test_aurora_connection.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_aurora_connection.py) |
| **Multi-Tenant Hierarchy** (`user_profiles` $\rightarrow$ `client_gstins`) | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/models/tenancy.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/models/tenancy.py) | `UserProfile`, `ClientGSTIN`, `TeamMember`, Lines 31–250 | [`test_aurora_tenancy.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_aurora_tenancy.py) |
| **37 Sequential Alembic Migrations** | **[VERIFIED BY TEST]** | [`recondesk-backend/alembic/versions/`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/alembic/versions/) | 37 Migration Scripts, `20260417_*` to `20261006140000_*` | [`test_aurora_migration_runner.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_aurora_migration_runner.py) |
| **Startup Migration Automation** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/main.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py) | `_run_alembic_upgrade()`, Lines 297–344 | [`test_aurora_migration_runner.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_aurora_migration_runner.py) |
| **Startup Database Lock Detection** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/main.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py) | `_log_db_locks()`, Lines 260–285 | [`test_aurora_connection.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_aurora_connection.py) |

---

## 5. Authentication, Authorization & Identity

| Security & Identity Claim | Evidentiary Standard | Exact Code Reference | Symbols / Line Numbers | Verifying Test Suite |
| :--- | :---: | :--- | :--- | :--- |
| **Amazon Cognito User Pool Config** (`ap-south-1_nvlPYMvFh`) | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/config.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/config.py) | `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, Lines 88–95 | [`test_auth_signup_mx.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_auth_signup_mx.py) |
| **RS256 Public Key JWKS Verification with In-Memory Cache** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/auth.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/auth.py) | `_JWKS_CACHE`, `_JWKS_TTL_SEC = 3600.0`, Lines 68–74 | [`test_auth_signup_mx.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_auth_signup_mx.py) |
| **Fail-Closed Role Fallback** (`DEFAULT_FAIL_CLOSED_ROLE = "viewer"`) | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/models/roles.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/models/roles.py) | `DEFAULT_FAIL_CLOSED_ROLE`, Line 78 | [`test_aurora_tenancy.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_aurora_tenancy.py) |
| **7 Granular RBAC Practice Roles** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/models/roles.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/models/roles.py) | `Role` Enum, Lines 13–24 | [`test_aurora_tenancy.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_aurora_tenancy.py) |
| **Maker-Checker Statutory Authorization** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/models/client_authorizations.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/models/client_authorizations.py) | `ClientFilingAuthorization`, Lines 1–80 | [`test_client_filing_authorization.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_client_filing_authorization.py) |

---

## 6. Statutory GST Compliance & Rule Engines

| GST Tax Rule & Statutory Claim | Evidentiary Standard | Exact Code Reference | Symbols / Line Numbers | Verifying Test Suite |
| :--- | :---: | :--- | :--- | :--- |
| **Section 17(5) Blocked Credit Detection** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/services/blocked_credit_checker.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/blocked_credit_checker.py) | `check_blocked_credits()`, Lines 1–100 | [`test_blocked_credit_checker.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_blocked_credit_checker.py) |
| **Rule 37 180-Day Payment Alert Scanner** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/services/rule37_alert_scan.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/rule37_alert_scan.py) | `run_rule37_alert_scan()`, Lines 1–80 | [`test_accuracy_suite.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_accuracy_suite.py) |
| **Supplier Compliance Scorecard Daily Rebuild** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/services/supplier_compliance_scorecard.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/supplier_compliance_scorecard.py) | `run_scorecard_daily_rebuild()`, Lines 1–80 | [`test_accuracy_suite.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_accuracy_suite.py) |
| **GSTR-3B Table 4 Gate & Suggestions** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/filing/gstr3b_suggestions.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/filing/gstr3b_suggestions.py) | `compute_gstr3b_table4_suggestions()`, Lines 1–120 | [`test_accuracy_suite.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_accuracy_suite.py) |
| **GSTR-3B Irreversible Tax Offset Guard** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/config.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/config.py) | `gstr3b_filing_enabled`, Lines 271–280 | [`test_client_filing_authorization.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_client_filing_authorization.py) |
| **IMS Action Overlay & Status Mapping** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/services/ims_overlay.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/ims_overlay.py) | `apply_ims_status_to_matcher_rows()`, Lines 50–55 | [`imsActionLogic.test.ts`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-frontend/components/reconcile/imsActionLogic.test.ts) |

---

## 7. Cloud Infrastructure, Networking & Security Guards

| DevOps & Infrastructure Claim | Evidentiary Standard | Exact Code Reference | Symbols / Line Numbers | Verifying Test Suite |
| :--- | :---: | :--- | :--- | :--- |
| **Caddy 2 Automated HTTPS & HSTS Preload** | **[VERIFIED IN DEPLOYMENT CONFIGURATION]** | [`Caddyfile`](file:///Users/omkarkadam/Documents/ReconDesk/Caddyfile) | `Strict-Transport-Security "max-age=63072000"`, Lines 1–4 | [`test_caddy_health_check.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_caddy_health_check.py) |
| **Fail-Closed Staging Safety Guard** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/staging_guard.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/staging_guard.py) | `enforce_staging_safety()`, Lines 1–100 | [`test_celery_worker_environment.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_celery_worker_environment.py) |
| **Next.js Staging Compilation Gate** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-frontend/next.config.mjs`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-frontend/next.config.mjs) | `isStagingBuild`, Lines 84–98 | Build Pre-Flight Check |
| **Sentry PII Masking & Telemetry Scrubbing** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/filing/log_safety.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/filing/log_safety.py) | `sentry_scrub_event()`, `sentry_scrub_breadcrumb()`, Lines 1–100 | [`test_celery_worker_environment.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_celery_worker_environment.py) |
| **Subsystem Health Probes with 2.0s Hard Cap** | **[VERIFIED IN SOURCE CODE]** | [`recondesk-backend/app/main.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py) | `_HEALTH_PROBE_TIMEOUT_S = 2.0`, `health_check()`, Lines 800–920 | [`test_caddy_health_check.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_caddy_health_check.py) |

---

## 8. Unresolved Operational Questions & Verification Checklist

To maintain institutional integrity, the following items cannot be fully verified from static code alone and require confirmation in production:

1. **Active DNS Resolution for Frontend**:
   * *Question*: Is public DNS for `recondesk.in` pointing to AWS Amplify Hosting or Vercel?
   * *Method*: Run `dig +short recondesk.in` or `nslookup recondesk.in`.
2. **Aurora Capacity Scaling Invariants**:
   * *Question*: What is the configured minimum and maximum ACU (Aurora Capacity Unit) range in the AWS RDS Console (e.g., 0.5 ACU to 16 ACU)?
   * *Method*: Inspect AWS RDS Console $\rightarrow$ Aurora Serverless v2 cluster configuration.
3. **Cognito Migration User Cutover**:
   * *Question*: What percentage of active user accounts in production currently authenticate via Amazon Cognito vs legacy Supabase Auth?
   * *Method*: Query `user_profiles.auth_provider` distribution in Aurora.
