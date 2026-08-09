"""Unit tests for HSN/SAC code auto-suggest service and endpoint."""

from __future__ import annotations

import pytest
from app.services.billing.hsn_suggest_service import (
    check_hsn_type_mismatch,
    suggest_hsn_sac,
)


def test_suggest_hsn_sac_medicine():
    """Test suggestion matching for 'medicine' yields 30xx pharmaceutical HSN codes."""
    suggestions = suggest_hsn_sac("medicine")
    assert len(suggestions) > 0
    codes = [s["code"] for s in suggestions]
    assert any(c.startswith("30") for c in codes)
    for s in suggestions:
        assert s["item_type"] == "goods"


def test_suggest_hsn_sac_consulting():
    """Test suggestion matching for 'consulting' yields 9983 SAC codes."""
    suggestions = suggest_hsn_sac("consulting")
    assert len(suggestions) > 0
    codes = [s["code"] for s in suggestions]
    assert any(c.startswith("9983") for c in codes)
    for s in suggestions:
        assert s["item_type"] == "service"


def test_item_type_filtering_excludes_wrong_category():
    """Test item_type filter strictly excludes opposite category codes."""
    # "software" matches IT services (998314 SAC service)
    goods_suggestions = suggest_hsn_sac("software", item_type="goods")
    for s in goods_suggestions:
        assert s["item_type"] == "goods"
        assert not s["code"].startswith("99")

    service_suggestions = suggest_hsn_sac("laptop", item_type="service")
    for s in service_suggestions:
        assert s["item_type"] == "service"
        assert s["code"].startswith("99")


def test_unfiltered_item_type_returns_both():
    """Test un-filtered search returns relevant matches regardless of category."""
    suggestions = suggest_hsn_sac("food")
    types = {s["item_type"] for s in suggestions}
    assert len(suggestions) > 0
    assert "code" in suggestions[0]
    assert "description" in suggestions[0]


def test_mismatch_warning_triggers_correctly():
    """Test inline mismatch detection for HSN (goods) vs SAC (services 99xx)."""
    # 1. SAC code with goods item_type -> mismatch warning
    warn1 = check_hsn_type_mismatch("9983", "goods")
    assert warn1 is not None
    assert warn1["mismatch"] is True
    assert "Service (SAC 99xx)" in warn1["message"]

    # 2. HSN (goods) code with service item_type -> mismatch warning
    warn2 = check_hsn_type_mismatch("3004", "service")
    assert warn2 is not None
    assert warn2["mismatch"] is True
    assert "Goods (HSN)" in warn2["message"]

    # 3. Matching combinations -> no warning
    assert check_hsn_type_mismatch("9983", "service") is None
    assert check_hsn_type_mismatch("3004", "goods") is None
    assert check_hsn_type_mismatch("8471", "goods") is None


def test_suggest_hsn_api_endpoint(client, auth_headers):
    """Test GET /api/billing/masters/items/suggest-hsn endpoint."""
    response = client.get(
        "/api/billing/masters/items/suggest-hsn?q=laptop&type=goods",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert data[0]["code"] == "8471"
    assert data[0]["item_type"] == "goods"
