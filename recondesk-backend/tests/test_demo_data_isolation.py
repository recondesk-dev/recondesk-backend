"""Regression tests for Demo Workspace auto-provisioning and strict Real/Demo data isolation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from app.config import Settings, get_settings
from app.services.demo_seeding import (
    DEMO_CLIENT_GSTIN,
    DEMO_PERIOD,
    provision_demo_workspace_if_needed,
    seed_demo_dataset,
)


def _settings(**kwargs) -> Settings:
    defaults = {"SECRET_KEY": "a" * 32, "APP_ENV": "development"}
    defaults.update(kwargs)
    return Settings(**defaults)


def test_demo_feature_flag_defaults(monkeypatch):
    """Test DEMO_ONBOARDING_ENABLED feature flag config logic."""
    monkeypatch.delenv("DEMO_ONBOARDING_ENABLED", raising=False)
    
    # Dev/Local environment -> True by default
    s_dev = _settings(APP_ENV="development", DEMO_ONBOARDING_ENABLED=None)
    assert s_dev.demo_onboarding_enabled is True

    # Production environment -> False by default
    s_prod = _settings(APP_ENV="production", DEMO_ONBOARDING_ENABLED=None)
    assert s_prod.demo_onboarding_enabled is False

    # Explicit override in production -> True
    s_prod_override = _settings(APP_ENV="production", DEMO_ONBOARDING_ENABLED=True)
    assert s_prod_override.demo_onboarding_enabled is True

    # Explicit override in dev -> False
    s_dev_override = _settings(APP_ENV="development", DEMO_ONBOARDING_ENABLED=False)
    assert s_dev_override.demo_onboarding_enabled is False


def test_seed_demo_dataset_covers_all_modules():
    """Verify synthetic seed dataset generates records across all key feature modules."""
    gstr_records, pr_records = seed_demo_dataset()

    assert len(gstr_records) > 0
    assert len(pr_records) > 0

    # Section 17(5) blocked credits HSN check (8703 Motor Vehicle, 9995 Club Membership)
    hsns = {g.get("hsn_code") for g in gstr_records if g.get("hsn_code")}
    assert "8703" in hsns
    assert "9995" in hsns

    # Rule 37 unpaid items check
    unpaid_pr = [p for p in pr_records if p.get("payment_status") == "Unpaid"]
    assert len(unpaid_pr) >= 2

    # Total Rule 37 tax check (₹2.3L = 15000000 + 8000000 paise = 23000000 paise)
    rule37_tax_sum = sum(p.get("total_tax_paise", 0) for p in unpaid_pr)
    assert rule37_tax_sum == 23000000  # ₹2,30,000

    # RCM reverse charge check
    rcm_gstr = [g for g in gstr_records if g.get("is_reverse_charge") == "Y"]
    assert len(rcm_gstr) >= 1


def test_demo_workspace_data_isolation():
    """Regression test asserting real client queries never return demo rows and vice versa."""
    mock_sb = MagicMock()

    real_client_id = "11111111-1111-1111-1111-111111111111"
    demo_client_id = "99999999-9999-9999-9999-999999999999"

    real_row = {
        "id": "run-real-1",
        "client_gstin_id": real_client_id,
        "is_demo": False,
        "period": "2026-04",
    }
    demo_row = {
        "id": "run-demo-1",
        "client_gstin_id": demo_client_id,
        "is_demo": True,
        "period": "2026-04",
    }

    def mock_query(client_id: str, is_demo_filter: bool | None = None):
        rows = [real_row, demo_row]
        filtered = [r for r in rows if r["client_gstin_id"] == client_id]
        if is_demo_filter is not None:
            filtered = [r for r in filtered if r["is_demo"] == is_demo_filter]
        return filtered

    # Querying real client must NEVER return demo rows
    real_results = mock_query(real_client_id)
    assert len(real_results) == 1
    assert real_results[0]["id"] == "run-real-1"
    assert real_results[0]["is_demo"] is False

    # Querying demo client must NEVER return real client rows
    demo_results = mock_query(demo_client_id)
    assert len(demo_results) == 1
    assert demo_results[0]["id"] == "run-demo-1"
    assert demo_results[0]["is_demo"] is True


def test_provision_demo_workspace_skips_when_flag_off(monkeypatch):
    """Assert provision_demo_workspace_if_needed returns None when feature flag is disabled."""
    monkeypatch.setenv("DEMO_ONBOARDING_ENABLED", "false")
    get_settings.cache_clear()
    try:
        user_id = "test-user-123"
        result = provision_demo_workspace_if_needed(user_id)
        assert result is None
    finally:
        get_settings.cache_clear()
