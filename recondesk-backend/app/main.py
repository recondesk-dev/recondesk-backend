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
from app.routers.gstin import router as gstin_router
from app.routers.team import router as team_router
from app.routers.rules import router as rules_router
from app.routers.gstr1_reconcile import router as gstr1_reconcile_router
from app.utils.rate_limit import limiter
from app.utils.storage import file_exists

_log = logging.getLogger(__name__)

START_TIME = datetime.now(timezone.utc)

# ── Sentry ────────────────────────────────────────────────────────────────────
if settings.SENTRY_DSN:
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
        # Rule 37 pre-deadline / overdue email scan (throttled inside the service).
        try:
            from app.services.rule37_alert_scan import run_rule37_alert_scan

            await run_rule37_alert_scan()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _log.exception("rule37_alert_scan failed")
            if settings.SENTRY_DSN:
                sentry_sdk.capture_exception(e)
        # Vendor compliance scorecard full rebuild (throttled to 24h inside service).
        try:
            from app.services.supplier_compliance_scorecard import (
                run_scorecard_daily_rebuild,
            )

            await run_scorecard_daily_rebuild()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _log.exception("supplier_compliance_scorecard rebuild failed")
            if settings.SENTRY_DSN:
                sentry_sdk.capture_exception(e)


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


# ── Core endpoints ────────────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health_check():
    supabase_state = "error"
    try:

        def _ping_supabase() -> None:
            get_supabase().table("user_profiles").select("id").limit(1).execute()

        await asyncio.to_thread(_ping_supabase)
        supabase_state = "ok"
    except Exception:
        pass

    r2_state = "error"
    try:
        await file_exists(_HEALTH_PROBE_KEY)
        r2_state = "ok"
    except Exception:
        pass

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
