# Volume 02: Complete System Architecture & Operational Workflows

> **Document ID**: `RD-TECH-02`  
> **Author**: Chief Technology Officer & Principal Systems Architect  
> **Target Audience**: ReconDesk Founder, System Architects, Security Reviewers, EF / YC Technical Interviewers  
> **Repository Baseline**: `release/v1.5.2-rc1`  
> **Verification Standards**: Every diagram and sequence corresponds directly to source code in `recondesk-backend/app/`, `recondesk-frontend/`, and deployment specifications.

---

## 1. Architectural Principles & Invariants

ReconDesk is engineered around **five non-negotiable architectural invariants**:
1. **Zero Floating-Point Financial Arithmetic**: All monetary quantities (taxable amount, CGST, SGST, IGST, Cess, differences) are ingested, computed, compared, and stored as 64-bit integer paise (`BigInteger`). 
2. **Decoupled Asynchronous Processing**: No long-running calculation or external government network call occurs in the HTTP request-response cycle. Heavy operations are dispatched to Celery background workers across 7 isolated queues.
3. **Strict Tenancy Boundaries**: Every database query and business transaction is anchored to `firm_owner_id` (the CA Principal) and scoped to `client_gstin_id`. Cross-tenant data leakage is prevented at both the application repository layer and foreign key constraints.
4. **Idempotent Ingestion & Duplicate Protection**: Ingestion pipelines hash file contents (`file_hash`) and enforce database uniqueness constraints (`uq_run_dedup`), ensuring duplicate uploads cannot corrupt ledger states.
5. **Fail-Closed Security & Trust Boundaries**: Unauthenticated requests, missing authorization roles, or staging environments attempting to access production assets trigger immediate, automated aborts.

---

## 2. The 14 Comprehensive Architecture Diagrams

---

### Diagram A: High-Level Overall System Architecture

```mermaid
flowchart TB
    subgraph PublicInternet ["Public Internet (Untrusted Zone)"]
        UserBrowser["Web Browser (CA / Tax Staff / Client)"]
        RazorpayServers["Razorpay Payment Gateway Servers"]
        GovPortal["GSTN Portal / Government Servers"]
    end

    subgraph CloudflareZone ["Edge & DNS Layer (Cloudflare)"]
        CFDNS["Cloudflare DNS & DDoS Shield"]
        R2Buckets[("Cloudflare R2 Object Storage<br/>(recondesk-uploads)")]
    end

    subgraph AWSCloud ["AWS Cloud Infrastructure (ap-south-1)"]
        subgraph AmplifyHosting ["AWS Amplify Hosting (SSR Compute)"]
            NextEdge["Next.js 14 App Router<br/>(Server Components & SSR)"]
        end

        subgraph EC2Host ["AWS EC2 Host (Compute Container Cluster)"]
            CaddyProxy["Caddy 2 Reverse Proxy<br/>(api.recondesk.in :443)"]
            FastAPIApp["FastAPI ASGI Application Server<br/>(web:8000 / 59 Routers)"]
            RedisBroker["Redis 7 In-Memory Broker<br/>(redis:6379)"]
            CeleryWorker["Celery 5 Worker Fleet<br/>(7 Domain Queues / Concurrency=2)"]
        end

        subgraph ManagedServices ["AWS Managed Data & Identity Services"]
            CognitoPool["Amazon Cognito User Pool<br/>(ap-south-1_nvlPYMvFh)"]
            AuroraDB[("AWS Aurora Serverless v2 PostgreSQL<br/>(Multi-AZ Replicated Storage)")]
            SESMail["Amazon SES SMTP<br/>(email-smtp.ap-south-1.amazonaws.com)"]
        end
    end

    subgraph ExternalGateways ["External Partner APIs"]
        SandboxAPI["Sandbox.co.in GSTN & E-Invoice Gateway"]
    end

    UserBrowser -->|HTTPS / Port 443| CFDNS
    CFDNS -->|Web Traffic| NextEdge
    CFDNS -->|API Traffic| CaddyProxy
    CaddyProxy -->|HTTP / Internal Bridge| FastAPIApp

    NextEdge -->|Client / Server Fetch| CaddyProxy
    FastAPIApp -->|Token Verification| CognitoPool
    FastAPIApp -->|Direct SQL / Pool| AuroraDB
    FastAPIApp -->|Enqueue Task| RedisBroker

    RedisBroker -->|Dequeue Task| CeleryWorker
    CeleryWorker -->|Read/Write Records| AuroraDB
    CeleryWorker -->|Store Large Payloads| R2Buckets
    CeleryWorker -->|Transactional Mail| SESMail
    CeleryWorker -->|GSP API Calls| SandboxAPI

    SandboxAPI --> GovPortal
    RazorpayServers -->|Webhooks / HMAC-SHA256| CaddyProxy
```

#### Node & Flow Analysis:
* **Trust Boundaries**: Public Internet is untrusted. Caddy 2 terminates TLS, enforcing HSTS preload. The communication between Caddy, FastAPI, Redis, and Celery is strictly private inside Docker’s bridge network on EC2.
* **Sensitive Financial Data**: Invoices move from Browser $\rightarrow$ FastAPI $\rightarrow$ Celery $\rightarrow$ Aurora DB. Large result payloads are encrypted in transit and offloaded to Cloudflare R2 (`reconciliation-payloads/`).
* **Points of Failure**: If Redis restarts, unacknowledged tasks persist on disk via `dump.rdb` or re-enqueue automatically. If Aurora fails over, SQLAlchemy recycles connections within 1,800s.

---

### Diagram B: Frontend Architecture (Next.js 14 App Router)

```mermaid
flowchart TD
    subgraph ClientBrowser ["Client Browser Runtime"]
        subgraph ViewportLayer ["Virtualized Viewport"]
            VirtualTable["TanStack Virtual Table<br/>(@tanstack/react-virtual)"]
            ModalManager["Audit & Rationale Drawers"]
        end
        subgraph StateLayer ["Client State & Cache"]
            SWRClient["SWR Cache & Revalidation Store"]
            AuthContext["Cognito Auth State & Session Cookies"]
        end
    end

    subgraph NextServer ["Next.js 14 SSR Server (Amplify / Node.js)"]
        MiddlewareEdge["middleware.ts<br/>(Route Guard & Token Check)"]
        
        subgraph RouteGroups ["Route Groups (app/)"]
            DashboardGroup["(dashboard)/<br/>Authenticated Workspaces"]
            AuthGroup["(auth)/<br/>Login, Signup, Callback"]
            LandingGroup["(landing)/<br/>Public Marketing & SSR Pages"]
        end

        subgraph BFFRoutes ["Backend-for-Frontend (/api/*)"]
            ProxyRouter["api/backendProxy.ts<br/>(CORS-Safe Forwarder)"]
            CognitoCallback["api/auth/cognito/callback/<br/>(Token Exchange)"]
        end
    end

    subgraph BackendAPI ["ReconDesk Backend API (api.recondesk.in)"]
        APIRouters["FastAPI Routers (/api/v1/*)"]
    end

    ClientBrowser -->|HTTP Request| MiddlewareEdge
    MiddlewareEdge -->|Authorized| RouteGroups
    MiddlewareEdge -->|Unauthenticated| AuthGroup

    DashboardGroup --> VirtualTable
    VirtualTable --> SWRClient
    SWRClient -->|Client Fetch| ProxyRouter
    ProxyRouter -->|HTTPS + Bearer Token| APIRouters
    CognitoCallback --> AuthContext
```

#### Node & Flow Analysis:
* **Rendering Strategy**: Landing pages use Server-Side Rendering (SSR) for SEO. Dashboard workspaces are Client Components (`"use client"`) using SWR for optimistic UI updates.
* **Large Table Rendering**: [`ReconcileTableVirtual.tsx`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-frontend/components/reconcile/) mounts `@tanstack/react-virtual` to calculate DOM row slices based on scroll offsets.
* **Points of Failure**: Token expiration triggers an automatic redirect to `/auth/login` via `middleware.ts`. Network timeouts trigger SWR retries with exponential backoff.

---

### Diagram C: Backend Architecture (FastAPI & Services)

```mermaid
flowchart TD
    subgraph Ingress ["API Ingress & Middleware Pipeline"]
        Request["Incoming HTTP Request"] --> CId["CorrelationIdMiddleware<br/>(Generates X-Correlation-ID)"]
        CId --> SlowAPI["SlowAPIMiddleware<br/>(Token Bucket Rate Limiter)"]
        SlowAPI --> CORS["CORSMiddleware<br/>(Strict Origin Validation)"]
        CORS --> AuthDep["FastAPI Dependency Injection<br/>(get_current_user / app/auth.py)"]
    end

    subgraph RouterTree ["Mounted Router Hierarchy (59 Routers)"]
        AuthDep --> AuthRouter["/api/v1/auth & cognito_auth"]
        AuthDep --> ReconRouter["/api/v1/reconciliation & /reconcile"]
        AuthDep --> FilingRouter["/api/filing (GSTR-1 / 3B / 9)"]
        AuthDep --> BillingRouter["/api/billing & /api/payments"]
        AuthDep --> ClientsRouter["/api/clients (GSTIN Scoping)"]
    end

    subgraph ServiceLayer ["Service & Business Logic Layer (94 Services)"]
        ReconRouter --> ReconService["reconciliation_service.py"]
        ReconService --> MatcherCore["matcher.py (L1-L6 Engine)"]
        FilingRouter --> FilingOrch["gstr1_orchestrator.py"]
        BillingRouter --> PaymentService["payments.py (Razorpay SDK)"]
        ClientsRouter --> TenancyRepo["repositories/tenancy.py"]
    end

    subgraph PersistenceLayer ["Data Access & Storage"]
        MatcherCore --> AuroraAdapter["AuroraClient / SQLAlchemy Session"]
        FilingOrch --> AuroraAdapter
        TenancyRepo --> AuroraAdapter
        AuroraAdapter --> AuroraDB[("AWS Aurora PostgreSQL")]
        ReconService --> RedisQ["Redis Task Queue (Celery)"]
    end
```

#### Node & Flow Analysis:
* **Request Lifecycle**: Every request passes through `CorrelationIdMiddleware` $\rightarrow$ `SlowAPIMiddleware` $\rightarrow$ `CORSMiddleware` $\rightarrow$ Route Dependency (`get_current_user`).
* **Dependency Injection**: Routes inject database sessions (`get_supabase` / `AuroraClient`) and authenticated user profiles (`AuthenticatedUser`), preventing shared mutable state across threads.
* **Points of Failure**: If an unhandled exception occurs, the global exception handler in [`main.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py#L430-L448) catches it, records the stack trace to Sentry, and returns a standard JSON error response (`HTTP 500`).

---

### Diagram D: Database Architecture & Multi-Tenancy Scoping

```mermaid
erDiagram
    user_profiles ||--o{ client_gstins : "owns (firm_owner_id)"
    user_profiles ||--o{ team_members : "firm_owner_id"
    user_profiles ||--o{ team_members : "member_user_id"
    user_profiles ||--o{ client_gstins : "assigned_to"

    client_gstins ||--o{ reconciliation_run : "client_gstin_id"
    reconciliation_run ||--o{ gstr_records : "run_id"
    reconciliation_run ||--o{ pr_records : "run_id"
    reconciliation_run ||--o{ reconciliation_results : "run_id"

    user_profiles ||--o{ billing_invoices : "user_id"
    user_profiles ||--o{ billing_subscriptions : "user_id"

    user_profiles {
        uuid id PK
        string email
        string firm_name
        string role
        integer runs_balance
        integer gstin_limit
        datetime created_at
    }

    client_gstins {
        uuid id PK
        uuid firm_owner_id FK
        string gstin
        string legal_name
        string trade_name
        uuid assigned_to FK
        boolean is_active
    }

    reconciliation_run {
        uuid id PK
        uuid client_gstin_id FK
        string period
        string file_hash
        string status
        bigint itc_at_risk
        bigint wrongful_itc
        datetime created_at
    }

    gstr_records {
        uuid id PK
        uuid run_id FK
        string supplier_gstin
        string invoice_number
        date invoice_date
        bigint taxable_amount_paise
        bigint igst_paise
        bigint cgst_paise
        bigint sgst_paise
        integer match_level
        string match_status
    }

    pr_records {
        uuid id PK
        uuid run_id FK
        string supplier_gstin
        string invoice_number
        date invoice_date
        bigint taxable_amount_paise
        bigint igst_paise
        bigint cgst_paise
        bigint sgst_paise
        boolean is_paid
        date payment_date
    }
```

#### Node & Flow Analysis:
* **Primary Tenancy Anchor**: `user_profiles.id` is the root anchor for the CA Firm.
* **Cascade Deletions**: Deleting a `reconciliation_run` cascades to delete associated `gstr_records`, `pr_records`, and `reconciliation_results` via foreign key `ON DELETE CASCADE`.
* **Points of Failure**: Inadvertent queries omitting `firm_owner_id` or `client_gstin_id` are caught by repository tests ([`test_aurora_tenancy.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_aurora_tenancy.py)).

---

### Diagram E: Authentication & Authorization Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor User as User / CA Staff
    participant FE as Next.js 14 Frontend
    participant Cog as Amazon Cognito User Pool
    participant API as FastAPI Backend (/api/v1/*)
    participant Verifier as cognito_verifier.py
    participant Aurora as AWS Aurora PostgreSQL

    User->>FE: Submits Email & Password
    FE->>Cog: InitiateAuth (USER_PASSWORD_AUTH)
    Cog-->>FE: Returns ID Token, Access Token (RS256 JWT), Refresh Token
    FE->>FE: Stores Tokens in HttpOnly Secure Cookies

    User->>FE: Navigates to Dashboard / Reconcile
    FE->>API: GET /api/v1/reconcile/runs (Header: Bearer <AccessToken>)
    API->>Verifier: verify_cognito_token(token)
    
    critical Verify RS256 JWT Signature
        Verifier->>Verifier: Check In-Memory JWKS Cache (TTL: 3600s)
        opt JWKS Cache Expired
            Verifier->>Cog: Fetch /.well-known/jwks.json
            Verifier->>Verifier: Update Cache & Cooldown (10s)
        end
        Verifier->>Verifier: Validate Signature, Claims, Expiry (exp), Client ID (aud)
    end

    Verifier-->>API: Extracted Claims (sub, email, username)
    API->>Aurora: SELECT * FROM user_profiles WHERE id = claims.sub
    Aurora-->>API: UserProfile (role="partner", firm_owner_id=UUID)
    API->>API: Check Role Authorization (is_writer_or_above)
    API->>Aurora: Execute Scoped Query (WHERE firm_owner_id = UUID)
    Aurora-->>API: User's Reconciliation Runs
    API-->>FE: HTTP 200 OK (JSON Response)
    FE-->>User: Displays Dashboard Data
```

#### Node & Flow Analysis:
* **Cryptographic Verification**: Tokens are verified locally using Cognito’s RS256 public key bundle (`jwks.json`), preventing network round-trips on every API call.
* **Fail-Closed RBAC**: If a user’s role is unrecognized or missing, [`roles.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/models/roles.py#L78) assigns `DEFAULT_FAIL_CLOSED_ROLE = "viewer"`, strictly revoking write/filing permissions.

---

### Diagram F: File Upload & Ingestion Pipeline

```mermaid
sequenceDiagram
    autonumber
    actor User as Chartered Accountant
    participant FE as Next.js Upload Wizard
    participant API as FastAPI Ingestion Router
    participant R2 as Cloudflare R2 Storage
    participant Redis as Redis Message Broker
    participant Worker as Celery Worker (imports queue)
    participant Aurora as AWS Aurora PostgreSQL

    User->>FE: Drops GSTR-2B JSON & PR Excel Files
    FE->>API: POST /api/v1/upload (Multipart Form Data)
    API->>API: Compute SHA-256 Hash of Files
    API->>Aurora: Check Existing Run (uq_run_dedup: client_id, period, file_hash)
    
    alt Duplicate File Detected
        API-->>FE: HTTP 409 Conflict ("Duplicate file upload detected")
    else Fresh Upload
        API->>R2: PutObject (recondesk-uploads/raw/{client_id}/{hash})
        R2-->>API: Upload Success
        API->>Aurora: INSERT INTO reconciliation_run (status="QUEUED", r2_key=...)
        API->>Redis: Enqueue worker.run_import_job (Queue: "imports")
        API-->>FE: HTTP 202 Accepted {run_id: UUID, status: "QUEUED"}
    end

    Worker->>Redis: Dequeue worker.run_import_job
    Worker->>Aurora: UPDATE reconciliation_run SET status="IMPORTING", last_heartbeat=NOW()
    Worker->>R2: GetObject (Read raw bytes)
    Worker->>Worker: Parse Records (OpenPyXL / JSON Parser)
    Worker->>Worker: Sanitize GSTINs, Strip Spaces, Convert Amounts to Integer Paise
    Worker->>Aurora: BATCH INSERT INTO gstr_records & pr_records (Chunks of 500)
    Worker->>Aurora: UPDATE reconciliation_run SET status="READY", progress_percent=100
    Worker->>Redis: Acknowledge Task Completion
```

#### Node & Flow Analysis:
* **Deduplication**: `file_hash` prevents duplicate processing of identical client files.
* **Batch Inserts**: Ingested records are inserted in parameterized chunks of 500 rows to optimize database transaction buffers and avoid statement timeouts.

---

### Diagram G: Celery & Redis Background Processing Pipeline

```mermaid
flowchart TD
    subgraph FastAPIWeb ["FastAPI Web Server"]
        Trigger["Run Triggered (/api/reconcile/start)"]
        Watchdog["Background Stuck Job Watchdog<br/>(Every 300s / main.py)"]
    end

    subgraph RedisBroker ["Redis 7 Message Broker"]
        QRecon["Queue: reconciliation"]
        QImports["Queue: imports"]
        QFiling["Queue: filing"]
        QExports["Queue: exports"]
        QDeadLetter["Dead Letter / Failed Queue"]
    end

    subgraph CeleryFleet ["Celery Worker Fleet (EC2)"]
        Worker1["Worker Process 1<br/>(Task: execute_reconciliation)"]
        Worker2["Worker Process 2<br/>(Task: process_filing_batch)"]
        Heartbeat["JobHeartbeat Thread<br/>(Emits update every 30s)"]
    end

    subgraph StorageTargets ["Persistence & Audit"]
        AuroraDB[("AWS Aurora PostgreSQL")]
        Sentry["Sentry Error Logging"]
    end

    Trigger -->|Enqueues Task| QRecon
    QRecon -->|Pops Task| Worker1
    Worker1 --> Heartbeat
    Heartbeat -->|UPDATE last_heartbeat_at| AuroraDB

    Worker1 -->|Completes Successfully| AuroraDB
    Worker1 -->|Worker Crash / OOM| QRecon

    Watchdog -->|Checks Runs Silent > 900s| AuroraDB
    Watchdog -->|Fails Stale Runs| QDeadLetter
    Watchdog -->|Alerts| Sentry
```

#### Node & Flow Analysis:
* **Queue Routing**: `TASK_ROUTES` routes tasks strictly to designated queues, isolating reconciliation traffic from export and filing pipelines.
* **Worker Crash Resilience**: `task_acks_late=True` ensures tasks are returned to the queue if the process crashes before completion.

---

### Diagram H: GSTN & External API Integration Pipeline

```mermaid
sequenceDiagram
    autonumber
    participant Worker as Celery Worker / API
    participant Client as sandbox_filing_client.py
    participant SB as Sandbox.co.in GSP Gateway
    participant GSTN as Government GSTN Portal

    Worker->>Client: request_gstr2b_download(gstin, period)
    Client->>Client: Load Cached Access Token for GSTIN
    
    alt Token Missing or Expired
        Client->>SB: POST /gsp/authenticate (API Key & Secret)
        SB-->>Client: New GSP Auth Token
        Client->>SB: POST /gsp/taxpayer/otp (Request OTP)
        SB->>GSTN: Trigger Mobile OTP
        Note over Client,Worker: CA enters OTP in ReconDesk UI
        Client->>SB: POST /gsp/taxpayer/token (Submit OTP)
        SB->>GSTN: Validate OTP
        GSTN-->>SB: Session Auth Token (Valid for 6 hours)
        SB-->>Client: Returns Encrypted GSTN Session Token
    end

    Client->>SB: GET /gsp/returns/gstr2b?gstin=...&ret_period=...
    SB->>GSTN: Fetch GSTR-2B Data
    GSTN-->>SB: Return GSTR-2B JSON (B2B, CDNR, B2BA, ISD)
    SB-->>Client: Forward Cleaned Response
    Client->>Client: Map GSTN Error Codes (gstn_error_mapper.py)
    Client-->>Worker: Parsed Statutory Invoices
```

#### Node & Flow Analysis:
* **Token Security**: GSTN access tokens have a maximum validity of 6 hours. Tokens are stored encrypted in `client_gstins.gstn_access_token`.
* **Error Resilience**: Network timeouts or transient GSTN 502 Bad Gateway responses are mapped through [`gstn_error_mapper.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/integrations/gstn_error_mapper.py) and retried with exponential jitter.

---

### Diagram I: Report Generation & Download Pipeline

```mermaid
flowchart TD
    subgraph Request ["Client Action"]
        User["User clicks 'Export Reconciliation Workbook'"]
        API["FastAPI /api/export/reconciliation"]
    end

    subgraph ExportService ["Export Orchestrator (services/reconcile_export_workbook.py)"]
        Query["Fetch Results from Aurora / R2"]
        Builder["OpenPyXL Workbook Builder"]
        Style["Apply Statutory CA Color Coding & Formulas"]
    end

    subgraph OffloadStorage ["Storage & Delivery"]
        R2Storage[("Cloudflare R2 Bucket")]
        PresignedURL["Generate Presigned Download URL (TTL: 15m)"]
    end

    User -->|GET Request| API
    API --> Query
    Query --> Builder
    Builder --> Style
    Style -->|Upload .xlsx| R2Storage
    R2Storage --> PresignedURL
    PresignedURL -->|HTTP 302 Redirect| User
    User -->|Direct Secure Download| R2Storage
```

#### Node & Flow Analysis:
* **Color Coding**: Excel workbooks generated via `reconcile_export_workbook.py` follow standardized CA audit palettes (Green for L1 Exact, Amber for Review, Red for Ineligible / At-Risk).
* **Streaming Delivery**: Workbooks are uploaded directly to Cloudflare R2 and served via short-lived presigned URLs, avoiding buffer bloat in the FastAPI web server.

---

### Diagram J: Payment & Subscription Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor CA as Firm Principal
    participant FE as Next.js Pricing Page
    participant API as FastAPI Payments Router (/api/payments)
    participant RZP as Razorpay Gateway
    participant Aurora as AWS Aurora PostgreSQL

    CA->>FE: Selects Growth Plan (Annual / ₹24,999)
    FE->>API: POST /api/payments/create-order
    API->>RZP: razorpay_client.order.create(amount=2499900, currency="INR")
    RZP-->>API: Returns Order ID (order_N8s9df7...)
    API->>Aurora: INSERT INTO billing_orders (order_id, status="CREATED", amount=2499900)
    API-->>FE: Return Order ID & Razorpay Public Key
    
    FE->>RZP: Opens Razorpay Standard Checkout Modal
    CA->>RZP: Completes UPI / Net Banking Payment
    RZP-->>FE: Returns payment_id, order_id, signature

    par Client Callback
        FE->>API: POST /api/payments/verify-signature
        API->>API: HMAC-SHA256 Verification (order_id + payment_id)
        API->>Aurora: UPDATE billing_orders SET status="PAID"
        API->>Aurora: UPDATE user_profiles SET plan="growth", gstin_limit=10, runs_balance=500
        API-->>FE: HTTP 200 OK ("Subscription activated")
    and Server Webhook (Safety Net)
        RZP->>API: POST /api/v1/webhooks/razorpay (Event: payment.captured)
        API->>API: Verify Webhook Signature via RAZORPAY_KEY_SECRET
        API->>Aurora: Check Idempotency (Skip if already processed)
        API->>Aurora: Ensure Account Entitlements are Active
        API-->>RZP: HTTP 200 OK
    end
```

#### Node & Flow Analysis:
* **Double Verification**: Payments are verified both via the client checkout callback and an authoritative server-to-server webhook, preventing lost subscriptions if a user closes the browser mid-checkout.
* **Idempotency**: Webhook events check order statuses before updating balances, preventing duplicate credit allocation.

---

### Diagram K: AWS Infrastructure & Production Deployment

```mermaid
flowchart TD
    subgraph Internet ["Public Ingress"]
        DNS["Route 53 / Cloudflare DNS<br/>(recondesk.in & api.recondesk.in)"]
    end

    subgraph AWSVPC ["AWS Virtual Private Cloud (ap-south-1)"]
        subgraph PublicSubnet ["Public Subnet"]
            EC2["AWS EC2 Instance (Ubuntu 22.04 LTS)"]
            subgraph DockerCompose ["Docker Compose Production Stack"]
                Caddy["Caddy 2 Container (:80 / :443)"]
                Web["FastAPI Web Container (:8000)"]
                Worker["Celery Worker Container (7 Queues)"]
                Redis["Redis 7 Container (:6379)"]
            end
        end

        subgraph PrivateSubnet ["Private Subnet (Secure DB Tier)"]
            Aurora["AWS Aurora Serverless v2 PostgreSQL<br/>(Multi-AZ Writer + Storage Fleet)"]
        end
    end

    subgraph ExternalSaaS ["External Cloud & Managed SaaS"]
        Amplify["AWS Amplify Hosting SSR<br/>(recondesk.in)"]
        Cognito["Amazon Cognito User Pool"]
        R2["Cloudflare R2 Object Storage"]
    end

    DNS -->|Web App Traffic| Amplify
    DNS -->|API Traffic| Caddy
    Caddy --> Web
    Web --> Redis
    Redis --> Worker
    Web -->|SQLAlchemy Connections| Aurora
    Worker -->|SQLAlchemy Connections| Aurora
    Web -->|Verify JWKS| Cognito
    Worker -->|Offload Payloads| R2
```

#### Node & Flow Analysis:
* **Network Isolation**: Aurora PostgreSQL resides in private database subnets, accessible only from the EC2 instance’s private IP via security group rules.
* **Storage Reliability**: Caddy configurations and Redis snapshots persist to mounted Docker volumes (`caddy_data`, `redis_data`).

---

### Diagram L: Monitoring, Error Handling & Disaster Recovery

```mermaid
flowchart TD
    subgraph ProbeSystem ["Health & Liveness Probes"]
        Monitor["Health Monitor / Railway Probe"]
        HealthEndpoint["GET /health (app/main.py)"]
    end

    subgraph ProbeTargets ["Subsystem Liveness Checks (2.0s Max Timeout)"]
        PingAurora["Aurora PostgreSQL Ping (SELECT 1)"]
        PingR2["Cloudflare R2 Soft Head Object"]
        PingRedis["Redis PING"]
        PingSupabase["Supabase Ping"]
    end

    subgraph ErrorTelemetry ["Exception & Crash Telemetry"]
        UnhandledException["Unhandled Exception Handler"]
        LogSafety["log_safety.py (Masks PAN, GSTIN, OTP, Tokens)"]
        SentryService["Sentry Cloud Error Tracking"]
    end

    subgraph AutoRecovery ["Automatic Disaster Recovery"]
        StuckDetector["Stuck Job Detector (stuck_job_detector)"]
        Failover["Aurora Multi-AZ Automatic Failover"]
        TaskRequeue["Celery Rejection & Re-enqueue"]
    end

    Monitor --> HealthEndpoint
    HealthEndpoint --> PingAurora
    HealthEndpoint --> PingR2
    HealthEndpoint --> PingRedis
    HealthEndpoint --> PingSupabase

    UnhandledException --> LogSafety
    LogSafety --> SentryService

    StuckDetector -->|Resets Frozen Runs > 900s| AutoRecovery
```

#### Node & Flow Analysis:
* **Fast Probing**: [`/health`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py#L803-L920) executes all checks via `asyncio.wait_for()` with a strict 2.0-second timeout, preventing hanging probes during upstream outages.
* **Zero PII Exposure**: Telemetry sent to Sentry is scrubbed of all Indian tax identifiers, banking details, and credentials.

---

### Diagram M: Multi-Tenant Data Isolation & Security Boundaries

```mermaid
flowchart TD
    subgraph UserContext ["User Authentication Context"]
        UserA["CA Firm A (firm_owner_id: UUID_A)"]
        UserB["CA Firm B (firm_owner_id: UUID_B)"]
    end

    subgraph APISecurityBoundary ["FastAPI Security Enforcement Layer"]
        Dep["get_current_user Dependency"]
        TenantGuard["Tenancy Guard: Enforces firm_owner_id scoping"]
    end

    subgraph AuroraDatabase ["AWS Aurora Database (Shared Multi-Tenant Storage)"]
        subgraph TenantAData ["Firm A Partition / Scoped Rows"]
            GSTINA["Client GSTINs (firm_owner_id = UUID_A)"]
            RunsA["Reconciliation Runs (client_gstin_id IN GSTINA)"]
            RecordsA["GSTR & PR Invoices (run_id IN RunsA)"]
        end

        subgraph TenantBData ["Firm B Partition / Scoped Rows"]
            GSTINB["Client GSTINs (firm_owner_id = UUID_B)"]
            RunsB["Reconciliation Runs (client_gstin_id IN GSTINB)"]
            RecordsB["GSTR & PR Invoices (run_id IN RunsB)"]
        end
    end

    UserA --> Dep
    UserB --> Dep
    Dep --> TenantGuard
    TenantGuard -->|Strictly Routes Query| TenantAData
    TenantGuard -.->|BLOCKS Cross-Tenant Access (HTTP 403 / 404)| TenantBData
```

#### Node & Flow Analysis:
* **Authorization Predicate**: Every query joining `reconciliation_run` must join `client_gstins` and match `firm_owner_id = current_user.firm_owner_id`.
* **IDOR Prevention**: An attacker attempting to view Run `UUID_X` belonging to another firm receives an immediate HTTP 404 Not Found or HTTP 403 Forbidden.

---

### Diagram N: External Service Dependencies & Failure Matrix

```mermaid
flowchart LR
    subgraph CorePlatform ["ReconDesk Core Application"]
        FastAPI["FastAPI Web Engine"]
        Celery["Celery Task Fleet"]
    end

    subgraph ExternalThirdParties ["External Services & Failure Impact"]
        SB["Sandbox.co.in (GSTN API)"]
        RZP["Razorpay Gateway"]
        SES["Amazon SES"]
        R2["Cloudflare R2"]
        Cog["Amazon Cognito"]
        Sentry["Sentry Monitoring"]
    end

    FastAPI --> Cog
    FastAPI --> RZP
    FastAPI --> Sentry
    Celery --> SB
    Celery --> SES
    Celery --> R2
```

#### Dependency Failure Mitigation Table:

| External Service | Operational Role | Consequence If Down | Automated Fallback / Mitigation |
| :--- | :--- | :--- | :--- |
| **Sandbox.co.in** | GSTN & E-Invoice Gateway | GSTR-2B autofetch & filing fails | Fallback to manual Excel/JSON file upload; user notification |
| **Amazon Cognito** | Authentication & Identity | Logins & token refreshes fail | Cached JWKS verification keeps existing active sessions alive |
| **Cloudflare R2** | Upload & Payload Storage | Large result payloads cannot save | Fallback to direct Aurora database JSONB storage (`RECONCILIATION_PAYLOAD_STORAGE=auto`) |
| **Razorpay** | Subscription Payments | Upgrades & checkouts fail | Existing paid subscriptions remain active until expiration |
| **Amazon SES** | Email Notifications | Email alerts delayed | Fallback to Resend SDK or background queue retry with backoff |
| **Sentry** | Error Telemetry | Telemetry dropped | Non-blocking execution; platform operates normally |

---

## 3. Architecture Interview Questions & Exercises

### 3.1 Self-Testing Questions for the Founder
1. **Trace the exact path of an invoice number from the moment a user uploads an Excel file to its storage in Aurora.** Which components touch it?
2. **What prevents an API thread from locking up when a user uploads a 50,000-line workbook?**
3. **How does ReconDesk guarantee that Firm A cannot inspect Firm B's reconciliation data?**
4. **Explain how the Celery heartbeat watchdog works.** What triggers a job status change to `FAILED`?
5. **Why does ReconDesk offload large match results to Cloudflare R2 instead of storing them directly in PostgreSQL?**

### 3.2 Practical Verification Exercises
* **Exercise 1 (Mermaid Verification)**: Review Diagram E (Authentication). Trace lines 15–22 in [`recondesk-backend/app/auth.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/auth.py) and confirm the JWKS caching logic.
* **Exercise 2 (Payload Storage Inspection)**: Open [`recondesk-backend/app/services/reconciliation_payload_store.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/services/reconciliation_payload_store.py) and identify the threshold where a match payload is offloaded to Cloudflare R2.
