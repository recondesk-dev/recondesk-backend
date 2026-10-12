"""Phase 4.3: Unit & Statutory Rule Tests for Form GSTR-5A (OIDAR Overseas Supplies).

Statutory References:
- Section 14 of IGST Act, 2017 (OIDAR services supplied from outside India to NTOR in India)
- Rule 64 of CGST Rules, 2017 (Due date 20th of succeeding month, Form GSTR-5A)
- Uniform 18% IGST tax rate
- Zero domestic Input Tax Credit (ITC) invariant

Tests:
1. Section 14 statutory tax computation (18% IGST exclusively).
2. Zero ITC invariant enforcement.
3. Due date (20th of succeeding month).
4. Table 5 outward supplies and Table 5A amendments.
5. Duplicate Place of Supply (POS) detection in Table 5.
6. Official GSTN offline JSON format verification.
"""

from decimal import Decimal
import pytest

from app.rules.gstr5a_rules import (
    OIDAR_DUE_DATE_DAY,
    OIDAR_STANDARD_IGST_RATE,
    compute_oidar_tax_for_supply,
    summarize_gstr5a_supplies,
)
from app.services.gstr5a_service import (
    Gstr5aDuplicateError,
    Gstr5aError,
    Gstr5aValidationError,
    add_or_update_record_sync,
    build_gstr5a_offline_json,
    delete_record_sync,
    get_batch_summary_sync,
    get_or_create_batch_sync,
    reset_gstr5a_store_for_testing,
)


@pytest.fixture(autouse=True)
def clean_store():
    reset_gstr5a_store_for_testing()


def test_oidar_statutory_constants():
    from app.rules.gstr5a_rules import STATUTORY_OIDAR_RATES, is_valid_statutory_oidar_rate
    assert OIDAR_DUE_DATE_DAY == 20
    assert OIDAR_STANDARD_IGST_RATE == Decimal("0.18")
    assert Decimal("18.0") in STATUTORY_OIDAR_RATES
    assert Decimal("28.0") in STATUTORY_OIDAR_RATES  # Section 14A online money gaming
    assert Decimal("5.0") in STATUTORY_OIDAR_RATES   # E-books
    assert is_valid_statutory_oidar_rate(18.0) is True
    assert is_valid_statutory_oidar_rate(28.0) is True
    assert is_valid_statutory_oidar_rate(5.0) is True
    assert is_valid_statutory_oidar_rate(12.0) is False  # Non-statutory for OIDAR


def test_oidar_tax_calculation_single_head_igst():
    # ₹10,00,000 supply to consumers in Maharashtra (27) at standard 18% IGST
    # Must attract 18% IGST (₹1,80,000) - NEVER CGST or SGST
    igst, cess, total_tax = compute_oidar_tax_for_supply(
        taxable_value=1000000.0,
        rate_pct=18.0,
        cess_amount=0.0,
    )
    assert igst == Decimal("180000.00")
    assert cess == Decimal("0.00")
    assert total_tax == Decimal("180000.00")

    # ₹5,00,000 online money gaming supply under Section 14A at 28% IGST
    igst_gaming, _, total_gaming = compute_oidar_tax_for_supply(
        taxable_value=500000.0,
        rate_pct=28.0,
        cess_amount=0.0,
    )
    assert igst_gaming == Decimal("140000.00")
    assert total_gaming == Decimal("140000.00")


def test_gstr5a_service_batch_lifecycle_and_summary():
    sb = None
    batch = get_or_create_batch_sync(
        sb,
        firm_id="f0000000-0000-0000-0000-000000000001",
        client_gstin_id="c0000000-0000-0000-0000-000000000001",
        gstin="9917USA00000OID",
        period="2026-07",
    )
    assert batch.status == "DRAFT"

    # Add Table 5 Record for MH (27)
    rec1 = add_or_update_record_sync(
        sb,
        batch_id=batch.id,
        record_data={
            "pos": "27",
            "taxable_value": 500000.0,
            "rate_pct": 18.0,
            "cess": 0.0,
            "record_type": "ORIGINAL",
        },
    )
    assert rec1.igst == 90000.0

    # Add Table 5 Record for KA (29)
    rec2 = add_or_update_record_sync(
        sb,
        batch_id=batch.id,
        record_data={
            "pos": "29",
            "taxable_value": 300000.0,
            "rate_pct": 18.0,
            "cess": 0.0,
            "record_type": "ORIGINAL",
        },
    )
    assert rec2.igst == 54000.0

    # Attempting to add duplicate POS in Table 5 should raise Gstr5aDuplicateError
    with pytest.raises(Gstr5aDuplicateError):
        add_or_update_record_sync(
            sb,
            batch_id=batch.id,
            record_data={
                "pos": "27",
                "taxable_value": 100000.0,
                "record_type": "ORIGINAL",
            },
        )

    # Add Table 5A Amendment for earlier period (2026-06)
    rec_amd = add_or_update_record_sync(
        sb,
        batch_id=batch.id,
        record_data={
            "pos": "27",
            "taxable_value": 50000.0,
            "rate_pct": 18.0,
            "cess": 0.0,
            "record_type": "AMENDMENT",
            "original_period": "2026-06",
            "original_pos": "27",
        },
    )
    assert rec_amd.record_type == "AMENDMENT"

    summary = get_batch_summary_sync(sb, batch_id=batch.id)
    # Total taxable = 5,00,000 + 3,00,000 + 50,000 = 8,50,000
    # Total IGST = 90,000 + 54,000 + 9,000 = 1,53,000
    assert summary["tax_summary"]["total_taxable_value"] == 850000.0
    assert summary["tax_summary"]["total_igst"] == 153000.0
    assert summary["tax_summary"]["net_tax_payable"] == 153000.0
    assert summary["statutory_checks"]["eligible_itc"] == 0.00


def test_gstr5a_offline_json_structure():
    sb = None
    batch = get_or_create_batch_sync(
        sb,
        firm_id="f0000000-0000-0000-0000-000000000001",
        client_gstin_id="c0000000-0000-0000-0000-000000000001",
        gstin="9917USA00000OID",
        period="2026-07",
    )
    add_or_update_record_sync(
        sb,
        batch_id=batch.id,
        record_data={
            "pos": "27",
            "taxable_value": 500000.0,
            "rate_pct": 18.0,
            "cess": 0.0,
            "record_type": "ORIGINAL",
        },
    )

    offline_json = build_gstr5a_offline_json(sb, batch_id=batch.id)
    assert offline_json["gstin"] == "9917USA00000OID"
    assert offline_json["fp"] == "072026"
    assert "sec5" in offline_json
    assert len(offline_json["sec5"]) == 1
    assert offline_json["sec5"][0]["pos"] == "27"
    assert offline_json["sec5"][0]["txval"] == 500000.0
    assert offline_json["sec5"][0]["iamt"] == 90000.0
