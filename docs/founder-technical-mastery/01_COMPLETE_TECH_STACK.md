# Volume 01: Complete Technology Stack & Architectural Evaluation

> **Document ID**: `RD-TECH-01`  
> **Author**: Chief Technology Officer & Principal Systems Architect  
> **Target Audience**: ReconDesk Founder, Technical Due Diligence Auditors, Engineering Candidates, EF / YC Interviewers  
> **Repository Baseline**: `release/v1.5.2-rc1`  
> **Source Evidence**: Verified against [`requirements.txt`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/requirements.txt), [`package.json`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-frontend/package.json), [`docker-compose.prod.yml`](file:///Users/omkarkadam/Documents/ReconDesk/docker-compose.prod.yml), and [`Dockerfile`](file:///Users/omkarkadam/Documents/ReconDesk/Dockerfile).

---

## 1. Executive Technology Inventory Matrix

| Technology | Verified Version | Primary Purpose | Codebase Location | Architectural State |
| :--- | :--- | :--- | :--- | :--- |
| **Python** | `3.11` (Debian Bookworm) | Core backend runtime & numeric computation | [`recondesk-backend/Dockerfile`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/Dockerfile#L1) | **Active Primary** |
| **FastAPI** | `>=0.111.0` | High-throughput asynchronous ASGI web API | [`recondesk-backend/requirements.txt`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/requirements.txt#L2) | **Active Primary** |
| **Uvicorn** | `>=0.29.0` (Standard) | High-performance ASGI HTTP web server | [`requirements.txt`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/requirements.txt#L3) | **Active Primary** |
| **Pydantic & Settings** | `>=2.7.0` / `>=2.2.0` | Strict data validation, schema enforcement, env config | [`requirements.txt`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/requirements.txt#L34-L35) | **Active Primary** |
| **SQLAlchemy** | `>=2.0.0` | Declarative ORM & pooled database queries | [`requirements.txt`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/requirements.txt#L62) | **Active Primary** |
| **Alembic** | `>=1.13.0` | Programmatic schema migrations & evolution | [`recondesk-backend/alembic/`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/alembic/) | **Active Primary** |
| **AWS Aurora PostgreSQL** | Serverless v2 (PG 15+) | Distributed relational database & multi-tenant storage | [`app/aurora.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/aurora.py), [`aurora_client.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/aurora_client.py) | **Active Target** |
| **Supabase PostgREST** | Client `>=2.4.0` | Legacy database backend & client adapter layer | [`app/database.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/database.py) | *Legacy Transitioning* |
| **Celery** | `>=5.3.0` (Redis broker) | Distributed background task & job queue processing | [`app/worker/celery_app.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/celery_app.py) | **Active Primary** |
| **Redis** | `7.0` (Alpine container) | In-memory message broker & task state cache | [`docker-compose.prod.yml`](file:///Users/omkarkadam/Documents/ReconDesk/docker-compose.prod.yml#L49) | **Active Primary** |
| **Cloudflare R2** | S3-Compatible API | Object storage for raw uploads & offloaded JSON payloads | [`app/utils/storage.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/utils/storage.py) | **Active Primary** |
| **OpenPyXL & Pandas** | `>=3.1.2` / `>=2.2.0` | Multi-sheet Excel workbook parsing & streaming export | [`requirements.txt`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/requirements.txt#L17-L19) | **Active Primary** |
| **Levenshtein & RapidFuzz** | `>=0.25.0` / `>=3.0.0` | Fuzzy string similarity & C-accelerated distance metrics | [`requirements.txt`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/requirements.txt#L44-L45) | **Active Primary** |
| **Amazon Cognito** | AWS User Pool (RS256) | Enterprise identity, JWT verification, and auth | [`app/cognito_verifier.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/cognito_verifier.py) | **Active Primary** |
| **Razorpay SDK** | `>=1.4.0` | Subscription billing, checkout, and webhook signatures | [`requirements.txt`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/requirements.txt#L48) | **Active Primary** |
| **Amazon SES & Resend** | Port 587 SMTP / SDK | Transactional email dispatch & notification delivery | [`app/config.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/config.py#L146-L153) | **Active Primary** |
| **Caddy 2** | `2-alpine` (Docker) | Reverse proxy, HTTP/2, HSTS, automated TLS | [`Caddyfile`](file:///Users/omkarkadam/Documents/ReconDesk/Caddyfile) | **Active Primary** |
| **Sentry SDK** | `>=2.0.0` (FastAPI) | Application telemetry, error tracking, and PII scrubbing | [`app/main.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py#L104-L119) | **Active Primary** |
| **SlowAPI** | `>=0.1.9` | IP-based and user-based token bucket rate limiting | [`app/utils/rate_limit.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/utils/rate_limit.py) | **Active Primary** |
| **TypeScript** | `^5.0.0` | Static typing, interface definitions, API client safety | [`recondesk-frontend/package.json`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-frontend/package.json#L44) | **Active Primary** |
| **Next.js & React** | `^14.2.35` / `^18.0.0` | React App Router framework, SSR, Server Components | [`package.json`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-frontend/package.json#L25-L30) | **Active Primary** |
| **TanStack Virtual** | `^3.14.13` | DOM virtualization for 20,000+ row table rendering | [`package.json`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-frontend/package.json#L17) | **Active Primary** |
| **Tailwind CSS** | `^3.4.1` | Utility-first responsive CSS styling system | [`package.json`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-frontend/package.json#L43) | **Active Primary** |
| **SWR** | `^2.4.1` | Client-side reactive data caching and revalidation | [`package.json`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-frontend/package.json#L33) | **Active Primary** |
| **Pytest Suite** | `>=8.1.0` (AsyncIO) | Automated unit, regression, and accuracy test harness | [`requirements.txt`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/requirements.txt#L71-L72) | **Active Primary** |

---

## 2. Deep Technical Breakdown by Technology

---

### 2.1 Backend Runtime: Python 3.11 & FastAPI

#### 1. What is it?
Python 3.11 is a high-level, interpreted programming language with strong dynamic typing and specialized scientific/numeric libraries. FastAPI is a modern, high-performance web framework designed specifically for building asynchronous REST APIs using standard Python type hints.

#### 2. Why does it exist?
Traditional Python web frameworks like Django and Flask were built around synchronous, blocking architectures (WSGI). When an application performs slow I/O (like querying a database or calling the GSTN portal), the entire server thread is blocked from handling other incoming requests. FastAPI was built on the **Asynchronous Server Gateway Interface (ASGI)** standard, allowing a single thread to juggle thousands of concurrent network connections without blocking.

#### 3. How does it work internally?
FastAPI leverages:
* **Starlette**: The underlying lightweight ASGI toolkit that handles routing, HTTP requests, responses, WebSockets, and middleware.
* **Pydantic**: Compiles Python type hints into fast C-level validation logic (via `pydantic-core` written in Rust), automatically validating request bodies and serializing JSON responses.
* **Python `asyncio` Event Loop**: Runs an event loop that suspends tasks awaiting I/O (`await`) and resumes them as soon as data arrives, enabling high concurrency.

#### 4. How ReconDesk uses it
ReconDesk structures the entire backend as a unified FastAPI application in [`recondesk-backend/app/main.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py). It registers **59 modular routers**, handles global application lifecycle events (`lifespan`), implements security middleware, and validates all financial payloads via Pydantic models.

#### 5. Show me the code
From [`recondesk-backend/app/main.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py#L387-L402):

```python
# ── App Definition ────────────────────────────────────────────────────────────
app = FastAPI(
    lifespan=lifespan,
    redirect_slashes=False,
    title="ReconDesk API",
    description="B2B SaaS reconciliation platform API",
    version=settings.APP_VERSION,
    docs_url="/docs" if settings.APP_ENV != "production" else None,
    redoc_url="/redoc" if settings.APP_ENV != "production" else None,
)

# ── Rate limiting & Middleware ────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(CorrelationIdMiddleware)
```

#### 6. Line-by-line explanation
* **Line 387–395**: Initializes the `FastAPI` instance. It binds the custom `lifespan` context manager which executes database checks and spawns background supervisor tasks. It sets `redirect_slashes=False` to prevent insecure 307 redirects on trailing-slash mismatches. In production (`APP_ENV == "production"`), it disables `/docs` (Swagger UI) and `/redoc` to prevent public discovery of API schemas by unauthorized adversaries.
* **Line 398–400**: Attaches the SlowAPI token bucket rate limiter to `app.state` and registers an exception handler for `RateLimitExceeded` (returning HTTP 429).
* **Line 401–402**: Mounts `SlowAPIMiddleware` to monitor request frequency per IP/token, and `CorrelationIdMiddleware` to inject a unique UUID into every request header (`X-Correlation-ID`) for distributed tracing across logs.

#### 7. Failure modes
* **Event Loop Blocking**: If an engineer executes a CPU-heavy, synchronous calculation (such as parsing a 50MB Excel sheet or running Levenshtein on 100,000 rows) directly inside an `async def` route without delegating to Celery or `asyncio.to_thread()`, the entire event loop freezes. All incoming health checks and API calls time out with HTTP 504.

#### 8. Alternatives & Trade-offs
* *Alternative*: Go (Golang) or Java (Spring Boot).
* *Trade-off*: Go offers higher raw throughput and lower memory consumption. However, Python was chosen because of its unmatched ecosystem for tabular data manipulation (`pandas`, `openpyxl`), fuzzy string algorithms (`rapidfuzz`), and tax rule scripting, enabling a solo founder to develop and iterate at 10x the speed of Go.

#### 9. Senior Engineer / CTO Interview Defense
* **Q**: *"Why choose FastAPI over Django for an enterprise tax platform?"*
* **A**: *"Django includes an extensive ORM and templating engine designed for server-rendered HTML apps, but it introduces significant overhead for decoupled JSON APIs. FastAPI gives us native ASGI concurrency, automated OpenAPI documentation, and sub-millisecond Rust-accelerated Pydantic validation. For our database layer, we needed granular control over connection pooling and transaction boundaries with AWS Aurora, which SQLAlchemy 2.0 provides far better than Django's ORM."*

---

### 2.2 Relational Database: AWS Aurora Serverless v2 & SQLAlchemy 2.0

#### 1. What is it?
AWS Aurora Serverless v2 is an on-demand, auto-scaling configuration of Amazon Aurora PostgreSQL. SQLAlchemy 2.0 is the premier Python SQL toolkit and Object Relational Mapper (ORM), providing an abstraction layer over database connections, query construction, and transactions.

#### 2. Why does it exist?
Traditional self-managed PostgreSQL on a single EC2 instance requires manual provisioning of CPU, RAM, and disk storage. If traffic spikes during GST filing deadlines (the 11th, 13th, and 20th of every month), a fixed database crashes from connection exhaustion or memory saturation. Aurora Serverless v2 automatically scales compute capacity up or down in fractional Aurora Capacity Units (ACUs) within milliseconds, while replicating storage six ways across three Availability Zones.

#### 3. How does it work internally?
* **Decoupled Compute & Storage**: Aurora separates the database compute nodes (which parse SQL and plan queries) from the distributed storage fleet. Compute nodes write log records directly to storage rather than flushing dirty buffer pages, achieving 3x the write throughput of standard PostgreSQL.
* **SQLAlchemy Connection Pooling**: Instead of opening and closing an expensive TCP/TLS handshake with Aurora on every HTTP request, SQLAlchemy maintains a pool of pre-warmed database connections (`QueuePool`). When a request needs the database, it checks out an existing connection in microseconds and returns it upon completion.

#### 4. How ReconDesk uses it
ReconDesk defines its schema using SQLAlchemy 2.x declarative models in [`recondesk-backend/app/models/`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/models/). To maintain backward compatibility during the migration from Supabase PostgREST, ReconDesk created [`AuroraClient`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/aurora_client.py), an adapter that translates chained query methods (`.table().select().eq().execute()`) into parameterized SQL executed against Aurora.

#### 5. Show me the code
From [`recondesk-backend/app/aurora.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/aurora.py#L76-L102):

```python
def create_aurora_engine(db_url: str):
    """Create a production SQLAlchemy engine for AWS Aurora PostgreSQL.

    Configures connection pooling, connection recycling, and health timeouts.
    """
    settings = get_settings()
    connect_args = {
        "connect_timeout": settings.AURORA_CONNECT_TIMEOUT_SECONDS,
        "application_name": "recondesk_api",
    }
    return create_engine(
        db_url,
        pool_size=settings.AURORA_POOL_SIZE,          # Default: 20
        max_overflow=settings.AURORA_MAX_OVERFLOW,    # Default: 10
        pool_recycle=settings.AURORA_POOL_RECYCLE_SECONDS,  # Default: 1800 (30m)
        pool_timeout=settings.AURORA_POOL_TIMEOUT_SECONDS,  # Default: 30
        pool_pre_ping=True,  # Discards severed connections before checkout
        connect_args=connect_args,
    )
```

#### 6. Line-by-line explanation
* **Line 83–86**: Injects psycopg2 connection parameters. `connect_timeout` (30s) prevents threads from hanging indefinitely during network partitions. `application_name="recondesk_api"` identifies the client in Aurora's `pg_stat_activity` monitoring view.
* **Line 89–90**: Sets `pool_size=20` and `max_overflow=10`. The pool maintains 20 persistent connections and allows up to 10 burst connections during high load (maximum 30 connections per worker process).
* **Line 91**: `pool_recycle=1800` (30 minutes). Crucial for AWS Aurora: Aurora dynamically updates DNS endpoints during automatic failovers. Recycling connections forces the driver to re-resolve DNS and reconnect to the newly promoted writer node.
* **Line 93**: `pool_pre_ping=True` issues a lightweight `SELECT 1` ping whenever a connection is checked out. If Aurora closed the connection due to an idle timeout, SQLAlchemy transparently recycles it rather than throwing an unhandled `psycopg2.OperationalError`.

#### 7. Failure modes
* **Connection Exhaustion**: If Celery workers or API threads fail to release sessions (e.g., forgetting to close a context manager), connections leak. Once the pool reaches 30, subsequent requests block for 30s (`pool_timeout`) before failing with `TimeoutError: QueuePool limit of size 20 overflow 10 reached`.

#### 8. Alternatives & Trade-offs
* *Alternative*: NoSQL (MongoDB, DynamoDB).
* *Trade-off*: NoSQL lacks ACID transactional guarantees, foreign key cascade constraints, and relational joins. In Indian tax compliance, multi-table joins between Invoices, Credit Notes, Tax Heads, and Clients are required. A relational schema prevents orphaned records and data corruption.

#### 9. Senior Engineer / CTO Interview Defense
* **Q**: *"How do you store monetary values in the database, and why not use floating-point numbers?"*
* **A**: *"We store every financial value as an integer representing paise (1 INR = 100 Paise) using 64-bit BigInteger columns (`taxable_amount_paise`, `igst_paise`, `cgst_paise`, `sgst_paise`). IEEE 754 floating-point numbers cannot accurately represent base-10 fractional decimals, leading to rounding discrepancies like 0.1 + 0.2 = 0.30000000000000004. In tax compliance, a one-paisa error can trigger an automated statutory demand notice under Rule 88D. Storing integer paise guarantees 100% mathematical precision across all database queries, aggregations, and reconciliation comparisons."*

---

### 2.3 Asynchronous Processing: Celery 5 & Redis 7

#### 1. What is it?
Celery is a distributed task queue system that executes units of work (tasks) asynchronously outside the HTTP request-response cycle. Redis is an ultra-fast, in-memory data store used by Celery as both a **message broker** (to store job queues) and a **result backend** (to track task statuses).

#### 2. Why does it exist?
Parsing a 50,000-line Purchase Register workbook and matching it against GSTR-2B takes between 10 to 90 seconds. If an HTTP client (like a web browser) initiates this request synchronously, the browser or reverse proxy (Caddy/Cloudflare) will terminate the connection after 30 seconds with an HTTP 504 Gateway Timeout. Background job queues allow the API to accept the upload immediately, return an HTTP 202 Accepted with a `run_id`, and execute the heavy computation asynchronously while the frontend polls for progress.

#### 3. How does it work internally?
1. The FastAPI web process receives an upload, writes records to the database, and publishes a message containing task arguments to a Redis list (`reconciliation` queue).
2. A separate Celery worker process running in the background continuously pops messages from Redis.
3. The worker executes the Python task, updates the progress in the database, and emits heartbeats.
4. When finished, the worker marks the run as `COMPLETED` and acknowledges the message in Redis.

#### 4. How ReconDesk uses it
Configured in [`recondesk-backend/app/worker/celery_app.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/celery_app.py), ReconDesk implements **7 isolated functional queues**:
* `reconciliation`: Core matching algorithms.
* `imports`: File parsing and data extraction.
* `gstn`: External government API communications.
* `filing`: GSTR return preparation and submission.
* `exports`: Excel report generation.
* `notifications`: Email and in-app alerts.
* `maintenance`: Stuck job cleanup and daily rule scans.

#### 5. Show me the code
From [`recondesk-backend/app/worker/celery_app.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/worker/celery_app.py#L33-L45):

```python
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Enterprise Queue Routing: separate queues prevent starvation across functional domains
    task_routes=TASK_ROUTES,
    task_default_queue=QUEUE_RECONCILIATION,
    # Late acknowledgement: task acknowledged only after successful completion so worker crashes don't drop jobs
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)
```

#### 6. Line-by-line explanation
* **Line 34–36**: Restricts serialization strictly to JSON. It forbids Python `pickle` serialization, eliminating arbitrary remote code execution (RCE) vulnerabilities if the Redis broker is compromised.
* **Line 40–41**: Binds `task_routes=TASK_ROUTES`, routing `worker.run_import_job` to `imports`, `worker.execute_reconciliation` to `reconciliation`, and `worker.process_filing_batch` to `filing`. This guarantees that a surge in large Excel exports cannot starve statutory filing jobs.
* **Line 43**: `task_acks_late=True` instructs the worker not to acknowledge the task to Redis when it starts. Instead, acknowledgment occurs **only after the task finishes successfully**.
* **Line 44**: `task_reject_on_worker_lost=True` guarantees that if the worker process is killed by the OS (e.g. Linux OOM-killer) while executing, Redis detects the lost worker and immediately re-enqueues the unacknowledged task for another worker to process.

#### 7. Failure modes
* **Poison Pill Tasks & Infinite Retry Loops**: If a corrupted Excel workbook triggers a fatal unhandled syntax exception and the task retries indefinitely without limits, the worker fleet gets jammed. ReconDesk mitigates this by setting `max_retries=3`, `retry_backoff=True`, and recording unrecoverable errors into a dead-letter failure log via `record_failed_job()`.

#### 8. Alternatives & Trade-offs
* *Alternative*: AWS SQS + AWS Lambda (Serverless).
* *Trade-off*: AWS Lambda has a strict 15-minute execution limit and cold starts. Complex reconciliations on 100,000+ invoices can exceed 15 minutes. Celery on EC2 allows tasks to run with extended soft time limits (up to 3,600s / 1 hour) without arbitrary timeouts.

#### 9. Senior Engineer / CTO Interview Defense
* **Q**: *"What happens to an active reconciliation job if the worker server runs out of memory and crashes?"*
* **A**: *"Because we configure `task_acks_late=True` and `task_reject_on_worker_lost=True`, the task is never removed from Redis until successful completion. When the worker process dies, Redis re-queues the message. Furthermore, in `main.py`, our background `stuck_job_detector()` monitors active jobs every 300s. If a job has been silent with no heartbeat for over 900s, the watchdog marks the run as `FAILED`, records the event in the audit dead-letter queue, and notifies Sentry."*

---

### 2.4 Frontend Architecture: Next.js 14 App Router, TypeScript & TanStack Virtual

#### 1. What is it?
Next.js 14 is a production-grade React framework providing Server-Side Rendering (SSR), Server Components, and optimized routing via the App Router. TypeScript provides compile-time static type checking. TanStack Virtual is a headless UI virtualization library for rendering large datasets.

#### 2. Why does it exist?
A client reconciling annual GST data might load 25,000 invoice rows. In a standard React application, rendering 25,000 rows creates over 200,000 DOM nodes. The browser becomes unresponsive, freezes the JavaScript thread, and crashes mobile or low-spec laptop browsers. TanStack Virtual calculates the viewport scroll position and renders **only the 30 rows currently visible on screen**, dynamically recycling DOM nodes as the user scrolls.

#### 3. How does it work internally?
* **Route Groups**: Folders wrapped in parentheses (e.g., `(dashboard)`, `(auth)`) structure layouts and middleware authorization without altering the public URL path.
* **SWR (Stale-While-Revalidate)**: Fetches data from the cache first (instant display), sends a background revalidation request to the backend, and silently updates the UI if data changed.
* **Server Components**: Render static UI on the server, sending zero JavaScript bundle weight to the client.

#### 4. How ReconDesk uses it
* **File Ingestion Wizard**: [`components/reconcile/`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-frontend/components/reconcile/) coordinates file uploads, progress bars, and column mapping.
* **Reconciliation Workspace**: Employs TanStack Virtual to render massive multi-tier match tables with real-time filtering (Exact, Review, Missed ITC, Ineligible).
* **API Client**: Implemented in [`recondesk-frontend/lib/api.ts`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-frontend/lib/api.ts) (203 KB), fully typed with TypeScript interfaces matching backend Pydantic schemas.

#### 5. Show me the code
From [`recondesk-frontend/components/reconcile/ReconcileTableVirtual.tsx`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-frontend/components/reconcile/ReconcileTableVirtual.tsx) (pattern verified in workspace components):

```typescript
// ── TanStack Virtualization Hook ─────────────────────────────────────────────
const rowVirtualizer = useVirtualizer({
  count: filteredRows.length,
  getScrollElement: () => parentRef.current,
  estimateSize: () => 52, // Fixed row height in pixels
  overscan: 10,           // Buffer rows rendered above and below viewport
});
```

#### 6. Line-by-line explanation
* `count: filteredRows.length`: Informs the virtualizer of the total dataset size (e.g., 15,000 rows).
* `getScrollElement: () => parentRef.current`: Binds to the scrollable container element.
* `estimateSize: () => 52`: Allocates a virtual height of 52px per row, computing the total virtual scrollbar height (`15,000 * 52px = 780,000px`).
* `overscan: 10`: Pre-renders 10 extra rows outside the visible viewport above and below, preventing blank flashes during rapid user scrolling.

#### 7. Failure modes
* **DOM Freezes Without Virtualization**: If a developer forgets virtualization and renders raw `.map()` over 10,000 rows, the browser tab consumes over 2GB of RAM and freezes.
* **Client-Server Token Mismatch**: If SSR attempts to render authenticated routes before reading client-side session cookies, a hydration mismatch error occurs.

#### 8. Alternatives & Trade-offs
* *Alternative*: Pure Single Page Application (SPA) using Vite + React.
* *Trade-off*: Pure SPAs have zero server-side rendering, leading to poor SEO on public landing pages and slow initial load times because the entire JavaScript bundle must be downloaded before rendering anything. Next.js 14 provides server-side rendering for landing pages and blazingly fast client-side navigation for the dashboard.

#### 9. Senior Engineer / CTO Interview Defense
* **Q**: *"Why did you migrate your frontend build to AWS Amplify Hosting instead of staying on Vercel?"*
* **A**: *"While Vercel is exceptional for early prototypes, AWS Amplify Hosting (Web Compute) brings our SSR frontend into the same AWS virtual private cloud ecosystem as our Aurora database and EC2 backend. This reduces cross-cloud network egress latency between frontend API routes and backend services, unifies security policies and IAM roles under a single cloud provider, and eliminates the unpredictable bandwidth pricing of cross-cloud deployments."*

---

### 2.5 Security & Reverse Proxy: Caddy 2, SlowAPI & Sentry

#### 1. What is it?
* **Caddy 2**: An enterprise-grade, open-source HTTP/2 reverse proxy written in Go with automatic HTTPS via Let's Encrypt.
* **SlowAPI**: A rate-limiting library for ASGI applications based on Redis/in-memory token buckets.
* **Sentry**: A real-time application monitoring and error-tracking platform.

#### 2. Why does it exist?
Exposing a Python application server (Uvicorn) directly to the public Internet is insecure: Uvicorn does not manage TLS certificates, is vulnerable to slowloris DoS attacks, and lacks HTTP request buffering. Caddy acts as a hardened shield in front of Uvicorn. SlowAPI prevents credential brute-forcing and API denial-of-service, while Sentry alerts engineers to uncaught exceptions before customers report them.

#### 3. How does it work internally?
* **Caddy TLS Engine**: Automatically executes ACME protocol challenges with Let's Encrypt, retrieves TLS certificates, configures TLS 1.3 ciphers, and handles zero-downtime certificate renewals.
* **Sentry PII Scrubbing**: Inspects captured stack traces, exception messages, and breadcrumbs, stripping out sensitive customer financial data (PAN, GSTIN, OTPs, auth tokens) before encrypting and sending telemetry to Sentry servers.

#### 4. How ReconDesk uses it
* **Caddy**: Defined in [`Caddyfile`](file:///Users/omkarkadam/Documents/ReconDesk/Caddyfile), reverse-proxies `api.recondesk.in` to `web:8000` with strict HTTP Strict Transport Security (HSTS) headers.
* **Sentry Scrubbing**: Implemented in [`recondesk-backend/app/filing/log_safety.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/filing/log_safety.py), scrubbing query parameters like `?otp=` and `?pan=` from URLs.

#### 5. Show me the code
From [`Caddyfile`](file:///Users/omkarkadam/Documents/ReconDesk/Caddyfile#L1-L5):

```caddyfile
api.recondesk.in {
    header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
    reverse_proxy web:8000
}
```

#### 6. Line-by-line explanation
* **Line 1**: Declares the public hostname `api.recondesk.in`. Caddy automatically provisions a Let's Encrypt certificate for this domain on port 443.
* **Line 2**: Injects the `Strict-Transport-Security` (HSTS) header with a 2-year duration (`max-age=63072000`), enforcing encrypted HTTPS across all subdomains and registering for browser preload lists.
* **Line 3**: Reverse-proxies all incoming decrypted traffic to the internal Docker Compose service named `web` on port 8000 over the private Docker bridge network.

#### 7. Failure modes
* **Domain DNS Cutover Failures**: If public DNS records for `api.recondesk.in` do not point to the EC2 Elastic IP, Caddy's Let's Encrypt ACME challenge fails, preventing certificate issuance and causing browsers to display `SSL_ERROR_UNRECOGNIZED_NAME_ALERT`.

#### 8. Alternatives & Trade-offs
* *Alternative*: Nginx or AWS Application Load Balancer (ALB).
* *Trade-off*: Nginx requires manual Certbot cron jobs for certificate renewals which often fail silently. AWS ALB costs ~$25/month plus bandwidth fees. Caddy provides zero-cost automated TLS, HTTP/2, and modern ciphers in a single, lightweight binary.

#### 9. Senior Engineer / CTO Interview Defense
* **Q**: *"How do you prevent sensitive financial data from leaking into external monitoring services like Sentry?"*
* **A**: *"In `main.py`, we initialize Sentry with custom sanitizers: `before_send=sentry_scrub_event`, `before_send_transaction=sentry_scrub_transaction`, and `before_breadcrumb=sentry_scrub_breadcrumb`. Implemented in `log_safety.py`, these sanitizers regex-mask Indian PAN numbers, supplier GSTINs, bank accounts, and query parameters containing OTPs and authorization headers before payload transmission. We maintain 100% observability into stack traces without violating financial privacy regulations."*

---

## 3. Technology Matrix: Comprehensive Interview Questions & Exercises

### 3.1 Self-Testing Questions for the Founder
1. **Explain the difference between ASGI and WSGI.** Why does ReconDesk require an ASGI server?
2. **Why does ReconDesk store monetary values in integer paise instead of floating-point numbers?** What specific tax notice does this prevent?
3. **What is the function of `pool_pre_ping=True` in SQLAlchemy?** What happens to user requests if this setting is disabled and Aurora restarts?
4. **Why are Celery tasks configured with `task_acks_late=True`?** What failure mode does this solve?
5. **How does TanStack Virtual allow ReconDesk to display 20,000 invoices without crashing the user's browser?**
6. **Explain the purpose of the Caddy reverse proxy.** Why not expose FastAPI directly to port 80/443?

### 3.2 Practical Verification Exercises
* **Exercise 1 (Paise Math)**: Write a 3-line Python snippet comparing `0.1 + 0.2 == 0.3` with integer paise math `10 + 20 == 30`. Prove that floating-point returns `False` while integer math returns `True`.
* **Exercise 2 (Celery Route Inspection)**: Open a terminal and run `celery -A app.worker.celery_app inspect active_queues`. Verify that all 7 enterprise queues (`reconciliation`, `imports`, `gstn`, `filing`, `exports`, `notifications`, `maintenance`) are recognized by the worker.
* **Exercise 3 (Database Pool Verification)**: Check [`recondesk-backend/app/aurora.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/aurora.py) and confirm the values for `pool_size`, `max_overflow`, and `pool_recycle`. Explain why `pool_recycle=1800` is critical for AWS Aurora.
