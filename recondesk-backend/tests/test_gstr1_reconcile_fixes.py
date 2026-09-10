"""Comprehensive test suite for GSTR-1 reconciliation engine fixes.

Covers:
1. B2CS aggregate reconciliation (Table 7) vs individual invoice matching
2. Credit note sign normalization (negative in books vs positive on portal)
3. Table 9 B2BA amendment handling (differential vs 0 contribution for unmatched)
4. GSTR-1 vs 3B tie-out liability alignment
5. Table 12 HSN summary reconciliation
6. Full end-to-end reconciliation on the July 2025 benchmark dataset
"""

from pathlib import Path
import pytest

from app.services.matcher import normalise_inv_no, _is_credit_note
from app.matching.generic_matcher import generic_match_pair, SALES_MATCH_CONFIG
from app.rules.gstr1_mismatch_rules import (
    classify_amount_mismatch,
    classify_tax_structure_mismatch,
    detect_amendments,
    reconcile_hsn_summary,
    MismatchType,
    MismatchSeverity,
)
from app.reconciliation.gstr1_vs_3b import (
    aggregate_gstr1,
    reconcile_gstr1_vs_3b,
)
from app.routers.gstr1_reconcile import (
    _is_sr_b2cs_record,
    reconcile_b2cs_aggregate,
    _run_pipeline,
)


# ── 1. B2CS Aggregate Tests ───────────────────────────────────────────────────

def test_is_sr_b2cs_record_classification():
    """Verify B2CS rows are identified and distinct from B2B, B2CL, Credit Notes, Exports."""
    supplier_gstin = "27ISKPK1273H1ZF"  # Maharashtra (27)
    b2cl_keys = {"202526007"}

    # B2C small intra-state
    sr_b2cs = {
        "invoice_number": "202526008",
        "place_of_supply": "27-Maharashtra",
        "taxable_amount_paise": 3500000,
        "total_tax_paise": 630000,
        "invoice_value_paise": 4130000,
        "gstin": None,
    }
    assert _is_sr_b2cs_record(sr_b2cs, supplier_gstin, b2cl_keys) is True

    # B2B registered party
    sr_b2b = {
        "invoice_number": "202526001",
        "place_of_supply": "29-Karnataka",
        "taxable_amount_paise": 15000000,
        "gstin": "29AABCI1681G1ZX",
    }
    assert _is_sr_b2cs_record(sr_b2b, supplier_gstin, b2cl_keys) is False

    # B2CL inter-state unregistered > 2.5L
    sr_b2cl = {
        "invoice_number": "202526007",
        "place_of_supply": "06-Haryana",
        "taxable_amount_paise": 30000000,
        "invoice_value_paise": 35400000,
        "gstin": None,
    }
    assert _is_sr_b2cs_record(sr_b2cl, supplier_gstin, b2cl_keys) is False

    # Credit Note
    sr_cn = {
        "invoice_number": "2025262001CN",
        "doc_type": "CREDIT_NOTE",
        "place_of_supply": "27-Maharashtra",
        "taxable_amount_paise": -2000000,
        "gstin": "27AAACR5055K1ZK",
    }
    assert _is_sr_b2cs_record(sr_cn, supplier_gstin, b2cl_keys) is False

    # Export
    sr_exp = {
        "invoice_number": "202526009",
        "doc_type": "EXPORT",
        "place_of_supply": "96-Foreign Country",
        "taxable_amount_paise": 50000000,
        "gstin": None,
    }
    assert _is_sr_b2cs_record(sr_exp, supplier_gstin, b2cl_keys) is False


def test_reconcile_b2cs_aggregate_matching():
    """Verify B2CS aggregate rows match without generating invoice-level mismatches."""
    sr_b2cs_rows = [
        {"taxable_amount_paise": 2000000, "cgst_paise": 180000, "sgst_paise": 180000},
        {"taxable_amount_paise": 1500000, "cgst_paise": 135000, "sgst_paise": 135000},
    ]
    g1_b2cs_rows = [
        {
            "section": "b2cs",
            "taxable_amount_paise": 3500000,
            "cgst_paise": 315000,
            "sgst_paise": 315000,
            "igst_paise": 0,
        }
    ]

    matched, mismatches = reconcile_b2cs_aggregate(sr_b2cs_rows, g1_b2cs_rows)
    assert len(matched) == 1
    assert len(mismatches) == 0
    sr_synth, g1_synth, mr_dict = matched[0]
    assert sr_synth["invoice_number"] == "B2CS-AGGREGATE"
    assert g1_synth["invoice_number"] == "B2CS-AGGREGATE"
    assert mr_dict["financial_status"] == "Exact"


def test_reconcile_b2cs_aggregate_mismatch():
    """Verify aggregate variance reports an aggregate mismatch, not false G1M1/G1M2."""
    sr_b2cs_rows = [
        {"taxable_amount_paise": 3500000, "cgst_paise": 315000, "sgst_paise": 315000}
    ]
    g1_b2cs_rows = [
        {"section": "b2cs", "taxable_amount_paise": 4000000, "cgst_paise": 360000, "sgst_paise": 360000}
    ]

    matched, mismatches = reconcile_b2cs_aggregate(sr_b2cs_rows, g1_b2cs_rows)
    assert len(matched) == 0
    assert len(mismatches) == 1
    mm = mismatches[0]
    assert mm.mismatch_type == MismatchType.AMOUNT_MISMATCH
    assert mm.rule_id == "G1M_003_B2CS_AGGREGATE"
    assert "B2CS aggregate mismatch" in mm.decision_what


# ── 2. Credit Note Sign Normalization Tests ────────────────────────────────────

def test_credit_note_sign_normalization_matching():
    """Verify SR credit note (negative) matches GSTR-1 portal credit note (positive)."""
    sr_cn = {
        "invoice_number": "2025262001CN",
        "doc_type": "CREDIT_NOTE",
        "gstin": "27AAACR5055K1ZK",
        "recipient_gstin": "27AAACR5055K1ZK",
        "taxable_amount_paise": -2000000,
        "cgst_paise": 180000,
        "sgst_paise": 180000,
        "total_tax_paise": -360000,
        "total_amount_paise": -2360000,
        "invoice_date": "2025-07-15",
    }
    g1_cn = {
        "nt_num": "2025262001CN",
        "section": "cdnr",
        "ntty": "C",
        "recipient_gstin": "27AAACR5055K1ZK",
        "taxable_amount_paise": 2000000,
        "cgst_paise": 180000,
        "sgst_paise": 180000,
        "total_tax_paise": 360000,
        "invoice_value_paise": 2360000,
        "invoice_date": "2025-07-15",
    }

    # 1. Matcher level check
    match_result = generic_match_pair(sr_cn, g1_cn, SALES_MATCH_CONFIG)
    assert match_result.matched is True
    assert match_result.level == 1
    assert match_result.discrepancies == []

    # 2. Rule classifier check: no G1M3 mismatch
    amt_mm = classify_amount_mismatch(sr_cn, g1_cn)
    assert amt_mm is None

    # 3. Tax structure classifier check: no structure mismatch
    tax_struct_mm = classify_tax_structure_mismatch(sr_cn, g1_cn)
    assert tax_struct_mm is None


def test_credit_note_genuine_mismatch_detected():
    """Verify genuine financial difference on credit note is still caught."""
    sr_cn = {
        "invoice_number": "CN-001",
        "doc_type": "CREDIT_NOTE",
        "taxable_amount_paise": -2000000,
        "total_tax_paise": -360000,
    }
    g1_cn = {
        "nt_num": "CN-001",
        "section": "cdnr",
        "taxable_amount_paise": 2500000,  # ₹25,000 vs ₹20,000
        "total_tax_paise": 450000,
    }

    amt_mm = classify_amount_mismatch(sr_cn, g1_cn)
    assert amt_mm is not None
    assert amt_mm.mismatch_type == MismatchType.AMOUNT_MISMATCH
    assert amt_mm.details["taxable_diff_paise"] == 500000  # ₹5,000 diff


def test_standard_invoice_sign_logic_preserved():
    """Verify standard invoices still catch negative vs positive as an amount mismatch."""
    sr_inv = {
        "invoice_number": "INV-001",
        "doc_type": "INVOICE",
        "taxable_amount_paise": 2000000,
        "total_tax_paise": 360000,
    }
    g1_inv = {
        "inum": "INV-001",
        "section": "b2b",
        "taxable_amount_paise": -2000000,
        "total_tax_paise": -360000,
    }
    amt_mm = classify_amount_mismatch(sr_inv, g1_inv)
    assert amt_mm is not None


# ── 3. Table 9 Amendment Tests ────────────────────────────────────────────────

def test_unmatched_b2ba_amendment_flags_review_required():
    """Verify B2BA amendment referencing non-existent prior invoice flags G1M11 review."""
    prior_records = [
        {"inum": "INV/2025-26/A01", "section": "b2b", "taxable_amount_paise": 10000000}
    ]
    current_amendments = [
        {
            "section": "b2ba",
            "is_amendment": True,
            "oinum": "20252601A",  # Typo / missing from prior return
            "inum": "20252601A",
            "taxable_amount_paise": 12000000,
            "igst_paise": 2160000,
            "filing_period": "072025",
        }
    ]

    results = detect_amendments(
        sr_records=[],
        prior_gstr1_records=prior_records,
        prior_provided=True,
        current_amendment_records=current_amendments,
    )
    unmatched_amends = [
        r for r in results if r.details.get("issue_type") == "unmatched_amendment"
    ]
    assert len(unmatched_amends) == 1
    flag = unmatched_amends[0]
    assert flag.mismatch_type == MismatchType.AMENDMENT_REQUIRED
    assert flag.severity == MismatchSeverity.HIGH
    assert "REVIEW REQUIRED — UNMATCHED / INVALID B2BA AMENDMENT" in flag.decision_what
    assert flag.details["original_invoice_number"] == "20252601A"


def test_unmatched_b2ba_amendment_does_not_inflate_turnover():
    """Verify unmatched B2BA contributes 0 to current-period GSTR-1 turnover."""
    current_gstr1 = [
        {"section": "b2b", "inum": "INV-001", "taxable_amount_paise": 10000000, "igst_paise": 1800000},
        {
            "section": "b2ba",
            "is_amendment": True,
            "oinum": "20252601A",  # Unmatched
            "taxable_amount_paise": 12000000,
            "igst_paise": 2160000,
        },
    ]
    prior_gstr1 = [
        {"section": "b2b", "inum": "INV/2025-26/A01", "taxable_amount_paise": 8000000}
    ]

    agg = aggregate_gstr1(current_gstr1, prior_records=prior_gstr1)
    # Only INV-001 (10,000,000 paise = ₹1,00,000) should be included; 20252601A must NOT be added.
    assert agg.taxable_value_paise == 10000000
    assert agg.igst_paise == 1800000


def test_valid_b2ba_amendment_applies_differential():
    """Verify verified B2BA amendment applies only the economic difference (amended - prior)."""
    current_gstr1 = [
        {
            "section": "b2ba",
            "is_amendment": True,
            "oinum": "INV/2025-26/A01",
            "inum": "INV/2025-26/A01",
            "taxable_amount_paise": 12000000,  # ₹1,20,000
            "igst_paise": 2160000,
        }
    ]
    prior_gstr1 = [
        {
            "section": "b2b",
            "inum": "INV/2025-26/A01",
            "taxable_amount_paise": 10000000,  # ₹1,00,000
            "igst_paise": 1800000,
        }
    ]

    agg = aggregate_gstr1(current_gstr1, prior_records=prior_gstr1)
    # Differential = ₹1,20,000 - ₹1,00,000 = ₹20,000 (2,000,000 paise)
    assert agg.taxable_value_paise == 2000000
    assert agg.igst_paise == 360000


# ── 4. Table 12 HSN Summary Reconciliation Tests ─────────────────────────────

def test_hsn_summary_reconciles_taxable_supplies():
    """Verify Table 12 HSN summary reconciles against outward supplies without false flags."""
    hsn_records = [
        {"section": "hsn", "hsn": "8471", "taxable_amount_paise": 106500000, "igst_paise": 9900000, "cgst_paise": 4635000, "sgst_paise": 4635000, "invoice_value_paise": 147970000},
        {"section": "hsn", "hsn": "3004", "taxable_amount_paise": 32500000, "igst_paise": 3000000, "cgst_paise": 900000, "sgst_paise": 900000, "invoice_value_paise": 37300000},
    ]
    outward_records = [
        {"section": "b2b", "taxable_amount_paise": 15000000, "igst_paise": 2700000},
        {"section": "b2b", "taxable_amount_paise": 25000000, "igst_paise": 3000000},
        {"section": "b2b", "taxable_amount_paise": 10000000, "igst_paise": 1800000},
        {"section": "b2b", "taxable_amount_paise": 20000000, "cgst_paise": 1800000, "sgst_paise": 1800000},
        {"section": "b2b", "taxable_amount_paise": 7500000, "cgst_paise": 900000, "sgst_paise": 900000},
        {"section": "b2b", "taxable_amount_paise": 30000000, "cgst_paise": 2700000, "sgst_paise": 2700000},
        {"section": "b2cl", "taxable_amount_paise": 30000000, "igst_paise": 5400000},
        {"section": "b2cs", "taxable_amount_paise": 3500000, "cgst_paise": 315000, "sgst_paise": 315000},
        {"section": "cdnr", "doc_type": "CREDIT_NOTE", "taxable_amount_paise": -2000000, "cgst_paise": -180000, "sgst_paise": -180000},
        {"section": "exp", "doc_type": "EXPORT", "taxable_amount_paise": 50000000, "place_of_supply": "96-Foreign Country"},
    ]

    mismatches = reconcile_hsn_summary(hsn_records, outward_records)
    assert len(mismatches) == 0


def test_hsn_summary_detects_genuine_discrepancy():
    """Verify Table 12 HSN summary flags genuine discrepancy."""
    hsn_records = [
        {"section": "hsn", "hsn": "8471", "taxable_amount_paise": 50000000, "igst_paise": 9000000, "invoice_value_paise": 59000000}
    ]
    outward_records = [
        {"section": "b2b", "taxable_amount_paise": 90000000, "igst_paise": 16200000}
    ]

    mismatches = reconcile_hsn_summary(hsn_records, outward_records)
    assert len(mismatches) == 1
    assert mismatches[0].rule_id == "G1M_009_HSN_SUMMARY_MISMATCH"


# ── 5. End-to-End July 2025 Benchmark Dataset Test ───────────────────────────

@pytest.mark.asyncio
async def test_july_2025_benchmark_reconciliation():
    """Full pipeline run on the July 2025 test dataset."""
    benchmark_dir = Path(__file__).resolve().parent.parent.parent / "benchmark_data" / "gstr1_jul2025"
    if not benchmark_dir.exists():
        pytest.skip(f"Benchmark dir {benchmark_dir} not found")

    sr_bytes = (benchmark_dir / "sales_register_jul2025.csv").read_bytes()
    g1_bytes = (benchmark_dir / "gstr1_jul2025.json").read_bytes()
    g3b_bytes = (benchmark_dir / "gstr3b_jul2025.json").read_bytes()
    prior_bytes = (benchmark_dir / "gstr1_prior_jun2025.json").read_bytes()

    res = await _run_pipeline(
        sr_file_content=sr_bytes,
        sr_filename="sales_register_jul2025.csv",
        gstr1_file_content=g1_bytes,
        gstr3b_file_content=g3b_bytes,
        gstr1_filing_period="072025",
        prior_gstr1_file_content=prior_bytes,
    )

    summary = res["summary"]

    # 1. Matched count must be 10 (8 standard + 1 credit note + 1 B2CS aggregate)
    assert summary["matched_count"] == 10
    assert summary["unmatched_sr_count"] == 0
    assert summary["unmatched_gstr1_count"] == 0

    # 2. Tie-out against GSTR-3B must be clean with 0 variances
    assert summary["tie_out_clean"] is True
    assert summary["tie_out_variance_count"] == 0
    assert len(res["tie_out"]["variances"]) == 0

    # 3. Exactly 1 amendment flagged (the unmatched B2BA)
    assert summary["amendment_count"] == 1
    unmatched_amends = [
        m for m in res["mismatches"]
        if m.get("rule_id") == "G1M_011_UNMATCHED_AMENDMENT"
    ]
    assert len(unmatched_amends) == 1
    assert "REVIEW REQUIRED — UNMATCHED / INVALID B2BA AMENDMENT" in unmatched_amends[0]["decision_what"]

    # 4. Credit note has no discrepancies
    cn_match = next(
        m for m in res["matched"]
        if (m.get("sr_record") or {}).get("invoice_number") == "2025262001CN"
    )
    assert cn_match["discrepancies"] == []

    # 5. B2CS aggregate match exists
    b2cs_match = next(
        m for m in res["matched"]
        if (m.get("sr_record") or {}).get("invoice_number") == "B2CS-AGGREGATE"
    )
    assert b2cs_match is not None
