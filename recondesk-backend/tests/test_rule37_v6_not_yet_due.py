"""
test_rule37_v6_not_yet_due.py
──────────────────────────────────────────────────────────────────────────────
Regression test for Bug 4 (BUG 4 FIX in reconciliation_task.py):

  Rule 37's 180-day threshold must be evaluated relative to the
  **reconciliation period end date** (gstr_end), NOT date.today().

  Without the fix, invoices whose 180-day window had NOT yet expired as of the
  reconciliation period end (e.g. 2025-09-30) but HAVE since expired in
  wall-clock time (e.g. 2026-06-24) are incorrectly flagged — producing the
  130 extra "not yet due" records and ~₹21.4 L extra amount.

Dataset:  08_rule37_v6_validgstin_sep2025
GSTIN   : 29AAACR5055K1ZK
Period  : 092025 (Sep 2025)  ->  period-end = 2025-09-30  (TODAY_FIXED)

Scenario breakdown (630 rows total):
  Scenario                   | Count | Expected bucket           | Reversal
  ──────────────────────────────────────────────────────────────────────────
  SAFE_PAID_WITHIN_180       |    70 | No Rule 37 Risk           | 0
  R37_TRUE_UNPAID            |   230 | Rule 37 True Risk         | per-row tax
  R37_PARTIAL_PAID           |    60 | Rule 37 Partial Risk      | proportionate
  R37_MISSING_STATUS         |    40 | Pending Verification      | 0
  R37_NOT_YET_DUE            |   130 | No Rule 37 Risk (not due) | 0
  R37_ITC_NOT_CLAIMED        |   100 | Excluded entirely         | 0
  ──────────────────────────────────────────────────────────────────────────
  Total at-risk              |   290 | ~44.04 L                  |

Bug-4 distinguishes R37_NOT_YET_DUE from SAFE_PAID:
  - SAFE_PAID: paid, not in Rule 37 scope regardless
  - NOT_YET_DUE: Unpaid, BUT 180-day window has NOT expired as of 2025-09-30.
    -> With bug (today = date.today() ~ 2026-06-24): WRONGLY flagged
    -> After fix (today = gstr_end = 2025-09-30): correctly excluded

Run:
    PYTHONPATH=. pytest tests/test_rule37_v6_not_yet_due.py -v
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import openpyxl
import pytest

from app.parsers.purchase_register_parser import parse_purchase_register
from app.services.rule37_tracker import (
    OVERDUE_UNPAID,
    PENDING_VERIFICATION,
    WARNING_30_DAYS,
    WARNING_60_DAYS,
    _is_itc_claimed,
    check_rule_37_compliance,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLIENT_GSTIN = "29AAACR5055K1ZK"
PERIOD_END   = date(2025, 9, 30)   # gstr_end for period 092025 -- used as today=
TODAY_FIXED  = PERIOD_END          # alias: deterministic reference date

# Invoice dates -- carefully chosen relative to PERIOD_END
# OLD: 213 days before 2025-09-30 -> PAST 180 days as of period end
INVOICE_DATE_OLD = "2025-03-01"
# RECENT: 152 days before 2025-09-30 -> NOT YET due as of period end
# deadline = 2025-05-01 + 180 = 2025-10-28 > 2025-09-30
INVOICE_DATE_RECENT = "2025-05-01"

# Sanity-check dates
assert (PERIOD_END - date.fromisoformat(INVOICE_DATE_OLD)).days >= 180
assert (PERIOD_END - date.fromisoformat(INVOICE_DATE_RECENT)).days < 180

# Simulated wall-clock: confirms NOT_YET_DUE would be flagged with buggy today
SIMULATED_WALL_CLOCK = date(2026, 6, 24)
assert (SIMULATED_WALL_CLOCK - date.fromisoformat(INVOICE_DATE_RECENT)).days >= 180

# Row counts
SAFE_PAID_COUNT       = 70
TRUE_UNPAID_COUNT     = 230
PARTIAL_COUNT         = 60
MISSING_STATUS_COUNT  = 40
NOT_YET_DUE_COUNT     = 130
ITC_NOT_CLAIMED_COUNT = 100
TOTAL_COUNT = (SAFE_PAID_COUNT + TRUE_UNPAID_COUNT + PARTIAL_COUNT
               + MISSING_STATUS_COUNT + NOT_YET_DUE_COUNT + ITC_NOT_CLAIMED_COUNT)
assert TOTAL_COUNT == 630

# Tax amounts in paise (integer, whole-paise arithmetic)
SAFE_PAID_TAX_PAISE         = 2_000_000   # 20,000 Rs -- paid, irrelevant
TRUE_UNPAID_TAX_PAISE       = 1_521_600   # 15,216 Rs per row
MISSING_STATUS_TAX_PAISE    = 3_000_000   # 30,000 Rs -- pending, 0 at-risk
NOT_YET_DUE_TAX_PAISE       = 1_645_632   # 16,456.32 Rs -- Bug-4: must NOT appear
ITC_NOT_CLAIMED_TAX_PAISE   = 1_382_500   # 13,825 Rs -- excluded by ITC gate

# Partial payment parameters
PARTIAL_INVOICE_VALUE_PAISE = 100_000_000   # 10,00,000 Rs (10 Lakh)
PARTIAL_AMOUNT_PAID_PAISE   =  25_000_000   # 2,50,000 Rs paid -> 75% unpaid
PARTIAL_TAX_PAISE           =   1_200_000   # 12,000 Rs per row
# reversal per row = int(1_200_000 * 0.75) = 900_000 paise
_PARTIAL_REVERSAL_PER_ROW = int(
    PARTIAL_TAX_PAISE
    * (PARTIAL_INVOICE_VALUE_PAISE - PARTIAL_AMOUNT_PAID_PAISE)
    / PARTIAL_INVOICE_VALUE_PAISE
)

# Aggregate spec
SPEC_TRUE_UNPAID_PAISE   = TRUE_UNPAID_COUNT * TRUE_UNPAID_TAX_PAISE     # 350_368_000
SPEC_PARTIAL_PAISE       = PARTIAL_COUNT * _PARTIAL_REVERSAL_PER_ROW     # 54_000_000
SPEC_TOTAL_AT_RISK_PAISE = SPEC_TRUE_UNPAID_PAISE + SPEC_PARTIAL_PAISE   # 404_368_000
SPEC_TOTAL_AT_RISK_RUPEES = SPEC_TOTAL_AT_RISK_PAISE / 100               # 40,43,68.00
TOLERANCE_PCT = 0.02

# Answer-key labels (embedded in XLSX)
BUCKET_SAFE     = "No Rule 37 Risk"
BUCKET_AT_RISK  = "Rule 37 True Risk"
BUCKET_PARTIAL  = "Rule 37 Partial Risk"
BUCKET_PENDING  = "Pending Verification"
BUCKET_NOT_DUE  = "Not Yet Due"
BUCKET_EXCLUDED = "Excluded entirely"

HEADERS = [
    "Supplier GSTIN", "Invoice No", "Invoice Date",
    "Taxable Value", "IGST", "CGST", "SGST", "Total Tax", "Total Invoice Value",
    "Payment Status", "Amount Paid", "ITC Claimed",
    "Expected Rule37 Bucket", "Expected Rule37 Reversal",
]


# ---------------------------------------------------------------------------
# XLSX fixture builder
# ---------------------------------------------------------------------------

def _build_xlsx_fixture() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Purchase Register"
    ws.append(HEADERS)
    row_num = 0

    # Scenario 1: SAFE_PAID_WITHIN_180 (paid, recent invoice)
    recent_date = (TODAY_FIXED - timedelta(days=45)).isoformat()
    for i in range(SAFE_PAID_COUNT):
        row_num += 1
        t = SAFE_PAID_TAX_PAISE
        iv = t * 6
        taxable = iv - t
        ws.append([CLIENT_GSTIN, f"SAFE-{i:04d}", recent_date,
                   taxable/100, 0, (t//2)/100, (t-t//2)/100, t/100, iv/100,
                   "Paid", iv/100, "Yes", BUCKET_SAFE, 0])

    # Scenario 2: R37_TRUE_UNPAID (unpaid, past 180 days as of PERIOD_END)
    for i in range(TRUE_UNPAID_COUNT):
        row_num += 1
        t = TRUE_UNPAID_TAX_PAISE
        iv = t * 6
        taxable = iv - t
        ws.append([CLIENT_GSTIN, f"UNPAID-{i:04d}", INVOICE_DATE_OLD,
                   taxable/100, 0, (t//2)/100, (t-t//2)/100, t/100, iv/100,
                   "Unpaid", 0, "Yes", BUCKET_AT_RISK, t])

    # Scenario 3: R37_PARTIAL_PAID (proportionate reversal)
    for i in range(PARTIAL_COUNT):
        row_num += 1
        t = PARTIAL_TAX_PAISE
        iv = PARTIAL_INVOICE_VALUE_PAISE
        taxable = iv - t
        ws.append([CLIENT_GSTIN, f"PARTIAL-{i:04d}", INVOICE_DATE_OLD,
                   taxable/100, 0, (t//2)/100, (t-t//2)/100, t/100, iv/100,
                   "Partially Paid", PARTIAL_AMOUNT_PAID_PAISE/100, "Yes",
                   BUCKET_PARTIAL, _PARTIAL_REVERSAL_PER_ROW])

    # Scenario 4: R37_MISSING_STATUS (blank status, past 180 days)
    for i in range(MISSING_STATUS_COUNT):
        row_num += 1
        t = MISSING_STATUS_TAX_PAISE
        iv = t * 6
        taxable = iv - t
        ws.append([CLIENT_GSTIN, f"MISSING-{i:04d}", INVOICE_DATE_OLD,
                   taxable/100, 0, (t//2)/100, (t-t//2)/100, t/100, iv/100,
                   "", 0, "Yes", BUCKET_PENDING, 0])

    # Scenario 5: R37_NOT_YET_DUE (unpaid, recent invoice, NOT yet past 180 days)
    # BUG 4 target: MUST be excluded when today=PERIOD_END.
    # With the bug (today=wall-clock 2026-06-24): WRONGLY flagged.
    for i in range(NOT_YET_DUE_COUNT):
        row_num += 1
        t = NOT_YET_DUE_TAX_PAISE
        iv = t * 6
        taxable = iv - t
        ws.append([CLIENT_GSTIN, f"NOTDUE-{i:04d}", INVOICE_DATE_RECENT,
                   taxable/100, 0, (t//2)/100, (t-t//2)/100, t/100, iv/100,
                   "Unpaid", 0, "Yes", BUCKET_NOT_DUE, 0])

    # Scenario 6: R37_ITC_NOT_CLAIMED (ITC Claimed = No)
    for i in range(ITC_NOT_CLAIMED_COUNT):
        row_num += 1
        t = ITC_NOT_CLAIMED_TAX_PAISE
        iv = t * 6
        taxable = iv - t
        ws.append([CLIENT_GSTIN, f"NOCLAIM-{i:04d}", INVOICE_DATE_OLD,
                   taxable/100, 0, (t//2)/100, (t-t//2)/100, t/100, iv/100,
                   "Unpaid", 0, "No", BUCKET_EXCLUDED, 0])

    assert row_num == TOTAL_COUNT
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def xlsx_bytes():
    return _build_xlsx_fixture()


@pytest.fixture(scope="module")
def parsed_records(xlsx_bytes):
    result = parse_purchase_register(xlsx_bytes, "08_rule37_v6_validgstin_sep2025.xlsx")
    assert result["success"] is True, f"Parser failed: {result.get('errors')}"
    return result["records"]


def _build_pr_inputs(parsed_records):
    """Shared helper: apply Bug-1 gate and payment filter, return (pr_records, payment_records)."""
    pr_records = []
    payment_records = []
    for i, rec in enumerate(parsed_records):
        rid = str(i)
        if not _is_itc_claimed(rec):
            continue  # Bug-1 gate: ITC not claimed -> skip
        ps = rec.get("payment_status")
        ps_norm = ps.strip().lower() if isinstance(ps, str) else None
        if ps_norm is not None and ps_norm not in ("unpaid", "partially paid", "partial", ""):
            continue  # paid / other -> out of Rule 37 scope
        pr_rec = {
            **rec,
            "id": rid,
            "invoice_date": rec.get("invoice_date") or INVOICE_DATE_OLD,
            "payment_status": ps_norm,
            "itc_claimed": True,
        }
        pr_records.append(pr_rec)
        if ps_norm in ("partially paid", "partial"):
            ap = rec.get("amount_paid_paise")
            if ap and int(ap) > 0:
                payment_records.append({
                    "invoice_id": rid,
                    "payment_date": INVOICE_DATE_OLD,
                    "amount_paise": int(ap),
                })
    return pr_records, payment_records


@pytest.fixture(scope="module")
def rule37_results_correct(parsed_records):
    """today=PERIOD_END -- mirrors the fixed reconciliation_task.py behaviour."""
    pr_records, payment_records = _build_pr_inputs(parsed_records)
    return check_rule_37_compliance(pr_records, payment_records, today=TODAY_FIXED)


@pytest.fixture(scope="module")
def rule37_results_buggy(parsed_records):
    """today=SIMULATED_WALL_CLOCK -- demonstrates the bug."""
    pr_records, payment_records = _build_pr_inputs(parsed_records)
    return check_rule_37_compliance(pr_records, payment_records, today=SIMULATED_WALL_CLOCK)


# ---------------------------------------------------------------------------
# Tests: parser sanity
# ---------------------------------------------------------------------------

class TestXlsxFixtureParsed:
    def test_parser_succeeds_and_row_count(self, parsed_records):
        assert len(parsed_records) == TOTAL_COUNT

    def test_itc_eligibility_column_present_all_rows(self, parsed_records):
        has = [r for r in parsed_records if "itc_eligibility" in r]
        assert len(has) == TOTAL_COUNT, (
            f"itc_eligibility missing from {TOTAL_COUNT - len(has)} records."
        )

    def test_itc_not_claimed_count(self, parsed_records):
        no_rows = [r for r in parsed_records
                   if str(r.get("itc_eligibility", "")).strip().lower() == "no"]
        assert len(no_rows) == ITC_NOT_CLAIMED_COUNT

    def test_not_yet_due_invoice_dates_within_180_days_of_period_end(self, parsed_records):
        notdue = [r for r in parsed_records
                  if str(r.get("invoice_number_normalized") or
                         r.get("invoice_number") or "").startswith("NOTDUE")]
        assert len(notdue) == NOT_YET_DUE_COUNT
        for r in notdue:
            inv_d = date.fromisoformat(r["invoice_date"])
            days = (PERIOD_END - inv_d).days
            assert days < 180, (
                f"NOTDUE invoice {r.get('invoice_number')} is {days} days old "
                f"as of PERIOD_END -- should be < 180"
            )

    def test_partial_rows_have_amount_paid(self, parsed_records):
        partial = [r for r in parsed_records
                   if r.get("payment_status") in ("partially paid", "partial")]
        assert len(partial) == PARTIAL_COUNT
        with_amt = [r for r in partial
                    if r.get("amount_paid_paise") and int(r["amount_paid_paise"]) > 0]
        assert len(with_amt) == PARTIAL_COUNT


# ---------------------------------------------------------------------------
# Tests: Bug 4 -- NOT_YET_DUE must be excluded (correct fix: today=PERIOD_END)
# ---------------------------------------------------------------------------

class TestBug4NotYetDueExcluded:
    """Bug 4: 180-day threshold must be at period end, not wall-clock date."""

    def test_not_yet_due_are_warnings_not_overdue(self, rule37_results_correct):
        """NOT_YET_DUE (within 180 as of period end) may appear as WARNING_* only."""
        # Parser normalises "NOTDUE-0001" → "NOTDUE0001" (hyphen stripped).
        not_due = [
            r
            for r in rule37_results_correct
            if (r.get("invoice_number") or "").startswith("NOTDUE")
        ]
        assert len(not_due) == NOT_YET_DUE_COUNT
        for r in not_due:
            assert r["status"] in (WARNING_30_DAYS, WARNING_60_DAYS), (
                f"NOT_YET_DUE must be a warning, not overdue. Got {r['status']}"
            )
            assert r.get("itc_at_risk_paise", 0) == 0, (
                "Pre-deadline warnings must not inflate itc_at_risk_paise"
            )

    def test_not_yet_due_contributes_zero_at_risk(self, rule37_results_correct):
        leaked_paise = sum(
            r.get("itc_at_risk_paise", 0)
            for r in rule37_results_correct
            if (r.get("invoice_number") or "").startswith("NOTDUE")
        )
        assert leaked_paise == 0, (
            f"NOT_YET_DUE at-risk must stay 0. Got {leaked_paise} p total."
        )

    def test_at_risk_record_count_is_290(self, rule37_results_correct):
        overdue = [r for r in rule37_results_correct if r["status"] == OVERDUE_UNPAID]
        expected = TRUE_UNPAID_COUNT + PARTIAL_COUNT
        assert len(overdue) == expected, (
            f"Expected {expected} overdue records (230 unpaid + 60 partial). "
            f"Got {len(overdue)}. "
            f"NOT_YET_DUE ({NOT_YET_DUE_COUNT}) must not be OVERDUE."
        )

    def test_total_result_count(self, rule37_results_correct):
        # overdue (290) + pending_verification (40) + warning NOT_YET_DUE (130)
        expected = (
            TRUE_UNPAID_COUNT
            + PARTIAL_COUNT
            + MISSING_STATUS_COUNT
            + NOT_YET_DUE_COUNT
        )
        assert len(rule37_results_correct) == expected, (
            f"Expected {expected} total results. Got {len(rule37_results_correct)}."
        )


# ---------------------------------------------------------------------------
# Tests: Bug 4 demonstration -- wall-clock date wrongly includes NOT_YET_DUE
# ---------------------------------------------------------------------------

class TestBug4DemonstrationWithWallClock:
    """Prove the bug exists: wall-clock today inflates count and amount."""

    def test_buggy_overdue_count_includes_not_yet_due(self, rule37_results_buggy):
        overdue_buggy = [r for r in rule37_results_buggy if r["status"] == OVERDUE_UNPAID]
        expected_buggy = TRUE_UNPAID_COUNT + PARTIAL_COUNT + NOT_YET_DUE_COUNT
        assert len(overdue_buggy) == expected_buggy, (
            f"Buggy mode: expected {expected_buggy} overdue "
            f"(290 legitimate + {NOT_YET_DUE_COUNT} NOT_YET_DUE). "
            f"Got {len(overdue_buggy)}."
        )

    def test_buggy_at_risk_exceeds_correct_by_exact_not_yet_due_amount(
        self, rule37_results_correct, rule37_results_buggy
    ):
        correct_paise = sum(r.get("itc_at_risk_paise", 0) for r in rule37_results_correct)
        buggy_paise   = sum(r.get("itc_at_risk_paise", 0) for r in rule37_results_buggy)
        assert buggy_paise > correct_paise, (
            "Buggy total must be higher than correct total."
        )
        extra_paise = buggy_paise - correct_paise
        expected_extra = NOT_YET_DUE_COUNT * NOT_YET_DUE_TAX_PAISE
        assert extra_paise == expected_extra, (
            f"Extra at-risk from Bug 4 = {extra_paise} p "
            f"(Rs {extra_paise/100:,.2f}). "
            f"Expected {expected_extra} p "
            f"(Rs {expected_extra/100:,.2f}) = 130 x NOT_YET_DUE_TAX_PAISE."
        )


# ---------------------------------------------------------------------------
# Tests: aggregate totals (correct behaviour)
# ---------------------------------------------------------------------------

class TestAggregateTotals:
    def test_at_risk_total_within_spec(self, rule37_results_correct):
        total_paise  = sum(r.get("itc_at_risk_paise", 0) for r in rule37_results_correct)
        total_rupees = total_paise / 100
        lower = SPEC_TOTAL_AT_RISK_RUPEES * (1 - TOLERANCE_PCT)
        upper = SPEC_TOTAL_AT_RISK_RUPEES * (1 + TOLERANCE_PCT)
        assert lower <= total_rupees <= upper, (
            f"itc_at_risk total Rs {total_rupees:,.2f} outside +-2% of "
            f"spec Rs {SPEC_TOTAL_AT_RISK_RUPEES:,.2f}."
        )

    def test_pending_count_and_zero_at_risk(self, rule37_results_correct):
        pending = [r for r in rule37_results_correct if r["status"] == PENDING_VERIFICATION]
        assert len(pending) == MISSING_STATUS_COUNT
        assert sum(r.get("itc_at_risk_paise", 0) for r in pending) == 0

    def test_proportionate_partial_reversal(self, rule37_results_correct):
        overdue = [r for r in rule37_results_correct if r["status"] == OVERDUE_UNPAID]
        prop_rows = [r for r in overdue
                     if r.get("itc_at_risk_paise") == _PARTIAL_REVERSAL_PER_ROW]
        assert len(prop_rows) == PARTIAL_COUNT, (
            f"Expected {PARTIAL_COUNT} partial rows with reversal "
            f"{_PARTIAL_REVERSAL_PER_ROW} p. Got {len(prop_rows)}."
        )


# ---------------------------------------------------------------------------
# Tests: Bug-1 ITC_NOT_CLAIMED gate must remain intact
# ---------------------------------------------------------------------------

class TestBug1GateUnchanged:
    def test_itc_not_claimed_absent_from_results(self, rule37_results_correct):
        leaked = [r for r in rule37_results_correct
                  if (r.get("invoice_number") or "").startswith("NOCLAIM-")]
        assert len(leaked) == 0, (
            f"Bug-1 guard broken: {len(leaked)} ITC_NOT_CLAIMED rows in results."
        )

    def test_itc_not_claimed_tax_not_in_at_risk(self, rule37_results_correct):
        leaked = [r for r in rule37_results_correct
                  if r.get("itc_at_risk_paise") == ITC_NOT_CLAIMED_TAX_PAISE]
        assert len(leaked) == 0, (
            f"ITC_NOT_CLAIMED tax {ITC_NOT_CLAIMED_TAX_PAISE} p leaked in "
            f"{len(leaked)} rows."
        )
