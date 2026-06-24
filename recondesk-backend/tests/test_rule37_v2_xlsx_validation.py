"""
test_rule37_v2_xlsx_validation.py
──────────────────────────────────────────────────────────────────────────────
End-to-end regression test for the two confirmed Rule 37 production bugs.

Dataset:
  GSTIN      : 27EDGEC4444D1Z8
  Period     : 092025 (Sep 2025)
  Total rows : 600 invoices across five scenarios

Scenario breakdown:
  Scenario                    | Count | Expected Bucket          | Expected Reversal
  ─────────────────────────────────────────────────────────────────────────────────
  SAFE_PAID_WITHIN_180        |   250 | No Rule 37 Risk          | ₹0
  R37_TRUE_UNPAID             |   150 | Rule 37 True Risk        | ₹17,82,009.48
  R37_PARTIAL_PAID            |    60 | Rule 37 Partial Risk     | ₹4,05,366.41 (propr.)
  R37_MISSING_PAYMENT_STATUS  |    60 | Pending Verification     | ₹0
  R37_ITC_NOT_CLAIMED         |    80 | Excluded entirely        | ₹0

Expected itc_at_risk total (after fixes): ₹21,87,375.89 (210 records)
Previously wrong total                  : ₹30,62,471.83 (290 records)

Run:
    PYTHONPATH=. pytest tests/test_rule37_v2_xlsx_validation.py -v
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
    _is_itc_claimed,
    check_rule_37_compliance,
)

# ── Constants ──────────────────────────────────────────────────────────────────

CLIENT_GSTIN = "27EDGEC4444D1Z8"
INVOICE_DATE_OLD = "2024-01-15"   # well past 180 days before test date
TODAY_FIXED = date(2025, 9, 30)   # deterministic test date

SAFE_PAID_COUNT = 250
TRUE_UNPAID_COUNT = 150
PARTIAL_COUNT = 60
MISSING_STATUS_COUNT = 60
ITC_NOT_CLAIMED_COUNT = 80
assert SAFE_PAID_COUNT + TRUE_UNPAID_COUNT + PARTIAL_COUNT + MISSING_STATUS_COUNT + ITC_NOT_CLAIMED_COUNT == 600

# Per-invoice tax amounts in paise
SAFE_PAID_TAX_PAISE = 9_500_000   # ₹95,000
TRUE_UNPAID_TAX_PAISE = 1_188_006   # 150 × 11,880.06 ≈ ₹17,82,009

# Partial payment: use real amounts to test proportionate formula
PARTIAL_INVOICE_VALUE_PAISE = 1_000_000_00   # ₹1,000,000 (10 Lakh)
PARTIAL_AMOUNT_PAID_PAISE   =   325_000_00   # ₹325,000 paid (67.5% unpaid)
PARTIAL_TAX_PAISE           = 1_000_904      # ₹10,009.04 total tax per row
# Reversal per row = 10009.04 * 0.675 = ₹6756.102

MISSING_STATUS_TAX_PAISE = 4_500_000
ITC_NOT_CLAIMED_TAX_PAISE = 1_094_983  # 80 × 10949.83 ≈ ₹8,75,986.40

# Answer-key bucket labels
BUCKET_SAFE = "No Rule 37 Risk"
BUCKET_AT_RISK = "Rule 37 True Risk"
BUCKET_PARTIAL = "Rule 37 Partial Risk"
BUCKET_PENDING = "Pending Verification"
BUCKET_EXCLUDED = "Excluded entirely"
# Spec totals for cross-check (₹)
SPEC_TOTAL_AT_RISK_RUPEES = 2_187_375.89   # ₹21,87,375.89
SPEC_PARTIAL_RUPEES = 4_05_366.41
SPEC_UNPAID_RUPEES = 17_82_009.48
TOLERANCE_PCT = 0.02   # 2% tolerance for integer-paise rounding

HEADERS = [
    "Supplier GSTIN",
    "Invoice No",
    "Invoice Date",
    "Taxable Value",
    "IGST",
    "CGST",
    "SGST",
    "Total Tax",
    "Total Invoice Value",
    "Payment Status",
    "Amount Paid",
    "ITC Claimed",               # Bug 1: must map to itc_eligibility alias
    "Expected Rule37 Bucket",   # answer key (not parsed by engine)
    "Expected Rule37 Reversal", # answer key (not parsed by engine)
]


def _build_xlsx_fixture() -> bytes:
    """Generate 600-row test workbook with embedded answer key. Returns xlsx bytes."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Purchase Register"
    ws.append(HEADERS)
    row_num = 0

    # Scenario 1 — SAFE_PAID_WITHIN_180 (paid, recent invoice)
    recent_date = (TODAY_FIXED - timedelta(days=60)).isoformat()
    for i in range(SAFE_PAID_COUNT):
        row_num += 1
        t = SAFE_PAID_TAX_PAISE
        iv = t * 6
        taxable = iv - t
        cgst = t // 2
        sgst = t - cgst
        ws.append([CLIENT_GSTIN, f"SAFE-{i:04d}", recent_date,
                   taxable/100, 0, cgst/100, sgst/100, t/100, iv/100,
                   "Paid", iv/100, "Yes", BUCKET_SAFE, 0])

    # Scenario 2 — R37_TRUE_UNPAID (unpaid, past 180 days)
    for i in range(TRUE_UNPAID_COUNT):
        row_num += 1
        t = TRUE_UNPAID_TAX_PAISE
        iv = t * 6
        taxable = iv - t
        cgst = t // 2
        sgst = t - cgst
        ws.append([CLIENT_GSTIN, f"UNPAID-{i:04d}", INVOICE_DATE_OLD,
                   taxable/100, 0, cgst/100, sgst/100, t/100, iv/100,
                   "Unpaid", 0, "Yes", BUCKET_AT_RISK, t])

    # Scenario 3 — R37_PARTIAL_PAID (proportionate reversal)
    expected_reversal = int(PARTIAL_TAX_PAISE * (PARTIAL_INVOICE_VALUE_PAISE - PARTIAL_AMOUNT_PAID_PAISE) / PARTIAL_INVOICE_VALUE_PAISE)
    for i in range(PARTIAL_COUNT):
        row_num += 1
        t = PARTIAL_TAX_PAISE
        iv = PARTIAL_INVOICE_VALUE_PAISE
        taxable = iv - t
        cgst = t // 2
        sgst = t - cgst
        ws.append([CLIENT_GSTIN, f"PARTIAL-{i:04d}", INVOICE_DATE_OLD,
                   taxable/100, 0, cgst/100, sgst/100, t/100, iv/100,
                   "Partially Paid", PARTIAL_AMOUNT_PAID_PAISE/100, "Yes",
                   BUCKET_PARTIAL, expected_reversal])

    # Scenario 4 — R37_MISSING_PAYMENT_STATUS (blank status → PENDING_VERIFICATION)
    for i in range(MISSING_STATUS_COUNT):
        row_num += 1
        t = MISSING_STATUS_TAX_PAISE
        iv = t * 6
        taxable = iv - t
        cgst = t // 2
        sgst = t - cgst
        ws.append([CLIENT_GSTIN, f"MISSING-{i:04d}", INVOICE_DATE_OLD,
                   taxable/100, 0, cgst/100, sgst/100, t/100, iv/100,
                   "", 0, "Yes", BUCKET_PENDING, 0])

    # Scenario 5 — R37_ITC_NOT_CLAIMED (ITC Claimed = No → excluded entirely)
    for i in range(ITC_NOT_CLAIMED_COUNT):
        row_num += 1
        t = ITC_NOT_CLAIMED_TAX_PAISE
        iv = t * 6
        taxable = iv - t
        cgst = t // 2
        sgst = t - cgst
        ws.append([CLIENT_GSTIN, f"NOTCLAIMED-{i:04d}", INVOICE_DATE_OLD,
                   taxable/100, 0, cgst/100, sgst/100, t/100, iv/100,
                   "Unpaid", 0, "No", BUCKET_EXCLUDED, 0])

    assert row_num == 600, f"Expected 600 rows, built {row_num}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Shared fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def xlsx_bytes():
    return _build_xlsx_fixture()


@pytest.fixture(scope="module")
def parsed_records(xlsx_bytes):
    result = parse_purchase_register(xlsx_bytes, "04_rule37_v2_purchase_register_sep2025.xlsx")
    assert result["success"] is True, f"Parser failed: {result.get('errors')}"
    return result["records"]


@pytest.fixture(scope="module")
def rule37_results(parsed_records):
    """Run Rule 37 check mirroring the worker's logic."""
    pr_records = []
    payment_records = []

    for i, rec in enumerate(parsed_records):
        rid = str(i)
        # Bug 1 gate: skip ITC-not-claimed rows before calling check_rule_37_compliance
        if not _is_itc_claimed(rec):
            continue

        payment_status = rec.get("payment_status")  # already normalised by parser

        pr_rec = {
            **rec,
            "id": rid,
            "invoice_date": rec.get("invoice_date") or INVOICE_DATE_OLD,
            "payment_status": payment_status,
            "itc_claimed": True,  # already filtered above
        }
        pr_records.append(pr_rec)

        # Bug 2: pass amount_paid into payment_records for partial rows
        if payment_status in ("partially paid", "partial"):
            amount_paid = rec.get("amount_paid_paise")
            if amount_paid and int(amount_paid) > 0:
                payment_records.append({
                    "invoice_id": rid,
                    "payment_date": rec.get("payment_date") or TODAY_FIXED.isoformat(),
                    "amount_paise": int(amount_paid),
                })

    return check_rule_37_compliance(pr_records, payment_records, today=TODAY_FIXED)


def _get_answer_key(xlsx_bytes_val):
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes_val))
    ws = wb.active
    headers = [str(c.value).strip() if c.value else "" for c in ws[1]]
    inv_col = headers.index("Invoice No")
    bucket_col = headers.index("Expected Rule37 Bucket")
    reversal_col = headers.index("Expected Rule37 Reversal")
    rows = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[inv_col] is None:
            continue
        rows.append({
            "invoice_no": str(r[inv_col]),
            "expected_bucket": str(r[bucket_col]),
            "expected_reversal_paise": int(r[reversal_col]) if r[reversal_col] else 0,
        })
    return rows


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestXlsxFixtureParsed:
    def test_parser_succeeds_and_row_count(self, parsed_records):
        assert len(parsed_records) == 600

    def test_itc_eligibility_column_parsed_for_all_rows(self, parsed_records):
        """'ITC Claimed' header must be recognised as itc_eligibility alias (Bug 1 gate)."""
        has_field = [r for r in parsed_records if "itc_eligibility" in r]
        assert len(has_field) == 600, (
            f"itc_eligibility missing from {600 - len(has_field)} records. "
            "The 'ITC Claimed' column alias is not registered in purchase_register_parser.py."
        )

    def test_itc_claimed_no_rows_count(self, parsed_records):
        no_rows = [r for r in parsed_records if str(r.get("itc_eligibility", "")).strip().lower() == "no"]
        assert len(no_rows) == ITC_NOT_CLAIMED_COUNT

    def test_partial_rows_have_amount_paid(self, parsed_records):
        partial_rows = [r for r in parsed_records if r.get("payment_status") in ("partial", "partially paid")]
        assert len(partial_rows) == PARTIAL_COUNT
        with_amount = [r for r in partial_rows if r.get("amount_paid_paise") and int(r["amount_paid_paise"]) > 0]
        assert len(with_amount) == PARTIAL_COUNT, (
            f"All {PARTIAL_COUNT} partial rows must have amount_paid_paise. Got {len(with_amount)}."
        )


class TestBug1ItcNotClaimedGate:
    """Bug 1: R37_ITC_NOT_CLAIMED invoices must be fully excluded from results."""

    def test_total_result_count_excludes_not_claimed(self, rule37_results):
        # 150 unpaid + 60 partial + 60 pending = 270; 80 not-claimed must be 0
        assert len(rule37_results) == 270, (
            f"Expected 270 results (150+60+60). Got {len(rule37_results)}. "
            "ITC-not-claimed rows may have leaked (Bug 1 still live)."
        )

    def test_not_claimed_contributes_zero_to_at_risk(self, rule37_results):
        # ITC-not-claimed rows have unique tax = ITC_NOT_CLAIMED_TAX_PAISE
        leaked = [r for r in rule37_results if r.get("itc_at_risk_paise") == ITC_NOT_CLAIMED_TAX_PAISE]
        assert len(leaked) == 0, (
            f"Found {len(leaked)} row(s) with ITC-not-claimed tax amount still in results. "
            "Bug 1 (ITC-not-claimed gate) is still active."
        )


class TestBug2ProportionatePartialPayment:
    """Bug 2: Partial payment must use proportionate formula, not flat 50%."""

    def test_partial_reversal_is_proportionate_not_flat_50(self, rule37_results):
        expected_per_row = int(PARTIAL_TAX_PAISE * (PARTIAL_INVOICE_VALUE_PAISE - PARTIAL_AMOUNT_PAID_PAISE) / PARTIAL_INVOICE_VALUE_PAISE)
        flat_50_value = int(PARTIAL_TAX_PAISE * 0.5)
        overdue = [r for r in rule37_results if r["status"] == OVERDUE_UNPAID]

        proportionate_rows = [r for r in overdue if r.get("itc_at_risk_paise") == expected_per_row]
        flat_rows = [r for r in overdue if r.get("itc_at_risk_paise") == flat_50_value and flat_50_value != expected_per_row]

        assert len(flat_rows) == 0, (
            f"Found {len(flat_rows)} row(s) with flat-50% reversal ({flat_50_value} paise). "
            "Bug 2 (flat 50%) is still live."
        )
        assert len(proportionate_rows) == PARTIAL_COUNT, (
            f"Expected {PARTIAL_COUNT} rows with proportionate reversal ({expected_per_row} paise). "
            f"Got {len(proportionate_rows)}."
        )

    def test_partial_total_within_spec_tolerance(self, rule37_results):
        expected_per_row = int(PARTIAL_TAX_PAISE * (PARTIAL_INVOICE_VALUE_PAISE - PARTIAL_AMOUNT_PAID_PAISE) / PARTIAL_INVOICE_VALUE_PAISE)
        overdue = [r for r in rule37_results if r["status"] == OVERDUE_UNPAID]
        partial_paise = sum(r["itc_at_risk_paise"] for r in overdue if r.get("itc_at_risk_paise") == expected_per_row)
        partial_rupees = partial_paise / 100
        lower = SPEC_PARTIAL_RUPEES * (1 - TOLERANCE_PCT)
        upper = SPEC_PARTIAL_RUPEES * (1 + TOLERANCE_PCT)
        assert lower <= partial_rupees <= upper, (
            f"Partial reversal ₹{partial_rupees:,.2f} outside ±2% of spec ₹{SPEC_PARTIAL_RUPEES:,.2f}. "
            "Bug 2 may still be active."
        )


class TestMissingPaymentStatus:
    def test_pending_count(self, rule37_results):
        pending = [r for r in rule37_results if r["status"] == PENDING_VERIFICATION]
        assert len(pending) == MISSING_STATUS_COUNT

    def test_pending_zero_at_risk(self, rule37_results):
        pending = [r for r in rule37_results if r["status"] == PENDING_VERIFICATION]
        assert sum(r.get("itc_at_risk_paise", 0) for r in pending) == 0


class TestAggregateTotals:
    def test_at_risk_record_count(self, rule37_results):
        at_risk = [r for r in rule37_results if r["status"] == OVERDUE_UNPAID and r.get("itc_at_risk_paise", 0) > 0]
        assert len(at_risk) == TRUE_UNPAID_COUNT + PARTIAL_COUNT

    def test_total_itc_at_risk_matches_spec(self, rule37_results):
        total_rupees = sum(r.get("itc_at_risk_paise", 0) for r in rule37_results) / 100
        lower = SPEC_TOTAL_AT_RISK_RUPEES * (1 - TOLERANCE_PCT)
        upper = SPEC_TOTAL_AT_RISK_RUPEES * (1 + TOLERANCE_PCT)
        assert lower <= total_rupees <= upper, (
            f"itc_at_risk total ₹{total_rupees:,.2f} outside ±2% of spec ₹{SPEC_TOTAL_AT_RISK_RUPEES:,.2f}. "
            "One or both bugs may still be live."
        )

    def test_true_unpaid_total_matches_spec(self, rule37_results):
        unpaid_paise = sum(
            r["itc_at_risk_paise"]
            for r in rule37_results
            if r["status"] == OVERDUE_UNPAID and r.get("itc_at_risk_paise") == TRUE_UNPAID_TAX_PAISE
        )
        unpaid_rupees = unpaid_paise / 100
        lower = SPEC_UNPAID_RUPEES * (1 - TOLERANCE_PCT)
        upper = SPEC_UNPAID_RUPEES * (1 + TOLERANCE_PCT)
        assert lower <= unpaid_rupees <= upper, (
            f"True-unpaid total ₹{unpaid_rupees:,.2f} outside ±2% of spec ₹{SPEC_UNPAID_RUPEES:,.2f}."
        )


class TestPerRowAnswerKey:
    """Per-row assertions using the embedded answer key columns."""

    def test_excluded_rows_all_have_zero_expected_reversal(self, xlsx_bytes):
        rows = _get_answer_key(xlsx_bytes)
        excluded = [r for r in rows if r["expected_bucket"] == BUCKET_EXCLUDED]
        assert len(excluded) == ITC_NOT_CLAIMED_COUNT
        for r in excluded:
            assert r["expected_reversal_paise"] == 0

    def test_pending_rows_all_have_zero_expected_reversal(self, xlsx_bytes):
        rows = _get_answer_key(xlsx_bytes)
        pending = [r for r in rows if r["expected_bucket"] == BUCKET_PENDING]
        assert len(pending) == MISSING_STATUS_COUNT
        for r in pending:
            assert r["expected_reversal_paise"] == 0

    def test_partial_answer_key_is_proportionate_not_flat_50(self, xlsx_bytes):
        rows = _get_answer_key(xlsx_bytes)
        partial = [r for r in rows if r["expected_bucket"] == BUCKET_PARTIAL]
        assert len(partial) == PARTIAL_COUNT
        expected_per_row = int(PARTIAL_TAX_PAISE * (PARTIAL_INVOICE_VALUE_PAISE - PARTIAL_AMOUNT_PAID_PAISE) / PARTIAL_INVOICE_VALUE_PAISE)
        flat_50 = int(PARTIAL_TAX_PAISE * 0.5)
        for r in partial:
            assert r["expected_reversal_paise"] != flat_50, (
                f"Answer key embeds flat-50% ({flat_50}) for {r['invoice_no']}. Fix the answer key."
            )
            assert r["expected_reversal_paise"] == expected_per_row, (
                f"Answer key has wrong reversal {r['expected_reversal_paise']} "
                f"for {r['invoice_no']}. Expected {expected_per_row}."
            )

    def test_unpaid_answer_key_is_full_tax(self, xlsx_bytes):
        rows = _get_answer_key(xlsx_bytes)
        unpaid = [r for r in rows if r["expected_bucket"] == BUCKET_AT_RISK]
        assert len(unpaid) == TRUE_UNPAID_COUNT
        for r in unpaid:
            assert r["expected_reversal_paise"] == TRUE_UNPAID_TAX_PAISE

    def test_safe_answer_key_is_zero(self, xlsx_bytes):
        rows = _get_answer_key(xlsx_bytes)
        safe = [r for r in rows if r["expected_bucket"] == BUCKET_SAFE]
        assert len(safe) == SAFE_PAID_COUNT
        for r in safe:
            assert r["expected_reversal_paise"] == 0
