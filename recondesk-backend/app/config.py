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
    APP_VERSION: str = "1.0"
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

    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # Cloudflare R2
    R2_ENDPOINT_URL: str = ""
    R2_ACCOUNT_ID: str = ""
    R2_BUCKET_NAME: str = "recondesk-uploads"
    R2_PUBLIC_URL: str = ""

    # Celery / Redis
    IMPORT_USE_CELERY: bool = False
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

    # Resend
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "ReconDesk <onboarding@resend.dev>"

    # Sentry / admin
    SENTRY_DSN: Optional[str] = None
    ADMIN_USER_ID: Optional[str] = None

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
        "R2_SECRET_ACCESS_KEY": s.R2_SECRET_ACCESS_KEY,
        "REDIS_URL": s.REDIS_URL,
        "SUPABASE_URL": s.SUPABASE_URL,
        "SUPABASE_SERVICE_ROLE_KEY": s.SUPABASE_SERVICE_ROLE_KEY,
    }
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
    return httpx.Client(timeout=60.0)


settings: Settings = get_settings()
