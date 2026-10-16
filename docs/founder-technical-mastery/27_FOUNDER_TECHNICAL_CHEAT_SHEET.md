# Chapter 27: The Founder's 10-Minute Technical Interview Cheat Sheet

```
==================================================================================================
RECONDESK FOUNDER TECHNICAL MASTERY SERIES
Stage 7: EF / YC Interview Preparation & Master Curriculum
Chapter 27: The Founder's 10-Minute Technical Interview Cheat Sheet
Review Window: Read 10 Minutes Before Entering an EF, YC, or VC Technical Due Diligence Interview
==================================================================================================
```

---

## 1. The 30-Second CTO Soundbite

> "ReconDesk is an enterprise B2B SaaS platform for Indian GST reconciliation and statutory compliance. We solve the multi-billion-dollar Input Tax Credit (ITC) mismatch crisis created by Section 16(2)(c) and Rule 88D. 
> Technically, we operate as a high-throughput **Modular Monolith** built on **FastAPI and Python 3.11**, backed by **AWS Aurora Serverless v2 PostgreSQL** and horizontally distributed across **7 domain-isolated Celery queues**. 
> Our matching engine reduces $O(N \times M)$ combinatorial search to strictly linear **$O(N + M)$** time via candidate-blocked inverted indexes and C++ AVX2 SIMD vectorization via RapidFuzz, reconciling 100,000 invoices in under 4 seconds with 100% mathematical precision using 64-bit integer paise."

---

## 2. Core Architecture & Tech Stack Matrix

```
+----------------------------------------------------------------------------------------------------+
|                                      TECH STACK AT A GLANCE                                        |
+----------------------+-----------------------+-----------------------------------------------------+
| Layer                | Technology            | Key Invariant / Location                            |
+----------------------+-----------------------+-----------------------------------------------------+
| API Framework        | FastAPI (Python 3.11) | Pydantic v2 Rust core, async/await, 59 routers      |
| Database Engine      | AWS Aurora PostgreSQL | Serverless v2 (0.5-128 ACUs), 6-way multi-AZ storage|
| Database Migration   | Alembic 1.13+         | 37 sequential migrations in alembic/versions/       |
| Background Workers   | Celery 5.3 + Redis 7  | 7 domain queues, task_acks_late=True, late reject   |
| Matching Engine      | RapidFuzz (C++/SIMD)  | O(N+M) candidate blocking in app/services/matcher.py|
| Web Frontend         | Next.js 14 App Router | React Server Components, SWR cache, edge middleware |
| UI Virtualization    | @tanstack/react-virt  | Recycles 35 DOM nodes for 50,000 tabular rows       |
| Edge Reverse Proxy   | Caddy 2 (Go)          | Automated Let's Encrypt TLS renewal, HTTP/2 & 3     |
| Identity & Auth      | AWS Cognito           | Asymmetric RS256 JWKS token validation in-memory    |
| Object Storage       | Cloudflare R2         | S3-compatible API with zero egress bandwidth fees   |
| Payments             | Razorpay              | Constant-time HMAC-SHA256 byte signature validation |
| Error Monitoring     | Sentry SDK            | Automated PII sanitization via app/filing/log_safety|
+----------------------+-----------------------+-----------------------------------------------------+
```

---

## 3. The 6-Tier Matching Engine Cheat Sheet

```
+----------------------------------------------------------------------------------------------------+
|                               THE 6 MATCHING TIERS (MATCHER.PY)                                    |
+------+-----------------------+-----------------------+---------------------------------------------+
| Tier | Match Name            | Search Method         | Criteria / Tolerance                        |
+------+-----------------------+-----------------------+---------------------------------------------+
| L1   | Exact Match           | O(1) Hash Map         | Exact normalized doc #, exact date, exact ₹ |
| L2   | Exact Num / Diff Date | O(1) Hash Map         | Exact doc #, exact ₹, date within 30 days   |
| L3   | Cleaned Delimiters    | Normalized Hash Map   | Strips '/', '-', ' ', leading zeros         |
| L4   | Fuzzy String Match    | RapidFuzz AVX2 SIMD   | Levenshtein ratio >= 0.85, OCR substitution |
| L5   | Taxable Value Bucket  | O(1) Value Hash Map   | Different doc #, exact ₹ match within date  |
| L6   | Multi-Invoice Split   | Combinatorial Subset  | 1 payment covering multiple bills (<= 3)    |
+------+-----------------------+-----------------------+---------------------------------------------+
```

---

## 4. The 4 Non-Negotiable Financial Invariants

1. **Integer-Paise Rule**: All monetary values are strictly stored as 64-bit integer paise (`BigInteger`). Floats are forbidden. Rounding drift is mathematically impossible.
2. **Return Period Crossing Guard**: Invoices cannot match across invalid statutory financial years (prevents claiming expired ITC under Section 16(4)).
3. **Document Type Gate**: Credit Notes (`CRN`) must NEVER match against Standard Invoices (`INV`), preventing catastrophic balance inversions.
4. **Candidate-Blocking Linear Time**: Inverted index pre-sorting reduces comparisons from $N \times M$ to $N + M$ linear time ($k \le 5$ bucket items).

---

## 5. Indian GST Statutory Quick Reference

- **Section 16(2)(c)**: Taxpayer can only claim Input Tax Credit (ITC) if their supplier has actually deposited the tax with the government (reflected in GSTR-2B).
- **Section 16(4)**: Hard annual deadline to claim ITC (30th November following the end of the financial year).
- **Section 17(5)**: Ineligible / Blocked Credit categories (motor vehicles, food/catering, club memberships) flagged via HSN codes.
- **Rule 37 (180-Day Reversal)**: If buyer fails to pay supplier within 180 days of invoice date, ITC must be reversed with 18% annual interest.
- **Rule 88C / 88D**: Automated government mismatch notices (Form DRC-01B for GSTR-1 vs 3B, Form DRC-01C for GSTR-2B vs 3B).
- **IMS (Invoice Management System)**: 2024 government portal feature allowing buyers to explicitly Accept, Reject, or Keep Pending supplier invoices.

---

## 6. The 7 Dedicated Celery Queues

1. `-Q reconciliation`: Core L1–L6 matching engine execution.
2. `-Q imports`: Ingestion and parsing of large Excel/CSV spreadsheets.
3. `-Q gstn`: Network-bound API sync with government GSTN servers.
4. `-Q filing`: GSTR-3B Table 4 computation and return drafting.
5. `-Q exports`: Generation of large XLSX and PDF audit reports.
6. `-Q notifications`: Email/SMS alerts and Rule 37 180-day warnings.
7. `-Q maintenance`: Stuck job watchdog, database health checks, daily scorecard rebuilds.

---

## 7. The Top 10 Technical Interview Soundbites

1. *"We don't use floats; we use 64-bit integer paise to eliminate IEEE 754 drift."*
2. *"Our matching engine scales at $O(N + M)$ using in-memory candidate blocking rather than $O(N \times M)$ brute force."*
3. *"We use RapidFuzz with C++ AVX2 SIMD instructions, doing 50,000 string comparisons per second on CPU."*
4. *"Our Celery workers use `task_acks_late=True` and `worker_max_memory_per_child=300MB` to eliminate memory leaks and guarantee at-least-once execution."*
5. *"We prevent split-brain worker execution via conditional atomic database state transitions (`UPDATE ... WHERE status = 'QUEUED'`)."*
6. *"Authentication is verified in under 0.1ms via asymmetric RS256 JWKS against AWS Cognito without touching our database."*
7. *"Our frontend virtualizes tables via `@tanstack/react-virtual`, recycling 35 DOM nodes for 50,000 invoices at 60 FPS."*
8. *"We use Caddy 2 for automated Let's Encrypt TLS renewal, making certificate expiration an impossibility."*
9. *"Our fail-closed Staging Guard hard-crashes container startup if a staging environment ever targets production URLs."*
10. *"I directed AI coding agents under strict Specification-Driven Development backed by a 296-test automated verification harness."*

---

## 8. Emergency Read-Only Diagnostic CLI Commands

```bash
# 1. Check multi-dependency health probe
curl -s http://127.0.0.1:8000/health | jq .

# 2. Check running container status and CPU/RAM usage
docker compose ps
docker stats --no-stream

# 3. Check active database locks in Aurora PostgreSQL
psql $AURORA_DATABASE_URL -c "
SELECT l.pid, l.locktype, l.mode, a.query, age(clock_timestamp(), a.query_start) AS duration
FROM pg_locks l JOIN pg_stat_activity a ON l.pid = a.pid
WHERE a.pid <> pg_backend_pid() AND a.state <> 'idle';
"

# 4. Check Celery active worker tasks across queues
docker compose exec backend celery -A app.worker.celery inspect active

# 5. Check Redis broker queue lengths
docker compose exec redis redis-cli llen reconciliation
```
