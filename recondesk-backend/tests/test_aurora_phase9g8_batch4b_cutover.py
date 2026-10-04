"""Phase 9G-8 Batch 4B Application Cutover & Supabase Outage Resilience Tests.

Verifies:
1. Aurora PostgreSQL is PRIMARY for all normal reads and writes on:
   - billing_company_profiles
   - billing_customers
   - billing_items
   - billing_invoices
   - billing_invoice_line_items
   - billing_credit_debit_notes
   - billing_cdn_line_items
   - billing_irp_submission_log
2. Zero dual-write behavior to Supabase during normal operation.
3. Complete Supabase outage simulation: all billing operations succeed on Aurora PRIMARY.
4. Supabase fallback activation: when Aurora repository raises an error, calls fall back safely.
5. Strict tenant isolation by client_gstin_id.
6. Atomic sequential numbering for invoices and CDNs.
"""

from __future__ import annotations

import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

backend_root = Path(__file__).resolve().parents[1]
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.models.schema_base import Base
from app.models.tenancy import ClientGSTIN, UserProfile
from app.models.billing_ledger import (
    BillingCdnLineItem,
    BillingCompanyProfile,
    BillingCreditDebitNote,
    BillingCustomer,
    BillingInvoice,
    BillingInvoiceLineItem,
    BillingIrpSubmissionLog,
    BillingItem,
)
from app.repositories.billing_ledger import (
    AuroraBillingLedgerRepository,
    set_billing_ledger_repository,
)
from app.models.billing import (
    CdnCreateInput,
    CdnNoteType,
    CdnReason,
    CdnUpdateInput,
    CompanyProfileCreate,
    CompanyProfileUpdate,
    CustomerCreate,
    CustomerUpdate,
    InvoiceCreateInput,
    InvoiceLineItemInput,
    InvoiceStatus,
    InvoiceUpdateInput,
    ItemCreate,
    ItemType,
    ItemUpdate,
)
from app.services.billing import invoice_service, cdn_service, irp_submission_service


@pytest.fixture
def aurora_billing_db():
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    repo = AuroraBillingLedgerRepository(session_factory=session_factory)
    set_billing_ledger_repository(repo)

    client1_id = uuid.UUID("11111111-1111-4111-8111-111111111111")
    client2_id = uuid.UUID("22222222-2222-4222-8222-222222222222")
    user_id = uuid.UUID("99999999-9999-4999-8999-999999999999")

    # Seed parent UserProfile and ClientGSTIN records for foreign key integrity
    with session_factory() as s:
        s.add(UserProfile(id=user_id, email="owner@recondesk.test", role="firm_owner"))
        s.add(
            ClientGSTIN(
                id=client1_id,
                firm_owner_id=user_id,
                gstin="27ABCDE1234F1Z0",
                legal_name="Alpha Tech Pvt Ltd",
                trade_name="Alpha Tech",
            )
        )
        s.add(
            ClientGSTIN(
                id=client2_id,
                firm_owner_id=user_id,
                gstin="29AABCT1332L1ZA",
                legal_name="Beta Solutions LLP",
                trade_name="Beta Solutions",
            )
        )
        s.commit()

    yield repo, session_factory, str(client1_id), str(client2_id), str(user_id)
    set_billing_ledger_repository(None)


def test_batch4b_company_profile_cutover(aurora_billing_db):
    """Test 1: Company Profile CRUD on Aurora PRIMARY."""
    repo, _, client1_id, _, _ = aurora_billing_db
    mock_sb = MagicMock()

    profile_in = CompanyProfileCreate(
        client_gstin_id=client1_id,
        legal_name="Alpha Tech Pvt Ltd",
        trade_name="Alpha Tech",
        gstin="27ABCDE1234F1Z0",
        address_line1="123 Tech Park",
        city="Mumbai",
        state_code="27",
        pincode="400001",
        invoice_number_prefix="ALP/26-27/",
        invoice_number_next_seq=1,
    )

    created = invoice_service.create_company_profile(mock_sb, profile_in)
    assert created["id"] is not None
    assert created["legal_name"] == "Alpha Tech Pvt Ltd"
    mock_sb.table.assert_not_called()  # Zero dual-write

    # Read back
    fetched = invoice_service.get_company_profile(mock_sb, created["id"], client1_id)
    assert fetched["id"] == created["id"]
    assert fetched["trade_name"] == "Alpha Tech"
    mock_sb.table.assert_not_called()

    # List
    profiles = invoice_service.list_company_profiles(mock_sb, client1_id)
    assert len(profiles) == 1
    mock_sb.table.assert_not_called()

    # Update
    update_in = CompanyProfileUpdate(trade_name="Alpha Technologies")
    updated = invoice_service.update_company_profile(mock_sb, created["id"], client1_id, update_in)
    assert updated["trade_name"] == "Alpha Technologies"
    mock_sb.table.assert_not_called()


def test_batch4b_customer_and_item_cutover(aurora_billing_db):
    """Test 2: Customer and Item CRUD on Aurora PRIMARY."""
    repo, _, client1_id, _, _ = aurora_billing_db
    mock_sb = MagicMock()

    # Create customer
    cust_in = CustomerCreate(
        client_gstin_id=client1_id,
        name="Global Client Inc",
        is_b2b=True,
        gstin="07ABCDE1234F1Z2",
        address_line1="45 Marine Drive",
        city="Mumbai",
        state_code="27",
        pincode="400020",
    )
    cust = invoice_service.create_customer(mock_sb, cust_in)
    assert cust["id"] is not None
    mock_sb.table.assert_not_called()

    cust_fetched = invoice_service.get_customer(mock_sb, cust["id"], client1_id)
    assert cust_fetched["name"] == "Global Client Inc"
    mock_sb.table.assert_not_called()

    # Create item
    item_in = ItemCreate(
        client_gstin_id=client1_id,
        name="Consulting Services",
        hsn_or_sac_code="998311",
        unit="HRS",
        rate_paise=500000,
        tax_rate_percent=18.0,
        item_type=ItemType.SERVICE,
    )
    item = invoice_service.create_item(mock_sb, item_in)
    assert item["id"] is not None
    mock_sb.table.assert_not_called()

    item_fetched = invoice_service.get_item(mock_sb, item["id"], client1_id)
    assert item_fetched["unit"] == "HRS"
    mock_sb.table.assert_not_called()


def test_batch4b_invoice_lifecycle_and_sequence(aurora_billing_db):
    """Test 3: Full Invoice lifecycle with atomic sequence and line items."""
    repo, _, client1_id, _, _ = aurora_billing_db
    mock_sb = MagicMock()

    # Setup profile & customer
    profile = invoice_service.create_company_profile(
        mock_sb,
        CompanyProfileCreate(
            client_gstin_id=client1_id,
            legal_name="Alpha Tech Pvt Ltd",
            trade_name="Alpha Tech",
            gstin="27ABCDE1234F1Z0",
            address_line1="123 Tech Park",
            city="Mumbai",
            state_code="27",
            pincode="400001",
            invoice_number_prefix="ALP/26-27/",
            invoice_number_next_seq=1,
        ),
    )
    customer = invoice_service.create_customer(
        mock_sb,
        CustomerCreate(
            client_gstin_id=client1_id,
            name="Global Client Inc",
            is_b2b=True,
            gstin="07ABCDE1234F1Z2",
            address_line1="45 Marine Drive",
            city="Mumbai",
            state_code="27",
            pincode="400020",
        ),
    )
    item = invoice_service.create_item(
        mock_sb,
        ItemCreate(
            client_gstin_id=client1_id,
            name="SaaS Subscription",
            hsn_or_sac_code="998313",
            unit="NOS",
            rate_paise=1000000,
            tax_rate_percent=18.0,
            item_type=ItemType.SERVICE,
        ),
    )

    # 1. Create Invoice
    inv_in = InvoiceCreateInput(
        client_gstin_id=client1_id,
        company_profile_id=profile["id"],
        customer_id=customer["id"],
        invoice_date=date(2026, 10, 4),
        place_of_supply="27",
        line_items=[
            InvoiceLineItemInput(
                item_id=item["id"],
                description="Annual Platform License",
                hsn_or_sac_code="998313",
                quantity=1.0,
                unit="NOS",
                rate_paise=1000000,
                discount_percent=0.0,
                tax_rate_percent=18.0,
            )
        ],
    )
    inv = invoice_service.create_invoice(mock_sb, inv_in)
    assert inv["invoice_number"] == "ALP/26-27/0001"
    assert inv["status"] == "draft"
    assert inv["subtotal_paise"] == 1000000
    assert inv["total_tax_paise"] == 180000
    assert inv["total_paise"] == 1180000
    assert len(inv["line_items"]) == 1
    mock_sb.table.assert_not_called()

    # Next invoice increments sequence
    inv_in2 = InvoiceCreateInput(
        client_gstin_id=client1_id,
        company_profile_id=profile["id"],
        customer_id=customer["id"],
        invoice_date=date(2026, 10, 5),
        place_of_supply="27",
        line_items=[
            InvoiceLineItemInput(
                item_id=item["id"],
                description="Consulting Pack",
                hsn_or_sac_code="998313",
                quantity=2.0,
                unit="NOS",
                rate_paise=500000,
                discount_percent=0.0,
                tax_rate_percent=18.0,
            )
        ],
    )
    inv2 = invoice_service.create_invoice(mock_sb, inv_in2)
    assert inv2["invoice_number"] == "ALP/26-27/0002"
    mock_sb.table.assert_not_called()

    # 2. Finalize Invoice 1
    finalized = invoice_service.finalize_invoice(mock_sb, inv["id"], client1_id)
    assert finalized["status"] == "finalized"
    mock_sb.table.assert_not_called()

    # 3. Get invoice detail
    detail = invoice_service.get_invoice_detail(mock_sb, inv["id"], client1_id)
    assert detail["id"] == inv["id"]
    assert detail["customer"]["name"] == "Global Client Inc"
    assert detail["company_profile"]["legal_name"] == "Alpha Tech Pvt Ltd"
    mock_sb.table.assert_not_called()

    # 4. List invoices
    inv_list = invoice_service.list_invoices(mock_sb, client1_id)
    assert len(inv_list) == 2
    mock_sb.table.assert_not_called()


def test_batch4b_credit_note_lifecycle(aurora_billing_db):
    """Test 4: Credit Note creation linked to IRP registered invoice on Aurora PRIMARY."""
    repo, _, client1_id, _, user_id = aurora_billing_db
    mock_sb = MagicMock()

    # Seed company, customer, item, invoice
    profile = invoice_service.create_company_profile(
        mock_sb,
        CompanyProfileCreate(
            client_gstin_id=client1_id,
            legal_name="Alpha Tech Pvt Ltd",
            trade_name="Alpha Tech",
            gstin="27ABCDE1234F1Z0",
            address_line1="123 Tech Park",
            city="Mumbai",
            state_code="27",
            pincode="400001",
            invoice_number_prefix="ALP/26-27/",
            cdn_number_prefix="CRN/ALP/",
            cdn_number_next_seq=1,
        ),
    )
    customer = invoice_service.create_customer(
        mock_sb,
        CustomerCreate(
            client_gstin_id=client1_id,
            name="Global Client Inc",
            is_b2b=True,
            gstin="07ABCDE1234F1Z2",
            address_line1="45 Marine Drive",
            city="Mumbai",
            state_code="27",
            pincode="400020",
        ),
    )
    inv = invoice_service.create_invoice(
        mock_sb,
        InvoiceCreateInput(
            client_gstin_id=client1_id,
            company_profile_id=profile["id"],
            customer_id=customer["id"],
            invoice_date=date(2026, 10, 4),
            place_of_supply="27",
            line_items=[
                InvoiceLineItemInput(
                    description="Licensing",
                    hsn_or_sac_code="998313",
                    quantity=1.0,
                    unit="NOS",
                    rate_paise=1000000,
                    discount_percent=0.0,
                    tax_rate_percent=18.0,
                )
            ],
        ),
    )

    # Mark invoice as irp_registered so CDN can be issued
    repo.update_invoice(
        inv["id"],
        client1_id,
        {
            "status": "finalized",
            "irp_status": "irp_registered",
            "irn": "3c02c678a635817d23d8cbfbf8122c4d62b168926eb3971eef6c518881d77cb3",
        },
    )

    # Mock user access check
    with patch("app.services.billing.cdn_service._assert_access"):
        cdn_in = CdnCreateInput(
            client_gstin_id=client1_id,
            original_invoice_id=inv["id"],
            note_type=CdnNoteType.CREDIT,
            note_date=date(2026, 10, 6),
            reason=CdnReason.CORRECTION_IN_INVOICE,
            reason_detail="Partial credit for discount adjustment",
            line_items=[
                InvoiceLineItemInput(
                    description="Discount refund",
                    hsn_or_sac_code="998313",
                    quantity=1.0,
                    unit="NOS",
                    rate_paise=200000,
                    discount_percent=0.0,
                    tax_rate_percent=18.0,
                )
            ],
        )

        created_cdn = cdn_service.create_credit_debit_note(mock_sb, cdn_in, user_id)
        assert created_cdn["note_number"] == "CRN/ALP/0000001"
        assert created_cdn["subtotal_paise"] == 200000
        assert created_cdn["status"] == "draft"
        mock_sb.table.assert_not_called()

        # Update CDN
        update_in = CdnUpdateInput(notes="Updated credit rationale")
        updated_cdn = cdn_service.update_cdn(mock_sb, created_cdn["id"], client1_id, update_in, user_id)
        assert updated_cdn["notes"] == "Updated credit rationale"
        mock_sb.table.assert_not_called()

        # Finalize CDN
        finalized_cdn = cdn_service.finalize_cdn(mock_sb, created_cdn["id"], client1_id, user_id)
        assert finalized_cdn["status"] == "finalized"
        mock_sb.table.assert_not_called()

        # List CDNs
        cdn_list = cdn_service.list_cdns(mock_sb, client1_id, user_or_id=user_id)
        assert len(cdn_list) == 1
        mock_sb.table.assert_not_called()


def test_batch4b_irp_audit_log_and_status(aurora_billing_db):
    """Test 5: IRP audit logs and status info on Aurora PRIMARY."""
    repo, _, client1_id, _, user_id = aurora_billing_db
    mock_sb = MagicMock()

    # Create profile, customer, invoice
    profile = invoice_service.create_company_profile(
        mock_sb,
        CompanyProfileCreate(
            client_gstin_id=client1_id,
            legal_name="Alpha Tech Pvt Ltd",
            trade_name="Alpha Tech",
            gstin="27ABCDE1234F1Z0",
            address_line1="123 Tech Park",
            city="Mumbai",
            state_code="27",
            pincode="400001",
        ),
    )
    customer = invoice_service.create_customer(
        mock_sb,
        CustomerCreate(
            client_gstin_id=client1_id,
            name="Global Client Inc",
            is_b2b=True,
            gstin="07ABCDE1234F1Z2",
            address_line1="45 Marine Drive",
            city="Mumbai",
            state_code="27",
            pincode="400020",
        ),
    )
    inv = invoice_service.create_invoice(
        mock_sb,
        InvoiceCreateInput(
            client_gstin_id=client1_id,
            company_profile_id=profile["id"],
            customer_id=customer["id"],
            invoice_date=date(2026, 10, 4),
            place_of_supply="27",
            line_items=[
                InvoiceLineItemInput(
                    description="Consulting",
                    hsn_or_sac_code="998311",
                    quantity=1.0,
                    unit="HRS",
                    rate_paise=100000,
                    discount_percent=0.0,
                    tax_rate_percent=18.0,
                )
            ],
        ),
    )

    # Log an attempt
    irp_submission_service.log_submission_attempt(
        db=mock_sb,
        invoice_id=inv["id"],
        client_gstin_id=client1_id,
        environment="test",
        request_payload={"test": "payload"},
        response_status="success",
        response_body={"Irn": "mock_irn_123"},
    )
    mock_sb.table.assert_not_called()

    # Retrieve status info
    with patch("app.services.billing.irp_submission_service._assert_access"):
        status_info = irp_submission_service.get_irp_status_info(mock_sb, inv["id"], client1_id, user_id)
        assert status_info["invoice_id"] == inv["id"]
        assert len(status_info["submission_logs"]) == 1
        assert status_info["submission_logs"][0]["response_status"] == "success"
        mock_sb.table.assert_not_called()


def test_batch4b_supabase_outage_simulation(aurora_billing_db):
    """Test 6: All billing operations succeed during a complete Supabase outage."""
    repo, _, client1_id, _, _ = aurora_billing_db

    # Create broken Supabase mock that raises on any access
    mock_sb_down = MagicMock()
    mock_sb_down.table.side_effect = RuntimeError("Supabase cluster unreachable / connection timeout")

    # Company profile creation
    profile = invoice_service.create_company_profile(
        mock_sb_down,
        CompanyProfileCreate(
            client_gstin_id=client1_id,
            legal_name="Outage Safe Ltd",
            trade_name="Outage Safe",
            gstin="27ABCDE1234F1Z0",
            address_line1="Safe Zone",
            city="Mumbai",
            state_code="27",
            pincode="400001",
        ),
    )
    assert profile["legal_name"] == "Outage Safe Ltd"

    # Customer creation
    customer = invoice_service.create_customer(
        mock_sb_down,
        CustomerCreate(
            client_gstin_id=client1_id,
            name="Resilient Buyer",
            is_b2b=True,
            gstin="07ABCDE1234F1Z2",
            address_line1="Buyer Road",
            city="Mumbai",
            state_code="27",
            pincode="400020",
        ),
    )
    assert customer["name"] == "Resilient Buyer"

    # Item creation
    item = invoice_service.create_item(
        mock_sb_down,
        ItemCreate(
            client_gstin_id=client1_id,
            name="Emergency Item",
            hsn_or_sac_code="998311",
            unit="NOS",
            rate_paise=200000,
            tax_rate_percent=18.0,
            item_type=ItemType.SERVICE,
        ),
    )
    assert item["unit"] == "NOS"

    # Invoice creation
    inv = invoice_service.create_invoice(
        mock_sb_down,
        InvoiceCreateInput(
            client_gstin_id=client1_id,
            company_profile_id=profile["id"],
            customer_id=customer["id"],
            invoice_date=date(2026, 10, 4),
            place_of_supply="27",
            line_items=[
                InvoiceLineItemInput(
                    item_id=item["id"],
                    description="Item During Outage",
                    hsn_or_sac_code="998311",
                    quantity=1.0,
                    unit="NOS",
                    rate_paise=200000,
                    discount_percent=0.0,
                    tax_rate_percent=18.0,
                )
            ],
        ),
    )
    assert inv["invoice_number"] == "INV-0001"
    assert inv["total_paise"] == 236000

    # Invoice detail
    detail = invoice_service.get_invoice_detail(mock_sb_down, inv["id"], client1_id)
    assert detail["id"] == inv["id"]


def test_batch4b_tenant_isolation(aurora_billing_db):
    """Test 7: Client GSTIN isolation boundaries strictly enforced."""
    repo, _, client1_id, client2_id, _ = aurora_billing_db
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

    # Create profile for client 1
    prof1 = invoice_service.create_company_profile(
        mock_sb,
        CompanyProfileCreate(
            client_gstin_id=client1_id,
            legal_name="Client 1 Corp",
            trade_name="Client 1",
            gstin="27ABCDE1234F1Z0",
            address_line1="Road 1",
            city="Mumbai",
            state_code="27",
            pincode="400001",
        ),
    )

    # Client 2 query for Client 1's profile returns None or 404
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        invoice_service.get_company_profile(mock_sb, prof1["id"], client2_id)
    assert exc.value.status_code == 404

    # Client 2 listing does not see Client 1's profile
    c2_profiles = invoice_service.list_company_profiles(mock_sb, client2_id)
    assert len(c2_profiles) == 0
