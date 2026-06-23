"""
test_rule37_three_bugs.py
─────────────────────────
Regression tests for the three Rule 37 bugs fixed in rule37_tracker.py.

Validates the known dataset described in the bug report:
  GSTIN 27EDGEC3333C1Z7 | period 092025 | 500 invoices

Category breakdown and expected itc_at_risk total:

  Category                | Count | Total Tax (₹) | Treatment
  ──────────────────────────────────────────────────────────────────────────
  Unpaid > 180 days       |   120 | ₹5,73,436     | Full reversal → itc_at_risk
  Partially paid          |    30 | ₹1,37,075     | 50% reversal = ₹68,537 → itc_at_risk
  Blank payment_status    |    70 | ₹3,13,137     | PENDING_VERIFICATION — NOT in itc_at_risk
  ITC not claimed         |    80 | ₹3,58,158     | Excluded entirely
  Paid within 180 days    |   200 | ₹9,83,779     | Compliant — NOT in itc_at_risk

  Expected itc_at_risk total: ₹6,41,973.31
    = ₹5,73,436.31 (full unpaid) + ₹68,537.00 (50% of partial)
  Previously buggy total:     ₹13,81,806.26

Run: PYTHONPATH=. pytest tests/test_rule37_three_bugs.py -v
"""

import pytest
from datetime import date, timedelta
from app.services.rule37_tracker import (
    check_rule_37_compliance,
    _is_itc_claimed,
    OVERDUE_UNPAID,
    PENDING_VERIFICATION,
    CRITICAL,
    MEDIUM,
)

GSTIN = "27EDGEC3333C1Z7"
# All invoices dated so they are well past the 180-day deadline when
# evaluated against TODAY_FIXED.
INVOICE_DATE = "2020-01-01"   # very old — always past 180 days
TODAY_FIXED = date(2025, 9, 30)


# ─── helpers ──────────────────────────────────────────────────────────────────

def make_pr(
    id: str,
    total_tax_paise: int,
    payment_status: str | None,
    itc_claimed: bool | str | None = None,
    invoice_date: str = INVOICE_DATE,
    gstin: str = GSTIN,
) -> dict:
    rec = {
        "id": id,
        "supplier_gstin": gstin,
        "invoice_number_normalized": f"INV-{id}",
        "invoice_date": invoice_date,
        "taxable_amount_paise": total_tax_paise * 5,   # rough proxy
        "total_tax_paise": total_tax_paise,
        "invoice_value_paise": total_tax_paise * 6,
    }
    # payment_status may be None (blank) or a string
    if payment_status is not None:
        rec["payment_status"] = payment_status
    # itc_claimed goes on the pr dict so the gate inside check_rule_37_compliance
    # can read it.  Worker sets it after calling _is_itc_claimed(raw).
    if itc_claimed is not None:
        rec["itc_claimed"] = itc_claimed
    return rec


# ─── BUG 1: ITC-claimed gate ──────────────────────────────────────────────────

class TestBug1ItcClaimedGate:
    """Records with ITC not claimed must be fully excluded from Rule 37."""

    def test_itc_claimed_false_bool_is_excluded(self):
        pr = make_pr("b1-001", total_tax_paise=10_000, payment_status="unpaid",
                     itc_claimed=False)
        results = check_rule_37_compliance([pr], [], today=TODAY_FIXED)
        assert results == [], (
            "ITC not claimed (False) must be excluded entirely from Rule 37."
        )

    def test_itc_claimed_no_string_is_excluded(self):
        pr = make_pr("b1-002", total_tax_paise=10_000, payment_status="unpaid",
                     itc_claimed="No")
        results = check_rule_37_compliance([pr], [], today=TODAY_FIXED)
        assert results == [], (
            "ITC not claimed ('No') must be excluded entirely from Rule 37."
        )

    def test_itc_claimed_ineligible_string_is_excluded(self):
        pr = make_pr("b1-003", total_tax_paise=8_000, payment_status="unpaid",
                     itc_claimed="Ineligible")
        results = check_rule_37_compliance([pr], [], today=TODAY_FIXED)
        assert results == []

    def test_itc_claimed_not_eligible_string_is_excluded(self):
        pr = make_pr("b1-004", total_tax_paise=5_000, payment_status="unpaid",
                     itc_claimed="not eligible")
        results = check_rule_37_compliance([pr], [], today=TODAY_FIXED)
        assert results == []

    def test_itc_claimed_yes_string_is_included(self):
        pr = make_pr("b1-005", total_tax_paise=10_000, payment_status="unpaid",
                     itc_claimed="Yes")
        results = check_rule_37_compliance([pr], [], today=TODAY_FIXED)
        assert len(results) == 1, (
            "ITC claimed ('Yes') must be included in Rule 37 assessment."
        )

    def test_itc_claimed_true_bool_is_included(self):
        pr = make_pr("b1-006", total_tax_paise=10_000, payment_status="unpaid",
                     itc_claimed=True)
        results = check_rule_37_compliance([pr], [], today=TODAY_FIXED)
        assert len(results) == 1

    def test_itc_claimed_absent_is_included(self):
        """When itc_claimed key is absent (most existing records), assume claimed."""
        pr = make_pr("b1-007", total_tax_paise=10_000, payment_status="unpaid")
        # itc_claimed key is deliberately absent
        assert "itc_claimed" not in pr
        results = check_rule_37_compliance([pr], [], today=TODAY_FIXED)
        assert len(results) == 1, (
            "Absent itc_claimed must default to 'claimed' (conservative)."
        )

    def test_multiple_records_only_claimed_itc_included(self):
        """80 ITC-not-claimed records + 5 claimed unpaid → only 5 in results."""
        prs = [
            make_pr(f"not-claimed-{i}", total_tax_paise=4_477, payment_status="unpaid",
                    itc_claimed=False)
            for i in range(80)
        ] + [
            make_pr(f"claimed-{i}", total_tax_paise=4_478, payment_status="unpaid")
            for i in range(5)
        ]
        results = check_rule_37_compliance(prs, [], today=TODAY_FIXED)
        assert len(results) == 5, (
            f"Expected 5 results (only claimed-ITC records). Got {len(results)}."
        )


# ─── BUG 2: Null/blank payment_status → PENDING_VERIFICATION ─────────────────

class TestBug2BlankPaymentStatusPendingVerification:
    """Blank/None payment_status must route to PENDING_VERIFICATION, not itc_at_risk."""

    def test_none_payment_status_past_deadline_is_pending_verification(self):
        # payment_status key absent → interpreted as None → PENDING_VERIFICATION
        pr = make_pr("b2-001", total_tax_paise=44_734, payment_status=None)
        # make_pr with None omits the key; assert it's absent
        assert "payment_status" not in pr
        results = check_rule_37_compliance([pr], [], today=TODAY_FIXED)
        # Must surface as PENDING_VERIFICATION — but NOT add to itc_at_risk
        # (the record may or may not appear depending on implementation, but
        #  itc_at_risk_paise must always be 0)
        for r in results:
            assert r["itc_at_risk_paise"] == 0, (
                "PENDING_VERIFICATION records must have itc_at_risk_paise=0."
            )
            assert r["status"] == PENDING_VERIFICATION, (
                f"Expected PENDING_VERIFICATION. Got: {r['status']}"
            )

    def test_empty_string_payment_status_is_pending_verification(self):
        pr = make_pr("b2-002", total_tax_paise=44_734, payment_status="")
        results = check_rule_37_compliance([pr], [], today=TODAY_FIXED)
        for r in results:
            assert r["status"] == PENDING_VERIFICATION
            assert r["itc_at_risk_paise"] == 0

    def test_blank_status_within_180_days_does_not_appear(self):
        """Blank status + within 180 days → not yet due → should not appear."""
        recent = (TODAY_FIXED - timedelta(days=90)).isoformat()
        pr = make_pr("b2-003", total_tax_paise=44_734, payment_status=None)
        # make_pr with None omits the key
        assert "payment_status" not in pr
        pr["invoice_date"] = recent
        results = check_rule_37_compliance([pr], [], today=TODAY_FIXED)
        assert results == [], (
            "Blank payment_status within 180 days must not appear in results."
        )

    def test_70_blank_status_records_excluded_from_at_risk_total(self):
        """Simulate the 70 blank-status records from the validation dataset."""
        prs = [
            make_pr(f"blank-{i}", total_tax_paise=4_473, payment_status=None)
            for i in range(70)
        ]
        # make_pr with None already omits payment_status key
        for pr in prs:
            assert "payment_status" not in pr
        results = check_rule_37_compliance(prs, [], today=TODAY_FIXED)
        total_at_risk = sum(r["itc_at_risk_paise"] for r in results)
        assert total_at_risk == 0, (
            f"70 blank-status records must contribute ₹0 to itc_at_risk. "
            f"Got: ₹{total_at_risk / 100:.2f}"
        )
        pending_count = sum(
            1 for r in results if r["status"] == PENDING_VERIFICATION
        )
        assert pending_count == 70, (
            f"All 70 blank-status records must appear as PENDING_VERIFICATION. "
            f"Got: {pending_count}"
        )


# ─── BUG 3: Proportionate reversal for partial payments ───────────────────────

class TestBug3PartialPaymentProportionateReversal:
    """Partial payments must reverse 50% of ITC, not 100%."""

    def test_partially_paid_reverses_50_percent(self):
        tax_paise = 20_000
        pr = make_pr("b3-001", total_tax_paise=tax_paise, payment_status="partially paid")
        results = check_rule_37_compliance([pr], [], today=TODAY_FIXED)
        assert len(results) == 1
        r = results[0]
        expected = int(tax_paise * 0.5)
        assert r["itc_at_risk_paise"] == expected, (
            f"Partial payment must reverse 50% of tax. "
            f"Expected: {expected}, Got: {r['itc_at_risk_paise']}"
        )

    def test_partial_alias_reverses_50_percent(self):
        """'partial' (short alias) must behave same as 'partially paid'."""
        tax_paise = 30_000
        pr = make_pr("b3-002", total_tax_paise=tax_paise, payment_status="partial")
        results = check_rule_37_compliance([pr], [], today=TODAY_FIXED)
        assert len(results) == 1
        assert results[0]["itc_at_risk_paise"] == int(tax_paise * 0.5)

    def test_unpaid_reverses_100_percent(self):
        """Fully unpaid past deadline must still reverse 100%."""
        tax_paise = 15_000
        pr = make_pr("b3-003", total_tax_paise=tax_paise, payment_status="unpaid")
        results = check_rule_37_compliance([pr], [], today=TODAY_FIXED)
        assert len(results) == 1
        assert results[0]["itc_at_risk_paise"] == tax_paise, (
            "Fully unpaid must reverse 100% of ITC, not 50%."
        )

    def test_30_partial_records_match_expected_at_risk(self):
        """Simulate the 30 partially-paid records from the validation dataset.

        Each has tax = ₹1,37,075 / 30 ≈ ₹4,569.17
        50% reversal ≈ ₹68,537 total (as stated in spec).
        """
        # Use exact paise so rounding doesn't cause test flakes
        # 30 records × 456_917 paise each = ₹1,37,075.10
        tax_per = 456_917
        prs = [
            make_pr(f"partial-{i}", total_tax_paise=tax_per, payment_status="partially paid")
            for i in range(30)
        ]
        results = check_rule_37_compliance(prs, [], today=TODAY_FIXED)
        assert len(results) == 30
        total_at_risk = sum(r["itc_at_risk_paise"] for r in results)
        expected = int(tax_per * 0.5) * 30
        assert total_at_risk == expected, (
            f"30 partial records: expected at_risk={expected} paise. "
            f"Got {total_at_risk}."
        )


# ─── Validation: five-category combined scenario ─────────────────────────────

class TestCombinedFiveCategoryScenario:
    """Validate the exact figures from the bug report for GSTIN 27EDGEC3333C1Z7."""

    # Totals from the spec (in paise; ₹1 = 100 paise)
    # Unpaid >180d: 120 records × avg tax → total ₹5,73,436.31 → 57_343_631 paise
    # Partial 30%:  30  records × avg tax → total ₹1,37,075.00 → 13_707_500 paise
    # Blank:        70  records           → ₹3,13,137          → 31_313_700 paise
    # Not claimed:  80  records           → ₹3,58,158          → 35_815_800 paise
    # Paid:         200 records           → ₹9,83,779          → (not included)

    UNPAID_COUNT = 120
    PARTIAL_COUNT = 30
    BLANK_COUNT = 70
    NOT_CLAIMED_COUNT = 80
    PAID_COUNT = 200

    # Paise for each group (approximate, chosen so totals hit the spec numbers)
    UNPAID_TAX_PAISE_EACH = 477_864     # 120 × 477_864 = 57_343_680 paise ≈ ₹5,73,436.80
    PARTIAL_TAX_PAISE_EACH = 456_917    # 30  × 456_917 = 13_707_510 paise ≈ ₹1,37,075.10
    BLANK_TAX_PAISE_EACH = 447_339      # 70  × 447_339 = 31_313_730 paise ≈ ₹3,13,137.30
    NOT_CLAIMED_TAX_PAISE_EACH = 447_697  # 80 × 447_697 = 35_815_760 paise ≈ ₹3,58,157.60

    def _build_dataset(self):
        prs = []
        # Category 1 — Unpaid > 180 days (full reversal)
        for i in range(self.UNPAID_COUNT):
            prs.append(make_pr(
                f"unpaid-{i}",
                total_tax_paise=self.UNPAID_TAX_PAISE_EACH,
                payment_status="unpaid",
            ))
        # Category 2 — Partially paid (50% reversal)
        for i in range(self.PARTIAL_COUNT):
            prs.append(make_pr(
                f"partial-{i}",
                total_tax_paise=self.PARTIAL_TAX_PAISE_EACH,
                payment_status="partially paid",
            ))
        # Category 3 — Blank payment_status (PENDING_VERIFICATION, 0 at-risk)
        for i in range(self.BLANK_COUNT):
            # make_pr with payment_status=None already omits the key
            pr = make_pr(
                f"blank-{i}",
                total_tax_paise=self.BLANK_TAX_PAISE_EACH,
                payment_status=None,
            )
            assert "payment_status" not in pr
            prs.append(pr)
        # Category 4 — ITC not claimed (excluded entirely)
        for i in range(self.NOT_CLAIMED_COUNT):
            prs.append(make_pr(
                f"not-claimed-{i}",
                total_tax_paise=self.NOT_CLAIMED_TAX_PAISE_EACH,
                payment_status="unpaid",
                itc_claimed=False,
            ))
        # Category 5 — Paid within 180 days (compliant, not in results at all)
        recent_date = (TODAY_FIXED - timedelta(days=90)).isoformat()
        for i in range(self.PAID_COUNT):
            prs.append(make_pr(
                f"paid-{i}",
                total_tax_paise=490_000,
                payment_status="paid",
                invoice_date=recent_date,
            ))
        return prs

    def test_total_itc_at_risk_excludes_not_claimed_blank_paid(self):
        """Combined: only unpaid + 50%-partial contribute to itc_at_risk."""
        prs = self._build_dataset()
        results = check_rule_37_compliance(prs, [], today=TODAY_FIXED)

        at_risk_results = [r for r in results if r["status"] == OVERDUE_UNPAID]
        pending_results = [r for r in results if r["status"] == PENDING_VERIFICATION]

        # ── counts ────────────────────────────────────────────────────────────
        assert len(at_risk_results) == self.UNPAID_COUNT + self.PARTIAL_COUNT, (
            f"Expected {self.UNPAID_COUNT + self.PARTIAL_COUNT} at-risk records. "
            f"Got {len(at_risk_results)}."
        )
        assert len(pending_results) == self.BLANK_COUNT, (
            f"Expected {self.BLANK_COUNT} pending-verification records. "
            f"Got {len(pending_results)}."
        )

        # ── itc_at_risk totals ────────────────────────────────────────────────
        total_at_risk_paise = sum(r["itc_at_risk_paise"] for r in at_risk_results)

        expected_unpaid_paise = self.UNPAID_COUNT * self.UNPAID_TAX_PAISE_EACH
        expected_partial_paise = self.PARTIAL_COUNT * int(self.PARTIAL_TAX_PAISE_EACH * 0.5)
        expected_total_at_risk = expected_unpaid_paise + expected_partial_paise

        assert total_at_risk_paise == expected_total_at_risk, (
            f"Expected itc_at_risk_paise={expected_total_at_risk} "
            f"(₹{expected_total_at_risk/100:.2f}). "
            f"Got {total_at_risk_paise} (₹{total_at_risk_paise/100:.2f})."
        )

        # ── pending_verification contributes 0 to at-risk ────────────────────
        pending_at_risk = sum(r["itc_at_risk_paise"] for r in pending_results)
        assert pending_at_risk == 0, (
            f"Pending-verification records must add 0 to itc_at_risk. "
            f"Got {pending_at_risk}."
        )

    def test_not_claimed_records_absent_from_results(self):
        """ITC-not-claimed records must not appear in results at all."""
        prs = self._build_dataset()
        results = check_rule_37_compliance(prs, [], today=TODAY_FIXED)
        result_ids = {r["pr_id"] for r in results}
        not_claimed_ids = {f"not-claimed-{i}" for i in range(self.NOT_CLAIMED_COUNT)}
        overlap = result_ids & not_claimed_ids
        assert not overlap, (
            f"ITC-not-claimed records must not appear in results. "
            f"Found: {overlap}"
        )

    def test_paid_within_180_days_absent_from_results(self):
        """Paid-on-time records must not appear in results at all."""
        prs = self._build_dataset()
        results = check_rule_37_compliance(prs, [], today=TODAY_FIXED)
        result_ids = {r["pr_id"] for r in results}
        paid_ids = {f"paid-{i}" for i in range(self.PAID_COUNT)}
        overlap = result_ids & paid_ids
        assert not overlap, (
            f"Paid-within-180d records must not appear. Found: {overlap}"
        )

    def test_approximate_rupee_totals_match_spec(self):
        """Cross-check paise totals against the spec rupee figures (±1%)."""
        prs = self._build_dataset()
        results = check_rule_37_compliance(prs, [], today=TODAY_FIXED)
        at_risk_paise = sum(
            r["itc_at_risk_paise"]
            for r in results
            if r["status"] == OVERDUE_UNPAID
        )
        at_risk_rupees = at_risk_paise / 100

        # Spec says ₹6,41,973.31; allow ±1% tolerance for rounding in test data
        spec_total = 641_973.31
        lower = spec_total * 0.99
        upper = spec_total * 1.01
        assert lower <= at_risk_rupees <= upper, (
            f"Expected itc_at_risk ≈ ₹{spec_total:,.2f} (±1%). "
            f"Got ₹{at_risk_rupees:,.2f}."
        )


# ─── _is_itc_claimed helper ───────────────────────────────────────────────────

class TestIsItcClaimedHelper:
    """Unit tests for the _is_itc_claimed helper function."""

    def test_absent_key_returns_true(self):
        assert _is_itc_claimed({}) is True

    def test_none_value_returns_true(self):
        assert _is_itc_claimed({"itc_eligibility": None}) is True

    def test_blank_string_returns_true(self):
        assert _is_itc_claimed({"itc_eligibility": ""}) is True

    def test_yes_returns_true(self):
        assert _is_itc_claimed({"itc_eligibility": "Yes"}) is True

    def test_no_returns_false(self):
        assert _is_itc_claimed({"itc_eligibility": "No"}) is False

    def test_no_case_insensitive(self):
        assert _is_itc_claimed({"itc_eligibility": "NO"}) is False

    def test_ineligible_returns_false(self):
        assert _is_itc_claimed({"itc_eligibility": "Ineligible"}) is False

    def test_not_eligible_returns_false(self):
        assert _is_itc_claimed({"itc_eligibility": "not eligible"}) is False

    def test_eligible_string_returns_true(self):
        assert _is_itc_claimed({"itc_eligibility": "Eligible"}) is True

    def test_zero_string_returns_false(self):
        assert _is_itc_claimed({"itc_eligibility": "0"}) is False

    def test_false_string_returns_false(self):
        assert _is_itc_claimed({"itc_eligibility": "false"}) is False

    def test_not_claimed_string_returns_false(self):
        assert _is_itc_claimed({"itc_eligibility": "not claimed"}) is False


# ─── Existing 180-day logic unchanged ─────────────────────────────────────────

class TestExisting180DayLogicUnchanged:
    """Verify the correct 180-day logic was NOT broken by the fixes."""

    def test_unpaid_within_180_days_still_excluded(self):
        recent = (TODAY_FIXED - timedelta(days=90)).isoformat()
        pr = make_pr("unchanged-001", total_tax_paise=18_000, payment_status="unpaid",
                     invoice_date=recent)
        results = check_rule_37_compliance([pr], [], today=TODAY_FIXED)
        assert results == [], "Record within 180 days must not appear."

    def test_unpaid_past_180_days_still_flagged_critical(self):
        pr = make_pr("unchanged-002", total_tax_paise=18_000, payment_status="unpaid")
        results = check_rule_37_compliance([pr], [], today=TODAY_FIXED)
        assert len(results) == 1
        assert results[0]["status"] == OVERDUE_UNPAID
        assert results[0]["urgency"] == CRITICAL
        assert results[0]["itc_at_risk_paise"] == 18_000

    def test_deadline_still_exactly_180_days(self):
        pr = make_pr("unchanged-003", total_tax_paise=18_000, payment_status="unpaid",
                     invoice_date="2024-01-01")
        results = check_rule_37_compliance([pr], [], today=date(2024, 8, 1))
        assert results[0]["deadline"] == "2024-06-29"

    def test_no_records_returns_empty(self):
        assert check_rule_37_compliance([], [], today=TODAY_FIXED) == []

    def test_paid_status_record_is_not_flagged(self):
        pr = make_pr("unchanged-004", total_tax_paise=18_000, payment_status="paid")
        results = check_rule_37_compliance([pr], [], today=TODAY_FIXED)
        assert results == [], "Paid record must never appear in Rule 37 results."
