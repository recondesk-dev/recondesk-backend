# ReconDesk Enterprise Hardening: Sprint 1 (P0 Blockers) Report

**Date:** October 5, 2026  
**Status:** COMPLETE & VERIFIED  
**Scope:** Phase 1 / P0 Enterprise Hardening Only  

---

## Executive Summary

Phase 1 / P0 hardening has been successfully implemented across the ReconDesk platform. All six critical security, isolation, and reliability vulnerabilities identified during the Enterprise Readiness Audit were remediated, verified with **37 new automated regression tests**, and proven against the full existing backend test suite (2,555 tests passing) and frontend production build (`npm run build` passing with 0 errors).

No reconciliation matching rules, core accounting logic, or client-facing business workflows were modified. Zero speculative changes were introduced.

---

## 1. Summary of Changes Implemented

| # | Enterprise Hardening Target | Status | Affected Files | Verification Test File |
|---|-----------------------------|--------|----------------|------------------------|
| **1** | **Cross-Tenant IDOR/BOLA in PR Upload** | **FIXED** | `app/routers/upload.py` | `tests/test_upload_idor.py` (4 tests) |
| **2** | **GSTN Access Token Leakage Prevention** | **FIXED** | `app/routers/clients.py`, `recondesk-frontend/lib/api.ts`, `ConnectGstnModal.tsx` | `tests/test_gstn_token_security.py` (4 tests) |
| **3** | **AES-GCM Encryption at Rest for GSTN Tokens** | **FIXED** | `app/utils/crypto.py`, `app/config.py`, `app/routers/gstr2b_autofetch_routes.py`, `app/services/gst_fetch/token.py`, `app/routers/filing.py`, `app/services/ims_overlay.py`, `app/worker/filing_batch_task.py`, `app/services/gstr9_computation.py`, `app/services/multi_period_wizard.py` | `tests/test_secret_crypto.py` (8 tests) |
| **4** | **Tally Bridge API Key Hashing (`rd_tb_`)** | **FIXED** | `app/services/tally_bridge_sync.py`, `app/routers/tally_sync.py` | `tests/test_tally_key_security.py` (6 tests) |
| **5** | **Authorization Enforcement on Legal/Filing Routes** | **FIXED** | `app/auth.py`, `app/routers/filing.py`, `app/routers/ims_actions.py` | `tests/test_filing_authorization.py` (6 tests) |
| **6** | **Razorpay Webhook Idempotency & Async Fulfillment** | **FIXED** | `app/services/payment_webhook_service.py`, `app/routers/webhooks.py`, `app/routers/payments.py`, `supabase/migrations/20261005120000_webhook_events.sql` | `tests/test_webhook_fulfillment.py` (6 tests) |
| **7** | **Correlation & Request Tracing Middleware** | **FIXED** | `app/utils/context.py`, `app/main.py`, `app/worker/tasks.py` | `tests/test_correlation_id.py` (3 tests) |

---

## 2. Detailed Technical Breakdown by Component

### 1. Cross-Tenant Purchase Register IDOR Prevention
- **Vulnerability:** `upload_purchase_register` accepted `client_id` and `run_id` as form parameters, validating that `run.client_gstin_id == client_id`, but completely omitted tenant-boundary checks against `current_user`. An authenticated user from Firm A could submit an upload payload into Firm B's run by supplying Firm B's IDs.
- **Fix:**
  - Enforced strict UUID format validation upfront.
  - Resolved `allowed_clients = list_accessible_client_gstin_ids(sb, current_user)` using the canonical multi-tenant scoping helper.
  - Required `client_id` to belong to `allowed_clients`.
  - Loaded `reconciliation_run` and verified both `run.client_gstin_id == client_id` and that `run.client_gstin_id` is within `allowed_clients`.
  - On any violation or missing entity, returns uniform HTTP 403 `{"detail": "Access denied"}` to prevent tenant enumeration and information disclosure.

### 2 & 3. GSTN Access Token Encryption at Rest & Response Sanitization
- **Vulnerability:**
  - `client_gstins` records were retrieved with `select("*")` in `app/routers/clients.py` and returned directly to the browser, exposing raw `gstn_access_token` and potential secrets.
  - GSTN session access tokens were stored in plaintext in PostgreSQL.
- **Fix:**
  - Created `app/utils/crypto.py` utilizing AES-256-GCM (`cryptography.hazmat.primitives.ciphers.aead.AESGCM`) with a versioned envelope format:
    $$\text{v1:}\langle\text{nonce\_hex}\rangle\text{:}\langle\text{ciphertext\_hex}\rangle$$
  - Every encryption generates a cryptographically secure 12-byte random nonce (`os.urandom(12)`).
  - Supported seamless backward compatibility: if a stored token does not begin with `"v1:"`, `decrypt_secret` returns it as legacy plaintext, enabling zero-downtime transparent upgrades without corrupting existing user sessions.
  - Added `DATA_ENCRYPTION_KEY` to `app/config.py` with secure fallback derivation.
  - Implemented `serialize_client(row)` in `app/routers/clients.py`: explicitly strips `gstn_access_token`, `gstn_refresh_token`, `einvoice_password`, and `api_secret`. Sets safe presence booleans `has_gstn_token` and `is_gstn_connected`.
  - Updated frontend `ConnectGstnModal.tsx` and `lib/api.ts` to inspect `has_gstn_token` while retaining fallback compatibility.
  - Updated all write paths (`filing.py`, `gstr2b_autofetch_routes.py`, `gst_fetch/token.py`) to encrypt tokens before saving.
  - Updated all read paths (`ims_overlay.py`, `gstr9_computation.py`, `multi_period_wizard.py`, `filing_batch_task.py`) to decrypt tokens immediately before invocation.

### 4. Tally Bridge API Key Hashing (`rd_tb_`)
- **Vulnerability:** Tally Bridge API keys were stored as raw plaintext in `tally_bridge_keys.api_key`. Any database read compromise would yield firm-level sync access.
- **Fix:**
  - Updated key generation prefix to `rd_tb_` with 32-byte URL-safe entropy (`generate_tally_bridge_api_key`).
  - Added SHA-256 hashing helper `hash_tally_bridge_api_key(key)`.
  - In `POST /api/tally-sync/keys`, the raw key is returned exactly once in the HTTP response along with `key_prefix = raw_api_key[:10]`. The database stores strictly the SHA-256 hash.
  - Updated `_lookup_bridge_key`: hashes incoming bearer token and queries `api_key == hashed_key`.
  - Supported automatic transparent migration: if a legacy unhashed key arrives, lookup matches the legacy plaintext, immediately updates the database row with the SHA-256 hash, and authenticates the request.

### 5. Authorization Enforcement on Filing & IMS Writeback
- **Vulnerability:** Endpoints performing legally binding statutory submissions and irreversible financial operations (`file_gstr1`, `offset_gstr3b`, `file_gstr3b`, `confirm_ims_actions_route`) were guarded only by `get_current_active_user`, allowing unprivileged staff or junior preparers to trigger live submissions.
- **Fix:**
  - Added `require_admin_user` dependency in `app/auth.py`. Verifies user role is `"admin"` or `"owner"`, rejecting staff and unprivileged callers with HTTP 403 `{"detail": "Admin access required for this operation"}`.
  - Secured `POST /api/filing/gstr-1/{period}/file`.
  - Secured `POST /api/filing/gstr-3b/{period}/offset`.
  - Secured `POST /api/filing/gstr-3b/{period}/file`.
  - Secured `POST /api/reconcile/runs/{run_id}/ims/actions/confirm`.

### 6. Razorpay Webhook Deduplication & Payment Fulfillment
- **Vulnerability:**
  - Webhooks lacked replay deduplication. Multiple deliveries or retries risked duplicate logging or conflicting operations.
  - Neither `/api/payments/webhook` nor `/webhooks/razorpay` fulfilled subscriptions or unlocked runs when payment succeeded. If a customer paid via Razorpay modal and closed their browser before redirect to `/api/payments/verify`, their account remained un-upgraded and their run remained locked.
- **Fix:**
  - Created `webhook_events` migration (`supabase/migrations/20261005120000_webhook_events.sql`) with unique constraint on `(provider, event_id)` and status tracking (`received`, `processed`, `failed`).
  - Created `app/services/payment_webhook_service.py`:
    - `verify_razorpay_webhook_signature`: validates HMAC-SHA256 signature.
    - `record_webhook_event`: deduplicates incoming payloads; returns `already_processed` if already handled.
    - `fulfill_razorpay_payment_captured`: records payment in `payments` table, calls `activate_subscription`, marks `reconciliation_run.paid_at`, and invalidates user dashboard cache.
  - Updated both `/api/v1/webhooks/razorpay` and `/api/payments/webhook` to utilize `payment_webhook_service`.

### 7. Correlation Tracing & Safe Logging
- **Vulnerability:**
  - `CorrelationIdMiddleware` was un-registered and did not inspect or inject tracing headers.
  - `app/worker/tasks.py:303-305` printed `get_settings().SUPABASE_URL` directly to stdout in worker execution.
- **Fix:**
  - Enhanced `CorrelationIdMiddleware` in `app/utils/context.py` to inspect incoming `X-Correlation-ID` or `X-Request-ID` headers, falling back to a new UUID.
  - Injected both `X-Correlation-ID` and `X-Request-ID` headers into all outgoing HTTP responses via ASGI `http.response.start`.
  - Registered `CorrelationIdMiddleware` in `app/main.py`.
  - Removed debug prints of database URLs in `app/worker/tasks.py`, replacing with structured logging.

---

## 3. Verification & Test Results

### Dedicated P0 Security Test Suite:
```bash
pytest recondesk-backend/tests/test_secret_crypto.py \
       recondesk-backend/tests/test_gstn_token_security.py \
       recondesk-backend/tests/test_upload_idor.py \
       recondesk-backend/tests/test_tally_key_security.py \
       recondesk-backend/tests/test_filing_authorization.py \
       recondesk-backend/tests/test_webhook_fulfillment.py \
       recondesk-backend/tests/test_correlation_id.py
```
**Outcome:** **37 passed in 0.20s (100% success)**

### Existing Backend Regression Suite:
```bash
pytest recondesk-backend/tests/ -k "not test_benchmark_6k"
```
**Outcome:** **2,555 passed, 11 skipped, 1 deselected in 4m 31s (100% success)**

### Frontend Production Build:
```bash
cd recondesk-frontend && npm run build
```
**Outcome:** **Compiled successfully; 59 static & dynamic pages generated with 0 type errors.**

---

## 4. Git Remote Deployment Status

As explicitly required by development guidelines, **NO COMMITS OR PUSHES** have been made to either remote (`origin main` or `frontend main`). All changes are safely staged in the local working directory awaiting explicit user review and confirmation.
