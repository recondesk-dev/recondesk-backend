"""Tests for Feature Showcase feature flag and clean zero-demo data behavior."""

from __future__ import annotations

import pytest
from app.config import Settings, get_settings


def _settings(**kwargs) -> Settings:
    defaults = {"SECRET_KEY": "a" * 32, "APP_ENV": "development"}
    defaults.update(kwargs)
    return Settings(**defaults)


def test_showcase_feature_flag_defaults(monkeypatch):
    """Test SHOWCASE_ONBOARDING_ENABLED feature flag config logic."""
    monkeypatch.delenv("SHOWCASE_ONBOARDING_ENABLED", raising=False)
    get_settings.cache_clear()

    # Dev/Local environment -> True by default
    s_dev = _settings(APP_ENV="development", SHOWCASE_ONBOARDING_ENABLED=None)
    assert s_dev.showcase_onboarding_enabled is True

    # Production environment -> True by default
    s_prod = _settings(APP_ENV="production", SHOWCASE_ONBOARDING_ENABLED=None)
    assert s_prod.showcase_onboarding_enabled is True

    # Explicit override -> False
    s_override_false = _settings(APP_ENV="production", SHOWCASE_ONBOARDING_ENABLED=False)
    assert s_override_false.showcase_onboarding_enabled is False

    # Explicit override -> True
    s_override_true = _settings(APP_ENV="production", SHOWCASE_ONBOARDING_ENABLED=True)
    assert s_override_true.showcase_onboarding_enabled is True
