"""
Independent verification: L1 (EXACT) classification correctness.

Creates 20 synthetic "Matched" records covering diverse edge cases, then
re-verifies raw field equality **outside** the matcher code by doing
byte-exact comparisons on the four critical fields:
  - supplier_gstin  (case-insensitive, stripped)
  - invoice_number  (normalised: alnum-only, upper, leading-zeros stripped)
  - invoice_date    (ISO date equality)
  - taxable_amount_paise + total_tax_paise  (within ₹1 / 100 paise)

Any record where the matcher assigned level=1 (EXACT) but these raw
equality checks disagree is a false-exact classification.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from app.services.matcher import (
    MatchResult,
    _match_gstr_to_pr_pair,
    normalize_invoice,
    AMOUNT_TOLERANCE_L1_PAISE,
    DATE_TOLERANCE_L1_DAYS,
)


# ─────────── test data generators ───────────────────────────────────────────

def _gstin(i: int) -> str:
    return f"27AAECR{i:04d}M1ZP"


def _make_pair(
    idx: int,
    *,
    # Field perturbations (all default to "identical")
    gstin_mismatch: bool = False,
    invoice_format_variant: bool = False,
    invoice_typo: bool = False,
    amount_diff_paise: int = 0,
    tax_diff_paise: int = 0,
    date_diff_days: int = 0,
    missing_date: bool = False,
    missing_amount: bool = False,
    missing_tax_breakdown: bool = False,
) -> tuple[dict, dict, str]:
    """Return (gstr_row, pr_row, case_description)."""
    gstin_g = _gstin(idx)
    gstin_p = _gstin(idx) if not gstin_mismatch else _gstin(idx + 1000)

    inv_g = f"INV-2026-{idx:05d}"
    if invoice_format_variant:
        inv_p = f"INV202600{idx:05d}"  # different separators / zero-padding
    elif invoice_typo:
        inv_p = f"INX-2026-{idx:05d}"  # single-char diff
    else:
        inv_p = inv_g

    base_date = date(2026, 5, 10)
    date_g = base_date
    date_p = None if missing_date else (base_date + timedelta(days=date_diff_days))

    taxable_g = 1_000_000 + idx * 137
    taxable_p = None if missing_amount else (taxable_g + amount_diff_paise)
    igst_g = int(round(taxable_g * 0.18))
    igst_p = None if missing_amount else (igst_g + tax_diff_paise)

    gstr = {
        "id": f"g_{idx}",
        "supplier_gstin": gstin_g,
        "invoice_number": inv_g,
        "invoice_number_normalized": normalize_invoice(inv_g),
        "invoice_date": date_g.isoformat(),
        "taxable_amount_paise": taxable_g,
        "igst_paise": igst_g,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "total_tax_paise": igst_g,
    }
    pr = {
        "id": f"p_{idx}",
        "supplier_gstin": gstin_p,
        "invoice_number": inv_p,
        "invoice_number_normalized": normalize_invoice(inv_p),
        "invoice_date": date_p.isoformat() if date_p else None,
        "taxable_amount_paise": taxable_p,
        "igst_paise": None if missing_tax_breakdown else igst_p,
        "cgst_paise": None if missing_tax_breakdown else 0,
        "sgst_paise": None if missing_tax_breakdown else 0,
        "total_tax_paise": igst_p,
    }
    parts = []
    if gstin_mismatch:
        parts.append("GSTIN_DIFF")
    if invoice_format_variant:
        parts.append("INV_FORMAT_VAR")
    if invoice_typo:
        parts.append("INV_TYPO")
    if amount_diff_paise:
        parts.append(f"AMT_DIFF={amount_diff_paise}p")
    if tax_diff_paise:
        parts.append(f"TAX_DIFF={tax_diff_paise}p")
    if date_diff_days:
        parts.append(f"DATE_DIFF={date_diff_days}d")
    if missing_date:
        parts.append("MISSING_DATE")
    if missing_amount:
        parts.append("MISSING_AMT")
    if missing_tax_breakdown:
        parts.append("NO_TAX_BREAKDOWN")
    desc = ", ".join(parts) or "PERFECT_MATCH"
    return gstr, pr, desc


# ─────────── independent raw-field equality check ───────────────────────────

def _raw_fields_match(gstr: dict, pr: dict) -> tuple[bool, list[str]]:
    """Check the four critical fields with NO tolerance beyond what L1 allows.

    Returns (all_match, list_of_mismatches).
    """
    mismatches: list[str] = []

    # 1. GSTIN: case-insensitive, stripped
    g_gst = (gstr.get("supplier_gstin") or "").strip().upper()
    p_gst = (pr.get("supplier_gstin") or "").strip().upper()
    if g_gst != p_gst:
        mismatches.append(f"GSTIN: {g_gst!r} vs {p_gst!r}")

    # 2. Invoice number: normalised form must be identical
    g_inv = normalize_invoice(gstr.get("invoice_number_normalized") or gstr.get("invoice_number"))
    p_inv = normalize_invoice(pr.get("invoice_number_normalized") or pr.get("invoice_number"))
    if g_inv != p_inv:
        mismatches.append(f"INVOICE: {g_inv!r} vs {p_inv!r}")

    # 3. Date: must be identical ISO dates, or one missing (skip_date → tolerance)
    g_date = gstr.get("invoice_date")
    p_date = pr.get("invoice_date")
    if g_date and p_date:
        # Both present — must be within DATE_TOLERANCE_L1_DAYS
        try:
            gd = date.fromisoformat(str(g_date))
            pd = date.fromisoformat(str(p_date))
            if abs((gd - pd).days) > DATE_TOLERANCE_L1_DAYS:
                mismatches.append(f"DATE: {g_date} vs {p_date} (diff>{DATE_TOLERANCE_L1_DAYS}d)")
        except (ValueError, TypeError):
            pass
    # If one is missing, skip_date is True → L1 allows it

    # 4. Amounts: taxable_amount_paise within AMOUNT_TOLERANCE_L1_PAISE (₹1)
    g_tax = gstr.get("taxable_amount_paise")
    p_tax = pr.get("taxable_amount_paise")
    if g_tax is not None and p_tax is not None:
        diff = abs(int(g_tax) - int(p_tax))
        if diff > AMOUNT_TOLERANCE_L1_PAISE:
            mismatches.append(f"TAXABLE: {g_tax} vs {p_tax} (diff={diff} paise)")

    # 4b. Total tax within tolerance
    g_tt = gstr.get("total_tax_paise")
    p_tt = pr.get("total_tax_paise")
    if g_tt is not None and p_tt is not None:
        tt_diff = abs(int(g_tt) - int(p_tt))
        if tt_diff > AMOUNT_TOLERANCE_L1_PAISE:
            mismatches.append(f"TOTAL_TAX: {g_tt} vs {p_tt} (diff={tt_diff} paise)")

    return len(mismatches) == 0, mismatches


# ─────────── 20 test cases ──────────────────────────────────────────────────

# The first 10 MUST be L1 (no field diffs), the next 10 MUST NOT be L1
# (they have deliberate field differences).
TEST_CASES = [
    # --- Expected L1 (truly exact) ---
    dict(idx=1),                                                      # perfect match
    dict(idx=2, missing_tax_breakdown=True),                          # PR has no IGST/CGST split
    dict(idx=3, amount_diff_paise=50),                                # within ₹0.50 rounding
    dict(idx=4, amount_diff_paise=100),                               # exactly ₹1 boundary
    dict(idx=5, date_diff_days=1),                                    # 1-day off (within L1)
    dict(idx=6, date_diff_days=3),                                    # exactly 3-day boundary
    dict(idx=7, missing_date=True),                                   # date missing on PR side
    dict(idx=8, amount_diff_paise=99),                                 # within ₹0.99 rounding
    dict(idx=9, tax_diff_paise=50),                                   # total_tax within ₹0.50
    dict(idx=10, amount_diff_paise=100, tax_diff_paise=100),          # both at boundary
    # --- Expected NOT L1 (field differences beyond tolerance) ---
    dict(idx=11, amount_diff_paise=101),                              # ₹1.01 — beyond L1
    dict(idx=12, date_diff_days=4),                                   # 4 days — beyond L1
    dict(idx=13, gstin_mismatch=True),                                # different GSTIN
    dict(idx=14, invoice_typo=True),                                  # invoice number typo
    dict(idx=15, amount_diff_paise=5000),                             # ₹50 diff
    dict(idx=16, tax_diff_paise=200),                                 # total_tax ₹2 off
    dict(idx=17, amount_diff_paise=101, date_diff_days=4),            # both beyond
    dict(idx=18, gstin_mismatch=True, amount_diff_paise=0),           # GSTIN diff, amounts ok
    dict(idx=19, invoice_format_variant=True, amount_diff_paise=200), # format variant + amt diff
    dict(idx=20, amount_diff_paise=100, tax_diff_paise=200),          # taxable ok, tax not
    dict(idx=21, missing_amount=True),                                # missing amount → total mismatch
]


class TestL1ExactClassificationIntegrity:
    """Run each of the 20 cases through the matcher, then independently
    verify raw field equality. Report any false-exact classifications."""

    def _run_case(self, case_kwargs):
        gstr, pr, desc = _make_pair(**case_kwargs)
        result = _match_gstr_to_pr_pair(gstr, pr)
        raw_ok, mismatches = _raw_fields_match(gstr, pr)
        return gstr, pr, desc, result, raw_ok, mismatches

    # ── Positive cases: should be L1 ────────────────────────────────────

    def test_case_01_perfect_match_is_l1(self):
        _, _, desc, result, raw_ok, mm = self._run_case(TEST_CASES[0])
        assert result.level == 1, f"{desc}: expected L1, got L{result.level}"
        assert raw_ok, f"{desc}: raw mismatch in supposedly-exact pair: {mm}"

    def test_case_02_missing_breakdown_is_l1(self):
        _, _, desc, result, raw_ok, mm = self._run_case(TEST_CASES[1])
        assert result.level == 1, f"{desc}: expected L1, got L{result.level}"
        assert raw_ok, f"{desc}: raw mismatch: {mm}"

    def test_case_03_50paise_diff_is_l1(self):
        _, _, desc, result, raw_ok, _ = self._run_case(TEST_CASES[2])
        assert result.level == 1, f"{desc}: expected L1, got L{result.level}"

    def test_case_04_100paise_boundary_is_l1(self):
        _, _, desc, result, raw_ok, _ = self._run_case(TEST_CASES[3])
        assert result.level == 1, f"{desc}: expected L1, got L{result.level}"

    def test_case_05_1day_diff_is_l1(self):
        _, _, desc, result, _, _ = self._run_case(TEST_CASES[4])
        assert result.level == 1, f"{desc}: expected L1, got L{result.level}"

    def test_case_06_3day_boundary_is_l1(self):
        _, _, desc, result, _, _ = self._run_case(TEST_CASES[5])
        assert result.level == 1, f"{desc}: expected L1, got L{result.level}"

    def test_case_07_missing_date_is_l1(self):
        _, _, desc, result, _, _ = self._run_case(TEST_CASES[6])
        assert result.level == 1, f"{desc}: expected L1, got L{result.level}"

    def test_case_08_99paise_diff_is_l1(self):
        _, _, desc, result, _, _ = self._run_case(TEST_CASES[7])
        assert result.level == 1, f"{desc}: expected L1, got L{result.level}"

    def test_case_09_50paise_tax_diff_is_l1(self):
        _, _, desc, result, _, _ = self._run_case(TEST_CASES[8])
        assert result.level == 1, f"{desc}: expected L1, got L{result.level}"

    def test_case_10_boundary_both_is_l1(self):
        _, _, desc, result, _, _ = self._run_case(TEST_CASES[9])
        assert result.level == 1, f"{desc}: expected L1, got L{result.level}"

    # ── Negative cases: must NOT be L1 ──────────────────────────────────

    def test_case_11_101paise_is_not_l1(self):
        _, _, desc, result, _, _ = self._run_case(TEST_CASES[10])
        assert result.level != 1, f"{desc}: should NOT be L1 (amount beyond tolerance)"

    def test_case_12_4days_is_not_l1(self):
        _, _, desc, result, _, _ = self._run_case(TEST_CASES[11])
        assert result.level != 1, f"{desc}: should NOT be L1 (date beyond tolerance)"

    def test_case_13_gstin_mismatch_is_not_l1(self):
        _, _, desc, result, _, _ = self._run_case(TEST_CASES[12])
        assert result.level != 1, f"{desc}: should NOT be L1 (GSTIN mismatch)"

    def test_case_14_invoice_typo_is_not_l1(self):
        _, _, desc, result, _, _ = self._run_case(TEST_CASES[13])
        assert result.level != 1, f"{desc}: should NOT be L1 (invoice typo)"

    def test_case_15_5000paise_is_not_l1(self):
        _, _, desc, result, _, _ = self._run_case(TEST_CASES[14])
        assert result.level != 1, f"{desc}: should NOT be L1 (₹50 diff)"

    def test_case_16_200paise_tax_is_not_l1(self):
        _, _, desc, result, _, _ = self._run_case(TEST_CASES[15])
        assert result.level != 1, f"{desc}: should NOT be L1 (total_tax ₹2 off)"

    def test_case_17_both_beyond_is_not_l1(self):
        _, _, desc, result, _, _ = self._run_case(TEST_CASES[16])
        assert result.level != 1, f"{desc}: should NOT be L1 (both beyond)"

    def test_case_18_gstin_diff_amounts_ok_not_l1(self):
        _, _, desc, result, _, _ = self._run_case(TEST_CASES[17])
        assert result.level != 1, f"{desc}: should NOT be L1 (GSTIN diff)"

    def test_case_19_format_variant_with_amt_diff_not_l1(self):
        _, _, desc, result, _, _ = self._run_case(TEST_CASES[18])
        assert result.level != 1, f"{desc}: should NOT be L1 (format variant + amt diff)"

    def test_case_20_taxable_ok_tax_not_is_not_l1(self):
        _, _, desc, result, _, _ = self._run_case(TEST_CASES[19])
        assert result.level != 1, f"{desc}: should NOT be L1 (total_tax beyond tolerance)"

    def test_case_21_missing_amount_not_l1(self):
        _, _, desc, result, _, _ = self._run_case(TEST_CASES[20])
        assert result.level != 1, f"{desc}: should NOT be L1 (missing amount causes total mismatch)"

    # ── Cross-verification: no false-exact in any of the 20 ─────────────

    def test_no_false_exact_in_all_20_cases(self):
        """Sweep all 20 cases: if matcher says L1, raw fields must also agree."""
        false_exacts = []
        for case_kwargs in TEST_CASES:
            _, _, desc, result, raw_ok, mismatches = self._run_case(case_kwargs)
            if result.level == 1 and not raw_ok:
                false_exacts.append((desc, mismatches))
        assert not false_exacts, (
            f"FALSE-EXACT classifications found:\n"
            + "\n".join(f"  {desc}: {mm}" for desc, mm in false_exacts)
        )


class TestL1ToleranceDocumentation:
    """Document and verify the exact thresholds used by L1."""

    def test_amount_tolerance_is_100_paise(self):
        assert AMOUNT_TOLERANCE_L1_PAISE == 100, (
            f"L1 amount tolerance should be 100 paise (₹1), is {AMOUNT_TOLERANCE_L1_PAISE}"
        )

    def test_date_tolerance_is_3_days(self):
        assert DATE_TOLERANCE_L1_DAYS == 3, (
            f"L1 date tolerance should be 3 days, is {DATE_TOLERANCE_L1_DAYS}"
        )

    def test_gstin_comparison_is_case_insensitive(self):
        """GSTIN comparison must be case-insensitive (both sides .upper().strip())."""
        from app.services.matcher import _gstin_match_spec
        assert _gstin_match_spec(
            {"supplier_gstin": "27AAECR0001M1ZP"},
            {"supplier_gstin": "27aaecr0001m1zp"},
        )

    def test_invoice_normalization_strips_separators(self):
        """Invoice normalization must strip non-alphanumeric characters."""
        assert normalize_invoice("INV-2026-00001") == normalize_invoice("INV/2026/00001")
        assert normalize_invoice("INV-2026-00001") == normalize_invoice("INV 2026 00001")

    def test_invoice_normalization_strips_leading_zeros(self):
        """Invoice normalization must strip leading zeros per segment."""
        assert normalize_invoice("INV-0001") == normalize_invoice("INV-1")
        assert normalize_invoice("00123") == normalize_invoice("123")
