import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.routers import (
    auth,
    intelligence,
    reconciliation,
    reconciliation_api,
    upload,
    reports,
    billing,
    webhooks,
    import_router,
    notes,
)
from app.routers.clients import clients_router
from app.utils.rate_limit import limiter

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
        send_default_pii=False,
    )

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
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
app.include_router(notes.router, prefix="/api/notes", tags=["Notes"])
app.include_router(clients_router, prefix="/api/clients", tags=["Clients"])
app.include_router(
    intelligence.router,
    prefix="/api/intelligence",
    tags=["Intelligence"],
)
app.include_router(upload.router, prefix="/api/v1/upload", tags=["Upload"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["Reports"])
app.include_router(billing.router, prefix="/api/v1/billing", tags=["Billing"])
app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["Webhooks"])
app.include_router(import_router.router, prefix="/api/import", tags=["Import"])


# ── Core endpoints ────────────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "version": settings.APP_VERSION}
