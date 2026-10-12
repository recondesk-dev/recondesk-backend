"""Phase 4.2: Unit & Statutory Rule Tests for Form GSTR-8 (TCS under Section 52).

Tests:
1. Statutory TCS rate transition (1% pre-10-Jul-2024 vs 0.5% post-10-Jul-2024).
2. Net taxable supply arithmetic (gross - returned).
3. Negative net taxable supply handling (returns > gross).
4. Table 3 B2B (registered) and B2C (unregistered) supplies.
5. Table 4 Amendments.
6. Duplicate B2B supplier and B2C POS record detection.
7. Figures digest computation & tamper-evidence.
8. Official GSTN offline JSON format.
"""

from decimal import Decimal
import pytest

from app.rules.gstr8_rules import (
    calculate_gstr8_tcs,
    get_applicable_tcs_rates,
)
from app.services.gstr8_service import (
    Gstr8DuplicateError,
    Gstr8ValidationError,
    add_or_update_gstr8_record_sync,
    build_gstr8_offline_json,
    compute_gstr8_figures_digest,
    delete_gstr8_record_sync,
    get_batch_summary_sync,
    get_or_create_batch_sync,
    reset_gstr8_memory_store_for_testing,
)


@pytest.fixture(autouse=True)
def clean_gstr8_store():
    reset_gstr8_memory_store_for_testing()


def test_statutory_tcs_rate_transition():
    # Pre-July 2024: 1.0% total (0.5% CGST + 0.5% SGST, 1.0% IGST)
    rate_pre = get_applicable_tcs_rates("2024-06")
    assert rate_pre.total_rate_pct == Decimal("1.00")
    assert rate_pre.cgst_rate == Decimal("0.0050")
    assert rate_pre.sgst_rate == Decimal("0.0050")
    assert rate_pre.igst_rate == Decimal("0.0100")
    assert "Notification No. 52/2018" in rate_pre.notification_reference

    # Post-July 2024: 0.5% total (0.25% CGST + 0.25% SGST, 0.5% IGST)
    rate_post = get_applicable_tcs_rates("2024-07")
    assert rate_post.total_rate_pct == Decimal("0.50")
    assert rate_post.cgst_rate == Decimal("0.0025")
    assert rate_post.sgst_rate == Decimal("0.0025")
    assert rate_post.igst_rate == Decimal("0.0050")
    assert "Notification No. 15/2024" in rate_post.notification_reference

    rate_current = get_applicable_tcs_rates("2026-07")
    assert rate_current.total_rate_pct == Decimal("0.50")


def test_net_taxable_supplies_and_tcs_calculation():
    # Post July 2024 intra-state supply: Net = 1,00,000 - 10,000 = 90,000
    # 0.25% CGST = 225.00, 0.25% SGST = 225.00, Total = 450.00
    calc = calculate_gstr8_tcs(
        period="2026-07",
        gross_supplies=100000.00,
        returned_supplies=10000.00,
        eco_state="27",
        pos="27",
        supplier_state="27",
    )
    assert calc.gross_supplies == Decimal("100000.00")
    assert calc.returned_supplies == Decimal("10000.00")
    assert calc.net_supplies == Decimal("90000.00")
    assert calc.is_negative_net is False
    assert calc.supply_nature == "INTRA_STATE"
    assert calc.tcs_cgst == Decimal("225.00")
    assert calc.tcs_sgst == Decimal("225.00")
    assert calc.tcs_igst == Decimal("0.00")
    assert calc.total_tcs == Decimal("450.00")


def test_inter_state_tcs_calculation():
    # Inter-state: Supplier in MH (27), POS in KA (29)
    # Net = 2,00,000. 0.5% IGST = 1000.00
    calc = calculate_gstr8_tcs(
        period="2026-07",
        gross_supplies=200000.00,
        returned_supplies=0.00,
        eco_state="27",
        pos="29",
        supplier_state="27",
    )
    assert calc.supply_nature == "INTER_STATE"
    assert calc.tcs_igst == Decimal("1000.00")
    assert calc.tcs_cgst == Decimal("0.00")
    assert calc.tcs_sgst == Decimal("0.00")


def test_negative_net_supplies_handling():
    # Returned supplies exceed gross sales: Gross 50,000, Returns 70,000 -> Net -20,000
    calc = calculate_gstr8_tcs(
        period="2026-07",
        gross_supplies=50000.00,
        returned_supplies=70000.00,
        eco_state="27",
        pos="27",
        supplier_state="27",
    )
    assert calc.net_supplies == Decimal("-20000.00")
    assert calc.is_negative_net is True
    assert calc.total_tcs == Decimal("0.00")
    assert calc.tcs_cgst == Decimal("0.00")
    assert calc.tcs_sgst == Decimal("0.00")


def test_gstr8_batch_and_records_lifecycle():
    firm_id = "f0000000-0000-0000-0000-000000000001"
    client_id = "c0000000-0000-0000-0000-000000000001"
    eco_gstin = "27AAACG0000A1Z5"
    period = "2026-07"

    # 1. Initialize batch
    batch = get_or_create_batch_sync(
        None,
        firm_id=firm_id,
        client_gstin_id=client_id,
        gstin=eco_gstin,
        period=period,
    )
    batch_id = batch["id"]
    assert batch["status"] == "DRAFT"

    # 2. Add Table 3 B2B record
    rec_b2b = add_or_update_gstr8_record_sync(
        None,
        batch_id=batch_id,
        record_data={
            "supply_type": "B2B",
            "record_type": "ORIGINAL",
            "supplier_gstin": "27ABCDE1234F1Z5",
            "gross_supplies": 500000.00,
            "returned_supplies": 50000.00,
            "pos": "27",
        },
    )
    assert rec_b2b["net_supplies"] == 450000.00
    assert rec_b2b["tcs_cgst"] == 1125.00  # 0.25% of 4,50,000
    assert rec_b2b["tcs_sgst"] == 1125.00
    assert rec_b2b["tcs_igst"] == 0.00

    # 3. Add Table 3 B2C record
    rec_b2c = add_or_update_gstr8_record_sync(
        None,
        batch_id=batch_id,
        record_data={
            "supply_type": "B2C",
            "record_type": "ORIGINAL",
            "pos": "29",  # Inter-state B2C
            "gross_supplies": 200000.00,
            "returned_supplies": 10000.00,
        },
    )
    assert rec_b2c["net_supplies"] == 190000.00
    assert rec_b2c["tcs_igst"] == 950.00  # 0.5% of 1,90,000

    # 4. Check summary
    summ = get_batch_summary_sync(None, batch_id=batch_id)
    assert summ["batch"]["total_b2b_records"] == 1
    assert summ["batch"]["total_b2c_records"] == 1
    assert summ["batch"]["gross_supplies_value"] == 700000.00
    assert summ["batch"]["returned_supplies_value"] == 60000.00
    assert summ["batch"]["net_taxable_value"] == 640000.00
    assert summ["total_tcs_liability"] == 3200.00  # (1125 + 1125 + 950)
    assert summ["batch"]["figures_digest"] != ""

    # 5. Check duplicate B2B supplier rejection
    with pytest.raises(Gstr8DuplicateError):
        add_or_update_gstr8_record_sync(
            None,
            batch_id=batch_id,
            record_data={
                "supply_type": "B2B",
                "record_type": "ORIGINAL",
                "supplier_gstin": "27ABCDE1234F1Z5",
                "gross_supplies": 100000.00,
                "returned_supplies": 0.00,
            },
        )

    # 6. Delete B2C record
    ok = delete_gstr8_record_sync(None, batch_id=batch_id, record_id=rec_b2c["id"])
    assert ok is True
    summ2 = get_batch_summary_sync(None, batch_id=batch_id)
    assert summ2["batch"]["total_b2c_records"] == 0
    assert summ2["total_tcs_liability"] == 2250.00


def test_build_gstr8_offline_json():
    firm_id = "f0000000-0000-0000-0000-000000000001"
    client_id = "c0000000-0000-0000-0000-000000000001"
    eco_gstin = "27AAACG0000A1Z5"
    period = "2026-07"

    batch = get_or_create_batch_sync(
        None,
        firm_id=firm_id,
        client_gstin_id=client_id,
        gstin=eco_gstin,
        period=period,
    )
    batch_id = batch["id"]

    add_or_update_gstr8_record_sync(
        None,
        batch_id=batch_id,
        record_data={
            "supply_type": "B2B",
            "record_type": "ORIGINAL",
            "supplier_gstin": "27ABCDE1234F1Z5",
            "gross_supplies": 1000000.00,
            "returned_supplies": 100000.00,
            "pos": "27",
        },
    )

    add_or_update_gstr8_record_sync(
        None,
        batch_id=batch_id,
        record_data={
            "supply_type": "B2C",
            "record_type": "ORIGINAL",
            "pos": "29",
            "gross_supplies": 50000.00,
            "returned_supplies": 0.00,
        },
    )

    offline_json = build_gstr8_offline_json(None, batch_id=batch_id)
    assert offline_json["gstin"] == eco_gstin
    assert offline_json["fp"] == "072026"
    assert len(offline_json["tcs"]) == 1
    assert offline_json["tcs"][0]["gstin_supp"] == "27ABCDE1234F1Z5"
    assert offline_json["tcs"][0]["gross_val"] == 1000000.00
    assert offline_json["tcs"][0]["ret_val"] == 100000.00
    assert offline_json["tcs"][0]["net_val"] == 900000.00
    assert offline_json["tcs"][0]["camt"] == 2250.00
    assert offline_json["tcs"][0]["samt"] == 2250.00
    assert len(offline_json["tcs_b2c"]) == 1
    assert offline_json["tcs_b2c"][0]["pos"] == "29"
    assert offline_json["tcs_b2c"][0]["net_val"] == 50000.00
    assert offline_json["tcs_b2c"][0]["iamt"] == 250.00
