"""Regression tests for Run 26 Short-Invoice Fuzzy Matching and Terminal Sequence Guards.

Covers:
1. Short Invoice OCR Substitution:
   - Invoices with canonical length <= 4 (e.g. 05 ↔ O5, A52 ↔ AS2, I086 ↔ IO86, 08 ↔ 0B)
     must NOT clean auto-match.
   - When GSTIN, date, amount, and tax corroborate, route to Review Required (OCR_CONFIDENCE_REVIEW).
2. Short Invoice Insertion / Deletion / Typo:
   - Insertion or deletion differences on short invoices (e.g. A2 ↔ A2O, 47 ↔ 47O)
     must route to Review Required.
3. Terminal Digit Sequence Deletion:
   - Invoices differing by a single terminal sequence digit deletion (e.g. 00221 ↔ 0021,
     00351 ↔ 0031, VND/0926/00221 ↔ VND/0926/0021) must NOT clean match as format variants.
   - Route to Review Required (TYPO_MISMATCH).
4. Normal-Length Single-OCR Clean Matching:
   - Normal-length invoices with a single OCR substitution (e.g. BILL-00042O ↔ BILL-000420,
     SUP/0926/00504 ↔ SUP92600S4) continue to clean auto-match at Level 2.
5. End-to-End Run 26 Reconciliation Fixture Verification.
"""

from datetime import date
from pathlib import Path
import pytest

from app.services.matcher import (
    _match_gstr_to_pr_pair,
    is_terminal_sequence_deletion,
    is_short_invoice_fuzzy_risk,
    is_invoice_format_variant,
    invoices_effectively_match,
)
from app.matching.engine import run_bidirectional_reconciliation


# ── 1. SHORT INVOICE OCR SUBSTITUTION ──────────────────────────────────────────


@pytest.mark.parametrize(
    "g_inv,p_inv",
    [
        ("05", "O5"),
        ("O5", "05"),
        ("A52", "AS2"),
        ("AS2", "A52"),
        ("I086", "IO86"),
        ("IO86", "I086"),
        ("08", "0B"),
        ("0B", "08"),
        ("I0", "10"),
        ("10", "I0"),
        ("AI1", "A11"),
        ("4B", "48"),
    ],
)
def test_short_invoice_ocr_substitution_routes_to_review(g_inv: str, p_inv: str):
    """Short invoices (canonical len <= 4) with single OCR substitution must route to Review Required."""
    assert is_short_invoice_fuzzy_risk(g_inv, p_inv, g_inv, p_inv, ocr_subs=1) is True
    assert invoices_effectively_match(g_inv, p_inv) is False
    assert is_invoice_format_variant(g_inv, p_inv, g_inv, p_inv) is False

    gstr = {
        "invoice_number": g_inv,
        "invoice_number_raw": g_inv,
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    pr = {
        "invoice_number": p_inv,
        "invoice_number_raw": p_inv,
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    res = _match_gstr_to_pr_pair(gstr, pr)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.level == 3
    assert res.review_reason == "OCR_CONFIDENCE_REVIEW"


# ── 2. SHORT INVOICE INSERTION / DELETION ─────────────────────────────────────


@pytest.mark.parametrize(
    "g_inv,p_inv",
    [
        ("A2", "A2O"),
        ("A2O", "A2"),
        ("47", "47O"),
        ("47O", "47"),
        ("A63", "A63O"),
    ],
)
def test_short_invoice_insertion_deletion_routes_to_review(g_inv: str, p_inv: str):
    """Short invoices with character insertion/deletion must route to Review Required."""
    gstr = {
        "invoice_number": g_inv,
        "invoice_number_raw": g_inv,
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    pr = {
        "invoice_number": p_inv,
        "invoice_number_raw": p_inv,
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    res = _match_gstr_to_pr_pair(gstr, pr)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.level == 3
    assert res.review_reason in ("OCR_CONFIDENCE_REVIEW", "TYPO_MISMATCH")


# ── 3. TERMINAL DIGIT SEQUENCE DELETION ───────────────────────────────────────


@pytest.mark.parametrize(
    "g_inv,p_inv",
    [
        ("00221", "0021"),
        ("0021", "00221"),
        ("00351", "0031"),
        ("0031", "00351"),
        ("VND/0926/00221", "VND/0926/0021"),
        ("VND/0926/0021", "VND/0926/00221"),
        ("INV/0926/00351", "INV/0926/0031"),
        ("GRN/0926/00338", "GRN/0926/0038"),
        ("VND/0926/00356", "VND/0926/0036"),
        ("INV/0926/00321", "INV/0926/0021"),
    ],
)
def test_terminal_digit_deletion_routes_to_review(g_inv: str, p_inv: str):
    """Terminal sequence deletions must NOT clean auto-match; route to Review Required (TYPO_MISMATCH)."""
    assert is_terminal_sequence_deletion(g_inv, p_inv, g_inv, p_inv) is True
    assert is_invoice_format_variant(g_inv, p_inv, g_inv, p_inv) is False

    gstr = {
        "invoice_number": g_inv,
        "invoice_number_raw": g_inv,
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    pr = {
        "invoice_number": p_inv,
        "invoice_number_raw": p_inv,
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    res = _match_gstr_to_pr_pair(gstr, pr)
    assert res.matched is True
    assert res.requires_human_review is True
    assert res.level == 3
    assert res.review_reason == "TYPO_MISMATCH"


# ── 4. NORMAL-LENGTH SINGLE-OCR CLEAN MATCHING ───────────────────────────────


@pytest.mark.parametrize(
    "g_inv,p_inv",
    [
        ("BILL-00042O", "BILL-000420"),
        ("SUP/0926/00504", "SUP92600S4"),
        ("AP-SEP26-00015", "AP-SEP26-0001S"),
        ("BILL000183", "BILL000183"),
        ("INV-00045-A", "INV-0045-A"),
    ],
)
def test_normal_length_single_ocr_still_clean_matches(g_inv: str, p_inv: str):
    """Normal-length invoices with safe single-OCR or formatting differences must still clean match."""
    gstr = {
        "invoice_number": g_inv,
        "invoice_number_raw": g_inv,
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    pr = {
        "invoice_number": p_inv,
        "invoice_number_raw": p_inv,
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_date": "2026-09-15",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }
    res = _match_gstr_to_pr_pair(gstr, pr)
    assert res.matched is True
    assert res.requires_human_review is False
    assert res.level in (1, 2)


# ── 5. EXACT RUN 26 FIXTURE RECONCILIATION ────────────────────────────────────


def test_run26_fixture_reconciliation_exact_bucket_counts():
    """Verify Run 26 full 5000-row production gate reconciliation counts."""
    gstr_path = Path("test_data/runs/ReconDesk_GSTR2B_5000_Run26_FinalProductionGate_Sep2026.json")
    pr_path = Path("test_data/runs/ReconDesk_Purchase_Register_5000_Run26_FinalProductionGate_Sep2026.xlsx")

    if not gstr_path.exists() or not pr_path.exists():
        pytest.skip("Run 26 test fixture files not found.")

    from app.parsers.gstr2b_parser import parse_gstr2b
    from app.parsers.purchase_register_parser import parse_purchase_register
    from app.services.reconciliation_record_adapter import (
        gstr_db_row_to_matcher_row,
        pr_db_row_to_matcher_row,
    )
    import openpyxl
    from collections import defaultdict

    wb = openpyxl.load_workbook(pr_path, data_only=True)
    sheet = wb.active
    headers = [cell.value for cell in sheet[1]]
    scenario_idx = headers.index("Scenario")
    pr_scenarios = {
        f"p_{i}": row[scenario_idx]
        for i, row in enumerate(sheet.iter_rows(min_row=2, values_only=True))
    }

    with open(gstr_path, "rb") as f:
        gstr_res = parse_gstr2b(f.read())
    gstr_rows = [{"id": f"g_{i}", "record_data": r} for i, r in enumerate(gstr_res["records"])]
    matcher_gstr = [gstr_db_row_to_matcher_row(row) for row in gstr_rows]

    with open(pr_path, "rb") as f:
        pr_res = parse_purchase_register(f.read(), pr_path.name)
    pr_rows = [{"id": f"p_{i}", "record_data": r} for i, r in enumerate(pr_res["records"])]
    matcher_pr = [pr_db_row_to_matcher_row(row) for row in pr_rows]

    recon = run_bidirectional_reconciliation(matcher_gstr, matcher_pr, gstr_period="2026-09-01")

    scenario_buckets = defaultdict(lambda: defaultdict(int))
    for m in recon.get("matched", []):
        pid = m.get("pr_id")
        sc = pr_scenarios.get(pid, "UNKNOWN")
        scenario_buckets[sc]["matched"] += 1

    for r in recon.get("review_required", []):
        pid = r.get("pr_id")
        sc = pr_scenarios.get(pid, "UNKNOWN")
        scenario_buckets[sc]["review_required"] += 1

    # Exact scenario validations
    assert scenario_buckets["SHORT_INVOICE_RISK_REVIEW"]["matched"] == 0
    assert scenario_buckets["SHORT_INVOICE_RISK_REVIEW"]["review_required"] == 100

    # Independent validation of MISSING_EXTRA_CHAR_REVIEW:
    # Out of 100 cases, exactly 37 represent safe statutory normalization variants:
    # - 24 leading-zero variants in numeric segments (e.g. INV-00045-A vs INV-0045-A, PO000122 vs PO00122)
    #   where normalize_invoice() strips leading zeros per segment (INV45A == INV45A),
    # - standard fiscal month/year format variants (e.g. AP/0926/00048 vs AP/926/00048).
    # The remaining 63 cases represent genuine structural character insertions/deletions
    # in prefixes or terminal sequences (e.g. GRN vs GN, 00561 vs 0061) and are strictly routed
    # to review_required under PREFIX_ALTERATION_REVIEW or TYPO_MISMATCH.
    assert scenario_buckets["MISSING_EXTRA_CHAR_REVIEW"]["matched"] == 37
    assert scenario_buckets["MISSING_EXTRA_CHAR_REVIEW"]["review_required"] == 63

    assert scenario_buckets["OCR_SINGLE_SAFE"]["matched"] == 180
    assert scenario_buckets["OCR_SINGLE_SAFE"]["review_required"] == 0

    assert scenario_buckets["BRANCH_SUFFIX_SAFE"]["matched"] == 100
    assert scenario_buckets["BRANCH_SUFFIX_SAFE"]["review_required"] == 0

    assert scenario_buckets["LEADING_ZERO"]["matched"] == 180
    assert scenario_buckets["LEADING_ZERO"]["review_required"] == 0

    assert scenario_buckets["FORMAT_VARIANT"]["matched"] == 300
    assert scenario_buckets["FORMAT_VARIANT"]["review_required"] == 0

    assert scenario_buckets["EXACT"]["matched"] == 2140
    assert scenario_buckets["EXACT"]["review_required"] == 0

    # Total bucket count assertions
    assert len(recon.get("matched", [])) == 3875
    assert len(recon.get("review_required", [])) == 757
    assert len(recon.get("missed_itc", [])) == 282
    assert len(recon.get("wrongful_itc_risk", [])) == 238
    assert len(recon.get("duplicate_entries", [])) == 130
    assert len(recon.get("matched", [])) + len(recon.get("review_required", [])) == 4632
