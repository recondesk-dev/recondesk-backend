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
        "section": "b2b",
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
        records = [_sr(hsn="88888888", igst=18000)]
        results = validate_hsn_rate_mapping(records, None)
        unknown = [r for r in results if r.details.get("issue_type") == "unknown_hsn"]
        assert len(unknown) == 1
        assert unknown[0].severity == MismatchSeverity.LOW
        assert unknown[0].mismatch_type == MismatchType.HSN_RATE_ISSUE
        assert unknown[0].rule_id == "G1M_009"
        assert unknown[0].details["hsn"] == "88888888"

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
        """3901 is 18% in the reference; charging 5% must flag HIGH."""
        # 5% of 100000 paise = 5000
        records = [_sr(hsn="3901", taxable=100000, igst=5000)]
        results = validate_hsn_rate_mapping(records, None)
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
        records = [_sr(hsn="")]
        records[0]["hsn"] = None
        g1 = [_g1(hsn=None, rate=18.0)]
        results = validate_hsn_rate_mapping(records, g1)
        missing = [r for r in results if r.details.get("issue_type") == "missing_hsn"]
        assert len(missing) >= 2
        assert all(r.severity == MismatchSeverity.LOW for r in missing)

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
        records = [
            _sr(inv="A", hsn="3901", taxable=100000, igst=5000),  # wrong rate HIGH
            _sr(inv="B", hsn="88888888", taxable=100000, igst=18000),  # unknown LOW
        ]
        results = validate_hsn_rate_mapping(records, None)
        assert len(results) >= 2
        assert results[0].severity == MismatchSeverity.HIGH

    def test_to_dict_serialisation(self):
        records = [_sr(hsn="88888888", igst=18000)]
        results = validate_hsn_rate_mapping(records, None)
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
        """Force HSN 3901 at 5% — must fire HIGH rate_mismatch."""
        records = [copy.deepcopy(r) for r in parsed_sr_records]
        target = records[0]
        target["hsn"] = "3901"
        target["taxable_amount_paise"] = 100000
        target["igst_paise"] = 5000
        target["cgst_paise"] = 0
        target["sgst_paise"] = 0
        target["total_tax_paise"] = 5000

        results = validate_hsn_rate_mapping(records[:1], None)
        rate_issues = [
            r for r in results if r.details.get("issue_type") == "rate_mismatch"
        ]
        assert len(rate_issues) == 1
        assert rate_issues[0].severity == MismatchSeverity.HIGH
        assert rate_issues[0].details["hsn"] == "3901"

    def test_inject_unknown_hsn_detected(self, parsed_sr_records):
        """Force an HSN absent from the reference — must fire LOW unknown_hsn."""
        records = [copy.deepcopy(r) for r in parsed_sr_records]
        target = records[0]
        target["hsn"] = "77777777"
        target["taxable_amount_paise"] = 100000
        target["igst_paise"] = 18000
        target["total_tax_paise"] = 18000

        results = validate_hsn_rate_mapping(records[:1], None)
        unknown = [r for r in results if r.details.get("issue_type") == "unknown_hsn"]
        assert len(unknown) == 1
        assert unknown[0].severity == MismatchSeverity.LOW
        assert unknown[0].details["hsn"] == "77777777"

    def test_both_severities_fire_together(self, parsed_sr_records, parsed_gstr1_records):
        """Inject one wrong-rate and one unknown-HSN row; both severities present."""
        records = [copy.deepcopy(r) for r in parsed_sr_records[:2]]
        records[0]["hsn"] = "3901"
        records[0]["taxable_amount_paise"] = 200000
        records[0]["igst_paise"] = 10000  # 5%
        records[0]["cgst_paise"] = 0
        records[0]["sgst_paise"] = 0
        records[0]["total_tax_paise"] = 10000

        records[1]["hsn"] = "66666666"
        records[1]["taxable_amount_paise"] = 200000
        records[1]["igst_paise"] = 36000
        records[1]["total_tax_paise"] = 36000

        results = validate_hsn_rate_mapping(records, parsed_gstr1_records)
        types = {r.details.get("issue_type") for r in results}
        severities = {r.severity for r in results}
        assert "rate_mismatch" in types
        assert "unknown_hsn" in types
        assert MismatchSeverity.HIGH in severities
        assert MismatchSeverity.LOW in severities
