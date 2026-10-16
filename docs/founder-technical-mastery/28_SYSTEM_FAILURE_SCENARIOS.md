# Chapter 28: System Failure Scenarios, Disaster Recovery & High-Availability Resilience

```
==================================================================================================
RECONDESK FOUNDER TECHNICAL MASTERY SERIES
Stage 5: Infrastructure, Security & Reliability
Chapter 28: System Failure Scenarios, Disaster Recovery & High-Availability Resilience
Evidentiary Baseline: release/v1.5.2-rc1 | Active Monorepo: recondesk-backend & recondesk-frontend
==================================================================================================
```

---

## 1. Executive Summary: Designing for Inevitable Failure

In distributed systems and financial cloud software, Murphy’s Law is an absolute certainty: **everything that can fail will eventually fail, and usually at the worst possible moment (e.g. 11:30 PM on the 20th of the month during GSTR-3B filing).**

Networks partition. Cloud regions lose power. Upstream government APIs return HTTP 503 Service Unavailable. Disk drives corrupt. Third-party payment gateways experience webhook delivery backlogs. Subcontractors upload corrupted spreadsheets containing malicious formulas.

A junior engineer assumes that systems work and writes code for the "happy path."
**A Principal Software Architect and CTO assumes that systems are broken by default and builds defense-in-depth, graceful degradation, fail-closed security guards, and automated self-healing mechanisms.**

This chapter analyzes **10 catastrophic system failure scenarios** in ReconDesk, detailing the exact mechanical failure mode, blast radius, automatic failover behavior, disaster recovery runbooks, and recovery point/time objectives (RPO/RTO).

---

## 2. Disaster Recovery Targets: RPO & RTO

```
+----------------------------------------------------------------------------------------------------+
|                                RECONDESK DISASTER RECOVERY TARGETS                                 |
+--------------------------+-----------------------+-----------------------+-------------------------+
| Subsystem                | RPO (Recovery Point)  | RTO (Recovery Time)   | DR Strategy             |
+--------------------------+-----------------------+-----------------------+-------------------------+
| Core Relational Ledger   | <= 5 minutes          | <= 15 minutes         | Aurora Multi-AZ + PITR  |
| Invoice Files (R2 / S3)  | 0 seconds (RPO=0)     | <= 5 minutes          | Dual-Region Replication |
| Redis Ephemeral Cache    | Can lose 100% of data | <= 60 seconds         | Instant Cold Flush/Init |
| Celery Async Queue       | <= 1 task             | <= 2 minutes          | Redis AOF + Late Ack    |
| Web API (FastAPI / Caddy)| 0 seconds (Stateless) | <= 30 seconds         | Container Auto-Restart  |
+--------------------------+-----------------------+-----------------------+-------------------------+
```
- **RPO (Recovery Point Objective)**: The maximum acceptable data loss measured in time. In ReconDesk, core financial records use continuous AWS Aurora storage backups with a 5-minute Point-In-Time Recovery (PITR) window.
- **RTO (Recovery Time Objective)**: The maximum allowable downtime to restore service. The target is under 15 minutes for full disaster recovery.

---

## 3. The 10 Critical Failure Scenarios

```
+----------------------------------------------------------------------------------------------------+
|                                    FAILURE SCENARIO TAXONOMY                                       |
+-----+-------------------------------------------------------+--------------------------------------+
| ID  | Failure Scenario                                      | Failure Domain                       |
+-----+-------------------------------------------------------+--------------------------------------+
| F01 | Aurora Primary Writer Host Hardware Failure           | Cloud Infrastructure (AWS RDS)       |
| F02 | Government GSTN Portal Downtime (HTTP 503 / 504)      | Upstream External Dependency         |
| F03 | Cloudflare R2 Global Egress Failure / Network Cut     | Object Storage Layer                 |
| F04 | Redis Process Crash / Total Ephemeral Memory Loss    | Async Task Broker & Cache            |
| F05 | Malicious / Corrupted Excel File Ingestion (Zip Bomb) | Data Ingestion Pipeline              |
| F06 | Double-Processing Race Condition in Async Workers    | Distributed State Machine            |
| F07 | Razorpay Webhook Outage / Delayed Delivery (12h lag)  | Third-Party Webhook Architecture     |
| F08 | PostgreSQL Database Table Bloat & Deadlock Freeze    | Database Engine & Concurrency        |
| F09 | Accidental Bulk Data Deletion / Insider Threat       | Data Integrity & Authorization       |
| F10 | Monorepo Staging-to-Production Environment Leak       | Configuration & Security Isolation   |
+-----+-------------------------------------------------------+--------------------------------------+
```

---

### Scenario F01: Aurora Primary Writer Host Hardware Failure

#### What Happens Mechanically
AWS Aurora separates database compute from the underlying distributed storage volume (which maintains 6 copies of data across 3 Availability Zones). If the EC2 hardware hosting the primary writer instance crashes:
1. The PostgreSQL engine terminates abruptly.
2. Active TCP client connections in ReconDesk's SQLAlchemy connection pool drop immediately (`psycopg2.OperationalError: server closed the connection unexpectedly`).
3. AWS RDS automated monitoring detects writer heartbeat loss within 10–25 seconds.
4. RDS initiates an automatic failover: an existing Aurora Read Replica is promoted to become the new Primary Writer, and the DNS record for the cluster Writer Endpoint (`...cluster-xxxx.rds.amazonaws.com`) is updated to point to the promoted instance.

#### How ReconDesk Handles This Automatically
1. **Connection Recycling**: In [`recondesk-backend/app/aurora.py:145-155`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/aurora.py#L145-L155), SQLAlchemy is configured with `pool_pre_ping=True`.
2. Before checking out any connection from the pool, SQLAlchemy issues a silent `SELECT 1`. If the connection is broken due to failover, the connection pool discards it and attempts to establish a fresh TCP connection.
3. The new connection resolves the Writer Endpoint DNS to the newly promoted primary writer.
4. Active Celery tasks that failed during the mid-flight crash are rejected back to the queue because ReconDesk configures `task_acks_late=True` and `task_reject_on_worker_lost=True` in [`recondesk-backend/app/worker/celery.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/celery.py).
5. Another worker claims the task cleanly without duplicate processing.

---

### Scenario F02: Government GSTN Portal Downtime (HTTP 503 / 504)

#### What Happens Mechanically
During statutory filing days, the Indian GSTN portal servers frequently saturate, returning HTTP 500, 502, 503, or 504 errors, or dropping TCP connections during automated GSTR-2B or IMS data pulls.

#### How ReconDesk Handles This Gracefully
1. **Circuit Breaker & Exponential Backoff**: GSTN sync tasks in [`recondesk-backend/app/services/`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/) implement exponential backoff with jitter:
   $$T_{\text{retry}} = \min(300, 2^{\text{attempt}} \times 5) \pm \text{random\_jitter}$$
2. **Queue Isolation**: GSTN sync jobs are strictly routed to the `-Q gstn` Celery queue. A total outage of the government portal **cannot saturate or block the `reconciliation` queue**. Customers can continue uploading Excel files and running internal reconciliations unhindered.
3. **User-Facing Circuit Tripping**: If 5 consecutive calls to GSTN fail for a specific GSTIN, the system flags the connection as `DEGRADED_UPSTREAM`, surfaces an informative banner ("Government GSTN portal is experiencing high traffic; background retries scheduled"), and ceases aggressive polling.

---

### Scenario F03: Cloudflare R2 Global Egress Failure / Network Cut

#### What Happens Mechanically
If Cloudflare R2 experiences an outage or network route partition, frontend clients cannot upload invoice files via presigned URLs, and backend workers cannot fetch uploaded files for parsing.

#### How ReconDesk Handles This Gracefully
1. In [`recondesk-backend/app/utils/storage.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/utils/storage.py), the storage layer abstracts object operations via standard S3-compatible APIs using `botocore`.
2. In the event of an extended R2 outage, switching to AWS S3 requires updating three environment variables in `.env` (`R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`) and restarting containers. No application code changes or database migrations are required.
3. The `/health` endpoint probe immediately isolates the failure to `r2: "error"` while keeping `aurora: "ok"`.

---

### Scenario F04: Redis Process Crash / Total Ephemeral Memory Loss

#### What Happens Mechanically
If the Redis container crashes or is abruptly terminated without an active append-only file (AOF), all in-memory keys, user session tokens, rate-limiting counters, and queued Celery messages are lost.

#### How ReconDesk Handles This Gracefully
1. **Persistent Task Source of Truth**: The definitive state of all operations lives in **AWS Aurora PostgreSQL (`reconciliation_run`, `import_jobs`)**, not Redis. Redis is treated purely as a transient delivery mechanism.
2. **State Reconciliation on Startup**: When Redis restarts, ReconDesk's `stuck_job_detector()` (`main.py:126-206`) scans Aurora for any jobs stuck in `QUEUED` or `PROCESSING` without active heartbeats. It safely transitions them to `FAILED` or re-dispatches them to the newly restored Redis queue.
3. **Stateless JWT Authentication**: User authentication relies on asymmetric **RS256 JWT tokens** verified against AWS Cognito JWKS public keys. Losing Redis does NOT log users out; their browser JWTs remain 100% valid.

---

### Scenario F05: Malicious / Corrupted Excel File Ingestion (Zip Bomb / Formula Injection)

#### What Happens Mechanically
A client uploads a manipulated 500KB `.xlsx` file that inflates into 25GB of uncompressed XML in memory (a decompression bomb), or contains `=CMD('powershell ...')` CSV injection formulas designed to exploit spreadsheet viewers.

#### How ReconDesk Handles This Gracefully
1. **Streaming Openpyxl / Calamine Inspection**: File parsers enforce strict size limits before opening files in memory.
2. **DefusedXML / Formula Sanitization**: Leading formula characters (`=`, `+`, `-`, `@`) in supplier names or invoice descriptions are escaped or stripped during ingestion to prevent CSV injection when an accountant opens an exported report in Excel.
3. **Worker Memory Sandboxing**: Celery workers run with `worker_max_memory_per_child = 300_000` (300 MB). If an unexpectedly bloated file attempts to allocate excessive heap memory, the worker process is terminated safely before it can exhaust the EC2 host RAM.

---

### Scenario F06: Double-Processing Race Condition in Async Workers

#### What Happens Mechanically
Two Celery workers simultaneously pick up task notifications for the same reconciliation run (e.g. due to a temporary network retransmission in Redis). Both begin matching invoices and attempting database inserts.

#### How ReconDesk Prevents Corruption Mechanically
Implemented in [`recondesk-backend/app/services/reconciliation.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/reconciliation.py):
1. **Atomic Conditional State Claiming**:
   ```sql
   UPDATE reconciliation_run
   SET status = 'PROCESSING',
       worker_task_id = :worker_task_id,
       processing_started_at = NOW(),
       last_heartbeat_at = NOW()
   WHERE id = :run_id AND status = 'QUEUED';
   ```
2. The database returns the number of affected rows.
   - **Worker 1**: Receives `rowcount = 1`. It acquires the lease and proceeds with matching.
   - **Worker 2**: Receives `rowcount = 0` (because status is already `PROCESSING`). It immediately aborts execution and logs `Job already claimed by another worker; exiting cleanly`.
3. Split-brain execution and duplicate invoice matching are mathematically impossible.

---

### Scenario F07: Razorpay Webhook Outage / Delayed Delivery (12-Hour Lag)

#### What Happens Mechanically
A user pays ₹49,999 for an Annual Enterprise Plan. Razorpay captures the payment, but their webhook delivery infrastructure suffers an outage, delaying webhook delivery by 12 hours. The user's account remains in the free tier.

#### How ReconDesk Handles This Gracefully
1. **Client-Side Callback Verification**: When the Razorpay JavaScript modal completes successfully on the frontend, it invokes the backend `/api/v1/billing/verify-payment` endpoint with `razorpay_payment_id`, `razorpay_order_id`, and `razorpay_signature`.
2. The backend verifies the HMAC-SHA256 signature immediately and provisions the subscription in real-time without waiting for the delayed webhook.
3. **Webhook Idempotency**: When Razorpay’s delayed webhook finally arrives 12 hours later, [`recondesk-backend/app/routers/billing.py:110-145`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/routers/billing.py#L110-L145) checks the transaction table. Seeing that `payment_id` is already recorded as `SUCCESS`, it returns HTTP 200 immediately without double-crediting or erroring.

---

### Scenario F08: PostgreSQL Database Table Bloat & Deadlock Freeze

#### What Happens Mechanically
High-frequency updates to `last_heartbeat_at` on `reconciliation_run` or rapid deletions of temporary staging records generate thousands of dead tuples. If PostgreSQL's autovacuum cannot keep pace, table bloat causes index scans to degrade from 2ms to 2,000ms.

#### How ReconDesk Mitigates This
1. In AWS Aurora PostgreSQL, table statistics and dead tuples are monitored via `pg_stat_user_tables`.
2. Aggressive autovacuum settings are applied to high-churn tables:
   ```sql
   ALTER TABLE reconciliation_run SET (
       autovacuum_vacuum_scale_factor = 0.05,
       autovacuum_vacuum_cost_limit = 1000
   );
   ```
3. Long-running locks are proactively audited by `_log_db_locks()` (`main.py:260-285`) on every startup.

---

### Scenario F09: Accidental Bulk Data Deletion / Insider Threat

#### What Happens Mechanically
A rogue administrator or bug executes a destructive query (`DELETE FROM reconciliation_matches`).

#### Disaster Recovery Runbook: Aurora Point-In-Time-Recovery (PITR)
1. **Never Panic**: Aurora does not overwrite data blocks immediately. All write-ahead logs (WAL) are streamed continuously to S3.
2. Open AWS RDS Console or execute AWS CLI:
   ```bash
   aws rds restore-db-cluster-to-point-in-time \
       --source-db-cluster-identifier recondesk-production \
       --target-db-cluster-identifier recondesk-restored-pitr \
       --restore-to-time 2026-10-15T23:45:00Z
   ```
3. Within 10–15 minutes, a complete clone of the production database is spun up restored to the exact second prior to the deletion.
4. Export the lost rows from the restored instance and re-insert them into production using `pg_dump` and `psql`.

---

### Scenario F10: Monorepo Staging-to-Production Environment Leak

#### What Happens Mechanically
A developer running local testing or deploying a staging build accidentally configures staging to connect to the production Aurora database cluster, risking overwriting live customer records.

#### Architectural Fail-Closed Guard
ReconDesk's automated safety guard in [`recondesk-backend/app/staging_guard.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/staging_guard.py) runs on container startup:
```python
# recondesk-backend/app/main.py:350-355
if settings.APP_ENV == "staging":
    from app.staging_guard import enforce_staging_guard
    enforce_staging_guard(settings)  # Hard crashes with sys.exit(1) if production URLs detected
```
If a staging build detects `api.recondesk.in` or the production Aurora cluster hostname in its environment variables, it aborts execution immediately with a critical alert, making cross-environment data contamination impossible.

---

## 4. Founder Technical Interview Defense & Exercises

### Q1: "Walk me through how your system recovers from an Aurora primary writer crash during an active reconciliation run."
**Model Answer:**
> "When an Aurora writer crashes, AWS RDS automated failover promotes a read replica to writer and updates the cluster endpoint DNS within 10 to 25 seconds.
> On our backend, SQLAlchemy's `pool_pre_ping=True` detects the severed TCP socket, discards the stale connection, and establishes a new connection to the promoted writer.
> For the active reconciliation run, the Celery worker processing it will have died mid-flight. Because our Celery workers are configured with `task_acks_late=True` and `task_reject_on_worker_lost=True`, the unacknowledged task is automatically re-queued by Redis.
> If the worker host itself died without releasing the task, our backend's background watchdog (`stuck_job_detector()`) identifies the silent heartbeat after 900 seconds, transitions the run to `FAILED`, and records a dead-letter entry. The customer is alerted to retry with a single click, with zero partial data corruption because all intermediate matching updates occur inside atomic database transactions."

### Practical Exercise
1. Review the Staging Guard implementation in [`recondesk-backend/app/staging_guard.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/staging_guard.py).
2. Trace the fail-closed assertion tests in:
   ```bash
   pytest recondesk-backend/tests/ -k "test_staging_guard"
   ```
