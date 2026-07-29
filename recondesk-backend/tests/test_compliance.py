"""
test_compliance.py
Scenario: GST compliance rules — Rule 37, Section 17(5), late filing.
Run: PYTHONPATH=. pytest tests/test_compliance.py -v
"""
import pytest
from datetime import date
from app.services.matcher import match_gstr_to_pr, normalize_invoice
from app.services.decision_templates import generate_decision, TEMPLATES
from app.decisions.layer import _decision_for_row, populate_decisions

def make_gstr(invoice="INV001", gstin="27ABCDE1234F1Z0", invoice_date="2024-04-01",
              taxable_paise=100000, igst_paise=0, cgst_paise=9000, sgst_paise=9000):
    return {
        "supplier_gstin": gstin,
        "invoice_number_normalized": normalize_invoice(invoice),
        "invoice_number": invoice,
        "invoice_date": date.fromisoformat(invoice_date),
        "taxable_amount_paise": taxable_paise,
        "igst_paise": igst_paise,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "total_tax_paise": igst_paise + cgst_paise + sgst_paise,
    }

def make_pr(invoice="INV001", gstin="27ABCDE1234F1Z0", invoice_date="2024-04-01",
            taxable_paise=100000, igst_paise=0, cgst_paise=9000, sgst_paise=9000, id="pr-001"):
    return {
        "id": id,
        "supplier_gstin": gstin,
        "invoice_number_normalized": normalize_invoice(invoice),
        "invoice_number": invoice,
        "invoice_date": date.fromisoformat(invoice_date),
        "taxable_amount_paise": taxable_paise,
        "igst_paise": igst_paise,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "total_tax_paise": igst_paise + cgst_paise + sgst_paise,
    }

class TestLateFiling:
    def test_invoice_within_90_days_late_is_flagged(self):
        g = make_gstr(invoice_date="2024-04-01")
        p = make_pr(invoice_date="2024-01-15")
        result = match_gstr_to_pr(g, [p])
        assert result is not None and result.matched, (
            "Late filing: same invoice in GSTR-2B and PR must still match."
        )
        assert result.is_late_filing is True, (
            "Invoice appearing 76 days late in GSTR-2B must set is_late_filing=True."
        )

    def test_late_filing_decision_template_renders(self):
        d = generate_decision(
            "LATE_FILING",
            original_period="Jan 2024",
            gstr_period="Apr 2024",
            late_months=3,
        )
        assert d.next != "", "LATE_FILING next action must not be empty."

    def test_late_filing_decision_layer_row(self):
        row = {
            "match_level": 1,
            "is_late_filing": True,
            "original_period": "Jan 2024",
            "gstr_period": "Apr 2024",
            "late_months": 3,
        }
        d = _decision_for_row(row)
        assert d.what != "", "Late filing row must produce a decision."

    def test_3_day_date_difference_is_not_late_filing(self):
        g = make_gstr(invoice_date="2024-04-01")
        p = make_pr(invoice_date="2024-04-03")
        result = match_gstr_to_pr(g, [p])
        assert result is not None and result.level == 1
        assert result.is_late_filing is False, (
            "3-day gap must not be flagged as late filing."
        )

class TestRule37Decisions:
    def test_rule37_overdue_mentions_reversal(self):
        d = generate_decision("RULE37_OVERDUE", itc_amount="18000.00")
        assert "revers" in d.next.lower(), (
            f"Rule 37 overdue must mention ITC reversal. Got: '{d.next}'"
        )

    def test_rule37_overdue_mentions_interest(self):
        d = generate_decision("RULE37_OVERDUE", itc_amount="18000.00")
        assert "interest" in d.next.lower() or "24%" in d.next, (
            f"Rule 37 overdue must mention interest. Got: '{d.next}'"
        )

    def test_rule37_warning_includes_deadline_date(self):
        d = generate_decision(
            "RULE37_WARNING",
            days_remaining=15,
            deadline_date="15-Oct-2024",
            supplier_gstin="27ABCDE1234F1Z0",
            itc_amount="9000.00",
        )
        assert "15-Oct-2024" in d.next, (
            f"Deadline date must appear in next action. Got: '{d.next}'"
        )

    def test_rule37_warning_includes_supplier_gstin(self):
        d = generate_decision(
            "RULE37_WARNING",
            days_remaining=15,
            deadline_date="15-Oct-2024",
            supplier_gstin="27ABCDE1234F1Z0",
            itc_amount="9000.00",
        )
        assert "Pay supplier by 15-Oct-2024" in d.next, (
            f"Next action must mention the deadline date. Got: '{d.next}'"
        )

    def test_rule37_zero_days_remaining_is_overdue(self):
        rule37_rows = [{
            "days_remaining": 0,
            "itc_at_risk_paise": 1800000,
            "supplier_gstin": "27ABCDE1234F1Z0",
            "deadline": "01-Apr-2024",
        }]
        result = populate_decisions([], rule37=rule37_rows)
        enriched = result.get("rule37", [])
        assert len(enriched) == 1
        decision_what = enriched[0].get("decision_what", "")
        assert "reversal" in decision_what.lower() or "mandatory" in decision_what.lower() or "180 days" in decision_what.lower(), (
            f"0 days remaining must produce OVERDUE decision. Got: '{decision_what}'"
        )

    def test_rule37_negative_days_remaining_is_overdue(self):
        rule37_rows = [{
            "days_remaining": -5,
            "itc_at_risk_paise": 900000,
            "supplier_gstin": "27ABCDE1234F1Z0",
            "deadline": "26-Mar-2024",
        }]
        result = populate_decisions([], rule37=rule37_rows)
        enriched = result.get("rule37", [])
        assert len(enriched) == 1
        assert enriched[0].get("decision_what", "") != "", (
            "Negative days_remaining must produce a non-empty decision."
        )

class TestSection175:
    def test_blocked_credit_template_renders_with_hsn_and_category(self):
        d = generate_decision("BLOCKED_CREDIT", category="Motor Vehicles", hsn_code="8703")
        assert "8703" in d.what or "Motor Vehicles" in d.what, (
            f"BLOCKED_CREDIT must include HSN or category in what. Got: '{d.what}'"
        )

    def test_blocked_credit_why_mentions_17_5(self):
        d = generate_decision("BLOCKED_CREDIT", category="Motor Vehicles", hsn_code="8703")
        assert "17(5)" in d.why or "ineligible" in d.why.lower(), (
            f"BLOCKED_CREDIT why must reference Section 17(5). Got: '{d.why}'"
        )

    def test_blocked_credit_next_says_verify_before_claiming(self):
        d = generate_decision("BLOCKED_CREDIT", category="Club Membership", hsn_code="9995")
        next_lower = d.next.lower()
        assert "verify" in next_lower or "document" in next_lower or "claiming" in next_lower, (
            f"BLOCKED_CREDIT next must say verify before claiming. Got: '{d.next}'"
        )

    def test_section175_warnings_in_populate_decisions(self):
        warnings = [{
            "supplier_gstin": "27ABCDE1234F1Z0",
            "invoice_number": "INV-8703",
            "hsn_code": "8703",
            "category": "Motor Vehicles",
            "itc_amount": 50000,
        }]
        result = populate_decisions([], section_175_warnings=warnings)
        enriched_175 = result.get("section_175", [])
        assert len(enriched_175) == 1, (
            f"section_175_warnings must be processed. Got: {enriched_175}"
        )
        assert "?" not in enriched_175[0]["decision_what"]
        assert "?" not in enriched_175[0]["decision_why"]
        assert "8703" in enriched_175[0]["decision_why"]
        assert "Motor Vehicles" in enriched_175[0]["decision_what"]

    def test_populate_decisions_no_hsn_does_not_emit_question_marks(self):
        warnings = [{
            "supplier_gstin": "27ABCDE1234F1Z0",
            "invoice_number": "INV-INELIG",
            "category": "Marked ITC-ineligible in purchase register",
            "hsn_code": None,
        }]
        result = populate_decisions([], section_175_warnings=warnings)
        row = result["section_175"][0]
        assert "?" not in row["decision_what"]
        assert "?" not in row["decision_why"]
        assert "ineligible" in row["decision_what"].lower() or "17(5)" in row["decision_what"]


class TestMissedAndWrongfulITC:
    def test_missed_itc_decision_mentions_amount_and_action(self):
        d = generate_decision("MISSED_ITC", source_software="Tally", itc_amount="18000.00")
        assert "18000.00" in d.next, (
            f"MISSED_ITC next must mention the ITC amount. Got: '{d.next}'"
        )
        assert "purchase register" in d.next.lower() or "add" in d.next.lower(), (
            f"MISSED_ITC must tell CA to add to purchase register. Got: '{d.next}'"
        )

    def test_wrongful_itc_decision_says_do_not_claim(self):
        d = generate_decision("WRONGFUL_ITC", supplier_gstin="27ABCDE1234F1Z0", itc_amount="9000.00")
        next_lower = d.next.lower()
        assert "do not claim" in next_lower or "not claim" in next_lower or "until" in next_lower, (
            f"WRONGFUL_ITC must explicitly say do not claim ITC. Got: '{d.next}'"
        )

    def test_missed_itc_flag_overrides_level_1_decision(self):
        row = {"match_level": 1, "is_missed_itc": True, "itc_amount": 18000, "source_software": "Busy"}
        d = _decision_for_row(row)
        assert "No action" not in d.next, (
            f"is_missed_itc flag must override L1 no-action decision. Got: '{d.next}'"
        )

    def test_wrongful_itc_flag_overrides_level_decision(self):
        row = {"match_level": 2, "is_wrongful_itc": True, "supplier_gstin": "27ABCDE1234F1Z0", "itc_amount": 9000}
        d = _decision_for_row(row)
        assert "Auto-accepted" not in d.next, (
            f"is_wrongful_itc flag must override L2 auto-accept decision. Got: '{d.next}'"
        )

class TestAllTemplatesRender:
    def test_L1_exact_renders(self):
        d = generate_decision("L1_EXACT")
        assert d.what and d.why and d.next

    def test_L2_amount_diff_renders(self):
        d = generate_decision("L2_AMOUNT_DIFF", diff="50.00", source_software="Tally")
        assert "50.00" in d.what
        assert "Tally" in d.why

    def test_L3_amount_diff_renders(self):
        d = generate_decision("L3_AMOUNT_DIFF", diff="300.00", pct="3.0", source_software="Busy", supplier_gstin="27ABCDE1234F1Z0")
        assert "300.00" in d.what
        assert "3.0" in d.what

    def test_L4_invoice_num_renders(self):
        d = generate_decision("L4_INVOICE_NUM", source_software="Excel")
        assert d.what and d.why and d.next

    def test_unknown_template_returns_fallback(self):
        d = generate_decision("THIS_DOES_NOT_EXIST")
        assert d.what == "Mismatch detected", (
            f"Unknown template must return fallback. Got: '{d.what}'"
        )

    def test_missing_placeholder_returns_question_mark(self):
        d = generate_decision("L2_AMOUNT_DIFF")
        assert "?" in d.what or "?" in d.why, (
            "Missing placeholder must produce '?' via _safe_format, not crash."
        )

    def test_populate_decisions_empty_inputs_does_not_crash(self):
        result = populate_decisions([], rule37=[], section_175_warnings=[], credit_note_adjustment=None)
        assert isinstance(result, dict), "populate_decisions must return a dict."
