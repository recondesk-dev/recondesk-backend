# Volume 10: Celery, Redis & Asynchronous Job Processing

> **Document ID**: `RD-TECH-10`  
> **Author**: Chief Technology Officer & Principal Systems Architect  
> **Target Audience**: ReconDesk Founder, Distributed Systems Engineers, DevOps Engineers, EF / YC Technical Interviewers  
> **Repository Baseline**: `release/v1.5.2-rc1`  
> **Primary Source Evidence**: [`recondesk-backend/app/worker/celery_app.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/celery_app.py), [`reconciliation_task.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/reconciliation_task.py), [`reliability.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/reliability.py), [`main.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py) (Lines 126–216).

---

## 1. Executive Summary & Why Background Workers Exist

In modern web applications, the primary thread of an API server (FastAPI/Uvicorn) must remain responsive to incoming user traffic. Operations that exceed **500 milliseconds**—such as parsing 50,000-line spreadsheets, running dynamic programming string alignments across invoice candidates, downloading large JSON statements from government portals, or dispatching batch emails—**must never run inside the HTTP request-response cycle**.

If long-running operations execute synchronously on the web process:
1. **Thread Starvation**: The ASGI worker pool becomes saturated, rejecting subsequent HTTP requests with `HTTP 504 Gateway Timeout` or `HTTP 502 Bad Gateway`.
2. **Reverse Proxy Disconnects**: Caddy, Cloudflare, and browser HTTP clients terminate idle connections after 30 to 60 seconds, aborting partially completed operations.
3. **Cascading Crash Risk**: A memory spike (e.g., loading a corrupted 100MB Excel file) kills the web process, crashing the entire API for all active users.

ReconDesk solves this by decoupling ingestion and computation into a distributed asynchronous worker architecture powered by **Celery 5** and **Redis 7**.

---

## 2. Core Worker Architecture: Broker vs Result Backend

```mermaid
flowchart TD
    subgraph WebProcess ["FastAPI Web Server (EC2)"]
        APIEndpoint["API Endpoint (/api/reconciliation/start)"]
        RunTable["Insert Run (status='QUEUED')"]
    end

    subgraph RedisStore ["Redis 7 In-Memory Server (redis:6379)"]
        subgraph Queues ["7 Domain-Isolated Queues"]
            QRecon["Queue: reconciliation"]
            QImports["Queue: imports"]
            QFiling["Queue: filing"]
            QExports["Queue: exports"]
            QGSTN["Queue: gstn"]
            QNotif["Queue: notifications"]
            QMaint["Queue: maintenance"]
        end
        TaskBackend["Result Backend (Task State & Metadata)"]
    end

    subgraph WorkerFleet ["Celery Worker Fleet (EC2 / Multi-Process)"]
        Worker1["Worker Process 1<br/>(Pops from 'reconciliation')"]
        Worker2["Worker Process 2<br/>(Pops from 'imports', 'filing')"]
        Heartbeat["JobHeartbeat Thread (Every 30s)"]
    end

    subgraph Storage ["Database & Storage"]
        AuroraDB[("AWS Aurora PostgreSQL")]
        R2Buckets[("Cloudflare R2 Object Storage")]
    end

    APIEndpoint --> RunTable
    RunTable -->|celery.send_task()| QRecon
    
    QRecon -->|Pops Job| Worker1
    Worker1 --> Heartbeat
    Heartbeat -->|UPDATE last_heartbeat_at| AuroraDB

    Worker1 -->|Read & Match Records| AuroraDB
    Worker1 -->|Offload Payloads| R2Buckets
    Worker1 -->|Update State| TaskBackend
    Worker1 -->|Late Acknowledgment| QRecon
```

### Key Components Defined:
* **The Message Broker (Redis 7)**: Acts as the transport buffer. When an API endpoint enqueues a job, it serializes task arguments into a lightweight JSON payload and pushes it to a Redis queue.
* **The Result Backend (Redis 7)**: Stores task lifecycle state metadata (`PENDING`, `STARTED`, `SUCCESS`, `FAILURE`) and return values.
* **The Worker Fleet (Celery 5)**: Independent Python OS processes running in the background. Workers continuously poll Redis, claim pending tasks, execute the business logic, and commit results to AWS Aurora.

---

## 3. The 7 Domain-Isolated Queues & Task Routing

* **Source Location**: [`reliability.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/reliability.py#L22-L50)

### Why Queue Isolation Is Critical:
If an application uses a single shared queue, a surge of heavy, low-priority tasks (e.g. 50 users exporting massive Excel workbooks) will block high-priority, time-sensitive operations (e.g. statutory GSTR-1 filings approaching the midnight deadline). 

ReconDesk isolates tasks into **7 distinct queues**:

```python
QUEUE_RECONCILIATION = "reconciliation"
QUEUE_IMPORTS = "imports"
QUEUE_GSTN = "gstn"
QUEUE_FILING = "filing"
QUEUE_EXPORTS = "exports"
QUEUE_NOTIFICATIONS = "notifications"
QUEUE_MAINTENANCE = "maintenance"

TASK_ROUTES = {
    "worker.run_import_job": {"queue": QUEUE_IMPORTS},
    "worker.run_wizard_job": {"queue": QUEUE_IMPORTS},
    "worker.execute_reconciliation": {"queue": QUEUE_RECONCILIATION},
    "worker.process_filing_batch": {"queue": QUEUE_FILING},
}
```

#### Queue Priority & Allocation:
1. `filing`: Highest priority. Handles legal GSTR-1/3B OTP submissions and IRP e-invoicing.
2. `reconciliation`: Dedicated to computationally intensive L1–L6 matching algorithms.
3. `imports`: File uploads, parsing, and streaming database staging.
4. `gstn`: External government API communications and GSTR-2B downloads.
5. `exports`: CPU-heavy OpenPyXL workbook generation.
6. `notifications`: Asynchronous transactional email dispatch via Amazon SES.
7. `maintenance`: Daily Rule 37 alert scans and stuck job watchdog routines.

---

## 4. Worker Reliability Invariants & Crash Protection

Configured in [`celery_app.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/celery_app.py#L33-L45):

### 4.1 Late Acknowledgement (`task_acks_late = True`)
* **Default Celery Behavior (Dangerous)**: By default, Celery acknowledges a task to Redis **as soon as the worker pops it**. If the worker crashes mid-task (due to an out-of-memory error or server reboot), Redis considers the task completed, and the job disappears forever, leaving the customer stranded.
* **ReconDesk Configuration (`task_acks_late = True`)**: The worker acknowledges the message to Redis **only after the task has finished and written its output to Aurora**.

### 4.2 Worker Loss Rejection (`task_reject_on_worker_lost = True`)
If the worker process is abruptly killed by the OS (e.g. Linux OOM-killer), the Redis broker detects that the consumer socket dropped while holding an unacknowledged task. Redis automatically rejects the task back into the queue so that another worker process can pick it up.

### 4.3 Soft and Hard Execution Time Limits
Defined in [`reconciliation_task.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/reconciliation_task.py#L79-L80, L936-L937):
```python
_RECON_SOFT_LIMIT = 3600  # 1 hour
_RECON_HARD_LIMIT = 3900  # 1 hour 5 minutes

@celery_app.task(
    bind=True,
    name="worker.execute_reconciliation",
    soft_time_limit=_RECON_SOFT_LIMIT,
    time_limit=_RECON_HARD_LIMIT,
    max_retries=3,
    retry_backoff=True,
    retry_jitter=True,
)
```
* **Soft Time Limit (3,600s)**: Raises a catchable `SoftTimeLimitExceeded` exception inside Python. The worker catches this exception, gracefully cleans up database connections, updates the run status to `FAILED: Execution time limit exceeded`, and records the audit log.
* **Hard Time Limit (3,900s)**: If the Python process hangs at the C-level (e.g., an infinite loop in a native C library), the OS sends a `SIGKILL` to forcefully terminate the worker.

---

## 5. The Heartbeat Watchdog & Stuck Job Detector

Even with Celery reliability settings, catastrophic hardware freezes or worker thread lockups can cause a job to remain in `PROCESSING` status indefinitely.

### 5.1 Active Heartbeat Emission (`JobHeartbeat`)
* **Source Location**: [`reconciliation_task.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/reconciliation_task.py#L958)
During reconciliation execution, a background thread emits a heartbeat every **30 seconds**, executing an atomic database update:
```sql
UPDATE reconciliation_run 
SET last_heartbeat_at = NOW(), updated_at = NOW() 
WHERE id = :run_id;
```

### 5.2 The FastAPI Liveness Watchdog (`_stuck_job_tick`)
* **Source Location**: [`main.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py#L126-L206)

Every **300 seconds (5 minutes)**, the FastAPI application server runs a background watchdog:
```python
def _stuck_job_tick() -> None:
    timeout_seconds = getattr(settings, "JOB_HEARTBEAT_TIMEOUT_SECONDS", 900) # 15 minutes
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)

    # Find jobs stuck in active statuses whose heartbeat has gone silent
    stuck_runs = db.table("reconciliation_run") \
        .select("id, status, last_heartbeat_at") \
        .in_("status", ["MATCHING", "PROCESSING", "importing"]) \
        .execute()

    for run in stuck_runs.data or []:
        beat_dt = parse_iso(run.get("last_heartbeat_at"))
        if beat_dt < cutoff:
            # Mark run as FAILED and log to Dead Letter Queue
            db.table("reconciliation_run").update({
                "status": "FAILED",
                "status_message": f"Worker heartbeat timeout (> {timeout_seconds}s silent) — please retry",
                "error_category": "HEARTBEAT_TIMEOUT",
            }).eq("id", run["id"]).execute()

            record_failed_job(...)
            sentry_sdk.capture_message(f"Stuck job detected and reset: {run['id']}", level="error")
```

---

## 6. Real-World System Failure Modes & Recovery Sequences

---

### Scenario 1: The User Closes Their Browser Mid-Reconciliation
* **What Happens**: Because the matching task was dispatched asynchronously to Celery via `celery_app.send_task()`, the client's browser connection is completely irrelevant to worker execution. The Celery worker continues parsing, matching, and saving results to AWS Aurora and Cloudflare R2.
* **Recovery / UX**: When the user reopens ReconDesk and navigates to the dashboard, the SWR client queries `/api/reconcile/runs`, sees status `COMPLETED`, and renders the finalized results instantly.

---

### Scenario 2: The Web Server (FastAPI) Restarts
* **What Happens**: The web server and the worker fleet run as **independent Docker containers**. A restart of the `web` container (e.g. during a deployment) does not interrupt Celery workers. The worker continues executing. Active user HTTP requests fail during the 2-second container restart, but background reconciliations complete without data loss.

---

### Scenario 3: Redis In-Memory Broker Restarts
* **What Happens**: In [`docker-compose.prod.yml`](file:///Users/omkarkadam/Documents/ReconDesk/docker-compose.prod.yml#L49-L52), Redis mounts a persistent Docker volume (`redis_data:/data`). When Redis restarts, it reloads queued tasks from its snapshot file (`dump.rdb`). If an active task was executing in a worker, `task_acks_late=True` ensures the worker re-submits acknowledgment upon completion, or the watchdog catches and resets it.

---

### Scenario 4: The Celery Worker Crashes (Linux OOM-Killer)
* **What Happens**: If a massive file causes memory consumption to exceed the EC2 limit, the Linux kernel terminates the worker process with `SIGKILL`.
* **Automatic Safeguard**:
  1. Redis detects socket termination and immediately re-enqueues the unacknowledged task (`task_reject_on_worker_lost=True`).
  2. Docker Compose automatically restarts the worker container (`restart: always`).
  3. The worker re-claims the job. If it fails 3 consecutive times, `max_retries=3` is exhausted, and the task transitions to `record_failed_job()`.

---

### Scenario 5: A Task Is Enqueued Twice (Duplicate Execution)
* **What Happens**: Rapid double-clicking by a user or transient network retries can send duplicate task triggers.
* **The Guard (`claim_reconciliation_run`)**:
Implemented in [`reliability.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/reliability.py#L90-L130), the worker executes an **atomic conditional SQL update** before beginning work:
```sql
UPDATE reconciliation_run 
SET status = 'MATCHING', processing_started_at = NOW() 
WHERE id = :run_id AND status IN ('queued', 'QUEUED');
```
If the row is already in `MATCHING` status, the query updates 0 rows. The second worker immediately aborts execution, preventing duplicate ledger entries.

---

## 7. Celery & Redis Interview Questions & Exercises

### 7.1 Founder Self-Testing Questions
1. **Explain the difference between `task_acks_late=True` and default Celery acknowledgment.** Why is this setting critical for financial software?
2. **How does ReconDesk prevent queue starvation between Excel report exports and statutory GSTR-1 filings?**
3. **What is an atomic run claim, and how does it prevent race conditions when two workers pick up the same job?**
4. **Explain how the `stuck_job_detector` watchdog functions.** What happens if an EC2 worker suffers a silent kernel panic?
5. **Why is Python `pickle` serialization strictly forbidden in our Celery configuration?** What vulnerability does JSON serialization prevent?

### 7.2 Practical Verification Exercises
* **Exercise 1 (Celery Queue Routing)**: Open a terminal and run `celery -A app.worker.celery_app inspect active_queues`. Verify that the 7 domain queues are properly mapped to worker listeners.
* **Exercise 2 (Simulated Worker Failure)**: In a local test environment, trigger a reconciliation job and execute `kill -9 <celery_pid>`. Confirm that the task remains in Redis and resumes upon restarting the worker.
