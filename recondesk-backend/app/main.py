import asyncio
import logging
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
from app.routers.filing import router as filing_router
from app.routers.tally_sync import router as tally_sync_router
from app.utils.rate_limit import limiter

_log = logging.getLogger(__name__)

START_TIME = datetime.now(timezone.utc)

# ── Sentry ────────────────────────────────────────────────────────────────────
if settings.SENTRY_DSN:
    from app.filing.log_safety import sentry_scrub_event

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
        # Scrub those keys from any captured request URL / exception text.
        before_send=sentry_scrub_event,
    )

_HEALTH_PROBE_KEY = "__recondesk/health_probe__"

_STUCK_STATUSES = ("MATCHING", "PROCESSING", "importing")


def _stuck_job_tick() -> None:
    supabase = get_supabase()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    cutoff_iso = cutoff.isoformat()
    try:
        stuck_runs = (
            supabase.table("reconciliation_run")
            .select("id, status, processing_started_at")
            .in_("status", list(_STUCK_STATUSES))
            .not_.is_("processing_started_at", "null")
            .lt("processing_started_at", cutoff_iso)
            .execute()
        )
    except Exception:
        _log.exception("stuck_job_detector: query failed")
        raise

    for run in stuck_runs.data or []:
        rid = run.get("id")
        if not rid:
            continue
        try:
            supabase.table("reconciliation_run").update(
                {
                    "status": "FAILED",
                    "status_message": "Processing timeout — please retry",
                }
            ).eq("id", rid).execute()
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(stuck_job_detector())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


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
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
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
app.include_router(upload.router, prefix="/api/v1/upload", tags=["Upload"])
app.include_router(upload.public_router, prefix="/upload", tags=["Upload"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["Reports"])
app.include_router(rules_router, prefix="/api/rules", tags=["rules"])
app.include_router(billing.router, prefix="/api/v1/billing", tags=["Billing"])
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
    tags=["GSTR-1 Reconciliation"],
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
        "uptime_seconds": uptime_seconds,
        "supabase": supabase_state,
        "r2": r2_state,
        "environment": env,
        "timestamp": now.isoformat(),
    }
