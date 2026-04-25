import logging
import os
import sys
import traceback
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware


def get_real_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


redis_url = os.environ.get("REDIS_URL", None)

if redis_url:
    limiter = Limiter(key_func=get_real_ip, storage_uri=redis_url)
else:
    limiter = Limiter(key_func=get_real_ip)

from app.config import settings, validate_production_secrets
from app.routers import (
    auth,
    billing,
    import_router,
    intelligence,
    notes,
    reconciliation,
    reconciliation_api,
    reports,
    upload,
    webhooks,
)
from app.routers.clients import clients_router
from app.middleware.body_limits import BodySizeJsonDepthMiddleware, SecurityHeadersMiddleware
from app.utils.context import CorrelationIdMiddleware
from app.utils.secret_log_filter import SecretRedactFilter
from app.utils.errors import error_response

_log = logging.getLogger("recondesk.api")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    validate_production_secrets()
    root = logging.getLogger()
    if not any(isinstance(f, SecretRedactFilter) for f in root.filters):
        root.addFilter(SecretRedactFilter())
    yield


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
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
    _log.error("Unhandled error: %s", exc, exc_info=True)
    print(traceback.format_exc(), file=sys.stderr)
    return error_response(
        500, "An unexpected error occurred. Please try again."
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    hdrs = {k: v for k, v in dict(exc.headers or {}).items()}
    if exc.status_code == 401:
        d = exc.detail
        allowed_401 = {
            "Invalid email or password.",
            "Invalid or expired token",
        }
        if isinstance(d, str) and d in allowed_401:
            msg401 = d
        else:
            msg401 = "Authentication required"
        h401 = {k: v for k, v in hdrs.items() if k.lower() == "www-authenticate"}
        if "www-authenticate" not in {k.lower() for k in h401} and "WWW-Authenticate" not in h401:
            h401["WWW-Authenticate"] = "Bearer"
        return error_response(401, msg401, headers=h401 or None)
    if exc.status_code == 403:
        return error_response(403, "Access denied")
    if exc.status_code == 429:
        return error_response(
            429, "Too many requests. Please try again later."
        )
    detail = exc.detail
    if isinstance(detail, list):
        detail = "Invalid request"
    elif not isinstance(detail, str):
        detail = str(detail)
    return error_response(exc.status_code, detail, headers=hdrs or None)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError  # noqa: ARG001
) -> JSONResponse:
    errs = exc.errors()
    parts: list[str] = []
    for e in errs[:12]:
        loc = ".".join(str(x) for x in e.get("loc", ()))
        msg = e.get("msg", "invalid")
        parts.append(f"{loc}: {msg}" if loc else msg)
    reason = "; ".join(parts) if parts else "Invalid request"
    return error_response(400, reason)


async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:  # noqa: ARG001
    return error_response(
        429, "Too many requests. Please try again later."
    )


app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

# Outermost middleware is added last (request: CorrelationId -> CORS -> security -> body -> rate limit -> app)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(BodySizeJsonDepthMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_middleware(CorrelationIdMiddleware)

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


@app.get("/debug/headers", tags=["System"])
async def debug_headers(request: Request):
    return dict(request.headers)


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "version": settings.APP_VERSION}
