# Chapter 16: Production Incident Playbooks, Diagnostics & Site Reliability Engineering (SRE)

```
==================================================================================================
RECONDESK FOUNDER TECHNICAL MASTERY SERIES
Stage 5: Infrastructure, Security & Reliability
Chapter 16: Production Incident Playbooks, Diagnostics & SRE
Evidentiary Baseline: release/v1.5.2-rc1 | Active Monorepo: recondesk-backend & recondesk-frontend
==================================================================================================
```

---

## 1. Executive Summary & SRE Philosophy

In enterprise fintech and statutory tax platforms, uptime and reliability are not merely conveniences—they represent legal compliance and financial survival for your customers. When an enterprise CFO or chartered accountant uses ReconDesk on the 10th or 11th of the month to file GSTR-1, or on the 18th to 20th to finalize GSTR-3B Input Tax Credit claims, **downtime directly causes statutory tax penalties, cash-flow seizure, and loss of vendor trust.**

As a technical founder, when a production alert triggers at 02:00 AM, you cannot afford panic, guesswork, or destructive trial-and-error. You need an **evidence-based, disciplined mental model** backed by concrete operational runbooks.

This chapter details **20 production incident playbooks** tailored precisely to ReconDesk's micro-architecture (FastAPI, AWS Aurora Serverless v2 PostgreSQL, Celery 5 distributed workers, Redis 7 broker, Cloudflare R2 object storage, Caddy 2 reverse proxy, and Next.js 14). Every playbook provides:
1. **Symptom & Alert Signals**: Exact HTTP status codes, log signatures, and Sentry alerts.
2. **Blast Radius & Severity**: Impact classification (P1 Critical to P3 Low).
3. **Underlying Architectural Mechanism**: The root cause at the operating system, network, database, or Python runtime level.
4. **Safe Read-Only Diagnostic Commands**: CLI commands, SQL queries, and log inspections that gather ground truth without risking data loss.
5. **Immediate Mitigation Procedures**: Steps to restore service rapidly without mutating historical financial records.
6. **Root Cause Analysis (RCA) & Long-Term Prevention**: Code changes, architectural guards, or configuration hardening.

---

## 2. Production Diagnostic Architecture & Safe Access

### 2.1 The Golden Rules of Production Troubleshooting
1. **Never mutate data blindly in production**: Never run raw SQL `UPDATE` or `DELETE` statements without a transaction wrapper (`BEGIN; ... ROLLBACK;`) and an explicit `WHERE` clause tested with a prior `SELECT COUNT(*)`.
2. **Observe before restarting**: Do not immediately restart containers or instances when a failure occurs. A restart destroys volatile state: active TCP socket queues, core dumps, thread dumps, memory fragmentation profiles, and uncommitted Celery worker memory. Inspect first, capture state, then restart.
3. **Observe Least Privilege & PII Protection**: Never print customer financial invoices, PANs, GSTINs, or auth tokens into terminal screens during live screen-shares or incident triage. ReconDesk enforces log scrubbing in [`recondesk-backend/app/filing/log_safety.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/filing/log_safety.py).

### 2.2 Health Check Diagnostics (`/health`)
ReconDesk provides a multi-subsystem liveness and readiness probe at `/health` implemented in [`recondesk-backend/app/main.py:803-920`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py#L803-L920). It queries all four critical dependencies concurrently with a strict 2.0-second timeout:
```json
{
  "status": "ok",
  "version": "1.5.2-rc1",
  "git_commit_sha": "a1b2c3d4",
  "uptime_seconds": 348120,
  "supabase": "ok",
  "r2": "ok",
  "aurora": {
    "status": "ok",
    "healthy": true,
    "latency_ms": 2.14,
    "database": "aurora_postgresql"
  },
  "worker": {
    "status": "ok",
    "healthy": true,
    "broker": "redis"
  },
  "environment": "production",
  "timestamp": "2026-10-16T00:25:00.000000+00:00"
}
```
If any dependency exceeds 2.0 seconds or throws an unhandled exception, `status` drops to `"degraded"` and HTTP monitoring flags the failure instantly.

---

## 3. The 20 Production Incident Playbooks

```
+----------------------------------------------------------------------------------------------------+
|                                    RECONDESK INCIDENT MATRIX                                       |
+-----+-------------------------------------------------------+----------+---------------------------+
| ID  | Incident Scenario                                     | Severity | Primary Component         |
+-----+-------------------------------------------------------+----------+---------------------------+
| 01  | API HTTP 502 / 504 Gateway Timeout                    | P1       | Caddy / Uvicorn Workers   |
| 02  | Celery Worker Stalled / Jobs Stuck in PROCESSING      | P1       | Celery / Worker Watchdog  |
| 03  | Aurora PostgreSQL Connection Pool Exhaustion          | P1       | SQLAlchemy QueuePool      |
| 04  | Database Migration Lock Wedge on Deployment           | P1       | Alembic / pg_locks        |
| 05  | Redis Broker OOM / Connection Refused                 | P1       | Redis 7 In-Memory Cache   |
| 06  | Celery Worker OOMKilled by Linux Kernel               | P2       | CPython Memory / Pandas   |
| 07  | Cloudflare R2 Presigned Upload / Parse Failure        | P2       | R2 Storage / S3 SDK       |
| 08  | Razorpay Webhook Verification Failure / Double Credit | P1       | HMAC-SHA256 / Webhook     |
| 09  | Fail-Closed Staging Guard Abort on Boot               | P1       | Staging Guard / Settings  |
| 10  | GSTN API 401 Unauthorized / Token Expiry              | P2       | GSTN Connector / Sandbox  |
| 11  | Reconciliation L1-L6 Engine Precision Degradation    | P2       | Matcher / RapidFuzz SIMD  |
| 12  | Rule 37 180-Day Background Job CPU Saturation         | P2       | Asyncio Background Task   |
| 13  | Tenant Data Isolation Leak Attempt (IDOR Probe)       | P1       | RBAC / Dependency Guard   |
| 14  | PDF Export Memory Spike (ReportLab OOM)               | P3       | Export Worker / Buffer    |
| 15  | Aurora Serverless v2 ACU Scaling Lag                  | P2       | AWS RDS Aurora v2 Scaling |
| 16  | Next.js Frontend Hydration Error / Blank View         | P2       | React DOM Virtualization  |
| 17  | CORS Preflight (OPTIONS 403 / 405) Failure            | P2       | CORSMiddleware Origins    |
| 18  | PostgREST-to-SQL Translation Exception               | P2       | AuroraClient PostgREST    |
| 19  | Dual Remote Push Desynchronization (Frontend/Backend) | P2       | Git Push / Deployment     |
| 20  | Sentry Event Flooding / Log Safety Scrubbing Failure  | P3       | Sentry SDK / Log Safety   |
+-----+-------------------------------------------------------+----------+---------------------------+
```

---

### Incident 01: API HTTP 502 / 504 Gateway Timeout (Worker Starvation)

#### Symptoms & Triggers
- Users report "502 Bad Gateway" or "504 Gateway Timeout" on large endpoints (`/api/v1/reconciliation/run`, `/api/v1/reports/export`).
- CloudWatch / Caddy reverse proxy logs show upstream connection refused or upstream timed out after 60s.
- Sentry captures `ClientDisconnected` or `TimeoutError`.

#### Underlying Mechanism
FastAPI runs under Uvicorn with a fixed number of worker processes (typically 2 to 4 per container). If a long-running synchronous calculation (such as parsing a 50MB Excel spreadsheet with 100,000 rows or compiling complex SQL without `asyncio.to_thread`) runs directly on the async event loop, **the entire event loop freezes.** No other incoming requests or health check pings can be processed, causing Caddy to time out.

#### Diagnostic Commands (Safe, Read-Only)
```bash
# 1. Check container CPU and memory consumption
docker stats --no-stream

# 2. Check Uvicorn active worker processes and threads
ps aux | grep uvicorn

# 3. Check Caddy reverse proxy logs for upstream response latency
docker compose logs --tail=100 caddy | grep -E "502|504"

# 4. Check active open connections on backend port 8000
netstat -an | grep 8000 | awk '{print $6}' | sort | uniq -c
```

#### Immediate Mitigation
1. If all Uvicorn workers are blocked by CPU lockup, issue a zero-downtime graceful reload:
   ```bash
   docker compose kill -s HUP backend
   ```
2. Verify that the health probe responds:
   ```bash
   curl -I http://127.0.0.1:8000/health
   ```

#### Permanent Remediation
Ensure that **zero CPU-bound or synchronous I/O operations** execute on the main event loop. Any file parsing must be offloaded to Celery queue `imports`, and synchronous database queries must be wrapped in `asyncio.to_thread()` as enforced in [`recondesk-backend/app/main.py:211`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py#L211).

---

### Incident 02: Celery Worker Stalled / Jobs Stuck in `PROCESSING`

#### Symptoms & Triggers
- Users observe the reconciliation progress bar stuck at "Processing (45%)" indefinitely.
- The `reconciliation_run` table has rows with `status = 'PROCESSING'` where `updated_at` is older than 30 minutes.

#### Underlying Mechanism
A worker executing a memory-heavy matching run was either abruptly killed by the OS kernel OOM killer (`SIGKILL`), the host rebooted, or the task encountered an unhandled native C-extension deadlock (e.g. SIMD Levenshtein edge case). Because `SIGKILL` cannot be trapped by Python, the worker could not execute its `finally:` block or update the database status to `FAILED`.

#### Diagnostic Commands (Safe, Read-Only)
```bash
# 1. Inspect stuck runs directly in Aurora PostgreSQL
psql $AURORA_DATABASE_URL -c "
SELECT id, firm_id, status, processing_started_at, updated_at, 
       NOW() - updated_at AS silence_duration 
FROM reconciliation_run 
WHERE status = 'PROCESSING' 
ORDER BY updated_at ASC LIMIT 10;
"

# 2. Check Celery active workers and currently active tasks
docker compose exec backend celery -A app.worker.celery inspect active

# 3. Check Linux kernel dmesg for OOMKilled worker processes
dmesg -T | grep -E -i "killed process|oom_reaper|celery"
```

#### Immediate Mitigation
ReconDesk features an automated internal watchdog: `stuck_job_detector()` in [`recondesk-backend/app/main.py:126-206`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py#L126-L206). It scans every 300 seconds and marks any run silent for > 900 seconds as `FAILED` with error category `HEARTBEAT_TIMEOUT`.
To force immediate recovery manually:
```sql
UPDATE reconciliation_run 
SET status = 'FAILED', 
    status_message = 'Worker stalled (manual recovery) - please retry',
    error_category = 'MANUAL_STALL_RECOVERY',
    updated_at = NOW()
WHERE id = '<STUCK_RUN_ID>' AND status = 'PROCESSING';
```

---

### Incident 03: Aurora Connection Pool Exhaustion (`QueuePool limit reached`)

#### Symptoms & Triggers
- Backend logs show: `sqlalchemy.exc.TimeoutError: QueuePool limit of size 20 overflow 10 reached, connection timed out, timeout 30.00`.
- All API requests begin throwing HTTP 500 errors.

#### Underlying Mechanism
In [`recondesk-backend/app/aurora.py:125-155`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/aurora.py#L125-L155), the SQLAlchemy engine is configured with `pool_size=20, max_overflow=10`. If incoming traffic spikes or an endpoint opens a database session without properly closing it in a `finally:` block or context manager (`with SessionLocal() as db:`), connections leak until all 30 pool slots are occupied. Subsequent requests queue up and time out after 30 seconds.

#### Diagnostic Commands (Safe, Read-Only)
```sql
-- Check total active connections and states in Aurora PostgreSQL
SELECT state, count(*) 
FROM pg_stat_activity 
GROUP BY state;

-- Find longest-running active queries holding connections
SELECT pid, age(clock_timestamp(), query_start), state, query 
FROM pg_stat_activity 
WHERE state != 'idle' 
ORDER BY age(clock_timestamp(), query_start) DESC 
LIMIT 10;
```

#### Immediate Mitigation
1. Terminate orphaned idle-in-transaction connections holding locks:
   ```sql
   SELECT pg_terminate_backend(pid) 
   FROM pg_stat_activity 
   WHERE state = 'idle in transaction' 
     AND age(clock_timestamp(), state_change) > interval '2 minutes';
   ```
2. Restart backend container to re-initialize connection pools cleanly:
   ```bash
   docker compose restart backend
   ```

#### Permanent Remediation
Audit all database dependencies in [`recondesk-backend/app/dependencies.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/dependencies.py) to guarantee that the `get_db()` generator pattern uses `yield db` wrapped in `finally: db.close()`.

---

### Incident 04: Database Migration Lock Wedge on Deployment

#### Symptoms & Triggers
- Deployment hangs for exactly 180 seconds during container startup.
- Logs show: `Startup ERROR: Alembic subprocess timed out after 180s!`.
- The new container fails health checks and restarts in a crash loop.

#### Underlying Mechanism
During deployment, [`recondesk-backend/app/main.py:297-344`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py#L297-L344) executes `alembic upgrade head`. If an Alembic migration executes an `ALTER TABLE` statement (such as adding a column or modifying an index) on a table currently being queried by a long-running background worker, PostgreSQL requests an `ACCESS EXCLUSIVE` lock. PostgreSQL queues this lock request behind the read queries, and all subsequent read/write queries queue behind Alembic, creating a total database lock wedge.

#### Diagnostic Commands (Safe, Read-Only)
ReconDesk implements automated lock diagnosis in [`recondesk-backend/app/main.py:260-285`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py#L260-L285) via `_log_db_locks()`. Run this query to inspect conflicting locks:
```sql
SELECT l.pid, l.locktype, l.mode, l.granted, a.query, age(clock_timestamp(), a.query_start) AS duration
FROM pg_locks l
JOIN pg_stat_activity a ON l.pid = a.pid
WHERE a.pid <> pg_backend_pid() AND a.state <> 'idle';
```

#### Immediate Mitigation
1. Identify the blocking query PID holding the lock.
2. Cancel the query gracefully:
   ```sql
   SELECT pg_cancel_backend(<BLOCKING_PID>);
   ```
3. If the query does not respond within 10 seconds, terminate the backend connection:
   ```sql
   SELECT pg_terminate_backend(<BLOCKING_PID>);
   ```
4. Alembic will immediately acquire its lock and complete the migration in milliseconds.

---

### Incident 05: Redis Broker OOM / Connection Refused

#### Symptoms & Triggers
- Celery tasks cannot be dispatched; API calls to start reconciliation return HTTP 500.
- Logs show: `redis.exceptions.ConnectionError: Error 111 connecting to redis:6379. Connection refused.` or `OOM command not allowed when used memory > 'maxmemory'`.

#### Underlying Mechanism
Redis is utilized both as a Celery message broker and as an ephemeral cache. If Celery task result backends (`celery_results`) store massive payloads (such as thousands of full invoice JSON dictionaries) without a Time-To-Live (TTL) expiration, or if Redis memory is exhausted, Redis stops accepting new writes.

#### Diagnostic Commands (Safe, Read-Only)
```bash
# 1. Connect to Redis container and inspect memory usage
docker compose exec redis redis-cli info memory

# 2. Inspect key space and largest keys
docker compose exec redis redis-cli info keyspace
docker compose exec redis redis-cli --bigkeys

# 3. Check Redis queue lengths
docker compose exec redis redis-cli llen reconciliation
docker compose exec redis redis-cli llen imports
```

#### Immediate Mitigation
1. Purge ephemeral cache keys (NEVER flush database 0 if tasks are queued):
   ```bash
   docker compose exec redis redis-cli -n 1 flushdb  # Flush cache database only
   ```
2. Verify Redis memory policy is configured to `volatile-lru` or `allkeys-lru` in `redis.conf`:
   ```bash
   docker compose exec redis redis-cli config set maxmemory-policy allkeys-lru
   ```

---

### Incident 06: Celery Worker OOMKilled by Linux Kernel

#### Symptoms & Triggers
- Worker container exits with code `137` (128 + 9 = `SIGKILL`).
- Sentry captures `WorkerLostError: Worker exited prematurely: signal 9 (SIGKILL) Job: app.worker.tasks.reconcile_tenant`.

#### Underlying Mechanism
CPython does not immediately release freed heap memory back to the operating system due to memory fragmentation and pymalloc arena structures. When a worker processes 50 consecutive reconciliation runs, resident set size (RSS) steadily accumulates. When RSS exceeds host RAM limits (e.g. 2GB or 4GB EC2 instance limits), the Linux kernel OOM killer terminates the worker process.

#### Diagnostic Commands (Safe, Read-Only)
```bash
# 1. Check system dmesg for OOM Kill invocation
dmesg -T | grep -E "Out of memory|killed process"

# 2. Check Celery configuration for memory limits
grep -rn "worker_max_memory_per_child" recondesk-backend/app/worker/
```

#### Immediate Mitigation & Architectural Guardrail
ReconDesk protects against this in [`recondesk-backend/app/worker/celery.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/celery.py) by setting:
```python
worker_max_memory_per_child = 300_000  # 300 MB maximum RAM before graceful replacement
worker_max_tasks_per_child = 50        # Recycle worker process every 50 tasks
```
This forces Celery to automatically terminate child worker processes after 50 tasks and spawn a clean replacement with zero memory bloat.

---

### Incident 07: Cloudflare R2 Presigned Upload / Parse Failure

#### Symptoms & Triggers
- Users report file uploads hanging at 0% or failing with `Network Error / 403 Forbidden`.
- Invoices cannot be processed; backend reports `NoSuchKey` or `ClientError: 404`.

#### Underlying Mechanism
Uploads use presigned S3 URLs generated by [`recondesk-backend/app/utils/storage.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/utils/storage.py) directed to Cloudflare R2 object storage. If the system clock on the EC2 host drifts by more than 15 minutes, AWS SigV4 signatures fail validation. Alternatively, if CORS is misconfigured on the R2 bucket, browsers block client-side `PUT` requests.

#### Diagnostic Commands (Safe, Read-Only)
```bash
# 1. Check EC2 host time synchronization against NTP
timedatectl status

# 2. Test R2 endpoint reachability via safe probe
curl -I https://<CLOUDFLARE_ACCOUNT_ID>.r2.cloudflarestorage.com

# 3. Check health probe status for R2
curl -s http://127.0.0.1:8000/health | jq .r2
```

#### Immediate Mitigation
1. Synchronize host clock immediately:
   ```bash
   sudo chronyc makestep
   ```
2. Verify R2 credentials (`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`) in `.env`.

---

### Incident 08: Razorpay Webhook Verification Failure / Double Credit

#### Symptoms & Triggers
- Customer completes payment on Razorpay checkout modal, but account status remains `free` / `inactive`.
- Backend logs show: `Razorpay webhook signature verification failed`.

#### Underlying Mechanism
Razorpay transmits an `X-Razorpay-Signature` header calculated using HMAC-SHA256 over the raw request payload using `RAZORPAY_WEBHOOK_SECRET`. If the webhook handler parses the request body as JSON before computing the hash, whitespace or unicode formatting alterations invalidate the signature. ReconDesk enforces constant-time byte verification over `await request.body()` in [`recondesk-backend/app/routers/billing.py:110-145`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/routers/billing.py#L110-L145).

#### Diagnostic Commands (Safe, Read-Only)
```bash
# 1. Inspect recent billing transactions in database
psql $AURORA_DATABASE_URL -c "
SELECT id, firm_id, order_id, payment_id, status, amount_paise, created_at 
FROM billing_transactions 
ORDER BY created_at DESC LIMIT 5;
"

# 2. Check billing router logs for signature mismatch
docker compose logs --tail=100 backend | grep -i "razorpay"
```

#### Immediate Mitigation
Verify payment status directly via Razorpay dashboard using the `order_id`. If payment is captured on Razorpay, activate the subscription manually via administrative command:
```sql
UPDATE firms 
SET subscription_tier = 'PRO', 
    subscription_status = 'ACTIVE', 
    subscription_expires_at = NOW() + interval '1 year' 
WHERE id = '<FIRM_ID>';
```

---

### Incident 09: Fail-Closed Staging Guard Abort on Boot

#### Symptoms & Triggers
- Staging container terminates immediately on startup with exit code `1`.
- Log output: `CRITICAL: Staging Guard violation: STAGING environment is pointed to production endpoint! Aborting startup.`

#### Underlying Mechanism
ReconDesk implements an automated fail-closed safety guard in [`recondesk-backend/app/staging_guard.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/staging_guard.py). During startup in [`recondesk-backend/app/main.py:350-375`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py#L350-L375), if `APP_ENV=staging`, the guard scans all database connection strings, S3 buckets, and API URLs. If any URL matches `api.recondesk.in` or production Aurora cluster hostnames, it immediately terminates the process with `sys.exit(1)` to protect customer production data.

#### Diagnostic Commands (Safe, Read-Only)
```bash
# Inspect environment variables for staging configuration errors
grep -E "APP_ENV|AURORA_DATABASE_URL|DATABASE_URL" .env
```

#### Remediation
Update `.env` on the staging host to ensure it targets `recondesk-staging` database and staging R2 buckets. Never bypass the Staging Guard.

---

### Incident 10: GSTN API 401 Unauthorized / Token Expiry

#### Symptoms & Triggers
- Automated GSTR-2B or IMS imports fail with `401 Unauthorized` or `Invalid Auth Token`.
- Error code in response: `TEC4001` (Token Expired) or `SEC4002` (IP Not Whitelisted).

#### Underlying Mechanism
GSTN session tokens expire after 360 minutes (6 hours) or 24 hours depending on the GSP (GST Suvidha Provider). If the automated refresh routine fails or if the outbound public IP of the EC2 instance changed due to a restart without an Elastic IP (EIP), GSTN's firewall blocks requests.

#### Diagnostic Commands (Safe, Read-Only)
```bash
# 1. Verify outbound public IP of the EC2 host
curl -s https://checkip.amazonaws.com

# 2. Check GSTN token records in database
psql $AURORA_DATABASE_URL -c "
SELECT gstin, token_expiry, updated_at 
FROM gstn_auth_tokens 
ORDER BY updated_at DESC LIMIT 5;
"
```

#### Remediation
1. Verify that the Elastic IP associated with the EC2 host matches the IP registered with the GST Suvidha Provider.
2. Trigger the token refresh flow using the stored encrypted username and auth app secret.

---

### Incident 11: Reconciliation L1-L6 Engine Precision Degradation

#### Symptoms & Triggers
- Customer flags that an invoice clearly present in both PR and GSTR-2B was placed into `UNMATCHED_PR` instead of `EXACT_MATCH`.
- Audit logs report unexpected drops in match confidence scores.

#### Underlying Mechanism
The matching pipeline in [`recondesk-backend/app/services/matcher.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/matcher.py) enforces strict candidate blocking and normalization. If a supplier uses an unusual invoice number delimiter (e.g. `INV/2026:00492`) that was stripped improperly, or if the return period crossing guard rejects the match because the purchase date is outside the 6-month tolerance window, the match will be blocked.

#### Diagnostic Commands (Safe, Read-Only)
Run the isolated offline audit script on the specific pair:
```bash
pytest recondesk-backend/tests/test_audit_2k.py -k "test_matcher_edge_cases" -v
```

#### Remediation
Inspect candidate blocking output in `_get_narrowed_candidates()`. If a new legitimate delimiter is discovered, add it to `clean_invoice_number()` and run the 296-test suite before deploying.

---

### Incident 12: Rule 37 180-Day Background Job CPU Saturation

#### Symptoms & Triggers
- Every 5 minutes, API response latency spikes for 30 seconds.
- CPU usage hits 100% periodically.

#### Underlying Mechanism
In [`recondesk-backend/app/main.py:207-241`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py#L207-L241), the `stuck_job_detector()` background loop runs every 300 seconds. After checking stuck jobs, it executes `run_rule37_alert_scan()` and `run_scorecard_daily_rebuild()`. If these jobs query all historical invoices across all tenants without pagination, they saturate CPU and RAM.

#### Diagnostic Commands (Safe, Read-Only)
```bash
# Monitor Uvicorn process CPU spikes in real-time
top -b -n 1 -p $(pgrep -d',' -f uvicorn)
```

#### Remediation
Ensure that daily scans only evaluate invoices within the active 180-day window (`payment_status = 'UNPAID' AND invoice_date >= NOW() - interval '210 days'`) using indexed queries on `(firm_id, payment_status, invoice_date)`.

---

### Incident 13: Tenant Data Isolation Leak Attempt (IDOR Probe)

#### Symptoms & Triggers
- Sentry captures `HTTP 403 Forbidden: Tenant isolation breach attempt`.
- Security logs show a user requesting an entity (`firm_id` or `run_id`) that does not belong to their authenticated identity.

#### Underlying Mechanism
In [`recondesk-backend/app/dependencies.py:130-185`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/dependencies.py#L130-L185), `get_current_firm()` enforces multi-tenancy verification. If an attacker tampers with URL parameters to guess sequential UUIDs, the dependency blocks the request and triggers a security breadcrumb.

#### Diagnostic Commands (Safe, Read-Only)
```bash
# Search logs for unauthorized tenant cross-access attempts
docker compose logs --tail=500 backend | grep -i "tenant isolation breach"
```

#### Remediation
1. Verify that the requesting user's IP is flagged by fail2ban or Cloudflare WAF.
2. Confirm that all endpoints accept `firm_id` exclusively through validated route dependencies, never raw unverified request bodies.

---

### Incident 14: PDF Export Memory Spike (ReportLab OOM)

#### Symptoms & Triggers
- Celery worker crashes when generating a consolidated GSTR-3B audit report with 50,000 line items.
- Task failed with `MemoryError`.

#### Underlying Mechanism
ReportLab renders PDF documents in memory before streaming bytes. Building a tabular PDF with tens of thousands of rows causes Python objects for canvas flowables to exceed resident memory limits.

#### Diagnostic Commands (Safe, Read-Only)
```bash
docker compose logs --tail=100 backend | grep -i "reportlab"
```

#### Remediation
Enforce export pagination or format restrictions: for datasets exceeding 5,000 line items, require Excel (`.xlsx`) or compressed CSV (`.zip`) streaming exports rather than single PDF compilation.

---

### Incident 15: Aurora Serverless v2 ACU Scaling Lag

#### Symptoms & Triggers
- On the 20th of the month at 16:00 IST (peak GSTR-3B filing rush), database latency spikes from 2ms to 450ms.
- CloudWatch reports CPU utilization at 100% on the writer instance.

#### Underlying Mechanism
Aurora Serverless v2 scales dynamically between minimum and maximum ACU (Aurora Capacity Units, where 1 ACU = 2GB RAM). If minimum ACU is set too low (e.g. 0.5 ACU = 1GB RAM), scaling up to 16 ACU under an abrupt 10x traffic spike can take up to 60 seconds, during which database queues saturate.

#### Diagnostic Commands (Safe, Read-Only)
```bash
# Query current Aurora database buffer pool hit ratio
psql $AURORA_DATABASE_URL -c "
SELECT round(100.0 * sum(blks_hit) / (sum(blks_hit) + sum(blks_read)), 2) AS cache_hit_ratio 
FROM pg_stat_database;
"
```

#### Remediation
During statutory filing windows (10th–20th of each month), pre-scale minimum ACU via AWS CLI:
```bash
aws rds modify-db-cluster \
    --db-cluster-identifier recondesk-production \
    --serverless-v2-scaling-configuration MinCapacity=4.0,MaxCapacity=32.0
```

---

### Incident 16: Next.js Frontend Hydration Error / Blank View

#### Symptoms & Triggers
- User visits the reconciliation screen; page flashes and renders completely blank white.
- Browser console reports: `Error: Hydration failed because the initial UI does not match what was rendered on the server.`

#### Underlying Mechanism
In Next.js 14 App Router, if a client component renders dates, currency symbols, or window dimensions directly during initial SSR rendering, the server output (evaluated in UTC) differs from the browser output (evaluated in IST), causing React hydration to collapse.

#### Diagnostic Commands (Safe, Read-Only)
Inspect browser developer console for the mismatched HTML attributes.

#### Remediation
In [`recondesk-frontend/`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-frontend), wrap dynamic client rendering in `useMounted()` hooks or configure `suppressHydrationWarning` on date-display containers.

---

### Incident 17: CORS Preflight (OPTIONS 403 / 405) Failure

#### Symptoms & Triggers
- Frontend requests fail with: `Access to XMLHttpRequest has been blocked by CORS policy: Response to preflight request doesn't pass access control check.`

#### Underlying Mechanism
In [`recondesk-backend/app/main.py:48-75`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py#L48-L75), `CORSMiddleware` defines `allow_origins`. If a user accesses the platform via a new custom domain or preview URL that is not included in `ALLOWED_ORIGINS`, preflight `OPTIONS` requests are rejected with HTTP 400/403.

#### Diagnostic Commands (Safe, Read-Only)
```bash
# Test CORS preflight response manually using curl
curl -I -X OPTIONS http://127.0.0.1:8000/api/v1/health \
  -H "Origin: https://app.recondesk.in" \
  -H "Access-Control-Request-Method: GET"
```

#### Remediation
Add authorized production domains to `ALLOWED_ORIGINS` in environment configuration and restart the backend.

---

### Incident 18: PostgREST-to-SQL Translation Exception

#### Symptoms & Triggers
- Specific search filter queries return HTTP 500.
- Logs show: `AuroraClient: Unsupported operator or query syntax: ...`.

#### Underlying Mechanism
In [`recondesk-backend/app/aurora_client.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/aurora_client.py), `AuroraClient` translates Supabase query builder syntax (`.eq()`, `.in_()`, `.ilike()`) into parameterized SQL. If a newly introduced frontend query uses an unsupported chaining method (e.g. `.contains()` or `.overlaps()`), the adapter throws a translation exception.

#### Diagnostic Commands (Safe, Read-Only)
```bash
# Search logs for AuroraClient translation failures
docker compose logs --tail=100 backend | grep -i "AuroraClient"
```

#### Remediation
Expand `AuroraClient` in `aurora_client.py` to support the required query builder operator, write an accompanying unit test in `tests/test_aurora_client.py`, and deploy.

---

### Incident 19: Dual Remote Push Desynchronization

#### Symptoms & Triggers
- Backend deployment succeeds on EC2, but frontend deployment on Vercel still runs older code, or vice-versa.
- API contract mismatch causes frontend errors: `Cannot read properties of undefined (reading 'taxable_paise')`.

#### Underlying Mechanism
Per [AGENTS.md](file:///Users/omkarkadam/Documents/ReconDesk/AGENTS.md), ReconDesk uses two distinct Git remotes:
1. Backend: `origin main` (`recondesk-backend.git`)
2. Frontend: `frontend main` (`recondesk-frontend.git`)
If an engineer pushes to `origin` but forgets `frontend`, the monorepo remotes desynchronize.

#### Diagnostic Commands (Safe, Read-Only)
```bash
# Check remote synchronization status
git status
git log origin/main..frontend/main --oneline
git log frontend/main..origin/main --oneline
```

#### Remediation
Always execute the automated synchronization script:
```bash
./push.sh "Synchronize frontend and backend deployment"
```

---

### Incident 20: Sentry Event Flooding / Log Safety Scrubbing Failure

#### Symptoms & Triggers
- Sentry monthly quota exhausted in 3 hours.
- Risk of sensitive financial data (customer GSTINs, invoice totals) appearing in Sentry breadcrumbs.

#### Underlying Mechanism
If an error occurs inside a tight loop processing 10,000 invoices, sending an unthrottled Sentry exception on every iteration will exhaust error budgets and potentially log unscrubbed local variables.

#### Diagnostic Commands (Safe, Read-Only)
```bash
# Check Sentry initialization settings
grep -rn "sentry_sdk.init" recondesk-backend/app/main.py
```

#### Remediation
ReconDesk mandates strict PII scrubbing hooks in [`recondesk-backend/app/main.py:116-118`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py#L116-L118):
```python
before_send=sentry_scrub_event,
before_send_transaction=sentry_scrub_transaction,
before_breadcrumb=sentry_scrub_breadcrumb,
```
These hooks, implemented in [`recondesk-backend/app/filing/log_safety.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/filing/log_safety.py), strip financial values, PANs, and auth tokens before payloads ever leave the server.

---

## 4. Founder Technical Interview Defense & Exercises

### Q1: "How do you detect and recover from stalled or dead background workers without risking duplicate processing?"
**Model Answer:**
> "In ReconDesk, we solve this via a combination of heartbeat watchdogs and atomic run claiming. 
> Every active worker task writes a heartbeat timestamp (`last_heartbeat_at`) to the database every 60 seconds while processing batches. In our backend, an asynchronous background watchdog (`stuck_job_detector()` in `main.py`) wakes up every 300 seconds. If a job's heartbeat has gone silent for more than 900 seconds—which happens if an EC2 instance reboots or the Linux kernel issues a `SIGKILL` due to OOM—the watchdog transitions the job to `FAILED` with error category `HEARTBEAT_TIMEOUT` and records a dead-letter entry.
> To prevent duplicate processing or split-brain execution, worker tasks use conditional atomic state transitions (`UPDATE reconciliation_run SET status = 'PROCESSING' WHERE id = :id AND status = 'QUEUED'`). If two workers attempt to claim the same job, exactly one succeeds and the other aborts."

### Practical Exercise
1. Run the test suite for Celery reliability:
   ```bash
   pytest recondesk-backend/tests/ -k "test_worker or test_stuck_job"
   ```
2. Inspect the watchdog implementation in [`recondesk-backend/app/main.py:126-206`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py#L126-L206) and trace how dead-letter payloads are recorded.
