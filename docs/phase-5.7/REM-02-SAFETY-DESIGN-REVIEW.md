# Phase 5.7 REM-02 — Pre-Implementation Safety and Design Review: Celery Ingestion Progress Starvation & Staging Idempotency

**Document ID**: REM-02-SAFETY-DESIGN-REVIEW  
**Target Component**: Ingestion Pipeline & Celery Worker (`app/worker/tasks.py:run_import_job`, `_bulk_insert`, `_update_run`)  
**Date**: 2026-09-21  
**Status**: DESIGN REVIEW & SAFETY VERIFICATION (Audit Only — No Code Modified)  
**Corpus Reference**: `docs/phase-5.7/REM-02-INGESTION-PROGRESS-AUDIT.md` and Phase 5.7 Audit Finding `FINDING-H02`

---

## 1. Executive Summary & Review Scope

This safety and design review investigates the proposed remediation for Phase 5.7 item **REM-02 (Celery Ingestion Progress Starvation)** across six critical architectural dimensions:
1. **Progress Reporting**: Authoritative progress tables, schema verification, table-name reconciliation, and bounded non-blocking flush mechanisms.
2. **Staging Idempotency**: `run_id` lifecycle, multi-file and multi-period semantics, safety of row deletion, and architectural alternatives.
3. **Partial-Failure Recovery**: Worker timeout behavior, exception containment, Celery task retry mechanics, and staging isolation from matching engines.
4. **Cancellation Mechanics**: Authoritative cancellation status, polling frequency and overhead, and prevention of false completion states.
5. **Time Limits & Batch Sizing**: Execution budgets, performance curves for 50,000 to 100,000+ rows, and batching trade-offs.
6. **Verification & Test Design**: Complete unit and simulation test matrix covering monotonicity, bounds, idempotency, cancellation, and terminal states.

---

## 2. Section 1: Progress Reporting Architecture

### 2.1 Complete Trace of Progress-Writing Paths

| File Path & Line Numbers | Context / Caller | Target Table | Column Written | Value / Semantics |
|---|---|---|---|---|
| `app/worker/tasks.py:271–279` | `run_import_job` start | `reconciliation_run` | `progress_percent` | `5` ("importing") |
| `app/worker/tasks.py:467–472` | `run_import_job` post-parse | `reconciliation_run` | `progress_percent` | `40` (PR parse complete) |
| `app/worker/tasks.py:577–584` | `run_import_job` post-insert | `reconciliation_run` | `progress_percent` | `90` (All chunks inserted) |
| `app/worker/tasks.py:586–598` | `run_import_job` finalization | `reconciliation_run` | `progress_percent` | `100` (Sanity report attached) |
| `app/worker/tasks.py:211–220` | `_update_run` mirroring helper | `wizard_runs` *(NON-EXISTENT)* | `progress_pct` | Mirrored from `progress_percent` (SILENTLY FAILS) |
| `app/worker/reconciliation_task.py:525–533` | `run_wizard_job._set_wizard_pct` | `wizard_runs` *(NON-EXISTENT)* | `progress_pct` | `10`, `25`, `40`, `100` (SILENTLY FAILS) |
| `app/worker/reconciliation_task.py:535–543` | `run_wizard_job._set_wizard_pct` | `reconciliation_run` | `progress_percent` | `10`, `25`, `40`, `100` |
| `app/services/reconciliation_import_wizard/wizard_service.py:774–782` | `_set_wizard_progress` | `reconciliation_import_runs` (`T_RUNS`) | `progress_pct` | `10`, `25`, `40`, `50`, `95`, `100` |
| `app/routers/reconciliation_import_wizard.py:741` | `start_reconciliation` | `reconciliation_import_runs` | `progress_pct` | `0` ("Starting…") |
| `app/routers/import_router.py:353, 511` | Ingestion dispatch endpoints | `reconciliation_run` | `progress_percent` | `0` ("uploading" / "queued") |

### 2.2 The Authoritative Progress Tables and Schemas

There are **two distinct run tables** serving two distinct product workflows:

1. **`public.reconciliation_import_runs` (Import Wizard State Table)**:
   - **Created by**: `supabase/migrations/20260428120000_reconciliation_import_wizard.sql:4-35`
   - **Primary Key**: `id` (UUID)
   - **Progress Column**: `progress_pct` (`INT NOT NULL DEFAULT 0`)
   - **Status Column**: `status` (`TEXT CHECK (status IN ('draft', 'gstr_uploaded', 'pr_uploaded', 'pending', 'processing', 'complete', 'error', 'cancelled'))`)
   - **Message Column**: `status_message` (`TEXT`)
   - **Queried by**: `GET /api/runs/{run_id}/status` (`reconciliation_import_wizard.py:810-828`), consumed by `importWizardApi.pollStatus` in `recondesk-frontend/lib/api.ts:2245`.

2. **`public.reconciliation_run` (Core Engine Processing Table)**:
   - **Created by**: Alembic `20260417_import_pipeline_upgrade.py:75`
   - **Primary Key**: `id` (UUID)
   - **Progress Column**: `progress_percent` (`DOUBLE PRECISION NOT NULL DEFAULT 0.0`)
   - **Status Column**: `status` (`VARCHAR(50) NOT NULL DEFAULT 'queued'`)
   - **Message Column**: `status_message` (`TEXT`)
   - **Queried by**: `GET /api/v1/import/status/{run_id}` (`import_router.py:550-600`) and `/api/reconciliation/{run_id}/status`.

### 2.3 Verification of `wizard_runs`: Defect vs. Supported Legacy Table

- **Evidence from Git History**:
  Commit `82fefac5d2157dc500f345c38b0f1d6a09a43b5c` (*"fix: mirror reconciliation engine progress into wizard_runs"*) introduced the mirroring logic in `tasks.py:_update_run`:
  ```python
  client.table("wizard_runs").update(wiz).eq("id", run_id).execute()
  ```
  The commit message explicitly states:
  > *"_update_run() now writes progress_pct (and status_message) into wizard_runs whenever it updates reconciliation_run.progress_percent. The poll endpoint reads wizard_runs..."*
- **The Defect**:
  The author assumed the table name was `wizard_runs`. In reality, migration `20260428120000` created `reconciliation_import_runs`.
- **Database Reality**:
  - `public.wizard_runs` does NOT exist in any schema, migration, or PostgreSQL catalog.
  - Every update to `wizard_runs` fails with `PGRST204` / `404 Not Found` (relation does not exist), which was caught and silenced by `except Exception: pass`.
  - There is zero legacy support or dependency on `wizard_runs`.
- **Conclusion**:
  Updating `tasks.py:_update_run` and `reconciliation_task.py:_set_wizard_pct` to write to **`reconciliation_import_runs`** restores the exact functionality intended by commit `82fefac`.

### 2.4 Bounded Progress-Flush Design for `_bulk_insert()`

To completely eliminate UI progress starvation without incurring database or network overhead:
1. **Never emit progress per row**. For a 50,000-row file, 50,000 writes would destroy database throughput.
2. **Never emit progress per chunk**. For `CHUNK_SIZE = 500`, 100 PostgREST writes would double total insertion latency.
3. **Bounded Dual-Threshold Throttle**:
   Emit a progress update if and only if:
   - At least `FLUSH_ROW_THRESHOLD = 5,000` rows have been inserted since the previous update, **OR**
   - At least `FLUSH_TIME_THRESHOLD_SEC = 3.0` seconds have elapsed since the previous update, **OR**
   - The insertion is 100% complete (`inserted == total`).

### 2.5 Safe Progress Semantics: Mapping the 40% to 85% Window

In `run_import_job`, the lifecycle is apportioned as:
- `0% – 5%`: Job initialization and Cloudflare R2 file download.
- `5% – 40%`: Excel/CSV parsing and header normalization (can take 15–30s for large files).
- `40%`: Sanity checks complete, row transformation ready.
- **`40% – 85%` (The Bulk Insertion Span)**:
  During `_bulk_insert`, progress scales linearly:
  $$\text{pct} = 40 + \text{int}\left(\frac{\text{inserted\_rows}}{\text{total\_rows}} \times 45\right)$$
  - Example (50,000 rows):
    - 5,000 rows (10% inserted) $\rightarrow 40 + 4 = 44\%$
    - 25,000 rows (50% inserted) $\rightarrow 40 + 22 = 62\%$
    - 45,000 rows (90% inserted) $\rightarrow 40 + 40 = 80\%$
    - 50,000 rows (100% inserted) $\rightarrow 40 + 45 = 85\%$
- `85% – 90%`: Post-insert verification, sanity report formatting, and count recording.
- `90% – 100%`: Final status resolution (`PURCHASE_IMPORT_COMPLETE` or `READY`).
- Accompanying message: `f"Importing purchase records ({inserted:,} / {total:,})…"`.

---

## 3. Section 2: Staging Idempotency & Deletion Safety

### 3.1 Trace of `run_id` Creation and Reuse Across Workflows

1. **Standalone Import Flow (`import_router.py`)**:
   - `POST /api/v1/import/gstr2b` creates a new `reconciliation_run` with `run_id = str(uuid4())` (line 338).
   - If a previous upload for the client and period failed or remained in `"uploading"`, it reuses `run_id = row["id"]` (line 320).
   - `POST /api/v1/import/purchase-register` receives `run_id` as a form field and attaches to the existing `reconciliation_run`.
2. **Wizard Import Flow (`reconciliation_import_wizard.py` & `wizard_service.py`)**:
   - `POST /api/runs` creates a row in `reconciliation_import_runs` with `id = gen_random_uuid()`.
   - `POST /api/runs/{run_id}/start` verifies or creates the corresponding `reconciliation_run` with the exact same `id = str(run_id)`.
   - Both `run_import_job(run_id, "gstr2b", ...)` and `run_import_job(run_id, "purchase_register", ...)` execute with the **same shared `run_id`**.
3. **Multi-Period Batch Flow (`multi_period_wizard.py`)**:
   - For each period item, `run_id = item.get("reconciliation_run_id") or str(uuid4())`.
   - Sequential calls to `run_import_job(run_id, "gstr2b", ...)` and `run_import_job(run_id, "purchase_register", ...)` use the **same shared `run_id`**.

### 3.2 Staging Table Inspection & Shared-Key Semantics

- Staging tables: `public.gstr_records` and `public.pr_records`.
- Both tables have a foreign key to `public.reconciliation_run(id)`:
  ```sql
  run_id UUID NOT NULL REFERENCES public.reconciliation_run(id) ON DELETE CASCADE
  ```
- **Key Semantic Fact**:
  `gstr_records` stores GSTR-2B invoices for `run_id`.
  `pr_records` stores Purchase Register invoices for `run_id`.
  They are **physically separate tables**. Deleting from `pr_records` never deletes rows from `gstr_records`.

### 3.3 Safety Evaluation of `DELETE FROM pr_records WHERE run_id = ...`

#### Can cleanup remove valid records?
**YES, under specific conditions if unconstrained**:
1. **Cross-Period Historical Data**:
   In `reconciliation_task.py:125-149`, the matching engine queries historical PR records across previous months:
   ```python
   client.table("pr_records").select(...).eq("client_gstin_id", client_gstin_id).eq("period", mo).neq("run_id", run_id)...
   ```
   If a deletion were scoped by `client_gstin_id` or `period` instead of `run_id`, it would destroy historical data.
2. **Completed / Finalized Runs**:
   If `run_import_job` is invoked against an already completed or locked run, deleting `pr_records` destroys the foundation of `recon_results` and Table 4 workpapers.
3. **Concurrent Worker Execution**:
   If two worker processes execute `run_import_job` concurrently for the same `run_id`, an unconditional delete by Worker B wipes Worker A's partial insert.

#### Can multiple PR files share one `run_id`?
**NO**. Across all workflows (Wizard, Standalone, Tally Bridge, Multi-Period), a single reconciliation run corresponds to exactly **one** Purchase Register file (which may contain multiple internal sheets combined by `purchase_register_parser.py`).

### 3.4 Evaluation of Alternatives to Blanket Deletion

| Alternative | Mechanics | Pros | Cons | Verdict |
|---|---|---|---|---|
| **A. Unconditional Deletion** | `delete().eq("run_id", run_id)` at task entry | Simple to implement | Destroys data if called on finalized/matching runs; race conditions | **REJECTED** |
| **B. Unique Import Attempt ID (`attempt_id`)** | Add `attempt_id` UUID column to `pr_records`; engine queries only active attempt | Completely zero risk to previous inserts | Requires table schema migration on massive production tables; breaks existing queries | **REJECTED (Out of Scope)** |
| **C. Database Transaction (RPC)** | Wrap all chunks in a single PostgreSQL transaction | Pure ACID atomicity | PostgREST does not support multi-request transactions over HTTP; requires raw SQL connection | **REJECTED (Architecture Mismatch)** |
| **D. Controlled Lifecycle Guarded Replacement** | Check run status; delete staging records **strictly if status is unfinalized/pre-matching** (`uploading`, `queued`, `importing`, `failed`) | 100% safe against locked/completed runs; prevents duplicate rows on retry | Requires status check before purge | **APPROVED (RECOMMENDED)** |
| **E. New `run_id` on Every Retry** | Discard run and create fresh `run_id` on failure | Completely clean slate | Breaks Wizard frontend SWR polling; requires CA to re-upload both files and re-do mapping | **REJECTED (UX Regression)** |

### 3.5 Approved Idempotency Policy: Guarded Staging Replacement

Prior to beginning `_bulk_insert` for `insert_table` (`pr_records` or `gstr_records`):
1. Query current `reconciliation_run` status.
2. If `status` is `MATCHING`, `PROCESSING`, `READY`, `COMPLETED`, or `FINALIZED`:
   **ABORT IMMEDIATELY** with `RuntimeError("Cannot import into run in status ...")`.
3. If `status` is `uploading`, `queued`, `importing`, or `failed`:
   Execute guarded deletion:
   ```python
   client.table(insert_table).delete().eq("run_id", run_id).execute()
   ```
This guarantees that:
- Retries clean up partial chunks from previous crashed attempts.
- No duplicate records can ever exist for `run_id`.
- Valid historical records for other runs and finalized runs remain completely protected.

---

## 4. Section 3: Partial-Failure Recovery & Celery Mechanics

### 4.1 Trace of Failure Scenarios

```
Failure Point                 Worker State                 Database State (reconciliation_run)      Staging State (pr_records)
─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
1. Parser Error (XLSX corrupt) Raises ValueError            status="failed", progress=40%             0 rows inserted
2. Worker Soft Timeout (300s)  Raises SoftTimeLimitExceeded status="failed", progress=40-85%          N partial rows (orphaned)
3. Database Network Blip       Raises RuntimeError          status="failed", progress=40-85%          N partial rows (orphaned)
4. Worker Process Killed (OOM) SIGKILL                      status="importing" (stale)                N partial rows (orphaned)
```

### 4.2 Celery Retry Behavior & Task Configuration
In `app/worker/tasks.py:239-244`:
```python
@celery_app.task(
    name="worker.run_import_job",
    max_retries=0,
    soft_time_limit=300,
    time_limit=360,
)
```
- `max_retries = 0`: Automatic Celery task retries are **disabled**. Celery will never silently re-queue a failed import job.
- When an import fails, recovery is strictly user-driven (via the UI **Retry** button).
- The user-driven retry transitions `reconciliation_import_runs.status` from `"error"` back to `"pr_uploaded"` (`reconciliation_import_wizard.py:843`).
- When the user clicks Start again, the Guarded Staging Replacement policy (Section 3.5) purges the orphaned $N$ partial rows before starting the fresh insert.

### 4.3 Staging Isolation from Reconciliation Engine

Can `execute_reconciliation` start against incomplete staging data?
**NO, the engine is fully isolated by a status gate**:
- `execute_reconciliation` (`reconciliation_task.py:734`) strictly enforces:
  ```python
  .update({"status": "PROCESSING"}).eq("id", run_id).eq("status", "MATCHING").execute()
  ```
- The status only reaches `"MATCHING"` in `wizard_service.py:846` **after** `run_import_job` completes without raising an exception.
- If `run_import_job` fails midway, `status` is set to `"failed"` / `"error"`, preventing `execute_reconciliation` from ever running.

---

## 5. Section 4: Cancellation Mechanics

### 5.1 Authoritative Cancellation Status

1. **User Action**: The user clicks Cancel in the Wizard UI (`new/page.tsx:1435`).
2. **API Endpoint**: `POST /api/runs/{run_id}/cancel` (`reconciliation_import_wizard.py:780`).
3. **Database Write**: `wizard_service.py:transition_run` updates `reconciliation_import_runs`:
   ```python
   {"status": "cancelled", "updated_at": now}
   ```
4. **Authoritative Table**: `public.reconciliation_import_runs.status == "cancelled"`.

### 5.2 Worker Cancellation Polling Frequency & Overhead

- In `_bulk_insert`, checking the database on every single chunk would add 100 extra queries.
- **Optimized Strategy**: Couple the cancellation check directly to the **progress flush callback**:
  - The worker only queries run status when flushing progress (every 5,000 rows or 3.0 seconds).
  - Overhead: Exactly 10 to 15 lightweight `select("status").eq("id", run_id)` queries over the entire 2-minute insertion.
  - If `status == "cancelled"`:
    Worker raises `ImportCancelledException("Import cancelled by user")`, terminates the insertion loop immediately, and exits cleanly.

### 5.3 Preventing False Completion

In `wizard_service.py:854` and `tasks.py:618`:
- Before transitioning to `"complete"` or `"READY"`, verify that the run status has not been set to `"cancelled"`.
- `state_machine.py:29` defines `"cancelled": frozenset()`. Any attempt to transition from `"cancelled"` to `"complete"` or `"error"` correctly raises a `ValueError`.
- With the cancellation check inside `_bulk_insert`, the worker halts before ever reaching the completion block.

---

## 6. Section 5: Time Limits, Performance & Batch Sizing

### 6.1 Performance Benchmarks & Estimates

| Dataset Size | Chunk Size | Number of Batches | Network Round-Trip Time | Parser Time | Total Runtime | Fits 300s Soft Limit? |
|---|---|---|---|---|---|---|
| **10,000 rows** | 500 | 20 | ~16s – 25s | ~3s – 6s | ~20s – 35s | **YES** (Plenty of margin) |
| **50,000 rows** | 500 | 100 | ~70s – 120s | ~15s – 28s | ~90s – 155s | **YES** (~50% budget) |
| **100,000 rows** | 500 | 200 | ~150s – 240s | ~35s – 65s | ~195s – 315s | **RISK** (Touches 300s limit) |
| **100,000 rows** | **1,000** | **100** | **~90s – 140s** | **~35s – 65s** | **~130s – 210s** | **YES** (Safe margin) |

### 6.2 Evaluation: Progress Optimization vs. Batch Tuning

- Progress optimization (throttled flushing) eliminates the **UI perception** of freezing.
- However, for datasets approaching 100,000 rows, `CHUNK_SIZE = 500` incurs 200 sequential HTTP PostgREST requests. Network latency alone can cause the worker to exceed `soft_time_limit = 300s`.
- **Recommendation**:
  - Keep `CHUNK_SIZE = 500` as the default for safety, but make it an internal constant easily tuned to `1000`.
  - For files $> 50,000$ rows, `CHUNK_SIZE = 1,000` cuts network round-trips by 50% with negligible memory overhead (~600 KB payload per batch).

---

## 7. Section 6: Comprehensive Verification & Test Design

### 7.1 Proposed Test Suite: `tests/test_ingestion_progress_safety.py`

```python
"""Unit tests verifying progress reporting, idempotency, and cancellation safety."""

import pytest
from unittest.mock import MagicMock, patch, call
from app.worker.tasks import _bulk_insert, _update_run, run_import_job

class TestIngestionProgressAndSafety:

    def test_progress_monotonicity_and_bounds(self):
        """Emitted progress percentages must be non-decreasing and capped at 100%."""
        emitted_pcts = []
        def mock_on_progress(inserted, total):
            pct = 40 + int((inserted / total) * 45)
            emitted_pcts.append(pct)

        mock_client = MagicMock()
        rows = [{"run_id": "test", "data": i} for i in range(15000)]
        _bulk_insert(mock_client, "pr_records", rows, on_progress=mock_on_progress)

        assert len(emitted_pcts) > 0
        assert all(0 <= p <= 100 for p in emitted_pcts)
        assert emitted_pcts == sorted(emitted_pcts)  # Monotonic
        assert emitted_pcts[-1] == 85  # Max insertion span

    def test_update_run_writes_to_reconciliation_import_runs(self):
        """_update_run must write to reconciliation_import_runs and not wizard_runs."""
        mock_client = MagicMock()
        _update_run(mock_client, "test-run-id", {"progress_percent": 65, "status_message": "Testing"})

        # Verify reconciliation_run updated
        mock_client.table.assert_any_call("reconciliation_run")
        # Verify reconciliation_import_runs updated with progress_pct
        mock_client.table.assert_any_call("reconciliation_import_runs")
        # Verify non-existent wizard_runs is NEVER called
        table_calls = [c[0][0] for c in mock_client.table.call_args_list]
        assert "wizard_runs" not in table_calls

    def test_staging_idempotency_purges_only_unfinalized_run(self):
        """Re-running import on failed run purges prior staging rows; rejects finalized run."""
        mock_client = MagicMock()
        # Case A: Run is in "failed" state -> deletion allowed
        mock_client.table("reconciliation_run").select().eq().limit().execute.return_value.data = [
            {"status": "failed", "client_gstin_id": "c1", "period": "2025-04"}
        ]
        # Verify delete executed on pr_records for run_id
        # ...

        # Case B: Run is in "COMPLETED" state -> raises RuntimeError, delete NEVER called
        mock_client.table("reconciliation_run").select().eq().limit().execute.return_value.data = [
            {"status": "COMPLETED", "client_gstin_id": "c1", "period": "2025-04"}
        ]
        with pytest.raises(RuntimeError, match="Cannot import into run in status COMPLETED"):
            # run_import_job(...)
            pass

    def test_cancellation_halts_bulk_insert_early(self):
        """When run status becomes 'cancelled', _bulk_insert must abort immediately."""
        mock_client = MagicMock()
        # Mock cancel status returned on second check
        # ...
        # Assert insert loop terminates early without processing remaining batches
```

---

## 8. Explicitly Approved vs. Rejected Approaches

| Proposed Item | Status | Technical Rationale |
|---|---|---|
| **Fix table name to `reconciliation_import_runs`** | **APPROVED** | Authoritative table in database; matches schema migration `20260428120000` and `wizard_service.py`. |
| **Keep `wizard_runs` as fallback** | **REJECTED** | `wizard_runs` does not exist; silent `pass` hid the bug for months. |
| **Throttled progress flush in `_bulk_insert`** | **APPROVED** | Bounded at 5,000 rows or 3.0s; provides live updates without database performance degradation. |
| **Per-row progress updates** | **REJECTED** | 50,000 network round-trips would completely crash performance. |
| **Guarded staging deletion (`run_id`)** | **APPROVED** | Purges orphaned chunks on retry while strictly protecting completed/locked runs. |
| **Unconditional staging deletion** | **REJECTED** | Dangerous if called on completed or finalized runs. |
| **Cancellation check in progress callback** | **APPROVED** | Stops wasted background compute when a CA cancels a run in the UI. |

---

## 9. Files Expected to Change During Implementation

| File | Change Scope |
|---|---|
| `recondesk-backend/app/worker/tasks.py` | 1. Fix `_update_run` to target `reconciliation_import_runs`.<br>2. Refactor `_bulk_insert` to take `on_progress` and cancellation check.<br>3. Add guarded staging cleanup before `_bulk_insert`.<br>4. Wire progress callback in `run_import_job` (40% to 85%). |
| `recondesk-backend/app/worker/reconciliation_task.py` | Replace legacy `wizard_runs` references with `reconciliation_import_runs` in `_set_wizard_pct` and `_fail`. |
| `recondesk-backend/tests/test_ingestion_progress_safety.py` | Add unit test suite covering monotonicity, table writes, staging idempotency, and cancellation. |

---

## 10. Conclusion & Recommended Implementation Sequence

1. **Phase 1: Unit Test Harness** — Implement `tests/test_ingestion_progress_safety.py` capturing current failure modes (reproducing table mismatch and lack of intermediate progress).
2. **Phase 2: Table Name Alignment** — Update `_update_run` and `reconciliation_task.py` to write to `reconciliation_import_runs`.
3. **Phase 3: Bulk Insert Refactor** — Implement the bounded `on_progress` callback and cancellation check in `_bulk_insert`.
4. **Phase 4: Guarded Idempotency** — Add lifecycle-guarded deletion of prior partial records in `run_import_job`.
5. **Phase 5: Verification & End-to-End Testing** — Run backend test suite, verify mock runs with 50,000 rows, and confirm clean logs.
