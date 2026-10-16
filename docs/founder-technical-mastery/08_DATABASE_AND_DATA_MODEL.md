# Volume 08: Database Architecture, Aurora Data Model & Multi-Tenancy

> **Document ID**: `RD-TECH-08`  
> **Author**: Chief Technology Officer & Principal Systems Architect  
> **Target Audience**: ReconDesk Founder, Database Engineers, Technical Due Diligence Reviewers, EF / YC Technical Interviewers  
> **Repository Baseline**: `release/v1.5.2-rc1`  
> **Primary Source Evidence**: [`recondesk-backend/app/models/tenancy.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/models/tenancy.py), [`reconciliation.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/models/reconciliation.py), [`billing.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/models/billing.py), [`aurora_client.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/aurora_client.py), [`aurora.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/aurora.py), [`alembic/versions/`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/alembic/versions/).

---

## 1. Executive Summary & Database Foundations

In financial SaaS applications, the database is the authoritative source of legal truth. A failure in data modeling—such as floating-point rounding drift, orphaned records from cascading deletes, or cross-tenant query leaks—can result in catastrophic business and legal consequences.

ReconDesk uses **AWS Aurora Serverless v2 PostgreSQL (PostgreSQL 15+)** as its primary production relational database engine. 

### Core Database Invariants:
1. **Integer-Paise Financial Storage**: All currency columns are 64-bit integer paise (`BigInteger`), eliminating floating-point rounding errors.
2. **Deterministic Multi-Tenant Partitioning**: All data is scoped hierarchically under `firm_owner_id` (the CA Firm Principal) and `client_gstin_id`.
3. **PostgREST-to-Aurora Client Adapter (`AuroraClient`)**: Translates fluent method chaining into parameterized SQL, decoupling the business layer from underlying database drivers while maintaining high query performance.
4. **Resilient Connection Pooling**: SQLAlchemy connection pool configured with active health checks (`pool_pre_ping=True`) and aggressive recycling (`pool_recycle=1800s`) to survive Aurora DNS failovers without dropped user sessions.

---

## 2. Complete Entity-Relationship (ER) Architecture

```mermaid
erDiagram
    user_profiles ||--o{ client_gstins : "owns (firm_owner_id)"
    user_profiles ||--o{ team_members : "firm_owner_id (CA Principal)"
    user_profiles ||--o{ team_members : "member_user_id (Staff Member)"
    user_profiles ||--o{ client_gstins : "assigned_to (Staff Assignee)"

    client_gstins ||--o{ reconciliation_run : "client_gstin_id"
    reconciliation_run ||--o{ gstr_records : "run_id"
    reconciliation_run ||--o{ pr_records : "run_id"
    reconciliation_run ||--o{ reconciliation_results : "run_id"

    user_profiles ||--o{ billing_orders : "user_id"
    user_profiles ||--o{ billing_subscriptions : "user_id"
    user_profiles ||--o{ client_authorizations : "firm_owner_id"

    user_profiles {
        uuid id PK "Root Tenant ID"
        string email "Unique Login"
        string role "owner / partner / manager / preparer / viewer"
        integer runs_balance "Available Reconciliation Credits"
        integer gstin_limit "Allowed Active GSTIN Registrations"
        datetime created_at
    }

    client_gstins {
        uuid id PK "Client Identifier"
        uuid firm_owner_id FK "Multi-Tenant Firm Anchor"
        string gstin "15-char Indian GSTIN"
        string legal_name "Statutory Registered Name"
        uuid assigned_to FK "Staff Assignee"
        string scheme_type "regular / composition / casual"
        boolean is_active
    }

    reconciliation_run {
        uuid id PK "Execution Run Header"
        uuid client_gstin_id FK "Scoped Client GSTIN"
        string period "Tax Return Period (YYYY-MM)"
        string file_hash "SHA-256 Ingestion Hash"
        string status "QUEUED / IMPORTING / MATCHING / COMPLETED / FAILED"
        bigint itc_at_risk "Paise Value of Missed Credits"
        bigint wrongful_itc "Paise Value of Excess Credits"
        datetime processing_started_at
        datetime last_heartbeat_at
    }

    gstr_records {
        uuid id PK
        uuid run_id FK "Reconciliation Header"
        string supplier_gstin "Counterparty Supplier"
        string invoice_number "Raw & Normalized Invoice"
        date invoice_date
        bigint taxable_amount_paise "Integer Paise"
        bigint igst_paise "Integer Paise"
        bigint cgst_paise "Integer Paise"
        bigint sgst_paise "Integer Paise"
        integer match_level "L1 to L6"
        string match_status "matched / review / unmatched"
    }

    pr_records {
        uuid id PK
        uuid run_id FK "Reconciliation Header"
        string supplier_gstin "Supplier in Books"
        string invoice_number "Invoice Number in Books"
        date invoice_date
        bigint taxable_amount_paise "Integer Paise"
        boolean is_paid "Payment Status for Rule 37"
        date payment_date "Payment Date for Rule 37"
    }
```

---

## 3. Deep Dive into Core Database Models

---

### 3.1 The Tenancy Anchor: `UserProfile` & `ClientGSTIN`
* **Source Location**: [`tenancy.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/models/tenancy.py#L31-L115)

```python
class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(GUID(), primary_key=True)
    email = Column(String(255), nullable=True)
    firm_name = Column(String(255), nullable=True)
    role = Column(String(50), default="admin", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    plan = Column(String(50), default="free", nullable=True)
    runs_balance = Column(Integer, default=0, nullable=True)
    free_runs_remaining = Column(Integer, default=2, nullable=False)
    gstin_limit = Column(Integer, default=2, nullable=False)
    subscription_ends_at = Column(DateTime(timezone=True), nullable=True)
    auto_approve_confidence_threshold = Column(Integer, default=95, nullable=False)
```

#### Line-by-Line Architectural Rationale:
* **`id` (GUID / UUIDv4)**: Acts as the root tenant anchor. Every client GSTIN and reconciliation run is linked to this ID. Using UUIDv4 instead of auto-incrementing sequential integers prevents **enumeration attacks** (where an attacker guesses `user_id=101`, `user_id=102`).
* **`runs_balance` & `free_runs_remaining`**: Implements prepaid credit metering. When a reconciliation job starts, the engine atomically decrements this counter inside a database transaction.
* **`auto_approve_confidence_threshold`**: Configurable confidence threshold (default 95%). Matches scoring below this threshold are routed to CA Review.

---

### 3.2 The Scoped Client GSTIN: `ClientGSTIN`
* **Source Location**: [`tenancy.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/models/tenancy.py#L186-L250)

```python
class ClientGSTIN(Base):
    __tablename__ = "client_gstins"
    __table_args__ = (
        UniqueConstraint("firm_owner_id", "gstin", name="uq_client_gstins_firm_gstin"),
        CheckConstraint(
            "scheme_type IN ('regular', 'composition', 'casual', 'nrtp', 'isd', 'tds_tcs_deductor')",
            name="ck_client_gstins_scheme_type",
        ),
        Index("idx_client_gstins_firm_owner_id", "firm_owner_id"),
        Index("idx_client_gstins_gstin", "gstin"),
    )

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    firm_owner_id = Column(GUID(), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    gstin = Column(String(15), nullable=False)
    legal_name = Column(String(255), nullable=True)
    assigned_to = Column(GUID(), ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True)
    gstn_access_token = Column(String, nullable=True)
    gstn_token_expiry = Column(DateTime(timezone=True), nullable=True)
```

#### Key Invariants:
* **Unique Constraint `uq_client_gstins_firm_gstin`**: A firm cannot accidentally register the same GSTIN twice. However, two different accounting firms can represent the same GSTIN (e.g. during a CA transition), maintaining flexibility while preventing internal duplicates.
* **`assigned_to`**: Maps to a staff team member (`TeamMember`), allowing a CA Partner to delegate specific client GSTINs to junior accountants.

---

### 3.3 The Ingestion & Matching Records: `ReconciliationRun` & `GstrRecord`
* **Source Location**: [`reconciliation.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/models/reconciliation.py#L96-L230, L233-L338)

```python
class ReconciliationRun(Base):
    __tablename__ = "reconciliation_run"
    __table_args__ = (
        UniqueConstraint("client_gstin_id", "period", "file_type", "file_hash", name="uq_run_dedup"),
        Index("idx_reconciliation_run_client_created_at", "client_gstin_id", "created_at"),
        Index("idx_reconciliation_run_status", "status"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    client_gstin_id = Column(GUID(), ForeignKey("client_gstins.id"), nullable=True)
    period = Column(String, nullable=False)
    file_hash = Column(String, nullable=True)
    status = Column(String, default="queued", nullable=True)
    itc_at_risk = Column(BigInteger, nullable=True)
    wrongful_itc = Column(BigInteger, nullable=True)
    late_itc = Column(BigInteger, nullable=True)
```

#### Key Invariants:
* **Unique Constraint `uq_run_dedup`**: Computes a SHA-256 hash of the uploaded workbook. If a user uploads the exact same file for the same client and tax period, PostgreSQL raises an integrity violation, preventing duplicate processing.
* **Financial Risk Aggregation (`itc_at_risk`, `wrongful_itc`, `late_itc`)**: Stored directly on the run header as 64-bit integer paise, allowing instant dashboard rendering without recalculating sums across hundreds of thousands of line items.

---

## 4. The PostgREST-to-SQL Adapter (`AuroraClient`)

* **Source Location**: [`aurora_client.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/aurora_client.py#L1-L85)

### 4.1 The Engineering Dilemma
ReconDesk originally used Supabase’s Python SDK (`supabase-py`), which uses PostgREST method chaining:
```python
# Legacy PostgREST query style used across 59 routers:
db.table("client_gstins").select("id, gstin").eq("firm_owner_id", user_id).execute()
```
When migrating to AWS Aurora PostgreSQL, rewriting thousands of query lines across 59 routers and 94 services into raw SQLAlchemy ORM syntax would have introduced widespread regressions and taken months.

### 4.2 The Adapter Architecture
ReconDesk created [`AuroraClient`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/aurora_client.py), a custom query compiler that mimics the PostgREST API:

```python
class AuroraQueryBuilder:
    def __init__(self, table_name: str, engine):
        self._table = table_name
        self._engine = engine
        self._select_cols = "*"
        self._wheres: list[tuple[str, str, Any]] = []
        self._order_by: list[str] = []
        self._limit: int | None = None

    def select(self, columns: str = "*"):
        self._select_cols = columns
        return self

    def eq(self, column: str, value: Any):
        self._wheres.append((column, "=", value))
        return self

    def execute(self) -> APIResponse:
        # 1. Compiles AST into parameterized SQL:
        # SELECT {cols} FROM {table} WHERE {col} = :param_0
        # 2. Checks out pooled connection from SQLAlchemy QueuePool
        # 3. Executes query via psycopg2 with parameterized bindings
        # 4. Returns PostgREST-compatible APIResponse(data=rows)
```

### 4.3 Why This Is a Brilliant CTO-Level Decision:
* **Zero Disruption Migration**: 100% of existing application code remains unchanged while executing native, high-performance parameterized SQL directly against AWS Aurora.
* **SQL Injection Immunity**: All parameters are bound using SQLAlchemy `:named` parameter replacements, completely neutralizing SQL injection attacks.

---

## 5. Connection Pooling & AWS Aurora Invariants

* **Source Location**: [`aurora.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/aurora.py#L76-L102)

```mermaid
flowchart TD
    subgraph AppServer ["FastAPI Application (Uvicorn Workers)"]
        Req1["Request 1"]
        Req2["Request 2"]
        ReqBurst["Burst Request 25"]
    end

    subgraph Pool ["SQLAlchemy Connection Pool (QueuePool)"]
        ActiveConnections["Base Pool (20 Persistent Connections)<br/>pool_size = 20"]
        OverflowConnections["Overflow Buffer (10 Burst Connections)<br/>max_overflow = 10"]
        PingGuard["Pre-Ping Liveness Probe<br/>pool_pre_ping = True (SELECT 1)"]
    end

    subgraph AuroraCluster ["AWS Aurora Serverless v2 PostgreSQL"]
        PrimaryWriter["Primary Writer ACU Node"]
        StorageFleet["6-Way Replicated Storage Fleet across 3 AZs"]
    end

    Req1 --> ActiveConnections
    Req2 --> ActiveConnections
    ReqBurst --> OverflowConnections
    ActiveConnections --> PingGuard
    OverflowConnections --> PingGuard
    PingGuard --> PrimaryWriter
    PrimaryWriter --> StorageFleet
```

### Critical Configuration Settings Explained:
1. `pool_size = 20`: Keeps 20 open connections per worker process ready for immediate checkout.
2. `max_overflow = 10`: Allows up to 10 additional temporary connections during filing deadline traffic surges.
3. `pool_recycle = 1800` (30 minutes): **Critical for Aurora**. In AWS Aurora, DNS endpoints point to the active writer. During a failover, AWS promotes a replica and repoints DNS. Without connection recycling, connection pools would hold stale TCP sockets to the old writer indefinitely. Recycling every 30 minutes forces DNS re-resolution.
4. `pool_pre_ping = True`: Executes a lightweight `SELECT 1` ping before handing a connection to a request. If Aurora closed an idle connection, SQLAlchemy transparently replaces it without raising an unhandled `psycopg2.OperationalError`.

---

## 6. Alembic Migrations & Schema Evolution

* **Source Location**: [`recondesk-backend/alembic/versions/`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/alembic/versions/) (37 sequential migration files)

### Automated Startup Migration Pipeline:
In [`main.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py#L297-L344), the application runs Alembic migrations on startup inside an OS subprocess with strict process timeout termination (`timeout=180s`):
```python
def _run_alembic_upgrade():
    _log.info("Startup: Beginning Alembic database migrations to head...")
    # 1. Inspect active database locks (pg_locks) to detect blocking migrations
    _log_db_locks(db_url)
    # 2. Run alembic upgrade head in isolated subprocess
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], timeout=180)
```
* **Active Lock Detection (`_log_db_locks`)**: Before running migrations, the server queries `pg_locks` and `pg_stat_activity` to detect long-running uncommitted queries that could deadlock Alembic schema alterations (`ALTER TABLE`), preventing startup hangs.

---

## 7. Database Interview Questions & Exercises

### 7.1 Founder Self-Testing Questions
1. **Why does ReconDesk store all currency values as integer paise (`BigInteger`) instead of `Float` or `Numeric(12, 2)`?**
2. **What is an enumeration attack, and how does ReconDesk's use of UUIDv4 primary keys prevent it?**
3. **Explain the purpose of `AuroraClient`. Why was this adapter built instead of rewriting the entire codebase in SQLAlchemy ORM?**
4. **What happens during an AWS Aurora failover, and how does `pool_recycle=1800` ensure high availability?**
5. **How does ReconDesk prevent database deadlocks during automated startup migrations?**

### 7.2 Practical Verification Exercises
* **Exercise 1 (UUID Tenancy Verification)**: Open [`tenancy.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/models/tenancy.py) and trace the foreign key constraint on `ClientGSTIN.firm_owner_id`. Verify what `ondelete="CASCADE"` does when a firm owner is removed.
* **Exercise 2 (Lock Detection Query)**: Inspect lines 268–275 in [`recondesk-backend/app/main.py`](file:///Users/omkarkadam/Documents/ReconDesk/recondesk-backend/app/main.py). Understand how querying `pg_locks` and `pg_stat_activity` surfaces blocked database sessions.
