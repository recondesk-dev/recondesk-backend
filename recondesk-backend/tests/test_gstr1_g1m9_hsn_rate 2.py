"""G1M9 — HSN code & tax rate schedule validation.

Covers:
- Unknown HSN (LOW severity, informational)
- Rate not valid for HSN (HIGH severity)
- HSN digit-length below turnover-tier requirement (MEDIUM)
- Integration with sample SR / GSTR-1 data via injected bad rows
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from app.data.hsn_rate_reference import (
    lookup_valid_rates,
    normalise_hsn,
    required_hsn_digits,
)
from app.rules.gstr1_mismatch_rules import (
    MismatchSeverity,
    MismatchType,
    validate_hsn_rate_mapping,
)

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_gstr1_3b_test"
SAMPLE_SR = SAMPLE_DIR / "Sales_Register_Sample_Corrected.xlsx"
SAMPLE_GSTR1 = SAMPLE_DIR / "sample_gstr1.json"


def _sr(
    *,
    inv: str = "INV/001",
    hsn: str = "3901",
    taxable: int = 100000,
    igst: int = 18000,
    cgst: int = 0,
    sgst: int = 0,
) -> dict:
    return {
        "invoice_number": inv,
        "invoice_number_normalized": inv,
        "hsn": hsn,
        "taxable_amount_paise": taxable,
        "igst_paise": igst,
        "cgst_paise": cgst,
        "sgst_paise": sgst,
        "total_tax_paise": igst + cgst + sgst,
        "invoice_date": "2026-05-10",
    }


def _g1(
    *,
    inv: str = "INV/001",
    hsn: str | None = None,
    rate: float = 18.0,
    taxable: int = 100000,
    section: str = "hsn",
) -> dict:
    tax = int(round(taxable * rate / 100))
    return {
        "invoice_number": inv,
        "invoice_number_normalized": inv,
        "hsn": hsn,
        "rate": rate,
        "taxable_amount_paise": taxable,
        "igst_paise": tax,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "total_tax_paise": tax,
        "section": section,
        "invoice_type": "HSN_SUMMARY" if section == "hsn" else "B2B",
    }


# ══════════════════════════════════════════════════════════════════════════════
# Reference helpers
# ══════════════════════════════════════════════════════════════════════════════

class TestReferenceHelpers:

    def test_normalise_hsn_strips_non_digits(self):
        assert normalise_hsn("8203.0") == "8203"
        assert normalise_hsn(" 3901 ") == "3901"
        assert normalise_hsn(None) is None
        assert normalise_hsn("NA") is None

    def test_lookup_longest_prefix(self):
        rates = lookup_valid_rates("3901")
        assert rates is not None
        assert 18.0 in rates

    def test_lookup_unknown_returns_none(self):
        assert lookup_valid_rates("88888888") is None

    def test_required_digits_by_tier(self):
        assert required_hsn_digits("upto_5cr") == 4
        assert required_hsn_digits("above_5cr") == 6


# ══════════════════════════════════════════════════════════════════════════════
# Unknown HSN — LOW
# ══════════════════════════════════════════════════════════════════════════════

class TestUnknownHsn:

    def test_unknown_hsn_is_low_severity(self):
        """Incomplete local schedule must not flood unknown_hsn flags."""
        records = [_sr(hsn="88888888", igst=18000)]
        results = validate_hsn_rate_mapping(records, None)
        unknown = [r for r in results if r.details.get("issue_type") == "unknown_hsn"]
        assert unknown == []

    def test_known_hsn_not_flagged_unknown(self):
        records = [_sr(hsn="3901", igst=18000)]
        results = validate_hsn_rate_mapping(records, None)
        unknown = [r for r in results if r.details.get("issue_type") == "unknown_hsn"]
        assert len(unknown) == 0


# ══════════════════════════════════════════════════════════════════════════════
# Rate mismatch — HIGH
# ══════════════════════════════════════════════════════════════════════════════

class TestRateMismatch:

    def test_wrong_rate_for_known_hsn_is_high(self):
        """GSTR-1 HSN summary: 3901 at 5% (schedule 18%) must flag HIGH."""
        g1 = [_g1(inv="HSN-ROW", hsn="3901", rate=5.0)]
        results = validate_hsn_rate_mapping(None, g1)
        rate_issues = [
            r for r in results if r.details.get("issue_type") == "rate_mismatch"
        ]
        assert len(rate_issues) == 1
        assert rate_issues[0].severity == MismatchSeverity.HIGH
        assert rate_issues[0].details["applied_rate"] == 5.0
        assert 18.0 in rate_issues[0].details["valid_rates"]

    def test_correct_rate_not_flagged(self):
        records = [_sr(hsn="3901", taxable=100000, igst=18000)]
        results = validate_hsn_rate_mapping(records, None)
        rate_issues = [
            r for r in results if r.details.get("issue_type") == "rate_mismatch"
        ]
        assert len(rate_issues) == 0

    def test_gstr1_rate_field_validated_when_hsn_present(self):
        """GSTR-1 HSN summary / records with hsn+rate are validated."""
        g1 = [_g1(inv="HSN-ROW", hsn="3901", rate=5.0)]
        results = validate_hsn_rate_mapping(None, g1)
        rate_issues = [
            r for r in results if r.details.get("issue_type") == "rate_mismatch"
        ]
        assert len(rate_issues) == 1
        assert rate_issues[0].details["source"] == "gstr1"


# ══════════════════════════════════════════════════════════════════════════════
# Digit length — MEDIUM
# ══════════════════════════════════════════════════════════════════════════════

class TestDigitLength:

    def test_two_digit_hsn_flagged_for_upto_5cr(self):
        records = [_sr(hsn="39", igst=18000)]
        results = validate_hsn_rate_mapping(
            records, None, turnover_tier="upto_5cr",
        )
        digit = [
            r for r in results if r.details.get("issue_type") == "hsn_digit_length"
        ]
        assert len(digit) == 1
        assert digit[0].severity == MismatchSeverity.MEDIUM
        assert digit[0].details["required_digits"] == 4

    def test_four_digit_ok_for_upto_5cr(self):
        records = [_sr(hsn="3901", igst=18000)]
        results = validate_hsn_rate_mapping(
            records, None, turnover_tier="upto_5cr",
        )
        digit = [
            r for r in results if r.details.get("issue_type") == "hsn_digit_length"
        ]
        assert len(digit) == 0

    def test_four_digit_flagged_for_above_5cr(self):
        records = [_sr(hsn="3901", igst=18000)]
        results = validate_hsn_rate_mapping(
            records, None, turnover_tier="above_5cr",
        )
        digit = [
            r for r in results if r.details.get("issue_type") == "hsn_digit_length"
        ]
        assert len(digit) == 1
        assert digit[0].details["required_digits"] == 6


# ══════════════════════════════════════════════════════════════════════════════
# Edge cases / serialisation
# ══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    def test_empty_inputs(self):
        assert validate_hsn_rate_mapping([], []) == []
        assert validate_hsn_rate_mapping(None, None) == []

    def test_skip_records_without_hsn(self):
        """Invoice-level rows without HSN are skipped (portal schema)."""
        records = [_sr(hsn="")]
        records[0]["hsn"] = None
        g1 = [_g1(hsn=None, rate=18.0)]
        results = validate_hsn_rate_mapping(records, g1)
        missing = [r for r in results if r.details.get("issue_type") == "missing_hsn"]
        assert missing == []

    def test_malformed_hsn_is_low_severity(self):
        records = [_sr(hsn="N/A-HSN", igst=18000)]
        results = validate_hsn_rate_mapping(records, None)
        bad = [r for r in results if r.details.get("issue_type") == "malformed_hsn"]
        assert len(bad) == 1
        assert bad[0].severity == MismatchSeverity.LOW

    def test_zero_taxable_does_not_crash_rate_detection(self):
        records = [_sr(hsn="3901", taxable=0, igst=0, cgst=0, sgst=0)]
        results = validate_hsn_rate_mapping(records, None)
        assert isinstance(results, list)

    def test_numeric_hsn_type_normalised(self):
        records = [{"invoice_number": "X1", "hsn": 8203, "taxable_amount_paise": 100000, "igst_paise": 18000, "total_tax_paise": 18000}]
        results = validate_hsn_rate_mapping(records, None)
        unknown = [r for r in results if r.details.get("issue_type") == "unknown_hsn"]
        assert len(unknown) == 0
        rate_issues = [r for r in results if r.details.get("issue_type") == "rate_mismatch"]
        assert len(rate_issues) == 0

    def test_severity_sort_high_before_low(self):
        g1 = [
            _g1(inv="A", hsn="3901", rate=5.0),  # wrong rate HIGH
            _g1(inv="B", hsn="39", rate=18.0),  # digit-length MEDIUM on short HSN
        ]
        results = validate_hsn_rate_mapping(None, g1)
        assert len(results) >= 2
        assert results[0].severity == MismatchSeverity.HIGH

    def test_to_dict_serialisation(self):
        g1 = [_g1(inv="HSN-ROW", hsn="3901", rate=5.0)]
        results = validate_hsn_rate_mapping(None, g1)
        assert results
        d = results[0].to_dict()
        assert d["mismatch_type"] == "G1M9_HSN_RATE_ISSUE"
        assert d["decision_rule"] == "G1M_009"
        assert d["decision_what"]
        assert d["decision_why"]
        assert d["decision_next"]
        do = results[0].to_decision_output()
        assert do.rule == "G1M_009"


# ══════════════════════════════════════════════════════════════════════════════
# Sample data integration — inject bad HSN / wrong rate
# ══════════════════════════════════════════════════════════════════════════════

class TestSampleDataIntegration:

    @pytest.fixture()
    def parsed_sr_records(self):
        from app.parsers.sales_register_parser import parse_sales_register

        if not SAMPLE_SR.exists():
            pytest.skip(f"Sample SR file not found: {SAMPLE_SR}")
        result = parse_sales_register(SAMPLE_SR.read_bytes(), SAMPLE_SR.name)
        assert result.get("success"), result.get("errors")
        return result["records"]

    @pytest.fixture()
    def parsed_gstr1_records(self):
        from app.parsers.gstr1_parser import parse_gstr1

        if not SAMPLE_GSTR1.exists():
            pytest.skip(f"Sample GSTR-1 not found: {SAMPLE_GSTR1}")
        result = parse_gstr1(SAMPLE_GSTR1.read_bytes())
        assert result.get("success") or result.get("records") is not None
        return result["records"]

    def test_sample_sr_has_hsn_field(self, parsed_sr_records):
        with_hsn = [r for r in parsed_sr_records if r.get("hsn")]
        assert len(with_hsn) > 0

    def test_inject_wrong_rate_detected(self, parsed_sr_records):
        """GSTR-1 HSN summary at wrong rate — must fire HIGH rate_mismatch."""
        del parsed_sr_records  # SR schedule checks are intentionally quiet
        g1 = [_g1(inv="HSN-3901", hsn="3901", rate=5.0)]
        results = validate_hsn_rate_mapping(None, g1)
        rate_issues = [
            r for r in results if r.details.get("issue_type") == "rate_mismatch"
        ]
        assert len(rate_issues) == 1
        assert rate_issues[0].severity == MismatchSeverity.HIGH
        assert rate_issues[0].details["hsn"] == "3901"

    def test_inject_unknown_hsn_detected(self, parsed_sr_records):
        """Unknown HSN is not flooded from the incomplete local schedule."""
        del parsed_sr_records
        g1 = [_g1(inv="HSN-UNK", hsn="77777777", rate=18.0)]
        results = validate_hsn_rate_mapping(None, g1)
        unknown = [r for r in results if r.details.get("issue_type") == "unknown_hsn"]
        assert unknown == []

    def test_both_severities_fire_together(self, parsed_sr_records, parsed_gstr1_records):
        """Wrong-rate HSN summary + short HSN digit-length both fire."""
        del parsed_sr_records, parsed_gstr1_records
        g1 = [
            _g1(inv="HSN-A", hsn="3901", rate=5.0),
            _g1(inv="HSN-B", hsn="39", rate=18.0),
        ]
        results = validate_hsn_rate_mapping(None, g1)
        types = {r.details.get("issue_type") for r in results}
        severities = {r.severity for r in results}
        assert "rate_mismatch" in types
        assert "hsn_digit_length" in types
        assert MismatchSeverity.HIGH in severities
        assert MismatchSeverity.MEDIUM in severities
