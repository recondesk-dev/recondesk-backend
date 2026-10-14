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

from datetime import date, datetime
from decimal import Decimal
import pytest

from app.rules.gstr8_rules import (
    calculate_gstr8_mixed_period_tcs,
    calculate_gstr8_tcs,
    get_applicable_tcs_rates,
    normalize_transaction_date,
)
from app.services.pre_filing_validator import validate_gstr8_pre_filing
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

    # Transition period July 2024: requires transaction_date or verifiable rate basis; unverified is flagged for review:
    rate_july = get_applicable_tcs_rates("2024-07")
    assert rate_july.requires_review is True
    assert "UNRESOLVED_RATE_BASIS" in rate_july.notification_reference

    # Post-transition period (August 2024 onward): 0.5% total (Notification 15/2024-CT)
    rate_post = get_applicable_tcs_rates("2024-08")
    assert rate_post.total_rate_pct == Decimal("0.50")
    assert rate_post.cgst_rate == Decimal("0.0025")
    assert rate_post.sgst_rate == Decimal("0.0025")
    assert rate_post.igst_rate == Decimal("0.0050")
    assert "Notification No. 15/2024" in rate_post.notification_reference

    # July 2024 with post-cutoff transaction date (>= 10 July 2024): 0.5% total
    rate_post_july = get_applicable_tcs_rates("2024-07", transaction_date="2024-07-10")
    assert rate_post_july.total_rate_pct == Decimal("0.50")
    assert "Notification No. 15/2024" in rate_post_july.notification_reference

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


def test_statutory_tcs_rate_boundary_dates():
    """Verify 9 July (1.0%), 10 July (0.5%) and 11 July (0.5%) boundaries across tax heads."""
    # 1. 9 July 2024: 1.0% total (Notification 52/2018-CT)
    calc_9th_intra = calculate_gstr8_tcs(
        period="2024-07",
        gross_supplies=10000.00,
        returned_supplies=0.00,
        eco_state="27",
        pos="27",
        supplier_state="27",
        transaction_date="2024-07-09",
    )
    assert calc_9th_intra.rate_structure.total_rate_pct == Decimal("1.00")
    assert calc_9th_intra.tcs_cgst == Decimal("50.00")
    assert calc_9th_intra.tcs_sgst == Decimal("50.00")
    assert calc_9th_intra.tcs_igst == Decimal("0.00")
    assert calc_9th_intra.total_tcs == Decimal("100.00")

    calc_9th_inter = calculate_gstr8_tcs(
        period="2024-07",
        gross_supplies=10000.00,
        returned_supplies=0.00,
        eco_state="27",
        pos="29",
        supplier_state="27",
        transaction_date="2024-07-09",
    )
    assert calc_9th_inter.tcs_igst == Decimal("100.00")
    assert calc_9th_inter.total_tcs == Decimal("100.00")

    # 2. 10 July 2024: 0.5% total (Notification 15/2024-CT)
    calc_10th_intra = calculate_gstr8_tcs(
        period="2024-07",
        gross_supplies=10000.00,
        returned_supplies=0.00,
        eco_state="27",
        pos="27",
        supplier_state="27",
        transaction_date="2024-07-10",
    )
    assert calc_10th_intra.rate_structure.total_rate_pct == Decimal("0.50")
    assert calc_10th_intra.tcs_cgst == Decimal("25.00")
    assert calc_10th_intra.tcs_sgst == Decimal("25.00")
    assert calc_10th_intra.tcs_igst == Decimal("0.00")
    assert calc_10th_intra.total_tcs == Decimal("50.00")

    calc_10th_inter = calculate_gstr8_tcs(
        period="2024-07",
        gross_supplies=10000.00,
        returned_supplies=0.00,
        eco_state="27",
        pos="29",
        supplier_state="27",
        transaction_date="2024-07-10",
    )
    assert calc_10th_inter.tcs_igst == Decimal("50.00")
    assert calc_10th_inter.total_tcs == Decimal("50.00")

    # 3. 11 July 2024: 0.5% total (Notification 15/2024-CT)
    calc_11th_intra = calculate_gstr8_tcs(
        period="2024-07",
        gross_supplies=10000.00,
        returned_supplies=0.00,
        eco_state="27",
        pos="27",
        supplier_state="27",
        transaction_date="2024-07-11",
    )
    assert calc_11th_intra.rate_structure.total_rate_pct == Decimal("0.50")
    assert calc_11th_intra.tcs_cgst == Decimal("25.00")
    assert calc_11th_intra.tcs_sgst == Decimal("25.00")
    assert calc_11th_intra.total_tcs == Decimal("50.00")

    calc_11th_inter = calculate_gstr8_tcs(
        period="2024-07",
        gross_supplies=10000.00,
        returned_supplies=0.00,
        eco_state="27",
        pos="29",
        supplier_state="27",
        transaction_date="2024-07-11",
    )
    assert calc_11th_inter.tcs_igst == Decimal("50.00")
    assert calc_11th_inter.total_tcs == Decimal("50.00")


def test_mixed_rate_july_2024_return_batches():
    """Verify July 2024 batch containing transactions both before and after the 10 July cutoff."""
    firm_id = "f0000000-0000-0000-0000-000000000001"
    client_id = "c0000000-0000-0000-0000-000000000001"
    eco_gstin = "27AAACG0000A1Z5"
    period = "2024-07"

    batch = get_or_create_batch_sync(
        None,
        firm_id=firm_id,
        client_gstin_id=client_id,
        gstin=eco_gstin,
        period=period,
    )
    batch_id = batch["id"]

    # Line 1: Pre-cutoff (9 July 2024) @ 1.0% TCS rate (0.5% CGST + 0.5% SGST)
    rec1 = add_or_update_gstr8_record_sync(
        None,
        batch_id=batch_id,
        record_data={
            "supply_type": "B2B",
            "record_type": "ORIGINAL",
            "supplier_gstin": "27ABCDE1234F1Z5",
            "gross_supplies": 10000.00,
            "returned_supplies": 0.00,
            "pos": "27",
            "transaction_date": "2024-07-09",
        },
    )
    assert rec1["tcs_cgst"] == 50.00
    assert rec1["tcs_sgst"] == 50.00

    # Line 2: Cutoff day (10 July 2024) @ 0.5% TCS rate (0.25% CGST + 0.25% SGST)
    rec2 = add_or_update_gstr8_record_sync(
        None,
        batch_id=batch_id,
        record_data={
            "supply_type": "B2B",
            "record_type": "ORIGINAL",
            "supplier_gstin": "27ABCDE1234F1Z5",
            "gross_supplies": 20000.00,
            "returned_supplies": 0.00,
            "pos": "27",
            "transaction_date": "2024-07-10",
        },
    )
    assert rec2["tcs_cgst"] == 50.00
    assert rec2["tcs_sgst"] == 50.00

    # Line 3: Post-cutoff (11 July 2024) @ 0.5% TCS rate (0.25% CGST + 0.25% SGST)
    rec3 = add_or_update_gstr8_record_sync(
        None,
        batch_id=batch_id,
        record_data={
            "supply_type": "B2B",
            "record_type": "ORIGINAL",
            "supplier_gstin": "27ABCDE1234F1Z5",
            "gross_supplies": 15000.00,
            "returned_supplies": 0.00,
            "pos": "27",
            "transaction_date": "2024-07-11",
        },
    )
    assert rec3["tcs_cgst"] == 37.50
    assert rec3["tcs_sgst"] == 37.50

    # Verify batch aggregates:
    # Gross = 10000 + 20000 + 15000 = 45000
    # CGST = 50 + 50 + 37.50 = 137.50
    # SGST = 50 + 50 + 37.50 = 137.50
    # Total TCS = 275.00
    summ = get_batch_summary_sync(None, batch_id=batch_id)
    assert summ["batch"]["gross_supplies_value"] == 45000.00
    assert summ["batch"]["net_taxable_value"] == 45000.00
    assert summ["batch"]["total_tcs_cgst"] == 137.50
    assert summ["batch"]["total_tcs_sgst"] == 137.50
    assert summ["total_tcs_liability"] == 275.00

    # Verify offline JSON aggregation per supplier GSTIN:
    offline = build_gstr8_offline_json(None, batch_id=batch_id)
    assert len(offline["tcs"]) == 1
    tcs_row = offline["tcs"][0]
    assert tcs_row["gstin_supp"] == "27ABCDE1234F1Z5"
    assert tcs_row["gross_val"] == 45000.00
    assert tcs_row["net_val"] == 45000.00
    assert tcs_row["camt"] == 137.50
    assert tcs_row["samt"] == 137.50


def test_mixed_rate_helper_and_rounding():
    """Verify calculate_gstr8_mixed_period_tcs helper with half-up rounding precision."""
    res = calculate_gstr8_mixed_period_tcs(
        period="2024-07",
        pre_cutoff_gross=10003.33,
        pre_cutoff_returned=3.33,  # Net 10,000.00 @ 1.0% -> CGST 50.00, SGST 50.00
        post_cutoff_gross=20005.55,
        post_cutoff_returned=5.55,  # Net 20,000.00 @ 0.5% -> CGST 50.00, SGST 50.00
        eco_state="27",
        pos="27",
    )
    assert res["total_gross"] == Decimal("30008.88")
    assert res["total_returned"] == Decimal("8.88")
    assert res["total_net"] == Decimal("30000.00")
    assert res["total_tcs_cgst"] == Decimal("100.00")
    assert res["total_tcs_sgst"] == Decimal("100.00")
    assert res["total_tcs"] == Decimal("200.00")
    assert res["effective_blended_rate_pct"] == Decimal("0.6667")  # 200 / 30000 * 100


def test_transaction_date_strict_normalization():
    """Verify strict date normalization rules: accept standard formats, reject invalid/ambiguous."""
    # Standard ISO format
    assert normalize_transaction_date("2024-07-09") == "2024-07-09"
    assert normalize_transaction_date("2024-07-10T15:30:00Z") == "2024-07-10"
    assert normalize_transaction_date("2024-07-11 09:00:00") == "2024-07-11"

    # Hyphenated Indian format DD-MM-YYYY
    assert normalize_transaction_date("09-07-2024") == "2024-07-09"
    assert normalize_transaction_date("10-07-2024") == "2024-07-10"

    # Python date and datetime instances
    assert normalize_transaction_date(date(2024, 7, 9)) == "2024-07-09"
    assert normalize_transaction_date(datetime(2024, 7, 10, 18, 0, 0)) == "2024-07-10"

    # Rejection of ambiguous slash formats
    with pytest.raises(ValueError, match="Ambiguous date format with slashes"):
        normalize_transaction_date("07/08/2024", strict=True)

    with pytest.raises(ValueError, match="Ambiguous date format with slashes"):
        normalize_transaction_date("2024/07/09", strict=True)

    # Rejection of invalid calendar dates
    with pytest.raises(ValueError, match="Invalid calendar date"):
        normalize_transaction_date("2024-02-30", strict=True)

    with pytest.raises(ValueError, match="Invalid calendar date"):
        normalize_transaction_date("31-04-2024", strict=True)

    # Non-date strings
    with pytest.raises(ValueError, match="Invalid transaction date format"):
        normalize_transaction_date("invalid-date-string", strict=True)

    # None and empty strings
    assert normalize_transaction_date(None) is None
    assert normalize_transaction_date("") is None
    assert normalize_transaction_date("   ") is None


def test_july_2024_unresolved_rate_basis_flagged_and_blocks_export():
    """For July 2024: records lacking transaction_date or rate_basis must be flagged for review,
    surface in summary exceptions, fail pre-filing validation, and block offline JSON generation.
    """
    firm_id = "f0000000-0000-0000-0000-000000000001"
    client_id = "c0000000-0000-0000-0000-000000000001"
    eco_gstin = "27AAACG0000A1Z5"
    period = "2024-07"

    batch = get_or_create_batch_sync(
        None,
        firm_id=firm_id,
        client_gstin_id=client_id,
        gstin=eco_gstin,
        period=period,
    )
    batch_id = batch["id"]

    # 1. Add July 2024 record WITHOUT transaction_date and WITHOUT rate_basis
    rec = add_or_update_gstr8_record_sync(
        None,
        batch_id=batch_id,
        record_data={
            "supply_type": "B2B",
            "record_type": "ORIGINAL",
            "supplier_gstin": "27ABCDE1234F1Z5",
            "gross_supplies": 50000.00,
            "returned_supplies": 0.00,
            "pos": "27",
        },
    )

    # Record must be flagged
    assert rec["needs_review"] is True
    assert "July 2024 transition record missing transaction_date" in rec["review_reason"]

    # 2. Summary must report MISSING_RATE_BASIS_JULY_2024 exception
    summary = get_batch_summary_sync(None, batch_id=batch_id)
    review_exceptions = [e for e in summary["exceptions"] if e["category"] == "MISSING_RATE_BASIS_JULY_2024"]
    assert len(review_exceptions) == 1
    assert review_exceptions[0]["record_id"] == rec["id"]

    # 3. Pre-filing validation must flag critical error G8_MISSING_RATE_BASIS_JULY_2024
    val = validate_gstr8_pre_filing(
        gstin=eco_gstin,
        period=period,
        batch=summary["batch"],
        records=[rec],
    )
    assert val.is_valid is False
    assert val.has_critical_violations is True
    assert val.statutory_checks["statutory_tcs_rate"] == "FAILED"
    critical_codes = [v.code for v in val.violations if v.severity.value == "CRITICAL_ERROR"]
    assert "G8_MISSING_RATE_BASIS_JULY_2024" in critical_codes

    # 4. Offline JSON generation must be BLOCKED
    with pytest.raises(Gstr8ValidationError, match="requires review for July 2024 rate determination"):
        build_gstr8_offline_json(None, batch_id=batch_id)


def test_july_2024_unresolved_record_cleared_by_verifiable_basis_or_date():
    """Unresolved July 2024 records can be resolved by providing a verifiable rate_basis
    or exact transaction_date, clearing review flags and permitting offline JSON export.
    """
    firm_id = "f0000000-0000-0000-0000-000000000001"
    client_id = "c0000000-0000-0000-0000-000000000001"
    eco_gstin = "27AAACG0000A1Z5"
    period = "2024-07"

    batch = get_or_create_batch_sync(
        None,
        firm_id=firm_id,
        client_gstin_id=client_id,
        gstin=eco_gstin,
        period=period,
    )
    batch_id = batch["id"]

    # Add initial unverified record
    rec_init = add_or_update_gstr8_record_sync(
        None,
        batch_id=batch_id,
        record_data={
            "supply_type": "B2B",
            "record_type": "ORIGINAL",
            "supplier_gstin": "27ABCDE1234F1Z5",
            "gross_supplies": 100000.00,
            "returned_supplies": 0.00,
            "pos": "27",
        },
    )
    assert rec_init["needs_review"] is True

    # Resolve with verifiable rate_basis="PRE_CUTOFF" (1.0% statutory rate)
    rec_pre = add_or_update_gstr8_record_sync(
        None,
        batch_id=batch_id,
        record_data={
            "id": rec_init["id"],
            "supply_type": "B2B",
            "record_type": "ORIGINAL",
            "supplier_gstin": "27ABCDE1234F1Z5",
            "gross_supplies": 100000.00,
            "returned_supplies": 0.00,
            "pos": "27",
            "rate_basis": "PRE_CUTOFF",
        },
    )
    assert rec_pre["needs_review"] is False
    assert rec_pre["tcs_rate"] == 1.00
    assert rec_pre["tcs_cgst"] == 500.00
    assert rec_pre["tcs_sgst"] == 500.00

    # Summary should now have 0 review exceptions
    summ_pre = get_batch_summary_sync(None, batch_id=batch_id)
    assert not any(e["category"] == "MISSING_RATE_BASIS_JULY_2024" for e in summ_pre["exceptions"])

    # Pre-filing validation passes
    val_pre = validate_gstr8_pre_filing(
        gstin=eco_gstin,
        period=period,
        batch=summ_pre["batch"],
        records=[rec_pre],
    )
    assert val_pre.is_valid is True

    # Offline JSON succeeds with 1.0% tax
    json_pre = build_gstr8_offline_json(None, batch_id=batch_id)
    assert json_pre["tcs"][0]["camt"] == 500.00
    assert json_pre["tcs"][0]["samt"] == 500.00

    # Now re-update with exact post-cutoff transaction date (15-Jul-2024 -> 0.5% rate)
    rec_post = add_or_update_gstr8_record_sync(
        None,
        batch_id=batch_id,
        record_data={
            "id": rec_init["id"],
            "supply_type": "B2B",
            "record_type": "ORIGINAL",
            "supplier_gstin": "27ABCDE1234F1Z5",
            "gross_supplies": 100000.00,
            "returned_supplies": 0.00,
            "pos": "27",
            "transaction_date": "2024-07-15",
        },
    )
    assert rec_post["needs_review"] is False
    assert rec_post["tcs_rate"] == 0.50
    assert rec_post["tcs_cgst"] == 250.00
    assert rec_post["tcs_sgst"] == 250.00

    json_post = build_gstr8_offline_json(None, batch_id=batch_id)
    assert json_post["tcs"][0]["camt"] == 250.00
    assert json_post["tcs"][0]["samt"] == 250.00


def test_transaction_date_persistence_and_multi_date_duplicate_handling():
    """Verify transaction_date survives create, update, and retrieval, and permits
    multiple transaction lines for the same supplier on distinct dates while rejecting same-date duplicates.
    """
    firm_id = "f0000000-0000-0000-0000-000000000001"
    client_id = "c0000000-0000-0000-0000-000000000001"
    eco_gstin = "27AAACG0000A1Z5"
    period = "2024-07"

    batch = get_or_create_batch_sync(
        None,
        firm_id=firm_id,
        client_gstin_id=client_id,
        gstin=eco_gstin,
        period=period,
    )
    batch_id = batch["id"]

    # 1. Add record with transaction_date = "2024-07-05"
    rec1 = add_or_update_gstr8_record_sync(
        None,
        batch_id=batch_id,
        record_data={
            "supply_type": "B2B",
            "record_type": "ORIGINAL",
            "supplier_gstin": "27ABCDE1234F1Z5",
            "gross_supplies": 10000.00,
            "returned_supplies": 0.00,
            "pos": "27",
            "transaction_date": "2024-07-05",
        },
    )
    assert rec1["transaction_date"] == "2024-07-05"

    # 2. Update record 1 to new date "2024-07-06"
    rec1_updated = add_or_update_gstr8_record_sync(
        None,
        batch_id=batch_id,
        record_data={
            "id": rec1["id"],
            "supply_type": "B2B",
            "record_type": "ORIGINAL",
            "supplier_gstin": "27ABCDE1234F1Z5",
            "gross_supplies": 15000.00,
            "returned_supplies": 0.00,
            "pos": "27",
            "transaction_date": "2024-07-06",
        },
    )
    assert rec1_updated["transaction_date"] == "2024-07-06"
    assert rec1_updated["gross_supplies"] == 15000.00

    # 3. Add second record for the same supplier on a different date ("2024-07-15")
    rec2 = add_or_update_gstr8_record_sync(
        None,
        batch_id=batch_id,
        record_data={
            "supply_type": "B2B",
            "record_type": "ORIGINAL",
            "supplier_gstin": "27ABCDE1234F1Z5",
            "gross_supplies": 25000.00,
            "returned_supplies": 0.00,
            "pos": "27",
            "transaction_date": "2024-07-15",
        },
    )
    assert rec2["transaction_date"] == "2024-07-15"

    # 4. Attempt to add third record for the same supplier on the SAME date ("2024-07-15") -> DuplicateError
    with pytest.raises(Gstr8DuplicateError, match="Duplicate B2B record"):
        add_or_update_gstr8_record_sync(
            None,
            batch_id=batch_id,
            record_data={
                "supply_type": "B2B",
                "record_type": "ORIGINAL",
                "supplier_gstin": "27ABCDE1234F1Z5",
                "gross_supplies": 5000.00,
                "returned_supplies": 0.00,
                "pos": "27",
                "transaction_date": "2024-07-15",
            },
        )

    # 5. Verify batch summary and offline JSON aggregation
    summ = get_batch_summary_sync(None, batch_id=batch_id)
    assert len(summ["table3_b2b"]) == 2
    assert summ["batch"]["gross_supplies_value"] == 40000.00

    # Offline JSON aggregates across both dates for this single supplier
    offline = build_gstr8_offline_json(None, batch_id=batch_id)
    assert len(offline["tcs"]) == 1
    assert offline["tcs"][0]["gstin_supp"] == "27ABCDE1234F1Z5"
    assert offline["tcs"][0]["gross_val"] == 40000.00


