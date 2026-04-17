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

    # Cloudflare R2
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "recondesk-uploads"
    R2_PUBLIC_URL: str = ""

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

    # Import pipeline (Day 11) — off by default so existing deployments behave unchanged
    # until DATABASE_URL migration, REDIS_URL, and Celery worker are ready.
    IMPORT_PIPELINE_ENABLED: bool = False

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


settings: Settings = get_settings()
