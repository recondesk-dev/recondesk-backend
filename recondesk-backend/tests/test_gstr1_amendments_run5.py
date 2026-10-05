"""Tests for GSTR-1 amendments engine, duplicate chains, wrong links, and Run 5 benchmark.

Covers:
1. B2BA value amendment (+10k delta)
2. B2BA date amendment
3. B2BA invoice number amendment
4. Wrong original link (AMENDMENT_ORIGINAL_NOT_FOUND)
5. Duplicate amendment chain (latest effective, 1 source accounted, warning emitted)
6. CDNA Credit Note (ont_num link, CN sign handling)
7. CDNA Debit Note (ont_num link, DN sign handling)
8. Wrong CDNA original (Review Required)
9. Late August filed September (matched as B2B, late warning)
10. Amendment delta aggregation increase (+10k)
11. Amendment delta aggregation decrease (-10k)
12. CN amendment delta
13. Duplicate amendment aggregation (+15k effective)
14. Run 5 headline counts
15. Run 5 tie-out (₹12,500 taxable only)
"""

import pytest
from app.matching.generic_matcher import match_sales_register_to_gstr1
from app.models.canonical_amendment import CanonicalAmendment
from app.routers.gstr1_reconcile import _run_pipeline
from app.services.gstr1_amendment_engine import (
    build_canonical_amendment,
    process_gstr1_amendments,
    resolve_amendment_original,
)


# ---------------------------------------------------------------------------
# Unit Tests for Amendment Scenarios (Tests 1 - 13)
# ---------------------------------------------------------------------------

def test_1_b2ba_value_amendment():
    """Test 1: B2BA value amendment (+10,000 delta)."""
    original_sr = {
        "invoice_number": "INV-100",
        "invoice_date": "2026-08-15",
        "gstin": "27TESTG1234A1Z5",
        "taxable_amount": 50000.0,
        "total_tax": 9000.0,
        "cgst": 4500.0,
        "sgst": 4500.0,
        "igst": 0.0,
        "invoice_type": "B2B",
    }
    amendment_record = {
        "invoice_number": "INV-100",
        "invoice_date": "2026-08-15",
        "oinum": "INV-100",
        "oidt": "15-08-2026",
        "gstin": "27TESTG1234A1Z5",
        "taxable_amount": 60000.0,
        "total_tax": 10800.0,
        "cgst": 5400.0,
        "sgst": 5400.0,
        "igst": 0.0,
        "invoice_type": "B2BA",
    }

    canon = build_canonical_amendment(
        amendment_rec=amendment_record,
        original_rec=original_sr,
        original_source="SALES_REGISTER",
        filing_period="092026",
    )

    assert canon.original_found is True
    assert canon.amended_taxable == 60000.0
    assert canon.original_taxable == 50000.0
    assert canon.delta_taxable == 10000.0
    assert canon.delta_cgst == 900.0
    assert canon.delta_sgst == 900.0


def test_2_b2ba_date_amendment():
    """Test 2: B2BA date amendment."""
    original_sr = {
        "invoice_number": "INV-101",
        "invoice_date": "2026-08-10",
        "gstin": "27TESTG1234A1Z5",
        "taxable_amount": 25000.0,
        "total_tax": 4500.0,
        "invoice_type": "B2B",
    }
    amendment_record = {
        "invoice_number": "INV-101",
        "invoice_date": "2026-08-20",  # Amended date
        "oinum": "INV-101",
        "oidt": "10-08-2026",
        "gstin": "27TESTG1234A1Z5",
        "taxable_amount": 25000.0,
        "total_tax": 4500.0,
        "invoice_type": "B2BA",
    }

    resolved, source = resolve_amendment_original(amendment_record, [original_sr], [])
    assert resolved is not None
    assert source == "SALES_REGISTER"

    canon = build_canonical_amendment(amendment_record, resolved, source, "092026")
    assert canon.amended_invoice_date == "2026-08-20"
    assert canon.original_invoice_date == "2026-08-10"
    assert canon.delta_taxable == 0.0


def test_3_b2ba_invoice_number_amendment():
    """Test 3: B2BA invoice number amendment."""
    original_sr = {
        "invoice_number": "INV-ORIG-102",
        "invoice_date": "2026-08-12",
        "gstin": "27TESTG1234A1Z5",
        "taxable_amount": 30000.0,
        "total_tax": 5400.0,
        "invoice_type": "B2B",
    }
    amendment_record = {
        "invoice_number": "INV-CORR-102",  # Amended inv number
        "invoice_date": "2026-08-12",
        "oinum": "INV-ORIG-102",
        "oidt": "12-08-2026",
        "gstin": "27TESTG1234A1Z5",
        "taxable_amount": 30000.0,
        "total_tax": 5400.0,
        "invoice_type": "B2BA",
    }

    resolved, source = resolve_amendment_original(amendment_record, [original_sr], [])
    assert resolved is not None
    assert resolved["invoice_number"] == "INV-ORIG-102"

    canon = build_canonical_amendment(amendment_record, resolved, source, "092026")
    assert canon.amended_invoice_number == "INV-CORR-102"
    assert canon.original_invoice_number == "INV-ORIG-102"


def test_4_wrong_original_link():
    """Test 4: Wrong original link (routes to Review Required)."""
    amendment_record = {
        "invoice_number": "INV-999-AMEND",
        "oinum": "DOES-NOT-EXIST",
        "oidt": "01-08-2026",
        "gstin": "27TESTG1234A1Z5",
        "taxable_amount": 40000.0,
        "total_tax": 7200.0,
        "invoice_type": "B2BA",
    }

    resolved, source = resolve_amendment_original(amendment_record, [], [])
    assert resolved is None

    res = process_gstr1_amendments([amendment_record], [], [], "092026")
    assert len(res["accounted_sr_records"]) == 0
    # Mismatch is generated for unmatched amendment requiring review
    unmatched_mms = [m for m in res["mismatches"] if m.rule_id == "G1M_011_UNMATCHED_AMENDMENT"]
    assert len(unmatched_mms) == 1
    assert unmatched_mms[0].details.get("requires_review") is True


def test_5_duplicate_amendment_chain():
    """Test 5: Duplicate amendment chain (latest effective, 1 source accounted, warning emitted)."""
    original_sr = {
        "invoice_number": "INV-200",
        "invoice_date": "2026-08-01",
        "gstin": "27TESTG1234A1Z5",
        "taxable_amount": 10000.0,
        "total_tax": 1800.0,
        "invoice_type": "B2B",
    }
    amend1 = {
        "invoice_number": "INV-200",
        "invoice_date": "2026-09-05",
        "oinum": "INV-200",
        "oidt": "01-08-2026",
        "gstin": "27TESTG1234A1Z5",
        "taxable_amount": 12000.0,
        "total_tax": 2160.0,
        "invoice_type": "B2BA",
    }
    amend2 = {
        "invoice_number": "INV-200",
        "invoice_date": "2026-09-15",
        "oinum": "INV-200",
        "oidt": "01-08-2026",
        "gstin": "27TESTG1234A1Z5",
        "taxable_amount": 15000.0,
        "total_tax": 2700.0,
        "invoice_type": "B2BA",
    }

    res = process_gstr1_amendments([amend1, amend2], [original_sr], [], "092026")

    # Only 1 source accounted
    assert len(res["accounted_sr_records"]) == 1
    assert res["accounted_sr_records"][0]["invoice_number"] == "INV-200"

    # Emitted MULTIPLE_AMENDMENTS_SAME_ORIGINAL review flag
    dup_mms = [m for m in res["mismatches"] if m.rule_id == "G1M_011_MULTIPLE_AMENDMENTS"]
    assert len(dup_mms) == 1

    dup_chains = [c for c in res["chains_summary"] if c["is_duplicate_chain"]]
    assert len(dup_chains) == 1
    assert dup_chains[0]["count"] == 2


def test_6_cdna_credit_note():
    """Test 6: CDNA Credit Note (ont_num link, CN sign handling)."""
    original_cr_sr = {
        "invoice_number": "CR-300",
        "invoice_date": "2026-08-10",
        "gstin": "27TESTG1234A1Z5",
        "taxable_amount": -5000.0,
        "total_tax": -900.0,
        "invoice_type": "CR",
    }
    cdna_record = {
        "invoice_number": "CR-300",
        "invoice_date": "2026-08-10",
        "ont_num": "CR-300",
        "ont_dt": "10-08-2026",
        "gstin": "27TESTG1234A1Z5",
        "taxable_amount": 8000.0,
        "total_tax": 1440.0,
        "invoice_type": "CDNA",
        "ntty": "C",
    }

    resolved, source = resolve_amendment_original(cdna_record, [original_cr_sr], [])
    assert resolved is not None

    canon = build_canonical_amendment(cdna_record, resolved, source, "092026")
    # For Credit Notes, signed delta reflects increase in credit note (reduction in turnover)
    assert canon.original_taxable == -5000.0
    assert canon.amended_taxable == -8000.0
    assert canon.delta_taxable == -3000.0


def test_7_cdna_debit_note():
    """Test 7: CDNA Debit Note (ont_num link, DN sign handling)."""
    original_dr_sr = {
        "invoice_number": "DR-400",
        "invoice_date": "2026-08-10",
        "gstin": "27TESTG1234A1Z5",
        "taxable_amount": 5000.0,
        "total_tax": 900.0,
        "invoice_type": "DR",
    }
    cdna_record = {
        "invoice_number": "DR-400",
        "invoice_date": "2026-08-10",
        "ont_num": "DR-400",
        "ont_dt": "10-08-2026",
        "gstin": "27TESTG1234A1Z5",
        "taxable_amount": 7000.0,
        "total_tax": 1260.0,
        "invoice_type": "CDNA",
        "ntty": "D",
    }

    resolved, source = resolve_amendment_original(cdna_record, [original_dr_sr], [])
    assert resolved is not None

    canon = build_canonical_amendment(cdna_record, resolved, source, "092026")
    assert canon.original_taxable == 5000.0
    assert canon.amended_taxable == 7000.0
    assert canon.delta_taxable == 2000.0


def test_8_wrong_cdna_original():
    """Test 8: Wrong CDNA original link (Review Required)."""
    cdna_record = {
        "invoice_number": "CR-UNRESOLVED",
        "ont_num": "MISSING-CR-NOTE",
        "ont_dt": "10-08-2026",
        "gstin": "27TESTG1234A1Z5",
        "taxable_amount": 5000.0,
        "total_tax": 900.0,
        "invoice_type": "CDNA",
        "ntty": "C",
    }

    resolved, source = resolve_amendment_original(cdna_record, [], [])
    assert resolved is None

    res = process_gstr1_amendments([cdna_record], [], [], "092026")
    assert len(res["accounted_sr_records"]) == 0
    unmatched_mms = [m for m in res["mismatches"] if m.rule_id == "G1M_011_UNMATCHED_AMENDMENT"]
    assert len(unmatched_mms) == 1


def test_9_late_august_filed_september():
    """Test 9: Late August filed September (matched as B2B)."""
    sr_rec = {
        "invoice_number": "LATE-AUG-01",
        "invoice_date": "2026-08-25",
        "gstin": "27TESTG1234A1Z5",
        "taxable_amount": 50000.0,
        "total_tax": 9000.0,
        "cgst": 4500.0,
        "sgst": 4500.0,
        "igst": 0.0,
        "invoice_type": "B2B",
    }
    gstr1_rec = {
        "invoice_number": "LATE-AUG-01",
        "invoice_date": "2026-08-25",
        "gstin": "27TESTG1234A1Z5",
        "taxable_amount": 50000.0,
        "total_tax": 9000.0,
        "cgst": 4500.0,
        "sgst": 4500.0,
        "igst": 0.0,
        "invoice_type": "B2B",
        "filing_period": "092026",
    }
    res = match_sales_register_to_gstr1(sr_rec, [gstr1_rec])
    assert res.matched is True
    assert res.level == 1


def test_10_amendment_delta_aggregation_increase():
    """Test 10: Amendment delta aggregation increase (+10,000)."""
    orig = {"invoice_number": "INV-A", "taxable_amount": 50000.0, "total_tax": 9000.0, "cgst": 4500.0, "sgst": 4500.0, "invoice_type": "B2B", "gstin": "27TESTG1234A1Z5"}
    amend = {"invoice_number": "INV-A", "oinum": "INV-A", "taxable_amount": 60000.0, "total_tax": 10800.0, "cgst": 5400.0, "sgst": 5400.0, "invoice_type": "B2BA", "gstin": "27TESTG1234A1Z5"}
    canon = build_canonical_amendment(amend, orig, "SALES_REGISTER", "092026")
    assert canon.delta_taxable == 10000.0
    assert canon.delta_taxable_paise == 1000000


def test_11_amendment_delta_aggregation_decrease():
    """Test 11: Amendment delta aggregation decrease (-10,000)."""
    orig = {"invoice_number": "INV-B", "taxable_amount": 50000.0, "total_tax": 9000.0, "cgst": 4500.0, "sgst": 4500.0, "invoice_type": "B2B", "gstin": "27TESTG1234A1Z5"}
    amend = {"invoice_number": "INV-B", "oinum": "INV-B", "taxable_amount": 40000.0, "total_tax": 7200.0, "cgst": 3600.0, "sgst": 3600.0, "invoice_type": "B2BA", "gstin": "27TESTG1234A1Z5"}
    canon = build_canonical_amendment(amend, orig, "SALES_REGISTER", "092026")
    assert canon.delta_taxable == -10000.0
    assert canon.delta_taxable_paise == -1000000


def test_12_cn_amendment_delta():
    """Test 12: Credit note amendment delta."""
    orig = {"invoice_number": "CR-1", "taxable_amount": -5000.0, "total_tax": -900.0, "invoice_type": "CR", "gstin": "27TESTG1234A1Z5"}
    amend = {"invoice_number": "CR-1", "ont_num": "CR-1", "taxable_amount": 8000.0, "total_tax": 1440.0, "invoice_type": "CDNA", "ntty": "C", "gstin": "27TESTG1234A1Z5"}
    canon = build_canonical_amendment(amend, orig, "SALES_REGISTER", "092026")
    assert canon.delta_taxable == -3000.0


def test_13_duplicate_amendment_aggregation():
    """Test 13: Duplicate amendment aggregation (+15,000 effective)."""
    orig = {"invoice_number": "INV-D", "taxable_amount": 20000.0, "total_tax": 3600.0, "invoice_type": "B2B", "gstin": "27TESTG1234A1Z5"}
    a1 = {"invoice_number": "INV-D", "oinum": "INV-D", "taxable_amount": 25000.0, "total_tax": 4500.0, "invoice_type": "B2BA", "gstin": "27TESTG1234A1Z5", "invoice_date": "2026-09-01"}
    a2 = {"invoice_number": "INV-D", "oinum": "INV-D", "taxable_amount": 35000.0, "total_tax": 6300.0, "invoice_type": "B2BA", "gstin": "27TESTG1234A1Z5", "invoice_date": "2026-09-10"}

    res = process_gstr1_amendments([a1, a2], [orig], [], "092026")
    assert len(res["canonical_amendments"]) == 2
    # The terminal (latest effective) amendment has effective value 35000.0
    latest = [c for c in res["canonical_amendments"] if c.is_latest_effective_amendment][0]
    assert latest.amended_taxable == 35000.0
    assert latest.delta_taxable == 15000.0


# ---------------------------------------------------------------------------
# Integration Tests on Run 5 Benchmark (Tests 14 - 15)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def run5_data():
    sr_path = "../benchmark_data/run5_amendments_3000/ReconDesk_Sales_Register_3000_Amendments_Run5_Sep2026.xlsx"
    cur_path = "../benchmark_data/run5_amendments_3000/ReconDesk_GSTR1_Sep2026_Amendments_Run5.json"
    prior_path = "../benchmark_data/run5_amendments_3000/ReconDesk_GSTR1_Aug2026_PriorPeriod_Run5.json"
    g3b_path = "../benchmark_data/run5_amendments_3000/ReconDesk_GSTR3B_Sep2026_Amendments_Run5.json"

    with open(sr_path, "rb") as f:
        sr_bytes = f.read()
    with open(cur_path, "rb") as f:
        cur_bytes = f.read()
    with open(prior_path, "rb") as f:
        prior_bytes = f.read()
    with open(g3b_path, "rb") as f:
        g3b_bytes = f.read()

    return {
        "sr_bytes": sr_bytes,
        "cur_bytes": cur_bytes,
        "prior_bytes": prior_bytes,
        "g3b_bytes": g3b_bytes,
    }


@pytest.mark.asyncio
async def test_14_run5_headline_counts(run5_data):
    """Test 14: Run 5 headline counts and reconciliation metrics."""
    res = await _run_pipeline(
        sr_file_content=run5_data["sr_bytes"],
        sr_filename="ReconDesk_Sales_Register_3000_Amendments_Run5_Sep2026.xlsx",
        gstr1_file_content=run5_data["cur_bytes"],
        gstr3b_file_content=run5_data["g3b_bytes"],
        gstr1_filing_period="092026",
        prior_gstr1_file_content=run5_data["prior_bytes"],
    )

    summary = res["summary"]

    # 1. Total Sales Register rows
    assert summary["sr_total_records"] == 3000

    # 2. Invoice-level matches (B2B, normalized, late Aug, B2CL, tax diff, +2 days, cancel/reissue)
    assert summary["matched_count"] == 2290

    # 3. Aggregate B2CS source invoices
    assert summary["aggregate_source_invoice_count"] == 140

    # 4. Amendment-accounted source invoices
    # 150 val + 80 dt + 70 inv + 30 dup chain + 80 CN + 60 DN = 470
    assert summary["amendment_accounted_source_count"] == 470

    # 5. Accounted source rows: 2290 + 140 + 470 = 2900
    assert summary["accounted_source_invoice_count"] == 2900

    # 6. Unaccounted source rows: 3000 - 2900 = 100 (60 missing + 40 wrong link)
    assert summary["unaccounted_source_invoice_count"] == 100

    # 7. Coverage percentage: 2900 / 3000 = 96.67%
    assert summary["coverage_percentage"] == 96.67

    # 8. Genuine missing in GSTR-1
    assert summary["missing_in_gstr1_count"] == 60
    assert summary["unmatched_sr_count"] == 60

    # 9. Extra in GSTR-1
    assert summary["unmatched_gstr1_count"] == 50

    # 10. Duplicate amendment chains
    assert summary["amendment_chains_count"] == 30

    # 11. Total parsed amendments
    assert summary["amendment_count"] == 540


@pytest.mark.asyncio
async def test_15_run5_tieout_deliberate_variance(run5_data):
    """Test 15: Run 5 GSTR-1 vs GSTR-3B tie-out (₹12,500 taxable only)."""
    res = await _run_pipeline(
        sr_file_content=run5_data["sr_bytes"],
        sr_filename="ReconDesk_Sales_Register_3000_Amendments_Run5_Sep2026.xlsx",
        gstr1_file_content=run5_data["cur_bytes"],
        gstr3b_file_content=run5_data["g3b_bytes"],
        gstr1_filing_period="092026",
        prior_gstr1_file_content=run5_data["prior_bytes"],
    )

    tie_out = res["tie_out"]
    variances = tie_out["variances"]

    # Exactly 1 variance (Table 3.1(a) taxable difference of ₹12,500)
    assert len(variances) == 1
    v = variances[0]
    assert v["field"] == "taxable_value"
    assert "12,500" in v["diff"]

    # Zero tax variances
    tax_variances = [v for v in variances if v["field"] in ("igst", "cgst", "sgst", "cess")]
    assert len(tax_variances) == 0
