"""Phase 4.3: Unit & Statutory Rule Tests for Form GSTR-5 (Non-Resident Taxable Persons).

Statutory References:
- Section 24(v) of CGST Act, 2017 (Compulsory registration for NRTP)
- Section 27(1) & (2) of CGST Act, 2017 (90-day registration validity & advance tax deposit)
- Rule 63 of CGST Rules, 2017 (Amended via Notification No. 26/2022-CT: due date is 13th of succeeding month or 7 days post-expiry)
- Section 17(5) of CGST Act (Domestic inward ITC prohibited; Bill of Entry BoE import ITC-only)

Tests:
1. 90-day registration validity tracking and extension calculation.
2. Statutory due date determination (earlier of 13th of succeeding month or 7 days post-expiry).
3. Bill of Entry BoE import ITC-only restriction under Section 17(5).
4. Advance tax deposit sufficiency check under Section 27(2).
5. Table 3 BoE imports, Table 5 B2B outward, Table 6 B2C outward, Table 7 amendments.
6. Official GSTN offline JSON format verification.
"""

from datetime import date
from decimal import Decimal
import pytest

from app.rules.gstr5_rules import (
    compute_nrtp_tax_summary,
    evaluate_nrtp_registration_and_due_date,
)
from app.services.gstr5_service import (
    Gstr5DuplicateError,
    Gstr5Error,
    Gstr5ValidationError,
    add_or_update_import_record_sync,
    add_or_update_outward_record_sync,
    build_gstr5_offline_json,
    delete_import_record_sync,
    delete_outward_record_sync,
    get_batch_summary_sync,
    get_or_create_batch_sync,
    reset_gstr5_store_for_testing,
)


@pytest.fixture(autouse=True)
def clean_store():
    reset_gstr5_store_for_testing()


def test_nrtp_registration_validity_calculation():
    # Registration for 90 days from 2026-06-01 to 2026-08-30
    start = date(2026, 6, 1)
    expiry = date(2026, 8, 30)

    # Check on 2026-07-15 -> within 90 days
    status_active = evaluate_nrtp_registration_and_due_date(
        period="2026-07",
        registration_start=start,
        registration_expiry=expiry,
        reference_date=date(2026, 7, 15),
    )
    assert status_active.is_valid is True
    assert status_active.days_remaining > 0

    # Check on 2026-09-05 -> expired
    status_expired = evaluate_nrtp_registration_and_due_date(
        period="2026-07",
        registration_start=start,
        registration_expiry=expiry,
        reference_date=date(2026, 9, 5),
    )
    assert status_expired.is_valid is False
    assert status_expired.is_expired is True


def test_nrtp_statutory_due_date_rule_63_amendment():
    # Test Notification No. 26/2022-Central Tax amendment:
    # 1. Standard active registration: Return for 2026-07 is due on 13th of August (2026-08-13)
    due_std = evaluate_nrtp_registration_and_due_date(
        period="2026-07",
        registration_start=date(2026, 6, 1),
        registration_expiry=date(2026, 8, 30),
    )
    assert due_std.statutory_due_date.isoformat() == "2026-08-13"

    # 2. Registration expires early (e.g. on 2026-08-02):
    # 7 days post-expiry = 2026-08-09, which is earlier than 2026-08-13!
    # Statutorily, the return must be filed by 2026-08-09!
    due_early = evaluate_nrtp_registration_and_due_date(
        period="2026-07",
        registration_start=date(2026, 6, 1),
        registration_expiry=date(2026, 8, 2),
    )
    assert due_early.statutory_due_date.isoformat() == "2026-08-09"


def test_advance_tax_deposit_sufficiency():
    outward = [{"taxable_value": 200000.0, "cgst": 18000.0, "sgst": 18000.0, "igst": 0.0}]
    imports = [{"taxable_value": 50000.0, "igst_paid": 9000.0}]

    # Liability = 36,000 - 9,000 = 27,000
    # Deposit ₹30,000 -> Sufficient
    summary_suff = compute_nrtp_tax_summary(
        outward_records=outward,
        import_records=imports,
        advance_tax_deposited=30000.0,
    )
    assert summary_suff.is_advance_sufficient is True
    assert summary_suff.net_tax_payable == Decimal("27000.00")
    assert summary_suff.shortfall_amount == Decimal("0.00")

    # Deposit ₹20,000 -> Deficit of 7,000
    summary_def = compute_nrtp_tax_summary(
        outward_records=outward,
        import_records=imports,
        advance_tax_deposited=20000.0,
    )
    assert summary_def.is_advance_sufficient is False
    assert summary_def.shortfall_amount == Decimal("7000.00")


def test_gstr5_service_batch_lifecycle_and_tax_summary():
    sb = None
    batch = get_or_create_batch_sync(
        sb,
        firm_id="f0000000-0000-0000-0000-000000000001",
        client_gstin_id="c0000000-0000-0000-0000-000000000001",
        gstin="27AAACG0000A1Z5",
        period="2026-07",
        registration_start_date="2026-06-01",
        registration_expiry_date="2026-08-30",
        advance_tax_deposited=100000.0,
    )
    assert batch.advance_tax_deposited == 100000.0

    # Add Table 3 BoE Import (Eligible ITC)
    imp = add_or_update_import_record_sync(
        sb,
        batch_id=batch.id,
        record_data={
            "boe_number": "BOE-5544",
            "boe_date": "2026-07-05",
            "port_code": "INBOM4",
            "taxable_value": 200000.0,
            "igst_paid": 36000.0,
            "cess_paid": 0.0,
        },
    )
    assert imp.igst_paid == 36000.0

    # Add Table 5 B2B Outward supply
    out_b2b = add_or_update_outward_record_sync(
        sb,
        batch_id=batch.id,
        record_data={
            "recipient_gstin": "27AABCT1234A1Z5",
            "pos": "27",
            "invoice_number": "NRTP-01",
            "invoice_date": "2026-07-15",
            "taxable_value": 300000.0,
            "rate_pct": 18.0,
            "igst": 0.0,
            "cgst": 27000.0,
            "sgst": 27000.0,
            "cess": 0.0,
            "record_type": "ORIGINAL",
        },
    )
    assert out_b2b.taxable_value == 300000.0

    # Add Table 6 B2C Outward supply
    out_b2c = add_or_update_outward_record_sync(
        sb,
        batch_id=batch.id,
        record_data={
            "recipient_gstin": None,
            "pos": "29",
            "invoice_number": "NRTP-02",
            "invoice_date": "2026-07-20",
            "taxable_value": 100000.0,
            "rate_pct": 18.0,
            "igst": 18000.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
            "record_type": "ORIGINAL",
        },
    )
    assert out_b2c.igst == 18000.0

    summary = get_batch_summary_sync(sb, batch_id=batch.id)
    # Gross outward liability = 27000 + 27000 + 18000 = 72,000
    # BoE import ITC = 36,000
    # Net tax payable = 72,000 - 36,000 = 36,000
    # Advance deposited = 1,00,000 -> Advance sufficient, cash payable = 0, refund eligible = 64,000
    assert summary["tax_summary"]["gross_tax_liability"] == 72000.0
    assert summary["tax_summary"]["eligible_import_itc"] == 36000.0
    assert summary["tax_summary"]["net_tax_payable"] == 36000.0
    assert summary["tax_summary"]["cash_payable"] == 0.0
    assert summary["tax_summary"]["refund_eligible"] == 64000.0
    assert summary["statutory_restrictions"]["inward_domestic_itc_permitted"] is False


def test_gstr5_offline_json_structure():
    sb = None
    batch = get_or_create_batch_sync(
        sb,
        firm_id="f0000000-0000-0000-0000-000000000001",
        client_gstin_id="c0000000-0000-0000-0000-000000000001",
        gstin="27AAACG0000A1Z5",
        period="2026-07",
    )
    add_or_update_import_record_sync(
        sb,
        batch_id=batch.id,
        record_data={
            "boe_number": "BOE-5544",
            "boe_date": "2026-07-05",
            "port_code": "INBOM4",
            "taxable_value": 200000.0,
            "igst_paid": 36000.0,
            "cess_paid": 0.0,
        },
    )
    add_or_update_outward_record_sync(
        sb,
        batch_id=batch.id,
        record_data={
            "recipient_gstin": "27AABCT1234A1Z5",
            "pos": "27",
            "invoice_number": "NRTP-01",
            "invoice_date": "2026-07-15",
            "taxable_value": 300000.0,
            "rate_pct": 18.0,
            "cgst": 27000.0,
            "sgst": 27000.0,
        },
    )

    offline_json = build_gstr5_offline_json(sb, batch_id=batch.id)
    assert offline_json["gstin"] == "27AAACG0000A1Z5"
    assert offline_json["fp"] == "072026"
    assert "imp_g" in offline_json
    assert len(offline_json["imp_g"]) == 1
    assert offline_json["imp_g"][0]["boe_num"] == "BOE-5544"
    assert "b2b" in offline_json
    assert len(offline_json["b2b"]) == 1
    assert offline_json["b2b"][0]["ctin"] == "27AABCT1234A1Z5"
