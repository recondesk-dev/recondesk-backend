import asyncio
import logging
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import sentry_sdk
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.database import get_supabase
from app.routers import (
    admin,
    audit_logs,
    audit_observations,
    auth,
    billing,
    dashboard,
    export as export_router,
    import_router,
    intelligence,
    manage_data,
    notes,
    notifications,
    pr_upload,
    register_upload,
    reconciliation,
    reconciliation_api,
    reconciliation_import_wizard,
    reports,
    upload,
    users as users_router,
    vendors,
    webhooks,
)
from app.routers import payments as payments_routes
from app.routers.clients import clients_router
from app.routers.gstr2b_autofetch_routes import router as gstr2b_autofetch_router
from app.routers.ims_actions import router as ims_actions_router
from app.routers.gst_fetch_routes import router as gst_fetch_router
from app.routers.gstin import router as gstin_router
from app.routers.team import router as team_router
from app.routers.rules import router as rules_router
from app.routers.gstr1_reconcile import router as gstr1_reconcile_router
from app.routers.einvoice_recon import router as einvoice_recon_router
from app.routers.filing import router as filing_router
from app.routers.tally_sync import router as tally_sync_router
from app.routers.multi_period_wizard import router as multi_period_wizard_router
from app.routers.gstr9 import router as gstr9_router
from app.routers.gstr4 import router as gstr4_router
from app.routers.gstr2a_delta import router as gstr2a_delta_router
from app.routers.notices import router as notices_router
from app.routers.practice import practice_router
from app.routers.vendor_followup import (
    router as vendor_followup_router,
    public_router as vendor_public_router,
)
from app.routers.billing import masters as billing_masters_router
from app.routers.billing import invoices as billing_invoices_router
from app.routers.billing import irp as billing_irp_router
from app.routers.billing import cdn as billing_cdn_router
from app.routers.billing import ewaybill as billing_ewaybill_router
from app.routers import work_items as work_items_router
from app.routers.cognito_auth import router as cognito_auth_router
from app.utils.rate_limit import limiter


_log = logging.getLogger(__name__)

from app.utils.context import CorrelationIdMiddleware

START_TIME = datetime.now(timezone.utc)

# ── Sentry ────────────────────────────────────────────────────────────────────
if settings.SENTRY_DSN:
    from app.filing.log_safety import (
        sentry_scrub_breadcrumb,
        sentry_scrub_event,
        sentry_scrub_transaction,
    )

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.APP_ENV,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
        ],
        traces_sample_rate=0.2,
        profiles_sample_rate=0.1,
        send_default_pii=False,
        # File GSTR-1 puts EVC OTP on Sandbox query string (?otp=&pan=).
        # Scrub those keys and mask GSTIN PII from any captured request URL / exception text / breadcrumbs / transactions.
        before_send=sentry_scrub_event,
        before_send_transaction=sentry_scrub_transaction,
        before_breadcrumb=sentry_scrub_breadcrumb,
    )

_HEALTH_PROBE_KEY = "__recondesk/health_probe__"

_STUCK_STATUSES = ("MATCHING", "PROCESSING", "importing")


def _stuck_job_tick() -> None:
    supabase = get_supabase()
    # Heartbeat timeout threshold from configuration (defaults to 900s / 15m)
    timeout_seconds = getattr(settings, "JOB_HEARTBEAT_TIMEOUT_SECONDS", 900)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
    cutoff_iso = cutoff.isoformat()
    try:
        # Check active jobs whose heartbeat or start timestamp has gone silent
        stuck_runs = (
            supabase.table("reconciliation_run")
            .select("id, status, processing_started_at, updated_at")
            .in_("status", list(_STUCK_STATUSES))
            .execute()
        )
    except Exception:
        _log.exception("stuck_job_detector: query failed")
        raise

    now_iso = datetime.now(timezone.utc).isoformat()
    for run in stuck_runs.data or []:
        rid = run.get("id")
        if not rid:
            continue

        # Evaluate liveness via updated_at or processing_started_at
        last_beat_str = run.get("last_heartbeat_at") or run.get("updated_at") or run.get("processing_started_at")
        if not last_beat_str:
            # If neither timestamp is set, job was never claimed or initiated
            continue

        try:
            # Parse ISO timestamp (handling trailing Z or offsets)
            beat_dt = datetime.fromisoformat(str(last_beat_str).replace("Z", "+00:00"))
        except Exception:
            _log.warning("stuck_job_detector: invalid timestamp format '%s' for run %s", last_beat_str, rid)
            continue

        # If heartbeat is still active within cutoff, job is healthy and progressing
        if beat_dt >= cutoff:
            continue

        # Heartbeat is stale beyond threshold -> mark FAILED and record dead letter
        _log.warning(
            "stuck_job_detector: stale heartbeat detected for run %s (last_beat=%s, cutoff=%s)",
            rid,
            last_beat_str,
            cutoff_iso,
        )
        try:
            supabase.table("reconciliation_run").update(
                {
                    "status": "FAILED",
                    "status_message": f"Worker heartbeat timeout (> {timeout_seconds}s silent) — please retry",
                    "error_category": "HEARTBEAT_TIMEOUT",
                    "updated_at": now_iso,
                }
            ).eq("id", rid).execute()

            from app.worker.reliability import record_failed_job

            record_failed_job(
                client=supabase,
                task_id=str(run.get("worker_task_id") or "unknown"),
                task_name="worker.stuck_job_watchdog",
                queue="maintenance",
                exc=TimeoutError(f"Heartbeat timeout (> {timeout_seconds}s silent)"),
                entity_id=rid,
                entity_type="reconciliation_run",
                attempt_count=int(run.get("attempt_count") or 1),
                payload_summary={"last_heartbeat_at": last_beat_str, "status": run.get("status")},
            )
        except Exception:
            _log.exception("stuck_job_detector: failed to update run %s", rid)
            continue
        if settings.SENTRY_DSN:
            sentry_sdk.capture_message(
                f"Stuck job detected and reset: {rid}",
                level="error",
            )


async def stuck_job_detector() -> None:
    while True:
        await asyncio.sleep(300)
        try:
            await asyncio.to_thread(_stuck_job_tick)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if settings.SENTRY_DSN:
                sentry_sdk.capture_exception(e)
        # Heavy sync Supabase work — must not run on the event loop or /health
        # and all API requests hang until Railway returns 499.
        try:
            from app.services.rule37_alert_scan import run_rule37_alert_scan

            await asyncio.to_thread(_run_async_job_sync, run_rule37_alert_scan)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _log.exception("rule37_alert_scan failed")
            if settings.SENTRY_DSN:
                sentry_sdk.capture_exception(e)
        try:
            from app.services.supplier_compliance_scorecard import (
                run_scorecard_daily_rebuild,
            )

            await asyncio.to_thread(_run_async_job_sync, run_scorecard_daily_rebuild)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _log.exception("supplier_compliance_scorecard rebuild failed")
            if settings.SENTRY_DSN:
                sentry_sdk.capture_exception(e)


def _run_async_job_sync(coro_fn) -> None:
    """Run an ``async def`` job that only does sync I/O, from a worker thread."""
    import asyncio as _asyncio

    _asyncio.run(coro_fn())


DATABASE_CHECK_TIMEOUT_SECONDS = 30.0


def _verify_database_connection() -> None:
    _log.info("Startup: Checking database connectivity (AWS Aurora PostgreSQL)...")
    db = get_supabase()
    db.table("client_gstins").select("id").limit(1).execute()
    _log.info("Startup: Database connection verified successfully.")


def _log_db_locks(db_url: str) -> None:
    """Query and log any active DB locks/blocking queries on target DB."""
    try:
        import sqlalchemy as sa
        eng = sa.create_engine(db_url)
        with eng.connect() as conn:
            res = conn.execute(
                sa.text(
                    """
                    SELECT pid, locktype, mode, granted, query, age(clock_timestamp(), query_start) AS duration
                    FROM pg_locks l
                    JOIN pg_stat_activity a ON l.pid = a.pid
                    WHERE a.pid <> pg_backend_pid()
                      AND a.state <> 'idle';
                    """
                )
            )
            rows = res.mappings().all()
            if rows:
                _log.warning("Startup DB Locks detected (%d active): %s", len(rows), [dict(r) for r in rows])
            else:
                _log.info("Startup DB Locks check: No active non-idle locks detected.")
        eng.dispose()
    except Exception:
        _log.info("DB lock check skipped: insufficient privileges or unsupported DB view.")


def _get_url_host(url_str: str) -> str:
    if not url_str:
        return "(none)"
    try:
        from urllib.parse import urlparse
        return urlparse(url_str).hostname or "(unknown)"
    except Exception:
        return "(invalid)"


def _run_alembic_upgrade():
    _log.info("Startup: Beginning Alembic database migrations to head...")
    db_url = settings.AURORA_DATABASE_URL or settings.DATABASE_URL or settings.SUPABASE_DATABASE_URL
    _log.info(
        "Startup: Migration target DB host: %s (AURORA_DATABASE_URL set: %s, DATABASE_URL set: %s)",
        _get_url_host(db_url),
        bool(settings.AURORA_DATABASE_URL),
        bool(settings.DATABASE_URL),
    )
    if db_url:
        _log_db_locks(db_url)

    try:
        res = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            timeout=180,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        if res.stdout:
            _log.info("Alembic stdout: %s", res.stdout.strip())
        if res.stderr:
            _log.error("Alembic stderr: %s", res.stderr.strip())

        if res.returncode != 0:
            _log.error("Startup ERROR: Alembic process returned exit code %d!", res.returncode)
        else:
            _log.info("Startup: Alembic database migration to head completed successfully.")

        from app.aurora import is_aurora_enabled, normalize_database_url
        if db_url and not is_aurora_enabled():
            import sqlalchemy as sa
            eng = sa.create_engine(normalize_database_url(db_url))
            with eng.connect() as conn:
                conn.execute(sa.text("NOTIFY pgrst, 'reload schema';"))
                conn.commit()
            eng.dispose()
            _log.info("Startup: PostgREST schema reload notified successfully.")
    except subprocess.TimeoutExpired as e:
        _log.error(
            "Startup ERROR: Alembic subprocess timed out after 180s!\nCaptured stdout:\n%s\nCaptured stderr:\n%s",
            e.stdout or "(none)",
            e.stderr or "(none)",
        )
    except Exception as e:
        _log.exception("Startup WARNING: Alembic migration / schema reload failed: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _log.info("Startup: Beginning application startup sequence...")

    # 1. Verify database connection with strict 10s timeout
    try:
        await asyncio.wait_for(
            asyncio.to_thread(_verify_database_connection),
            timeout=DATABASE_CHECK_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        _log.error("Startup ERROR: Database connection check timed out after 10s!")
    except Exception as e:
        _log.exception("Startup WARNING: Database connection check failed: %s", e)

    # 2. Run Alembic migrations as a subprocess with true OS process termination on timeout
    try:
        await asyncio.to_thread(_run_alembic_upgrade)
    except Exception as e:
        _log.exception("Startup WARNING: Alembic database migration failed: %s", e)

    # 3. Spawn background workers
    _log.info("Startup: Spawning background stuck_job_detector worker...")
    task = asyncio.create_task(stuck_job_detector())
    _log.info("Startup: Application startup complete. Server ready to receive requests.")
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    _log.info("Shutdown: Application shutdown complete.")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    lifespan=lifespan,
    redirect_slashes=False,
    title="ReconDesk API",
    description="B2B SaaS reconciliation platform API",
    version=settings.APP_VERSION,
    docs_url="/docs" if settings.APP_ENV != "production" else None,
    redoc_url="/redoc" if settings.APP_ENV != "production" else None,
)

# ── Rate limiting ─────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(CorrelationIdMiddleware)

# ── CORS ──────────────────────────────────────────────────────────────────────
_EXTRA_CORS_ORIGINS = (
    "https://recondesk.in",
    "https://www.recondesk.in",
)


def _cors_allow_origins() -> list[str]:
    """All env-configured origins plus fixed production frontends (deduplicated)."""
    merged: list[str] = []
    seen: set[str] = set()
    for origin in (*settings.allowed_origins_list, *_EXTRA_CORS_ORIGINS):
        if origin and origin not in seen:
            seen.add(origin)
            merged.append(origin)
    return merged


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        return await http_exception_handler(request, exc)
    _log.exception("Unhandled %s %s", request.method, request.url.path)
    if settings.SENTRY_DSN:
        sentry_sdk.capture_exception(exc)

    msg = str(exc) or exc.__class__.__name__
    if hasattr(exc, "message") and getattr(exc, "message"):
        msg = str(getattr(exc, "message"))
    elif hasattr(exc, "details") and getattr(exc, "details"):
        msg = str(getattr(exc, "details"))

    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {msg}"},
    )

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(cognito_auth_router, prefix="/api/v1/auth", tags=["Cognito Auth"])
app.include_router(auth.router, prefix="/auth", tags=["Auth (Direct)"])
app.include_router(auth.router, prefix="/api/auth", tags=["Auth (API)"])
app.include_router(cognito_auth_router, prefix="/auth", tags=["Cognito Auth (Direct)"])
app.include_router(cognito_auth_router, prefix="/api/auth", tags=["Cognito Auth (API)"])
app.include_router(auth.webhook_router, prefix="/api/auth", tags=["Auth Webhook"])
app.include_router(auth.test_router, prefix="/api/test", tags=["Test"])
app.include_router(reconciliation.router, prefix="/api/v1/reconciliation", tags=["Reconciliation"])
app.include_router(
    reconciliation.start_router,
    prefix="/api/reconciliation",
    tags=["Reconciliation Run"],
)
app.include_router(
    reconciliation_api.router,
    prefix="/api/reconciliation",
    tags=["Reconciliation API"],
)
app.include_router(
    reconciliation_api.reconcile_runs_router,
    prefix="/api/reconcile",
    tags=["Reconcile Runs"],
)
app.include_router(
    reconciliation_api.reconcile_runs_router,
    prefix="/api/v1/reconcile",
    tags=["Reconcile Runs"],
)
app.include_router(
    ims_actions_router,
    prefix="/api/reconcile",
    tags=["IMS Actions"],
)
app.include_router(
    ims_actions_router,
    prefix="/api/v1/reconcile",
    tags=["IMS Actions"],
)
app.include_router(
    export_router.router,
    prefix="/api/export",
    tags=["Advanced Export"],
)
app.include_router(notes.router, prefix="/api/notes", tags=["Notes"])
app.include_router(clients_router, prefix="/api/clients", tags=["Clients"])
app.include_router(clients_router, prefix="/api/v1/clients", tags=["Clients v1"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"])
app.include_router(
    gstr2b_autofetch_router,
    prefix="/api/clients",
    tags=["GSTR-2B Autofetch"],
)
app.include_router(
    gstr2b_autofetch_router,
    prefix="/api/v1/clients",
    tags=["GSTR-2B Autofetch"],
)
app.include_router(
    gst_fetch_router,
    prefix="/api/fetch",
    tags=["GST Fetch"],
)
app.include_router(gstin_router, prefix="/api/gstin", tags=["GSTIN"])
app.include_router(team_router, prefix="/api/team", tags=["Team"])
app.include_router(users_router.router, prefix="/api/users", tags=["Users"])
app.include_router(
    intelligence.router,
    prefix="/api/intelligence",
    tags=["Intelligence"],
)
app.include_router(
    vendors.router,
    prefix="/api/vendors",
    tags=["Vendors"],
)
app.include_router(
    vendor_followup_router,
    prefix="/api/vendors/followup",
    tags=["Vendor Follow-up"],
)
app.include_router(
    vendor_public_router,
    prefix="/api/public/v",
    tags=["Vendor Action Portal"],
)
app.include_router(
    vendor_public_router,
    prefix="/v",
    tags=["Vendor Action Portal"],
)
app.include_router(upload.router, prefix="/api/v1/upload", tags=["Upload"])
app.include_router(upload.public_router, prefix="/upload", tags=["Upload"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["Reports"])
app.include_router(rules_router, prefix="/api/rules", tags=["rules"])
app.include_router(billing.router, prefix="/api/v1/billing", tags=["Billing"])
app.include_router(
    billing_masters_router.router,
    prefix="/api/billing/masters",
    tags=["E-Invoicing Masters"],
)
app.include_router(
    billing_masters_router.router,
    prefix="/api/einvoicing/masters",
    tags=["E-Invoicing Masters"],
)
app.include_router(
    billing_invoices_router.router,
    prefix="/api/billing/invoices",
    tags=["E-Invoicing Invoices"],
)
app.include_router(
    billing_invoices_router.router,
    prefix="/api/einvoicing/invoices",
    tags=["E-Invoicing Invoices"],
)
app.include_router(
    billing_irp_router.router,
    prefix="/api/billing/invoices",
    tags=["E-Invoicing IRP"],
)
app.include_router(
    billing_irp_router.router,
    prefix="/api/einvoicing/invoices",
    tags=["E-Invoicing IRP"],
)
app.include_router(
    billing_cdn_router.router,
    prefix="/api/billing/credit-debit-notes",
    tags=["E-Invoicing CDNR"],
)
app.include_router(
    billing_cdn_router.router,
    prefix="/api/einvoicing/credit-debit-notes",
    tags=["E-Invoicing CDNR"],
)
app.include_router(
    billing_ewaybill_router.router,
    prefix="/api/billing/ewaybill",
    tags=["E-Way Bill Suite"],
)
app.include_router(
    billing_ewaybill_router.router,
    prefix="/api/ewaybill",
    tags=["E-Way Bill Suite"],
)
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["Notifications"])
app.include_router(
    payments_routes.payments_router,
    prefix="/api/payments",
    tags=["Payments"],
)
app.include_router(
    payments_routes.billing_status_router,
    prefix="/api/billing",
    tags=["Billing Status"],
)
app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["Webhooks"])
app.include_router(import_router.router, prefix="/api/import", tags=["Import"])
app.include_router(pr_upload.router, prefix="/api/pr-upload", tags=["PR Upload"])
app.include_router(
    register_upload.router, prefix="/api/register-upload", tags=["Register Upload"]
)
app.include_router(
    reconciliation_import_wizard.router,
    prefix="/api",
    tags=["Import Wizard"],
)
app.include_router(
    multi_period_wizard_router,
    prefix="/api/multi-period",
    tags=["Multi-Period Wizard"],
)
app.include_router(
    multi_period_wizard_router,
    prefix="/api/v1/multi-period",
    tags=["Multi-Period Wizard"],
)
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(audit_logs.router, prefix="/api/audit-logs", tags=["Audit Logs"])
app.include_router(
    audit_observations.router,
    prefix="/api/audit-observations",
    tags=["Audit Observations"],
)
app.include_router(
    manage_data.router,
    prefix="/api/v1/manage-data",
    tags=["Manage Data"],
)
app.include_router(
    gstr1_reconcile_router,
    prefix="/api/gstr1-reconcile",
    tags=["GSTR-1 Reconcile"],
)
app.include_router(
    einvoice_recon_router,
    prefix="/api/einvoice-recon",
    tags=["E-Invoice Recon"],
)
app.include_router(
    work_items_router.router,
    prefix="/api",
    tags=["ITC Work Items"],
)
app.include_router(
    filing_router,
    prefix="/api/filing",
    tags=["GST Filing"],
)
app.include_router(
    tally_sync_router,
    prefix="/api/tally-sync",
    tags=["Tally Bridge"],
)
app.include_router(
    gstr9_router,
    prefix="/api/gstr9",
    tags=["GSTR-9 & GSTR-9C"],
)
app.include_router(
    gstr9_router,
    prefix="/api/gstr9c",
    tags=["GSTR-9 & GSTR-9C"],
)
app.include_router(
    gstr4_router,
    prefix="/api/gstr4",
    tags=["GSTR-4 Composition Annual Return"],
)
app.include_router(
    gstr4_router,
    prefix="/api/v1/gstr4",
    tags=["GSTR-4 Composition Annual Return"],
)
app.include_router(
    gstr2a_delta_router,
    prefix="/api/gstr2a-delta",
    tags=["GSTR-2A Delta"],
)
app.include_router(
    notices_router,
    prefix="/api/notices",
    tags=["Notices"],
)
app.include_router(
    practice_router,
    prefix="/api/practice",
    tags=["Practice Management"],
)



# ── Core endpoints ────────────────────────────────────────────────────────────
_HEALTH_PROBE_TIMEOUT_S = 2.0


@app.get("/health", tags=["System"])
async def health_check():
    """Liveness/readiness probe — must stay fast even when deps are slow.

    Supabase/R2 checks are hard-capped so a hung dependency cannot wedge
    Railway health checks into 499 / multi-minute stalls.
    """

    async def _timed_state(label: str, factory) -> str:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(factory), timeout=_HEALTH_PROBE_TIMEOUT_S
            )
            return "ok"
        except asyncio.TimeoutError:
            _log.warning("health probe %s timed out after %.1fs", label, _HEALTH_PROBE_TIMEOUT_S)
            return "error"
        except Exception:
            _log.warning("health probe %s failed", label, exc_info=True)
            return "error"

    def _ping_supabase() -> None:
        get_supabase().table("user_profiles").select("id").limit(1).execute()

    def _ping_r2_soft() -> None:
        from botocore.exceptions import ClientError
        from app.utils.storage import _get_client

        try:
            _get_client().head_object(
                Bucket=settings.R2_BUCKET_NAME, Key=_HEALTH_PROBE_KEY
            )
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in ("404", "NoSuchKey", "NotFound"):
                return
            raise

    supabase_state, r2_state = await asyncio.gather(
        _timed_state("supabase", _ping_supabase),
        _timed_state("r2", _ping_r2_soft),
    )

    env = "production" if (settings.APP_ENV or "").lower() == "production" else "development"
    now = datetime.now(timezone.utc)
    uptime_seconds = int((now - START_TIME).total_seconds())
    overall = "ok" if supabase_state == "ok" and r2_state == "ok" else "degraded"

    return {
        "status": overall,
        "version": settings.APP_VERSION,
        "git_commit_sha": os.environ.get("RAILWAY_GIT_COMMIT_SHA", os.environ.get("COMMIT_SHA", "unknown")),
        "uptime_seconds": uptime_seconds,
        "supabase": supabase_state,
        "r2": r2_state,
        "environment": env,
        "timestamp": now.isoformat(),
    }
