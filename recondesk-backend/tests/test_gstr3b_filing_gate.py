"""GSTR-3B filing feature-flag gate (production off by default)."""

from __future__ import annotations

from fastapi import HTTPException

from app.config import Settings, get_settings
from app.routers.filing import require_gstr3b_filing_enabled


def _settings(**kwargs) -> Settings:
    # Ignore repo .env so unit tests are deterministic.
    return Settings(_env_file=None, **kwargs)


def test_gstr3b_enabled_outside_production_when_unset():
    s = _settings(APP_ENV="development", GSTR3B_FILING_ENABLED=None)
    assert s.gstr3b_filing_enabled is True


def test_gstr3b_disabled_in_production_when_unset():
    s = _settings(APP_ENV="production", GSTR3B_FILING_ENABLED=None)
    assert s.gstr3b_filing_enabled is False


def test_gstr3b_explicit_true_overrides_production():
    s = _settings(APP_ENV="production", GSTR3B_FILING_ENABLED=True)
    assert s.gstr3b_filing_enabled is True


def test_gstr3b_explicit_false_overrides_development():
    s = _settings(APP_ENV="development", GSTR3B_FILING_ENABLED=False)
    assert s.gstr3b_filing_enabled is False


def test_require_gstr3b_raises_503_when_disabled(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("GSTR3B_FILING_ENABLED", raising=False)
    get_settings.cache_clear()
    try:
        try:
            require_gstr3b_filing_enabled()
            raised = False
        except HTTPException as exc:
            raised = True
            assert exc.status_code == 503
            assert isinstance(exc.detail, dict)
            assert exc.detail["code"] == "GSTR3B_FILING_DISABLED"
        assert raised
    finally:
        get_settings.cache_clear()
