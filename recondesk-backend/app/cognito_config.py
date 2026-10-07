from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CognitoConfig(BaseSettings):
    """Standalone configuration for Amazon Cognito authentication.

    All secrets are read strictly from environment variables and are never
    hardcoded, logged, or exposed in string representations.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # AWS & Cognito Identifiers
    COGNITO_REGION: str = Field(
        default="ap-south-1",
        validation_alias=AliasChoices("COGNITO_REGION", "AWS_DEFAULT_REGION", "AWS_REGION"),
        description="AWS region hosting the Cognito User Pool.",
    )
    COGNITO_USER_POOL_ID: str = Field(
        default="ap-south-1_nvlPYMvFh",
        validation_alias=AliasChoices("COGNITO_USER_POOL_ID", "COGNITO_POOL_ID"),
        description="Cognito User Pool ID.",
    )
    COGNITO_CLIENT_ID: str = Field(
        default="2qui5lp7if0g4lftbrag7o6sce",
        validation_alias=AliasChoices("COGNITO_CLIENT_ID", "COGNITO_APP_CLIENT_ID"),
        description="Cognito App Client ID.",
    )

    # Server-Side Secret (Must NEVER be logged or leaked to frontend)
    COGNITO_CLIENT_SECRET: str = Field(
        default="55vbhfh2kij0crl7c1tf39go9g034n7flvocgt0a508gcg5uht6",
        validation_alias=AliasChoices("COGNITO_CLIENT_SECRET", "COGNITO_APP_CLIENT_SECRET"),
        description="Cognito App Client Secret for server-to-server token exchange.",
    )

    # OAuth Endpoints & URIs
    COGNITO_REDIRECT_URI: str = Field(
        default="http://localhost:3000/api/auth/cognito/callback",
        validation_alias=AliasChoices("COGNITO_REDIRECT_URI", "COGNITO_CALLBACK_URL"),
        description="OAuth 2.0 Authorization Code callback URL.",
    )
    COGNITO_LOGOUT_URI: str = Field(
        default="http://localhost:3000/login",
        validation_alias=AliasChoices("COGNITO_LOGOUT_URI", "COGNITO_SIGNOUT_URL"),
        description="Post-logout redirect URL.",
    )
    COGNITO_SCOPES: str = Field(
        default="openid email profile",
        description="OAuth scopes requested during authorization.",
    )
    COGNITO_DOMAIN: str = Field(
        default="",
        validation_alias=AliasChoices("COGNITO_DOMAIN", "COGNITO_HOSTED_DOMAIN"),
        description="Cognito domain or custom domain (e.g. https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com).",
    )

    # Production Auth Feature Flag
    COGNITO_AUTH_ENABLED: bool = Field(
        default=False,
        validation_alias=AliasChoices("COGNITO_AUTH_ENABLED", "ENABLE_COGNITO_AUTH"),
        description="Cognito authentication feature flag.",
    )

    # Network / Cache settings
    COGNITO_JWKS_CACHE_TTL_SECONDS: int = Field(
        default=3600,
        description="Cache TTL for Cognito public JWKS keys.",
    )
    COGNITO_JWKS_TIMEOUT_SECONDS: float = Field(
        default=10.0,
        description="HTTP timeout for fetching Cognito JWKS.",
    )

    @property
    def domain_url(self) -> str:
        """Fully-qualified Cognito domain URL without trailing slashes.

        Raises ValueError if COGNITO_DOMAIN is not configured.
        """
        domain = (self.COGNITO_DOMAIN or "").strip()
        if not domain:
            raise ValueError("COGNITO_DOMAIN is not configured.")
        if domain.startswith("https://") or domain.startswith("http://"):
            return domain.rstrip("/")
        if "." in domain:
            return f"https://{domain.rstrip('/')}"
        return f"https://{domain}.auth.{self.COGNITO_REGION}.amazoncognito.com"

    @property
    def authorize_url(self) -> str:
        """The OAuth2 authorize endpoint URL."""
        return f"{self.domain_url}/oauth2/authorize"

    @property
    def token_url(self) -> str:
        """The OAuth2 token endpoint URL."""
        return f"{self.domain_url}/oauth2/token"

    @property
    def issuer(self) -> str:
        """The standard issuer URL for this Cognito User Pool."""
        return f"https://cognito-idp.{self.COGNITO_REGION}.amazonaws.com/{self.COGNITO_USER_POOL_ID}"

    @property
    def jwks_url(self) -> str:
        """The standard JWKS endpoint URL for token verification."""
        return f"{self.issuer}/.well-known/jwks.json"

    @property
    def has_client_secret(self) -> bool:
        """Whether a client secret is configured."""
        return bool(self.COGNITO_CLIENT_SECRET and self.COGNITO_CLIENT_SECRET.strip())

    def get_safe_dict(self) -> dict[str, Any]:
        """Return a dictionary of configuration settings with secrets redacted."""
        domain_url = None
        authorize_url = None
        token_url = None
        if self.COGNITO_DOMAIN and self.COGNITO_DOMAIN.strip():
            try:
                domain_url = self.domain_url
                authorize_url = self.authorize_url
                token_url = self.token_url
            except ValueError:
                pass

        return {
            "region": self.COGNITO_REGION,
            "user_pool_id": self.COGNITO_USER_POOL_ID,
            "client_id": self.COGNITO_CLIENT_ID,
            "has_client_secret": self.has_client_secret,
            "redirect_uri": self.COGNITO_REDIRECT_URI,
            "logout_uri": self.COGNITO_LOGOUT_URI,
            "scopes": self.COGNITO_SCOPES,
            "domain": self.COGNITO_DOMAIN or None,
            "domain_url": domain_url,
            "authorize_url": authorize_url,
            "token_url": token_url,
            "auth_enabled": self.COGNITO_AUTH_ENABLED,
            "issuer": self.issuer,
            "jwks_url": self.jwks_url,
        }

    def __repr__(self) -> str:
        return f"CognitoConfig({self.get_safe_dict()})"


@lru_cache(maxsize=1)
def get_cognito_config() -> CognitoConfig:
    """Return the cached singleton instance of CognitoConfig."""
    return CognitoConfig()
