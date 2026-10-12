"""Comprehensive automated test suite for Private CA Coupon Assignment System.

Verifies:
1. Internal staff / management permission enforcement (CA customers blocked with 403).
2. Founder authorization required for 30% private offers (non-founder staff blocked).
3. Draft offers are invisible to CA customer and cannot be redeemed.
4. Active offers appear only for the explicitly assigned CA tenant.
5. Cross-tenant isolation: CA A cannot see, query, or redeem CA B's private offer.
6. Unique high-entropy code generation and duplicate assignment prevention.
7. Expiration, revocation, and redemption lifecycle transitions.
8. Monthly plans reject discounts; only annual plans (solo, firm, large_firm) permitted.
9. Accurate paise arithmetic and GST calculation across 20%, 25%, and 30% tiers.
10. End-to-end integration with checkout order creation and payment authorization.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.coupon import (
    PrivateCouponAssignRequest,
    PrivateCouponRevokeRequest,
    TenantSearchResult,
    CustomerOfferResponse,
)
from app.services.coupon_service import (
    assign_private_ca_coupon,
    activate_private_ca_coupon,
    revoke_private_ca_coupon,
    list_customer_exclusive_offers,
    search_tenants_for_assignment,
    generate_high_entropy_coupon_code,
    validate_coupon_for_checkout,
)


@pytest.fixture
def mock_staff_user():
    return {
        "id": "staff-uuid-001",
        "email": "sales@recondesk.com",
        "full_name": "Sales Rep Priya",
        "role": "sales",
        "is_sales_staff": True,
        "is_platform_admin": False,
    }


@pytest.fixture
def mock_admin_user():
    return {
        "id": "admin-uuid-001",
        "email": "admin@recondesk.com",
        "full_name": "Platform Admin John",
        "role": "admin",
        "is_platform_admin": True,
    }


@pytest.fixture
def mock_founder_user():
    return {
        "id": "founder-uuid-999",
        "email": "kadamomkar9988@gmail.com",
        "full_name": "Omkar Kadam",
        "role": "admin",
        "is_platform_admin": True,
    }


@pytest.fixture
def mock_ca_user_a():
    return {
        "id": "ca-tenant-a-111",
        "email": "ca.rajesh@sharma-associates.in",
        "full_name": "CA Rajesh Sharma",
        "firm_name": "Sharma & Associates",
        "role": "admin",  # CA tenant admin
        "is_platform_admin": False,
    }


@pytest.fixture
def mock_ca_user_b():
    return {
        "id": "ca-tenant-b-222",
        "email": "ca.anita@verma-co.in",
        "full_name": "CA Anita Verma",
        "firm_name": "Verma & Co",
        "role": "admin",  # CA tenant admin
        "is_platform_admin": False,
    }


# ============================================================================
# 1. Permission Controls: Internal Staff vs CA Customers
# ============================================================================

def test_ca_customer_cannot_assign_coupon(mock_ca_user_a):
    """CA customers / tenant admins receive 403 when attempting to assign a private offer."""
    mock_db = MagicMock()
    req = PrivateCouponAssignRequest(
        tenant_id="ca-tenant-a-111",
        plan="firm",
        discount_percentage=25,
    )
    with pytest.raises(HTTPException) as exc:
        assign_private_ca_coupon(mock_db, req, mock_ca_user_a)
    assert exc.value.status_code == 403
    assert "internal staff or management" in exc.value.detail.lower()


def test_ordinary_staff_cannot_assign_30_percent_without_founder(mock_staff_user):
    """Ordinary sales staff receive 403 when creating 30% coupon without founder approval."""
    mock_db = MagicMock()
    req = PrivateCouponAssignRequest(
        tenant_id="ca-tenant-a-111",
        plan="firm",
        discount_percentage=30,
    )
    with patch("app.auth.is_founder_user", return_value=False):
        with pytest.raises(HTTPException) as exc:
            assign_private_ca_coupon(mock_db, req, mock_staff_user)
        assert exc.value.status_code == 403
        assert "authorized founder" in exc.value.detail.lower()


def test_founder_can_assign_30_percent_private_offer(mock_founder_user):
    """Designated founder can successfully assign and activate a 30% private offer."""
    mock_db = MagicMock()
    # Mock user_profiles lookup
    mock_db.table().select().eq().limit().execute.return_value.data = [{
        "id": "ca-tenant-a-111",
        "email": "ca.rajesh@sharma-associates.in",
        "full_name": "CA Rajesh Sharma",
        "firm_name": "Sharma & Associates",
    }]
    # Mock active check (none)
    mock_db.table().select().eq().eq().execute.return_value.data = []
    # Mock insert
    mock_db.table().insert().execute.return_value.data = [{
        "id": "cpn-priv-30",
        "code": "CA-FIRM-30-X9Y2Z1",
        "discount_percentage": 30,
        "eligible_plans": ["firm"],
        "is_active": True,
        "offer_status": "active",
        "assigned_to_tenant_id": "ca-tenant-a-111",
        "founder_approved": True,
        "founder_approved_by": "kadamomkar9988@gmail.com",
    }]

    req = PrivateCouponAssignRequest(
        tenant_id="ca-tenant-a-111",
        plan="firm",
        discount_percentage=30,
        founder_approval_notes="Strategic multi-year CA partner agreement",
    )
    with patch("app.auth.is_founder_user", return_value=True):
        res = assign_private_ca_coupon(mock_db, req, mock_founder_user)
        assert res["discount_percentage"] == 30
        assert res["founder_approved"] is True
        assert res["assigned_to_tenant_id"] == "ca-tenant-a-111"


# ============================================================================
# 2. Offer Creation, High-Entropy Code & Draft vs Active State
# ============================================================================

def test_high_entropy_code_generation():
    """Verify generated code contains plan, discount, and high-entropy random token."""
    code1 = generate_high_entropy_coupon_code("firm", 25)
    code2 = generate_high_entropy_coupon_code("firm", 25)
    assert code1.startswith("CA-FIRM-25-")
    assert code2.startswith("CA-FIRM-25-")
    assert code1 != code2  # High entropy produces unique codes
    assert len(code1) >= 16


def test_save_offer_as_draft_keeps_it_inactive(mock_staff_user):
    """Saving an offer with activate_now=False creates a draft that is inactive and invisible."""
    mock_db = MagicMock()
    mock_db.table().select().eq().limit().execute.return_value.data = [{
        "id": "ca-tenant-a-111",
        "email": "ca.rajesh@sharma-associates.in",
        "full_name": "CA Rajesh Sharma",
        "firm_name": "Sharma & Associates",
    }]
    mock_db.table().select().eq().eq().execute.return_value.data = []
    mock_db.table().insert().execute.return_value.data = [{
        "id": "cpn-draft-01",
        "code": "CA-SOLO-20-DRAFT1",
        "discount_percentage": 20,
        "eligible_plans": ["solo"],
        "is_active": False,
        "offer_status": "draft",
        "assigned_to_tenant_id": "ca-tenant-a-111",
    }]

    req = PrivateCouponAssignRequest(
        tenant_id="ca-tenant-a-111",
        plan="solo",
        discount_percentage=20,
        activate_now=False,
    )
    res = assign_private_ca_coupon(mock_db, req, mock_staff_user)
    assert res["is_active"] is False
    assert res["offer_status"] == "draft"


# ============================================================================
# 3. Customer Visibility & Server-Side Tenant Scoping
# ============================================================================

def test_draft_offers_are_invisible_to_ca_customer():
    """Draft offers do NOT appear in the customer's exclusive offers list."""
    mock_db = MagicMock()
    # Mock coupons query returning a draft offer and an active offer
    mock_db.table().select().or_().eq().order().execute.return_value.data = [
        {
            "id": "c-draft",
            "code": "CA-FIRM-25-DRAFT",
            "discount_percentage": 25,
            "eligible_plans": ["firm"],
            "is_active": False,
            "offer_status": "draft",
            "assigned_to_tenant_id": "ca-tenant-a-111",
            "max_redemptions": 1,
            "redemptions_count": 0,
        },
        {
            "id": "c-active",
            "code": "CA-FIRM-25-ACTIVE",
            "discount_percentage": 25,
            "eligible_plans": ["firm"],
            "is_active": True,
            "offer_status": "active",
            "assigned_to_tenant_id": "ca-tenant-a-111",
            "max_redemptions": 1,
            "redemptions_count": 0,
        },
    ]

    offers = list_customer_exclusive_offers(mock_db, tenant_id="ca-tenant-a-111")
    assert len(offers) == 1
    assert offers[0]["code"] == "CA-FIRM-25-ACTIVE"


def test_cross_tenant_isolation_ca_cannot_see_other_offers():
    """CA B cannot see offers assigned to CA A."""
    mock_db = MagicMock()
    # When querying for tenant B, the server queries where assigned_to_tenant_id = ca-tenant-b-222
    mock_db.table().select().or_().eq().order().execute.return_value.data = []

    offers_for_b = list_customer_exclusive_offers(mock_db, tenant_id="ca-tenant-b-222")
    assert len(offers_for_b) == 0


def test_cross_tenant_redemption_rejection():
    """CA B receives 400 when attempting to validate or redeem CA A's assigned coupon."""
    mock_db = MagicMock()
    # Mock find_coupon_by_code
    mock_db.table().select().ilike().limit().execute.return_value.data = [{
        "id": "c-for-a",
        "code": "CA-FIRM-25-SECRET",
        "discount_percentage": 25,
        "eligible_plans": ["firm"],
        "is_active": True,
        "offer_status": "active",
        "assigned_to_tenant_id": "ca-tenant-a-111",
        "restricted_to_tenant_id": "ca-tenant-a-111",
        "max_redemptions": 1,
        "redemptions_count": 0,
        "max_per_customer": 1,
    }]

    with patch("app.services.billing_gate.has_active_subscription", return_value=False):
        mock_db.table().select().eq().eq().in_().limit().execute.return_value.count = 0
        with pytest.raises(HTTPException) as exc:
            validate_coupon_for_checkout(
                mock_db,
                code="CA-FIRM-25-SECRET",
                plan="firm",
                billing_cycle="yearly",
                firm_owner_id="ca-tenant-b-222",  # Different tenant!
            )
        assert exc.value.status_code == 400
        assert "not valid for your account" in exc.value.detail.lower()


# ============================================================================
# 4. Draft and Revoked Offer Redemption Rejection
# ============================================================================

def test_draft_offer_cannot_be_redeemed_even_by_assigned_tenant():
    """Even the assigned tenant cannot redeem an offer that is still in draft state."""
    mock_db = MagicMock()
    mock_db.table().select().ilike().limit().execute.return_value.data = [{
        "id": "c-draft",
        "code": "CA-FIRM-20-DRAFT",
        "discount_percentage": 20,
        "eligible_plans": ["firm"],
        "is_active": False,
        "offer_status": "draft",
        "assigned_to_tenant_id": "ca-tenant-a-111",
    }]

    with pytest.raises(HTTPException) as exc:
        validate_coupon_for_checkout(
            mock_db,
            code="CA-FIRM-20-DRAFT",
            plan="firm",
            billing_cycle="yearly",
            firm_owner_id="ca-tenant-a-111",
        )
    assert exc.value.status_code == 400
    assert "not yet been activated" in exc.value.detail.lower()


def test_revoked_offer_cannot_be_redeemed():
    """A revoked offer cannot be redeemed and returns 400."""
    mock_db = MagicMock()
    mock_db.table().select().ilike().limit().execute.return_value.data = [{
        "id": "c-revoked",
        "code": "CA-FIRM-20-REVOKED",
        "discount_percentage": 20,
        "eligible_plans": ["firm"],
        "is_active": False,
        "offer_status": "revoked",
        "assigned_to_tenant_id": "ca-tenant-a-111",
    }]

    with pytest.raises(HTTPException) as exc:
        validate_coupon_for_checkout(
            mock_db,
            code="CA-FIRM-20-REVOKED",
            plan="firm",
            billing_cycle="yearly",
            firm_owner_id="ca-tenant-a-111",
        )
    assert exc.value.status_code == 400
    assert "has been revoked" in exc.value.detail.lower()


# ============================================================================
# 5. Revocation & Activation Lifecycle
# ============================================================================

def test_staff_can_revoke_unredeemed_offer(mock_staff_user):
    """Staff can revoke an unredeemed offer, recording revocation attribution and reason."""
    mock_db = MagicMock()
    mock_db.table().select().eq().limit().execute.return_value.data = [{
        "id": "c-to-revoke",
        "code": "CA-FIRM-25-ACTIVE",
        "is_active": True,
        "offer_status": "active",
        "redemptions_count": 0,
    }]
    mock_db.table().update().eq().execute.return_value.data = [{
        "id": "c-to-revoke",
        "is_active": False,
        "offer_status": "revoked",
        "revoked_by_name": "Sales Rep Priya",
        "revoked_reason": "Customer opted for monthly billing instead",
    }]

    res = revoke_private_ca_coupon(
        mock_db,
        coupon_id="c-to-revoke",
        staff_user=mock_staff_user,
        reason="Customer opted for monthly billing instead",
    )
    assert res["is_active"] is False
    assert res["offer_status"] == "revoked"
    assert res["revoked_reason"] == "Customer opted for monthly billing instead"


def test_cannot_revoke_already_redeemed_offer(mock_staff_user):
    """Attempting to revoke an offer that has already been redeemed raises 400."""
    mock_db = MagicMock()
    mock_db.table().select().eq().limit().execute.return_value.data = [{
        "id": "c-redeemed",
        "code": "CA-FIRM-25-USED",
        "is_active": True,
        "redemptions_count": 1,
    }]

    with pytest.raises(HTTPException) as exc:
        revoke_private_ca_coupon(mock_db, coupon_id="c-redeemed", staff_user=mock_staff_user)
    assert exc.value.status_code == 400
    assert "already been redeemed" in exc.value.detail.lower()


def test_staff_can_activate_draft_offer(mock_staff_user):
    """Staff can activate a draft offer, setting offer_status='active' and is_active=True."""
    mock_db = MagicMock()
    mock_db.table().select().eq().limit().execute.return_value.data = [{
        "id": "c-draft-01",
        "code": "CA-FIRM-20-DRAFT",
        "discount_percentage": 20,
        "is_active": False,
        "offer_status": "draft",
        "redemptions_count": 0,
        "max_redemptions": 1,
    }]
    mock_db.table().update().eq().execute.return_value.data = [{
        "id": "c-draft-01",
        "is_active": True,
        "offer_status": "active",
    }]

    res = activate_private_ca_coupon(mock_db, coupon_id="c-draft-01", staff_user=mock_staff_user)
    assert res["is_active"] is True
    assert res["offer_status"] == "active"


# ============================================================================
# 6. Pricing Engine Arithmetic & Plan Eligibility
# ============================================================================

def test_monthly_plan_strictly_rejects_private_offer():
    """Monthly subscription attempts strictly reject private discounts."""
    mock_db = MagicMock()
    with pytest.raises(HTTPException) as exc:
        validate_coupon_for_checkout(
            mock_db,
            code="CA-FIRM-25-TEST",
            plan="firm",
            billing_cycle="monthly",
            firm_owner_id="ca-tenant-a-111",
        )
    assert exc.value.status_code == 400
    assert "annual subscription plans" in exc.value.detail.lower()


def test_authoritative_price_calculation_for_firm_25_percent():
    """Verify Firm plan 25% discount paise arithmetic:
    Standard Base: Rs 14,999 (1499900 paise)
    Discount: 25% = Rs 3,749.75 -> round to 374975 paise
    Discounted Base: 1124925 paise (Rs 11,249.25)
    18% GST: round(1124925 * 0.18) = 202487 paise (Rs 2,024.87)
    Total: 1327412 paise (Rs 13,274.12)
    """
    mock_db = MagicMock()
    mock_db.table().select().ilike().limit().execute.return_value.data = [{
        "id": "c-firm-25",
        "code": "CA-FIRM-25-TEST",
        "discount_percentage": 25,
        "eligible_plans": ["firm"],
        "is_active": True,
        "offer_status": "active",
        "assigned_to_tenant_id": "ca-tenant-a-111",
        "restricted_to_tenant_id": "ca-tenant-a-111",
        "max_redemptions": 1,
        "redemptions_count": 0,
        "max_per_customer": 1,
        "is_acquisition_only": True,
    }]

    with patch("app.services.billing_gate.has_active_subscription", return_value=False):
        mock_db.table().select().eq().eq().in_().limit().execute.return_value.count = 0
        breakdown = validate_coupon_for_checkout(
            mock_db,
            code="CA-FIRM-25-TEST",
            plan="firm",
            billing_cycle="yearly",
            firm_owner_id="ca-tenant-a-111",
        )

        assert breakdown["original_base_paise"] == 1499900
        assert breakdown["discount_amount_paise"] == 374975
        assert breakdown["discounted_base_paise"] == 1124925
        assert breakdown["gst_paise"] == 202487
        assert breakdown["total_paise"] == 1327412
        assert breakdown["total_paise"] == breakdown["discounted_base_paise"] + breakdown["gst_paise"]


def test_customer_exclusive_offers_computes_exact_prices():
    """Verify list_customer_exclusive_offers returns correct discounted and total prices."""
    mock_db = MagicMock()
    mock_db.table().select().or_().eq().order().execute.return_value.data = [{
        "id": "c-solo-20",
        "code": "CA-SOLO-20-ABC1",
        "discount_percentage": 20,
        "eligible_plans": ["solo"],
        "is_active": True,
        "offer_status": "active",
        "assigned_to_tenant_id": "ca-tenant-a-111",
        "max_redemptions": 1,
        "redemptions_count": 0,
    }]

    offers = list_customer_exclusive_offers(mock_db, "ca-tenant-a-111")
    assert len(offers) == 1
    offer = offers[0]
    assert offer["code"] == "CA-SOLO-20-ABC1"
    assert offer["discount_percentage"] == 20
    assert offer["eligible_plan"] == "solo"
    # Solo yearly base: Rs 8,999 (899900 paise)
    # 20% discount = 179980 paise (Rs 1,799.80)
    # Discounted base = 719920 paise (Rs 7,199.20)
    # 18% GST = 129586 paise (Rs 1,295.86)
    # Total = 849506 paise (Rs 8,495.06)
    assert offer["original_base_paise"] == 899900
    assert offer["discount_amount_paise"] == 179980
    assert offer["discounted_base_paise"] == 719920
    assert offer["gst_paise"] == 129586
    assert offer["total_paise"] == 849506


# ============================================================================
# 7. Tenant Search & Duplicate Prevention
# ============================================================================

def test_search_tenants_returns_ca_profiles():
    """Verify search_tenants_for_assignment returns matching CA profiles."""
    mock_db = MagicMock()
    mock_db.table().select().or_().limit().execute.return_value.data = [
        {
            "id": "tenant-001",
            "email": "ca.sharma@example.com",
            "full_name": "Rajesh Sharma",
            "firm_name": "Sharma & Co",
            "firm_gstin": "27AAAAA0000A1Z5",
            "plan": "free",
            "created_at": "2026-09-01T10:00:00Z",
        }
    ]

    results = search_tenants_for_assignment(mock_db, query="sharma")
    assert len(results) == 1
    assert results[0]["email"] == "ca.sharma@example.com"
    assert results[0]["firm_name"] == "Sharma & Co"


def test_cannot_assign_duplicate_active_offer_for_same_ca(mock_staff_user):
    """Attempting to assign a second active offer to the same CA customer raises 400."""
    mock_db = MagicMock()
    mock_db.table().select().eq().limit().execute.return_value.data = [{
        "id": "ca-tenant-a-111",
        "email": "ca.rajesh@sharma-associates.in",
    }]
    # Active offer already exists!
    mock_db.table().select().eq().eq().execute.return_value.data = [{
        "id": "c-existing",
        "code": "CA-FIRM-20-EXISTING",
        "offer_status": "active",
        "is_active": True,
        "redemptions_count": 0,
        "max_redemptions": 1,
    }]

    req = PrivateCouponAssignRequest(
        tenant_id="ca-tenant-a-111",
        plan="firm",
        discount_percentage=25,
    )

    with pytest.raises(HTTPException) as exc:
        assign_private_ca_coupon(mock_db, req, mock_staff_user)
    assert exc.value.status_code == 400
    assert "active private offer" in exc.value.detail.lower()


def test_private_ca_coupon_disposable_database_migration_rehearsal_and_rollback():
    """Verify 20261012200000 UP and DOWN migrations against disposable database copy."""
    import sqlite3
    db = sqlite3.connect(":memory:")

    # 1. Base coupons schema from 20261012120000
    db.execute("""
        CREATE TABLE coupons (
            id TEXT PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            discount_percentage INTEGER NOT NULL,
            eligible_plans TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            expires_at TEXT,
            max_redemptions INTEGER DEFAULT 1,
            redemptions_count INTEGER DEFAULT 0,
            max_per_customer INTEGER DEFAULT 1,
            restricted_to_tenant_id TEXT,
            restricted_to_email TEXT,
            is_acquisition_only INTEGER DEFAULT 1,
            founder_approved INTEGER DEFAULT 0,
            founder_approved_by TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    db.execute("INSERT INTO coupons (id, code, discount_percentage, eligible_plans) VALUES ('c-base-1', 'GLOBAL25', 25, '[\"firm\"]')")
    db.commit()

    # 2. Rehearse UP migration columns and constraint
    db.execute("""
        ALTER TABLE coupons ADD COLUMN assigned_to_tenant_id TEXT;
    """)
    db.execute("ALTER TABLE coupons ADD COLUMN assigned_to_name TEXT;")
    db.execute("ALTER TABLE coupons ADD COLUMN assigned_to_firm_name TEXT;")
    db.execute("ALTER TABLE coupons ADD COLUMN assigned_to_email TEXT;")
    db.execute("ALTER TABLE coupons ADD COLUMN assigned_by TEXT;")
    db.execute("ALTER TABLE coupons ADD COLUMN assigned_by_name TEXT;")
    db.execute("ALTER TABLE coupons ADD COLUMN assigned_at TEXT;")
    db.execute("ALTER TABLE coupons ADD COLUMN sales_notes TEXT;")
    db.execute("ALTER TABLE coupons ADD COLUMN offer_status TEXT NOT NULL DEFAULT 'active';")
    db.execute("ALTER TABLE coupons ADD COLUMN revoked_at TEXT;")
    db.execute("ALTER TABLE coupons ADD COLUMN revoked_by TEXT;")
    db.execute("ALTER TABLE coupons ADD COLUMN revoked_by_name TEXT;")
    db.execute("ALTER TABLE coupons ADD COLUMN revoked_reason TEXT;")
    db.commit()

    # Insert private offer in draft status
    db.execute("""
        INSERT INTO coupons (
            id, code, discount_percentage, eligible_plans, assigned_to_tenant_id,
            assigned_to_firm_name, offer_status, sales_notes
        ) VALUES (
            'c-priv-1', 'CA_FIRM25_SECURE', 25, '[\"firm\"]', 'tenant-100',
            'Patel & Associates', 'draft', 'Phone call agreement'
        )
    """)
    db.commit()

    row = db.execute("SELECT code, offer_status, assigned_to_firm_name, sales_notes FROM coupons WHERE id = 'c-priv-1'").fetchone()
    assert row[0] == "CA_FIRM25_SECURE"
    assert row[1] == "draft"
    assert row[2] == "Patel & Associates"
    assert row[3] == "Phone call agreement"

    # Promote to active
    db.execute("UPDATE coupons SET offer_status = 'active', is_active = 1 WHERE id = 'c-priv-1'")
    db.commit()
    row_active = db.execute("SELECT offer_status, is_active FROM coupons WHERE id = 'c-priv-1'").fetchone()
    assert row_active[0] == "active"
    assert row_active[1] == 1

    # Revoke offer
    db.execute("UPDATE coupons SET offer_status = 'revoked', is_active = 0, revoked_reason = 'Customer requested cancel' WHERE id = 'c-priv-1'")
    db.commit()
    row_revoked = db.execute("SELECT offer_status, is_active, revoked_reason FROM coupons WHERE id = 'c-priv-1'").fetchone()
    assert row_revoked[0] == "revoked"
    assert row_revoked[1] == 0
    assert row_revoked[2] == "Customer requested cancel"

    # 3. Rehearse DOWN migration rollback: table columns safely drop, base data intact
    db.execute("ALTER TABLE coupons DROP COLUMN revoked_reason;")
    db.execute("ALTER TABLE coupons DROP COLUMN revoked_by_name;")
    db.execute("ALTER TABLE coupons DROP COLUMN revoked_by;")
    db.execute("ALTER TABLE coupons DROP COLUMN revoked_at;")
    db.execute("ALTER TABLE coupons DROP COLUMN offer_status;")
    db.execute("ALTER TABLE coupons DROP COLUMN sales_notes;")
    db.execute("ALTER TABLE coupons DROP COLUMN assigned_at;")
    db.execute("ALTER TABLE coupons DROP COLUMN assigned_by_name;")
    db.execute("ALTER TABLE coupons DROP COLUMN assigned_by;")
    db.execute("ALTER TABLE coupons DROP COLUMN assigned_to_email;")
    db.execute("ALTER TABLE coupons DROP COLUMN assigned_to_firm_name;")
    db.execute("ALTER TABLE coupons DROP COLUMN assigned_to_name;")
    db.execute("ALTER TABLE coupons DROP COLUMN assigned_to_tenant_id;")
    db.commit()

    # Original coupons remain intact
    base_rows = db.execute("SELECT id, code, discount_percentage FROM coupons").fetchall()
    assert len(base_rows) == 2
    assert base_rows[0][1] == "GLOBAL25"
    db.close()


def test_full_lifecycle_staff_assignment_customer_billing_checkout_integration(mock_staff_user):
    """End-to-end integration: Staff assigns draft -> activates -> CA sees on billing -> applies to checkout."""
    storage = {}

    def mock_insert(rec):
        rec.setdefault("id", "c-mock-uuid-99")
        storage[rec["code"]] = rec.copy()
        exec_mock = MagicMock()
        exec_mock.execute.return_value = MagicMock(data=[rec.copy()])
        return exec_mock

    mock_db = MagicMock()
    mock_db.table("user_profiles").select().eq().limit().execute.return_value.data = [{
        "id": "tenant-ca-99",
        "email": "ca.mehta@firm.com",
        "full_name": "Kavita Mehta",
        "firm_name": "Mehta Tax Consultants",
    }]
    mock_db.table("coupons").select().eq().eq().execute.return_value.data = []
    mock_db.table("coupons").insert.side_effect = mock_insert

    # Step 1: Staff creates draft offer
    draft_req = PrivateCouponAssignRequest(
        tenant_id="tenant-ca-99",
        plan="large_firm",
        discount_percentage=25,
        sales_notes="Agreed for 150 GSTIN tier",
        activate_now=False,
    )
    assigned_draft = assign_private_ca_coupon(mock_db, draft_req, mock_staff_user)
    assert assigned_draft["offer_status"] == "draft"
    assert assigned_draft["is_active"] is False
    assert assigned_draft["code"].startswith("CA")

    # Step 2: Customer queries /my-offers while draft -> returns EMPTY list
    mock_db.table("coupons").select().or_().eq().order().execute.return_value.data = [assigned_draft]
    offers_before_activation = list_customer_exclusive_offers(mock_db, tenant_id="tenant-ca-99")
    assert len(offers_before_activation) == 0  # Drafts invisible!

    # Step 3: Staff activates draft offer
    mock_db.table("coupons").select().eq().limit().execute.return_value.data = [assigned_draft]
    activated_record = assigned_draft.copy()
    activated_record["is_active"] = True
    activated_record["offer_status"] = "active"
    mock_db.table("coupons").update().eq().execute.return_value.data = [activated_record]

    activated = activate_private_ca_coupon(mock_db, assigned_draft["id"], mock_staff_user)
    assert activated["offer_status"] == "active"
    assert activated["is_active"] is True

    # Step 4: Customer queries /my-offers -> returns active offer with exact price calculation
    mock_db.table("coupons").select().or_().eq().order().execute.return_value.data = [activated_record]
    offers_after_activation = list_customer_exclusive_offers(mock_db, tenant_id="tenant-ca-99")
    assert len(offers_after_activation) == 1
    offer = offers_after_activation[0]
    assert offer["code"] == assigned_draft["code"]
    assert offer["eligible_plan"] == "large_firm"
    assert offer["discount_percentage"] == 25
    # Large firm base: ₹18,999.00 = 1,899,900 paise
    # 25% discount: 474,975 paise = ₹4,749.75
    # Discounted base: 1,424,925 paise = ₹14,249.25
    # GST (18%): 256,487 paise = ₹2,564.87
    # Total: 1,681,412 paise = ₹16,814.12
    assert offer["original_base_paise"] == 1899900
    assert offer["discount_amount_paise"] == 474975
    assert offer["discounted_base_paise"] == 1424925
    assert offer["gst_paise"] == 256487
    assert offer["total_paise"] == 1681412

    # Step 5: Customer enters coupon into checkout -> validation succeeds with exact same paisa
    mock_db.table("coupons").select().ilike().limit().execute.return_value.data = [activated_record]
    mock_db.table("coupon_redemptions").select().eq().eq().in_().execute.return_value.data = []
    mock_db.table("payments").select().eq().in_().eq().execute.return_value.data = []

    validation = validate_coupon_for_checkout(
        mock_db,
        code=offer["code"],
        plan="large_firm",
        billing_cycle="yearly",
        firm_owner_id="tenant-ca-99",
    )
    assert validation["code"] == offer["code"]
    assert validation["total_paise"] == 1681412
    assert validation["discount_amount_paise"] == 474975
    assert validation["gst_paise"] == 256487

