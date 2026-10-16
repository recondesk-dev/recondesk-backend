# Volume 11: AWS Cloud Infrastructure, Docker & Production DevOps

> **Document ID**: `RD-TECH-11`  
> **Author**: Chief Technology Officer & Principal Systems Architect  
> **Target Audience**: ReconDesk Founder, DevOps Engineers, Cloud Architects, EF / YC Technical Interviewers  
> **Repository Baseline**: `release/v1.5.2-rc1`  
> **Primary Source Evidence**: [`docker-compose.prod.yml`](file:///Users/omkarkadam/Documents/ReconDesk/docker-compose.prod.yml), [`Caddyfile`](file:///Users/omkarkadam/Documents/ReconDesk/Caddyfile), [`amplify.yml`](file:///Users/omkarkadam/Documents/ReconDesk/amplify.yml), [`recondesk-backend/Dockerfile`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/Dockerfile), [`auto_deploy.sh`](file:///Users/omkarkadam/Documents/ReconDesk/auto_deploy.sh), [`push.sh`](file:///Users/omkarkadam/Documents/ReconDesk/push.sh), [`docs/AWS_AMPLIFY_MIGRATION_PHASE1.md`](file:///Users/omkarkadam/Documents/ReconDesk/docs/AWS_AMPLIFY_MIGRATION_PHASE1.md).

---

## 1. Executive Summary & Cloud Architecture Topology

ReconDesk uses a **hybrid cloud deployment architecture**:
1. **Compute & Ingress (AWS EC2 & Docker Compose)**: The FastAPI web server, Celery worker fleet, Redis broker, and Caddy reverse proxy run in isolated container environments on an AWS EC2 instance in region `ap-south-1` (Mumbai).
2. **Managed Relational Storage (AWS Aurora Serverless v2)**: Replicated multi-AZ PostgreSQL storage running in private VPC subnets.
3. **Frontend Edge Hosting (AWS Amplify Hosting SSR)**: Next.js 14 Server-Side Rendering (SSR) deployed via AWS Amplify `WEB_COMPUTE` architecture.
4. **Object Storage (Cloudflare R2)**: Zero-egress-fee S3-compatible storage for raw client uploads and offloaded JSON reconciliation result payloads.

```mermaid
flowchart TD
    subgraph EdgeIngress ["Edge & DNS Tier"]
        DNS["Cloudflare DNS / Route 53<br/>recondesk.in & api.recondesk.in"]
        AmplifyEdge["AWS Amplify Hosting<br/>(Next.js 14 SSR Compute)"]
    end

    subgraph EC2Host ["AWS EC2 Container Host (ap-south-1 / Ubuntu 22.04)"]
        subgraph DockerBridge ["Private Docker Bridge Network"]
            Caddy["Caddy 2 Reverse Proxy<br/>(:80, :443 / Automated TLS)"]
            FastAPI["FastAPI Web Container<br/>(web:8000 / Uvicorn ASGI)"]
            Worker["Celery Worker Container<br/>(worker: 7 queues, concurrency=2)"]
            Redis["Redis 7 Container<br/>(redis:6379 / In-Memory Broker)"]
        end
        VolumeCaddy[("Mounted Volume: caddy_data")]
        VolumeRedis[("Mounted Volume: redis_data")]
    end

    subgraph AWSManaged ["AWS Managed Cloud Tier (Private Subnets)"]
        AuroraDB[("AWS Aurora Serverless v2 PostgreSQL<br/>(Multi-AZ Auto-Scaling Storage)")]
        Cognito["Amazon Cognito User Pool<br/>(ap-south-1_nvlPYMvFh)"]
        SES["Amazon SES SMTP<br/>(email-smtp.ap-south-1.amazonaws.com)"]
    end

    subgraph CloudflareStorage ["Distributed Object Storage"]
        R2[("Cloudflare R2 Bucket<br/>(recondesk-uploads)")]
    end

    DNS -->|Web Traffic| AmplifyEdge
    DNS -->|API Traffic (Port 443)| Caddy
    AmplifyEdge -->|Internal API Calls| Caddy
    
    Caddy -->|HTTP Forwarding| FastAPI
    Caddy --- VolumeCaddy
    
    FastAPI -->|Enqueue Task| Redis
    Redis --- VolumeRedis
    Redis -->|Dequeue Task| Worker
    
    FastAPI -->|Direct SQL / Pool| AuroraDB
    Worker -->|Read / Write Invoices| AuroraDB
    Worker -->|Offload Payloads| R2
    Worker -->|Dispatch Mail| SES
    FastAPI -->|Verify JWKS| Cognito
```

---

## 2. Docker Compose Production Configuration

* **Source Location**: [`docker-compose.prod.yml`](file:///Users/omkarkadam/Documents/ReconDesk/docker-compose.prod.yml)

```yaml
services:
  caddy:
    image: caddy:2-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - web
    restart: always

  web:
    build:
      context: ./recondesk-backend
      dockerfile: Dockerfile
    environment:
      - REDIS_URL=redis://redis:6379/0
      - AURORA_DB_ENABLED=true
      - COGNITO_USER_POOL_ID=${COGNITO_USER_POOL_ID:-ap-south-1_nvlPYMvFh}
      - COGNITO_CLIENT_ID=${COGNITO_CLIENT_ID:-2qui5lp7if0g4lftbrag7o6sce}
      - COGNITO_AUTH_ENABLED=true
    env_file: .env
    depends_on:
      - redis
    restart: always

  worker:
    build:
      context: ./recondesk-backend
      dockerfile: Dockerfile
    command: celery -A app.worker.celery_app worker -Q reconciliation,imports,gstn,filing,exports,notifications,maintenance --loglevel=info --concurrency=2
    environment:
      - REDIS_URL=redis://redis:6379/0
      - AURORA_DB_ENABLED=true
      - COGNITO_AUTH_ENABLED=true
    env_file: .env
    depends_on:
      - redis
    restart: always

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    restart: always

volumes:
  caddy_data:
  caddy_config:
  redis_data:
```

### Architectural Decisions Explained:
* **Internal DNS Resolution**: In Docker Compose, containers communicate using service names as hostnames (`redis:6379`, `web:8000`). The web process connects to Redis via `redis://redis:6379/0` over Docker’s private software bridge network, completely unexposed to the public Internet.
* **Persistent Volumes**: `caddy_data` persists Let's Encrypt TLS certificates across container restarts, avoiding Let's Encrypt rate-limit lockouts. `redis_data` persists queued job states.
* **Worker Process Isolation**: The `worker` container runs the same Docker image as `web`, but overrides the entrypoint command to launch Celery listening on all 7 queues with `concurrency=2`.

---

## 3. Reverse Proxy & Automated TLS: Caddy 2

* **Source Location**: [`Caddyfile`](file:///Users/omkarkadam/Documents/ReconDesk/Caddyfile)

```caddyfile
api.recondesk.in {
    header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
    reverse_proxy web:8000
}
```

### How Caddy Handles Automated TLS:
1. When Caddy starts, it reads `api.recondesk.in`.
2. It contacts the **Let's Encrypt ACME server**, solves the HTTP-01 or TLS-ALPN-01 challenge on port 80/443, and obtains a valid 90-day X.509 certificate.
3. It configures modern ciphers (TLS 1.3, ChaCha20-Poly1305, AES-256-GCM) with **PFS (Perfect Forward Secrecy)**.
4. It sets up an internal timer to renew certificates automatically 30 days before expiration.
5. It injects the `Strict-Transport-Security` (HSTS) header with a 2-year duration (`63,072,000s`), preventing SSL-stripping man-in-the-middle attacks.

---

## 4. AWS Amplify Hosting SSR Architecture

* **Source Location**: [`amplify.yml`](file:///Users/omkarkadam/Documents/ReconDesk/amplify.yml) and [`docs/AWS_AMPLIFY_MIGRATION_PHASE1.md`](file:///Users/omkarkadam/Documents/ReconDesk/docs/AWS_AMPLIFY_MIGRATION_PHASE1.md)

### 4.1 Authoritative Build Specification (`amplify.yml`):
```yaml
version: 1
applications:
  - appRoot: recondesk-frontend
    frontend:
      phases:
        preBuild:
          commands:
            - nvm use 20 || true
            - node scripts/validate-staging-env.mjs
            - npm ci --cache .npm --prefer-offline
        build:
          commands:
            - node scripts/generate-build-env.mjs
            - npm run build
            - rm -rf .next/cache
      artifacts:
        baseDirectory: .next
        files:
          - '**/*'
      cache:
        paths:
          - .npm/**/*
```

### 4.2 Security Vulnerability Resolved (Secret Protection):
A common mistake in Amplify Next.js deployments is running `env >> .env.production`. This indiscriminately bakes private server secrets (`COGNITO_CLIENT_SECRET`, `RAZORPAY_KEY_SECRET`) into plaintext JavaScript bundles sent to browsers.

ReconDesk implements a strict **Allowlist Script** ([`generate-build-env.mjs`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-frontend/scripts/generate-build-env.mjs)):
* **Allowed Client Variables**: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_COGNITO_AUTH_ENABLED`, `NEXT_PUBLIC_RAZORPAY_KEY_ID`, `NEXT_PUBLIC_SENTRY_DSN`.
* **Strictly Blocked Secrets**: `COGNITO_CLIENT_SECRET`, `RAZORPAY_KEY_SECRET`, `DATABASE_URL`, `AWS_SECRET_ACCESS_KEY`.
* In Amplify Hosting, private secrets are injected directly into the runtime `process.env` inside the SSR compute container via AWS KMS, never written to disk.

---

## 5. Fail-Closed Staging Isolation Guard

* **Source Location**: [`recondesk-backend/app/staging_guard.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/staging_guard.py) and [`recondesk-frontend/scripts/validate-staging-env.mjs`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-frontend/scripts/validate-staging-env.mjs)

### The Catastrophic Staging Disaster:
In many startups, a staging build accidentally inherits production environment variables. A test run on staging executes migrations that wipe production tables, or a test payment charges a real corporate credit card using production Razorpay keys (`rzp_live_*`).

### ReconDesk's Multi-Layered Automated Defense:
1. **Frontend Pre-Flight Gate (`validate-staging-env.mjs`)**:
   Runs during `preBuild` in Amplify. If `APP_ENV === "staging"`, it halts the build with exit code 1 if:
   * `NEXT_PUBLIC_API_URL` points to `api.recondesk.in`.
   * `NEXT_PUBLIC_RAZORPAY_KEY_ID` contains a live key (`rzp_live_*`).
   * `COGNITO_REDIRECT_URI` points to the production domain.
2. **Backend Startup Gate (`staging_guard.py`)**:
   In [`main.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py#L350-L355), if `APP_ENV == "staging"`, the server inspects database URLs:
   ```python
   def enforce_staging_safety(settings):
       if "prod" in settings.DATABASE_URL.lower() or "aurora.recondesk.in" in settings.DATABASE_URL.lower():
           raise SystemExit("[CRITICAL] Staging aborted: Attempted connection to production database!")
   ```

---

## 6. Deployment Workflow: The Dual-Remote Invariant

* **Source Location**: [`push.sh`](file:///Users/omkarkadam/Documents/ReconDesk/push.sh) and [`AGENTS.md`](file:///Users/omkarkadam/Documents/ReconDesk/AGENTS.md)

ReconDesk enforces the **Dual-Remote Push Invariant**:
* Remote 1 (`origin main`): `https://github.com/recondesk-dev/recondesk-backend.git`
* Remote 2 (`frontend main`): `https://github.com/recondesk-dev/recondesk-frontend.git`

```bash
# Automated deployment procedure enforced by push.sh:
pytest recondesk-backend/tests/
cd recondesk-frontend && npm run build && cd ..
git add .
git commit -m "$1"
git push origin main
git push frontend main
```
* **Why**: The backend repo triggers EC2 container rebuilds, while the frontend repo triggers AWS Amplify SSR edge deployments. Pushing to both remotes simultaneously guarantees that API contracts between frontend and backend never drift out of sync.

---

## 7. DevOps Interview Questions & Exercises

### 7.1 Founder Self-Testing Questions
1. **Explain how Caddy provisions TLS certificates without human intervention.** What ACME challenges does it perform?
2. **Why does the Celery worker container mount the same Docker image as the FastAPI web container?** What is different about how the worker runs?
3. **What is the purpose of `generate-build-env.mjs` in our AWS Amplify build pipeline?** What security vulnerability does it eliminate?
4. **How does `staging_guard.py` prevent staging builds from corrupting production databases?**
5. **Why does ReconDesk mandate pushing to both `origin` and `frontend` Git remotes?**

### 7.2 Practical Verification Exercises
* **Exercise 1 (Docker Compose Verification)**: Run `docker compose -f docker-compose.prod.yml config` in your terminal. Verify that the YAML syntax compiles cleanly with zero schema errors.
* **Exercise 2 (Caddy Health Check Test)**: Run pytest on [`test_caddy_health_check.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/tests/test_caddy_health_check.py). Confirm that all Caddy reverse-proxy routing rules pass verification.
