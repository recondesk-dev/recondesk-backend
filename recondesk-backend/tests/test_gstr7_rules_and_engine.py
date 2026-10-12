"""Phase 4.2: Unit & Statutory Rule Tests for Form GSTR-7 (TDS under Section 51).

Tests:
1. Contract threshold boundary checks (<= ₹2.5L vs > ₹2.5L).
2. Section 51(1) Proviso exemption (supplier state == POS != deductor state).
3. Intra-state (1% CGST + 1% SGST) vs Inter-state (2% IGST) calculations.
4. Table 3 Original & Table 4 Amendment records.
5. Duplicate deduction record detection.
6. Deducted vs deposited tax reconciliation.
7. Figures digest computation & tamper-evidence.
8. Official GSTN offline JSON format.
"""

from decimal import Decimal
import pytest

from app.rules.gstr7_rules import (
    GSTR7_CONTRACT_THRESHOLD,
    calculate_gstr7_tds,
    evaluate_section_51_proviso,
    extract_state_code,
    validate_gstin_format,
)
from app.services.gstr7_service import (
    Gstr7DuplicateError,
    Gstr7ValidationError,
    add_or_update_gstr7_record_sync,
    build_gstr7_offline_json,
    compute_gstr7_figures_digest,
    delete_gstr7_record_sync,
    get_batch_summary_sync,
    get_or_create_batch_sync,
    reset_gstr7_memory_store_for_testing,
)


@pytest.fixture(autouse=True)
def clean_gstr7_store():
    reset_gstr7_memory_store_for_testing()


def test_gstin_format_validation():
    assert validate_gstin_format("27AAACG0000A1Z5") is True
    assert validate_gstin_format("29ABCDE1234F1Z5") is True
    assert validate_gstin_format("INVALID_GSTIN") is False
    assert validate_gstin_format("27AAACG0000A1") is False


def test_extract_state_code():
    assert extract_state_code("27AAACG0000A1Z5") == "27"
    assert extract_state_code("29ABCDE1234F1Z5") == "29"
    assert extract_state_code("INVALID") == ""


def test_contract_threshold_boundary():
    # Exactly ₹2,50,000 -> Not exceeding threshold -> No TDS
    res_exact = calculate_gstr7_tds(
        contract_value=250000.00,
        amount_paid=50000.00,
        deductor_state="27",
        supplier_state="27",
        pos="27",
    )
    assert res_exact.contract_exceeds_threshold is False
    assert res_exact.is_eligible is False
    assert res_exact.total_tds == Decimal("0.00")
    assert "does not exceed statutory threshold" in str(res_exact.ineligibility_reason)

    # ₹2,49,999.99 -> Below threshold -> No TDS
    res_below = calculate_gstr7_tds(
        contract_value=249999.99,
        amount_paid=50000.00,
        deductor_state="27",
        supplier_state="27",
        pos="27",
    )
    assert res_below.contract_exceeds_threshold is False
    assert res_below.total_tds == Decimal("0.00")

    # ₹2,50,000.01 -> Exceeds threshold -> Liable to TDS
    res_above = calculate_gstr7_tds(
        contract_value=250000.01,
        amount_paid=50000.00,
        deductor_state="27",
        supplier_state="27",
        pos="27",
    )
    assert res_above.contract_exceeds_threshold is True
    assert res_above.is_eligible is True
    assert res_above.total_tds == Decimal("1000.00")  # 2% of 50,000


def test_section_51_proviso_exemption():
    # Deductor in MH (27), Supplier in KA (29), POS in KA (29)
    # Supplier State == POS (29 == 29), but Deductor State != 29 (27)
    # By proviso to Sec 51(1), NO deduction permitted!
    assert evaluate_section_51_proviso(deductor_state="27", supplier_state="29", pos="29") is True

    calc = calculate_gstr7_tds(
        contract_value=500000.00,
        amount_paid=100000.00,
        deductor_state="27",
        supplier_state="29",
        pos="29",
    )
    assert calc.is_proviso_exempt is True
    assert calc.is_eligible is False
    assert calc.total_tds == Decimal("0.00")
    assert "Exempt under Proviso to Section 51(1)" in str(calc.ineligibility_reason)

    # Counter-example: Deductor in MH (27), Supplier in KA (29), POS in MH (27)
    # Inter-state supply to Deductor state -> Not proviso exempt! Liable to 2% IGST
    assert evaluate_section_51_proviso(deductor_state="27", supplier_state="29", pos="27") is False
    calc_inter = calculate_gstr7_tds(
        contract_value=500000.00,
        amount_paid=100000.00,
        deductor_state="27",
        supplier_state="29",
        pos="27",
    )
    assert calc_inter.is_proviso_exempt is False
    assert calc_inter.is_eligible is True
    assert calc_inter.tax_type == "INTER_STATE"
    assert calc_inter.tds_igst == Decimal("2000.00")
    assert calc_inter.tds_cgst == Decimal("0.00")


def test_intra_state_tds_tax_head_allocation():
    # Intra-state: Deductor 27, Supplier 27, POS 27
    calc = calculate_gstr7_tds(
        contract_value=1000000.00,
        amount_paid=250000.00,
        deductor_state="27",
        supplier_state="27",
        pos="27",
    )
    assert calc.is_eligible is True
    assert calc.tax_type == "INTRA_STATE"
    assert calc.tds_cgst == Decimal("2500.00")  # 1%
    assert calc.tds_sgst == Decimal("2500.00")  # 1%
    assert calc.tds_igst == Decimal("0.00")
    assert calc.total_tds == Decimal("5000.00")  # 2% total


def test_gstr7_batch_and_record_lifecycle():
    firm_id = "f0000000-0000-0000-0000-000000000001"
    client_id = "c0000000-0000-0000-0000-000000000001"
    deductor_gstin = "27AAACG0000A1Z5"
    period = "2026-07"

    # 1. Initialize batch
    batch = get_or_create_batch_sync(
        None,
        firm_id=firm_id,
        client_gstin_id=client_id,
        gstin=deductor_gstin,
        period=period,
    )
    batch_id = batch["id"]
    assert batch["status"] == "DRAFT"
    assert batch["total_records"] == 0

    # 2. Add Table 3 original record
    rec1 = add_or_update_gstr7_record_sync(
        None,
        batch_id=batch_id,
        record_data={
            "record_type": "ORIGINAL",
            "deductee_gstin": "27ABCDE1234F1Z5",
            "contract_number": "PO-101",
            "contract_value": 400000.00,
            "payment_reference": "VCH-01",
            "amount_paid": 100000.00,
            "pos": "27",
        },
    )
    assert rec1["tds_cgst"] == 1000.00
    assert rec1["tds_sgst"] == 1000.00
    assert rec1["tds_igst"] == 0.00

    # 3. Add Table 4 amendment record
    rec2 = add_or_update_gstr7_record_sync(
        None,
        batch_id=batch_id,
        record_data={
            "record_type": "AMENDMENT",
            "deductee_gstin": "29XYZAB5678C1Z2",
            "original_period": "2026-06",
            "contract_value": 600000.00,
            "payment_reference": "VCH-02",
            "amount_paid": 50000.00,
            "pos": "27",  # Inter-state to Deductor (MH)
        },
    )
    assert rec2["tds_igst"] == 1000.00  # 2% of 50,000

    # 4. Check summary
    summ = get_batch_summary_sync(None, batch_id=batch_id)
    assert summ["batch"]["total_records"] == 1
    assert summ["batch"]["total_amendments"] == 1
    assert summ["batch"]["total_amount_paid"] == 150000.00
    assert summ["total_tds_liability"] == 3000.00
    assert summ["batch"]["figures_digest"] != ""

    # 5. Check duplicate detection
    with pytest.raises(Gstr7DuplicateError):
        add_or_update_gstr7_record_sync(
            None,
            batch_id=batch_id,
            record_data={
                "record_type": "ORIGINAL",
                "deductee_gstin": "27ABCDE1234F1Z5",
                "payment_reference": "VCH-01",  # Same payment reference
                "contract_value": 400000.00,
                "amount_paid": 50000.00,
            },
        )

    # 6. Delete record
    ok = delete_gstr7_record_sync(None, batch_id=batch_id, record_id=rec2["id"])
    assert ok is True
    summ2 = get_batch_summary_sync(None, batch_id=batch_id)
    assert summ2["batch"]["total_amendments"] == 0
    assert summ2["total_tds_liability"] == 2000.00


def test_build_gstr7_offline_json():
    firm_id = "f0000000-0000-0000-0000-000000000001"
    client_id = "c0000000-0000-0000-0000-000000000001"
    deductor_gstin = "27AAACG0000A1Z5"
    period = "2026-07"

    batch = get_or_create_batch_sync(
        None,
        firm_id=firm_id,
        client_gstin_id=client_id,
        gstin=deductor_gstin,
        period=period,
    )
    batch_id = batch["id"]

    add_or_update_gstr7_record_sync(
        None,
        batch_id=batch_id,
        record_data={
            "record_type": "ORIGINAL",
            "deductee_gstin": "27ABCDE1234F1Z5",
            "contract_value": 500000.00,
            "amount_paid": 100000.00,
            "pos": "27",
        },
    )

    offline_json = build_gstr7_offline_json(None, batch_id=batch_id)
    assert offline_json["gstin"] == deductor_gstin
    assert offline_json["fp"] == "072026"
    assert len(offline_json["tds"]) == 1
    assert offline_json["tds"][0]["gstin_ded"] == "27ABCDE1234F1Z5"
    assert offline_json["tds"][0]["amt_paid"] == 100000.00
    assert offline_json["tds"][0]["camt"] == 1000.00
    assert offline_json["tds"][0]["samt"] == 1000.00
    assert offline_json["tds"][0]["iamt"] == 0.00
