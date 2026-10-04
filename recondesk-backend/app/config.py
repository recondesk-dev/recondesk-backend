from functools import lru_cache
from typing import List, Optional

import httpx
from pydantic import AliasChoices, Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # App
    APP_ENV: str = Field(
        default="development",
        description="Use 'production' in live deployments.",
    )
    APP_VERSION: str = "1.0.1"
    SECRET_KEY: str = "dev-local-secret-key-32b-minimum!!!!"
    ALLOWED_ORIGINS: str = "http://localhost:3000"
    FRONTEND_URL: str = ""

    # Secrets (load from environment; never log)
    JWT_SECRET: str = ""
    DATABASE_URL: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = Field(
        default="",
        validation_alias=AliasChoices("R2_SECRET_ACCESS_KEY", "R2_SECRET_KEY"),
    )
    REDIS_URL: str = "redis://localhost:6379/0"

    # AWS Aurora / PostgreSQL (Migration layer)
    AURORA_DATABASE_URL: str = Field(
        default="",
        validation_alias=AliasChoices("AURORA_DATABASE_URL", "AURORA_DB_URL"),
        description="Explicit AWS Aurora connection string; required for Aurora operations (does not fallback to DATABASE_URL).",
    )
    AURORA_DB_ENABLED: bool = Field(
        default=True,
        description="Primary database flag: Aurora PostgreSQL is the sole production database.",
    )
    AURORA_SSL_MODE: Optional[str] = Field(
        default=None,
        description="SSL mode for Aurora connections (e.g. 'require', 'verify-ca', 'verify-full', 'disable').",
    )
    AURORA_SSL_CERT_PATH: Optional[str] = Field(
        default=None,
        description="Path to CA certificate bundle (e.g. global-bundle.pem) when using verify-ca or verify-full.",
    )
    AURORA_POOL_SIZE: int = Field(
        default=2,
        description="SQLAlchemy connection pool size for Aurora (conservative development default).",
    )
    AURORA_MAX_OVERFLOW: int = Field(
        default=0,
        description="SQLAlchemy connection pool max overflow for Aurora (conservative development default).",
    )
    AURORA_POOL_RECYCLE_SECONDS: int = Field(
        default=1800,
        description="SQLAlchemy pool recycle timeout in seconds to handle Aurora DNS failovers.",
    )
    AURORA_POOL_TIMEOUT_SECONDS: int = Field(
        default=30,
        description="SQLAlchemy pool checkout timeout in seconds.",
    )
    AURORA_CONNECT_TIMEOUT_SECONDS: int = Field(
        default=10,
        description="Psycopg2 connection establishment timeout in seconds.",
    )

    # Amazon Cognito (Migration layer)
    COGNITO_AUTH_ENABLED: bool = Field(
        default=False,
        description="Feature flag for Amazon Cognito authentication layer.",
    )
    COGNITO_REGION: str = Field(
        default="ap-south-1",
        description="AWS region for Cognito User Pool.",
    )
    COGNITO_USER_POOL_ID: str = Field(
        default="ap-south-1_nvlPYMvFh",
        description="Cognito User Pool ID.",
    )
    COGNITO_CLIENT_ID: str = Field(
        default="2qui5lp7if0g4lftbrag7o6sce",
        description="Cognito App Client ID.",
    )
    COGNITO_CLIENT_SECRET: str = Field(
        default="",
        description="Cognito App Client Secret (Server-side only).",
    )
    COGNITO_REDIRECT_URI: str = Field(
        default="http://localhost:3000/api/auth/cognito/callback",
        description="Cognito OAuth Callback URL.",
    )

    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_DATABASE_URL: str = Field(
        default="",
        validation_alias=AliasChoices("SUPABASE_DATABASE_URL", "SUPABASE_DB_URL"),
    )

    # Storage Configuration (AWS S3 primary with R2 migration fallback)
    STORAGE_BACKEND: str = Field(
        default="s3",
        validation_alias=AliasChoices("STORAGE_BACKEND", "RECONDESK_STORAGE_BACKEND"),
        description="Active storage backend: 's3' (native AWS S3) or 'r2' (legacy Cloudflare R2).",
    )
    AWS_REGION: str = Field(
        default="ap-south-1",
        validation_alias=AliasChoices("AWS_REGION", "AWS_DEFAULT_REGION", "COGNITO_REGION"),
    )
    AWS_S3_BUCKET_NAME: str = Field(
        default="recondesk-storage-991216470563",
        validation_alias=AliasChoices("AWS_S3_BUCKET_NAME", "S3_BUCKET_NAME", "STORAGE_BUCKET_NAME"),
    )
    AWS_S3_ENDPOINT_URL: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("AWS_S3_ENDPOINT_URL", "S3_ENDPOINT_URL"),
        description="Custom S3 endpoint URL (e.g. for testing / LocalStack).",
    )
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""

    # Cloudflare R2 (Retained for dual-read fallback and migration verification)
    R2_ENDPOINT_URL: str = ""
    R2_ACCOUNT_ID: str = ""
    R2_BUCKET_NAME: str = "recondesk-uploads"
    R2_PUBLIC_URL: str = ""

    # Celery / Redis — set IMPORT_USE_CELERY=true when a Celery worker is running,
    # false to force synchronous in-process imports (no worker needed).
    # Unset (None) → falls back to APP_ENV heuristic (production = True).
    IMPORT_USE_CELERY: Optional[bool] = None
    IMPORT_SANITY_STRICT: bool = False

    # JWT
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_AUDIENCE: str = ""
    JWT_ISSUER: str = ""

    # File uploads
    MAX_FILE_SIZE_MB: int = 10

    # Razorpay
    RAZORPAY_KEY_ID: str = ""

    # Amazon SES (SMTP) & Email
    SES_SMTP_HOST: str = "email-smtp.ap-south-1.amazonaws.com"
    SES_SMTP_PORT: int = 587
    SES_SMTP_USER: str = ""
    SES_SMTP_PASS: str = ""
    EMAIL_FROM: str = "ReconDesk <noreply@recondesk.in>"

    # Legacy Resend (optional fallback)
    RESEND_API_KEY: str = ""

    # Sentry / admin
    SENTRY_DSN: Optional[str] = None
    ADMIN_USER_ID: Optional[str] = None

    # Sandbox.co.in GST API
    SANDBOX_API_KEY: str = ""
    SANDBOX_API_SECRET: str = ""  # Used only for /authenticate (public GSTIN verification)
    SANDBOX_BASE_URL: str = "https://api.sandbox.co.in"
    SANDBOX_API_VERSION: str = "1.0.0"

    # GSTR-3B filing (Save → Offset → File). Offset moves real ledger money.
    # Unset → enabled outside production, disabled in production.
    # Explicit true/false always wins.
    GSTR3B_FILING_ENABLED: Optional[bool] = None

    # Showcase onboarding
    SHOWCASE_ONBOARDING_ENABLED: Optional[bool] = None

    # Seller Invoicing / B2B GST compliance
    SELLER_LEGAL_NAME: str = "ReconDesk Technologies"
    SELLER_TRADE_NAME: str = "ReconDesk"
    SELLER_GSTIN: str = ""
    SELLER_ADDRESS: str = "Hadapsar, Pune, Maharashtra 411028, India"
    SELLER_STATE: str = "Maharashtra"
    SELLER_STATE_CODE: str = "27"
    SELLER_SAC_CODE: str = "998314"

    @computed_field  # type: ignore[misc]
    @property
    def showcase_onboarding_enabled(self) -> bool:
        """Whether post-signup /welcome feature showcase is enabled.

        Unset → enabled outside production, enabled in production unless explicitly set to False.
        Override with ``SHOWCASE_ONBOARDING_ENABLED=false|true``.
        """
        if self.SHOWCASE_ONBOARDING_ENABLED is not None:
            return bool(self.SHOWCASE_ONBOARDING_ENABLED)
        return True

    @computed_field  # type: ignore[misc]
    @property
    def ENV(self) -> str:  # noqa: N802
        return self.APP_ENV

    @computed_field  # type: ignore[misc]
    @property
    def SUPABASE_SERVICE_KEY(self) -> str:  # noqa: N802
        return self.SUPABASE_SERVICE_ROLE_KEY

    @computed_field  # type: ignore[misc]
    @property
    def R2_ACCESS_KEY(self) -> str:  # noqa: N802
        return self.R2_ACCESS_KEY_ID

    @computed_field  # type: ignore[misc]
    @property
    def R2_BUCKET(self) -> str:  # noqa: N802
        return self.R2_BUCKET_NAME

    @computed_field  # type: ignore[misc]
    @property
    def S3_BUCKET(self) -> str:  # noqa: N802
        return self.AWS_S3_BUCKET_NAME or self.R2_BUCKET_NAME

    @computed_field  # type: ignore[misc]
    @property
    def RAZORPAY_KEY(self) -> str:  # noqa: N802
        return self.RAZORPAY_KEY_ID

    @computed_field  # type: ignore[misc]
    @property
    def RAZORPAY_SECRET(self) -> str:  # noqa: N802
        return self.RAZORPAY_KEY_SECRET

    @property
    def allowed_origins_list(self) -> List[str]:
        base = [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]
        fe = (self.FRONTEND_URL or "").strip()
        if fe and fe not in base:
            base = [fe] + [x for x in base if x != fe]
        if "http://localhost:3000" not in base:
            base.append("http://localhost:3000")
        return base

    @property
    def cors_origins(self) -> List[str]:
        out: List[str] = []
        for u in ((self.FRONTEND_URL or "").strip(), "http://localhost:3000"):
            if u and u not in out:
                out.append(u)
        return out

    @property
    def jwt_signing_key(self) -> str:
        return (self.JWT_SECRET or self.SECRET_KEY or "").strip()

    @property
    def jwt_verify_aud_iss(self) -> bool:
        return bool((self.JWT_AUDIENCE or "").strip() and (self.JWT_ISSUER or "").strip())

    @property
    def import_use_celery(self) -> bool:
        """Queue imports to Celery when explicitly enabled or (by default) in production.

        IMPORT_USE_CELERY=true  → always use Celery (worker must be running)
        IMPORT_USE_CELERY=false → always run synchronously (no worker needed)
        unset                   → use Celery only when APP_ENV=production
        """
        if self.IMPORT_USE_CELERY is not None:
            return bool(self.IMPORT_USE_CELERY)  # explicit override always wins
        return (self.APP_ENV or "").lower() == "production"

    @property
    def gstr3b_filing_enabled(self) -> bool:
        """Whether GSTR-3B filing APIs/UI may run.

        Default: off in production (Offset is irreversible), on in local/dev.
        Override with ``GSTR3B_FILING_ENABLED=true|false``.
        """
        if self.GSTR3B_FILING_ENABLED is not None:
            return bool(self.GSTR3B_FILING_ENABLED)
        return (self.APP_ENV or "").lower() != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_production_secrets() -> None:
    """Call on application startup."""
    s = get_settings()
    is_prod = (s.APP_ENV or "").lower() == "production"
    if len(s.jwt_signing_key) < 32:
        raise RuntimeError("JWT secret must be at least 32 characters")
    if not is_prod:
        return
    required: dict[str, str] = {
        "JWT_SECRET or SECRET_KEY": s.jwt_signing_key,
        "DATABASE_URL": s.DATABASE_URL,
        "RAZORPAY_KEY_SECRET": s.RAZORPAY_KEY_SECRET,
        "REDIS_URL": s.REDIS_URL,
        "SUPABASE_URL": s.SUPABASE_URL,
        "SUPABASE_SERVICE_ROLE_KEY": s.SUPABASE_SERVICE_ROLE_KEY,
    }
    if (s.STORAGE_BACKEND or "").lower() == "r2":
        required["R2_SECRET_ACCESS_KEY"] = s.R2_SECRET_ACCESS_KEY
    else:
        required["AWS_S3_BUCKET_NAME"] = s.AWS_S3_BUCKET_NAME
    missing = [k for k, v in required.items() if not (str(v or "").strip())]
    if missing:
        raise RuntimeError(
            "Production configuration incomplete; missing: " + ", ".join(missing)
        )


def get_r2_s3_endpoint_url() -> str:
    """R2 S3 API URL: ``R2_ENDPOINT_URL`` if set, else ``https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com``."""
    s = get_settings()
    ep = (s.R2_ENDPOINT_URL or "").strip()
    if ep:
        return ep.rstrip("/")
    acc = (s.R2_ACCOUNT_ID or "").strip()
    if acc:
        return f"https://{acc}.r2.cloudflarestorage.com"
    raise ValueError(
        "R2 endpoint not configured: set R2_ENDPOINT_URL or R2_ACCOUNT_ID in the environment"
    )


def httpx_timeout_client() -> httpx.Client:
    return httpx.Client(timeout=120.0)


settings: Settings = get_settings()
