# REM-07 Pre-Commit Audit Report: Sentry PII Masking for Taxpayer Identifiers

**Date**: September 22, 2026  
**Auditor / Agent**: Antigravity Assistant  
**Status**: Ready for Commit & Dual-Remote Push  
**Remediation Target**: FINDING-L01 (Phase 5.7 Audit Report)  

---

## 1. Executive Summary

In compliance with statutory taxpayer privacy requirements and security finding **[FINDING-L01]**, this change implements automatic scrubbing and masking of 15-character Goods and Services Tax Identification Numbers (GSTINs) before telemetry payloads leave the application boundary and are transmitted to Sentry.

Characters 3–12 (the taxpayer's 10-character Permanent Account Number / PAN) are replaced with `XXXXXXXXXX`, while preserving the 2-digit State Code (characters 1–2) and the 3-character entity vertical / checksum suffix (characters 13–15). This guarantees complete zero-knowledge protection of taxpayer PANs in Sentry logs, request URLs, breadcrumbs, transactions, and error payloads, while retaining Place of Supply (POS) state attribution and vertical disambiguation for debugging.

---

## 2. Modified Components & Mechanics

### A. `recondesk-backend/app/filing/log_safety.py`
1. **Masking Engine**:
   - Compiles `_GSTIN_MASK_REGEX = re.compile(r"(?<![A-Za-z0-9])([0-9]{2})([A-Za-z]{5}[0-9]{4}[A-Za-z])([1-9A-Za-z][zZ][0-9A-Za-z])(?![A-Za-z0-9])", re.IGNORECASE)`
   - Rigorous negative lookbehind and lookahead prevent false positives on UUIDs, 64-character SHA-256 digests, long session tokens, or timestamps.
   - `mask_gstin(text)`: Converts e.g. `27AABCU9603R1ZM` or `27aabcu9603r1zm` into `27XXXXXXXXXX1ZM`.
2. **Recursive Data Scrubbing**:
   - `scrub_data_recursively(obj)`: Handles arbitrary strings, lists, tuples, and nested dictionaries in breadcrumbs and span telemetry.
3. **Telemetry Hooks**:
   - `sentry_scrub_breadcrumb(crumb, _hint)`: Sanitizes log messages and outgoing HTTP crumb data dicts.
   - `sentry_scrub_transaction(event, _hint)`: Masks transaction endpoint paths, request URLs, query parameters, span descriptions, and transaction breadcrumbs.
   - `sentry_scrub_event(event, _hint)`: Redacts sensitive query keys (OTP, EVC tokens) and masks GSTINs across request URLs, query strings, exception values, and error breadcrumbs.

### B. `recondesk-backend/app/main.py`
- Connected `before_send_transaction=sentry_scrub_transaction` and `before_breadcrumb=sentry_scrub_breadcrumb` to `sentry_sdk.init(...)` alongside the existing `before_send=sentry_scrub_event`.

### C. `recondesk-backend/tests/test_filing_log_safety.py`
- Added 7 dedicated unit test functions validating:
  - Uppercase and lowercase GSTIN masking.
  - Non-mutation collision avoidance on UUIDs, SHA-256 hashes, timestamps, and invoice numbers.
  - Safe handling of URL paths and query strings.
  - Breadcrumb scrubbing (`message`, `data.url`, `data.supplier`).
  - Transaction scrubbing (`transaction`, `request.url`, `request.query_string`, `spans`, `breadcrumbs`).
  - Error event scrubbing (`exception.values`, `request.url`, `request.query_string`, `breadcrumbs`).

---

## 3. Verification & Validation Evidence

### Automated Backend Tests
- `pytest tests/test_filing_log_safety.py -v`:
  - 11/11 tests PASSED in 0.02s.
- `pytest tests/test_celery_worker_environment.py tests/test_cdn_reconciliation.py tests/test_gstr3b_table4_adjustments_concurrency.py -v`:
  - 43/43 tests PASSED in 0.13s.

### Frontend Production Build
- `cd recondesk-frontend && npm run build`:
  - Next.js 14.2.35 production build compiled successfully.
  - 55/55 static pages generated.
  - Zero TypeScript or linting errors.

---

## 4. Deployment & Safety Checklist

- [x] Zero mutations to database schema or SQL queries.
- [x] Zero modifications to reconciliation mathematical engine or scoring logic.
- [x] Only telemetry payloads in Sentry before dispatch are scrubbed.
- [x] Follows dual-remote git push policy (`origin main` and `frontend main`).
- [x] Excluded `test_data/` from git staging.
