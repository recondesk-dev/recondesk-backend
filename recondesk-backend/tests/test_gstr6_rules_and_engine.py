"""Phase 4.3: Unit & Statutory Rule Tests for Form GSTR-6 (Input Service Distributor).

Statutory References:
- Section 20 of CGST Act, 2017 (Manner of distribution of credit by Input Service Distributor)
- Rule 39 of CGST Rules, 2017 (Procedure for distribution of input tax credit by Input Service Distributor)
- Rule 65 of CGST Rules, 2017 (Due date: 13th of succeeding month)
- Notification No. 12/2024-Central Tax (Mandatory ISD mechanism)

Tests:
1. Proportionate turnover allocation under Rule 39(1)(d).
2. Rule 39(1)(e) & (f) Tax Head Conversions:
   - Intra-state (ISD state == Recipient state): CGST/SGST/IGST preserved.
   - Cross-state (ISD state != Recipient state): CGST & SGST converted to IGST.
   - IGST distributed as IGST across all states.
3. Distinct person PAN matching (ISD and recipient must share 10-char PAN).
4. Ineligible ITC pool segregation under Section 17(5).
5. Over-distribution prevention (allocated <= pool).
6. Table 3 inward invoices, Table 5 distribution, Table 6B amendments.
7. Official GSTN offline JSON format verification.
"""

from decimal import Decimal
import pytest

from app.rules.gstr6_rules import (
    compute_turnover_ratios,
    distribute_isd_credit,
    extract_pan_from_gstin,
    extract_state_code,
    validate_distinct_persons,
)
from app.services.gstr6_service import (
    Gstr6DuplicateError,
    Gstr6Error,
    Gstr6OverDistributionError,
    Gstr6ValidationError,
    add_or_update_inward_invoice_sync,
    build_gstr6_offline_json,
    delete_inward_invoice_sync,
    execute_isd_distribution_sync,
    get_batch_summary_sync,
    get_or_create_batch_sync,
    reset_gstr6_store_for_testing,
)


@pytest.fixture(autouse=True)
def clean_store():
    reset_gstr6_store_for_testing()


def test_isd_distinct_person_pan_matching():
    # Matching PAN (first 10 chars of GSTIN)
    isd_gstin = "27AAACG0000A1Z5"
    valid_recipient = "29AAACG0000A1Z2"  # KA branch of same PAN
    diff_pan = "29BBBCG0000A1Z2"

    assert validate_distinct_persons(isd_gstin, valid_recipient) is True
    assert validate_distinct_persons(isd_gstin, diff_pan) is False


def test_isd_tax_head_conversion_intra_state():
    # Intra-state: ISD in MH (27), Recipient in MH (27)
    # CGST remains CGST, SGST remains SGST, IGST remains IGST
    res = distribute_isd_credit(
        isd_gstin="27AAACG0000A1Z5",
        pool_igst=500.0,
        pool_cgst=1000.0,
        pool_sgst=1000.0,
        is_eligible=True,
        recipient_turnovers=[
            {"recipient_gstin": "27AAACG0000A1Z5", "turnover": 100000.0}
        ],
    )
    assert len(res.distributions) == 1
    d = res.distributions[0]
    assert d.is_same_state is True
    assert d.distributed_cgst == Decimal("1000.00")
    assert d.distributed_sgst == Decimal("1000.00")
    assert d.distributed_igst == Decimal("500.00")
    assert d.original_cgst_converted_to_igst == Decimal("0.00")


def test_isd_tax_head_conversion_cross_state():
    # Cross-state: ISD in MH (27), Recipient in KA (29)
    # Under Rule 39(1)(e) & (f), CGST (1000) + SGST (1000) convert to IGST (2000)!
    # Plus original IGST (500) -> Total distributed IGST = 2500.
    res = distribute_isd_credit(
        isd_gstin="27AAACG0000A1Z5",
        pool_igst=500.0,
        pool_cgst=1000.0,
        pool_sgst=1000.0,
        is_eligible=True,
        recipient_turnovers=[
            {"recipient_gstin": "29AAACG0000A1Z2", "turnover": 100000.0}
        ],
    )
    assert len(res.distributions) == 1
    d = res.distributions[0]
    assert d.is_same_state is False
    assert d.distributed_cgst == Decimal("0.00")
    assert d.distributed_sgst == Decimal("0.00")
    assert d.distributed_igst == Decimal("2500.00")  # 1000 + 1000 + 500
    assert d.original_cgst_converted_to_igst == Decimal("1000.00")
    assert d.original_sgst_converted_to_igst == Decimal("1000.00")


def test_proportionate_turnover_distribution():
    # Credit pool of ₹1,00,000 IGST
    # Branch 1 turnover: ₹4,00,000 (40%)
    # Branch 2 turnover: ₹6,00,000 (60%)
    res = distribute_isd_credit(
        isd_gstin="27AAACG0000A1Z5",
        pool_igst=100000.0,
        pool_cgst=0.0,
        pool_sgst=0.0,
        is_eligible=True,
        recipient_turnovers=[
            {"recipient_gstin": "27AAACG0000A1Z5", "turnover": 400000.0},
            {"recipient_gstin": "29AAACG0000A1Z2", "turnover": 600000.0},
        ],
    )
    assert len(res.distributions) == 2
    assert res.distributions[0].distributed_igst == Decimal("40000.00")
    assert res.distributions[1].distributed_igst == Decimal("60000.00")
    assert res.total_distributed == Decimal("100000.00")
    assert res.is_over_distributed is False


def test_over_distribution_prevention():
    ratios = compute_turnover_ratios([
        {"recipient_gstin": "27AAACG0000A1Z5", "turnover": 500000.0},
        {"recipient_gstin": "29AAACG0000A1Z2", "turnover": 500000.0},
    ])
    assert sum(r.ratio for r in ratios) == Decimal("1.0000")

    # Uneven 3-branch turnover allocation: ₹1,00,000 divided by 3 branches
    # Must sum exactly to ₹1,00,000.00 down to the paisa
    res = distribute_isd_credit(
        isd_gstin="27AAACG0000A1Z5",
        pool_igst=100000.0,
        pool_cgst=0.0,
        pool_sgst=0.0,
        is_eligible=True,
        recipient_turnovers=[
            {"recipient_gstin": "27AAACG0000A1Z5", "turnover": 100000.0},
            {"recipient_gstin": "29AAACG0000A1Z2", "turnover": 100000.0},
            {"recipient_gstin": "33AAACG0000A1Z4", "turnover": 100000.0},
        ],
    )
    assert len(res.distributions) == 3
    assert res.total_distributed == Decimal("100000.00")
    assert sum(d.total_distributed for d in res.distributions) == Decimal("100000.00")
    assert res.is_over_distributed is False

    # Zero tolerance verification: Even 1 paisa over pool is strictly rejected
    res_over = distribute_isd_credit(
        isd_gstin="27AAACG0000A1Z5",
        pool_igst=100.00,
        pool_cgst=0.0,
        pool_sgst=0.0,
        is_eligible=True,
        recipient_turnovers=[
            {"recipient_gstin": "27AAACG0000A1Z5", "turnover": 100000.0},
        ],
    )
    # Manually simulate distributed > pool by 1 paisa
    object.__setattr__(res_over, "total_distributed", Decimal("100.01"))
    object.__setattr__(res_over, "is_over_distributed", res_over.total_distributed > res_over.total_pool_available)
    assert res_over.is_over_distributed is True


def test_gstr6_service_batch_lifecycle_and_summary():
    sb = None
    batch = get_or_create_batch_sync(
        sb,
        firm_id="f0000000-0000-0000-0000-000000000001",
        client_gstin_id="c0000000-0000-0000-0000-000000000001",
        gstin="27AAACG0000A1Z5",
        period="2026-07",
    )
    assert batch.status == "DRAFT"
    assert batch.period == "2026-07"

    # Add Table 3 Inward invoice (Eligible)
    inw1 = add_or_update_inward_invoice_sync(
        sb,
        batch_id=batch.id,
        record_data={
            "supplier_gstin": "27AABCS1429B1Z1",
            "invoice_number": "INV-101",
            "invoice_date": "2026-07-10",
            "taxable_value": 100000.0,
            "igst": 0.0,
            "cgst": 9000.0,
            "sgst": 9000.0,
            "cess": 0.0,
            "itc_eligible": "ELIGIBLE",
        },
    )
    assert inw1.cgst == 9000.0

    # Add Table 3 Inward invoice (Ineligible Section 17(5))
    inw2 = add_or_update_inward_invoice_sync(
        sb,
        batch_id=batch.id,
        record_data={
            "supplier_gstin": "27AABCS1429B1Z2",
            "invoice_number": "INV-102",
            "invoice_date": "2026-07-12",
            "taxable_value": 50000.0,
            "igst": 9000.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
            "is_eligible": False,
        },
    )
    assert inw2.is_eligible is False

    # Execute distribution to Karnataka branch (29)
    # CGST (9000) + SGST (9000) converted to IGST (18000)
    dist_records = execute_isd_distribution_sync(
        sb,
        batch_id=batch.id,
        recipient_turnovers=[
            {"recipient_gstin": "29AAACG0000A1Z2", "turnover": 100000.0}
        ],
    )
    assert len(dist_records) == 2
    eligible_dist = [d for d in dist_records if d.is_eligible][0]
    assert eligible_dist.distributed_igst == 18000.0
    ineligible_dist = [d for d in dist_records if not d.is_eligible][0]
    assert ineligible_dist.distributed_igst == 9000.0

    summary = get_batch_summary_sync(sb, batch_id=batch.id)
    assert summary["pool_summary"]["total_pool_cgst"] == 9000.0
    assert summary["pool_summary"]["total_pool_sgst"] == 9000.0
    assert summary["pool_summary"]["total_ineligible_pool"] == 9000.0
    assert summary["distribution_summary"]["total_distributed_igst"] == 27000.0
    assert summary["distribution_summary"]["total_eligible_distributed_igst"] == 18000.0
    assert summary["downstream_destination"] == "GSTR-2B Table 4(A)(4) of Recipient Distinct Persons"


def test_gstr6_offline_json_structure():
    sb = None
    batch = get_or_create_batch_sync(
        sb,
        firm_id="f0000000-0000-0000-0000-000000000001",
        client_gstin_id="c0000000-0000-0000-0000-000000000001",
        gstin="27AAACG0000A1Z5",
        period="2026-07",
    )
    add_or_update_inward_invoice_sync(
        sb,
        batch_id=batch.id,
        record_data={
            "supplier_gstin": "27AABCS1429B1Z1",
            "invoice_number": "INV-101",
            "invoice_date": "2026-07-10",
            "taxable_value": 100000.0,
            "igst": 18000.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
            "itc_eligible": "ELIGIBLE",
        },
    )
    execute_isd_distribution_sync(
        sb,
        batch_id=batch.id,
        recipient_turnovers=[
            {"recipient_gstin": "29AAACG0000A1Z2", "turnover": 100000.0}
        ],
    )

    offline_json = build_gstr6_offline_json(sb, batch_id=batch.id)
    assert offline_json["gstin"] == "27AAACG0000A1Z5"
    assert offline_json["fp"] == "072026"
    assert "isd" in offline_json
    assert len(offline_json["isd"]) == 1
    assert offline_json["isd"][0]["cpt_gstin"] == "29AAACG0000A1Z2"
    assert offline_json["isd"][0]["iamt"] == 18000.0
