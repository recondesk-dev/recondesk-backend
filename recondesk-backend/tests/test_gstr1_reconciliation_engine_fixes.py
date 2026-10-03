"""Comprehensive regression test suite for GSTR-1 vs Sales Register vs GSTR-3B reconciliation engine.

Tests 1 to 10 covering:
1. Clean September 2026 3,000-record benchmark reconciliation (2,172 B2B, 498 B2CL, 330 B2CS).
2. B2CS aggregate mismatch (dimensional variance, no false missing invoices).
3. Actual B2B missing invoice (G1M1 flagged with credit note advice if applicable).
4. B2CS invoice absent from GSTR-1 JSON (no G1M1, no series gap).
5. Genuine Sales Register sequence gap (INV-00003 warning in books, not G1 missing).
6. Multiple series (SALE vs SERVICE evaluated independently).
7. Aug 2024+ threshold (₹100,000 boundary).
8. Historical July 2024 threshold (₹250,000 boundary).
9. Nil/exempt 3B tie-out (Table 8 / 3.1(c) clean tie-out).
10. Real GSTR-3B mismatch (₹10,000 variance flagged).
"""

from __future__ import annotations

import json
from typing import Any
import pytest

from app.rules.gstr1_rules import get_gstr1_rules
from app.rules.gstr1_mismatch_rules import (
    check_invoice_series_continuity,
    classify_missing_invoice,
    reconcile_hsn_summary,
    MismatchType,
)
from app.reconciliation.gstr1_vs_3b import (
    aggregate_gstr1,
    compute_variances,
    reconcile_gstr1_vs_3b,
    GSTR1Aggregate,
    GSTR3BSummary,
)
from app.routers.gstr1_reconcile import (
    _is_sr_b2cs_record,
    reconcile_b2cs_aggregate,
    _run_pipeline,
)


# ══════════════════════════════════════════════════════════════════════════════
# Test 7 & 8: Period-Aware B2CL / B2CS Thresholds
# ══════════════════════════════════════════════════════════════════════════════

def test_period_aware_b2cl_threshold_post_aug_2024():
    """Test 7: Post-August 2024 (Notification 12/2024-CT) B2CL threshold is ₹1,00,000."""
    rules = get_gstr1_rules("2026-09")
    assert rules.b2cl_threshold_paise == 10_000_000  # ₹1,00,000
    assert rules.b2cl_threshold_rupees == 100_000.0

    # Interstate unregistered, inv_val = ₹1,50,000 (> ₹1L) -> B2CL
    assert rules.is_b2cl(
        inv_val_paise=15_000_000, is_interstate=True, is_registered=False
    )
    assert not rules.is_b2cs(
        inv_val_paise=15_000_000, is_interstate=True, is_registered=False
    )

    # Interstate unregistered, inv_val = ₹90,000 (<= ₹1L) -> B2CS
    assert not rules.is_b2cl(
        inv_val_paise=9_000_000, is_interstate=True, is_registered=False
    )
    assert rules.is_b2cs(
        inv_val_paise=9_000_000, is_interstate=True, is_registered=False
    )

    # Boundary: exactly ₹1,00,000 -> B2CS (threshold is strictly greater than for B2CL)
    assert not rules.is_b2cl(
        inv_val_paise=10_000_000, is_interstate=True, is_registered=False
    )
    assert rules.is_b2cs(
        inv_val_paise=10_000_000, is_interstate=True, is_registered=False
    )

    # Intra-state unregistered is always B2CS regardless of value
    assert not rules.is_b2cl(
        inv_val_paise=50_000_000, is_interstate=False, is_registered=False
    )
    assert rules.is_b2cs(
        inv_val_paise=50_000_000, is_interstate=False, is_registered=False
    )


def test_period_aware_b2cl_threshold_historical_pre_aug_2024():
    """Test 8: Pre-August 2024 historical threshold was ₹2,50,000."""
    rules = get_gstr1_rules("2024-07")
    assert rules.b2cl_threshold_paise == 25_000_000  # ₹2,50,000
    assert rules.b2cl_threshold_rupees == 250_000.0

    # Interstate unregistered, inv_val = ₹1,50,000:
    # Under historical rules (<= ₹2.5L) this was B2CS, NOT B2CL!
    assert not rules.is_b2cl(
        inv_val_paise=15_000_000, is_interstate=True, is_registered=False
    )
    assert rules.is_b2cs(
        inv_val_paise=15_000_000, is_interstate=True, is_registered=False
    )

    # Interstate unregistered, inv_val = ₹3,00,000 (> ₹2.5L) -> B2CL
    assert rules.is_b2cl(
        inv_val_paise=30_000_000, is_interstate=True, is_registered=False
    )
    assert not rules.is_b2cs(
        inv_val_paise=30_000_000, is_interstate=True, is_registered=False
    )


# ══════════════════════════════════════════════════════════════════════════════
# Test 4: B2CS Invoices Absent from GSTR-1 JSON
# ══════════════════════════════════════════════════════════════════════════════

def test_b2cs_invoices_absent_from_gstr1_json_produce_no_false_gaps():
    """Test 4: B2CS invoices absent from individual GSTR-1 rows do not create missing invoice flags or series gaps."""
    # 3 B2CS invoices in books
    sr_records = [
        {
            "invoice_number": f"RD/S/26-27/0065{i}",
            "invoice_number_normalized": f"RDS26270065{i}",
            "invoice_date": "2026-09-10",
            "place_of_supply": "27-Maharashtra",
            "taxable_amount_paise": 100000,
            "cgst_paise": 9000,
            "sgst_paise": 9000,
            "total_tax_paise": 18000,
            "invoice_value_paise": 118000,
            "gstin": None,
            "invoice_type": "B2C",
            "document_type": "B2C",
        }
        for i in (659, 660, 661)
    ]

    # In GSTR-1, these invoices do NOT appear as individual invoice rows (only aggregated in Table 7)
    gstr1_records = [
        # Some other B2B invoice
        {
            "invoice_number": "RD/S/26-27/00001",
            "invoice_number_normalized": "RDS262700001",
            "section": "b2b",
            "taxable_amount_paise": 100000,
            "total_tax_paise": 18000,
        }
    ]

    # Series continuity check with SR records authoritative
    mismatches = check_invoice_series_continuity(sr_records, gstr1_records)
    # The B2CS records are contiguous in SR (00659, 00660, 00661), so NO gap warning should be emitted!
    gap_warnings = [m for m in mismatches if m.mismatch_type == MismatchType.INVOICE_SERIES_ISSUE]
    assert len(gap_warnings) == 0


# ══════════════════════════════════════════════════════════════════════════════
# Test 5: Genuine Sales Register Sequence Gap
# ══════════════════════════════════════════════════════════════════════════════

def test_genuine_sales_register_sequence_gap():
    """Test 5: Real numeric gap in SR series (e.g. 00001, 00002, 00004) flagged as series issue, not missing turnover in GSTR-1."""
    sr_records = [
        {"invoice_number": "INV/26-27/00001", "invoice_date": "2026-09-01", "taxable_amount_paise": 100000, "total_tax_paise": 18000},
        {"invoice_number": "INV/26-27/00002", "invoice_date": "2026-09-02", "taxable_amount_paise": 100000, "total_tax_paise": 18000},
        {"invoice_number": "INV/26-27/00004", "invoice_date": "2026-09-04", "taxable_amount_paise": 100000, "total_tax_paise": 18000},
        {"invoice_number": "INV/26-27/00005", "invoice_date": "2026-09-05", "taxable_amount_paise": 100000, "total_tax_paise": 18000},
    ]
    # GSTR-1 matches what is in SR
    gstr1_records = list(sr_records)

    mismatches = check_invoice_series_continuity(sr_records, gstr1_records)
    assert len(mismatches) == 1
    issue = mismatches[0]
    assert issue.mismatch_type == MismatchType.INVOICE_SERIES_ISSUE
    assert issue.details.get("issue_type") == "gap"
    assert issue.details.get("missing_count") == 1
    assert 3 in issue.details.get("missing_numbers", [])
    assert "INV/26-27/3" in issue.decision_next
    assert "cancelled" in issue.decision_next.lower()


# ══════════════════════════════════════════════════════════════════════════════
# Test 6: Multiple Legitimate Invoice Series
# ══════════════════════════════════════════════════════════════════════════════

def test_multiple_simultaneous_invoice_series():
    """Test 6: Multiple legitimate series (SALE vs SERVICE) evaluated independently without false gaps."""
    sr_records = [
        {"invoice_number": "SALE/26-27/001", "taxable_amount_paise": 50000, "total_tax_paise": 9000},
        {"invoice_number": "SALE/26-27/002", "taxable_amount_paise": 50000, "total_tax_paise": 9000},
        {"invoice_number": "SALE/26-27/003", "taxable_amount_paise": 50000, "total_tax_paise": 9000},
        {"invoice_number": "SERVICE/26-27/001", "taxable_amount_paise": 80000, "total_tax_paise": 14400},
        {"invoice_number": "SERVICE/26-27/002", "taxable_amount_paise": 80000, "total_tax_paise": 14400},
    ]
    gstr1_records = list(sr_records)

    mismatches = check_invoice_series_continuity(sr_records, gstr1_records)
    assert len(mismatches) == 0


# ══════════════════════════════════════════════════════════════════════════════
# Test 3: Actual B2B Missing Invoice
# ══════════════════════════════════════════════════════════════════════════════

def test_actual_b2b_missing_invoice():
    """Test 3: Statutory invoice-level B2B missing in GSTR-1 is flagged as G1M1 with appropriate advice."""
    sr_rec = {
        "invoice_number": "INV-2026-999",
        "taxable_amount_paise": 5000000,
        "total_tax_paise": 900000,
        "recipient_gstin": "27AAACB1234F1Z5",
        "document_type": "INVOICE",
    }
    mismatch = classify_missing_invoice(sr_rec)
    assert mismatch.mismatch_type == MismatchType.MISSING_INVOICE
    assert mismatch.rule_id == "G1M_001"
    assert "INV-2026-999" in mismatch.decision_what


# ══════════════════════════════════════════════════════════════════════════════
# Test 2: B2CS Aggregate Mismatch (Dimensional Variance)
# ══════════════════════════════════════════════════════════════════════════════

def test_b2cs_aggregate_mismatch_dimensional_variance():
    """Test 2: When Table 7 values differ from books, report aggregate dimensional variance without false invoice-level missing rows."""
    sr_b2cs = [
        {
            "invoice_number": f"B2C-{i}",
            "place_of_supply": "27",
            "rate": 18.0,
            "supply_type": "INTRA",
            "taxable_amount_paise": 1000000,
            "cgst_paise": 90000,
            "sgst_paise": 90000,
            "total_tax_paise": 180000,
        }
        for i in range(10)
    ]
    # Total SR taxable: 10 * 10,000 = 1,00,000 (10,000,000 paise)

    # GSTR-1 Table 7 reports only ₹80,000 taxable (variance of ₹20,000)
    gstr1_b2cs = [
        {
            "section": "b2cs",
            "place_of_supply": "27",
            "rate": 18.0,
            "supply_type": "INTRA",
            "taxable_amount_paise": 8000000,
            "cgst_paise": 720000,
            "sgst_paise": 720000,
            "total_tax_paise": 1440000,
        }
    ]

    res = reconcile_b2cs_aggregate(sr_b2cs, gstr1_b2cs, supplier_gstin="27ISKPK1273H1ZF")
    assert res.status == "MISMATCH"
    assert len(res.mismatches) == 1
    assert res.mismatches[0].rule_id == "G1M_003_B2CS_AGGREGATE"
    assert res.mismatches[0].details["taxable_diff"] == 2000000  # ₹20,000 in paise
    # Crucially, individual invoices are NOT created as missing rows
    assert res.source_invoice_count == 10
    assert res.accounted_invoice_count == 0


# ══════════════════════════════════════════════════════════════════════════════
# Test 9: Nil/Exempt 3B Tie-Out
# ══════════════════════════════════════════════════════════════════════════════

def test_nil_exempt_3b_tie_out_clean():
    """Test 9: Nil/exempt outward supplies reported in Table 8 / 3.1(c) reconcile cleanly against 3.1(c)."""
    # GSTR-1 records:
    # 3.1(a) taxable: ₹358,139,419.93 (35,813,941,993 paise)
    # Table 8 nil/exempt: ₹16,941,428.53 (1,694,142,853 paise)
    gstr1_records = [
        {
            "section": "b2b",
            "taxable_amount_paise": 35_813_941_993,
            "igst_paise": 3_223_254_779,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
            "total_tax_paise": 3_223_254_779,
        },
        {
            "section": "nil",
            "taxable_amount_paise": 1_694_142_853,
            "igst_paise": 0,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
            "total_tax_paise": 0,
        },
    ]

    gstr3b_summary = GSTR3BSummary(
        taxable_value_paise=35_813_941_993,     # 3.1(a)
        igst_paise=3_223_254_779,
        cgst_paise=0,
        sgst_paise=0,
        cess_paise=0,
        nil_exempt_taxable_paise=1_694_142_853, # 3.1(c)
    )

    tie_out = reconcile_gstr1_vs_3b(gstr1_records, gstr3b_summary)
    assert tie_out.is_clean is True
    assert tie_out.unexplained_difference_paise == 0
    assert tie_out.reclassification_difference_paise == 0
    assert len(tie_out.variances) == 0


# ══════════════════════════════════════════════════════════════════════════════
# Test 10: Real GSTR-3B Mismatch
# ══════════════════════════════════════════════════════════════════════════════

def test_real_gstr3b_mismatch_flagged():
    """Test 10: Real financial variance in Table 3.1(a) (e.g. ₹10,000 difference) is flagged as unexplained variance."""
    gstr1_records = [
        {
            "section": "b2b",
            "taxable_amount_paise": 10_000_000,  # ₹100,000
            "igst_paise": 1_800_000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
            "total_tax_paise": 1_800_000,
        },
    ]

    gstr3b_summary = GSTR3BSummary(
        taxable_value_paise=9_000_000,           # ₹90,000 (diff: ₹10,000 / 1,000,000 paise)
        igst_paise=1_800_000,
        cgst_paise=0,
        sgst_paise=0,
        cess_paise=0,
    )

    tie_out = reconcile_gstr1_vs_3b(gstr1_records, gstr3b_summary)
    assert tie_out.is_clean is False
    assert tie_out.unexplained_difference_paise == 1_000_000  # ₹10,000
    assert len(tie_out.variances) == 1
    assert tie_out.variances[0].field == "taxable_value"


# ══════════════════════════════════════════════════════════════════════════════
# Test 1: Clean September 2026 3,000-Record Benchmark
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_clean_september_2026_3000_record_benchmark():
    """Test 1: Full benchmark reconciliation matching the user's exact specification:

    GSTIN: 27ISKPK1273H1ZF
    Period: September 2026 (2026-09)
    Sales Register: 3,000 invoices:
      - 2,172 B2B invoices
      - 498 B2CL invoices (> ₹1L interstate)
      - 330 B2CS invoices (aggregated)
    GSTR-1:
      - 2,670 invoice-level rows (2,172 B2B + 498 B2CL)
      - Table 7 B2CS aggregate covering the 330 source invoices
      - Table 8 nil/exempt outward: ₹16,941,428.53
      - Combined GSTR-1 outward: ₹375,080,848.46
    GSTR-3B:
      - Table 3.1(a): ₹358,139,419.93
      - Table 3.1(c): ₹16,941,428.53
      - Combined outward: ₹375,080,848.46

    Expected Output:
      - 3,000 / 3,000 Sales Register invoices accounted for (100%)
      - 2,670 invoice-level matches
      - 330 aggregate source invoices covered
      - B2CS reconciliation status: MATCHED
      - Missing in GSTR-1: 0
      - Extra in GSTR-1: 0
      - Review Required: 0
      - Unexplained GSTR-1 vs GSTR-3B variance: ₹0
    """
    # 1. Build Sales Register CSV
    # Total taxable domestic outward: ₹358,139,419.93 = 358139419.93
    # 2,172 B2B + 498 B2CL = 2,670 invoices
    # 330 B2CS invoices
    # We distribute the value deterministically across the 3,000 invoices
    b2b_count = 2172
    b2cl_count = 498
    b2cs_count = 330

    sr_rows = [
        "Voucher Type,Invoice No,Document Date,Party Name,GSTIN,Place of Supply (State Code),HSN Code,Description,Taxable Value,IGST Rate %,IGST Amount,CGST Rate %,CGST Amount,SGST Rate %,SGST Amount,Invoice Value"
    ]

    # Pre-calculated deterministic amounts to sum to exact ₹358,139,419.93
    # 2172 B2B: ~₹280,000,000
    # 498 B2CL: ~₹70,000,000 (> ₹100,000 each)
    # 330 B2CS: ~₹8,139,419.93
    b2b_unit_tx = 130000.0  # 2172 * 130000 = 282,360,000
    b2cl_unit_tx = 140000.0  # 498 * 140000 = 69,720,000 (> 100k, so B2CL post Aug 2024!)
    b2cs_base_unit_tx = 18000.0
    # 329 * 18000 = 5,922,000
    # Remainder to make total exact:
    target_taxable = 358139419.93
    current_subtotal = (b2b_count * b2b_unit_tx) + (b2cl_count * b2cl_unit_tx) + ((b2cs_count - 1) * b2cs_base_unit_tx)
    b2cs_last_unit_tx = round(target_taxable - current_subtotal, 2)

    # Generate B2B rows
    g1_b2b_inv_list = []
    for i in range(1, b2b_count + 1):
        inv_no = f"INV-2627-{i:05d}"
        cgst = round(b2b_unit_tx * 0.09, 2)
        sgst = round(b2b_unit_tx * 0.09, 2)
        tot = round(b2b_unit_tx + cgst + sgst, 2)
        sr_rows.append(
            f"Sales,{inv_no},15/09/2026,Client {i},27AAACB{i:04d}A1Z1,27,8471,Hardware,{b2b_unit_tx},0,0,9,{cgst},9,{sgst},{tot}"
        )
        g1_b2b_inv_list.append({
            "inum": inv_no,
            "idt": "15-09-2026",
            "val": tot,
            "pos": "27",
            "rchrg": "N",
            "inv_typ": "R",
            "itms": [{
                "num": 1,
                "itm_det": {
                    "txval": b2b_unit_tx,
                    "rt": 18,
                    "iamt": 0,
                    "camt": cgst,
                    "samt": sgst,
                    "csamt": 0,
                },
            }],
        })

    # Generate B2CL rows (Interstate to state 24, value > 100k)
    g1_b2cl_inv_list = []
    for i in range(1, b2cl_count + 1):
        inv_no = f"B2CL-2627-{i:05d}"
        igst = round(b2cl_unit_tx * 0.18, 2)
        tot = round(b2cl_unit_tx + igst, 2)
        sr_rows.append(
            f"Sales,{inv_no},16/09/2026,Unregistered Buyer,None,24,8471,Hardware,{b2cl_unit_tx},18,{igst},0,0,0,0,{tot}"
        )
        g1_b2cl_inv_list.append({
            "inum": inv_no,
            "idt": "16-09-2026",
            "val": tot,
            "itms": [{
                "num": 1,
                "itm_det": {
                    "txval": b2cl_unit_tx,
                    "rt": 18,
                    "iamt": igst,
                    "csamt": 0,
                },
            }],
        })

    # Generate B2CS rows (Intrastate state 27, unregistered)
    total_b2cs_tx = 0.0
    total_b2cs_cgst = 0.0
    total_b2cs_sgst = 0.0
    for i in range(1, b2cs_count + 1):
        inv_no = f"RD/S/26-27/{i:05d}"
        tx = b2cs_last_unit_tx if i == b2cs_count else b2cs_base_unit_tx
        cgst = round(tx * 0.09, 2)
        sgst = round(tx * 0.09, 2)
        tot = round(tx + cgst + sgst, 2)
        total_b2cs_tx += tx
        total_b2cs_cgst += cgst
        total_b2cs_sgst += sgst
        sr_rows.append(
            f"Sales,{inv_no},18/09/2026,Retail Customer,None,27,8471,Hardware,{tx},0,0,9,{cgst},9,{sgst},{tot}"
        )

    total_b2cs_tx = round(total_b2cs_tx, 2)
    total_b2cs_cgst = round(total_b2cs_cgst, 2)
    total_b2cs_sgst = round(total_b2cs_sgst, 2)

    # GSTR-1 payload:
    # 2172 B2B + 498 B2CL
    # Table 7 B2CS consolidated
    # Table 8 nil/exempt outward: 16,941,428.53
    gstr1_dict = {
        "gstin": "27ISKPK1273H1ZF",
        "fp": "092026",
        "b2b": [
            {
                "ctin": f"27AAACB{i:04d}A1Z1",
                "inv": [g1_b2b_inv_list[i - 1]],
            }
            for i in range(1, b2b_count + 1)
        ],
        "b2cl": [
            {
                "pos": "24",
                "inv": g1_b2cl_inv_list,
            }
        ],
        "b2cs": [
            {
                "sply_tp": "INTRA",
                "pos": "27",
                "typ": "OE",
                "rt": 18,
                "txval": total_b2cs_tx,
                "iamt": 0,
                "camt": total_b2cs_cgst,
                "samt": total_b2cs_sgst,
                "csamt": 0,
            }
        ],
        "nil": {
            "inv": [
                {
                    "nil_amt": 16941428.53,
                    "expt_amt": 0,
                    "ngsup_amt": 0,
                    "sply_ty": "INTRAR",
                }
            ]
        },
    }

    # GSTR-3B payload:
    # 3.1(a) = 358,139,419.93
    # 3.1(c) = 16,941,428.53
    total_igst = round(b2cl_count * b2cl_unit_tx * 0.18, 2)
    total_cgst = round((b2b_count * b2b_unit_tx * 0.09) + total_b2cs_cgst, 2)
    total_sgst = round((b2b_count * b2b_unit_tx * 0.09) + total_b2cs_sgst, 2)

    gstr3b_dict = {
        "gstin": "27ISKPK1273H1ZF",
        "ret_period": "092026",
        "sup_details": {
            "osup_det": {
                "txval": 358139419.93,
                "iamt": total_igst,
                "camt": total_cgst,
                "samt": total_sgst,
                "csamt": 0,
            },
            "osup_nil_exmp": {
                "txval": 16941428.53,
            },
        },
    }

    sr_csv_bytes = "\n".join(sr_rows).encode("utf-8")
    g1_json_bytes = json.dumps(gstr1_dict).encode("utf-8")
    g3b_json_bytes = json.dumps(gstr3b_dict).encode("utf-8")

    # Run full reconciliation pipeline
    res = await _run_pipeline(
        sr_file_content=sr_csv_bytes,
        sr_filename="sales_register_sep2026.csv",
        gstr1_file_content=g1_json_bytes,
        gstr3b_file_content=g3b_json_bytes,
        gstr1_filing_period="092026",
    )

    summary = res["summary"]

    # Verify all expected clean reconciliation metrics:
    # 1. Sales Register count: 3,000
    assert summary["sr_total_records"] == 3000

    # 2. Invoice-level matches: 2,670 (2,172 B2B + 498 B2CL)
    assert summary["invoice_level_match_count"] == 2670
    assert summary["matched_count"] == 2670
    assert len(res["matched"]) == 2670

    # 3. Aggregate coverage: 330 source invoices accounted for
    assert summary["aggregate_source_invoice_count"] == 330
    assert summary["b2cs_reconciliation_status"] == "MATCHED"

    # 4. Overall Sales Register coverage: 3,000 / 3,000 (100%)
    assert summary["accounted_source_invoice_count"] == 3000
    assert summary["unaccounted_source_invoice_count"] == 0
    assert summary["coverage_percentage"] == 100.0

    # 5. Missing / Extra / Review: 0
    assert summary["unmatched_sr_count"] == 0
    assert summary["unmatched_gstr1_count"] == 0
    # Zero invoice-level mismatches (genuine Missing = 0, Extra = 0, Review = 0)
    genuine_invoice_mismatches = [
        m for m in res["mismatches"]
        if m.get("mismatch_type") in ("G1M1_MISSING_INVOICE", "G1M2_EXTRA_INVOICE", "G1M3_AMOUNT_MISMATCH")
    ]
    assert len(genuine_invoice_mismatches) == 0

    # 6. GSTR-1 vs GSTR-3B tie-out: Clean, ₹0 unexplained variance!
    assert summary["tie_out_clean"] is True
    assert summary["tie_out_variance_count"] == 0
    tie_out = res["tie_out"]
    assert tie_out["unexplained_difference_paise"] == 0
    assert tie_out["unexplained_difference"] == 0.0
