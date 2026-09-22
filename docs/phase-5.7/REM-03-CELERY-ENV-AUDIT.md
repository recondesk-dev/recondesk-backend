# Phase 5.7 REM-03 — Celery Worker Environment Hardening Audit Report

**Item**: REM-03 — Celery Worker Environment Hardening  
**Audit Type**: Pre-Implementation Architecture, Security, and Safety Audit  
**Audit Date**: 2026-09-22  
**Target File Identified**: `recondesk-backend/app/worker/celery_app.py`  
**Auditor**: Antigravity Engineering  

---

## 1. Executive Summary

This audit evaluates the Celery worker startup architecture to design a fail-closed boot assertion that prevents the worker from starting if `SUPABASE_SERVICE_ROLE_KEY` is missing or empty.

Currently, if `SUPABASE_SERVICE_ROLE_KEY` is absent or blank, the Celery worker starts up without error, connects to Redis, advertises readiness, and consumes jobs from the queue. It only fails **latently** inside task execution when `_supabase()` calls `create_client()`, causing tasks to fail with an unhandled exception or leaving import runs stranded in `queued`/`importing` status.

The smallest, safest, zero-regression remediation is to introduce an explicit boot assertion via Celery's `@worker_init.connect` signal handler in `app/worker/celery_app.py`. This ensures the worker halts immediately on startup with a clear fatal error message, prevents tasks from being dequeued into a broken worker, and leaves web API startup, unit testing, and shared configuration completely unaffected.

---

## 2. Current Startup Architecture

### 2.1 Container & Process Hierarchy
- **Deployment Spec**: [`recondesk-backend/docker-compose.prod.yml`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/docker-compose.prod.yml#L26-L35)
  ```yaml
  worker:
    build: .
    command: celery -A app.worker.celery_app worker --loglevel=info --concurrency=2
    environment:
      - REDIS_URL=redis://redis:6379/0
    env_file: .env
    depends_on:
      - redis
    restart: always
  ```
- **Base Image**: [`recondesk-backend/Dockerfile`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/Dockerfile#L1-L17) (`python:3.11-slim`)
- **Worker Invocation**: `celery -A app.worker.celery_app worker --loglevel=info --concurrency=2`
- **Application Module**: `app.worker.celery_app`

### 2.2 Celery App Initialization Sequence
In [`recondesk-backend/app/worker/celery_app.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/celery_app.py):
1. Reads `REDIS_URL` from `os.environ` (default: `redis://localhost:6379/0`).
2. Instantiates `celery_app = Celery("recondesk", broker=redis_url, backend=redis_url, include=[...])`.
3. Sets serialization and timezone configuration (`json`, `UTC`).
4. Imports task modules to register Celery tasks:
   - `app.worker.filing_batch_task`
   - `app.worker.reconciliation_task`
   - `app.worker.tasks`
5. **No environment validation occurs during initialization.**

---

## 3. Current Secret-Loading Behavior & Usage Analysis

### 3.1 Settings Configuration
In [`recondesk-backend/app/config.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/config.py#L41):
```python
SUPABASE_SERVICE_ROLE_KEY: str = ""
```
- Defaults to an empty string `""`.
- `validate_production_secrets()` (lines 196–218) defines `SUPABASE_SERVICE_ROLE_KEY` as a required production secret, but **this function is never invoked anywhere in the codebase** (neither in `app/main.py` nor in `celery_app.py`).

### 3.2 Where `SUPABASE_SERVICE_ROLE_KEY` is Consumed by Workers
1. **Purchase Register & GSTR Ingestion** ([`app/worker/tasks.py:56-59`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/tasks.py#L56-L59)):
   ```python
   def _supabase() -> Client:
       s = get_settings()
       return create_client(s.SUPABASE_URL, s.SUPABASE_SERVICE_ROLE_KEY)
   ```
   Used for:
   - Reading run metadata (`reconciliation_run`).
   - Guarded staging deletion on retry (`pr_records` / `gstr_records`).
   - Bulk insertion of records (`_bulk_insert`).
   - Updating progress and terminal status (`reconciliation_run`, `reconciliation_import_runs`).
2. **Reconciliation Task Execution** ([`app/worker/reconciliation_task.py:522,702`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/reconciliation_task.py#L522)):
   Imports and invokes `_supabase()` from `tasks.py`.
3. **Filing Batch Tasks** ([`app/worker/filing_batch_task.py:62`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/filing_batch_task.py#L62)):
   Invokes `get_supabase()` from `app.database`.

### 3.3 Production Presence Verification
- **Inspection Protocol**: Evaluated without printing secret content.
- **Production Status**: **`PRESENT`**
  - **Empirical Evidence**: During Phase 5.7 REM-02 production verification (tests 1, 2, 3, 4 executed on 2026-09-22), the worker successfully connected to Supabase, queried `client_gstins`, purged and inserted 6,000+ staging records, and updated `reconciliation_run`. This confirms that `SUPABASE_SERVICE_ROLE_KEY` is loaded and active in the live EC2 environment.
- **Local Environment Status**: **`PRESENT`** (verified in `recondesk-backend/.env`).

---

## 4. Failure-Mode Analysis: Why Latent Failure is Dangerous

If `SUPABASE_SERVICE_ROLE_KEY` is unset or empty:

```
[Producer: Web API]                     [Redis Broker]                     [Celery Worker]
       │                                      │                                  │
       │── POST /import/purchase-register ───>│                                  │
       │   Enqueue "worker.run_import_job" ──>│                                  │
       │                                      │── Pop task "worker.run_import" ─>│ (Worker is RUNNING)
       │                                      │                                  │
       │                                      │                                  │ Calls _supabase()
       │                                      │                                  │ create_client(url, "")
       │                                      │                                  │ 💥 SupabaseException:
       │                                      │                                  │   "supabase_key is required"
       │                                      │                                  │
       │                                      │                                  │ In exception handler:
       │                                      │                                  │ _update_run(client, ...)
       │                                      │                                  │ 💥 UnboundLocalError: 'client'
       │                                      │                                  │
       │                                      │                                  │ Task fails/retried
       │                                      │                                  │ Run trapped in 'queued'
       │                                      │                                  │ UI appears frozen
```

### Consequences of Current Latent Failure:
1. **False Readiness**: Docker health checks, container orchestrators, and monitoring tools view the worker container as healthy because the process is running.
2. **Task Black-Holing**: The worker continuously consumes tasks from Redis and immediately crashes during execution.
3. **UnboundLocalError**: In `tasks.py:807`, the error handler calls `_update_run(client, run_id, ...)`. If `client = _supabase()` failed, `client` is unassigned, crashing the error handler and preventing failure status persistence.
4. **Frozen User Experience**: The user's upload appears permanently stuck in `queued` or `importing` (0%).

---

## 5. Architectural Scope & Boundary Selection

We evaluated four possible locations to implement the assertion:

| Option | Location | Mechanism | Evaluation & Risk |
|---|---|---|---|
| **Option A (Recommended)** | `app/worker/celery_app.py` | `@worker_init.connect` signal handler | **Optimal**: Executes strictly when `celery worker` starts. Fails closed with exit code 1 before connecting to broker or consuming any tasks. Does not affect Web API or test imports. |
| **Option B** | `app/worker/celery_app.py` | Top-level module import check | **High Risk**: Triggers whenever `celery_app` is imported. Harms unit test files and Web API routers that import task definitions (`from app.worker.tasks import run_import_job`). |
| **Option C** | `app/config.py` | Pydantic `field_validator` on `Settings` | **Critical Risk**: Breaks any CLI script, Alembic migration, or unit test running in an environment without full service-role secrets. |
| **Option D** | `docker-compose.prod.yml` | Shell entrypoint wrapper script | **Sub-optimal**: Does not protect non-docker execution, local worker runs, or alternative deployment orchestrators. |

### Recommended Scope:
The assertion must be scoped **strictly to Celery worker process startup** via the `@worker_init.connect` signal in `app/worker/celery_app.py`.

---

## 6. Recommended Implementation Design

In [`recondesk-backend/app/worker/celery_app.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/celery_app.py):

```python
import sys
import logging
from celery.signals import worker_init

_log = logging.getLogger(__name__)

@worker_init.connect
def assert_worker_environment(**kwargs) -> None:
    """Fail-closed startup assertion: ensure required credentials exist before consuming tasks."""
    from app.config import get_settings

    settings = get_settings()
    key = (settings.SUPABASE_SERVICE_ROLE_KEY or "").strip()
    if not key:
        msg = (
            "FATAL: Celery worker startup aborted: SUPABASE_SERVICE_ROLE_KEY is missing or empty. "
            "The worker cannot execute ingestion, reconciliation, or filing jobs without service-role access."
        )
        _log.critical(msg)
        sys.stderr.write(f"\n[CRITICAL] {msg}\n\n")
        raise SystemExit(1)

    url = (settings.SUPABASE_URL or "").strip()
    if not url:
        msg = (
            "FATAL: Celery worker startup aborted: SUPABASE_URL is missing or empty."
        )
        _log.critical(msg)
        sys.stderr.write(f"\n[CRITICAL] {msg}\n\n")
        raise SystemExit(1)
```

### Why this design is safest:
1. **Signals are Celery-native**: `worker_init` is invoked by the Celery worker harness during process boot, before any worker pool threads/forks are created and before any tasks are consumed from the broker.
2. **Deterministic Process Termination**: Calling `sys.stderr.write()` and raising `SystemExit(1)` forces the worker process to exit with status code 1.
3. **Container Supervisor Visibility**: In `docker-compose.prod.yml`, `restart: always` coupled with container exit will cause the worker container to enter an observable restart loop / exit state with clear fatal logs, alerting ops immediately.
4. **Zero Impact on Web API / Testing**: Importing `app.worker.celery_app` or task functions in FastAPI or pytest does not fire `worker_init`.

---

## 7. Security Considerations

- **No Secret Exposure**:
  - The assertion checks `bool((key or "").strip())` and length.
  - The secret value is never printed, logged, or included in `SystemExit` messages or exception strings.
  - Logs report only: `[CRITICAL] FATAL: Celery worker startup aborted: SUPABASE_SERVICE_ROLE_KEY is missing or empty.`
- **Safe Filtering**:
  - ReconDesk's existing secret filter (`app/utils/secret_log_filter.py`) already scrubs `SUPABASE_SERVICE_ROLE_KEY`.
- **No Secret Rotation Required**:
  - This change introduces an assertion on the existing variable; no existing secrets need to be rotated or replaced.
- **No Environment File Changes**:
  - Production `.env` already has the key `PRESENT`.

---

## 8. Exact Files to Modify

| File | Change Scope | Lines | Purpose |
|---|---|---|---|
| [`recondesk-backend/app/worker/celery_app.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/celery_app.py) | Add `assert_worker_environment` with `@worker_init.connect` | ~25 lines | Hard boot assertion on worker startup |
| `recondesk-backend/tests/test_celery_worker_environment.py` | New unit test module | ~80 lines | Comprehensive test coverage for presence/absence/empty scenarios |

---

## 9. Minimum Test Plan

Create a new test file: `recondesk-backend/tests/test_celery_worker_environment.py` covering:

1. **Test 1: Normal Startup with Valid Key**:
   - `SUPABASE_SERVICE_ROLE_KEY` present and non-empty.
   - `assert_worker_environment()` completes with no exception and worker proceeds normally.
2. **Test 2: Missing Key Aborts Startup**:
   - `SUPABASE_SERVICE_ROLE_KEY` set to `""` or `None`.
   - `assert_worker_environment()` raises `SystemExit` with exit code 1.
   - Verifies error message matches expected FATAL string without exposing any values.
3. **Test 3: Whitespace-Only Key Aborts Startup**:
   - `SUPABASE_SERVICE_ROLE_KEY` set to `"   "`.
   - `assert_worker_environment()` raises `SystemExit` with exit code 1.
4. **Test 4: Missing Supabase URL Aborts Startup**:
   - `SUPABASE_URL` set to `""`.
   - `assert_worker_environment()` raises `SystemExit` with exit code 1.
5. **Test 5: Web API & Task Import Isolation**:
   - Importing `celery_app`, `app.worker.tasks`, and `app.main` with `SUPABASE_SERVICE_ROLE_KEY=""` does NOT trigger `assert_worker_environment` or abort the process.

---

## 10. Deployment & Rollback Strategy

- **Deployment Procedure**:
  1. Commit and push per `AGENTS.md` (to both `origin main` and `frontend main`).
  2. GitHub Actions deploys to EC2 via `docker compose -f docker-compose.prod.yml up -d --build`.
  3. Worker container starts, loads `.env`, executes `assert_worker_environment`, verifies key `PRESENT`, and begins processing jobs.
- **Verification on Deploy**:
  1. Verify `docker logs recondesk-backend-worker-1` shows clean startup without critical errors.
  2. Query `https://api.recondesk.in/health`.
- **Rollback Procedure**:
  1. If any unexpected worker issue occurs, revert commit via `git revert`.
  2. Push to both remotes. Docker compose will rebuild and restart previous worker state.

---

## 11. Risk Assessment

| Risk Category | Severity | Likelihood | Mitigation |
|---|---|---|---|
| **Production Worker Startup Failure** | High | Near Zero | Production worker currently has valid `SUPABASE_SERVICE_ROLE_KEY` confirmed active via empirical tests. |
| **Web API Boot Interruption** | Medium | Zero | Assertion is hooked exclusively to Celery's `worker_init` signal; the Web container does not run a Celery worker. |
| **Test Suite Regressions** | Medium | Zero | Unit tests that import `celery_app` will not fire the signal; isolated subprocess or direct signal tests will explicitly test both paths. |
| **Credential Leakage** | Critical | Zero | Assertion message contains zero interpolations of secret variables. |

---

## 12. Final Recommendation

**PROCEED TO IMPLEMENTATION**:
The architecture, failure mode, and signal hook are completely mapped and verified. Implementation is strictly localized to `app/worker/celery_app.py` and requires no schema migrations, no infrastructure changes, and no changes to production secrets.
