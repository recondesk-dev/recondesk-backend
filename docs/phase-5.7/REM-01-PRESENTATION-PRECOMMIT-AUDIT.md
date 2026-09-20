# Phase 5.7 REM-01 — Disposition Presentation Fixes Pre-Commit Audit Report

**Date**: 2026-09-20  
**Target Slice**: Phase 5.7 REM-01 — Disposition Presentation & Note Separation Fixes  
**Base Commit**: `1d7f3ba` ("fix(recon): support review-required disposition IDs")  
**Audit Scope**: Strict pre-commit verification across frontend and backend changes. Zero source code modifications made during audit.

---

## 1. Executive Verdict & Summary

### Verdict: **PASS — APPROVED FOR COMMIT**

| Category | Status | Details |
|---|---|---|
| **Drawer Actions State Awareness** | **PASS** | `results/page.tsx:6275-6370` conditionally renders active indicators ("Acted ✓", "Ignored") alongside valid transition actions ("Mark as Ignored", "Mark as Acted") and explicit "Reset to Pending". |
| **Card Status Pill Integration** | **PASS** | `<DecisionStatusPill status={effectiveStatus(row)} />` integrated into `DecisionInvoiceCard` in Review Required section, mirroring established ITC/Risk UX. |
| **Notes API Separation** | **PASS** | `app/routers/notes.py:185-210` selects `note_type` and strictly filters out `note_type == "decision_status"`, completely preventing disposition leakage into CA user notes. |
| **Identifier Normalization & Resolution** | **PASS** | Prefix stripping (`rr:` -> bare UUID) and dictionary lookup via `_lookup_by_record_id` verified end-to-end. |
| **Transition Support** | **PASS** | Backend supports all 3 states: `"acted"`, `"ignored"`, and `"pending"`. |
| **Locked / Finalized Run Protections** | **PASS** | Both frontend (`isRunFinalized`) and backend (`is_locked` / `status == FINAL` -> HTTP 409 Conflict) protect all transition paths. |
| **Preservation of User Notes** | **PASS** | Ordinary user-authored notes remain completely visible with full metadata. |
| **Persisted State Hydration** | **PASS** | Fresh data fetches correctly hydrate persisted decision status into Review Required rows and display in cards and drawer. |
| **Test Authenticity** | **PASS** | 19 frontend unit tests and 67 backend pytest tests pass without regressions, testing real API endpoints, unmocked routing, and contract behavior. |
| **Git Diff Cleanliness** | **PASS** | Diff strictly confined to presentation and note separation. Zero engine, tax, statutory, schema, or migration changes. |

---

## 2. Changed-File Inventory

| File Path | Component | Type of Change | Lines Changed | Description |
|---|---|---|---|---|
| `recondesk-backend/app/routers/notes.py` | Backend Router | Modified | +18, -4 | Added `note_type` column selection and filtered out `note_type == "decision_status"` in `list_notes` (`GET /api/notes/{record_id}`). Added schema fallback. |
| `recondesk-backend/tests/test_review_required_disposition.py` | Backend Tests | Modified | +162, -3 | Added focused tests for `list_notes` filtering, end-to-end disposition non-leakage, and reset-to-pending transitions. Added `order` and `in_` mock support. |
| `recondesk-frontend/app/(dashboard)/reconcile/runs/[run_id]/results/page.tsx` | Frontend Results UI | Modified | +72, -26 | Added `<DecisionStatusPill>` to `DecisionInvoiceCard` in Review Required list. Made drawer buttons state-aware for acted, ignored, and pending states with reset option. |
| `recondesk-frontend/components/reconcile/reviewRequiredPresentation.test.ts` | Frontend Unit Tests | New (Untracked) | +183 | Added unit tests for effective status calculation, state-aware drawer action config derivation, card pill text mapping, and finalized run locking. |
| `recondesk-frontend/components/reconcile/Table4WorkpaperView.tsx` | Frontend SWR Sync | Modified (Slice 1A) | +6, -3 | Slice 1A SWR synchronization after Table 4 adjustment and disposition mutations (previously approved). |
| `recondesk-frontend/components/reconcile/bulkDispositionSync.test.ts` | Frontend Tests | Untracked (Slice 1A) | +289 | Unit tests for Slice 1A SWR key matching and rollback behavior (previously approved). |
| `recondesk-frontend/lib/swrReconciliationSync.ts` | Frontend SWR Helper | Untracked (Slice 1A) | +136 | Run-scoped SWR revalidation helper for Slice 1A (previously approved). |
| `docs/phase-5.7/REM-01-DISPOSITION-PERSISTENCE-AUDIT.md` | Documentation | Untracked | +278 | Phase 5.7 REM-01 persistence audit report. |

---

## 3. Detailed Technical Audit Findings

### 3.1 State-Aware Drawer Action Controls (`results/page.tsx:6275-6370`)
- **Inspection**:
  The previous drawer buttons were static:
  ```tsx
  <button onClick={() => void runSingleDecision(activeRecord.id, "acted")}>Mark as Acted</button>
  <button onClick={() => void runSingleDecision(activeRecord.id, "ignored")}>Mark as Ignored</button>
  ```
  The new implementation evaluates `effectiveStatus(activeRecord)`:
  - **`status === "acted"`**:
    - Primary indicator: `<button disabled aria-pressed="true" className="... bg-[var(--ink)] text-white ... cursor-default">Acted ✓</button>`. Clearly communicates confirmed action.
    - Transition button: `<button onClick={() => void runSingleDecision(activeRecord.id, "ignored")}>Mark as Ignored</button>`. Permits changing disposition to ignored.
    - Reset button: `<button onClick={() => void runSingleDecision(activeRecord.id, "pending")}>Reset to Pending</button>`. Permits reverting to unacted state.
  - **`status === "ignored"`**:
    - Transition button: `<button onClick={() => void runSingleDecision(activeRecord.id, "acted")}>Mark as Acted</button>`. Permits changing disposition to acted.
    - Primary indicator: `<button disabled aria-pressed="true" className="... line-through text-gray-500 cursor-default">Ignored</button>`. Clearly communicates ignored disposition.
    - Reset button: `<button onClick={() => void runSingleDecision(activeRecord.id, "pending")}>Reset to Pending</button>`. Permits reverting to unacted state.
  - **`status === "pending"`**:
    - Preserves standard dual action buttons: `"Mark as Acted"` and `"Mark as Ignored"`.
- **Verdict**: **PASS (Severity: None)**. Eliminates misleading button presentation.

---

### 3.2 DecisionStatusPill Integration in Review Required Cards (`results/page.tsx:5373`)
- **Inspection**:
  In `DecisionInvoiceCard` (line 5373):
  ```tsx
  status={
    <div className="flex flex-wrap items-center gap-2">
      <DecisionStatusPill status={effectiveStatus(row)} />
      <MatchLevelBadge level={row.match_level} />
      ...
  ```
- **Evaluation**:
  - Reuses the standard `DecisionStatusPill` component (`ResultsUi.tsx:580`), ensuring uniform styling:
    - `"acted"` -> Dark pill with text `Done`.
    - `"ignored"` -> Gray line-through pill with text `Ignored`.
    - `"pending"` -> Gray pill with text `Pending`.
  - Driven by `effectiveStatus(row)`, reflecting optimistic updates immediately and hydrated server values after SWR fetch.
  - Does not alter tax amounts, discrepancy reasons, or match calculations.
- **Verdict**: **PASS (Severity: None)**.

---

### 3.3 Notes API Filtering of `decision_status` Rows (`app/routers/notes.py:185-210`)
- **Inspection**:
  In `list_notes`:
  ```python
  try:
      res = (
          sb.table("mismatch_notes")
          .select("id, record_id, record_type, run_id, user_id, note, created_at, note_type")
          .eq("record_id", db_record_id)
          .order("created_at", desc=True)
          .execute()
      )
  except Exception:
      res = (
          sb.table("mismatch_notes")
          .select("id, record_id, record_type, run_id, user_id, note, created_at")
          .eq("record_id", db_record_id)
          .order("created_at", desc=True)
          .execute()
      )
  rows = [
      n
      for n in (res.data or [])
      if isinstance(n, dict)
      and str(n.get("note_type") or "").strip().lower() != "decision_status"
  ]
  ```
- **Evaluation**:
  - Filtering in Python (`!= "decision_status"`) safely handles SQL `NULL` values on legacy rows without dropping them (avoiding the SQL tri-state logic trap where `NULL <> 'decision_status'` evaluates to false).
  - Preserves user-authored notes (which have `note_type: "user_note"` or NULL).
  - Graceful fallback ensures compatibility if a test mock or legacy table lacks the `note_type` column.
  - Completely isolates `_decision_statuses_for_run` in `reconciliation_api.py`, which continues to select `record_id, note` where `note_type == "decision_status"`.
- **Verdict**: **PASS (Severity: None)**.

---

### 3.4 Disposition Transition Matrix

| Initial State | User Action | Endpoint Called | DB Note Written | Reconstructed State | Card Pill | Drawer UI |
|---|---|---|---|---|---|---|
| `pending` | Click "Mark as Acted" | `PATCH /records/bulk-update` (`acted`) | `note: "acted"`, `note_type: "decision_status"` | `acted` | `Done` | `[Acted ✓] [Mark as Ignored] [Reset to Pending]` |
| `pending` | Click "Mark as Ignored" | `PATCH /records/bulk-update` (`ignored`) | `note: "ignored"`, `note_type: "decision_status"` | `ignored` | `Ignored` | `[Mark as Acted] [Ignored] [Reset to Pending]` |
| `acted` | Click "Mark as Ignored" | `PATCH /records/bulk-update` (`ignored`) | `note: "ignored"`, `note_type: "decision_status"` | `ignored` | `Ignored` | `[Mark as Acted] [Ignored] [Reset to Pending]` |
| `acted` | Click "Reset to Pending" | `PATCH /records/bulk-update` (`pending`) | `note: "pending"`, `note_type: "decision_status"` | `pending` | `Pending` | `[Mark as Acted] [Mark as Ignored]` |
| `ignored` | Click "Mark as Acted" | `PATCH /records/bulk-update` (`acted`) | `note: "acted"`, `note_type: "decision_status"` | `acted` | `Done` | `[Acted ✓] [Mark as Ignored] [Reset to Pending]` |
| `ignored` | Click "Reset to Pending" | `PATCH /records/bulk-update` (`pending`) | `note: "pending"`, `note_type: "decision_status"` | `pending` | `Pending` | `[Mark as Acted] [Mark as Ignored]` |
| Any | Run finalized (`isRunFinalized=true` / `status=FINAL`) | Attempted `PATCH` returns HTTP 409 | No write | Unchanged | Unchanged | All action and reset buttons disabled |

---

## 4. Test Authenticity Assessment

### 4.1 Backend Tests (`test_review_required_disposition.py`)
- **Execution Command**:
  ```bash
  pytest recondesk-backend/tests/test_review_required_disposition.py
  ```
- **Result**: 13 passed in 0.10s.
- **Authenticity Audit**:
  - `test_list_notes_excludes_decision_status`: Issues an HTTP GET via FastAPI `TestClient` to `/api/notes/{record_id}`. Verifies that user notes are returned with author name and timestamp, while `decision_status` rows are excluded.
  - `test_end_to_end_disposition_does_not_leak_into_notes`: Issues a real `PATCH /api/reconcile/records/bulk-update` followed by `GET /api/notes/{record_id}`. Confirms that acting on a record does not create a user-visible note.
  - `test_reset_to_pending_via_bulk_update`: Issues a real `PATCH` with `decision_status: "pending"`, verifies HTTP 200 `{"updated_count": 1}`, and verifies that `_build_matched_pair_records` hydrates `"decision_status": "pending"`.
  - All tests exercise genuine endpoint routers, schema models, and business logic without shallow mocking of the functions under test.

### 4.2 Frontend Unit Tests (`reviewRequiredPresentation.test.ts` & `bulkDispositionSync.test.ts`)
- **Execution Command**:
  ```bash
  node --test components/reconcile/bulkDispositionSync.test.ts components/reconcile/reviewRequiredPresentation.test.ts
  ```
- **Result**: 19 passed in 78ms.
- **Authenticity Audit**:
  - Tests pure state resolution: verifies that optimistic updates take precedence during in-flight requests and that server values take over when optimistic keys are cleared.
  - Tests the complete drawer button configuration logic for all three states (`pending`, `acted`, `ignored`) and verified that finalized runs lock all actions.
  - Tests `DecisionStatusPill` mapping.

### 4.3 Broader Regression Suites
- `pytest recondesk-backend/tests/test_engine_classification.py recondesk-backend/tests/test_scenario_regression.py`: **54 passed**.
- Frontend production build (`next build`): **55/55 static pages compiled successfully**.

---

## 5. Scope & Safety Constraint Confirmation

1. **Reconciliation Engine**: Untouched. Files under `reconciliation_outcomes.py`, `rule37.py`, and `engine/` have 0 modifications.
2. **Tax & Statutory Logic**: Untouched. No modifications to GST calculation, GSTR-3B Table 4 formulas, or Rule 37 computations.
3. **Database Schema & Migrations**: Untouched. No new Alembic revisions, no alterations to `models/` or SQL DDL.
4. **Redis & Infrastructure**: Untouched. Redis configuration, TTLs, and worker topology remain untouched.
5. **Production Data Access**: Confirmed zero access or modification of production environments.
6. **Frontend Slice 1A Integrity**: Confirmed intact. `Table4WorkpaperView.tsx`, `swrReconciliationSync.ts`, and `bulkDispositionSync.test.ts` are preserved without conflict.
7. **Audit Process Non-Destructive**: Confirmed zero source files modified during this pre-commit audit.

---

## 6. Deployment Prerequisites

1. **Standard Two-Remote Push**:
   Per `AGENTS.md`, commit and push must be made to **both** remotes:
   - Backend: `origin main`
   - Frontend: `frontend main`
2. **Pre-Push Validation**:
   - Backend tests pass (`pytest recondesk-backend/tests/`).
   - Frontend production build succeeds (`npm run build`).

---

## 7. Final Audit Conclusion

The latest REM-01 disposition presentation fixes are **fully verified, correct, state-aware, and production-ready**. All pre-commit requirements are satisfied. The implementation is **APPROVED** for commit.
