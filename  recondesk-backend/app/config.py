from functools import lru_cache
from typing import List

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # App
    APP_ENV: str = "development"
    APP_VERSION: str = "1.0"
    SECRET_KEY: str = "change-me"
    ALLOWED_ORIGINS: str = "http://localhost:3000"
    FRONTEND_URL: str = ""

    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # Cloudflare R2 (S3-compatible; prefer R2_ENDPOINT_URL when set)
    R2_ENDPOINT_URL: str = ""
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "recondesk-uploads"
    R2_PUBLIC_URL: str = ""

    # Celery / Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    # When False (default), import jobs run in the API process via Celery ``.apply()`` so
    # progress updates without a separate worker. Set True + run ``celery worker`` to offload.
    IMPORT_USE_CELERY: bool = False
    # When True, any sanity check with severity=error fails the run. When False, failures are
    # still stored in sanity_report but the import continues (recommended for messy GSTR-2B data).
    IMPORT_SANITY_STRICT: bool = False

    # JWT
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Razorpay
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""

    # Resend
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "no-reply@recondesk.com"

    # Sentry
    SENTRY_DSN: str = ""

    # ── Computed aliases (alternate env-var name spellings) ───────────────────

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SUPABASE_SERVICE_KEY(self) -> str:
        return self.SUPABASE_SERVICE_ROLE_KEY

    @computed_field  # type: ignore[prop-decorator]
    @property
    def R2_ACCESS_KEY(self) -> str:
        return self.R2_ACCESS_KEY_ID

    @computed_field  # type: ignore[prop-decorator]
    @property
    def R2_SECRET_KEY(self) -> str:
        return self.R2_SECRET_ACCESS_KEY

    @computed_field  # type: ignore[prop-decorator]
    @property
    def R2_BUCKET(self) -> str:
        return self.R2_BUCKET_NAME

    @computed_field  # type: ignore[prop-decorator]
    @property
    def RAZORPAY_KEY(self) -> str:
        return self.RAZORPAY_KEY_ID

    @computed_field  # type: ignore[prop-decorator]
    @property
    def RAZORPAY_SECRET(self) -> str:
        return self.RAZORPAY_KEY_SECRET

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


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


settings: Settings = get_settings()
