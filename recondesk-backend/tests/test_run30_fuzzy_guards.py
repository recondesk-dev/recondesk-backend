"""Regression tests for Run 30 Fuzzy Sequence Insertion and Terminal Mismatch Guards.

Covers:
1. Meaningful numeric sequence insertion:
   - Pairs with inserted non-zero digits within numeric sequences (e.g. 00050 ↔ 300050,
     00067 ↔ 300067, 000194 ↔ 0300194) must NOT clean auto-match.
   - When GSTIN, date, amount, and tax corroborate in bidirectional reconciliation,
     route to Review Required (TYPO_MISMATCH).
2. Material terminal sequence mismatch:
   - Invoices with materially different terminal sequences (e.g. 00009 ↔ 00056,
     BILL/00009/26 ↔ BILL/00056/26) must NEVER clean match.
3. Harmless leading-zero preservation:
   - Differences consisting only of leading zero padding (e.g. 000009 ↔ 00009,
     000032 ↔ 00032, 00035 ↔ 0035) must continue to clean match at Level 1 or 2.
4. Normal safe single-OCR clean matching:
   - Normal-length invoices with a single OCR substitution (e.g. BILL-00042O ↔ BILL-000420,
     AP-SEP26-00015 ↔ AP-SEP26-0001S) continue to clean auto-match.
5. End-to-End Run 30 Fixture Verification:
   - 0 clean matches in SEQUENCE_INSERT_REVIEW
   - 0 clean matches in TERMINAL_SEQUENCE_MISMATCH_NO_MATCH
   - BILL/00009/26 ↔ BILL/00056/26 is no longer clean-matched
   - Exact conservation: PR == 5,000, GSTR-2B == 4,780, Duplicates == 90.
"""

from pathlib import Path
import pytest

from app.services.matcher import (
    _match_gstr_to_pr_pair,
    is_meaningful_numeric_sequence_mismatch,
    is_invoice_format_variant,
    invoices_effectively_match,
    normalize_invoice,
)
from app.matching.engine import run_bidirectional_reconciliation


# ── 1. NON-ZERO SEQUENCE INSERTION (NEVER CLEAN MATCH) ─────────────────────────


@pytest.mark.parametrize(
    "g_inv,p_inv",
    [
        ("TXN/0926/00050", "TXN/0926/300050"),
        ("INV/0926/00067", "INV/0926/300067"),
        ("BILL000194", "BILL0300194"),
        ("GRN/0926/00165", "GRN/0926/900165"),
        ("BILL/00397/26", "BILL/700397/26"),
        ("00050", "300050"),
        ("00067", "300067"),
        ("000194", "0300194"),
    ],
)
def test_sequence_insertion_never_clean_matches(g_inv: str, p_inv: str):
    """Invoices with inserted non-zero digits within sequence must NOT clean match."""
    assert is_meaningful_numeric_sequence_mismatch(g_inv, p_inv) is True
    assert is_invoice_format_variant(g_inv, p_inv) is False
    assert invoices_effectively_match(g_inv, p_inv) is False

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
    # Must never be a clean match (either not matched or requires human review)
    assert not (res.matched and not res.requires_human_review)


@pytest.mark.parametrize(
    "g_inv,p_inv",
    [
        ("TXN/0926/00050", "TXN/0926/300050"),
        ("INV/0926/00067", "INV/0926/300067"),
        ("GRN/0926/00165", "GRN/0926/900165"),
        ("BILL/00397/26", "BILL/700397/26"),
    ],
)
def test_sequence_insertion_corroborated_routes_to_review(g_inv: str, p_inv: str):
    """Corroborated invoice sequence insertion pairs route to Review Required in bidirectional engine."""
    g = [{
        "id": "g_1",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_number": g_inv,
        "invoice_number_normalized": normalize_invoice(g_inv),
        "invoice_date": "2026-09-15",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }]
    p = [{
        "id": "p_1",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_number": p_inv,
        "invoice_number_normalized": normalize_invoice(p_inv),
        "invoice_date": "2026-09-15",
        "taxable_amount_paise": 1000000,
        "total_tax_paise": 180000,
        "igst_paise": 180000,
        "cgst_paise": 0,
        "sgst_paise": 0,
    }]
    recon = run_bidirectional_reconciliation(g, p, gstr_period="2026-09-01")
    assert len(recon["matched"]) == 0
    assert len(recon["review_required"]) == 1
    assert recon["review_required"][0]["review_reason"] == "TYPO_MISMATCH"


# ── 2. MATERIAL TERMINAL SEQUENCE MISMATCH ─────────────────────────────────────


@pytest.mark.parametrize(
    "g_inv,p_inv",
    [
        ("BILL/00009/26", "BILL/00056/26"),
        ("00009", "00056"),
        ("INV-00009", "INV-00056"),
    ],
)
def test_terminal_sequence_mismatch_never_clean_matches(g_inv: str, p_inv: str):
    """Material sequence differences (e.g. 00009 vs 00056) must NEVER clean match."""
    assert is_meaningful_numeric_sequence_mismatch(g_inv, p_inv) is True
    assert is_invoice_format_variant(g_inv, p_inv) is False
    assert invoices_effectively_match(g_inv, p_inv) is False

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
    # Must either be routed to human review or not clean-matched
    assert not (res.matched and not res.requires_human_review)


# ── 3. HARMLESS LEADING-ZERO NORMALIZATION (CLEAN MATCH) ────────────────────────


@pytest.mark.parametrize(
    "g_inv,p_inv",
    [
        ("TXN000009", "TXN00009"),
        ("SUP000032", "SUP00032"),
        ("TAX-00035-A", "TAX-0035-A"),
        ("000009", "00009"),
        ("000032", "00032"),
        ("00035", "0035"),
    ],
)
def test_harmless_leading_zeros_clean_match(g_inv: str, p_inv: str):
    """Harmless leading-zero variations must continue to clean match."""
    assert is_meaningful_numeric_sequence_mismatch(g_inv, p_inv) is False
    assert (
        invoices_effectively_match(g_inv, p_inv)
        or is_invoice_format_variant(g_inv, p_inv)
    )

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


# ── 4. NORMAL SAFE SINGLE-OCR CLEAN MATCHING ───────────────────────────────────


@pytest.mark.parametrize(
    "g_inv,p_inv",
    [
        ("BILL-00042O", "BILL-000420"),
        ("AP-SEP26-00015", "AP-SEP26-0001S"),
        ("SUP/0926/00504", "SUP92600S4"),
    ],
)
def test_normal_length_single_ocr_clean_matches(g_inv: str, p_inv: str):
    """Normal-length invoices with a single OCR substitution continue to clean auto-match."""
    assert is_meaningful_numeric_sequence_mismatch(g_inv, p_inv) is False

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


# ── 5. EXACT RUN 30 FIXTURE RECONCILIATION ─────────────────────────────────────


def test_run30_fixture_reconciliation_exact_bucket_counts():
    """Verify Run 30 full 5000-row fixture reconciliation counts and conservation."""
    gstr_path = Path("test_data/runs/ReconDesk_GSTR2B_5000_Run30_PureFuzzy_Sep2026.json")
    pr_path = Path("test_data/runs/ReconDesk_Purchase_Register_5000_Run30_PureFuzzy_Sep2026.xlsx")

    if not gstr_path.exists() or not pr_path.exists():
        pytest.skip("Run 30 test fixture files not found.")

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
    # 1. SEQUENCE_INSERT_REVIEW: clean matches must be 0, all 102 corroborated pairs in Review Required
    assert scenario_buckets["SEQUENCE_INSERT_REVIEW"]["matched"] == 0
    assert scenario_buckets["SEQUENCE_INSERT_REVIEW"]["review_required"] == 102

    # 2. TERMINAL_SEQUENCE_MISMATCH_NO_MATCH: clean matches must be 0
    assert scenario_buckets["TERMINAL_SEQUENCE_MISMATCH_NO_MATCH"]["matched"] == 0

    # 3. LEADING_ZERO_SAFE: unchanged
    assert scenario_buckets["LEADING_ZERO_SAFE"]["matched"] == 149
    assert scenario_buckets["LEADING_ZERO_SAFE"]["review_required"] == 1

    # 4. Duplicate count remains exactly 90
    assert len(recon.get("duplicate_entries", [])) == 90

    # 5. Total bucket counts
    matched_count = len(recon.get("matched", []))
    review_count = len(recon.get("review_required", []))
    missed_itc_count = len(recon.get("missed_itc", []))
    wrongful_itc_count = len(recon.get("wrongful_itc_risk", []))

    assert matched_count == 3595
    assert review_count == 783
    assert missed_itc_count == 402
    assert wrongful_itc_count == 532

    # 6. Conservation laws
    # PR conservation: matched (3595) + review (783) + wrongful_itc (532) + duplicates (90) = 5,000
    assert matched_count + review_count + wrongful_itc_count + len(recon.get("duplicate_entries", [])) == 5000

    # GSTR-2B conservation: matched (3595) + review (783) + missed_itc (402) = 4,780
    assert matched_count + review_count + missed_itc_count == 4780
